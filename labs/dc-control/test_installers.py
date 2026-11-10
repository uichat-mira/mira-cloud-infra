"""Compile reviewed bootstrap code offline without running privileged installation."""
import unittest
import importlib.util
import tempfile
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

    def test_installers_compile_without_executing(self):
        for file in ("install_tencent_node.py", "install_aliyun_target.py"):
            with self.subTest(file=file):
                compile((ROOT / file).read_text(encoding="utf-8"), str(ROOT / file), "exec")


if __name__ == "__main__":
    unittest.main()
