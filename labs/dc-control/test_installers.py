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


if __name__ == "__main__":
    unittest.main()
