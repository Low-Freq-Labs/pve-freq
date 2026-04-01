"""Tests for switch orchestration — Cisco deployer parsers and CLI integration.

Covers: Cisco IOS output parsers, target resolution, CLI subcommand registration.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Sample Cisco IOS Output — realistic show command responses
# ---------------------------------------------------------------------------

SHOW_VERSION = """
Cisco IOS Software, C3750E Software (C3750E-UNIVERSALK9-M), Version 15.2(4)E10, RELEASE SOFTWARE (fc2)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2020 by Cisco Systems, Inc.
Compiled Tue 14-Jul-20 07:07 by prod_rel_team

ROM: Bootstrap program is C3750E boot loader
BOOTLDR: C3750E Boot Loader (C3750E-HBOOT-M) Version 12.2(58r)SE1

DC01-SW01 uptime is 45 days, 12 hours, 33 minutes
System returned to ROM by power-on
System restarted at 14:22:31 CDT Mon Mar 15 2026
System image file is "flash:c3750e-universalk9-mz.152-4.E10.bin"

cisco WS-C3750X-24T-S (PowerPC405) processor (revision W0) with 262144K bytes of memory.
Processor board ID FDO1234X5Y6

Last reset from power-on
2 Virtual Ethernet interfaces
1 FastEthernet interface
28 Gigabit Ethernet interfaces
The password-recovery mechanism is enabled.

512K bytes of flash-simulated non-volatile configuration memory.
"""

SHOW_INTERFACES_STATUS = """
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   Camera-Lobby       connected    50         a-full  a-1000 10/100/1000BaseTX
Gi1/0/2   Camera-Hall        connected    50         a-full  a-1000 10/100/1000BaseTX
Gi1/0/3                      notconnect   1          auto    auto  10/100/1000BaseTX
Gi1/0/4   Workstation-A      connected    10         a-full  a-1000 10/100/1000BaseTX
Gi1/0/5                      disabled     1          auto    auto  10/100/1000BaseTX
Gi1/0/6   AP-Floor2          connected    25         a-full  a-1000 10/100/1000BaseTX
Gi1/0/7   Server-Rack        err-disabled 2550       full    1000  10/100/1000BaseTX
Gi1/0/24  Uplink-Core        connected    trunk      a-full  a-10G SFP-10GBase-SR
"""

SHOW_VLAN_BRIEF = """
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi1/0/3, Gi1/0/5
5    PUBLIC                           active    Gi1/0/20, Gi1/0/21
10   DEVLAB                           active    Gi1/0/4
25   STORAGE                          active    Gi1/0/6
50   CAMERAS                          active    Gi1/0/1, Gi1/0/2
2550 MGMT                             active    Gi1/0/7
1002 fddi-default                     act/unsup
1003 token-ring-default               act/unsup
"""

SHOW_MAC_TABLE = """
          Mac Address Table
-------------------------------------------

Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  50    aabb.cc00.1111    DYNAMIC     Gi1/0/1
  50    aabb.cc00.2222    DYNAMIC     Gi1/0/2
  10    ddee.ff00.3333    DYNAMIC     Gi1/0/4
2550    1122.3344.5566    STATIC      Gi1/0/7
Total Mac Addresses for this criterion: 4
"""

SHOW_ARP = """
Protocol  Address          Age (min)  Hardware Addr   Type   Interface
Internet  10.25.255.1      -          aabb.ccdd.ee00  ARPA   Vlan2550
Internet  10.25.255.5      0          1122.3344.5566  ARPA   Vlan2550
Internet  10.25.5.100      15         ddee.ff00.1234  ARPA   Vlan5
Internet  10.25.25.10      3          aabb.cc00.9999  ARPA   Vlan25
"""

SHOW_CDP_DETAIL = """
-------------------------
Device ID: core-switch.dc01.local
Entry address(es):
  IP address: 10.25.255.1
Platform: cisco WS-C9300-48P, Capabilities: Router Switch IGMP
Interface: GigabitEthernet1/0/24,  Port ID (outgoing port): GigabitEthernet0/0/1
Holdtime : 131 sec

Version :
Cisco IOS Software, Catalyst L3 Switch Software

advertisement version: 2
Duplex: full

-------------------------
Device ID: access-point-floor2
Entry address(es):
  IP address: 10.25.25.50
Platform: Cisco AIR-AP3802I, Capabilities: Trans-Bridge
Interface: GigabitEthernet1/0/6,  Port ID (outgoing port): GigabitEthernet0
Holdtime : 145 sec

Version :
Cisco AP Software
"""


# ---------------------------------------------------------------------------
# Cisco Parser Tests
# ---------------------------------------------------------------------------

class TestCiscoParseShowVersion(unittest.TestCase):
    """Test _parse_show_version parser."""

    def setUp(self):
        from freq.deployers.switch.cisco import _parse_show_version
        self.parse = _parse_show_version

    def test_hostname(self):
        facts = self.parse(SHOW_VERSION)
        self.assertEqual(facts["hostname"], "DC01-SW01")

    def test_uptime(self):
        facts = self.parse(SHOW_VERSION)
        self.assertIn("45 days", facts["uptime"])

    def test_model(self):
        facts = self.parse(SHOW_VERSION)
        self.assertEqual(facts["model"], "WS-C3750X-24T-S")

    def test_serial(self):
        facts = self.parse(SHOW_VERSION)
        self.assertEqual(facts["serial"], "FDO1234X5Y6")

    def test_os_version(self):
        facts = self.parse(SHOW_VERSION)
        self.assertIn("15.2(4)E10", facts["os_version"])

    def test_image(self):
        facts = self.parse(SHOW_VERSION)
        self.assertIn("c3750e", facts["image"])

    def test_empty_input(self):
        facts = self.parse("")
        self.assertEqual(facts["hostname"], "")
        self.assertEqual(facts["model"], "")

    def test_all_keys_present(self):
        facts = self.parse(SHOW_VERSION)
        for key in ("hostname", "model", "serial", "os_version", "uptime", "image"):
            self.assertIn(key, facts)


class TestCiscoParseInterfacesStatus(unittest.TestCase):
    """Test _parse_interfaces_status parser."""

    def setUp(self):
        from freq.deployers.switch.cisco import _parse_interfaces_status
        self.parse = _parse_interfaces_status

    def test_count(self):
        ifaces = self.parse(SHOW_INTERFACES_STATUS)
        self.assertEqual(len(ifaces), 8)

    def test_connected_port(self):
        ifaces = self.parse(SHOW_INTERFACES_STATUS)
        gi1 = next(i for i in ifaces if i["name"] == "Gi1/0/1")
        self.assertEqual(gi1["status"], "connected")
        self.assertEqual(gi1["description"], "Camera-Lobby")
        self.assertEqual(gi1["vlan"], "50")

    def test_notconnect_port(self):
        ifaces = self.parse(SHOW_INTERFACES_STATUS)
        gi3 = next(i for i in ifaces if i["name"] == "Gi1/0/3")
        self.assertEqual(gi3["status"], "notconnect")
        self.assertEqual(gi3["description"], "")

    def test_disabled_port(self):
        ifaces = self.parse(SHOW_INTERFACES_STATUS)
        gi5 = next(i for i in ifaces if i["name"] == "Gi1/0/5")
        self.assertEqual(gi5["status"], "disabled")

    def test_err_disabled_port(self):
        ifaces = self.parse(SHOW_INTERFACES_STATUS)
        gi7 = next(i for i in ifaces if i["name"] == "Gi1/0/7")
        self.assertEqual(gi7["status"], "err-disabled")

    def test_trunk_port(self):
        ifaces = self.parse(SHOW_INTERFACES_STATUS)
        gi24 = next(i for i in ifaces if i["name"] == "Gi1/0/24")
        self.assertEqual(gi24["status"], "connected")
        self.assertEqual(gi24["vlan"], "trunk")
        self.assertEqual(gi24["description"], "Uplink-Core")

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestCiscoParseVlanBrief(unittest.TestCase):
    """Test _parse_vlan_brief parser."""

    def setUp(self):
        from freq.deployers.switch.cisco import _parse_vlan_brief
        self.parse = _parse_vlan_brief

    def test_count(self):
        vlans = self.parse(SHOW_VLAN_BRIEF)
        # 6 real VLANs + 2 unsupported
        self.assertGreaterEqual(len(vlans), 6)

    def test_vlan_id(self):
        vlans = self.parse(SHOW_VLAN_BRIEF)
        ids = [v["id"] for v in vlans]
        self.assertIn(1, ids)
        self.assertIn(50, ids)
        self.assertIn(2550, ids)

    def test_vlan_name(self):
        vlans = self.parse(SHOW_VLAN_BRIEF)
        v50 = next(v for v in vlans if v["id"] == 50)
        self.assertEqual(v50["name"], "CAMERAS")

    def test_vlan_ports(self):
        vlans = self.parse(SHOW_VLAN_BRIEF)
        v50 = next(v for v in vlans if v["id"] == 50)
        self.assertIn("Gi1/0/1", v50["ports"])
        self.assertIn("Gi1/0/2", v50["ports"])

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestCiscoParseMacTable(unittest.TestCase):
    """Test _parse_mac_table parser."""

    def setUp(self):
        from freq.deployers.switch.cisco import _parse_mac_table
        self.parse = _parse_mac_table

    def test_count(self):
        entries = self.parse(SHOW_MAC_TABLE)
        self.assertEqual(len(entries), 4)

    def test_entry_fields(self):
        entries = self.parse(SHOW_MAC_TABLE)
        e = entries[0]
        self.assertEqual(e["vlan"], 50)
        self.assertEqual(e["mac"], "aabb.cc00.1111")
        self.assertEqual(e["type"], "dynamic")
        self.assertEqual(e["port"], "Gi1/0/1")

    def test_static_entry(self):
        entries = self.parse(SHOW_MAC_TABLE)
        static = next(e for e in entries if e["type"] == "static")
        self.assertEqual(static["vlan"], 2550)

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestCiscoParseArpTable(unittest.TestCase):
    """Test _parse_arp_table parser."""

    def setUp(self):
        from freq.deployers.switch.cisco import _parse_arp_table
        self.parse = _parse_arp_table

    def test_count(self):
        entries = self.parse(SHOW_ARP)
        self.assertEqual(len(entries), 4)

    def test_entry_fields(self):
        entries = self.parse(SHOW_ARP)
        e = next(a for a in entries if a["ip"] == "10.25.255.5")
        self.assertEqual(e["mac"], "1122.3344.5566")
        self.assertEqual(e["interface"], "Vlan2550")

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


class TestCiscoParseCdpDetail(unittest.TestCase):
    """Test _parse_cdp_detail parser."""

    def setUp(self):
        from freq.deployers.switch.cisco import _parse_cdp_detail
        self.parse = _parse_cdp_detail

    def test_count(self):
        neighbors = self.parse(SHOW_CDP_DETAIL)
        self.assertEqual(len(neighbors), 2)

    def test_neighbor_fields(self):
        neighbors = self.parse(SHOW_CDP_DETAIL)
        core = next(n for n in neighbors if "core" in n["device"])
        self.assertEqual(core["ip"], "10.25.255.1")
        self.assertIn("9300", core["platform"])
        self.assertEqual(core["local_port"], "GigabitEthernet1/0/24")
        self.assertEqual(core["remote_port"], "GigabitEthernet0/0/1")

    def test_ap_neighbor(self):
        neighbors = self.parse(SHOW_CDP_DETAIL)
        ap = next(n for n in neighbors if "access-point" in n["device"])
        self.assertEqual(ap["ip"], "10.25.25.50")

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


# ---------------------------------------------------------------------------
# Target Resolution Tests
# ---------------------------------------------------------------------------

@dataclass
class MockHost:
    ip: str
    label: str
    htype: str
    groups: str = ""


class MockConfig:
    def __init__(self):
        self.hosts = [
            MockHost("10.25.255.5", "switch", "switch"),
            MockHost("10.25.255.26", "pve01", "pve"),
        ]
        self.switch_ip = "10.25.255.5"
        self.ssh_key_path = "/home/test/.ssh/id_ed25519"
        self.ssh_rsa_key_path = "/home/test/.ssh/id_rsa"
        self.ssh_connect_timeout = 5
        self.conf_dir = "/tmp/freq-test/conf"


class TestTargetResolution(unittest.TestCase):
    """Test switch target resolution."""

    def setUp(self):
        from freq.modules.switch_orchestration import _resolve_target
        self.resolve = _resolve_target
        self.cfg = MockConfig()

    def test_resolve_by_label(self):
        ip, label, vendor = self.resolve("switch", self.cfg)
        self.assertEqual(ip, "10.25.255.5")
        self.assertEqual(label, "switch")

    def test_resolve_by_ip(self):
        ip, label, vendor = self.resolve("10.25.255.5", self.cfg)
        self.assertEqual(ip, "10.25.255.5")

    def test_resolve_default(self):
        ip, label, vendor = self.resolve(None, self.cfg)
        self.assertEqual(ip, "10.25.255.5")

    def test_resolve_bare_ip(self):
        ip, label, vendor = self.resolve("192.168.1.1", self.cfg)
        self.assertEqual(ip, "192.168.1.1")
        self.assertEqual(vendor, "cisco")  # default

    def test_resolve_unknown(self):
        ip, label, vendor = self.resolve("nonexistent", self.cfg)
        self.assertIsNone(ip)

    def test_no_switch_ip_no_target(self):
        cfg = MockConfig()
        cfg.switch_ip = ""
        cfg.hosts = []
        ip, label, vendor = self.resolve(None, cfg)
        self.assertIsNone(ip)


class TestGetSwitchHosts(unittest.TestCase):
    """Test switch host filtering."""

    def test_filters_switches(self):
        from freq.modules.switch_orchestration import _get_switch_hosts
        cfg = MockConfig()
        switches = _get_switch_hosts(cfg)
        self.assertEqual(len(switches), 1)
        self.assertEqual(switches[0].label, "switch")


# ---------------------------------------------------------------------------
# CLI Registration Tests
# ---------------------------------------------------------------------------

class TestCLISwitchRegistration(unittest.TestCase):
    """Test that switch subcommands are registered in the CLI parser."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    def test_switch_show(self):
        args = self._parse("net switch show")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_facts(self):
        args = self._parse("net switch facts")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_interfaces(self):
        args = self._parse("net switch interfaces")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_vlans(self):
        args = self._parse("net switch vlans")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_mac(self):
        args = self._parse("net switch mac")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_arp(self):
        args = self._parse("net switch arp")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_neighbors(self):
        args = self._parse("net switch neighbors")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_config(self):
        args = self._parse("net switch config")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_environment(self):
        args = self._parse("net switch environment")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_exec(self):
        args = self._parse("net switch exec")
        self.assertTrue(hasattr(args, "func"))

    def test_switch_show_with_target(self):
        args = self._parse("net switch show 10.25.255.5")
        self.assertEqual(args.target, "10.25.255.5")

    def test_switch_mac_with_vlan_filter(self):
        args = self._parse("net switch mac --vlan 50")
        self.assertEqual(args.vlan, "50")

    def test_switch_config_backup_flag(self):
        args = self._parse("net switch config --backup")
        self.assertTrue(args.backup)

    def test_switch_exec_all_flag(self):
        args = self._parse("net switch exec --all")
        self.assertTrue(getattr(args, "all"))


# ---------------------------------------------------------------------------
# Deployer Interface Tests
# ---------------------------------------------------------------------------

class TestCiscoDeployerInterface(unittest.TestCase):
    """Test that cisco deployer exports all required getter functions."""

    def test_has_all_getters(self):
        from freq.deployers.switch import cisco
        required = [
            "get_facts", "get_interfaces", "get_vlans", "get_mac_table",
            "get_arp_table", "get_neighbors", "get_config", "get_environment",
        ]
        for fn in required:
            self.assertTrue(hasattr(cisco, fn), f"Missing getter: {fn}")
            self.assertTrue(callable(getattr(cisco, fn)), f"Not callable: {fn}")

    def test_has_setters(self):
        from freq.deployers.switch import cisco
        for fn in ("push_config", "save_config"):
            self.assertTrue(hasattr(cisco, fn), f"Missing setter: {fn}")
            self.assertTrue(callable(getattr(cisco, fn)), f"Not callable: {fn}")

    def test_has_deploy_remove(self):
        from freq.deployers.switch import cisco
        self.assertTrue(callable(cisco.deploy))
        self.assertTrue(callable(cisco.remove))

    def test_vendor_constants(self):
        from freq.deployers.switch import cisco
        self.assertEqual(cisco.CATEGORY, "switch")
        self.assertEqual(cisco.VENDOR, "cisco")
        self.assertTrue(cisco.NEEDS_PASSWORD)
        self.assertTrue(cisco.NEEDS_RSA)


# ---------------------------------------------------------------------------
# Module Import Tests
# ---------------------------------------------------------------------------

class TestModuleImports(unittest.TestCase):
    """Test that all new modules import cleanly."""

    def test_cisco_deployer_imports(self):
        from freq.deployers.switch import cisco
        self.assertIsNotNone(cisco)

    def test_switch_orchestration_imports(self):
        from freq.modules import switch_orchestration
        self.assertIsNotNone(switch_orchestration)

    def test_switch_orchestration_all_commands(self):
        from freq.modules.switch_orchestration import (
            cmd_switch_show, cmd_switch_facts, cmd_switch_interfaces,
            cmd_switch_vlans, cmd_switch_mac, cmd_switch_arp,
            cmd_switch_neighbors, cmd_switch_config, cmd_switch_environment,
            cmd_switch_exec,
        )
        # All imports succeed
        self.assertTrue(callable(cmd_switch_show))


if __name__ == "__main__":
    unittest.main()
