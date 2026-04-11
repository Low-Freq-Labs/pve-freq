"""FREQ hosts sync tests — _hosts_sync() logic, TOML format, label sanitization, backup, diff.

Tests the auto-sync pipeline that populates hosts.toml (TOML format) from
PVE API + fleet-boundaries.toml. All SSH/PVE calls are mocked.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.core.types import Host, PhysicalDevice, FleetBoundaries, PVENode


# ── Helpers ──────────────────────────────────────────────────────────

def _make_cfg(tmpdir, hosts=None, pve_nodes=None, pve_node_names=None, fleet_boundaries=None):
    """Build a minimal FreqConfig-like object for _hosts_sync."""
    from freq.core.config import FreqConfig
    cfg = FreqConfig()
    cfg.hosts_file = os.path.join(tmpdir, "hosts.toml")
    cfg.hosts = hosts or []
    cfg.pve_nodes = pve_nodes or []
    cfg.pve_node_names = pve_node_names or []
    cfg.conf_dir = tmpdir
    cfg.ssh_key_path = "/tmp/fake-key"
    cfg.fleet_boundaries = fleet_boundaries or FleetBoundaries()
    # Write initial hosts.toml in TOML format (v1 contract)
    from freq.core.config import save_hosts_toml
    if cfg.hosts:
        save_hosts_toml(cfg.hosts_file, cfg.hosts)
    else:
        with open(cfg.hosts_file, "w") as f:
            f.write("# FREQ Fleet Registry\n")
    return cfg


def _fake_ssh_result(stdout="", stderr="", returncode=0):
    """Create a mock CmdResult."""
    @dataclass
    class FakeResult:
        stdout: str = ""
        stderr: str = ""
        returncode: int = 0
        duration: float = 0.1
    return FakeResult(stdout=stdout, stderr=stderr, returncode=returncode)


def _pve_cluster_json(vms):
    """Build JSON like pvesh get /cluster/resources returns."""
    return json.dumps(vms)


def _qm_agent_json(ips):
    """Build JSON like qm agent network-get-interfaces returns (raw list format).

    Accepts a flat list of IPs (all on eth0) or a list of (name, ip) tuples
    for multi-NIC simulation.
    """
    ifaces = [{"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4", "prefix": 8}]}]
    if ips:
        if isinstance(ips[0], tuple):
            # Multi-NIC: list of (iface_name, ip)
            nic_map = {}
            for name, ip in ips:
                nic_map.setdefault(name, []).append(ip)
            for name, addrs in nic_map.items():
                ip_addrs = [{"ip-address": ip, "ip-address-type": "ipv4", "prefix": 24} for ip in addrs]
                ifaces.append({"name": name, "ip-addresses": ip_addrs})
        else:
            # Simple: all IPs on eth0
            addrs = [{"ip-address": ip, "ip-address-type": "ipv4", "prefix": 24} for ip in ips]
            ifaces.append({"name": "eth0", "ip-addresses": addrs})
    return json.dumps(ifaces)


# ═══════════════════════════════════════════════════════════════════
# _hosts_sync() tests
# ═══════════════════════════════════════════════════════════════════

class TestHostsSync(unittest.TestCase):
    """Test the PVE + fleet-boundaries → hosts.toml sync pipeline."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-sync-")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_hosts_conf(self, cfg):
        """Read hosts.toml and return non-comment, non-empty lines."""
        with open(cfg.hosts_file) as f:
            return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

    def _read_hosts_conf_raw(self, cfg):
        """Read full hosts.toml content."""
        with open(cfg.hosts_file) as f:
            return f.read()

    def _read_hosts_toml(self, cfg):
        """Parse the TOML hosts file and return list of host dicts."""
        import tomllib
        with open(cfg.hosts_file, "rb") as f:
            data = tomllib.load(f)
        return data.get("host", [])

    # ── PVE VM discovery ──

    @patch("freq.core.ssh.run")
    def test_discovers_new_vm_from_pve(self, mock_ssh):
        """New VM found in PVE gets added to hosts.toml."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 101, "name": "plex", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 101" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.30"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        rc = _hosts_sync(cfg)
        self.assertEqual(rc, 0)

        # Output is now TOML format — parse and check IPs
        content = self._read_hosts_conf_raw(cfg)
        self.assertIn('ip = "192.168.255.30"', content)

    @patch("freq.core.ssh.run")
    def test_preserves_existing_host_metadata(self, mock_ssh):
        """Existing host keeps its label/type/groups when re-discovered."""
        existing = [Host(ip="192.168.255.30", label="plex", htype="docker", groups="prod,media")]
        cfg = _make_cfg(self.tmpdir, hosts=existing, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 101, "name": "plex-server", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 101" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.30"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        # Original label "plex" preserved, not overwritten with PVE name "plex-server"
        self.assertIn("plex", content)
        self.assertIn("docker", content)
        self.assertIn("prod,media", content)

    @patch("freq.core.ssh.run")
    def test_skips_vms_without_guest_agent(self, mock_ssh):
        """VMs where qm agent fails are skipped (no crash)."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 900, "name": "nexus", "node": "pve02", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent" in command:
                return _fake_ssh_result(stdout="", returncode=1)
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        rc = _hosts_sync(cfg)
        self.assertEqual(rc, 0)

    @patch("freq.core.ssh.run")
    def test_skips_stopped_vms(self, mock_ssh):
        """Stopped VMs are not queried for IP."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 802, "name": "vault", "node": "pve01", "status": "stopped", "type": "qemu"},
        ])

        call_commands = []
        def ssh_side_effect(host, command, **kwargs):
            call_commands.append(command)
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        # Should NOT have called qm agent for stopped VM
        agent_calls = [c for c in call_commands if "qm agent" in c]
        self.assertEqual(len(agent_calls), 0)

    # ── Fleet boundaries merge ──

    @patch("freq.core.ssh.run")
    def test_merges_physical_devices_from_fleet_boundaries(self, mock_ssh):
        """Physical devices from fleet-boundaries.toml get added."""
        fb = FleetBoundaries()
        fb.physical = {
            "idrac_pve01": PhysicalDevice(key="idrac_pve01", ip="192.168.255.11", label="iDRAC - PVE01", device_type="idrac"),
            "switch": PhysicalDevice(key="switch", ip="192.168.255.5", label="gigecolo", device_type="switch"),
        }
        cfg = _make_cfg(self.tmpdir, fleet_boundaries=fb, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout="[]")
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        self.assertIn("192.168.255.11", content)
        self.assertIn("idrac", content)
        self.assertIn("192.168.255.5", content)
        self.assertIn("switch", content)

    @patch("freq.core.ssh.run")
    def test_label_sanitization_spaces_to_hyphens(self, mock_ssh):
        """Physical device labels with spaces get sanitized to hyphens."""
        fb = FleetBoundaries()
        fb.physical = {
            "idrac_truenas": PhysicalDevice(key="idrac_truenas", ip="192.168.255.10", label="iDRAC - TRUENAS", device_type="idrac"),
        }
        cfg = _make_cfg(self.tmpdir, fleet_boundaries=fb, pve_nodes=[], pve_node_names=[])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout="[]")
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        # Label should be sanitized — output is TOML format now
        self.assertIn('ip = "192.168.255.10"', content)
        self.assertIn('label = "idrac---truenas"', content)

    # ── Backup creation ──

    @patch("freq.core.ssh.run")
    def test_creates_backup_before_write(self, mock_ssh):
        """hosts.toml.bak is created before overwriting."""
        existing = [Host(ip="192.168.255.30", label="plex", htype="docker", groups="prod,media")]
        cfg = _make_cfg(self.tmpdir, hosts=existing, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 999, "name": "new-vm", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 999" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.10.99"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        backup_path = cfg.hosts_file + ".bak"
        self.assertTrue(os.path.isfile(backup_path))

        # Backup should contain original content
        with open(backup_path) as f:
            backup_content = f.read()
        self.assertIn("plex", backup_content)

    # ── Manual host preservation ──

    @patch("freq.core.ssh.run")
    def test_preserves_manually_added_hosts(self, mock_ssh):
        """Hosts in hosts.toml but not in PVE or fleet-boundaries are kept."""
        existing = [
            Host(ip="192.168.255.8", label="gigenet", htype="linux", groups="prod,network"),
        ]
        cfg = _make_cfg(self.tmpdir, hosts=existing, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout="[]")
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        self.assertIn("gigenet", content)
        self.assertIn("192.168.255.8", content)

    # ── Dry run ──

    @patch("freq.core.ssh.run")
    def test_dry_run_does_not_modify_file(self, mock_ssh):
        """--dry-run reports changes but doesn't write hosts.toml."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])
        original_content = self._read_hosts_conf_raw(cfg)

        cluster_json = _pve_cluster_json([
            {"vmid": 101, "name": "plex", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 101" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.30"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        rc = _hosts_sync(cfg, dry_run=True)
        self.assertEqual(rc, 0)

        # File should be unchanged
        after_content = self._read_hosts_conf_raw(cfg)
        self.assertEqual(original_content, after_content)

        # No backup created
        self.assertFalse(os.path.isfile(cfg.hosts_file + ".bak"))

    # ── PVE node addition ──

    @patch("freq.core.ssh.run")
    def test_adds_pve_nodes_themselves(self, mock_ssh):
        """PVE hypervisor nodes are added to hosts.toml."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26", "192.168.255.27"], pve_node_names=["pve01", "pve02"])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout="[]")
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        self.assertIn("192.168.255.26", content)
        self.assertIn("pve01", content)
        self.assertIn("192.168.255.27", content)
        self.assertIn("pve02", content)

    # ── No-op when up to date ──

    @patch("freq.core.ssh.run")
    def test_no_changes_when_already_synced(self, mock_ssh):
        """When all hosts are already in hosts.toml, returns 0 with no write."""
        existing = [Host(ip="192.168.255.26", label="pve01", htype="pve", groups="prod,cluster")]
        cfg = _make_cfg(self.tmpdir, hosts=existing, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])
        mtime_before = os.path.getmtime(cfg.hosts_file)

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout="[]")
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        rc = _hosts_sync(cfg)
        self.assertEqual(rc, 0)

        # No backup should be created when nothing changed
        self.assertFalse(os.path.isfile(cfg.hosts_file + ".bak"))

    # ── PVE API failure graceful handling ──

    @patch("freq.core.ssh.run")
    def test_pve_api_failure_still_preserves_existing(self, mock_ssh):
        """If PVE API fails, existing hosts + fleet boundaries still written."""
        existing = [Host(ip="192.168.255.30", label="plex", htype="docker", groups="prod,media")]
        fb = FleetBoundaries()
        fb.physical = {
            "switch": PhysicalDevice(key="switch", ip="192.168.255.5", label="gigecolo", device_type="switch"),
        }
        cfg = _make_cfg(self.tmpdir, hosts=existing, fleet_boundaries=fb,
                        pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        def ssh_side_effect(host, command, **kwargs):
            # PVE API call fails
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        # Existing host preserved
        self.assertIn("plex", content)
        # Fleet boundary device added
        self.assertIn("gigecolo", content)

    # ── Auto-classify VM type from name ──

    @patch("freq.core.ssh.run")
    def test_auto_classifies_docker_vm_by_name(self, mock_ssh):
        """VM named 'arr-stack' is classified as docker type."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 102, "name": "arr-stack", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 102" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.31"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        self.assertIn("docker", content)
        self.assertIn("arr-stack", content)

    # ── VLAN-based group assignment ──

    @patch("freq.core.ssh.run")
    def test_auto_assigns_prod_group_for_255_vlan(self, mock_ssh):
        """VM on .255. subnet gets 'prod' group."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 101, "name": "newvm", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 101" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.99"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        self.assertIn("prod", content)

    @patch("freq.core.ssh.run")
    def test_auto_assigns_lab_group_for_10_vlan(self, mock_ssh):
        """VM on .10. subnet gets 'lab' group."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 5001, "name": "lab-test", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 5001" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.10.70"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        self.assertIn("lab", content)

    # ── Output format ──

    @patch("freq.core.ssh.run")
    def test_output_has_toml_structure(self, mock_ssh):
        """Written hosts file uses TOML format with [[host]] entries."""
        existing = [
            Host(ip="192.168.255.30", label="plex", htype="docker", groups="prod,media"),
            Host(ip="192.168.10.60", label="lab-debian12", htype="linux", groups="lab,distro"),
        ]
        cfg = _make_cfg(self.tmpdir, hosts=existing, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 999, "name": "new-prod", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 999" in command:
                return _fake_ssh_result(stdout=_qm_agent_json(["192.168.255.99"]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        # TOML format: header comment + [[host]] entries
        self.assertIn("# FREQ Fleet Registry", content)
        self.assertIn("[[host]]", content)
        # Both existing and new hosts should be present
        self.assertIn('label = "plex"', content)
        self.assertIn('label = "lab-debian12"', content)


    # ── Multi-IP tracking ──

    @patch("freq.core.ssh.run")
    def test_multi_ip_written_to_hosts_conf(self, mock_ssh):
        """VM with multiple NICs has all IPs written as column 5."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 101, "name": "plex", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 101" in command:
                # Plex has MGMT + Public + Storage NICs
                return _fake_ssh_result(stdout=_qm_agent_json([
                    ("eth0", "192.168.255.30"),
                    ("eth1", "192.168.5.30"),
                    ("eth2", "192.168.25.30"),
                ]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        # All three real IPs should appear in the all_ips column
        self.assertIn("192.168.255.30", content)
        self.assertIn("192.168.5.30", content)
        self.assertIn("192.168.25.30", content)

    @patch("freq.core.ssh.run")
    def test_multi_ip_filters_docker_bridge(self, mock_ssh):
        """Docker bridge IPs (172.x) are excluded from all_ips."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 101, "name": "plex", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 101" in command:
                return _fake_ssh_result(stdout=_qm_agent_json([
                    ("eth0", "192.168.255.30"),
                    ("docker0", "172.17.0.1"),
                ]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        content = self._read_hosts_conf_raw(cfg)
        self.assertIn("192.168.255.30", content)
        self.assertNotIn("172.17.0.1", content)

    @patch("freq.core.ssh.run")
    def test_multi_ip_prefers_mgmt_vlan_as_primary(self, mock_ssh):
        """Primary IP (column 1) should be on management VLAN (same subnet as PVE nodes)."""
        cfg = _make_cfg(self.tmpdir, pve_nodes=["192.168.255.26"], pve_node_names=["pve01"])

        cluster_json = _pve_cluster_json([
            {"vmid": 101, "name": "plex", "node": "pve01", "status": "running", "type": "qemu"},
        ])

        def ssh_side_effect(host, command, **kwargs):
            if "pvesh" in command:
                return _fake_ssh_result(stdout=cluster_json)
            if "qm agent 101" in command:
                # Storage NIC listed first, MGMT NIC second
                return _fake_ssh_result(stdout=_qm_agent_json([
                    ("eth0", "192.168.25.30"),
                    ("eth1", "192.168.255.30"),
                ]))
            return _fake_ssh_result(stdout="", returncode=1)

        mock_ssh.side_effect = ssh_side_effect

        from freq.modules.hosts import _hosts_sync
        _hosts_sync(cfg)

        # Output is TOML — find the plex entry and verify its primary IP
        hosts = self._read_hosts_toml(cfg)
        plex_hosts = [h for h in hosts if h.get("label") == "plex"]
        self.assertEqual(len(plex_hosts), 1, "plex not found in hosts file")
        # Should pick MGMT VLAN IP as primary, not storage
        self.assertEqual(plex_hosts[0]["ip"], "192.168.255.30")

    # ── Backwards compatibility ──

    def test_parse_old_format_without_all_ips(self):
        """Old 4-column hosts.toml entries parse fine with empty all_ips."""
        from freq.core.config import load_hosts

        hosts_file = os.path.join(self.tmpdir, "hosts.toml")
        with open(hosts_file, "w") as f:
            f.write("192.168.255.30  plex  docker  prod,media\n")
            f.write("192.168.255.26  pve01  pve  prod,cluster\n")

        hosts = load_hosts(hosts_file)
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0].ip, "192.168.255.30")
        self.assertEqual(hosts[0].all_ips, [])
        self.assertEqual(hosts[1].all_ips, [])

    def test_parse_new_format_with_all_ips(self):
        """5-column hosts.toml entries parse all_ips correctly."""
        from freq.core.config import load_hosts

        hosts_file = os.path.join(self.tmpdir, "hosts.toml")
        with open(hosts_file, "w") as f:
            f.write("192.168.255.30  plex  docker  prod,media  192.168.255.30,192.168.5.30,192.168.25.30\n")

        hosts = load_hosts(hosts_file)
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].ip, "192.168.255.30")
        self.assertEqual(hosts[0].all_ips, ["192.168.255.30", "192.168.5.30", "192.168.25.30"])

    def test_parse_3_column_minimal_format(self):
        """Minimal 3-column entries (no groups, no all_ips) still parse."""
        from freq.core.config import load_hosts

        hosts_file = os.path.join(self.tmpdir, "hosts.toml")
        with open(hosts_file, "w") as f:
            f.write("192.168.255.30  plex  docker\n")

        hosts = load_hosts(hosts_file)
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].groups, "")
        self.assertEqual(hosts[0].all_ips, [])

    def test_parse_mixed_old_and_new_format(self):
        """Hosts file with both old and new format entries."""
        from freq.core.config import load_hosts

        hosts_file = os.path.join(self.tmpdir, "hosts.toml")
        with open(hosts_file, "w") as f:
            f.write("# Mixed format\n")
            f.write("192.168.255.30  plex  docker  prod,media  192.168.255.30,192.168.5.30\n")
            f.write("192.168.255.26  pve01  pve  prod,cluster\n")
            f.write("192.168.255.5  gigecolo  switch\n")

        hosts = load_hosts(hosts_file)
        self.assertEqual(len(hosts), 3)
        self.assertEqual(hosts[0].all_ips, ["192.168.255.30", "192.168.5.30"])
        self.assertEqual(hosts[1].all_ips, [])
        self.assertEqual(hosts[2].all_ips, [])

    # ── Cross-VLAN IP lookup ──

    def test_by_ip_finds_host_by_primary_ip(self):
        """by_ip() finds host by primary IP."""
        from freq.core.resolve import by_ip

        hosts = [Host(ip="192.168.255.30", label="plex", htype="docker", all_ips=["192.168.255.30", "192.168.5.30"])]
        result = by_ip(hosts, "192.168.255.30")
        self.assertIsNotNone(result)
        self.assertEqual(result.label, "plex")

    def test_by_ip_finds_host_by_secondary_ip(self):
        """by_ip() finds host by non-primary IP in all_ips."""
        from freq.core.resolve import by_ip

        hosts = [Host(ip="192.168.255.30", label="plex", htype="docker", all_ips=["192.168.255.30", "192.168.5.30", "192.168.25.30"])]
        result = by_ip(hosts, "192.168.5.30")
        self.assertIsNotNone(result)
        self.assertEqual(result.label, "plex")

    def test_by_ip_returns_none_for_unknown_ip(self):
        """by_ip() returns None for IP not in any host."""
        from freq.core.resolve import by_ip

        hosts = [Host(ip="192.168.255.30", label="plex", htype="docker", all_ips=["192.168.255.30", "192.168.5.30"])]
        result = by_ip(hosts, "192.168.66.99")
        self.assertIsNone(result)

    def test_by_ip_works_with_empty_all_ips(self):
        """by_ip() still works for old hosts without all_ips."""
        from freq.core.resolve import by_ip

        hosts = [Host(ip="192.168.255.30", label="plex", htype="docker")]
        result = by_ip(hosts, "192.168.255.30")
        self.assertIsNotNone(result)
        self.assertEqual(result.label, "plex")


if __name__ == "__main__":
    unittest.main()
