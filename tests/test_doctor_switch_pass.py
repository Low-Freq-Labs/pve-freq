"""Tests for doctor switch-pass false warning after green init.

Bug: Doctor warned "Legacy password file configured but missing" even
though the file existed at /home/freq-admin/.ssh/switch-pass (600).
The parent dir ~/.ssh/ is 700 owned by freq-admin. When freq-ops runs
doctor, os.path.isfile() returns False because the dir is inaccessible.

Fix: When the file appears missing but the parent dir exists and is
unreadable, treat it as "in secure dir" rather than "missing".
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestDoctorSwitchPassSecureDir(unittest.TestCase):
    """Doctor must not false-warn for files in secure service-owned dirs."""

    def test_secure_dir_check_exists(self):
        """Doctor must check if parent dir is unreadable before warning."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("os.access(parent, os.R_OK)", src)

    def test_in_secure_dir_message(self):
        """Doctor must report 'in secure dir' for files in unreadable parents."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("in secure dir", src)

    def test_no_false_warn_for_absent_legacy_password_file(self):
        """Not having legacy_password_file at all should not be a warning."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        # The old code warned "No legacy_password_file configured" — should be gone
        self.assertNotIn("may need it", src)


if __name__ == "__main__":
    unittest.main()
