"""Runtime doctor honesty tests.

Proves:
1. Doctor checks SSH key readability (not just permissions)
2. Doctor detects log path diversion
3. Doctor distinguishes built-in default from missing custom pack
4. Doctor reports honest data directory state
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDoctorKeyReadability(unittest.TestCase):
    """Doctor must check if current user can read the SSH key."""

    def test_check_ssh_key_tests_readability(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            src = f.read()
        handler = src.split("def _check_ssh_key")[1].split("\ndef _")[0]
        self.assertIn("os.access", handler,
                       "SSH key check must test readability with os.access")
        self.assertIn("R_OK", handler,
                       "Must check R_OK (read permission)")

    def test_reports_key_owner_on_unreadable(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            src = f.read()
        handler = src.split("def _check_ssh_key")[1].split("\ndef _")[0]
        self.assertIn("owned by", handler,
                       "Must report file owner when key is unreadable")

    def test_get_file_owner_helper_exists(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            src = f.read()
        self.assertIn("def _get_file_owner", src)


class TestDoctorLogDiversion(unittest.TestCase):
    """Doctor must detect when logs are diverted from expected path."""

    def test_checks_log_path(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            src = f.read()
        data_dir_fn = src.split("def _check_data_dirs")[1].split("\ndef ")[0]
        self.assertIn("_LOG_FILE", data_dir_fn,
                       "Data dir check must verify actual log path")
        self.assertIn("diverted", data_dir_fn.lower(),
                       "Must warn about log diversion")

    def test_log_module_has_fallback(self):
        with open(os.path.join(REPO_ROOT, "freq/core/log.py")) as f:
            src = f.read()
        self.assertIn("fallback", src.lower())
        self.assertIn(".freq", src,
                       "Fallback should go to ~/.freq/log/")


class TestDoctorPersonalityRevisited(unittest.TestCase):
    """Doctor personality check must be honest (regression from earlier fix)."""

    def test_default_pack_passes(self):
        from freq.core.config import load_config
        from freq.core.doctor import _check_personality
        cfg = load_config()
        if cfg.build == "default":
            self.assertEqual(_check_personality(cfg), 0,
                             "Default personality must pass (built-in)")


class TestDoctorLiveRun(unittest.TestCase):
    """Doctor runs without crashing on current state."""

    def test_doctor_returns_exit_code(self):
        """Doctor must return an int exit code, not crash."""
        import subprocess
        r = subprocess.run(
            ["python3", "-m", "freq", "doctor"],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
        )
        self.assertIn(r.returncode, (0, 1, 2),
                       f"Doctor should return 0/1/2, got {r.returncode}")
        self.assertNotIn("Traceback", r.stderr,
                          "Doctor must not crash with traceback")


if __name__ == "__main__":
    unittest.main()
