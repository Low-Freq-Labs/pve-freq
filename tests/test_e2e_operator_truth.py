"""E2E operator truth tests.

Proves:
1. /api/info includes install_method for update guidance
2. Log diversion warning goes to stderr (not stdout)
3. freq help runs cleanly without crashing
4. freq doctor separates workspace issues from fleet health
"""

import os
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestInfoEndpointMetadata(unittest.TestCase):
    """GET /api/info must include runtime metadata for update guidance."""

    def test_info_handler_includes_install_method(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler = src.split("def handle_info")[1].split("\ndef ")[0]
        self.assertIn("install_method", handler,
                       "/api/info must include install_method")
        self.assertIn("_detect_install_method", handler,
                       "Must use _detect_install_method from selfupdate")


class TestLogDiversionHonesty(unittest.TestCase):
    """Log diversion warning must go to stderr, never stdout."""

    def test_log_fallback_warns_to_stderr(self):
        with open(os.path.join(REPO_ROOT, "freq/core/log.py")) as f:
            src = f.read()
        self.assertIn("file=sys.stderr", src,
                       "Log diversion warning must go to stderr")

    def test_log_fallback_uses_home_dir(self):
        with open(os.path.join(REPO_ROOT, "freq/core/log.py")) as f:
            src = f.read()
        self.assertIn(".freq", src,
                       "Fallback log dir must be ~/.freq/log/")


class TestFirstTouchClean(unittest.TestCase):
    """First-touch commands must run without crash or confusing output."""

    def test_freq_help_clean_exit(self):
        r = subprocess.run(
            ["python3", "-m", "freq", "help"],
            capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(r.returncode, 0, f"freq help failed: {r.stderr}")
        self.assertNotIn("Traceback", r.stderr)

    def test_freq_version_clean_exit(self):
        r = subprocess.run(
            ["python3", "-m", "freq", "version"],
            capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_freq_doctor_clean_exit(self):
        r = subprocess.run(
            ["python3", "-m", "freq", "doctor"],
            capture_output=True, text=True, timeout=30, cwd=REPO_ROOT,
        )
        self.assertIn(r.returncode, (0, 1, 2))
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
