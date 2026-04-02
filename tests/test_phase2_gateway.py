"""Tests for Phase 2 — The Gateway: firewall, DNS, VPN, certs, proxy.

Covers: Module imports, CLI registration, DHCP parser, WireGuard parser,
        DNS inventory CRUD, proxy backend detection.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Mock Config
# ---------------------------------------------------------------------------

@dataclass
class MockHost:
    ip: str
    label: str
    htype: str
    groups: str = ""


class MockConfig:
    def __init__(self, tmpdir=None):
        self.conf_dir = tmpdir or tempfile.mkdtemp()
        self.hosts = [
            MockHost("10.25.255.5", "switch", "switch"),
            MockHost("10.25.255.1", "pfsense", "pfsense"),
        ]
        self.pfsense_ip = "10.25.255.1"
        self.switch_ip = "10.25.255.5"
        self.ssh_key_path = "/tmp/test"
        self.ssh_rsa_key_path = "/tmp/test_rsa"
        self.ssh_connect_timeout = 5


# ---------------------------------------------------------------------------
# Firewall Tests
# ---------------------------------------------------------------------------

DHCP_LEASES = """
lease 10.25.255.100 {
  starts 2 2026/04/01 12:00:00;
  ends 2 2026/04/01 20:00:00;
  hardware ethernet aa:bb:cc:dd:ee:01;
  client-hostname "desktop-01";
}
lease 10.25.255.101 {
  starts 2 2026/04/01 13:00:00;
  ends 2 2026/04/01 21:00:00;
  hardware ethernet aa:bb:cc:dd:ee:02;
  client-hostname "laptop-02";
}
"""


class TestDHCPParser(unittest.TestCase):
    """Test DHCP lease parsing."""

    def setUp(self):
        from freq.modules.firewall import _parse_dhcp_leases
        self.parse = _parse_dhcp_leases

    def test_parse_leases(self):
        leases = self.parse(DHCP_LEASES)
        self.assertEqual(len(leases), 2)

    def test_lease_fields(self):
        leases = self.parse(DHCP_LEASES)
        l = leases[0]
        self.assertEqual(l["ip"], "10.25.255.100")
        self.assertEqual(l["mac"], "aa:bb:cc:dd:ee:01")
        self.assertEqual(l["hostname"], "desktop-01")

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestFirewallImports(unittest.TestCase):
    """Test firewall module imports."""

    def test_all_commands(self):
        from freq.modules.firewall import (
            cmd_fw_status, cmd_fw_rules, cmd_fw_nat,
            cmd_fw_states, cmd_fw_interfaces, cmd_fw_gateways,
            cmd_fw_dhcp,
        )
        self.assertTrue(callable(cmd_fw_status))


# ---------------------------------------------------------------------------
# DNS Tests
# ---------------------------------------------------------------------------

class TestDNSInventory(unittest.TestCase):
    """Test DNS internal record CRUD."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)

    def test_add_and_list(self):
        from freq.modules.dns_management import _load_dns_inventory, _save_dns_inventory
        data = _load_dns_inventory(self.cfg)
        data["records"].append({"hostname": "test.local", "ip": "10.0.0.1", "type": "A"})
        _save_dns_inventory(self.cfg, data)
        reloaded = _load_dns_inventory(self.cfg)
        self.assertEqual(len(reloaded["records"]), 1)

    def test_empty_load(self):
        from freq.modules.dns_management import _load_dns_inventory
        data = _load_dns_inventory(self.cfg)
        self.assertEqual(data["records"], [])


class TestDNSImports(unittest.TestCase):
    """Test DNS management module imports."""

    def test_all_commands(self):
        from freq.modules.dns_management import (
            cmd_dns_internal_list, cmd_dns_internal_add,
            cmd_dns_internal_remove, cmd_dns_internal_sync,
            cmd_dns_internal_audit,
        )
        self.assertTrue(callable(cmd_dns_internal_list))


# ---------------------------------------------------------------------------
# VPN Tests
# ---------------------------------------------------------------------------

WG_SHOW_OUTPUT = """interface: wg0
  public key: abcdef1234567890abcdef1234567890abcdef123456=
  private key: (hidden)
  listening port: 51820

peer: QRSTUVWXYZ1234567890abcdef1234567890abcdef12=
  endpoint: 203.0.113.50:51820
  allowed ips: 10.25.100.2/32
  latest handshake: 1 minute, 30 seconds ago
  transfer: 1.5 MiB received, 3.2 MiB sent
"""


class TestWGParser(unittest.TestCase):
    """Test WireGuard output parser."""

    def setUp(self):
        from freq.modules.vpn import _parse_wg_show
        self.parse = _parse_wg_show

    def test_parse_peers(self):
        peers = self.parse(WG_SHOW_OUTPUT)
        self.assertEqual(len(peers), 1)

    def test_peer_fields(self):
        peers = self.parse(WG_SHOW_OUTPUT)
        p = peers[0]
        self.assertEqual(p["interface"], "wg0")
        self.assertIn("QRSTUVWXYZ", p["public_key"])
        self.assertIn("203.0.113.50", p["endpoint"])

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestVPNImports(unittest.TestCase):
    """Test VPN module imports."""

    def test_all_commands(self):
        from freq.modules.vpn import (
            cmd_vpn_wg_status, cmd_vpn_wg_peers, cmd_vpn_wg_audit,
            cmd_vpn_ovpn_status,
        )
        self.assertTrue(callable(cmd_vpn_wg_status))


# ---------------------------------------------------------------------------
# Certificate Tests
# ---------------------------------------------------------------------------

class TestCertImports(unittest.TestCase):
    """Test cert management module imports."""

    def test_all_commands(self):
        from freq.modules.cert_management import (
            cmd_cert_inspect, cmd_cert_fleet_check,
            cmd_cert_acme_status, cmd_cert_issued_list,
        )
        self.assertTrue(callable(cmd_cert_inspect))


class TestCertIssuedStorage(unittest.TestCase):
    """Test issued cert tracking."""

    def test_empty_load(self):
        from freq.modules.cert_management import _load_issued
        cfg = MockConfig(tempfile.mkdtemp())
        data = _load_issued(cfg)
        self.assertEqual(data["certs"], [])

    def test_save_and_load(self):
        from freq.modules.cert_management import _load_issued, _save_issued
        cfg = MockConfig(tempfile.mkdtemp())
        data = {"certs": [{"domain": "test.com", "type": "acme"}]}
        _save_issued(cfg, data)
        reloaded = _load_issued(cfg)
        self.assertEqual(len(reloaded["certs"]), 1)


# ---------------------------------------------------------------------------
# Proxy Tests
# ---------------------------------------------------------------------------

class TestProxyImports(unittest.TestCase):
    """Test proxy management module imports."""

    def test_all_commands(self):
        from freq.modules.proxy_management import (
            cmd_proxy_status, cmd_proxy_hosts, cmd_proxy_health,
        )
        self.assertTrue(callable(cmd_proxy_status))


# ---------------------------------------------------------------------------
# CLI Registration Tests
# ---------------------------------------------------------------------------

class TestPhase2CLIRegistration(unittest.TestCase):
    """Test that all Phase 2 commands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    # Firewall
    def test_fw_status(self):
        args = self._parse("fw status")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_rules(self):
        args = self._parse("fw rules")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_rules_audit(self):
        args = self._parse("fw rules audit")
        self.assertEqual(args.action, "audit")

    def test_fw_nat(self):
        args = self._parse("fw nat")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_states(self):
        args = self._parse("fw states")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_dhcp(self):
        args = self._parse("fw dhcp")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_interfaces(self):
        args = self._parse("fw interfaces")
        self.assertTrue(hasattr(args, "func"))

    def test_fw_gateways(self):
        args = self._parse("fw gateways")
        self.assertTrue(hasattr(args, "func"))

    # DNS
    def test_dns_scan(self):
        args = self._parse("dns scan")
        self.assertTrue(hasattr(args, "func"))

    def test_dns_internal_list(self):
        args = self._parse("dns internal list")
        self.assertTrue(hasattr(args, "func"))

    def test_dns_internal_add(self):
        args = self._parse("dns internal add test.local 10.0.0.1")
        self.assertEqual(args.hostname, "test.local")
        self.assertEqual(args.ip, "10.0.0.1")

    def test_dns_internal_sync(self):
        args = self._parse("dns internal sync")
        self.assertTrue(hasattr(args, "func"))

    # VPN
    def test_vpn_domain_registered(self):
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertIn("vpn", registered)

    def test_vpn_wg_status(self):
        args = self._parse("vpn wg status")
        self.assertTrue(hasattr(args, "func"))

    def test_vpn_wg_peers(self):
        args = self._parse("vpn wg peers")
        self.assertTrue(hasattr(args, "func"))

    def test_vpn_wg_audit(self):
        args = self._parse("vpn wg audit")
        self.assertTrue(hasattr(args, "func"))

    def test_vpn_ovpn_status(self):
        args = self._parse("vpn ovpn status")
        self.assertTrue(hasattr(args, "func"))

    # Cert
    def test_cert_inspect(self):
        args = self._parse("cert inspect google.com:443")
        self.assertEqual(args.target, "google.com:443")

    def test_cert_fleet_check(self):
        args = self._parse("cert fleet-check")
        self.assertTrue(hasattr(args, "func"))

    def test_cert_acme(self):
        args = self._parse("cert acme")
        self.assertTrue(hasattr(args, "func"))

    def test_cert_issued(self):
        args = self._parse("cert issued")
        self.assertTrue(hasattr(args, "func"))

    # Proxy
    def test_proxy_status(self):
        args = self._parse("proxy status")
        self.assertTrue(hasattr(args, "func"))

    def test_proxy_hosts(self):
        args = self._parse("proxy hosts")
        self.assertTrue(hasattr(args, "func"))

    def test_proxy_health(self):
        args = self._parse("proxy health")
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
