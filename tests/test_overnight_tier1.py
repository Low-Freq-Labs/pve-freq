"""Overnight Matrix — Tier 1: Config Loading (Profiles A-D)

Tests 1.1-1.10: Load configs with different profiles and verify correct parsing.
No network calls. Pure config loading.
"""
import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")


def load_with_profile(profile: str):
    """Load config from a test profile directory."""
    from freq.core.config import load_config
    profile_dir = os.path.join(CONFIGS_DIR, profile)
    return load_config(install_dir=profile_dir)


class TestTier1ConfigLoading(unittest.TestCase):
    """Tier 1: Config loading edge cases across profiles A-D."""

    # --- 1.1: Empty/minimal freq.toml (Profile C) ---
    def test_1_1_load_config_minimal_toml(self):
        """Load config with minimal freq.toml — should get defaults, no crash."""
        cfg = load_with_profile("profile_c")
        self.assertEqual(cfg.brand, "PVE FREQ")
        self.assertEqual(cfg.build, "default")
        self.assertEqual(cfg.ssh_service_account, "freq-admin")
        self.assertEqual(cfg.vm_default_cores, 2)
        self.assertEqual(cfg.vm_default_ram, 2048)
        self.assertEqual(cfg.vm_cpu, "kvm64")
        self.assertEqual(cfg.vm_gateway, "")
        self.assertEqual(cfg.vm_nameserver, "1.1.1.1")
        self.assertEqual(cfg.nic_bridge, "vmbr0")

    # --- 1.2: Missing freq.toml entirely ---
    def test_1_2_load_config_missing_toml(self):
        """Load config with missing freq.toml — should return defaults, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create conf/ dir but no freq.toml
            os.makedirs(os.path.join(tmpdir, "conf"))
            from freq.core.config import load_config
            cfg = load_config(install_dir=tmpdir)
            self.assertEqual(cfg.brand, "PVE FREQ")
            self.assertEqual(cfg.ssh_service_account, "freq-admin")
            self.assertEqual(cfg.vm_cpu, "kvm64")
            self.assertEqual(cfg.pve_nodes, [])
            self.assertEqual(cfg.hosts, [])
            self.assertEqual(cfg.vlans, [])

    # --- 1.3: Missing vlans.toml ---
    def test_1_3_load_config_missing_vlans(self):
        """Load config with missing vlans.toml — cfg.vlans = [], no crash."""
        cfg = load_with_profile("profile_c")
        self.assertEqual(cfg.vlans, [])

    # --- 1.4: Missing hosts.conf ---
    def test_1_4_load_config_missing_hosts(self):
        """Load config with missing hosts.conf — cfg.hosts = [], no crash."""
        cfg = load_with_profile("profile_c")
        self.assertEqual(cfg.hosts, [])

    # --- 1.5: /16 VLANs (Profile B) ---
    def test_1_5_load_config_16_vlans(self):
        """Load config with /16 VLANs — parses correctly."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(len(cfg.vlans), 4)
        # Check VLAN attributes
        vlan_names = {v.name for v in cfg.vlans}
        self.assertIn("MGMT", vlan_names)
        self.assertIn("SERVERS", vlan_names)
        self.assertIn("STORAGE", vlan_names)
        self.assertIn("PUBLIC", vlan_names)
        # Check /16 subnets parsed correctly
        mgmt = next(v for v in cfg.vlans if v.name == "MGMT")
        self.assertEqual(mgmt.subnet, "10.0.0.0/16")
        self.assertEqual(mgmt.id, 10)
        self.assertEqual(mgmt.gateway, "10.0.0.1")

    # --- 1.6: /23 VLANs (Profile D) ---
    def test_1_6_load_config_23_vlans(self):
        """Load config with /23 VLANs — parses correctly."""
        cfg = load_with_profile("profile_d")
        self.assertEqual(len(cfg.vlans), 2)
        main_vlan = next(v for v in cfg.vlans if v.name == "MAIN")
        self.assertEqual(main_vlan.subnet, "172.16.0.0/23")
        self.assertEqual(main_vlan.id, 100)
        self.assertEqual(main_vlan.gateway, "172.16.0.1")
        svc_vlan = next(v for v in cfg.vlans if v.name == "SERVICES")
        self.assertEqual(svc_vlan.subnet, "172.16.2.0/23")
        self.assertEqual(svc_vlan.id, 200)

    # --- 1.7: Unknown personality pack ---
    def test_1_7_load_config_unknown_personality(self):
        """Load config with nonexistent personality — falls back to defaults, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conf_dir = os.path.join(tmpdir, "conf")
            os.makedirs(conf_dir)
            # Write freq.toml with bogus build name
            with open(os.path.join(conf_dir, "freq.toml"), "w") as f:
                f.write('[freq]\nbuild = "nonexistent"\n')
            from freq.core.config import load_config
            from freq.core.personality import load_pack
            cfg = load_config(install_dir=tmpdir)
            self.assertEqual(cfg.build, "nonexistent")
            pack = load_pack(cfg.conf_dir, cfg.build)
            self.assertEqual(pack.name, "nonexistent")
            # Should have default values, not crash
            self.assertEqual(pack.subtitle, "P V E  F R E Q")
            self.assertEqual(pack.celebrations, [])
            self.assertEqual(pack.dashboard_header, "PVE FREQ Dashboard")

    # --- 1.8: Empty pve_nodes ---
    def test_1_8_load_config_empty_pve_nodes(self):
        """Load config with empty nodes list — cfg.pve_nodes = [], no crash."""
        cfg = load_with_profile("profile_c")
        self.assertEqual(cfg.pve_nodes, [])

    # --- 1.9: Custom storage pool names ---
    def test_1_9_load_config_custom_storage(self):
        """Load config with custom storage pool names."""
        cfg = load_with_profile("profile_d")
        self.assertIn("pve1", cfg.pve_storage)
        self.assertEqual(cfg.pve_storage["pve1"]["pool"], "ceph-pool")
        self.assertEqual(cfg.pve_storage["pve1"]["type"], "SSD")

    # --- 1.10: service_account = "root" ---
    def test_1_10_load_config_root_service_account(self):
        """Load config with service_account = root."""
        cfg = load_with_profile("profile_d")
        self.assertEqual(cfg.ssh_service_account, "root")


class TestTier1ProfileA(unittest.TestCase):
    """Additional Profile A (Bare Metal Baby) verification."""

    def test_profile_a_single_node(self):
        """Profile A: single PVE node loads correctly."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.pve_nodes, ["192.168.1.10"])
        self.assertEqual(cfg.pve_node_names, ["proxmox1"])

    def test_profile_a_no_vlans(self):
        """Profile A: empty vlans.toml means no VLANs."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.vlans, [])

    def test_profile_a_empty_hosts(self):
        """Profile A: empty hosts.conf means no hosts."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.hosts, [])

    def test_profile_a_vm_defaults(self):
        """Profile A: VM defaults from config."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.vm_cpu, "kvm64")
        self.assertEqual(cfg.vm_gateway, "192.168.1.1")
        self.assertEqual(cfg.vm_nameserver, "192.168.1.1")
        self.assertEqual(cfg.vm_domain, "home.lab")

    def test_profile_a_storage(self):
        """Profile A: local-lvm storage."""
        cfg = load_with_profile("profile_a")
        self.assertIn("proxmox1", cfg.pve_storage)
        self.assertEqual(cfg.pve_storage["proxmox1"]["pool"], "local-lvm")

    def test_profile_a_infrastructure(self):
        """Profile A: cluster name, no infra IPs."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.cluster_name, "HomeCluster")
        self.assertEqual(cfg.truenas_ip, "")
        self.assertEqual(cfg.pfsense_ip, "")


class TestTier1ProfileB(unittest.TestCase):
    """Additional Profile B (Big Boy /16) verification."""

    def test_profile_b_three_nodes(self):
        """Profile B: 3 PVE nodes."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(len(cfg.pve_nodes), 3)
        self.assertEqual(cfg.pve_nodes, ["10.0.1.1", "10.0.1.2", "10.0.1.3"])
        self.assertEqual(cfg.pve_node_names, ["node1", "node2", "node3"])

    def test_profile_b_twelve_hosts(self):
        """Profile B: 12 hosts load correctly."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(len(cfg.hosts), 12)
        # Check types parsed correctly
        pve_hosts = [h for h in cfg.hosts if h.htype == "pve"]
        docker_hosts = [h for h in cfg.hosts if h.htype == "docker"]
        linux_hosts = [h for h in cfg.hosts if h.htype == "linux"]
        self.assertEqual(len(pve_hosts), 3)
        self.assertEqual(len(docker_hosts), 2)
        self.assertEqual(len(linux_hosts), 5)

    def test_profile_b_infra_ips(self):
        """Profile B: infrastructure IPs."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(cfg.truenas_ip, "10.0.1.100")
        self.assertEqual(cfg.pfsense_ip, "10.0.0.1")

    def test_profile_b_storage_per_node(self):
        """Profile B: different storage per node."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(cfg.pve_storage["node1"]["pool"], "zfs-pool")
        self.assertEqual(cfg.pve_storage["node3"]["pool"], "ceph-pool")
        self.assertEqual(cfg.pve_storage["node3"]["type"], "HDD")

    def test_profile_b_vm_defaults(self):
        """Profile B: larger VM defaults."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(cfg.vm_default_cores, 4)
        self.assertEqual(cfg.vm_default_ram, 4096)
        self.assertEqual(cfg.vm_default_disk, 64)
        self.assertEqual(cfg.vm_cpu, "host")

    def test_profile_b_protected_vmids(self):
        """Profile B: protected VMIDs list."""
        cfg = load_with_profile("profile_b")
        self.assertEqual(cfg.protected_vmids, [100, 200, 300])
        self.assertEqual(cfg.protected_ranges, [[900, 999]])


class TestTier1ProfileD(unittest.TestCase):
    """Additional Profile D (/23 network) verification."""

    def test_profile_d_single_node(self):
        """Profile D: single PVE node."""
        cfg = load_with_profile("profile_d")
        self.assertEqual(cfg.pve_nodes, ["172.16.0.5"])

    def test_profile_d_five_hosts(self):
        """Profile D: 5 hosts load correctly."""
        cfg = load_with_profile("profile_d")
        self.assertEqual(len(cfg.hosts), 5)

    def test_profile_d_root_ssh(self):
        """Profile D: SSH as root with root mode."""
        cfg = load_with_profile("profile_d")
        self.assertEqual(cfg.ssh_service_account, "root")
        self.assertEqual(cfg.ssh_mode, "root")

    def test_profile_d_custom_vm_settings(self):
        """Profile D: custom VM settings (seabios, non-standard scsihw)."""
        cfg = load_with_profile("profile_d")
        self.assertEqual(cfg.vm_bios, "seabios")
        self.assertEqual(cfg.vm_scsihw, "virtio-scsi-pci")
        self.assertEqual(cfg.vm_cpu, "host")

    def test_profile_d_custom_nic(self):
        """Profile D: custom NIC bridge."""
        cfg = load_with_profile("profile_d")
        self.assertEqual(cfg.nic_bridge, "vmbr1")


class TestTier1EdgeCases(unittest.TestCase):
    """Edge cases not covered by specific profiles."""

    def test_load_toml_corrupt_file(self):
        """load_toml with corrupt TOML returns empty dict."""
        from freq.core.config import load_toml
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("this is not valid toml {\n!@#$%\n")
            path = f.name
        try:
            data = load_toml(path)
            self.assertIsInstance(data, dict)
        finally:
            os.unlink(path)

    def test_load_toml_nonexistent(self):
        """load_toml with nonexistent path returns empty dict."""
        from freq.core.config import load_toml
        data = load_toml("/nonexistent/path/freq.toml")
        self.assertEqual(data, {})

    def test_hosts_partial_lines(self):
        """Hosts with incomplete lines (< 3 fields) are skipped."""
        from freq.core.config import load_hosts
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write("# Valid\n")
            f.write("10.0.0.1  host1  linux  prod\n")
            f.write("incomplete-line\n")       # Only 1 field
            f.write("10.0.0.2  host2\n")       # Only 2 fields
            f.write("10.0.0.3  host3  pve\n")  # 3 fields, valid
            path = f.name
        try:
            hosts = load_hosts(path)
            self.assertEqual(len(hosts), 2)
            self.assertEqual(hosts[0].label, "host1")
            self.assertEqual(hosts[1].label, "host3")
            self.assertEqual(hosts[1].groups, "")  # No groups
        finally:
            os.unlink(path)

    def test_vlans_empty_toml(self):
        """Empty vlans.toml returns empty list."""
        from freq.core.config import load_vlans
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("# empty\n")
            path = f.name
        try:
            vlans = load_vlans(path)
            self.assertEqual(vlans, [])
        finally:
            os.unlink(path)

    def test_distros_missing_file(self):
        """Missing distros.toml returns empty list."""
        from freq.core.config import load_distros
        distros = load_distros("/nonexistent/distros.toml")
        self.assertEqual(distros, [])

    def test_containers_missing_file(self):
        """Missing containers.toml returns empty dict."""
        from freq.core.config import load_containers
        containers = load_containers("/nonexistent/containers.toml")
        self.assertEqual(containers, {})

    def test_fleet_boundaries_missing_file(self):
        """Missing fleet-boundaries.toml returns default FleetBoundaries."""
        from freq.core.config import load_fleet_boundaries
        from freq.core.types import FleetBoundaries
        fb = load_fleet_boundaries("/nonexistent/fleet-boundaries.toml")
        self.assertIsInstance(fb, FleetBoundaries)
        self.assertEqual(fb.tiers, {})
        self.assertEqual(fb.categories, {})

    def test_config_paths_resolved(self):
        """All path fields are resolved relative to install_dir."""
        cfg = load_with_profile("profile_a")
        profile_dir = os.path.join(CONFIGS_DIR, "profile_a")
        self.assertEqual(cfg.conf_dir, os.path.join(profile_dir, "conf"))
        self.assertTrue(cfg.hosts_file.endswith("hosts.conf"))
        self.assertTrue(cfg.log_file.endswith("freq.log"))

    def test_default_freqconfig_values(self):
        """FreqConfig() with no args has safe defaults."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        self.assertEqual(cfg.version, "2.0.0")
        self.assertEqual(cfg.brand, "PVE FREQ")
        self.assertEqual(cfg.build, "default")
        self.assertFalse(cfg.ascii_mode)
        self.assertFalse(cfg.debug)
        self.assertEqual(cfg.ssh_connect_timeout, 5)
        self.assertEqual(cfg.vm_default_disk, 32)
        self.assertEqual(cfg.max_failure_percent, 50)
        self.assertEqual(cfg.nic_bridge, "vmbr0")
        self.assertEqual(cfg.nic_mtu, 1500)
        self.assertEqual(cfg.discord_webhook, "")
        self.assertEqual(cfg.slack_webhook, "")


class TestPortabilityConfig(unittest.TestCase):
    """Portability: service ports and configurable defaults."""

    def test_default_service_ports(self):
        """FreqConfig has configurable service port defaults."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        self.assertEqual(cfg.dashboard_port, 8888)
        self.assertEqual(cfg.watchdog_port, 9900)
        self.assertEqual(cfg.agent_port, 9990)

    def test_service_ports_in_defaults(self):
        """Service ports are in _DEFAULTS dict."""
        from freq.core.config import _DEFAULTS
        self.assertIn("dashboard_port", _DEFAULTS)
        self.assertIn("watchdog_port", _DEFAULTS)
        self.assertIn("agent_port", _DEFAULTS)

    def test_service_ports_from_toml(self):
        """Service ports can be overridden via freq.toml [services] section."""
        from freq.core.config import FreqConfig, _apply_toml
        cfg = FreqConfig()
        data = {
            "services": {
                "dashboard_port": 9999,
                "watchdog_port": 7700,
                "agent_port": 8800,
            }
        }
        _apply_toml(cfg, data)
        self.assertEqual(cfg.dashboard_port, 9999)
        self.assertEqual(cfg.watchdog_port, 7700)
        self.assertEqual(cfg.agent_port, 8800)

    def test_service_account_configurable(self):
        """Service account is configurable via freq.toml, not hardcoded."""
        from freq.core.config import FreqConfig, _apply_toml
        cfg = FreqConfig()
        data = {"ssh": {"service_account": "my-custom-admin"}}
        _apply_toml(cfg, data)
        self.assertEqual(cfg.ssh_service_account, "my-custom-admin")

    def test_service_account_default_from_defaults(self):
        """Default service account comes from _DEFAULTS dict."""
        from freq.core.config import _DEFAULTS, FreqConfig
        cfg = FreqConfig()
        self.assertEqual(cfg.ssh_service_account, _DEFAULTS["ssh_service_account"])

    def test_ssh_fallback_uses_defaults_dict(self):
        """SSH fallback user comes from _DEFAULTS, not a hardcoded string."""
        from freq.core.config import _DEFAULTS
        from freq.core.ssh import get_platform_ssh
        opts = get_platform_ssh("linux", cfg=None)
        self.assertEqual(opts["user"], _DEFAULTS["ssh_service_account"])

    def test_no_dc01_ips_in_source(self):
        """No DC01-specific IPs (10.25.x.x) in Python source files."""
        import glob
        freq_dir = os.path.join(os.path.dirname(__file__), "..", "freq")
        violations = []
        for py_file in glob.glob(os.path.join(freq_dir, "**", "*.py"), recursive=True):
            # Skip cache files and data files
            if "/data/cache/" in py_file:
                continue
            with open(py_file) as f:
                for i, line in enumerate(f, 1):
                    if "10.25." in line and not line.strip().startswith("#"):
                        # Allow example/placeholder text in UI
                        if "placeholder" in line or "e.g." in line:
                            continue
                        violations.append(f"{os.path.basename(py_file)}:{i}")
        self.assertEqual(violations, [], f"DC01 IPs found in source: {violations}")

    def test_cache_dir_has_gitkeep(self):
        """Cache directory has .gitkeep so git tracks the dir but not data files."""
        cache_dir = os.path.join(os.path.dirname(__file__), "..", "freq", "data", "cache")
        if os.path.isdir(cache_dir):
            self.assertTrue(os.path.isfile(os.path.join(cache_dir, ".gitkeep")),
                            "Cache dir should have .gitkeep for git tracking")


if __name__ == "__main__":
    unittest.main()
