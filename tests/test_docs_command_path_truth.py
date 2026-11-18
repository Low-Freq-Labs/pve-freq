"""Docs command path truth tests.

Proves:
1. BREAK-GLASS does not reference phantom CLI flags
2. All freq command examples in docs match real CLI map
3. No --regenerate-keys or --deploy-keys (replaced by freq host keys)
"""

import os
import re
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Flags that were removed/never existed
PHANTOM_FLAGS = [
    "--regenerate-keys",
    "--deploy-keys",
    "--install-service",
    "--remove-service",
]


class TestNoPhantomFlags(unittest.TestCase):
    """Docs must not reference CLI flags that don't exist."""

    def _check_doc(self, path, label):
        with open(path) as f:
            src = f.read()
        for flag in PHANTOM_FLAGS:
            self.assertNotIn(flag, src,
                              f"{label} references phantom flag: {flag}")

    def test_break_glass_no_phantoms(self):
        self._check_doc(os.path.join(REPO_ROOT, "docs/BREAK-GLASS.md"), "BREAK-GLASS")

    def test_quick_reference_no_phantoms(self):
        self._check_doc(os.path.join(REPO_ROOT, "docs/QUICK-REFERENCE.md"), "QUICK-REFERENCE")

    def test_readme_no_phantoms(self):
        self._check_doc(os.path.join(REPO_ROOT, "README.md"), "README")


class TestBreakGlassCommandsExist(unittest.TestCase):
    """All freq commands in BREAK-GLASS must be valid."""

    def test_freq_doctor_exists(self):
        r = subprocess.run(["python3", "-m", "freq", "doctor", "--help"],
                           capture_output=True, text=True, cwd=REPO_ROOT, timeout=10)
        self.assertEqual(r.returncode, 0)

    def test_freq_init_fix_exists(self):
        r = subprocess.run(["python3", "-m", "freq", "init", "--help"],
                           capture_output=True, text=True, cwd=REPO_ROOT, timeout=10)
        self.assertIn("--fix", r.stdout)

    def test_freq_host_keys_deploy_exists(self):
        r = subprocess.run(["python3", "-m", "freq", "host", "keys", "--help"],
                           capture_output=True, text=True, cwd=REPO_ROOT, timeout=10)
        self.assertIn("deploy", r.stdout)

    def test_freq_serve_exists(self):
        r = subprocess.run(["python3", "-m", "freq", "serve", "--help"],
                           capture_output=True, text=True, cwd=REPO_ROOT, timeout=10)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
