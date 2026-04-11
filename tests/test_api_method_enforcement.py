"""Batch regression tests for POST enforcement on freq/api/ domain modules.

Proves: every mutating handler in freq/api/*.py rejects GET with 405.
These handlers all use require_post() or _require_post() as their first
gate. This test file exercises each one directly with command="GET" and
asserts 405.

Complementary to test_method_enforcement.py which covers serve.py handlers.
"""
import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_handler(path="/", method="GET"):
    """Minimal handler mock for method enforcement tests."""
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


# ══════════════════════════════════════════════════════════════════════════
# Unit test: require_post() helper itself
# ══════════════════════════════════════════════════════════════════════════

class TestRequirePostHelper(unittest.TestCase):
    """The shared require_post() helper must reject GET and pass POST."""

    def test_get_rejected_with_405(self):
        from freq.api.helpers import require_post
        h = _make_handler(method="GET")
        rejected = require_post(h, "Test action")
        self.assertTrue(rejected, "require_post must return True for GET")
        self.assertEqual(h._status, 405)
        data = _get_json(h)
        self.assertIn("requires POST", data["error"])

    def test_post_passes(self):
        from freq.api.helpers import require_post
        h = _make_handler(method="POST")
        rejected = require_post(h, "Test action")
        self.assertFalse(rejected, "require_post must return False for POST")
        self.assertIsNone(h._status, "POST should not set any status")


# ══════════════════════════════════════════════════════════════════════════
# Batch: every mutating handler across all freq/api/ modules
# ══════════════════════════════════════════════════════════════════════════

# Each entry: (module_path, function_name, description)
# All these handlers call require_post() as their first gate.
MUTATING_HANDLERS = [
    # ── VM operations ──
    ("freq.api.vm", "handle_vm_create", "VM create"),
    ("freq.api.vm", "handle_vm_destroy", "VM destroy"),
    ("freq.api.vm", "handle_vm_snapshot", "VM snapshot"),
    ("freq.api.vm", "handle_vm_resize", "VM resize"),
    ("freq.api.vm", "handle_vm_power", "VM power"),
    ("freq.api.vm", "handle_vm_template", "VM template"),
    ("freq.api.vm", "handle_vm_rename", "VM rename"),
    ("freq.api.vm", "handle_vm_delete_snapshot", "VM delete snapshot"),
    ("freq.api.vm", "handle_vm_change_id", "VM change ID"),
    ("freq.api.vm", "handle_vm_add_nic", "VM add NIC"),
    ("freq.api.vm", "handle_vm_clear_nics", "VM clear NICs"),
    ("freq.api.vm", "handle_vm_change_ip", "VM change IP"),
    ("freq.api.vm", "handle_vm_add_disk", "VM add disk"),
    ("freq.api.vm", "handle_vm_tag", "VM tag"),
    ("freq.api.vm", "handle_vm_clone", "VM clone"),
    ("freq.api.vm", "handle_vm_migrate", "VM migrate"),
    ("freq.api.vm", "handle_rollback", "VM rollback"),
    # ── Container operations ──
    ("freq.api.ct", "handle_ct_create", "CT create"),
    ("freq.api.ct", "handle_ct_destroy", "CT destroy"),
    ("freq.api.ct", "handle_ct_power", "CT power"),
    ("freq.api.ct", "handle_ct_set", "CT set config"),
    ("freq.api.ct", "handle_ct_snapshot", "CT snapshot"),
    ("freq.api.ct", "handle_ct_rollback", "CT rollback"),
    ("freq.api.ct", "handle_ct_delete_snapshot", "CT delete snapshot"),
    ("freq.api.ct", "handle_ct_clone", "CT clone"),
    ("freq.api.ct", "handle_ct_migrate", "CT migrate"),
    ("freq.api.ct", "handle_ct_resize", "CT resize"),
    ("freq.api.ct", "handle_ct_exec", "CT exec"),
    # ── Firewall: pfSense ──
    ("freq.api.fw", "handle_pfsense_service", "pfSense service"),
    ("freq.api.fw", "handle_pfsense_dhcp_reservation", "pfSense DHCP"),
    ("freq.api.fw", "handle_pfsense_config_backup", "pfSense backup"),
    ("freq.api.fw", "handle_pfsense_reboot", "pfSense reboot"),
    ("freq.api.fw", "handle_pfsense_rules", "pfSense rules"),
    ("freq.api.fw", "handle_pfsense_nat", "pfSense NAT"),
    ("freq.api.fw", "handle_pfsense_wg_peer", "pfSense WireGuard"),
    ("freq.api.fw", "handle_pfsense_updates", "pfSense updates"),
    # ── Firewall: OPNsense ──
    ("freq.api.opnsense", "handle_opnsense_service_action", "OPNsense service"),
    ("freq.api.opnsense", "handle_opnsense_rule_add", "OPNsense rule add"),
    ("freq.api.opnsense", "handle_opnsense_rule_delete", "OPNsense rule delete"),
    ("freq.api.opnsense", "handle_opnsense_dhcp_add", "OPNsense DHCP add"),
    ("freq.api.opnsense", "handle_opnsense_dhcp_delete", "OPNsense DHCP delete"),
    ("freq.api.opnsense", "handle_opnsense_dns_add", "OPNsense DNS add"),
    ("freq.api.opnsense", "handle_opnsense_dns_delete", "OPNsense DNS delete"),
    ("freq.api.opnsense", "handle_opnsense_wg_add", "OPNsense WireGuard"),
    ("freq.api.opnsense", "handle_opnsense_reboot", "OPNsense reboot"),
    # ── Storage: TrueNAS ──
    ("freq.api.store", "handle_truenas_snapshot", "TrueNAS snapshot"),
    ("freq.api.store", "handle_truenas_service", "TrueNAS service"),
    ("freq.api.store", "handle_truenas_scrub", "TrueNAS scrub"),
    ("freq.api.store", "handle_truenas_reboot", "TrueNAS reboot"),
    ("freq.api.store", "handle_truenas_dataset", "TrueNAS dataset"),
    ("freq.api.store", "handle_truenas_share", "TrueNAS share"),
    ("freq.api.store", "handle_truenas_replication", "TrueNAS replication"),
    ("freq.api.store", "handle_truenas_app", "TrueNAS app"),
    # ── Storage: Synology ──
    ("freq.api.synology", "handle_synology_service", "Synology service"),
    ("freq.api.synology", "handle_synology_reboot", "Synology reboot"),
    # ── Network ──
    ("freq.api.net", "handle_switch_vlan_create", "VLAN create"),
    ("freq.api.net", "handle_switch_vlan_delete", "VLAN delete"),
    ("freq.api.net", "handle_switch_acl", "ACL management"),
    # ── Fleet ──
    ("freq.api.fleet", "handle_exec", "Fleet exec"),
    ("freq.api.fleet", "handle_federation_register", "Federation register"),
    ("freq.api.fleet", "handle_federation_unregister", "Federation unregister"),
    ("freq.api.fleet", "handle_federation_poll", "Federation poll"),
    ("freq.api.fleet", "handle_federation_toggle", "Federation toggle"),
    ("freq.api.fleet", "handle_deploy_agent", "Agent deploy"),
    # ── DR ──
    ("freq.api.dr", "handle_backup_create", "Backup create"),
    ("freq.api.dr", "handle_backup_restore", "Backup restore"),
    # ── Automation ──
    ("freq.api.auto", "handle_rules_create", "Rule create"),
    ("freq.api.auto", "handle_rules_update", "Rule update"),
    ("freq.api.auto", "handle_rules_delete", "Rule delete"),
    ("freq.api.auto", "handle_playbooks_run", "Playbook run"),
    ("freq.api.auto", "handle_playbooks_step", "Playbook step"),
    ("freq.api.auto", "handle_playbooks_create", "Playbook create"),
    ("freq.api.auto", "handle_chaos_run", "Chaos experiment"),
    # ── State / GitOps ──
    ("freq.api.state", "handle_policy_fix", "Policy fix"),
    ("freq.api.state", "handle_gitops_sync", "GitOps sync"),
    ("freq.api.state", "handle_gitops_apply", "GitOps apply"),
    ("freq.api.state", "handle_gitops_rollback", "GitOps rollback"),
    ("freq.api.state", "handle_gitops_init", "GitOps init"),
    # ── Security / Vault ──
    ("freq.api.secure", "handle_vault_set", "Vault set"),
    ("freq.api.secure", "handle_vault_delete", "Vault delete"),
    # ── Users ──
    ("freq.api.user", "handle_user_create", "User create"),
    ("freq.api.user", "handle_user_promote", "User promote"),
    ("freq.api.user", "handle_user_demote", "User demote"),
    # ── IPMI / Redfish ──
    ("freq.api.ipmi", "handle_ipmi_power", "IPMI power"),
    ("freq.api.ipmi", "handle_ipmi_boot", "IPMI boot"),
    ("freq.api.ipmi", "handle_ipmi_sel_clear", "IPMI SEL clear"),
    ("freq.api.redfish", "handle_redfish_power", "Redfish power"),
    # ── Docker ──
    ("freq.api.docker_api", "handle_containers_delete", "Container delete"),
    ("freq.api.docker_api", "handle_containers_add", "Container add"),
    ("freq.api.docker_api", "handle_containers_edit", "Container edit"),
    ("freq.api.docker_api", "handle_containers_compose_up", "Docker Compose up"),
    ("freq.api.docker_api", "handle_containers_compose_down", "Docker Compose down"),
    # ── Terminal ──
    ("freq.api.terminal", "handle_terminal_open", "Terminal open"),
    ("freq.api.terminal", "handle_terminal_close", "Terminal close"),
    ("freq.api.terminal", "handle_terminal_resize", "Terminal resize"),
    # ── Observability ──
    ("freq.api.observe", "handle_capacity_snapshot", "Capacity snapshot"),
    # ── Benchmark / Hardware ──
    ("freq.api.bench", "handle_wol", "Wake-on-LAN"),
    ("freq.api.bench", "handle_bench_run", "Benchmark run"),
    ("freq.api.bench", "handle_bench_netspeed", "Network speed test"),
    ("freq.api.hw", "handle_gwipe", "GWIPE operation"),
    # ── Backup verify ──
    ("freq.api.backup_verify", "handle_backup_verify", "Backup verify"),
]


class TestApiModulesRejectGet(unittest.TestCase):
    """Every mutating handler in freq/api/ must reject GET with 405."""

    pass


def _make_test(module_path, func_name, description):
    """Generate a test method for a single handler."""
    def test_method(self):
        import importlib
        mod = importlib.import_module(module_path)
        handler_fn = getattr(mod, func_name, None)
        if handler_fn is None:
            self.skipTest(f"{module_path}.{func_name} not found")
        h = _make_handler(method="GET")
        handler_fn(h)
        self.assertEqual(
            h._status, 405,
            f"{module_path}.{func_name} ({description}) must reject GET with 405, got {h._status}"
        )
    test_method.__doc__ = f"GET {description} must return 405"
    return test_method


# Dynamically add test methods for each handler
for _module, _func, _desc in MUTATING_HANDLERS:
    _test_name = f"test_{_func}_rejects_get"
    setattr(TestApiModulesRejectGet, _test_name, _make_test(_module, _func, _desc))


if __name__ == "__main__":
    unittest.main()
