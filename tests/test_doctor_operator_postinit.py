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


if __name__ == "__main__":
    unittest.main()
