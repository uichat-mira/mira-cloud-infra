"""OPS-027: local-only tests for the pinned, fixed-target SSH call."""
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("remote_node", Path(__file__).with_name("remote_node.py"))
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


def reply(policy=None, **updates):
    data = {
        "running": False,
        "legacyRunning": False,
        "remainingSeconds": None,
        "memoryBytes": None,
        "policy": policy or {
            "durationMinutes": 30, "memoryMiB": 384,
            "cpuPercent": 50, "minAvailableMiB": 512,
        },
        "at": "2026-11-10T12:00:00+00:00",
    }
    data.update(updates)
    return json.dumps({"ok": True, "data": data})


class RemoteBoundaryTests(unittest.TestCase):
    def test_fixed_user_host_and_pinned_identity_with_no_shell(self):
        calls = []
        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, reply(), "")
        with patch.object(remote, "target", return_value=("192.0.2.45", 22)), patch.object(remote.subprocess, "run", side_effect=fake_run):
            value = remote.request("status", {})
            self.assertFalse(value["running"])
        argv, kwargs = calls[0]
        self.assertEqual(argv[0], "/usr/bin/ssh")
        self.assertIn("miraops@192.0.2.45", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("ClearAllForwardings=yes", argv)
        self.assertNotIn("bash", argv)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(json.loads(kwargs["input"]), {"action": "status", "payload": {}})

    def test_reject_arbitrary_command_or_target_data(self):
        for action, payload in (("exec", {}), ("start", {"unit": "sshd"}), ("stop", {"host": "1.2.3.4"})):
            with self.subTest(action=action, payload=payload), self.assertRaises(remote.RemoteError) as ctx:
                remote.request(action, payload)
            self.assertEqual(ctx.exception.code, 400)

    def test_connection_failure_and_malformed_response_fail_closed(self):
        with patch.object(remote, "target", return_value=("192.0.2.45", 22)):
            with patch.object(remote.subprocess, "run", return_value=subprocess.CompletedProcess([], 255, "", "")):
                with self.assertRaises(remote.RemoteError) as ctx:
                    remote.request("status", {})
                self.assertEqual(ctx.exception.code, 503)
            with patch.object(remote.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, reply(policy={"durationMinutes": 30}), "")):
                with self.assertRaises(remote.RemoteError) as ctx:
                    remote.request("status", {})
                self.assertEqual(ctx.exception.code, 503)

    def test_missing_root_only_credentials_fail_closed(self):
        with patch.object(remote, "CONFIG_DIR", Path("/nonexistent/dc-control-path")):
            with self.assertRaises(remote.RemoteError) as ctx:
                remote.target()
        self.assertEqual(ctx.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
