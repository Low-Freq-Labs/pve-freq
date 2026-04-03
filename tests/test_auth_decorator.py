"""Auth decorator tests — validates Phase 1.4 require_role decorator.

Tests the require_role() decorator from freq/api/helpers.py.
"""
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.api.auth import _auth_tokens, _auth_lock
from freq.api.helpers import require_role, json_response


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

class TestRequireRole:
    """@require_role decorator must enforce auth before handler runs."""

    def setup_method(self):
        _clear_tokens()

    def test_blocks_no_token(self):
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

    def test_passes_valid_token(self):
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

    def test_blocks_insufficient_role(self):
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

    def test_viewer_blocked_from_operator_endpoint(self):
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

    def test_admin_passes_operator_endpoint(self):
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

    def test_preserves_function_name(self):
        """Decorator must preserve the wrapped function's name."""
        @require_role("admin")
        def my_special_handler(h):
            pass

        assert my_special_handler.__name__ == "my_special_handler"

    def test_preserves_docstring(self):
        """Decorator must preserve the wrapped function's docstring."""
        @require_role("admin")
        def documented_handler(h):
            """This is the doc."""
            pass

        assert documented_handler.__doc__ == "This is the doc."
