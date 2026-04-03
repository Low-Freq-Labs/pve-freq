"""Tests for IPAM — IP Address Management."""
import ipaddress
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSubnetParsing(unittest.TestCase):
    """Test subnet parsing utility."""

    def test_valid_cidr(self):
        from freq.modules.ipam import _parse_subnet
        net = _parse_subnet("10.0.0.0/24")
        self.assertIsNotNone(net)
        self.assertEqual(str(net), "10.0.0.0/24")

    def test_valid_cidr_16(self):
        from freq.modules.ipam import _parse_subnet
        net = _parse_subnet("172.16.0.0/16")
        self.assertIsNotNone(net)
        self.assertEqual(net.prefixlen, 16)

    def test_host_in_subnet(self):
        from freq.modules.ipam import _parse_subnet
        net = _parse_subnet("10.0.0.50/24")
        self.assertIsNotNone(net)
        self.assertEqual(str(net), "10.0.0.0/24")

    def test_invalid_subnet(self):
        from freq.modules.ipam import _parse_subnet
        self.assertIsNone(_parse_subnet("not-a-subnet"))

    def test_empty_string(self):
        from freq.modules.ipam import _parse_subnet
        self.assertIsNone(_parse_subnet(""))

    def test_none_input(self):
        from freq.modules.ipam import _parse_subnet
        self.assertIsNone(_parse_subnet(None))


class TestNextAvailable(unittest.TestCase):
    """Test next available IP finder."""

    def test_first_available(self):
        from freq.modules.ipam import _next_available
        subnet = ipaddress.IPv4Network("10.0.0.0/24")
        used = set()
        result = _next_available(subnet, used, count=1, start_offset=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(str(result[0]), "10.0.0.10")

    def test_skip_used(self):
        from freq.modules.ipam import _next_available
        subnet = ipaddress.IPv4Network("10.0.0.0/24")
        used = {ipaddress.IPv4Address("10.0.0.10"), ipaddress.IPv4Address("10.0.0.11")}
        result = _next_available(subnet, used, count=1, start_offset=10)
        self.assertEqual(str(result[0]), "10.0.0.12")

    def test_multiple_available(self):
        from freq.modules.ipam import _next_available
        subnet = ipaddress.IPv4Network("10.0.0.0/24")
        result = _next_available(subnet, set(), count=3, start_offset=10)
        self.assertEqual(len(result), 3)
        self.assertEqual(str(result[0]), "10.0.0.10")
        self.assertEqual(str(result[1]), "10.0.0.11")
        self.assertEqual(str(result[2]), "10.0.0.12")

    def test_skip_reserved_range(self):
        from freq.modules.ipam import _next_available
        subnet = ipaddress.IPv4Network("10.0.0.0/24")
        result = _next_available(subnet, set(), count=1, start_offset=20)
        self.assertEqual(str(result[0]), "10.0.0.20")

    def test_dense_subnet(self):
        from freq.modules.ipam import _next_available
        subnet = ipaddress.IPv4Network("10.0.0.0/29")  # 6 usable hosts
        used = {
            ipaddress.IPv4Address("10.0.0.1"),
            ipaddress.IPv4Address("10.0.0.2"),
            ipaddress.IPv4Address("10.0.0.3"),
            ipaddress.IPv4Address("10.0.0.4"),
            ipaddress.IPv4Address("10.0.0.5"),
            ipaddress.IPv4Address("10.0.0.6"),
        }
        result = _next_available(subnet, used, count=1, start_offset=1)
        self.assertEqual(len(result), 0)  # All full

    def test_gaps_in_used(self):
        from freq.modules.ipam import _next_available
        subnet = ipaddress.IPv4Network("10.0.0.0/24")
        used = {
            ipaddress.IPv4Address("10.0.0.10"),
            ipaddress.IPv4Address("10.0.0.12"),
            ipaddress.IPv4Address("10.0.0.14"),
        }
        result = _next_available(subnet, used, count=3, start_offset=10)
        self.assertEqual(len(result), 3)
        self.assertEqual(str(result[0]), "10.0.0.11")
        self.assertEqual(str(result[1]), "10.0.0.13")
        self.assertEqual(str(result[2]), "10.0.0.15")


class TestFindVlan(unittest.TestCase):
    """Test VLAN lookup."""

    def test_find_by_name(self):
        from freq.modules.ipam import _find_vlan
        from unittest.mock import MagicMock
        from freq.core.types import VLAN
        cfg = MagicMock()
        cfg.vlans = [
            VLAN(id=10, name="MGMT", subnet="10.0.0.0/24", prefix="10.0.0"),
            VLAN(id=20, name="STORAGE", subnet="10.0.1.0/24", prefix="10.0.1"),
        ]
        result = _find_vlan(cfg, "mgmt")
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 10)

    def test_case_insensitive(self):
        from freq.modules.ipam import _find_vlan
        from unittest.mock import MagicMock
        from freq.core.types import VLAN
        cfg = MagicMock()
        cfg.vlans = [VLAN(id=10, name="MGMT", subnet="10.0.0.0/24", prefix="10.0.0")]
        self.assertIsNotNone(_find_vlan(cfg, "Mgmt"))
        self.assertIsNotNone(_find_vlan(cfg, "MGMT"))
        self.assertIsNotNone(_find_vlan(cfg, "mgmt"))

    def test_not_found(self):
        from freq.modules.ipam import _find_vlan
        from unittest.mock import MagicMock
        cfg = MagicMock()
        cfg.vlans = []
        self.assertIsNone(_find_vlan(cfg, "nonexistent"))


class TestCheckIP(unittest.TestCase):
    """Test IP availability checking."""

    def test_ip_in_use_by_host(self):
        from freq.modules.ipam import _check_ip
        from unittest.mock import MagicMock
        from freq.core.types import Host
        cfg = MagicMock()
        cfg.hosts = [Host(ip="10.0.0.50", label="web-01", htype="linux")]
        cfg.vm_gateway = ""
        cfg.vm_nameserver = ""
        cfg.truenas_ip = ""
        cfg.pfsense_ip = ""
        cfg.switch_ip = ""
        cfg.docker_dev_ip = ""
        result = _check_ip(cfg, "10.0.0.50")
        self.assertTrue(result["in_use"])
        self.assertEqual(result["owner"], "web-01")

    def test_ip_available(self):
        from freq.modules.ipam import _check_ip
        from unittest.mock import MagicMock
        cfg = MagicMock()
        cfg.hosts = []
        cfg.vm_gateway = ""
        cfg.vm_nameserver = ""
        cfg.truenas_ip = ""
        cfg.pfsense_ip = ""
        cfg.switch_ip = ""
        cfg.docker_dev_ip = ""
        result = _check_ip(cfg, "10.0.0.99")
        self.assertFalse(result["in_use"])

    def test_ip_is_gateway(self):
        from freq.modules.ipam import _check_ip
        from unittest.mock import MagicMock
        cfg = MagicMock()
        cfg.hosts = []
        cfg.vm_gateway = "10.0.0.1"
        cfg.vm_nameserver = ""
        cfg.truenas_ip = ""
        cfg.pfsense_ip = ""
        cfg.switch_ip = ""
        cfg.docker_dev_ip = ""
        result = _check_ip(cfg, "10.0.0.1")
        self.assertTrue(result["in_use"])
        self.assertEqual(result["owner"], "gateway")

    def test_invalid_ip(self):
        from freq.modules.ipam import _check_ip
        from unittest.mock import MagicMock
        cfg = MagicMock()
        cfg.hosts = []
        result = _check_ip(cfg, "not-an-ip")
        self.assertIn("error", result)

    def test_ip_with_cidr(self):
        from freq.modules.ipam import _check_ip
        from unittest.mock import MagicMock
        from freq.core.types import Host
        cfg = MagicMock()
        cfg.hosts = [Host(ip="10.0.0.50", label="db-01", htype="linux")]
        cfg.vm_gateway = ""
        cfg.vm_nameserver = ""
        cfg.truenas_ip = ""
        cfg.pfsense_ip = ""
        cfg.switch_ip = ""
        cfg.docker_dev_ip = ""
        result = _check_ip(cfg, "10.0.0.50/24")
        self.assertTrue(result["in_use"])


class TestListIPs(unittest.TestCase):
    """Test IP listing."""

    def test_list_all(self):
        from freq.modules.ipam import _list_ips
        from unittest.mock import MagicMock
        from freq.core.types import Host
        cfg = MagicMock()
        cfg.hosts = [
            Host(ip="10.0.0.10", label="a", htype="linux"),
            Host(ip="10.0.0.20", label="b", htype="linux"),
        ]
        cfg.pve_nodes = []
        cfg.vlans = []
        cfg.vm_gateway = ""
        cfg.vm_nameserver = ""
        cfg.truenas_ip = ""
        cfg.pfsense_ip = ""
        cfg.switch_ip = ""
        cfg.docker_dev_ip = ""
        result = _list_ips(cfg)
        self.assertIn("10.0.0.10", result)
        self.assertIn("10.0.0.20", result)


class TestIPAMCLI(unittest.TestCase):
    """Test CLI registration for ip command (under net domain)."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_ip_registered(self):
        """ip is registered as a subcommand under the 'net' domain."""
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertIn("net", registered)

    def test_ip_next(self):
        args = self.parser.parse_args(["net", "ip", "next", "--vlan", "mgmt"])
        self.assertEqual(args.action, "next")
        self.assertEqual(args.vlan, "mgmt")

    def test_ip_list(self):
        args = self.parser.parse_args(["net", "ip", "list"])
        self.assertEqual(args.action, "list")

    def test_ip_check(self):
        args = self.parser.parse_args(["net", "ip", "check", "10.0.0.50"])
        self.assertEqual(args.action, "check")
        self.assertEqual(args.target, "10.0.0.50")

    def test_ip_count(self):
        args = self.parser.parse_args(["net", "ip", "next", "--vlan", "lan", "--count", "5"])
        self.assertEqual(args.count, 5)


if __name__ == "__main__":
    unittest.main()
