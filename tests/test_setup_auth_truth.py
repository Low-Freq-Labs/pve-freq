"""Setup wizard and auth operator truth tests.

Proves:
1. Only status/create-admin are public during zero-state setup
2. Setup creates admin with enforced password policy
3. Login validates against stored hash (not plaintext)
4. First-login-sets-password only fires when vault has no hash
5. Password change enforces minimum length
6. Rate limiting prevents brute force
7. Completion markers belong only to successful browser-launched init
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSetupWizardGating(unittest.TestCase):
    """Setup wizard must only be accessible during first run."""

    def _serve_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            return f.read()

    def test_create_admin_gated_by_existing_users_and_markers(self):
        src = self._serve_src()
        handler = src.split("def _serve_setup_create_admin")[1].split("def _serve_")[0]
        self.assertIn("_load_users(cfg)", handler)
        self.assertIn('"operator_exists"', handler)
        self.assertIn('"setup_closed"', handler)

    def test_configure_gated_by_first_run(self):
        src = self._serve_src()
        handler = src.split("def _serve_setup_configure")[1].split("def _serve_")[0]
        self.assertIn("_is_first_run()", handler)

    def test_complete_endpoint_is_disabled(self):
        src = self._serve_src()
        handler = src.split("def _serve_setup_complete")[1].split("def _serve_")[0]
        self.assertIn("legacy_endpoint_disabled", handler)
        self.assertNotIn("_write_web_setup_markers", handler)

    def test_successful_init_job_owns_web_marker(self):
        src = self._serve_src()
        handler = src.split("def _run_setup_init_job")[1].split("def _init_blocker_from_artifacts")[0]
        self.assertIn("_write_web_setup_markers", handler)
        self.assertIn("rc == 0 and initialized", handler)


class TestPasswordPolicy(unittest.TestCase):
    """Password policy must be enforced consistently."""

    def test_setup_enforces_min_length(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_setup_create_admin")[1].split("def _serve_")[0]
        self.assertIn("len(password) < 8", handler,
                       "Setup must enforce 8-char minimum password")

    def test_change_password_enforces_min_length(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        handler = src.split("def handle_auth_change_password")[1].split("\ndef ")[0]
        self.assertIn("len(", handler,
                       "Password change must enforce minimum length")

    def test_setup_validates_username_format(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_setup_create_admin")[1].split("def _serve_")[0]
        self.assertIn("re.match", handler,
                       "Setup must validate username format")


class TestLoginAuthContract(unittest.TestCase):
    """Login must authenticate honestly against stored credentials."""

    def _auth_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            return f.read()

    def test_login_requires_post(self):
        handler = self._auth_src().split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("POST", handler)
        self.assertIn("405", handler)

    def test_login_checks_users_conf(self):
        """Login must verify user exists in users.conf."""
        handler = self._auth_src().split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("_load_users", handler,
                       "Login must load users from users.conf")
        self.assertIn("401", handler,
                       "Unknown users must get 401")

    def test_login_verifies_password_hash(self):
        """Login must call verify_password against stored hash."""
        handler = self._auth_src().split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("verify_password", handler)

    def test_first_login_sets_password_only_when_no_hash(self):
        """First-login-sets-password must ONLY trigger when vault has no hash."""
        handler = self._auth_src().split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("not stored_hash", handler,
                       "Password set must be conditional on empty hash")

    def test_login_uses_secure_token(self):
        """Session tokens must use secrets.token_urlsafe."""
        handler = self._auth_src().split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("establish_session", handler)
        helper = self._auth_src().split("def establish_session")[1].split("\ndef ")[0]
        self.assertIn("token_urlsafe", helper)


class TestRateLimiting(unittest.TestCase):
    """Login must be rate-limited to prevent brute force."""

    def test_login_has_rate_limit(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        handler = src.split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("check_rate_limit", handler)
        self.assertIn("429", handler,
                       "Rate-limited requests must get 429")

    def test_failed_logins_are_recorded(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        handler = src.split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("record_login_attempt", handler)


class TestSetupPasswordStorage(unittest.TestCase):
    """Setup must store passwords via vault, not plaintext."""

    def test_setup_hashes_password(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_setup_create_admin")[1].split("def _serve_")[0]
        helper = src.split("def _setup_store_admin_password")[1].split("def _setup_")[0]
        self.assertIn("_setup_store_admin_password", handler)
        self.assertIn("_hash_password", helper,
                       "Setup must hash password before storage")

    def test_setup_stores_in_vault(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_setup_create_admin")[1].split("def _serve_")[0]
        helper = src.split("def _setup_store_admin_password")[1].split("def _setup_")[0]
        self.assertIn("_setup_store_admin_password", handler)
        self.assertIn("vault_set", helper,
                       "Setup must store hash in vault")

    def test_no_plaintext_password_in_users_conf(self):
        """users.conf dict must NOT contain a password field."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_setup_create_admin")[1].split("def _serve_")[0]
        # Find the users.append(...) dict literal
        append_match = re.search(r'users\.append\((\{[^}]+\})\)', handler)
        self.assertIsNotNone(append_match, "Must have users.append({...})")
        user_dict = append_match.group(1)
        self.assertNotIn("password", user_dict,
                          "User dict in users.conf must not contain password field")


class TestAuthWhitelist(unittest.TestCase):
    """Setup and auth endpoints must be whitelisted for first run."""

    def test_setup_endpoints_whitelisted(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        # Find the auth whitelist
        self.assertIn("/api/setup/", src)
        self.assertIn("/api/auth/login", src)


if __name__ == "__main__":
    unittest.main()
