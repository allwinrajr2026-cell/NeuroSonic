"""Runs the browser-logic unit tests (tests/js/*.test.mjs) with Node's built-in test runner, if Node exists."""
import shutil
import subprocess
import unittest

from tests._common import ROOT

NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node not installed (browser-logic tests skipped)")
class TestWebLogic(unittest.TestCase):
    def test_node_unit_tests(self):
        files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.mjs"))
        self.assertTrue(files)
        r = subprocess.run([NODE, "--test", *files], capture_output=True, text=True, timeout=120, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
