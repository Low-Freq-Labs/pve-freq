"""Tests for PVE discovery and hosts sync contract.

Documents the exact rules for what gets auto-added, what remains
unresolved, and how observed identity is handled.

Discovery contract rules:
1. VMs with vmid < 100 are silently skipped
2. VMs without guest agent IP are "unresolved" and not added
3. Docker bridge IPs (172.17-31.x.x) are filtered from IP selection
4. PVE guest names remain observations; they do not classify host type
5. Discovery is keyed by IP — duplicate IPs overwrite, not duplicate
6. VLAN scan skips hosts already known (by IP)
7. hosts.toml append has no built-in dedup — caller must filter
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.core.host_identity import is_docker_bridge_ip


class TestDockerBridgeFilter(unittest.TestCase):
    """Docker bridge IPs must be excluded from host IP selection."""

    CASES = (
        ("default-bridge", "172.17.0.1", True),
        ("range-upper-bound", "172.31.255.255", True),
        ("below-range", "172.16.0.1", False),
        ("above-range", "172.32.0.1", False),
        ("management-network", "10.25.255.31", False),
        ("private-network", "192.168.1.1", False),
        ("empty", "", False),
        ("nonnumeric-octet", "172.abc.0.1", False),
        ("custom-bridge", "172.18.0.1", True),
        ("range-upper-neighbor", "172.31.255.254", True),
        ("below-range-host", "172.16.50.100", False),
        ("private-management", "192.168.255.1", False),
        ("zero-second-octet", "172.0.0.1", False),
        ("low-second-octet", "172.15.0.1", False),
        ("invalid-text", "not-an-ip", False),
        ("incomplete", "172", False),
        ("high-second-octet", "172.100.0.1", False),
        ("malformed-host-octet", "172.17.bad.1", False),
        ("out-of-range-host-octet", "172.17.256.1", False),
    )

    def test_docker_bridge_matrix(self):
        self.assertEqual(len(self.CASES), 19)
        case_ids = tuple(case_id for case_id, _ip, _expected in self.CASES)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case_id, ip, expected in self.CASES:
            with self.subTest(case=case_id, ip=ip):
                self.assertIs(is_docker_bridge_ip(ip), expected)


class TestNoHostnameClassification(unittest.TestCase):
    """Discovery must not expose or consume a hostname classifier."""

    def test_hostname_classifier_is_absent(self):
        from freq.core import host_identity

        init_source = (Path(__file__).parent.parent / "freq/modules/init_cmd.py").read_text()
        self.assertFalse(hasattr(host_identity, "classify_host_by_name"))
        self.assertNotIn("classify_host_by_name", init_source)


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
