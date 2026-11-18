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

from tests.case_matrix import run_case_matrix

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
    def _case_3_1_find_node_single(self):
        """With 1 PVE node, _find_node tries only that node."""
        self.assertEqual(len(self.cfg.pve_nodes), 1)
        self.assertEqual(self.cfg.pve_nodes[0], "192.168.1.10")

    # --- 3.3: migrate with only 1 node ---
    def _case_3_3_migrate_no_target_node_fails(self):
        """Migrate without --node returns 1."""
        from freq.modules.vm import cmd_migrate
        args = make_args(target="100", node=None, storage=None)
        result = cmd_migrate(self.cfg, None, args)
        self.assertEqual(result, 1)

    # --- 3.7: destroy safety check ---
    def _case_3_7_destroy_safety_check_protected(self):
        """Destroy on protected VMID is rejected."""
        from freq.core.validate import is_protected_vmid
        # Profile A protects range 900-999
        self.assertTrue(is_protected_vmid(900, [], [[900, 999]]))
        self.assertTrue(is_protected_vmid(999, [], [[900, 999]]))
        self.assertFalse(is_protected_vmid(100, [], [[900, 999]]))
        self.assertFalse(is_protected_vmid(5000, [], [[900, 999]]))

    def _case_3_7b_safety_check_function(self):
        """_safety_check blocks protected VMIDs."""
        from freq.modules.vm import _safety_check
        # Profile A has protected_ranges = [[900, 999]]
        self.assertFalse(_safety_check(self.cfg, 900, "test"))
        self.assertFalse(_safety_check(self.cfg, 950, "test"))
        self.assertTrue(_safety_check(self.cfg, 100, "test"))
        self.assertTrue(_safety_check(self.cfg, 5000, "test"))

    # --- 3.8: init --dry-run with 1 PVE node ---
    def _case_3_8_init_config_single_node(self):
        """Init config with 1 PVE node — config is valid."""
        self.assertEqual(len(self.cfg.pve_nodes), 1)
        self.assertEqual(self.cfg.pve_node_names, ["proxmox1"])
        self.assertEqual(self.cfg.ssh_service_account, "admin")

    # --- 3.10: risk with custom risk.toml ---
    def _case_3_10_risk_toml_missing(self):
        """Profile A has no risk.toml — load_toml returns empty."""
        from freq.core.config import load_toml
        risk_path = os.path.join(CONFIGS_DIR, "profile_a", "conf", "risk.toml")
        data = load_toml(risk_path)
        self.assertEqual(data, {})


class TestTier3ProfileB(unittest.TestCase):
    """Tier 3 equivalent checks with Profile B (3 nodes)."""

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def _case_multi_node_config(self):
        """Profile B: 3 nodes are available."""
        self.assertEqual(len(self.cfg.pve_nodes), 3)

    def _case_protected_vmids_list(self):
        """Profile B: explicit protected VMIDs."""
        from freq.core.validate import is_protected_vmid
        self.assertTrue(is_protected_vmid(100, self.cfg.protected_vmids, self.cfg.protected_ranges))
        self.assertTrue(is_protected_vmid(200, self.cfg.protected_vmids, self.cfg.protected_ranges))
        self.assertTrue(is_protected_vmid(300, self.cfg.protected_vmids, self.cfg.protected_ranges))
        self.assertFalse(is_protected_vmid(400, self.cfg.protected_vmids, self.cfg.protected_ranges))

    def _case_storage_per_node(self):
        """Profile B: different storage per node."""
        self.assertEqual(self.cfg.pve_storage["node1"]["pool"], "zfs-pool")
        self.assertEqual(self.cfg.pve_storage["node3"]["pool"], "ceph-pool")


class TestTier3CLIDispatch(unittest.TestCase):
    """Test CLI dispatch handles missing/bad arguments gracefully."""

    FAILURE_CASES = (
        ("destroy-missing-target", "cmd_destroy", (("target", None),), 1),
        ("destroy-nonnumeric-target", "cmd_destroy", (("target", "not-a-number"),), 1),
        (
            "resize-missing-target",
            "cmd_resize",
            (("target", None), ("cores", None), ("ram", None), ("disk", None)),
            1,
        ),
        (
            "resize-no-changes",
            "cmd_resize",
            (("target", "100"), ("cores", None), ("ram", None), ("disk", None)),
            1,
        ),
        ("clone-missing-source", "cmd_clone", (("source", None),), 1),
        ("clone-nonnumeric-source", "cmd_clone", (("source", "not-a-number"),), 1),
        ("template-missing-target", "cmd_template", (("target", None),), 1),
        (
            "migrate-missing-target",
            "cmd_migrate",
            (("target", None), ("node", None), ("storage", None)),
            1,
        ),
    )

    def _case_invalid_vm_commands_return_one(self):
        from freq.modules import vm

        self.assertEqual(
            tuple(case_id for case_id, _, _, _ in self.FAILURE_CASES),
            (
                "destroy-missing-target",
                "destroy-nonnumeric-target",
                "resize-missing-target",
                "resize-no-changes",
                "clone-missing-source",
                "clone-nonnumeric-source",
                "template-missing-target",
                "migrate-missing-target",
            ),
        )
        self.assertEqual(
            tuple(handler for _, handler, _, _ in self.FAILURE_CASES),
            (
                "cmd_destroy",
                "cmd_destroy",
                "cmd_resize",
                "cmd_resize",
                "cmd_clone",
                "cmd_clone",
                "cmd_template",
                "cmd_migrate",
            ),
        )
        self.assertEqual(
            tuple(kwargs for _, _, kwargs, _ in self.FAILURE_CASES),
            (
                (("target", None),),
                (("target", "not-a-number"),),
                (("target", None), ("cores", None), ("ram", None), ("disk", None)),
                (("target", "100"), ("cores", None), ("ram", None), ("disk", None)),
                (("source", None),),
                (("source", "not-a-number"),),
                (("target", None),),
                (("target", None), ("node", None), ("storage", None)),
            ),
        )
        self.assertEqual(tuple(expected for _, _, _, expected in self.FAILURE_CASES), (1,) * 8)
        case_ids = tuple(case_id for case_id, _, _, _ in self.FAILURE_CASES)
        self.assertEqual(len(case_ids), 8)
        self.assertEqual(len(set(case_ids)), 8)
        for case_id, handler_name, kwargs, expected in self.FAILURE_CASES:
            with self.subTest(case=case_id):
                handler = getattr(vm, handler_name, None)
                self.assertTrue(callable(handler), handler_name)
                args = make_args(**dict(kwargs))
                result = handler(load_with_profile("profile_a"), None, args)
                self.assertEqual(result, expected)

class TestTier6VMNetworkEdgeCases(unittest.TestCase):
    """Tier 6 (Rick's half): VM network IP prefix handling."""

    # --- 6.1: Create VM with empty gateway ---
    def _case_6_1_empty_gateway(self):
        """Config with empty gateway: vm_gateway is empty string."""
        cfg = load_with_profile("profile_c")
        self.assertEqual(cfg.vm_gateway, "")

    def _case_6_1b_profile_a_has_gateway(self):
        """Profile A has a gateway configured."""
        cfg = load_with_profile("profile_a")
        self.assertEqual(cfg.vm_gateway, "192.168.1.1")

    # --- 6.2: Clone VM with IP including /23 ---
    def _case_6_2_ip_with_23_prefix(self):
        """IP with /23 prefix: should use /23, not append /24."""
        ip_addr = "172.16.0.50/23"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "172.16.0.50/23")

    # --- 6.3: Clone VM with bare IP ---
    def _case_6_3_bare_ip_gets_24(self):
        """Bare IP (no prefix): should append /24."""
        ip_addr = "172.16.0.50"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "172.16.0.50/24")

    # --- 6.4: Sandbox VM with IP including prefix ---
    def _case_6_4_ip_with_16_prefix(self):
        """IP with /16 prefix: should use /16, not double-append."""
        ip_addr = "10.0.5.10/16"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "10.0.5.10/16")

    # --- 6.5: Sandbox VM with bare IP ---
    def _case_6_5_bare_sandbox_ip(self):
        """Bare sandbox IP: should append /24."""
        ip_addr = "10.0.5.10"
        ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
        self.assertEqual(ip_with_prefix, "10.0.5.10/24")

    # --- Extra: VLAN-aware prefix extraction ---
    def _case_vlan_prefix_from_profile_d(self):
        """Profile D VLANs have /23 subnets — prefix is correct."""
        cfg = load_with_profile("profile_d")
        main_vlan = next(v for v in cfg.vlans if v.name == "MAIN")
        self.assertEqual(main_vlan.subnet, "172.16.0.0/23")
        self.assertEqual(main_vlan.prefix, "172.16.0")

    def _case_gateway_from_vlan(self):
        """Profile D: gateway comes from VLAN config."""
        cfg = load_with_profile("profile_d")
        main_vlan = next(v for v in cfg.vlans if v.name == "MAIN")
        self.assertEqual(main_vlan.gateway, "172.16.0.1")

    def _case_create_cmd_uses_config_values(self):
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

    def _case_create_cmd_profile_a(self):
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

    def _case_storage_fallback_to_local_lvm(self):
        """When no pve_storage configured, fallback to local-lvm."""
        # Simulate the storage selection logic from cmd_create
        pve_storage = {}
        storage = "local-lvm"
        for node_name, store_info in pve_storage.items():
            if store_info.get("pool"):
                storage = store_info["pool"]
                break
        self.assertEqual(storage, "local-lvm")

    def _case_storage_from_profile_b(self):
        """Profile B: picks first storage pool."""
        cfg = load_with_profile("profile_b")
        storage = "local-lvm"
        for node_name, store_info in cfg.pve_storage.items():
            if store_info.get("pool"):
                storage = store_info["pool"]
                break
        # Should pick one of the configured pools
        self.assertIn(storage, ["zfs-pool", "ceph-pool"])

    def _case_storage_from_profile_d(self):
        """Profile D: ceph-pool storage."""
        cfg = load_with_profile("profile_d")
        self.assertIn("pve1", cfg.pve_storage)
        self.assertEqual(cfg.pve_storage["pve1"]["pool"], "ceph-pool")


TIER3_SINGLE_NODE_CASES = (
    "_case_3_1_find_node_single", "_case_3_3_migrate_no_target_node_fails",
    "_case_3_7_destroy_safety_check_protected", "_case_3_7b_safety_check_function",
    "_case_3_8_init_config_single_node", "_case_3_10_risk_toml_missing",
)
TIER3_PROFILE_B_CASES = (
    "_case_multi_node_config", "_case_protected_vmids_list",
    "_case_storage_per_node",
)
TIER3_CLI_DISPATCH_CASES = ("_case_invalid_vm_commands_return_one",)
TIER6_VM_NETWORK_CASES = (
    "_case_6_1_empty_gateway", "_case_6_1b_profile_a_has_gateway",
    "_case_6_2_ip_with_23_prefix", "_case_6_3_bare_ip_gets_24",
    "_case_6_4_ip_with_16_prefix", "_case_6_5_bare_sandbox_ip",
    "_case_vlan_prefix_from_profile_d", "_case_gateway_from_vlan",
    "_case_create_cmd_uses_config_values", "_case_create_cmd_profile_a",
)
TIER6_STORAGE_CASES = (
    "_case_storage_fallback_to_local_lvm", "_case_storage_from_profile_b",
    "_case_storage_from_profile_d",
)


class TestTier3SingleNodeMatrix(unittest.TestCase):
    def test_tier3_single_node_matrix(self):
        run_case_matrix(self, TestTier3SingleNode, TIER3_SINGLE_NODE_CASES)


class TestTier3ProfileBMatrix(unittest.TestCase):
    def test_tier3_profile_b_matrix(self):
        run_case_matrix(self, TestTier3ProfileB, TIER3_PROFILE_B_CASES)


class TestTier3CLIDispatchMatrix(unittest.TestCase):
    def test_tier3_cli_dispatch_matrix(self):
        run_case_matrix(self, TestTier3CLIDispatch, TIER3_CLI_DISPATCH_CASES)


class TestTier6VMNetworkMatrix(unittest.TestCase):
    def test_tier6_vm_network_matrix(self):
        run_case_matrix(self, TestTier6VMNetworkEdgeCases, TIER6_VM_NETWORK_CASES)


class TestTier6StorageMatrix(unittest.TestCase):
    def test_tier6_storage_matrix(self):
        run_case_matrix(self, TestTier6StorageFallback, TIER6_STORAGE_CASES)


if __name__ == "__main__":
    unittest.main()
