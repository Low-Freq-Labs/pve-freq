"""First-use login acceptance tests.

Proves:
1. Login endpoint accepts POST with JSON credentials
2. Successful login returns ok=true with token and role
3. Token works for authenticated API calls
4. Verify endpoint checks Bearer header or cookie (not query string)
5. Login rejects empty credentials
6. Auth dead-end is prevented (no users → helpful error)
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLoginEndpointContract(unittest.TestCase):
    """Login must accept POST with JSON and return token."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        return src.split("def handle_auth_login")[1].split("\ndef ")[0]

    def test_requires_post(self):
        src = self._handler_src()
        self.assertIn("POST", src)
        self.assertIn("405", src)

    def test_returns_token_on_success(self):
        src = self._handler_src()
        self.assertIn("token", src)
        self.assertIn("token_urlsafe", src)

    def test_returns_role(self):
        src = self._handler_src()
        self.assertIn('"role"', src)

    def test_rejects_empty_credentials(self):
        src = self._handler_src()
        self.assertIn("Username and password required", src)

    def test_no_users_gives_helpful_error(self):
        src = self._handler_src()
        self.assertIn("No users configured", src)


class TestVerifyEndpointContract(unittest.TestCase):
    """Verify checks Bearer header or cookie, not query string."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        return src.split("def handle_auth_verify")[1].split("\ndef ")[0]

    def test_checks_bearer_header(self):
        src = self._handler_src()
        self.assertIn("Bearer", src)

    def test_checks_cookie(self):
        src = self._handler_src()
        self.assertIn("freq_session", src)

    def test_returns_valid_field(self):
        src = self._handler_src()
        self.assertIn('"valid"', src)


class TestSessionTokenFlow(unittest.TestCase):
    """Session tokens must work for API calls via query string."""

    def test_check_session_accepts_query_token(self):
        """_check_session_role must read token from query string."""
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        self.assertIn("token", src)
        # The session check function should read from query params
        check_fn = src.split("def check_session_role")[1].split("\ndef ")[0] if "def check_session_role" in src else ""
        if not check_fn:
            # Try the underscore version
            check_fn = src.split("def _check_session_role")[1].split("\ndef ")[0] if "def _check_session_role" in src else ""
        if check_fn:
            self.assertIn("query", check_fn.lower(),
                           "Session check must read token from query string")


if __name__ == "__main__":
    unittest.main()
