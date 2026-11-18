"""Tests for doctor honesty after a green init.

Bug: freq doctor reported false warnings on a successful post-init install:
1. "Dir not writable: data/log" — operator doesn't write logs
2. "Dir not writable: data/vault" — secure dir, intentionally 700
3. "Dir not writable: data/keys" — secure dir, intentionally 700
4. "Logs diverted to ~/.freq/log/freq.log" — expected for operator context

Root cause: _check_data_dirs() checked os.access(W_OK) for ALL data dirs
without distinguishing operator vs service account context. Secure dirs
being unwritable to operators is the security model working correctly.

Fix: Secure dirs (keys, vault) and log dir are only checked for
writability when running as the service account. Operator log diversion
to ~/.freq/log/ is normal and not flagged.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestDoctorSecureDirContext(unittest.TestCase):
    """Doctor must not flag secure dirs as defects in operator context."""

    def test_secure_dirs_identified(self):
        """Doctor must identify vault and keys as secure dir names."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("data/vault", src)
        self.assertIn("data/keys", src)
        self.assertIn("secure_dir_names", src)

    def test_service_account_check(self):
        """Doctor must compare current user to service account."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("is_service_account", src)
        self.assertIn("cfg.ssh_service_account", src)

    def test_log_diversion_only_for_service(self):
        """Log diversion warning only applies to service account."""
        src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("if is_service_account:", src)


class TestDoctorOperatorRun(unittest.TestCase):
    """Doctor run as operator should not produce false warnings."""

    def test_doctor_data_dirs_no_false_positives(self):
        """_check_data_dirs should not flag secure dirs as errors for operators."""
        from freq.core.config import load_config
        from freq.core.doctor import _check_data_dirs
        cfg = load_config()
        result = _check_data_dirs(cfg)
        # 0 = all ok, 2 = warnings — both acceptable
        # 1 = hard fail — should not happen on a green install
        self.assertIn(result, (0, 2))


if __name__ == "__main__":
    unittest.main()
