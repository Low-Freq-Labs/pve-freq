"""Security tests — input validation and injection prevention.

Phase 1 of v2.1 hardening: validates that shell_safe_name, bay_device,
and all VM command input gates reject malicious input before it reaches
shell interpolation.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.core import validate


# ── shell_safe_name ─────────────────────────────────────────────────────

class TestShellSafeName(unittest.TestCase):
    """VM names must be safe for shell interpolation."""

    def test_simple_name(self):
        assert validate.shell_safe_name("my-vm") is True

    def test_dotted_name(self):
        assert validate.shell_safe_name("vm01.prod") is True

    def test_underscore_name(self):
        assert validate.shell_safe_name("test_vm") is True

    def test_numeric_start(self):
        assert validate.shell_safe_name("100-web") is True

    def test_single_char(self):
        assert validate.shell_safe_name("a") is True

    def test_max_length(self):
        assert validate.shell_safe_name("a" * 63) is True

    def test_injection_semicolon(self):
        assert validate.shell_safe_name("vm'; rm -rf /") is False

    def test_injection_dollar(self):
        assert validate.shell_safe_name("$(whoami)") is False

    def test_injection_backtick(self):
        assert validate.shell_safe_name("`id`") is False

    def test_injection_pipe(self):
        assert validate.shell_safe_name("vm|cat /etc/passwd") is False

    def test_injection_ampersand(self):
        assert validate.shell_safe_name("vm&reboot") is False

    def test_space(self):
        assert validate.shell_safe_name("my vm") is False

    def test_empty(self):
        assert validate.shell_safe_name("") is False

    def test_too_long(self):
        assert validate.shell_safe_name("a" * 64) is False

    def test_starts_with_dot(self):
        assert validate.shell_safe_name(".hidden") is False

    def test_starts_with_hyphen(self):
        assert validate.shell_safe_name("-flag") is False

    def test_newline(self):
        assert validate.shell_safe_name("vm\nid") is False

    def test_slash(self):
        assert validate.shell_safe_name("vm/name") is False


# ── bay_device ──────────────────────────────────────────────────────────

class TestBayDevice(unittest.TestCase):
    """Block device names for gwipe path traversal prevention."""

    def test_sda(self):
        assert validate.bay_device("sda") is True

    def test_nvme(self):
        assert validate.bay_device("nvme0n1") is True

    def test_sdb1(self):
        # Partition names don't have dots — this is fine
        assert validate.bay_device("sdb1") is True

    def test_path_traversal(self):
        assert validate.bay_device("../etc/passwd") is False

    def test_slash(self):
        assert validate.bay_device("sda/../../etc") is False

    def test_dot_dot(self):
        assert validate.bay_device("..") is False

    def test_empty(self):
        assert validate.bay_device("") is False

    def test_uppercase(self):
        assert validate.bay_device("SDA") is False

    def test_too_long(self):
        assert validate.bay_device("a" * 33) is False

    def test_starts_with_number(self):
        assert validate.bay_device("1sda") is False


# ── VM command input gates ──────────────────────────────────────────────

def _make_cfg():
    """Create a minimal FreqConfig mock."""
    cfg = MagicMock()
    cfg.pve_nodes = ["192.168.255.1"]
    cfg.ssh_key_path = "/tmp/test_key"
    cfg.ssh_connect_timeout = 5
    cfg.vm_cpu = "host"
    cfg.vm_machine = "q35"
    cfg.vm_scsihw = "virtio-scsi-pci"
    cfg.vm_default_cores = 2
    cfg.vm_default_ram = 2048
    cfg.vm_default_disk = 32
    cfg.vm_gateway = "192.168.10.1"
    cfg.nic_bridge = "vmbr0"
    cfg.pve_storage = {}
    # R-PVEFREQ-BOOTSTRAP-UNTOUCHED-20260415D: freq-ops is bootstrap-only
    # and cannot be the managed service account. Use the canonical default.
    cfg.ssh_service_account = "freq-admin"
    cfg.protected_vmids = []
    cfg.protected_ranges = []
    return cfg


class TestCreateRejectsBadName(unittest.TestCase):
    """cmd_create must reject invalid names before calling _pve_cmd."""

    @patch("freq.modules.vm._find_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._pve_cmd")
    def test_injection_name_rejected(self, mock_pve, mock_node):
        from freq.modules.vm import cmd_create
        cfg = _make_cfg()
        args = SimpleNamespace(
            name="vm'; rm -rf /", image=None, node=None,
            cores=2, ram=2048, disk=32, vmid=5001, yes=True
        )
        result = cmd_create(cfg, None, args)
        assert result == 1
        mock_pve.assert_not_called()

    @patch("freq.modules.vm._find_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._pve_cmd")
    def test_valid_name_proceeds(self, mock_pve, mock_node):
        from freq.modules.vm import cmd_create
        cfg = _make_cfg()
        mock_pve.return_value = ("", True)
        args = SimpleNamespace(
            name="web-01", image=None, node=None,
            cores=2, ram=2048, disk=32, vmid=5001, yes=True
        )
        result = cmd_create(cfg, None, args)
        assert result == 0
        assert mock_pve.called


class TestCloneRejectsBadInput(unittest.TestCase):
    """cmd_clone must reject invalid names, IPs, and VLANs."""

    @patch("freq.modules.vm._find_vm_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._find_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._pve_cmd")
    def test_bad_name_rejected(self, mock_pve, mock_node, mock_vm_node):
        from freq.modules.vm import cmd_clone
        cfg = _make_cfg()
        args = SimpleNamespace(
            source="100", name="$(whoami)", vmid=5002,
            ip=None, vlan=None, yes=True
        )
        result = cmd_clone(cfg, None, args)
        assert result == 1
        mock_pve.assert_not_called()

    @patch("freq.modules.vm._find_vm_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._find_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._pve_cmd")
    def test_bad_vlan_rejected(self, mock_pve, mock_node, mock_vm_node):
        from freq.modules.vm import cmd_clone
        cfg = _make_cfg()
        args = SimpleNamespace(
            source="100", name="clone-ok", vmid=5002,
            ip=None, vlan="9999", yes=True
        )
        result = cmd_clone(cfg, None, args)
        assert result == 1
        mock_pve.assert_not_called()

    @patch("freq.modules.vm._find_vm_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._find_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._pve_cmd")
    def test_bad_ip_rejected(self, mock_pve, mock_node, mock_vm_node):
        from freq.modules.vm import cmd_clone
        cfg = _make_cfg()
        args = SimpleNamespace(
            source="100", name="clone-ok", vmid=5002,
            ip="not.an.ip", vlan=None, yes=True
        )
        result = cmd_clone(cfg, None, args)
        assert result == 1
        mock_pve.assert_not_called()

    @patch("freq.modules.vm._find_vm_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._find_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._pve_cmd")
    def test_valid_vlan_accepted(self, mock_pve, mock_node, mock_vm_node):
        from freq.modules.vm import cmd_clone
        cfg = _make_cfg()
        cfg.protected_vmids = []
        cfg.protected_ranges = []
        mock_pve.return_value = ("", True)
        args = SimpleNamespace(
            source="100", name="clone-ok", vmid=5002,
            ip=None, vlan="10", yes=True
        )
        result = cmd_clone(cfg, None, args)
        # Should proceed past validation (clone call happens)
        assert mock_pve.called


class TestRenameRejectsBadName(unittest.TestCase):
    """cmd_rename must reject invalid names."""

    @patch("freq.modules.vm._find_vm_node", return_value="192.168.255.1")
    @patch("freq.modules.vm._pve_cmd")
    def test_injection_rejected(self, mock_pve, mock_node):
        from freq.modules.vm import cmd_rename
        cfg = _make_cfg()
        args = SimpleNamespace(target="5001", name="`reboot`")
        result = cmd_rename(cfg, None, args)
        assert result == 1
        mock_pve.assert_not_called()


class TestNicAddRejectsBadInput(unittest.TestCase):
    """_nic_add must reject invalid IPs and VLANs."""

    def test_bad_ip_rejected(self):
        from freq.modules.vm import _nic_add
        cfg = _make_cfg()
        args = SimpleNamespace(target="5001", ip="999.999.999.999", gw=None, vlan=None)
        result = _nic_add(cfg, args)
        assert result == 1

    def test_bad_vlan_rejected(self):
        from freq.modules.vm import _nic_add
        cfg = _make_cfg()
        args = SimpleNamespace(target="5001", ip="192.168.10.50", gw=None, vlan="99999")
        result = _nic_add(cfg, args)
        assert result == 1


class TestNicChangeIpRejectsBadInput(unittest.TestCase):
    """_nic_change_ip must reject invalid IPs and VLANs."""

    def test_bad_ip_rejected(self):
        from freq.modules.vm import _nic_change_ip
        cfg = _make_cfg()
        args = SimpleNamespace(target="5001", ip="not-an-ip", gw=None, nic_index=0, vlan=None)
        result = _nic_change_ip(cfg, args)
        assert result == 1

    def test_bad_vlan_rejected(self):
        from freq.modules.vm import _nic_change_ip
        cfg = _make_cfg()
        args = SimpleNamespace(target="5001", ip="192.168.10.50", gw=None, nic_index=0, vlan="-1")
        result = _nic_change_ip(cfg, args)
        assert result == 1


# ── gwipe bay_device validation ─────────────────────────────────────────

class TestGwipeBayValidation(unittest.TestCase):
    """gwipe must reject path traversal in bay targets."""

    def test_traversal_rejected(self):
        from freq.modules.gwipe import cmd_gwipe
        cfg = MagicMock()
        cfg.vault_file = "/tmp/nonexistent"
        args = SimpleNamespace(
            host="10.0.0.1", key="testkey",
            action="wipe", target="../etc/passwd"
        )
        result = cmd_gwipe(cfg, None, args)
        assert result == 1

    def test_valid_bay_passes(self):
        from freq.modules.gwipe import cmd_gwipe
        cfg = MagicMock()
        args = SimpleNamespace(
            host="10.0.0.1", key="testkey",
            action="status", target=None
        )
        # status action with no target — should not reject
        with patch("freq.modules.gwipe._gwipe_api", return_value=({"version": "1"}, None)):
            result = cmd_gwipe(cfg, None, args)
            assert result == 0


# ── Policy sed escaping ─────────────────────────────────────────────────

class TestPolicySedEscaping(unittest.TestCase):
    """Policy fix_commands must escape regex metacharacters in keys."""

    def test_escape_sed_dots(self):
        from freq.engine.policy import _escape_sed
        assert _escape_sed("net.ipv4.ip_forward") == r"net\.ipv4\.ip_forward"

    def test_escape_sed_plain(self):
        from freq.engine.policy import _escape_sed
        assert _escape_sed("PermitRootLogin") == "PermitRootLogin"

    def test_escape_sed_brackets(self):
        from freq.engine.policy import _escape_sed
        assert _escape_sed("value[0]") == r"value\[0\]"

    def test_fix_commands_escapes_key(self):
        from freq.engine.policy import PolicyExecutor
        policy = {
            "name": "test-policy",
            "scope": ["pve"],
            "resources": [{
                "type": "file_line",
                "path": "/etc/sysctl.conf",
                "applies_to": ["pve"],
                "entries": {"net.ipv4.ip_forward": "1"},
            }],
        }
        executor = PolicyExecutor(policy)
        host = SimpleNamespace(htype="pve")
        findings = executor.compare({"net.ipv4.ip_forward": "0"}, {"net.ipv4.ip_forward": "1"})
        commands = executor.fix_commands(host, findings)
        assert len(commands) == 1
        # The grep and sed patterns should have escaped dots
        assert r"net\.ipv4\.ip_forward" in commands[0]


class TestPolicyMissingName(unittest.TestCase):
    """PolicyExecutor must raise ValueError when 'name' is missing."""

    def test_missing_name_raises(self):
        from freq.engine.policy import PolicyExecutor
        with self.assertRaisesRegex(ValueError, "missing required 'name'"):
            PolicyExecutor({})
