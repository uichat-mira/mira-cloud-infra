"""Offline security and behavior tests: no Docker, root or Cloud Auth needed."""
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location("dc_control_server", Path(__file__).with_name("server.py"))
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)


class PolicyTests(unittest.TestCase):
    def test_preset_validation(self):
        self.assertEqual(dc.validate_policy(dict(dc.DEFAULT_POLICY)), dc.DEFAULT_POLICY)
        for changed in (
            {"durationMinutes": 0}, {"durationMinutes": 1440},
            {"memoryMiB": 4096}, {"cpuPercent": 0},
            {"minAvailableMiB": False},
            {"arbitraryCommand": "rm -rf /"},
        ):
            with self.subTest(changed=changed):
                value = dict(dc.DEFAULT_POLICY)
                value.update(changed)
                with self.assertRaises(dc.ControlError):
                    dc.validate_policy(value)

    def test_policy_persistence_is_atomic(self):
        with tempfile.TemporaryDirectory() as td, patch.object(dc, "STATE_DIR", Path(td)):
            data = dict(dc.DEFAULT_POLICY, durationMinutes=60)
            dc.atomic_json("policy.json", data)
            self.assertEqual(dc.policy(), data)
            self.assertFalse((Path(td) / "policy.json.tmp").exists())

    def test_fixed_shell_free_launch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "dc-user"
            auth = home / ".desktop-commander-device"
            auth.mkdir(parents=True)
            (auth / "device.json").write_text("{}")
            node = root / "node"
            entry = root / "entry.js"
            node.write_text("")
            entry.write_text("")
            service_active = {"v": False}
            executed = []
            def fake_run(args, **_):
                executed.append(args)
                if args[0] == "systemd-run":
                    service_active["v"] = True
                return type("Result", (), {"returncode": 0, "stdout": ""})()
            def fake_active(unit):
                return unit == dc.UNIT and service_active["v"]
            with (patch.object(dc, "STATE_DIR", root / "state"),
                  patch.object(dc, "NODE", str(node)),
                  patch.object(dc, "ENTRY", str(entry)),
                  patch.object(dc, "DEVICE_HOME", str(home)),
                  patch.object(dc, "run", fake_run),
                  patch.object(dc, "active", fake_active)):
                result = dc.start_session()
                self.assertTrue(result["running"])
                launch = next(args for args in executed if args[0] == "systemd-run")
                self.assertIn("RuntimeMaxSec=1800", launch)
                self.assertIn("MemoryMax=384M", launch)
                self.assertIn("CPUQuota=50%", launch)
                self.assertIn("SupplementaryGroups=docker", launch)
                self.assertEqual(launch[-3:], [str(node), str(entry), "remote"])
                self.assertNotIn("sh", launch)
                with self.assertRaises(dc.ControlError) as ctx:
                    dc.start_session()
                self.assertEqual(ctx.exception.code, 409)

    def test_stop_only_fixed_unit_names(self):
        ran = []
        def fake_run(args, **_):
            ran.append(args)
            return type("Result", (), {"returncode": 0, "stdout": ""})()
        with (patch.object(dc, "run", fake_run),
              patch.object(dc, "active", lambda _: True),
              patch.object(dc, "status", lambda: {"running": False})):
            self.assertFalse(dc.stop_session()["running"])
        self.assertEqual([cmd[2] for cmd in ran], [dc.UNIT, *dc.LEGACY_UNITS])


class AuthenticationTests(unittest.TestCase):
    class Response:
        status = 200
        def __init__(self, account):
            self.payload = json.dumps({"account": account, "expiresAt": "2030-01-01T00:00:00Z"}).encode()
        def read(self, _limit):
            return self.payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    def test_cloud_auth_verifies_exact_owner_id(self):
        token = "Bearer mcs_v1." + "A" * 22 + "." + "b" * 43
        with patch.object(dc, "OWNER_ID", "owner_123"):
            with patch.object(dc, "urlopen", return_value=self.Response({"id": "owner_123"})) as remote:
                account = dc.get_account(token)
                self.assertEqual(account["id"], "owner_123")
                self.assertEqual(remote.call_args.args[0].full_url, dc.AUTH_URL)
                self.assertEqual(remote.call_args.args[0].get_header("Authorization"), token)
            with patch.object(dc, "urlopen", return_value=self.Response({"id": "other_456"})):
                with self.assertRaises(dc.ControlError) as ctx:
                    dc.get_account(token)
                self.assertEqual(ctx.exception.code, 403)

    def test_unconfigured_owner_and_invalid_bearer_fail_closed(self):
        with patch.object(dc, "OWNER_ID", ""):
            with self.assertRaises(dc.ControlError) as ctx:
                dc.get_account("Bearer whatever")
            self.assertEqual(ctx.exception.code, 503)
        with patch.object(dc, "OWNER_ID", "owner_123"):
            with self.assertRaises(dc.ControlError) as ctx:
                dc.get_account("Bearer invalid")
            self.assertEqual(ctx.exception.code, 401)

    def test_cloud_auth_network_failure_denies_access(self):
        token = "Bearer mcs_v1." + "A" * 22 + "." + "b" * 43
        from urllib.error import URLError
        with patch.object(dc, "OWNER_ID", "owner_123"), patch.object(dc, "urlopen", side_effect=URLError("offline")):
            with self.assertRaises(dc.ControlError) as ctx:
                dc.get_account(token)
            self.assertEqual(ctx.exception.code, 503)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_patch = patch.object(dc, "STATE_DIR", Path(self.temp.name))
        self.state_patch.start()
        self.auth_patch = patch.object(dc, "get_account", side_effect=self.fake_auth)
        self.auth_patch.start()
        def fake_helper(action, payload=None):
            if action == "policy":
                dc.atomic_json("policy.json", dc.validate_policy(payload))
            if action not in ("status", "policy"):
                raise AssertionError("unexpected privileged action")
            return {"running": False, "policy": dc.policy(), "memoryBytes": None}
        self.status_patch = patch.object(dc, "call_helper", side_effect=fake_helper)
        self.status_patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), dc.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=3)
        self.httpd.server_close()
        self.status_patch.stop()
        self.auth_patch.stop()
        self.state_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def fake_auth(bearer):
        if bearer != "Bearer authorised":
            raise dc.ControlError(401, "not signed in")
        return {"id": "owner"}

    def call(self, path, *, method="GET", payload=None, token="Bearer authorised", origin=None):
        headers = {"Authorization": token}
        if origin is not None:
            headers["Origin"] = origin
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, headers=headers,
                          method=method,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urlopen(request, timeout=4) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_ui_is_static_and_contains_no_token(self):
        code, data = self.call("/dc/", token="")
        self.assertEqual(code, 200)
        self.assertIn(b"DC", data)
        self.assertNotIn(b"mcs_v1", data)

    def test_api_requires_session(self):
        self.assertEqual(self.call("/dc/api/status", token="")[0], 401)

    def test_api_rejects_cross_site_and_unknown_verbs(self):
        self.assertEqual(self.call("/dc/api/start", method="POST", payload={}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.call("/dc/api/start", method="POST", payload={})[0], 403)
        self.assertEqual(self.call("/dc/api/command", method="POST", payload={"cmd": "docker rm"}, origin=dc.ORIGIN)[0], 404)

    def test_save_rejects_invalid_policies(self):
        self.assertEqual(self.call("/dc/api/policy", method="PUT", payload={"durationMinutes": 300}, origin=dc.ORIGIN)[0], 400)
        self.assertEqual(self.call("/dc/api/status")[0], 200)
        ok, _ = self.call("/dc/api/policy", method="PUT", payload=dict(dc.DEFAULT_POLICY), origin=dc.ORIGIN)
        self.assertEqual(ok, 200)
        self.assertEqual(dc.policy(), dc.DEFAULT_POLICY)


    def test_frontend_never_invokes_root_operation_directly(self):
        self.call("/dc/api/status")
        self.assertEqual(self.status_patch.call_args.args[0], "status")
        self.assertEqual(self.call("/dc/api/start", method="POST", payload={"cmd": "id"}, origin=dc.ORIGIN)[0], 404)

    def test_start_does_not_accept_command_payload(self):
        self.assertEqual(self.call("/dc/api/start", method="POST", payload={"cmd": "id"}, origin=dc.ORIGIN)[0], 404)

if __name__ == "__main__":
    unittest.main()
