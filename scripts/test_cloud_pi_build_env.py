#!/usr/bin/env python3
"""No credential or network access is needed to test the env builder."""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
BUILDER = Path(__file__).with_name("cloud-pi-build-env.py")
class Tests(unittest.TestCase):
    def env(self):
        return {**os.environ, "CLOUD_PI_FEISHU_APP_ID": "cli_test1234",
                "CLOUD_PI_FEISHU_APP_SECRET": "fake-secret-1",
                "CLOUD_PI_WECOM_BOT_ID": "fake-bot",
                "CLOUD_PI_WECOM_BOT_SECRET": "fake-secret-2",
                "CLOUD_PI_WECOM_BOT_NAME": "测试机器人",
                "CLOUD_PI_MODEL_API_KEY": "fake-key",
                "CLOUD_PI_OWNER_ACCOUNT_ID": "account-test",
                "CLOUD_PI_MODEL_ID": "deepseek-v4.1-flash-od"}
    def run_builder(self, env):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "agent.env"
            run = subprocess.run([sys.executable, str(BUILDER), str(output)],
                                 env=env, capture_output=True, text=True)
            return run, output.read_text() if output.exists() else None, (
                stat.S_IMODE(output.stat().st_mode) if output.exists() else None)
    def test_valid_private_dual_channel(self):
        proc, data, mode = self.run_builder(self.env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(mode, 0o600)
        self.assertIn("CLOUD_AGENT_CHANNELS=feishu,wecom", data)
        self.assertIn("CLOUD_PI_MODEL_BASE_URL=http://127.0.0.1:3000/v1", data)
        self.assertNotIn("fake-secret", proc.stdout + proc.stderr)
    def test_refuses_implicit_model_fallback(self):
        env = self.env()
        del env["CLOUD_PI_MODEL_ID"]
        proc, data, _ = self.run_builder(env)
        self.assertEqual(proc.returncode, 2)
        self.assertIsNone(data)
        self.assertIn("CLOUD_PI_MODEL_ID", proc.stderr)
    def test_preserves_explicit_model_alias(self):
        proc, data, _ = self.run_builder(self.env())
        self.assertEqual(proc.returncode, 0)
        self.assertIn("CLOUD_PI_MODEL_ID=deepseek-v4.1-flash-od", data)
    def test_missing_does_not_print_secrets(self):
        env = self.env()
        del env["CLOUD_PI_WECOM_BOT_SECRET"]
        proc, data, _ = self.run_builder(env)
        self.assertEqual(proc.returncode, 2)
        self.assertIsNone(data)
        self.assertIn("CLOUD_PI_WECOM_BOT_SECRET", proc.stderr)
        self.assertNotIn("fake-secret", proc.stderr)
    def test_rejects_newline_in_secret(self):
        env = self.env()
        env["CLOUD_PI_MODEL_API_KEY"] = "fake\nCLOUD_AGENT_CHANNELS=none"
        proc, data, _ = self.run_builder(env)
        self.assertEqual(proc.returncode, 2)
        self.assertIsNone(data)
if __name__ == "__main__":
    unittest.main()
