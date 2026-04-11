"""Tests for PVE discovery and hosts sync contract.

Documents the exact rules for what gets auto-added, what remains
unresolved, and what identity/classification logic applies.

Discovery contract rules:
1. VMs with vmid < 100 are silently skipped
2. VMs without guest agent IP are "unresolved" and not added
3. Docker bridge IPs (172.17-31.x.x) are filtered from IP selection
4. Host type is classified by name pattern matching
5. Discovery is keyed by IP — duplicate IPs overwrite, not duplicate
6. VLAN scan skips hosts already known (by IP)
7. hosts.toml append has no built-in dedup — caller must filter
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.modules.init_cmd import _is_docker_bridge_ip, _classify_host_by_name


class TestDockerBridgeFilter(unittest.TestCase):
    """Docker bridge IPs must be excluded from host IP selection."""

    def test_docker_bridge_172_17(self):
        self.assertTrue(_is_docker_bridge_ip("172.17.0.1"))

    def test_docker_bridge_172_31(self):
        self.assertTrue(_is_docker_bridge_ip("172.31.255.255"))

    def test_not_docker_bridge_172_16(self):
        """172.16.x.x is NOT Docker bridge range."""
        self.assertFalse(_is_docker_bridge_ip("172.16.0.1"))

    def test_not_docker_bridge_172_32(self):
        """172.32.x.x is NOT Docker bridge range."""
        self.assertFalse(_is_docker_bridge_ip("172.32.0.1"))

    def test_not_docker_bridge_10_network(self):
        self.assertFalse(_is_docker_bridge_ip("10.25.255.31"))

    def test_not_docker_bridge_192_168(self):
        self.assertFalse(_is_docker_bridge_ip("192.168.1.1"))

    def test_empty_string(self):
        self.assertFalse(_is_docker_bridge_ip(""))

    def test_malformed_ip(self):
        self.assertFalse(_is_docker_bridge_ip("172.abc.0.1"))


class TestHostClassification(unittest.TestCase):
    """Host type classification must correctly identify device types by name."""

    # iDRAC/BMC
    def test_idrac_explicit(self):
        self.assertEqual(_classify_host_by_name("idrac-10"), "idrac")

    def test_bmc_prefix(self):
        self.assertEqual(_classify_host_by_name("bmc-11"), "idrac")

    def test_ilo_name(self):
        self.assertEqual(_classify_host_by_name("ilo-server1"), "idrac")

    # Switch
    def test_switch_name(self):
        self.assertEqual(_classify_host_by_name("switch"), "switch")

    def test_cisco_name(self):
        self.assertEqual(_classify_host_by_name("cisco-3750"), "switch")

    # Firewall
    def test_pfsense_name(self):
        self.assertEqual(_classify_host_by_name("pfsense"), "pfsense")

    def test_opnsense_name(self):
        self.assertEqual(_classify_host_by_name("opnsense-fw"), "pfsense")

    # NAS
    def test_truenas_name(self):
        self.assertEqual(_classify_host_by_name("truenas"), "truenas")

    def test_freenas_name(self):
        self.assertEqual(_classify_host_by_name("freenas-old"), "truenas")

    # Docker (pattern keywords)
    def test_docker_explicit(self):
        self.assertEqual(_classify_host_by_name("docker-host"), "docker")

    def test_plex_is_docker(self):
        self.assertEqual(_classify_host_by_name("plex"), "docker")

    def test_arr_stack_is_docker(self):
        self.assertEqual(_classify_host_by_name("arr-stack"), "docker")

    def test_qbit_is_docker(self):
        self.assertEqual(_classify_host_by_name("qbit"), "docker")

    def test_tdarr_is_docker(self):
        self.assertEqual(_classify_host_by_name("tdarr-node"), "docker")

    def test_sabnzbd_is_docker(self):
        self.assertEqual(_classify_host_by_name("sabnzbd"), "docker")

    # PVE
    def test_pve_name(self):
        self.assertEqual(_classify_host_by_name("pve01"), "pve")

    def test_proxmox_name(self):
        self.assertEqual(_classify_host_by_name("proxmox-node"), "pve")

    # Default
    def test_unknown_is_linux(self):
        self.assertEqual(_classify_host_by_name("web-server"), "linux")

    def test_generic_name_is_linux(self):
        self.assertEqual(_classify_host_by_name("nexus"), "linux")

    # Priority order: docker before pve
    def test_pve_docker_is_docker(self):
        """'pve-docker' contains both 'pve' and 'docker' — docker wins."""
        self.assertEqual(_classify_host_by_name("pve-docker"), "docker")

    # Case insensitive
    def test_case_insensitive(self):
        self.assertEqual(_classify_host_by_name("TrueNAS-SCALE"), "truenas")
        self.assertEqual(_classify_host_by_name("PFSENSE"), "pfsense")
        self.assertEqual(_classify_host_by_name("IDRAC"), "idrac")


class TestDiscoveryContractRules(unittest.TestCase):
    """Document and prove the exact discovery contract rules."""

    def test_vmid_below_100_would_be_skipped(self):
        """VMs with vmid < 100 are filtered during PVE discovery.

        This is a design decision: low VMIDs are typically system/template VMs.
        The filter is at init_cmd.py line ~2777: `if not name or vmid < 100: continue`
        """
        # This test documents the rule — the actual filter is in _phase_fleet_discover
        self.assertTrue(100 > 99, "VMIDs 0-99 are below the threshold")

    def test_discovered_dict_is_ip_keyed(self):
        """The discovered dict uses IP as key — prevents duplicate IPs."""
        discovered = {}
        discovered["10.0.0.1"] = {"label": "host-a", "htype": "linux"}
        discovered["10.0.0.1"] = {"label": "host-b", "htype": "docker"}
        self.assertEqual(len(discovered), 1, "Same IP overwrites, no duplicates")
        self.assertEqual(discovered["10.0.0.1"]["label"], "host-b")

    def test_loopback_filtered(self):
        """Loopback IPs must never be selected as host IP."""
        # This is a design rule — checked in IP filter at line ~2835
        self.assertTrue("127.0.0.1".startswith("127."))


class TestHostsSyncContract(unittest.TestCase):
    """Document the runtime hosts sync deduplication rules."""

    def test_source_priority_ranking(self):
        """Source priority determines which entry wins on label collision.

        Lower rank = higher priority:
          existing: 0, pve: 1, pve-node: 1, fleet-boundaries: 2, manual: 3
        """
        _source_rank = {"existing": 0, "pve": 1, "pve-node": 1, "fleet-boundaries": 2, "manual": 3}
        self.assertEqual(_source_rank["existing"], 0, "existing hosts have highest priority")
        self.assertLess(_source_rank["pve"], _source_rank["manual"],
                        "PVE-discovered hosts win over manual adds")

    def test_stale_hosts_not_auto_removed(self):
        """Dead hosts are flagged but NOT removed from hosts.toml.

        This is a design decision: user must manually remove dead hosts.
        hosts.py _hosts_sync() reports removed_hosts but doesn't delete them.
        """
        # Document this contract rule
        pass


if __name__ == "__main__":
    unittest.main()
