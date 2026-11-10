"""OPS-027: offline boundary tests for the unprivileged Tencent node agent."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("remote_agent", Path(__file__).with_name("remote_agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class PolicyTests(unittest.TestCase):
    def test_exact_presets_only(self):
        self.assertEqual(agent.validate_policy(dict(agent.DEFAULT_POLICY)), agent.DEFAULT_POLICY)
        for change in (
            {"durationMinutes": 0}, {"durationMinutes": 999},
            {"memoryMiB": 9999}, {"cpuPercent": 200},
            {"minAvailableMiB": False}, {"unit": "ssh.service"},
        ):
            policy = dict(agent.DEFAULT_POLICY, **change)
            with self.subTest(change=change), self.assertRaises(agent.ControlError):
                agent.validate_policy(policy)

    def test_fixed_actions_reject_command_and_unknown_keys(self):
        with self.assertRaises(agent.ControlError) as ctx:
            agent.dispatch({"action": "exec", "payload": {"cmd": "id"}})
        self.assertEqual(ctx.exception.code, 404)
        for payload in ({"cmd": "id"}, {"unit": "other.service"}, {"node": "aliyun"}):
            with self.assertRaises(agent.ControlError):
                agent.dispatch({"action": "start", "payload": payload})

    def test_wrong_execution_user_rejected(self):
        with patch.object(agent.os, "geteuid", return_value=-1):
            with self.assertRaises(agent.ControlError) as ctx:
                agent.require_user()
        self.assertEqual(ctx.exception.code, 403)
        with patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "bash"}):
            with patch.object(agent.os, "geteuid", return_value=agent.pwd.getpwnam(agent.USER).pw_uid if agent.USER in (p.pw_name for p in __import__("pwd").getpwall()) else -1):
                with self.assertRaises(agent.ControlError):
                    agent.require_user()

    def test_atomic_policy_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(agent, "state_dir", return_value=Path(directory)):
            agent.atomic_json("policy.json", dict(agent.DEFAULT_POLICY, durationMinutes=60))
            self.assertEqual(agent.policy()["durationMinutes"], 60)
            self.assertEqual((Path(directory) / "policy.json").stat().st_mode & 0o777, 0o600)


class UserServiceTests(unittest.TestCase):
    def test_launch_has_fixed_user_unit_no_shell_no_auto_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".desktop-commander-device").mkdir()
            (root / ".desktop-commander-device/device.json").write_text("{}")
            node = root / "node"
            entry = root / "entry.js"
            node.touch()
            entry.touch()
            commands = []
            running = {"value": False}

            def fake_command(args, **kwargs):
                commands.append(args)
                if args[0] == "systemd-run":
                    running["value"] = True
                return subprocess.CompletedProcess(args, 0, "", "")

            with (
                patch.object(agent, "home", return_value=root),
                patch.object(agent, "state_dir", return_value=root / "state"),
                patch.object(agent, "NODE", str(node)),
                patch.object(agent, "ENTRY", str(entry)),
                patch.object(agent, "available_memory_mib", return_value=2048),
                patch.object(agent, "unmanaged_process", return_value=False),
                patch.object(agent, "active", side_effect=lambda: running["value"]),
                patch.object(agent, "memory_current", return_value=1024),
                patch.object(agent, "command", side_effect=fake_command),
            ):
                result = agent.start()
                self.assertTrue(result["running"])
                self.assertGreater(result["remainingSeconds"], 0)
                launch = next(args for args in commands if args[0] == "systemd-run")
                self.assertIn("--user", launch)
                self.assertIn("RuntimeMaxSec=1800", launch)
                self.assertIn("MemoryMax=384M", launch)
                self.assertIn("CPUQuota=50%", launch)
                self.assertIn("Restart=no", launch)
                self.assertEqual(launch[-3:], [str(node), str(entry), "remote"])
                self.assertNotIn("/bin/sh", launch)
                with self.assertRaises(agent.ControlError) as ctx:
                    agent.start()
                self.assertEqual(ctx.exception.code, 409)

    def test_unmanaged_existing_dc_is_never_killed(self):
        with patch.object(agent, "active", return_value=False), patch.object(agent, "unmanaged_process", return_value=True):
            with self.assertRaises(agent.ControlError) as ctx:
                agent.stop()
            self.assertEqual(ctx.exception.code, 409)
            with self.assertRaises(agent.ControlError) as ctx:
                agent.start()
            self.assertEqual(ctx.exception.code, 409)

    def test_fail_closed_without_user_bus(self):
        with patch.object(agent, "user_env", side_effect=agent.ControlError(503, "no user bus")):
            with self.assertRaises(agent.ControlError) as ctx:
                agent.active()
        self.assertEqual(ctx.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
