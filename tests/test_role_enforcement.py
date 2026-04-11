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
# ALL admin-only handlers must reject operator sessions
# ══════════════════════════════════════════════════════════════════════════

class TestAdminOnlyHandlersRejectOperator(unittest.TestCase):
    """Every admin-only handler must reject operator with 403."""

    def setUp(self):
        self.operator_token = _inject_session("operator")

    def tearDown(self):
        _cleanup_sessions()

    # Complete list of all admin-only handlers across all freq/api/ modules
    ADMIN_ONLY = [
        # ── VM (9 handlers) ──
        ("freq.api.vm", "handle_vm_create", "VM create"),
        ("freq.api.vm", "handle_vm_destroy", "VM destroy"),
        ("freq.api.vm", "handle_vm_template", "VM template"),
        ("freq.api.vm", "handle_vm_change_id", "VM change ID"),
        ("freq.api.vm", "handle_vm_clear_nics", "VM clear NICs"),
        ("freq.api.vm", "handle_vm_add_disk", "VM add disk"),
        ("freq.api.vm", "handle_vm_clone", "VM clone"),
        ("freq.api.vm", "handle_vm_migrate", "VM migrate"),
        ("freq.api.vm", "handle_rollback", "VM rollback"),
        # ── CT (2 handlers) ──
        ("freq.api.ct", "handle_ct_destroy", "CT destroy"),
        ("freq.api.ct", "handle_ct_rollback", "CT rollback"),
        # ── Firewall: pfSense (8 via _require_pfsense → admin) ──
        ("freq.api.fw", "handle_pfsense_service", "pfSense service"),
        ("freq.api.fw", "handle_pfsense_dhcp_reservation", "pfSense DHCP"),
        ("freq.api.fw", "handle_pfsense_config_backup", "pfSense backup"),
        ("freq.api.fw", "handle_pfsense_reboot", "pfSense reboot"),
        ("freq.api.fw", "handle_pfsense_rules", "pfSense rules"),
        ("freq.api.fw", "handle_pfsense_nat", "pfSense NAT"),
        ("freq.api.fw", "handle_pfsense_wg_peer", "pfSense WireGuard"),
        ("freq.api.fw", "handle_pfsense_updates", "pfSense updates"),
        # ── Firewall: OPNsense (9 via _require_opnsense → admin) ──
        ("freq.api.opnsense", "handle_opnsense_service_action", "OPNsense service"),
        ("freq.api.opnsense", "handle_opnsense_rule_add", "OPNsense rule add"),
        ("freq.api.opnsense", "handle_opnsense_rule_delete", "OPNsense rule delete"),
        ("freq.api.opnsense", "handle_opnsense_dhcp_add", "OPNsense DHCP add"),
        ("freq.api.opnsense", "handle_opnsense_dhcp_delete", "OPNsense DHCP delete"),
        ("freq.api.opnsense", "handle_opnsense_dns_add", "OPNsense DNS add"),
        ("freq.api.opnsense", "handle_opnsense_dns_delete", "OPNsense DNS delete"),
        ("freq.api.opnsense", "handle_opnsense_wg_add", "OPNsense WireGuard"),
        ("freq.api.opnsense", "handle_opnsense_reboot", "OPNsense reboot"),
        # ── Storage: TrueNAS (8 handlers) ──
        ("freq.api.store", "handle_truenas_snapshot", "TrueNAS snapshot"),
        ("freq.api.store", "handle_truenas_service", "TrueNAS service"),
        ("freq.api.store", "handle_truenas_scrub", "TrueNAS scrub"),
        ("freq.api.store", "handle_truenas_reboot", "TrueNAS reboot"),
        ("freq.api.store", "handle_truenas_dataset", "TrueNAS dataset"),
        ("freq.api.store", "handle_truenas_share", "TrueNAS share"),
        ("freq.api.store", "handle_truenas_replication", "TrueNAS replication"),
        ("freq.api.store", "handle_truenas_app", "TrueNAS app"),
        # ── Synology (via fw-style check) ──
        # (synology handlers use operator-level checks, verified separately)
        # ── Network (3 handlers) ──
        ("freq.api.net", "handle_switch_vlan_create", "VLAN create"),
        ("freq.api.net", "handle_switch_vlan_delete", "VLAN delete"),
        ("freq.api.net", "handle_switch_acl", "ACL management"),
        # ── Fleet (6 handlers) ──
        ("freq.api.fleet", "handle_exec", "Fleet exec"),
        ("freq.api.fleet", "handle_deploy_agent", "Agent deploy"),
        ("freq.api.fleet", "handle_federation_register", "Federation register"),
        ("freq.api.fleet", "handle_federation_unregister", "Federation unregister"),
        ("freq.api.fleet", "handle_federation_poll", "Federation poll"),
        ("freq.api.fleet", "handle_federation_toggle", "Federation toggle"),
        # ── DR (1 handler) ──
        ("freq.api.dr", "handle_backup_restore", "Backup restore"),
        # ── Automation (7 handlers) ──
        ("freq.api.auto", "handle_rules_create", "Rule create"),
        ("freq.api.auto", "handle_rules_update", "Rule update"),
        ("freq.api.auto", "handle_rules_delete", "Rule delete"),
        ("freq.api.auto", "handle_playbooks_run", "Playbook run"),
        ("freq.api.auto", "handle_playbooks_step", "Playbook step"),
        ("freq.api.auto", "handle_playbooks_create", "Playbook create"),
        ("freq.api.auto", "handle_chaos_run", "Chaos experiment"),
        # ── State / GitOps (5 handlers) ──
        ("freq.api.state", "handle_policy_fix", "Policy fix"),
        ("freq.api.state", "handle_gitops_sync", "GitOps sync"),
        ("freq.api.state", "handle_gitops_apply", "GitOps apply"),
        ("freq.api.state", "handle_gitops_rollback", "GitOps rollback"),
        ("freq.api.state", "handle_gitops_init", "GitOps init"),
        # ── Security / Vault (2 handlers) ──
        ("freq.api.secure", "handle_vault_set", "Vault set"),
        ("freq.api.secure", "handle_vault_delete", "Vault delete"),
        # ── Users (3 handlers) ──
        ("freq.api.user", "handle_user_create", "User create"),
        ("freq.api.user", "handle_user_promote", "User promote"),
        ("freq.api.user", "handle_user_demote", "User demote"),
        # ── IPMI / Redfish (4 handlers) ──
        ("freq.api.ipmi", "handle_ipmi_power", "IPMI power"),
        ("freq.api.ipmi", "handle_ipmi_boot", "IPMI boot"),
        ("freq.api.ipmi", "handle_ipmi_sel_clear", "IPMI SEL clear"),
        ("freq.api.redfish", "handle_redfish_power", "Redfish power"),
        # ── Hardware (1 handler; handle_idrac is mixed read/write, tested separately) ──
        ("freq.api.hw", "handle_gwipe", "GWIPE (disk wipe)"),
        # ── Observability (1 handler) ──
        ("freq.api.observe", "handle_capacity_snapshot", "Capacity snapshot"),
        # ── Benchmark (3 handlers) ──
        ("freq.api.bench", "handle_wol", "Wake-on-LAN"),
        ("freq.api.bench", "handle_bench_run", "Benchmark run"),
        ("freq.api.bench", "handle_bench_netspeed", "Network speed test"),
        # ── Backup verify (1 handler) ──
        ("freq.api.backup_verify", "handle_backup_verify", "Backup verify"),
    ]

    def test_operator_rejected_on_all_admin_handlers(self):
        """Operator session must get 403 on every admin-only handler."""
        import importlib
        for module_path, func_name, desc in self.ADMIN_ONLY:
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


# ══════════════════════════════════════════════════════════════════════════
# Operator handlers must reject viewer sessions
# ══════════════════════════════════════════════════════════════════════════

class TestOperatorHandlersRejectViewer(unittest.TestCase):
    """Operator-level handlers must reject viewer with 403."""

    def setUp(self):
        self.viewer_token = _inject_session("viewer")

    def tearDown(self):
        _cleanup_sessions()

    # Complete list of all operator-level handlers
    OPERATOR_HANDLERS = [
        # ── VM (8 handlers) ──
        ("freq.api.vm", "handle_vm_power", "VM power"),
        ("freq.api.vm", "handle_vm_snapshot", "VM snapshot"),
        ("freq.api.vm", "handle_vm_resize", "VM resize"),
        ("freq.api.vm", "handle_vm_rename", "VM rename"),
        ("freq.api.vm", "handle_vm_delete_snapshot", "VM delete snapshot"),
        ("freq.api.vm", "handle_vm_add_nic", "VM add NIC"),
        ("freq.api.vm", "handle_vm_change_ip", "VM change IP"),
        ("freq.api.vm", "handle_vm_tag", "VM tag"),
        # ── CT (8 handlers) ──
        ("freq.api.ct", "handle_ct_create", "CT create"),
        ("freq.api.ct", "handle_ct_power", "CT power"),
        ("freq.api.ct", "handle_ct_set", "CT set config"),
        ("freq.api.ct", "handle_ct_snapshot", "CT snapshot"),
        ("freq.api.ct", "handle_ct_delete_snapshot", "CT delete snapshot"),
        ("freq.api.ct", "handle_ct_clone", "CT clone"),
        ("freq.api.ct", "handle_ct_migrate", "CT migrate"),
        ("freq.api.ct", "handle_ct_resize", "CT resize"),
        ("freq.api.ct", "handle_ct_exec", "CT exec"),
        # ── Docker (5 handlers) ──
        ("freq.api.docker_api", "handle_containers_delete", "Container delete"),
        ("freq.api.docker_api", "handle_containers_add", "Container add"),
        ("freq.api.docker_api", "handle_containers_edit", "Container edit"),
        ("freq.api.docker_api", "handle_containers_compose_up", "Docker Compose up"),
        ("freq.api.docker_api", "handle_containers_compose_down", "Docker Compose down"),
        # ── DR (1 handler) ──
        ("freq.api.dr", "handle_backup_create", "Backup create"),
        # ── Terminal (3 handlers) ──
        ("freq.api.terminal", "handle_terminal_open", "Terminal open"),
        ("freq.api.terminal", "handle_terminal_close", "Terminal close"),
        ("freq.api.terminal", "handle_terminal_resize", "Terminal resize"),
        # ── Observability (1 handler) ──
        ("freq.api.observe", "handle_trend_snapshot", "Trend snapshot"),
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
