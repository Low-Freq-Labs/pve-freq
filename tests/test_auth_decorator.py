"""Auth decorator tests — validates Phase 1.4 require_role decorator.

Tests the require_role() decorator from freq/api/helpers.py.
"""
import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

from freq.api.auth import _auth_lock, _auth_tokens
from freq.api.helpers import json_response, require_role

# ── Helpers ──────────────────────────────────────────────────────────

def _clear_tokens():
    with _auth_lock:
        _auth_tokens.clear()


def _mock_handler(auth_header=""):
    h = MagicMock()
    h.path = "/api/test"
    h.headers = MagicMock()
    h.headers.get = lambda key, default="": {
        "Authorization": auth_header,
        "Origin": "",
    }.get(key, default)
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    h.wfile = MagicMock()
    return h


# ── Tests ────────────────────────────────────────────────────────────

class TestRequireRole(unittest.TestCase):
    """@require_role decorator must enforce auth before handler runs."""

    def setUp(self):
        _clear_tokens()

    def _case_blocks_no_token(self):
        """Handler must not execute without authentication."""
        called = []

        @require_role("operator")
        def handler(h):
            called.append(True)

        h = _mock_handler()
        handler(h)
        assert len(called) == 0  # Handler was NOT called
        # Verify 403 was sent
        h.send_response.assert_called_with(403)

    def _case_passes_valid_token(self):
        """Handler must execute with valid admin token."""
        with _auth_lock:
            _auth_tokens["good-token"] = {
                "user": "admin", "role": "admin", "ts": time.time(),
            }
        called = []

        @require_role("operator")
        def handler(h):
            called.append(True)

        h = _mock_handler(auth_header="Bearer good-token")
        handler(h)
        assert len(called) == 1  # Handler WAS called

    def _case_blocks_insufficient_role(self):
        """@require_role('admin') must block operator tokens."""
        with _auth_lock:
            _auth_tokens["op-token"] = {
                "user": "operator", "role": "operator", "ts": time.time(),
            }
        called = []

        @require_role("admin")
        def handler(h):
            called.append(True)

        h = _mock_handler(auth_header="Bearer op-token")
        handler(h)
        assert len(called) == 0  # Handler was NOT called
        h.send_response.assert_called_with(403)

    def _case_viewer_blocked_from_operator_endpoint(self):
        """Viewer role must be blocked from operator endpoints."""
        with _auth_lock:
            _auth_tokens["viewer-token"] = {
                "user": "viewer", "role": "viewer", "ts": time.time(),
            }
        called = []

        @require_role("operator")
        def handler(h):
            called.append(True)

        h = _mock_handler(auth_header="Bearer viewer-token")
        handler(h)
        assert len(called) == 0

    def _case_admin_passes_operator_endpoint(self):
        """Admin role must pass operator-level endpoints."""
        with _auth_lock:
            _auth_tokens["admin-tok"] = {
                "user": "admin", "role": "admin", "ts": time.time(),
            }
        called = []

        @require_role("operator")
        def handler(h):
            called.append(True)

        h = _mock_handler(auth_header="Bearer admin-tok")
        handler(h)
        assert len(called) == 1

    def _case_preserves_function_name(self):
        """Decorator must preserve the wrapped function's name."""
        @require_role("admin")
        def my_special_handler(h):
            pass

        assert my_special_handler.__name__ == "my_special_handler"

    def _case_preserves_docstring(self):
        """Decorator must preserve the wrapped function's docstring."""
        @require_role("admin")
        def documented_handler(h):
            """This is the doc."""
            pass

        assert documented_handler.__doc__ == "This is the doc."


REQUIRE_ROLE_CASES = (
    "_case_blocks_no_token",
    "_case_passes_valid_token",
    "_case_blocks_insufficient_role",
    "_case_viewer_blocked_from_operator_endpoint",
    "_case_admin_passes_operator_endpoint",
    "_case_preserves_function_name",
    "_case_preserves_docstring",
)


class TestRequireRoleMatrix(unittest.TestCase):
    def test_require_role_matrix(self):
        run_case_matrix(self, TestRequireRole, REQUIRE_ROLE_CASES)


class TestJsonResponse(unittest.TestCase):
    """The shared API response helper enforces same-origin response mechanics."""

    def test_hostile_origin_gets_json_without_cors_access(self):
        handler = _mock_handler()
        handler.headers.get = lambda key, default="": {
            "Origin": "https://evil.example",
        }.get(key, default)
        handler._refresh_session_cookie = ""
        payload = {"ok": True, "items": [1, 2]}
        expected_body = json.dumps(payload).encode()

        json_response(handler, payload, 207)

        handler.send_response.assert_called_once_with(207)
        emitted_headers = {}
        for call in handler.send_header.call_args_list:
            name, value = call.args
            emitted_headers.setdefault(name, []).append(value)
        expected_headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Content-Length": str(len(expected_body)),
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
        for name, value in expected_headers.items():
            with self.subTest(header=name):
                self.assertEqual(emitted_headers.get(name), [value])
        self.assertNotIn("Access-Control-Allow-Origin", emitted_headers)
        handler.end_headers.assert_called_once_with()
        handler.wfile.write.assert_called_once_with(expected_body)
