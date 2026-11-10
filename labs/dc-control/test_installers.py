"""Compile reviewed bootstrap code offline without running privileged installation."""
import unittest
import importlib.util
import tempfile
import os
import stat
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).parent


class BootstrapSourceTests(unittest.TestCase):
    def test_reject_world_writable_release_ancestors(self):
        module_path = ROOT / "install_tencent_node.py"
        spec = importlib.util.spec_from_file_location("install_tencent_node_test", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "remote_agent.py"
            candidate.write_text("# reviewed\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                module.require_secure_root_path(candidate)

    def test_restrictive_umask_package_is_readable_without_group_write(self):
        module_path = ROOT / "install_tencent_node.py"
        spec = importlib.util.spec_from_file_location("install_tencent_node_permissions", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent"
            nested = root / "node_modules" / "package"
            nested.mkdir(parents=True)
            entry = nested / "index.js"
            entry.write_text("console.log('ok')", encoding="utf-8")
            for item in (root, nested.parent, nested):
                item.chmod(0o700)
            entry.chmod(0o600)
            # A local unprivileged CI worker cannot chown to uid 0; only the
            # metadata operation is stubbed, chmod is applied for real.
            with patch.object(module.os, "chown"):
                module.make_agent_group_readable(root, os.getgid())
            self.assertEqual(stat.S_IMODE(nested.stat().st_mode) & 0o070, 0o050)
            self.assertEqual(stat.S_IMODE(entry.stat().st_mode) & 0o070, 0o040)
            self.assertFalse(stat.S_IMODE(entry.stat().st_mode) & 0o020)

    def test_installers_compile_without_executing(self):
        for file in ("install_tencent_node.py", "install_aliyun_target.py"):
            with self.subTest(file=file):
                compile((ROOT / file).read_text(encoding="utf-8"), str(ROOT / file), "exec")



    def test_prod_installer_requires_explicit_account_owner(self):
        """Regression for #118: another allowed account must not block the configured owner."""
        import contextlib
        import io
        import sqlite3

        script = (ROOT / "install-prod.sh").read_text(encoding="utf-8")
        self.assertIn('[[ -n "${MIRA_DC_CONTROL_OWNER_USERNAME:-}" ]]', script)
        self.assertNotIn("SELECT id FROM accounts WHERE is_allowed=1 AND disabled_at IS NULL", script)
        self.assertIn("username_normalized=? AND is_allowed=1 AND disabled_at IS NULL", script)
        self.assertIn("DC_CONTROL_EXPLICIT_OWNER_SELECTED=YES", script)
        snippet = script.split("OWNER_ID=\"$(python3 - <<'PY'\\n".replace("\\n", "\n"), 1)[1].split("\nPY\n", 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            db_path = str(Path(temp) / "accounts.sqlite")
            original_connect = sqlite3.connect
            db = original_connect(db_path)
            db.execute("CREATE TABLE accounts (id TEXT, username_normalized TEXT, is_allowed INTEGER, disabled_at TEXT)")
            db.executemany("INSERT INTO accounts VALUES (?, ?, ?, ?)", [
                ("tomz-account", "tomz", 1, None),
                ("other-account", "other", 1, None),
                ("blocked-account", "blocked", 0, None),
                ("disabled-account", "disabled", 1, "2026-01-01"),
            ])
            db.commit()
            db.close()

            def test_connect(*_args, **_kwargs):
                return original_connect(db_path)

            for username, expected in (("tomz", "tomz-account"), ("OTHER", "other-account")):
                output = io.StringIO()
                with patch.dict(os.environ, {"MIRA_DC_CONTROL_OWNER_USERNAME": username}):
                    with patch("sqlite3.connect", side_effect=test_connect):
                        with contextlib.redirect_stdout(output):
                            exec(compile(snippet, "<owner-lookup>", "exec"), {})
                self.assertEqual(output.getvalue().strip(), expected)
            for username in ("blocked", "disabled", "missing"):
                with patch.dict(os.environ, {"MIRA_DC_CONTROL_OWNER_USERNAME": username}):
                    with patch("sqlite3.connect", side_effect=test_connect):
                        with self.assertRaises(SystemExit):
                            exec(compile(snippet, "<owner-lookup>", "exec"), {})

    def test_prod_installer_retries_loopback_readiness(self):
        script = (ROOT / "install-prod.sh").read_text(encoding="utf-8")
        self.assertIn("for attempt in $(seq 1 25)", script)
        self.assertIn("DC_CONTROL_LOCAL_READY_FAILED_HTTP", script)
        self.assertIn("remote_node.py", script)

if __name__ == "__main__":
    unittest.main()
