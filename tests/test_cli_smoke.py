"""Smoke tests for chaincraft CLI entry points."""

import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestCLISmoke(unittest.TestCase):
    def test_chaincraft_cli_help(self):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "chaincraft_cli.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Chaincraft CLI", result.stdout)


if __name__ == "__main__":
    unittest.main()
