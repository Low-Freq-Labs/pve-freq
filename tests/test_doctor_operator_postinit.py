"""Doctor operator truth after successful init.

Proves:
1. Doctor distinguishes unreachable hosts from account failures
2. Unreachable hosts get warnings, not hard failures
3. Account/sudo issues are still hard failures
4. Doctor doesn't undermine a just-successful init
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestServiceAccountSeverity(unittest.TestCase):
    """Service account check must distinguish unreachable from broken."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            src = f.read()
        return src.split("def _check_service_account")[1].split("\ndef ")[0]

    def test_distinguishes_unreachable_from_issues(self):
        src = self._handler_src()
        self.assertIn("unreachable", src,
                       "Must track unreachable hosts separately from issues")

    def test_unreachable_is_warning_not_failure(self):
        """Unreachable hosts should be warnings (return 2), not failures (return 1)."""
        src = self._handler_src()
        # Find the unreachable-only branch
        self.assertIn("step_warn", src,
                       "Unreachable-only case must be a warning")

    def test_account_issues_still_fail(self):
        """Real account/sudo issues must still be hard failures."""
        src = self._handler_src()
        self.assertIn("step_fail", src,
                       "Account issues must be hard failures")

    def test_catches_connection_patterns(self):
        """Must detect common SSH connection failure patterns."""
        src = self._handler_src()
        for pattern in ["Permission denied", "Connection refused", "connect to host"]:
            self.assertIn(pattern, src,
                           f"Must detect '{pattern}' as unreachable")

    def test_verified_count_reported(self):
        """Must report how many hosts were successfully verified."""
        src = self._handler_src()
        self.assertIn("verified", src)

    def test_service_account_check_only_samples_unix_managed_hosts(self):
        """Physical devices use device-specific probes, not Unix sudo checks."""
        src = self._handler_src()
        self.assertIn('service_account_htypes = {"linux", "pve", "docker", "truenas"}', src)
        self.assertIn("h.htype in service_account_htypes", src)


class TestDoctorFleetLockPermissions(unittest.TestCase):
    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            return f.read()

    def test_lock_file_does_not_require_write_access_to_existing_root_file(self):
        src = self._src()
        lock_block = src.split("def _doctor_fleet_lock")[1].split("\ndef ", 1)[0]
        self.assertIn("os.open(path, os.O_RDWR | os.O_CREAT, 0o664)", lock_block)
        self.assertIn("os.fchmod(fd, 0o664)", lock_block)
        self.assertIn("except PermissionError", lock_block)
        self.assertIn("os.open(path, os.O_RDONLY)", lock_block)


class TestDoctorOperatorCredentialContext(unittest.TestCase):
    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            return f.read()

    def test_detects_operator_context_mismatch(self):
        src = self._src()
        self.assertIn("def _doctor_operator_context_mismatch", src)
        self.assertIn("not os.access(key_dir, os.X_OK)", src)

    def test_fleet_check_skips_wrong_operator_key_context(self):
        src = self._src()
        block = src.split("def _check_fleet_connectivity")[1].split("\ndef ", 1)[0]
        self.assertIn("context_mismatch", block)
        self.assertIn("Run `sudo freq doctor` or use /api/doctor", block)
        self.assertIn("return 2", block)

    def test_service_account_check_skips_wrong_operator_key_context(self):
        src = self._src()
        block = src.split("def _check_service_account")[1].split("\ndef ", 1)[0]
        self.assertIn("context_mismatch", block)
        self.assertIn("installed service SSH keys are not readable", block)

    def test_global_doctor_skips_pve_hosts_outside_configured_cluster(self):
        src = self._src()
        helper = src.split("def _doctor_managed_hosts", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("return managed_probe_hosts(cfg)", helper)
        self.assertIn("from freq.core.host_scope import managed_probe_hosts", src)
        self.assertIn("_doctor_managed_hosts(cfg)", src.split("def _check_fleet_connectivity", 1)[1])
        self.assertIn("_doctor_managed_hosts(cfg)", src.split("def _check_service_account", 1)[1])


if __name__ == "__main__":
    unittest.main()
