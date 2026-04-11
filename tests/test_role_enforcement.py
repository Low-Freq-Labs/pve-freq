"""Regression tests for auth role enforcement on API handlers.

Proves: admin-only handlers reject operator sessions, operator handlers
reject viewer sessions, and the role hierarchy is enforced correctly.

Critical because: if a role check uses "operator" instead of "admin",
any authenticated operator can destroy VMs, wipe disks, or modify
firewall rules.
"""
import io
import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_handler(path="/", method="POST"):
    """Minimal handler mock for role enforcement tests."""
    from freq.modules.serve import FreqHandler

    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.command = method
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO()
    h.requestline = f"{method} {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = {}
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
    return json.loads(raw.decode()) if raw else None


def _inject_session(role):
    """Inject a test session token with given role, return token string."""
    from freq.api.auth import _auth_tokens, _auth_lock
    token = f"test-{role}-{time.time()}"
    with _auth_lock:
        _auth_tokens[token] = {
            "user": f"test_{role}",
            "role": role,
            "ts": time.time(),
        }
    return token


def _cleanup_sessions():
    """Remove all test sessions."""
    from freq.api.auth import _auth_tokens, _auth_lock
    with _auth_lock:
        to_remove = [k for k in _auth_tokens if k.startswith("test-")]
        for k in to_remove:
            del _auth_tokens[k]


def _authed_handler(path, token, method="POST"):
    """Create a handler with auth token set."""
    h = _make_handler(path, method=method)
    h.headers = MagicMock()
    h.headers.get = lambda key, default="": {
        "Authorization": f"Bearer {token}",
        "Cookie": "",
        "Origin": "",
        "Content-Length": "0",
    }.get(key, default)
    return h


# ══════════════════════════════════════════════════════════════════════════
# Core: check_session_role role hierarchy
# ══════════════════════════════════════════════════════════════════════════

class TestRoleHierarchy(unittest.TestCase):
    """check_session_role must enforce viewer < operator < admin."""

    def setUp(self):
        self.viewer_token = _inject_session("viewer")
        self.operator_token = _inject_session("operator")
        self.admin_token = _inject_session("admin")

    def tearDown(self):
        _cleanup_sessions()

    def test_admin_passes_admin_check(self):
        from freq.api.auth import check_session_role
        h = _authed_handler("/api/test", self.admin_token)
        role, err = check_session_role(h, "admin")
        self.assertEqual(role, "admin")
        self.assertIsNone(err)

    def test_operator_fails_admin_check(self):
        from freq.api.auth import check_session_role
        h = _authed_handler("/api/test", self.operator_token)
        role, err = check_session_role(h, "admin")
        self.assertIsNone(role)
        self.assertIn("admin", err)

    def test_viewer_fails_admin_check(self):
        from freq.api.auth import check_session_role
        h = _authed_handler("/api/test", self.viewer_token)
        role, err = check_session_role(h, "admin")
        self.assertIsNone(role)
        self.assertIn("admin", err)

    def test_operator_passes_operator_check(self):
        from freq.api.auth import check_session_role
        h = _authed_handler("/api/test", self.operator_token)
        role, err = check_session_role(h, "operator")
        self.assertEqual(role, "operator")
        self.assertIsNone(err)

    def test_viewer_fails_operator_check(self):
        from freq.api.auth import check_session_role
        h = _authed_handler("/api/test", self.viewer_token)
        role, err = check_session_role(h, "operator")
        self.assertIsNone(role)
        self.assertIn("operator", err)

    def test_viewer_passes_viewer_check(self):
        from freq.api.auth import check_session_role
        h = _authed_handler("/api/test", self.viewer_token)
        role, err = check_session_role(h, "viewer")
        self.assertEqual(role, "viewer")
        self.assertIsNone(err)

    def test_admin_passes_all_levels(self):
        """Admin must pass all role checks."""
        from freq.api.auth import check_session_role
        for min_role in ("viewer", "operator", "admin"):
            h = _authed_handler("/api/test", self.admin_token)
            role, err = check_session_role(h, min_role)
            self.assertEqual(role, "admin",
                             f"admin must pass {min_role} check")


# ══════════════════════════════════════════════════════════════════════════
# Destructive admin-only handlers must reject operator sessions
# ══════════════════════════════════════════════════════════════════════════

class TestAdminOnlyHandlersRejectOperator(unittest.TestCase):
    """Destructive admin-only handlers must reject operator with 403."""

    def setUp(self):
        self.operator_token = _inject_session("operator")

    def tearDown(self):
        _cleanup_sessions()

    # Each entry: (module, function, description)
    ADMIN_ONLY_DESTRUCTIVE = [
        ("freq.api.vm", "handle_vm_destroy", "VM destroy"),
        ("freq.api.vm", "handle_vm_create", "VM create"),
        ("freq.api.vm", "handle_vm_change_id", "VM change ID"),
        ("freq.api.vm", "handle_vm_clear_nics", "VM clear NICs"),
        ("freq.api.vm", "handle_vm_clone", "VM clone"),
        ("freq.api.vm", "handle_vm_migrate", "VM migrate"),
        ("freq.api.vm", "handle_rollback", "VM rollback"),
        ("freq.api.vm", "handle_vm_template", "VM template"),
        ("freq.api.vm", "handle_vm_add_disk", "VM add disk"),
        ("freq.api.ct", "handle_ct_destroy", "CT destroy"),
        ("freq.api.ct", "handle_ct_rollback", "CT rollback"),
        ("freq.api.fw", "handle_pfsense_reboot", "pfSense reboot"),
        ("freq.api.fw", "handle_pfsense_rules", "pfSense rules"),
        ("freq.api.opnsense", "handle_opnsense_reboot", "OPNsense reboot"),
        ("freq.api.store", "handle_truenas_reboot", "TrueNAS reboot"),
        ("freq.api.store", "handle_truenas_dataset", "TrueNAS dataset"),
        ("freq.api.hw", "handle_gwipe", "GWIPE (disk wipe)"),
        ("freq.api.ipmi", "handle_ipmi_power", "IPMI power"),
        ("freq.api.secure", "handle_vault_set", "Vault set"),
        ("freq.api.secure", "handle_vault_delete", "Vault delete"),
        ("freq.api.user", "handle_user_create", "User create"),
        ("freq.api.user", "handle_user_promote", "User promote"),
        ("freq.api.state", "handle_gitops_apply", "GitOps apply"),
        ("freq.api.auto", "handle_chaos_run", "Chaos experiment"),
        ("freq.api.dr", "handle_backup_restore", "Backup restore"),
    ]

    def test_operator_rejected_on_admin_handlers(self):
        """Operator session must get 403 on all admin-only destructive handlers."""
        import importlib
        for module_path, func_name, desc in self.ADMIN_ONLY_DESTRUCTIVE:
            mod = importlib.import_module(module_path)
            handler_fn = getattr(mod, func_name, None)
            if handler_fn is None:
                continue
            h = _authed_handler(f"/api/test-{func_name}", self.operator_token)
            handler_fn(h)
            self.assertEqual(
                h._status, 403,
                f"{desc} ({func_name}) must reject operator with 403, got {h._status}"
            )
            data = _get_json(h)
            if data and "error" in data:
                self.assertIn("admin", data["error"].lower(),
                              f"{desc} error must mention 'admin' role requirement")


# ══════════════════════════════════════════════════════════════════════════
# Operator handlers must reject viewer sessions
# ══════════════════════════════════════════════════════════════════════════

class TestOperatorHandlersRejectViewer(unittest.TestCase):
    """Operator-level handlers must reject viewer with 403."""

    def setUp(self):
        self.viewer_token = _inject_session("viewer")

    def tearDown(self):
        _cleanup_sessions()

    OPERATOR_HANDLERS = [
        ("freq.api.vm", "handle_vm_power", "VM power"),
        ("freq.api.vm", "handle_vm_snapshot", "VM snapshot"),
        ("freq.api.vm", "handle_vm_resize", "VM resize"),
        ("freq.api.vm", "handle_vm_rename", "VM rename"),
        ("freq.api.vm", "handle_vm_tag", "VM tag"),
        ("freq.api.ct", "handle_ct_create", "CT create"),
        ("freq.api.ct", "handle_ct_power", "CT power"),
        ("freq.api.ct", "handle_ct_snapshot", "CT snapshot"),
        ("freq.api.ct", "handle_ct_exec", "CT exec"),
        ("freq.api.dr", "handle_backup_create", "Backup create"),
        ("freq.api.terminal", "handle_terminal_open", "Terminal open"),
    ]

    def test_viewer_rejected_on_operator_handlers(self):
        """Viewer session must get 403 on all operator-level handlers."""
        import importlib
        for module_path, func_name, desc in self.OPERATOR_HANDLERS:
            mod = importlib.import_module(module_path)
            handler_fn = getattr(mod, func_name, None)
            if handler_fn is None:
                continue
            h = _authed_handler(f"/api/test-{func_name}", self.viewer_token)
            handler_fn(h)
            self.assertEqual(
                h._status, 403,
                f"{desc} ({func_name}) must reject viewer with 403, got {h._status}"
            )


# ══════════════════════════════════════════════════════════════════════════
# Anonymous (no token) must be rejected by all protected handlers
# ══════════════════════════════════════════════════════════════════════════

class TestAnonymousRejected(unittest.TestCase):
    """Handlers with auth checks must reject anonymous requests."""

    PROTECTED = [
        ("freq.api.vm", "handle_vm_destroy"),
        ("freq.api.ct", "handle_ct_destroy"),
        ("freq.api.secure", "handle_vault_set"),
        ("freq.api.user", "handle_user_create"),
        ("freq.api.fleet", "handle_exec"),
    ]

    def test_no_auth_gets_401_or_403(self):
        """Anonymous requests must be rejected (401 or 403)."""
        import importlib
        for module_path, func_name in self.PROTECTED:
            mod = importlib.import_module(module_path)
            handler_fn = getattr(mod, func_name, None)
            if handler_fn is None:
                continue
            h = _make_handler(method="POST")
            h.headers = MagicMock()
            h.headers.get = lambda key, default="": {
                "Authorization": "", "Cookie": "", "Origin": "",
                "Content-Length": "0",
            }.get(key, default)
            handler_fn(h)
            self.assertIn(
                h._status, (401, 403),
                f"{func_name} must reject anonymous with 401/403, got {h._status}"
            )


if __name__ == "__main__":
    unittest.main()
