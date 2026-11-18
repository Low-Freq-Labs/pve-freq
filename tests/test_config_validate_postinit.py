"""Tests for config validate honesty after a green init.

Bug: freq config validate reported false errors on a successful post-init install:
1. "Directory not readable: keys" — keys/ is 700 owned by service account (intentional)
2. "Log directory not writable" — operator doesn't write logs, service does
3. "N iDRAC/switch host(s) but no legacy_password_file" — device creds via --device-credentials

Root cause: validate_config() didn't distinguish between operator context
(freq-ops running validate) and service context (freq-admin running serve).
Secure dirs being unreadable to operators is the security model working.

Fix:
- keys/ and vault/ 700 dirs are excluded from "not readable" check
- Log write check only applies to the service account user
- legacy_password_file is optional when device creds can be provided at runtime
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestSecureDirsNotFalsePositive(unittest.TestCase):
    """700 dirs owned by service account must not fail validate."""

    def test_keys_in_secure_dirs_exclusion(self):
        """keys/ must be in the secure_dirs set."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn('"keys"', src)
        self.assertIn("secure_dirs", src)

    def test_vault_in_secure_dirs_exclusion(self):
        """vault/ must be in the secure_dirs set."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn('"vault"', src)

    def test_not_readable_skipped_for_secure_dirs(self):
        """'not readable' check must skip dirs in secure_dirs."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn("name not in secure_dirs", src)


class TestLogWriteContextual(unittest.TestCase):
    """Log write check must only apply to the service account."""

    def test_log_write_checks_current_user(self):
        """Log write check must compare current user to service account."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn("cfg.ssh_service_account", src)
        self.assertIn("current_user", src)


class TestLegacyPasswordFileOptional(unittest.TestCase):
    """legacy_password_file must not be required when device-credentials exist."""

    def test_no_error_when_legacy_password_file_absent(self):
        """Missing legacy_password_file should not be an error by itself."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        # Must NOT contain the old "but no legacy_password_file configured" error
        self.assertNotIn("but no legacy_password_file configured", src)

    def test_still_errors_when_file_specified_but_missing(self):
        """If legacy_password_file IS configured but file missing, still error."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn("legacy_password_file not found", src)


class TestValidateOnGreenInstall(unittest.TestCase):
    """validate_config on a correctly initialized install should be clean."""

    def test_validate_no_false_positives(self):
        """Run validate on current config — secure dirs must not produce errors."""
        from freq.core.config import load_config, validate_config
        cfg = load_config()
        issues = validate_config(cfg)
        # Filter out real issues (missing PVE nodes, etc.) — just check no false positives
        false_positives = [
            i for i in issues
            if "not readable: keys" in i
            or "Log directory not writable" in i
            or "no legacy_password_file configured" in i
        ]
        self.assertEqual(false_positives, [],
                         f"False positive validation errors: {false_positives}")


if __name__ == "__main__":
    unittest.main()
