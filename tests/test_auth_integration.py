"""Integration tests for the full auth lifecycle.

Simulates: login → cookie set → authenticated API call → SSE auth →
mutating endpoint POST enforcement → anonymous rejection.

Proves the auth/cookie/CSP/header contract holds end-to-end.
"""
import io
import json
import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_handler(path="/", method="GET", headers=None, body=None):
    """Create a FreqHandler with captured response."""
    from freq.modules.serve import FreqHandler

    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.command = method
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO(body.encode() if body else b"")
    h.requestline = f"{method} {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = headers or {}
    h._headers_buffer = []
    h._status = None
    h._resp_headers = []

    def mock_send(code, msg=None):
        h._status = code

    def mock_header(k, v):
        h._resp_headers.append((k, v))

    h.send_response = mock_send
    h.send_header = mock_header
    h.end_headers = lambda: None
    return h


def _get_json(h):
    return json.loads(h.wfile.getvalue().decode())


def _get_header(h, name):
    for k, v in h._resp_headers:
        if k.lower() == name.lower():
            return v
    return None


class TestFullAuthLifecycle(unittest.TestCase):
    """End-to-end auth flow: login → cookie → API → SSE → logout."""

    def tearDown(self):
        """Clean up shared auth state after each test."""
        from freq.api.auth import _auth_tokens, _auth_lock
        with _auth_lock:
            _auth_tokens.clear()

    def _login(self):
        """Simulate login and return (token, cookie_header)."""
        from freq.api.auth import handle_auth_login, _auth_tokens, _auth_lock

        h = _make_handler(
            path="/api/auth/login",
            method="POST",
            headers={
                "Content-Length": "50",
                "Content-Type": "application/json",
                "Origin": "",
                "Cookie": "",
                "Authorization": "",
            },
            body='{"username":"admin","password":"testpass123"}',
        )

        # Mock user lookup and password verification
        mock_users = [{"username": "admin", "role": "admin"}]
        with patch("freq.modules.users._load_users", return_value=mock_users), \
             patch("freq.api.auth.verify_password", return_value=True), \
             patch("freq.api.auth.vault_get", return_value="$pbkdf2$hash"), \
             patch("freq.api.auth.check_rate_limit", return_value=True), \
             patch("freq.api.auth.record_login_attempt"), \
             patch("freq.api.auth.load_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(conf_dir="/tmp/fake", vault_file="/tmp/fake.vault")
            handle_auth_login(h)

        self.assertEqual(h._status, 200, "Login should succeed")
        data = _get_json(h)
        self.assertIn("token", data)

        # Verify cookie was set
        cookie = _get_header(h, "Set-Cookie")
        self.assertIsNotNone(cookie, "Login must set Set-Cookie header")
        self.assertIn("freq_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

        return data["token"], cookie

    def test_login_sets_cookie(self):
        """Login response must include Set-Cookie with HttpOnly + SameSite."""
        token, cookie = self._login()
        self.assertTrue(len(token) > 20)
        self.assertIn("freq_session=", cookie)

    def test_cookie_authenticates_api_call(self):
        """A request with only the session cookie (no Bearer) must authenticate."""
        from freq.api.auth import check_session_role

        token, _ = self._login()
        h = _make_handler(path="/api/fleet/overview")
        h.headers = {
            "Authorization": "",
            "Cookie": f"freq_session={token}",
            "Origin": "",
            "Content-Length": "0",
        }
        # Use dict-like get
        headers_dict = dict(h.headers) if isinstance(h.headers, dict) else {}
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "",
            "Cookie": f"freq_session={token}",
            "Origin": "",
            "Content-Length": "0",
        }.get(key, default)

        role, err = check_session_role(h, "viewer")
        self.assertIsNone(err, f"Cookie auth should succeed, got: {err}")
        self.assertEqual(role, "admin")

    def test_query_param_token_does_not_authenticate(self):
        """?token= in URL must NOT authenticate — only Bearer header or cookie."""
        from freq.api.auth import check_session_role

        token, _ = self._login()
        h = _make_handler(path=f"/api/fleet/overview?token={token}")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "",
            "Cookie": "",
            "Origin": "",
        }.get(key, default)

        role, err = check_session_role(h, "viewer")
        self.assertIsNotNone(err, "Query param token must NOT authenticate")

    def test_sse_cookie_authenticates(self):
        """SSE must authenticate via the session cookie on same-origin requests."""
        from freq.api.auth import check_session_role

        token, _ = self._login()
        h = _make_handler(path="/api/events")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "",
            "Cookie": f"freq_session={token}",
            "Origin": "",
        }.get(key, default)

        role, err = check_session_role(h, "viewer")
        self.assertIsNone(err, "SSE cookie auth must authenticate")
        self.assertIsNotNone(role)

    def test_sse_query_param_reports_removed_auth_channel(self):
        """SSE query-token callers must get a truthful migration reason."""
        from freq.api.auth import check_session_role

        token, _ = self._login()
        h = _make_handler(path=f"/api/events?token={token}")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "",
            "Cookie": "",
            "Origin": "",
        }.get(key, default)

        role, err = check_session_role(h, "viewer")
        self.assertIsNone(role)
        self.assertIn("Query-string auth", err)

    def test_anonymous_request_rejected(self):
        """Request with no auth at all must fail."""
        from freq.api.auth import check_session_role

        h = _make_handler(path="/api/fleet/overview")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "",
            "Cookie": "",
            "Origin": "",
        }.get(key, default)

        role, err = check_session_role(h, "viewer")
        self.assertIsNotNone(err)
        self.assertEqual(err, "Authentication required")

    def test_json_response_includes_csp(self):
        """JSON responses must include Content-Security-Policy."""
        h = _make_handler("/api/test")
        h._json_response({"ok": True})

        csp = _get_header(h, "Content-Security-Policy")
        self.assertIsNotNone(csp, "JSON response must include CSP header")
        self.assertIn("default-src", csp)

    def test_mutating_endpoint_rejects_get(self):
        """Mutating setup endpoints must reject GET."""
        from freq.modules.serve import FreqHandler

        with patch("freq.modules.serve._is_first_run", return_value=True):
            for path in ["/api/setup/create-admin", "/api/setup/configure",
                         "/api/setup/generate-key", "/api/setup/complete"]:
                h = _make_handler(path, method="GET")
                handler_name = FreqHandler._ROUTES.get(path)
                if handler_name:
                    getattr(h, handler_name)()
                    self.assertEqual(h._status, 405,
                                     f"{path} must reject GET with 405")


class TestSessionExpiry(unittest.TestCase):
    """Session tokens must expire and be consistently rejected."""

    def tearDown(self):
        """Clean up shared auth state after each test."""
        from freq.api.auth import _auth_tokens, _auth_lock
        with _auth_lock:
            _auth_tokens.clear()

    def test_expired_token_rejected(self):
        """A token past SESSION_TIMEOUT must return error."""
        from freq.api.auth import check_session_role, _auth_tokens, _auth_lock, SESSION_TIMEOUT_SECONDS

        token = "expired-test-token"
        with _auth_lock:
            _auth_tokens[token] = {
                "user": "admin", "role": "admin",
                "ts": time.time() - SESSION_TIMEOUT_SECONDS - 1,
            }

        h = MagicMock()
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": f"Bearer {token}",
            "Cookie": "",
            "Origin": "",
        }.get(key, default)
        h.path = "/api/fleet/overview"

        role, err = check_session_role(h, "viewer")
        self.assertIsNone(role)
        self.assertIn("expired", err.lower())

    def test_api_wrapper_preserves_expired_session_reason(self):
        """Protected API routes must return the specific expired-session reason."""
        from freq.api.auth import _auth_tokens, _auth_lock, SESSION_TIMEOUT_SECONDS

        token = "expired-wrapper-token"
        with _auth_lock:
            _auth_tokens[token] = {
                "user": "admin", "role": "admin",
                "ts": time.time() - SESSION_TIMEOUT_SECONDS - 1,
            }

        h = _make_handler(
            path="/api/fleet/overview",
            headers={
                "Authorization": f"Bearer {token}",
                "Cookie": "",
                "Origin": "",
            },
        )
        h.do_GET()

        self.assertEqual(h._status, 403)
        self.assertEqual(_get_json(h)["error"], "Session expired or invalid")

    def test_api_wrapper_preserves_insufficient_role_reason(self):
        """Protected API routes must return the specific role failure reason."""
        from freq.api.auth import _auth_tokens, _auth_lock

        token = "viewer-wrapper-token"
        with _auth_lock:
            _auth_tokens[token] = {
                "user": "viewer", "role": "viewer",
                "ts": time.time(),
            }

        h = _make_handler(
            path="/api/admin/fleet-boundaries",
            headers={
                "Authorization": f"Bearer {token}",
                "Cookie": "",
                "Origin": "",
            },
        )
        h.do_GET()

        self.assertEqual(h._status, 403)
        self.assertIn("Requires admin role", _get_json(h)["error"])

    def test_post_logout_token_rejected(self):
        """After logout, the same token must be rejected."""
        from freq.api.auth import (
            handle_auth_logout, check_session_role,
            _auth_tokens, _auth_lock
        )

        token = "logout-test-token"
        with _auth_lock:
            _auth_tokens[token] = {
                "user": "admin", "role": "admin",
                "ts": time.time(),
            }

        # Verify token works before logout
        h = MagicMock()
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": f"Bearer {token}",
            "Cookie": "",
            "Origin": "",
        }.get(key, default)
        h.path = "/api/test"

        role, err = check_session_role(h, "viewer")
        self.assertEqual(role, "admin")

        # Logout
        logout_h = _make_handler("/api/auth/logout", method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Cookie": "", "Origin": "",
                                          "Content-Length": "0"})
        logout_h.headers = MagicMock()
        logout_h.headers.get = lambda key, default="": {
            "Authorization": f"Bearer {token}",
            "Cookie": "",
            "Origin": "",
        }.get(key, default)
        handle_auth_logout(logout_h)

        # Verify token is now rejected
        role2, err2 = check_session_role(h, "viewer")
        self.assertIsNone(role2)
        self.assertIn("expired or invalid", err2)

    def test_login_cookie_has_max_age(self):
        """Login cookie must include Max-Age matching session timeout."""
        import inspect
        from freq.api.auth import handle_auth_login
        src = inspect.getsource(handle_auth_login)
        self.assertIn("Max-Age=", src,
                       "Login cookie must include Max-Age")
        self.assertIn("SESSION_TIMEOUT_SECONDS", src,
                       "Cookie Max-Age must reference SESSION_TIMEOUT_SECONDS")

    def test_logout_clears_cookie(self):
        """Logout must set cookie Max-Age=0 to clear it."""
        import inspect
        from freq.api.auth import handle_auth_logout
        src = inspect.getsource(handle_auth_logout)
        self.assertIn("Max-Age=0", src,
                       "Logout must clear cookie via Max-Age=0")


if __name__ == "__main__":
    unittest.main()
