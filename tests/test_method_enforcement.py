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
import unittest
from unittest.mock import MagicMock, call, patch

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
                                   "Origin": "https://freq.test", "Host": "freq.test",
                                   "Content-Length": "0"})
        h.headers = MagicMock()
        h.headers.get = lambda key, default="": {
            "Authorization": "", "Cookie": "", "Origin": "https://freq.test",
            "Host": "freq.test",
        }.get(key, default)
        with patch("freq.api.auth.request_is_https", return_value=True):
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
        ("/api/media/restart", "_serve_media_restart", True),
        ("/api/media/update", "_serve_media_update", True),
        ("/api/containers/action", "_serve_container_action", True),
        ("/api/net/portscan", "_serve_portscan", True),
        ("/api/admin/hosts/update", "_serve_admin_hosts_update", True),
        ("/api/admin/fleet-boundaries/update", "_serve_admin_fleet_boundaries_update", True),
    ]

    def test_all_reject_get(self):
        """Every mutating handler rejects GET; portscan also preserves POST behavior."""
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
        self._case_watch_control_post_behavior()
        self._case_portscan_post_behavior()

    def _case_watch_control_post_behavior(self):
        """Freeze watch start/stop authorization, process, and response behavior."""
        from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
        from pathlib import Path

        from freq.services import watch_control

        def attribute_path(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, Attribute):
                parent = attribute_path(node.value)
                return f"{parent}.{node.attr}" if parent else node.attr
            return ""

        repo_root = Path(__file__).parent.parent
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        service_tree = parse((repo_root / "freq/services/watch_control.py").read_text())
        service_imports = set()
        for node in walk(service_tree):
            if isinstance(node, Import):
                service_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                service_imports.add(node.module)
        self.assertEqual(service_imports, {"subprocess"})
        self.assertIn(
            "run_watch_action",
            {node.name for node in walk(service_tree) if isinstance(node, FunctionDef)},
        )
        for action in ("start", "stop"):
            handler = next(
                node
                for node in walk(serve_tree)
                if isinstance(node, FunctionDef)
                and node.name == f"_serve_watch_{action}"
            )
            handler_calls = {
                attribute_path(node.func)
                for node in walk(handler)
                if isinstance(node, Call)
            }
            self.assertIn("_watch_control.run_watch_action", handler_calls)
            self.assertNotIn("subprocess.run", handler_calls)
        self.assertIs(watch_control.subprocess, __import__("subprocess"))

        for action in ("start", "stop"):
            with (
                patch(
                    "freq.modules.serve._check_session_role",
                    return_value=(None, "admin role required"),
                ) as check_role,
                patch("freq.services.watch_control.subprocess.run") as run,
            ):
                h = _make_handler(f"/api/watch/{action}", method="POST")
                getattr(h, f"_serve_watch_{action}")()
                self.assertEqual(h._status, 403)
                self.assertEqual(
                    _get_json(h),
                    {"error": "admin role required", "request_id": ""},
                )
                check_role.assert_called_once_with(h, "admin")
                run.assert_not_called()

        for action, returncode, stdout, expected_ok in (
            ("start", 0, "watch started\n", True),
            ("stop", 7, "watch stop refused\n", False),
        ):
            result = MagicMock(returncode=returncode, stdout=stdout)
            with (
                patch(
                    "freq.modules.serve._check_session_role",
                    return_value=("admin", None),
                ) as check_role,
                patch(
                    "freq.services.watch_control.subprocess.run",
                    return_value=result,
                ) as run,
            ):
                h = _make_handler(f"/api/watch/{action}", method="POST")
                getattr(h, f"_serve_watch_{action}")()
                self.assertEqual(h._status, 200)
                self.assertEqual(
                    _get_json(h),
                    {"ok": expected_ok, "output": stdout},
                )
                check_role.assert_called_once_with(h, "admin")
                run.assert_called_once_with(
                    ["freq", "watch", action],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

        for action in ("start", "stop"):
            with (
                patch(
                    "freq.modules.serve._check_session_role",
                    return_value=("admin", None),
                ),
                patch(
                    "freq.services.watch_control.subprocess.run",
                    side_effect=RuntimeError(f"{action} unavailable"),
                ) as run,
            ):
                h = _make_handler(f"/api/watch/{action}", method="POST")
                getattr(h, f"_serve_watch_{action}")()
                self.assertEqual(h._status, 500)
                self.assertEqual(
                    _get_json(h),
                    {"error": f"{action} unavailable", "request_id": ""},
                )
                run.assert_called_once_with(
                    ["freq", "watch", action],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

    def _case_portscan_post_behavior(self):
        """Freeze the existing portscan authorization, socket, and result contract."""
        from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
        from pathlib import Path
        from socket import AF_INET, SOCK_STREAM

        from freq.services import portscan

        def attribute_path(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, Attribute):
                parent = attribute_path(node.value)
                return f"{parent}.{node.attr}" if parent else node.attr
            return ""

        repo_root = Path(__file__).parent.parent
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        service_tree = parse((repo_root / "freq/services/portscan.py").read_text())
        service_imports = set()
        for node in walk(service_tree):
            if isinstance(node, Import):
                service_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                service_imports.add(node.module)
        self.assertEqual(service_imports, {"re", "socket"})
        self.assertIn(
            "scan_ports",
            {node.name for node in walk(service_tree) if isinstance(node, FunctionDef)},
        )
        portscan_handler = next(
            node
            for node in walk(serve_tree)
            if isinstance(node, FunctionDef) and node.name == "_serve_portscan"
        )
        self.assertEqual(len(portscan_handler.body), 7)
        handler_calls = {
            attribute_path(node.func)
            for node in walk(portscan_handler)
            if isinstance(node, Call)
        }
        self.assertIn("_portscan.scan_ports", handler_calls)
        self.assertNotIn("socket.socket", handler_calls)
        self.assertNotIn("_re.match", handler_calls)
        self.assertIs(portscan.socket, __import__("socket"))

        with (
            patch(
                "freq.modules.serve._check_session_role",
                return_value=(None, "operator role required"),
            ) as check_role,
            patch("freq.modules.serve._parse_query") as parse_query,
            patch("freq.services.portscan.socket.socket") as socket_ctor,
        ):
            h = _make_handler("/api/net/portscan", method="POST")
            h._serve_portscan()
            self.assertEqual(h._status, 403)
            self.assertEqual(
                _get_json(h),
                {"error": "operator role required", "request_id": ""},
            )
            check_role.assert_called_once_with(h, "operator")
            parse_query.assert_not_called()
            socket_ctor.assert_not_called()

        for query, expected in (
            (
                {"host": [""], "ports": [""]},
                ({"error": "host and ports required", "request_id": ""}, 400),
            ),
            (
                {"host": ["bad host!"], "ports": ["22"]},
                ({"error": "Invalid hostname", "request_id": ""}, 400),
            ),
        ):
            with (
                patch(
                    "freq.modules.serve._check_session_role",
                    return_value=("operator", None),
                ),
                patch("freq.modules.serve._parse_query", return_value=query) as parse_query,
                patch("freq.services.portscan.socket.socket") as socket_ctor,
            ):
                h = _make_handler("/api/net/portscan", method="POST")
                h._serve_portscan()
                self.assertEqual((_get_json(h), h._status), expected)
                parse_query.assert_called_once_with(h)
                socket_ctor.assert_not_called()

        open_socket = MagicMock()
        open_socket.connect_ex.return_value = 0
        closed_socket = MagicMock()
        closed_socket.connect_ex.return_value = 111
        failed_socket = MagicMock()
        failed_socket.connect_ex.side_effect = OSError("network unavailable")
        query = {"host": ["node.example"], "ports": ["22, bad, 443, 80"]}
        with (
            patch(
                "freq.modules.serve._check_session_role",
                return_value=("operator", None),
            ) as check_role,
            patch("freq.modules.serve._parse_query", return_value=query) as parse_query,
            patch(
                "freq.services.portscan.socket.socket",
                side_effect=(open_socket, closed_socket, failed_socket),
            ) as socket_ctor,
        ):
            h = _make_handler("/api/net/portscan", method="POST")
            h._serve_portscan()

        self.assertEqual(h._status, 200)
        self.assertEqual(
            _get_json(h),
            {
                "host": "node.example",
                "results": [
                    {"port": 22, "open": True},
                    {"port": "bad", "open": False, "error": "invalid"},
                    {"port": 443, "open": False},
                    {"port": "80", "open": False, "error": "invalid"},
                ],
            },
        )
        check_role.assert_called_once_with(h, "operator")
        parse_query.assert_called_once_with(h)
        self.assertEqual(
            socket_ctor.call_args_list,
            [call(AF_INET, SOCK_STREAM), call(AF_INET, SOCK_STREAM), call(AF_INET, SOCK_STREAM)],
        )
        for sock, port in ((open_socket, 22), (closed_socket, 443), (failed_socket, 80)):
            sock.settimeout.assert_called_once_with(2)
            sock.connect_ex.assert_called_once_with(("node.example", port))
        open_socket.close.assert_called_once_with()
        closed_socket.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
