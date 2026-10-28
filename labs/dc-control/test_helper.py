"""Ensure the privileged helper cannot be invoked directly by the HTTP process."""
import json
import subprocess
import sys
import unittest
from pathlib import Path


class PrivilegeBoundaryTests(unittest.TestCase):
    def test_direct_unprivileged_invocation_rejected(self):
        # This test runs on an unprivileged GitHub Actions runner and must not
        # attempt systemd. The helper rejects before processing the command.
        helper = Path(__file__).with_name("helper.py")
        r = subprocess.run(
            [sys.executable, str(helper)],
            input=json.dumps({"action": "start", "payload": {}}),
            text=True, capture_output=True, check=True, timeout=3,
        )
        result = json.loads(r.stdout)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], 403)


if __name__ == "__main__":
    unittest.main()
