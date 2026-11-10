"""Compile reviewed bootstrap code offline without running privileged installation."""
import unittest
from pathlib import Path

ROOT = Path(__file__).parent


class BootstrapSourceTests(unittest.TestCase):
    def test_installers_compile_without_executing(self):
        for file in ("install_tencent_node.py", "install_aliyun_target.py"):
            with self.subTest(file=file):
                compile((ROOT / file).read_text(encoding="utf-8"), str(ROOT / file), "exec")


if __name__ == "__main__":
    unittest.main()
