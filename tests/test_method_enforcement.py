"""Regression tests for HTTP method enforcement on mutating handlers.

Proves: every state-mutating endpoint rejects GET with 405.
Catches: handlers that write to vault/disk/state but accept GET
(which enables CSRF via link prefetch, img tags, etc.).

Each test creates a mock handler with command=GET, calls the handler,
and asserts 405. A companion test with command=POST confirms the
handler proceeds past the method check (may fail later on missing
body/auth, which is fine — the point is it doesn't 405).
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
    raw = h.wfile.getvalue()
    if not raw:
        return None
    return json.loads(raw.decode())


# ══════════════════════════════════════════════════════════════════════════
# Lab Tool: save-config must require POST (writes API keys to vault)
# ══════════════════════════════════════════════════════════════════════════

class TestLabToolSaveConfigMethod(unittest.TestCase):
    """_serve_lab_tool_save_config writes to vault — must reject GET."""

    def test_get_returns_405(self):
        """GET /api/lab-tool/save-config must return 405."""
        h = _make_handler(
            path="/api/lab-tool/save-config?tool=test&host=1.2.3.4&key=secret",
            method="GET",
        )
        h._serve_lab_tool_save_config()
        self.assertEqual(h._status, 405)
        data = _get_json(h)
        self.assertIn("POST", data["error"])

    def test_post_passes_method_check(self):
        """POST /api/lab-tool/save-config must pass method gate (auth may reject)."""
        h = _make_handler(
            path="/api/lab-tool/save-config?tool=test&host=1.2.3.4&key=secret",
            method="POST",
            headers={
                "Authorization": "", "Cookie": "", "Origin": "",
                "Content-Length": "0",
            },
        )
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "", "Cookie": "", "Origin": "",
        }.get(key, default)
        h._serve_lab_tool_save_config()
        # Should NOT be 405 — will be 403 (no auth) which proves method gate passed
        self.assertNotEqual(h._status, 405,
                            "POST must pass method check (403 from auth is expected)")
        self.assertEqual(h._status, 403)


# ══════════════════════════════════════════════════════════════════════════
# Auth: logout must require POST (GET logout = CSRF via prefetch/img)
# ══════════════════════════════════════════════════════════════════════════

class TestAuthLogoutMethod(unittest.TestCase):
    """handle_auth_logout invalidates sessions — must reject GET."""

    def test_get_returns_405(self):
        """GET /api/auth/logout must return 405."""
        from freq.api.auth import handle_auth_logout

        h = _make_handler(path="/api/auth/logout", method="GET")
        handle_auth_logout(h)
        self.assertEqual(h._status, 405)
        data = _get_json(h)
        self.assertIn("POST", data["error"])

    def test_post_proceeds(self):
        """POST /api/auth/logout must proceed past method gate."""
        from freq.api.auth import handle_auth_logout

        h = _make_handler(path="/api/auth/logout", method="POST",
                          headers={"Authorization": "", "Cookie": "",
                                   "Origin": "", "Content-Length": "0"})
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "", "Cookie": "", "Origin": "",
        }.get(key, default)
        handle_auth_logout(h)
        # Should be 200 (logout always succeeds even with no token)
        self.assertEqual(h._status, 200)


# ══════════════════════════════════════════════════════════════════════════
# Auth: login already enforces POST — regression guard
# ══════════════════════════════════════════════════════════════════════════

class TestAuthLoginMethod(unittest.TestCase):
    """handle_auth_login must reject GET — regression guard."""

    def test_get_returns_405(self):
        """GET /api/auth/login must return 405."""
        from freq.api.auth import handle_auth_login

        h = _make_handler(path="/api/auth/login", method="GET")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "", "Cookie": "", "Origin": "",
            "Content-Length": "0",
        }.get(key, default)
        with patch("freq.api.auth.check_rate_limit", return_value=True):
            handle_auth_login(h)
        self.assertEqual(h._status, 405)


# ══════════════════════════════════════════════════════════════════════════
# Auth: change-password already enforces POST — regression guard
# ══════════════════════════════════════════════════════════════════════════

class TestAuthChangePasswordMethod(unittest.TestCase):
    """handle_auth_change_password must reject GET — regression guard."""

    def test_get_returns_405(self):
        """GET /api/auth/change-password must return 405."""
        from freq.api.auth import handle_auth_change_password

        h = _make_handler(path="/api/auth/change-password", method="GET")
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "", "Cookie": "", "Origin": "",
        }.get(key, default)
        handle_auth_change_password(h)
        self.assertEqual(h._status, 405)


# ══════════════════════════════════════════════════════════════════════════
# Setup endpoints: all mutating setup handlers must reject GET
# ══════════════════════════════════════════════════════════════════════════

class TestSetupMethodEnforcement(unittest.TestCase):
    """Setup endpoints that mutate state must reject GET with 405."""

    SETUP_ROUTES = [
        "/api/setup/create-admin",
        "/api/setup/configure",
        "/api/setup/generate-key",
        "/api/setup/complete",
        "/api/setup/reset",
    ]

    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_setup_mutating_endpoints_reject_get(self, _mock_first_run):
        """All mutating setup endpoints must return 405 for GET."""
        from freq.modules.serve import FreqHandler

        for path in self.SETUP_ROUTES:
            handler_name = FreqHandler._ROUTES.get(path)
            if not handler_name:
                continue
            h = _make_handler(path, method="GET")
            h.headers = MagicMock()
            h.headers.get = lambda key, default="": {
                "Authorization": "", "Cookie": "", "Origin": "",
                "Content-Length": "0",
            }.get(key, default)
            # setup/reset requires auth, mock it
            with patch("freq.modules.serve._check_session_role",
                       return_value=("admin", None)):
                getattr(h, handler_name)()
            self.assertEqual(
                h._status, 405,
                f"{path} must reject GET with 405, got {h._status}"
            )


# ══════════════════════════════════════════════════════════════════════════
# Batch: serve.py mutating handlers that already enforce POST
# (regression guards — if someone removes the check, this catches it)
# ══════════════════════════════════════════════════════════════════════════

class TestServeMutatingHandlersRejectGet(unittest.TestCase):
    """Batch regression: serve.py handlers that write state must reject GET."""

    # (route, handler_attr, needs_auth_mock)
    MUTATING = [
        ("/api/watch/start", "_serve_watch_start", True),
        ("/api/watch/stop", "_serve_watch_stop", True),
        ("/api/notify/test", "_serve_notify_test", True),
        ("/api/agent/create", "_serve_agent_create", True),
        ("/api/agent/destroy", "_serve_agent_destroy", True),
        ("/api/media/restart", "_serve_media_restart", True),
        ("/api/media/update", "_serve_media_update", True),
        ("/api/net/portscan", "_serve_portscan", True),
        ("/api/admin/hosts/update", "_serve_admin_hosts_update", True),
        ("/api/admin/fleet-boundaries/update", "_serve_admin_fleet_boundaries_update", True),
    ]

    def test_all_reject_get(self):
        """Every mutating serve.py handler must return 405 for GET."""
        for path, attr, needs_auth in self.MUTATING:
            h = _make_handler(path, method="GET")
            h.headers = MagicMock()
            h.headers.get = lambda key, default="": {
                "Authorization": "", "Cookie": "", "Origin": "",
                "Content-Length": "0",
            }.get(key, default)
            ctx = patch("freq.modules.serve._check_session_role",
                        return_value=("admin", None)) if needs_auth else MagicMock()
            with ctx:
                fn = getattr(h, attr, None)
                if fn is None:
                    continue
                fn()
            self.assertEqual(
                h._status, 405,
                f"{path} ({attr}) must reject GET with 405, got {h._status}"
            )


if __name__ == "__main__":
    unittest.main()
