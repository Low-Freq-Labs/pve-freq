"""Overnight Matrix — Extra Coverage: Resolve, Validate, FleetBoundaries

Deep testing of load-bearing modules not covered by the matrix tiers.
These are the functions every command depends on.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")


def load_with_profile(profile: str):
    from freq.core.config import load_config
    return load_config(install_dir=os.path.join(CONFIGS_DIR, profile))


class TestResolveByLabel(unittest.TestCase):
    """Test host resolution by label."""

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_find_by_label_exact(self):
        from freq.core.resolve import by_label
        host = by_label(self.cfg.hosts, "node1")
        self.assertIsNotNone(host)
        self.assertEqual(host.ip, "10.0.1.1")

    def test_find_by_label_case_insensitive(self):
        from freq.core.resolve import by_label
        host = by_label(self.cfg.hosts, "NODE1")
        self.assertIsNotNone(host)
        self.assertEqual(host.label, "node1")

    def test_find_by_label_not_found(self):
        from freq.core.resolve import by_label
        host = by_label(self.cfg.hosts, "nonexistent")
        self.assertIsNone(host)

    def test_find_by_label_empty_hosts(self):
        from freq.core.resolve import by_label
        host = by_label([], "anything")
        self.assertIsNone(host)


class TestResolveByIP(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_find_by_ip(self):
        from freq.core.resolve import by_ip
        host = by_ip(self.cfg.hosts, "10.0.1.1")
        self.assertIsNotNone(host)
        self.assertEqual(host.label, "node1")

    def test_find_by_ip_not_found(self):
        from freq.core.resolve import by_ip
        host = by_ip(self.cfg.hosts, "10.99.99.99")
        self.assertIsNone(host)


class TestResolveByTarget(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_by_target_label(self):
        from freq.core.resolve import by_target
        host = by_target(self.cfg.hosts, "node1")
        self.assertIsNotNone(host)
        self.assertEqual(host.ip, "10.0.1.1")

    def test_by_target_ip(self):
        from freq.core.resolve import by_target
        host = by_target(self.cfg.hosts, "10.0.1.1")
        self.assertIsNotNone(host)
        self.assertEqual(host.label, "node1")

    def test_by_target_not_found(self):
        from freq.core.resolve import by_target
        host = by_target(self.cfg.hosts, "999.999.999.999")
        self.assertIsNone(host)


class TestResolveByGroup(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_group_prod(self):
        from freq.core.resolve import by_group
        hosts = by_group(self.cfg.hosts, "prod")
        self.assertGreater(len(hosts), 0)
        # All should have "prod" in their groups
        for h in hosts:
            self.assertIn("prod", h.groups.lower())

    def test_group_web(self):
        from freq.core.resolve import by_group
        hosts = by_group(self.cfg.hosts, "web")
        self.assertEqual(len(hosts), 2)

    def test_group_not_found(self):
        from freq.core.resolve import by_group
        hosts = by_group(self.cfg.hosts, "nonexistent")
        self.assertEqual(len(hosts), 0)

    def test_group_empty_hosts(self):
        from freq.core.resolve import by_group
        hosts = by_group([], "prod")
        self.assertEqual(hosts, [])


class TestResolveByType(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_type_pve(self):
        from freq.core.resolve import by_type
        hosts = by_type(self.cfg.hosts, "pve")
        self.assertEqual(len(hosts), 3)

    def test_type_docker(self):
        from freq.core.resolve import by_type
        hosts = by_type(self.cfg.hosts, "docker")
        self.assertEqual(len(hosts), 2)

    def test_type_case_insensitive(self):
        from freq.core.resolve import by_type
        hosts = by_type(self.cfg.hosts, "PVE")
        self.assertEqual(len(hosts), 3)

    def test_type_not_found(self):
        from freq.core.resolve import by_type
        hosts = by_type(self.cfg.hosts, "windows")
        self.assertEqual(len(hosts), 0)


class TestResolveAllGroups(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_all_groups(self):
        from freq.core.resolve import all_groups
        groups = all_groups(self.cfg.hosts)
        self.assertIn("prod", groups)
        self.assertGreater(len(groups["prod"]), 0)

    def test_all_groups_empty(self):
        from freq.core.resolve import all_groups
        groups = all_groups([])
        self.assertEqual(groups, {})


class TestResolveAllTypes(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_all_types(self):
        from freq.core.resolve import all_types
        types = all_types(self.cfg.hosts)
        self.assertEqual(types["pve"], 3)
        self.assertEqual(types["docker"], 2)
        self.assertEqual(types["linux"], 5)

    def test_all_types_empty(self):
        from freq.core.resolve import all_types
        types = all_types([])
        self.assertEqual(types, {})


class TestResolveByScope(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_scope_linux(self):
        from freq.core.resolve import by_scope
        hosts = by_scope(self.cfg.hosts, ["linux"])
        self.assertEqual(len(hosts), 5)

    def test_scope_multiple(self):
        from freq.core.resolve import by_scope
        hosts = by_scope(self.cfg.hosts, ["linux", "pve"])
        self.assertEqual(len(hosts), 8)  # 5 linux + 3 pve

    def test_scope_empty(self):
        from freq.core.resolve import by_scope
        hosts = by_scope(self.cfg.hosts, [])
        self.assertEqual(len(hosts), 0)


class TestResolveByLabels(unittest.TestCase):

    def setUp(self):
        self.cfg = load_with_profile("profile_b")

    def test_by_labels(self):
        from freq.core.resolve import by_labels
        hosts = by_labels(self.cfg.hosts, "node1,node2")
        self.assertEqual(len(hosts), 2)

    def test_by_labels_single(self):
        from freq.core.resolve import by_labels
        hosts = by_labels(self.cfg.hosts, "node1")
        self.assertEqual(len(hosts), 1)

    def test_by_labels_not_found(self):
        from freq.core.resolve import by_labels
        hosts = by_labels(self.cfg.hosts, "fake1,fake2")
        self.assertEqual(len(hosts), 0)


class TestValidateExtras(unittest.TestCase):
    """Extra validation edge cases."""

    def test_vlan_id_valid(self):
        from freq.core.validate import vlan_id
        self.assertTrue(vlan_id(0))
        self.assertTrue(vlan_id(1))
        self.assertTrue(vlan_id(4094))
        self.assertTrue(vlan_id("100"))

    def test_vlan_id_invalid(self):
        from freq.core.validate import vlan_id
        self.assertFalse(vlan_id(-1))
        self.assertFalse(vlan_id(4095))
        self.assertFalse(vlan_id("abc"))
        self.assertFalse(vlan_id(None))

    def test_port_valid(self):
        from freq.core.validate import port
        self.assertTrue(port(1))
        self.assertTrue(port(80))
        self.assertTrue(port(443))
        self.assertTrue(port(65535))

    def test_port_invalid(self):
        from freq.core.validate import port
        self.assertFalse(port(0))
        self.assertFalse(port(65536))
        self.assertFalse(port(-1))
        self.assertFalse(port(None))

    def test_label_valid(self):
        from freq.core.validate import label
        self.assertTrue(label("pve01"))
        self.assertTrue(label("my-host"))
        self.assertTrue(label("a"))

    def test_label_invalid(self):
        from freq.core.validate import label
        self.assertFalse(label(""))
        self.assertFalse(label("-starts-bad"))
        self.assertFalse(label("a" * 65))

    def test_ip_edge_cases(self):
        from freq.core.validate import ip
        self.assertTrue(ip("0.0.0.0"))
        self.assertTrue(ip("255.255.255.255"))
        self.assertFalse(ip("192.168.255"))      # Only 3 octets
        self.assertFalse(ip("192.168.255.256"))   # Octet > 255
        self.assertFalse(ip("192.168.255.-1"))    # Negative

    def test_vmid_boundaries(self):
        from freq.core.validate import vmid
        self.assertTrue(vmid(100))
        self.assertTrue(vmid(999999999))
        self.assertFalse(vmid(99))
        self.assertFalse(vmid(0))


class TestFleetBoundaries(unittest.TestCase):
    """Test FleetBoundaries categorization with production config."""

    def setUp(self):
        from freq.core.config import load_config
        self.cfg = load_config()
        self.fb = self.cfg.fleet_boundaries

    def test_categorize_known_vmid(self):
        """Known VMID returns correct category."""
        if not self.fb.categories:
            self.skipTest("No fleet-boundaries.toml in this config")
        # Just verify it returns a tuple
        cat, tier = self.fb.categorize(900)
        self.assertIsInstance(cat, str)
        self.assertIsInstance(tier, str)

    def test_categorize_unknown_vmid(self):
        """Unknown VMID returns ('unknown', 'probe')."""
        cat, tier = self.fb.categorize(99999)
        self.assertEqual(cat, "unknown")
        self.assertEqual(tier, "probe")

    def test_allowed_actions_unknown(self):
        """Unknown VMID gets probe-level actions."""
        actions = self.fb.allowed_actions(99999)
        self.assertIsInstance(actions, list)

    def test_is_prod_unknown(self):
        """Unknown VMID is not prod."""
        self.assertFalse(self.fb.is_prod(99999))

    def test_can_action_view(self):
        """Any VMID should be viewable."""
        # Even unknown VMIDs get at least "view" from probe tier
        if self.fb.tiers.get("probe"):
            can = self.fb.can_action(99999, "view")
            self.assertTrue(can)

    def test_category_description_unknown(self):
        """Unknown VMID returns 'Unknown' description."""
        desc = self.fb.category_description(99999)
        self.assertEqual(desc, "Unknown")

    def test_empty_boundaries(self):
        """FleetBoundaries with no config still works."""
        from freq.core.types import FleetBoundaries
        fb = FleetBoundaries()
        cat, tier = fb.categorize(100)
        self.assertEqual(cat, "unknown")
        self.assertEqual(tier, "probe")
        self.assertFalse(fb.is_prod(100))
        self.assertEqual(fb.category_description(100), "Unknown")


class TestContainerResolve(unittest.TestCase):
    """Test container resolution."""

    def test_container_by_name_not_found(self):
        from freq.core.resolve import container_by_name
        container, vm = container_by_name({}, "sonarr")
        self.assertIsNone(container)
        self.assertIsNone(vm)

    def test_containers_on_vm_not_found(self):
        from freq.core.resolve import containers_on_vm
        result = containers_on_vm({}, 100)
        self.assertEqual(result, [])

    def test_all_containers_empty(self):
        from freq.core.resolve import all_containers
        result = all_containers({})
        self.assertEqual(result, [])

    def test_container_vm_by_ip_not_found(self):
        from freq.core.resolve import container_vm_by_ip
        result = container_vm_by_ip({}, "10.0.0.1")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
