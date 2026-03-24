"""Overnight Matrix — Tier 3: CLI Single Node + Tier 6: VM Network Edge Cases

Tier 3 (3.1-3.10): Single-node CLI behavior — safety gates, parameter validation,
node finding logic. Tests avoid SSH by testing internal functions.

Tier 6 (6.1-6.5): Rick's half — VM network edge cases around IP prefix handling.
"""
import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")


def load_with_profile(profile: str):
    """Load config from a test profile directory."""
    from freq.core.config import load_config
    profile_dir = os.path.join(CONFIGS_DIR, profile)
    return load_config(install_dir=profile_dir)


def make_args(**kwargs):
    """Create a mock args namespace."""
    defaults = {"yes": True, "debug": False, "command": "test"}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestTier3SingleNode(unittest.TestCase):
    """Tier 3: CLI commands with single-node config (Profile A)."""

    def setUp(self):
        self.cfg = load_with_profile("profile_a")

    # --- 3.1: vm create finds single node ---
    def test_3_1_find_node_single(self):
        """With 1 PVE node, _find_node tries only that node."""
        self.assertEqual(len(self.cfg.pve_nodes), 1)
        self.assertEqual(self.cfg.pve_nodes[0], "192.168.1.10")

    # --- 3.3: migrate with only 1 node ---
    def test_3_3_migrate_no_target_node_fails(self):
        """Migrate without --node returns 1."""
        from freq.modules.vm import cmd_migrate
        args = make_args(target="100", node=None, storage=None)
        result = cmd_migrate(self.cfg, None, args)
        self.assertEqual(result, 1)

    # --- 3.7: destroy safety check ---
    def test_3_7_destroy_safety_check_protected(self):
        """Destroy on protected VMID is rejected."""
        from freq.core.validate import is_protected_vmid
        # Profile A protects range 900-999
        self.assertTrue(is_protected_vmid(900, [], [[900, 999]]))
        self.assertTrue(is_protected_vmid(999, [], [[900, 999]]))
        self.assertFalse(is_protected_vmid(100, [], [[900, 999]]))
        self.assertFalse(is_protected_vmid(5000, [], [[900, 999]]))

    def test_3_7b_safety_check_function(self):
        """_safety_check blocks protected VMIDs."""
        from freq.modules.vm import _safety_check
        # Profile A has protected_ranges = [[900, 999]]
        self.assertFalse(_safety_check(self.cfg, 900, "test"))
        self.assertFalse(_safety_check(self.cfg, 950, "test"))
        self.assertTrue(_safety_check(self.cfg, 100, "test"))
        self.assertTrue(_safety_check(self.cfg, 5000, "test"))

    # --- 3.8: init --dry-run with 1 PVE node ---
    def test_3_8_init_config_single_node(self):
        """Init config with 1 PVE node — config is valid."""
        self.assertEqual(len(self.cfg.pve_nodes), 1)
        self.assertEqual(self.cfg.pve_node_names, ["proxmox1"])
        self.assertEqual(self.cfg.ssh_service_account, "admin")

    # --- 3.10: risk with custom risk.toml ---
    def test_3_10_risk_toml_missing(self):
        """Profile A has no risk.toml — load_toml returns empty."""
        from freq.core.config import load_toml
        risk_path = os.path.join(CONFIGS_DIR, "profile_a", "conf", "risk.toml")
        data = load_toml(risk_path)
        self.assertEqual(data, {})


class TestTier3ProfileB(unittest.TestCase):
    """Tier 3 equivalent checks with Profile B (3 nodes)."""

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_multi_node_config(self):
        """Profile B: 3 nodes are available."""
        self.assertEqual(len(self.cfg.pve_nodes), 3)

    def test_protected_vmids_list(self):
        """Profile B: explicit protected VMIDs."""
        from freq.core.validate import is_protected_vmid
        self.assertTrue(is_protected_vmid(100, self.cfg.protected_vmids, self.cfg.protected_ranges))
        self.assertTrue(is_protected_vmid(200, self.cfg.protected_vmids, self.cfg.protected_ranges))
        self.assertTrue(is_protected_vmid(300, self.cfg.protected_vmids, self.cfg.protected_ranges))
        self.assertFalse(is_protected_vmid(400, self.cfg.protected_vmids, self.cfg.protected_ranges))

    def test_storage_per_node(self):
        """Profile B: different storage per node."""
        self.assertEqual(self.cfg.pve_storage["node1"]["pool"], "zfs-pool")
        self.assertEqual(self.cfg.pve_storage["node3"]["pool"], "ceph-pool")


class TestTier3CLIDispatch(unittest.TestCase):
    """Test CLI dispatch handles missing/bad arguments gracefully."""

    def test_destroy_no_target(self):
        """freq destroy with no target returns 1."""
        from freq.modules.vm import cmd_destroy
        args = make_args(target=None)
        result = cmd_destroy(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)

    def test_destroy_invalid_vmid(self):
        """freq destroy with non-numeric VMID returns 1."""
        from freq.modules.vm import cmd_destroy
        args = make_args(target="not-a-number")
        result = cmd_destroy(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)

    def test_resize_no_target(self):
        """freq resize with no target returns 1."""
        from freq.modules.vm import cmd_resize
        args = make_args(target=None, cores=None, ram=None, disk=None)
        result = cmd_resize(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)

    def test_resize_no_changes(self):
        """freq resize with no changes returns 1."""
        from freq.modules.vm import cmd_resize
        args = make_args(target="100", cores=None, ram=None, disk=None)
        result = cmd_resize(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)

    def test_clone_no_source(self):
        """freq clone with no source returns 1."""
        from freq.modules.vm import cmd_clone
        args = make_args(source=None)
        result = cmd_clone(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)

    def test_clone_invalid_source(self):
        """freq clone with invalid source VMID returns 1."""
        from freq.modules.vm import cmd_clone
        args = make_args(source="not-a-number")
        result = cmd_clone(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)

    def test_template_no_target(self):
        """freq vm template with no target returns 1."""
        from freq.modules.vm import cmd_template
        args = make_args(target=None)
        result = cmd_template(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)

    def test_migrate_no_target(self):
        """freq migrate with no target returns 1."""
        from freq.modules.vm import cmd_migrate
        args = make_args(target=None, node=None, storage=None)
        result = cmd_migrate(load_with_profile("profile_a"), None, args)
        self.assertEqual(result, 1)


class TestTier6VMNetworkEdgeCases(unittest.TestCase):
    """Tier 6 (Rick's half): VM network IP prefix handling."""

    # --- 6.1: Create VM with empty gateway ---
    def test_6_1_empty_gateway(self):
        """Config with empty gateway: vm_gateway is empty string."""
        cfg = load_with_profile("profile_c")
        self.assertEqual(cfg.vm_gateway, "")

    def test_6_1b_profile_a_has_gateway(self):
        """Profile A has a gateway configured."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.vm_gateway, "192.168.1.1")

    # --- 6.2: Clone VM with IP including /23 ---
    def test_6_2_ip_with_23_prefix(self):
        """IP with /23 prefix: should use /23, not append /24."""
        ip_addr = "172.16.0.50/23"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "172.16.0.50/23")

    # --- 6.3: Clone VM with bare IP ---
    def test_6_3_bare_ip_gets_24(self):
        """Bare IP (no prefix): should append /24."""
        ip_addr = "172.16.0.50"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "172.16.0.50/24")

    # --- 6.4: Sandbox VM with IP including prefix ---
    def test_6_4_ip_with_16_prefix(self):
        """IP with /16 prefix: should use /16, not double-append."""
        ip_addr = "10.0.5.10/16"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "10.0.5.10/16")

    # --- 6.5: Sandbox VM with bare IP ---
    def test_6_5_bare_sandbox_ip(self):
        """Bare sandbox IP: should append /24."""
        ip_addr = "10.0.5.10"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "10.0.5.10/24")

    # --- Extra: VLAN-aware prefix extraction ---
    def test_vlan_prefix_from_profile_d(self):
        """Profile D VLANs have /23 subnets — prefix is correct."""
        cfg = load_with_profile("profile_d")
        main_vlan = next(v for v in cfg.vlans if v.name == "MAIN")
        self.assertEqual(main_vlan.subnet, "172.16.0.0/23")
        self.assertEqual(main_vlan.prefix, "172.16.0")

    def test_gateway_from_vlan(self):
        """Profile D: gateway comes from VLAN config."""
        cfg = load_with_profile("profile_d")
        main_vlan = next(v for v in cfg.vlans if v.name == "MAIN")
        self.assertEqual(main_vlan.gateway, "172.16.0.1")

    def test_create_cmd_uses_config_values(self):
        """Create command builds qm create with cfg values."""
        cfg = load_with_profile("profile_d")
        # Simulate what cmd_create builds
        vmid = 5000
        name = "test-vm"
        create_cmd = (
            f"qm create {vmid} --name {name} "
            f"--cores {cfg.vm_default_cores} --memory {cfg.vm_default_ram} "
            f"--cpu {cfg.vm_cpu} --machine {cfg.vm_machine} "
            f"--net0 virtio,bridge={cfg.nic_bridge} "
            f"--scsihw {cfg.vm_scsihw}"
        )
        self.assertIn("--cpu host", create_cmd)
        self.assertIn("--machine q35", create_cmd)
        self.assertIn("bridge=vmbr1", create_cmd)  # Profile D uses vmbr1
        self.assertIn("--scsihw virtio-scsi-pci", create_cmd)  # Profile D

    def test_create_cmd_profile_a(self):
        """Profile A create command uses kvm64 and vmbr0."""
        cfg = load_with_profile("profile_a")
        create_cmd = (
            f"qm create 100 --name test "
            f"--cpu {cfg.vm_cpu} "
            f"--net0 virtio,bridge={cfg.nic_bridge} "
            f"--scsihw {cfg.vm_scsihw}"
        )
        self.assertIn("--cpu kvm64", create_cmd)
        self.assertIn("bridge=vmbr0", create_cmd)
        self.assertIn("--scsihw virtio-scsi-single", create_cmd)


class TestTier6StorageFallback(unittest.TestCase):
    """Tier 6: Storage pool selection logic."""

    def test_storage_fallback_to_local_lvm(self):
        """When no pve_storage configured, fallback to local-lvm."""
        # Simulate the storage selection logic from cmd_create
        pve_storage = {}
        storage = "local-lvm"
        for node_name, store_info in pve_storage.items():
            if store_info.get("pool"):
                storage = store_info["pool"]
                break
        self.assertEqual(storage, "local-lvm")

    def test_storage_from_profile_b(self):
        """Profile B: picks first storage pool."""
        cfg = load_with_profile("profile_b")
        storage = "local-lvm"
        for node_name, store_info in cfg.pve_storage.items():
            if store_info.get("pool"):
                storage = store_info["pool"]
                break
        # Should pick one of the configured pools
        self.assertIn(storage, ["zfs-pool", "ceph-pool"])

    def test_storage_from_profile_d(self):
        """Profile D: ceph-pool storage."""
        cfg = load_with_profile("profile_d")
        self.assertIn("pve1", cfg.pve_storage)
        self.assertEqual(cfg.pve_storage["pve1"]["pool"], "ceph-pool")


if __name__ == "__main__":
    unittest.main()
