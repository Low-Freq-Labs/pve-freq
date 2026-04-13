"""Tests for service account web login blocking contract.

Original bug: Post-init, POST /api/auth/login with {username: freq-admin,
password: anything} returned 200 because of the "first login sets password"
feature. The service-account block was added to short-circuit that path.

Followup: R-SECURITY-TRUST-AUDIT-20260413P F1 then removed the underlying
trust-on-first-use seeding entirely (login now refuses any user whose
stored_hash is empty), so the historic "first login still works" assertion
was inverted — the test now pins the absence of that path.

Contract pinned here:
  1. Service account (freq-admin) is NOT a web principal. It runs the
     dashboard process but cannot authenticate to it. Block returns 401
     Invalid credentials with no info leak.
  2. The block runs BEFORE any vault read or password check, so a
     service-account attempt never even touches the credential store.
  3. The trust-on-first-use seeding from before F1 must NOT come back —
     login refuses an empty stored_hash.
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

    def test_block_happens_before_credential_lookup(self):
        """Service account check must happen BEFORE the vault lookup so
        a service-account attempt never even touches the credential store.

        Pre-F1 this test compared against the now-removed 'First login sets
        password' comment; F1 removed the trust-on-first-use path entirely
        so the anchor changed to vault_get."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        block_pos = src.find("service account login blocked")
        vault_pos = src.find("stored_hash = vault_get(")
        self.assertNotEqual(block_pos, -1, "Block check must exist")
        self.assertNotEqual(vault_pos, -1, "Vault lookup must exist")
        self.assertLess(block_pos, vault_pos,
                        "Service-account block must run before any vault read")

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
    """Normal user login paths must still work; trust-on-first-use must not."""

    def test_bootstrap_user_still_allowed(self):
        """Bootstrap user (non-service-account) can still log in."""
        # The block is conditional on the username matching the configured
        # service account; everyone else falls through to normal verify.
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertIn("username == cfg.ssh_service_account.lower()", src)

    def test_no_silent_first_login_seed(self):
        """R-SECURITY-TRUST-AUDIT-20260413P F1: login MUST NOT seed a
        password from caller input on empty stored_hash. The pre-F1
        `if not stored_hash or ('$' not in stored_hash):` block was the
        account-takeover trigger and is gone."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertNotIn(
            "if not stored_hash or",
            src,
            "auth.py must not contain the empty-hash silent-seed branch",
        )
        self.assertIn(
            "if not stored_hash:",
            src,
            "auth.py must explicitly refuse login on empty stored_hash",
        )


if __name__ == "__main__":
    unittest.main()
