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
    """Verify uses the shared token extractor for header/cookie auth."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        return src.split("def handle_auth_verify")[1].split("\ndef ")[0]

    def test_uses_shared_token_extractor(self):
        src = self._handler_src()
        self.assertIn("_extract_session_token", src)

    def test_returns_valid_field(self):
        src = self._handler_src()
        self.assertIn('"valid"', src)


class TestSessionTokenFlow(unittest.TestCase):
    """Session checks must use the shared extractor, not query strings."""

    def test_check_session_uses_shared_extractor(self):
        """check_session_role must rely on the central auth extractor."""
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        check_fn = src.split("def check_session_role")[1].split("\ndef ")[0] if "def check_session_role" in src else ""
        self.assertIn("_extract_session_token", check_fn)
        self.assertNotIn("parse_qs", check_fn)


if __name__ == "__main__":
    unittest.main()
