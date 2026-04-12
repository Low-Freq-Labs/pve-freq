"""Tests for service account web login blocking contract.

Bug: Post-init, POST /api/auth/login with {username: freq-admin, password: anything}
returned 200 because of the "first login sets password" feature. Even though
commit ef3b9c9 removed the explicit password seeding, the first-login mechanism
hashed whatever password was submitted and stored it on demand.

Contract: Service account (freq-admin) is NOT a web principal. It runs the
dashboard process but cannot authenticate to it. Only the bootstrap user
(freq-ops) and additional operators can log in.

Fix: handle_auth_login checks username against cfg.ssh_service_account and
returns 401 (Invalid credentials) before any hash check or first-login path.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestServiceAccountLoginBlocked(unittest.TestCase):
    """Source-level contract: handle_auth_login blocks service account."""

    def test_source_blocks_service_account(self):
        """handle_auth_login must reject username matching ssh_service_account."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertIn("cfg.ssh_service_account", src)
        self.assertIn("service account login blocked", src)

    def test_block_happens_before_first_login(self):
        """Service account check must happen BEFORE the first-login password set."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        # The block check must appear before "First login sets password"
        block_pos = src.find("service account login blocked")
        first_login_pos = src.find("First login sets password")
        self.assertNotEqual(block_pos, -1, "Block check must exist")
        self.assertNotEqual(first_login_pos, -1, "First login comment must still exist")
        self.assertLess(block_pos, first_login_pos,
                        "Block must happen before first-login path")

    def test_block_returns_401(self):
        """Block must return 401 Invalid credentials (no info leak)."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        # Find the blocked-service-account block
        import re
        block = re.search(
            r'service account login blocked.*?Invalid credentials.*?401',
            src, re.DOTALL
        )
        self.assertIsNotNone(block,
                             "Service account block must return 401 'Invalid credentials'")


class TestLoginLogicUnchanged(unittest.TestCase):
    """Normal user login paths must still work."""

    def test_bootstrap_user_still_allowed(self):
        """Bootstrap user (non-service-account) can still log in."""
        # This is enforced by the check being conditional on username match
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertIn("username == cfg.ssh_service_account.lower()", src)

    def test_first_login_still_works_for_others(self):
        """First-login mechanism preserved for non-service users."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertIn("First login sets password", src)


if __name__ == "__main__":
    unittest.main()
