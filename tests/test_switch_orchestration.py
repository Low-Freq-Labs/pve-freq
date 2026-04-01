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
            "get_port_status", "get_poe_status",
        ]
        for fn in required:
            self.assertTrue(hasattr(cisco, fn), f"Missing getter: {fn}")
            self.assertTrue(callable(getattr(cisco, fn)), f"Not callable: {fn}")

    def test_has_setters(self):
        from freq.deployers.switch import cisco
        for fn in ("push_config", "save_config", "set_port_vlan",
                    "set_port_shutdown", "set_port_description", "set_port_poe",
                    "flap_port", "apply_profile_lines"):
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

    def test_port_commands_import(self):
        from freq.modules.switch_orchestration import (
            cmd_port_status, cmd_port_configure, cmd_port_desc,
            cmd_port_poe, cmd_port_find, cmd_port_flap,
        )
        self.assertTrue(callable(cmd_port_status))

    def test_profile_commands_import(self):
        from freq.modules.switch_orchestration import (
            cmd_profile_list, cmd_profile_show, cmd_profile_apply,
            cmd_profile_create, cmd_profile_delete,
        )
        self.assertTrue(callable(cmd_profile_list))


# ---------------------------------------------------------------------------
# PoE Parser Tests
# ---------------------------------------------------------------------------

SHOW_POWER_INLINE = """
Module   Available     Used     Remaining
          (Watts)     (Watts)    (Watts)
------   ---------   --------   ---------
1          740.0       62.0       678.0

Interface Admin  Oper       Power   Device              Class Max
                            (Watts)
--------- ------ ---------- ------- ------------------- ----- ----
Gi1/0/1   auto   on         7.0     Ieee PD             3     30.0
Gi1/0/2   auto   on         4.5     Ieee PD             2     30.0
Gi1/0/3   auto   off        0.0     n/a                 n/a   30.0
Gi1/0/4   auto   on         15.4    Ieee PD             4     30.0
Gi1/0/5   auto   off        0.0     n/a                 n/a   30.0
Gi1/0/6   auto   on         7.0     IP Phone            3     30.0
"""


class TestCiscoParsePowerInline(unittest.TestCase):
    """Test _parse_power_inline parser."""

    def setUp(self):
        from freq.deployers.switch.cisco import _parse_power_inline
        self.parse = _parse_power_inline

    def test_count(self):
        entries = self.parse(SHOW_POWER_INLINE)
        self.assertEqual(len(entries), 6)

    def test_powered_port(self):
        entries = self.parse(SHOW_POWER_INLINE)
        gi1 = next(e for e in entries if e["port"] == "Gi1/0/1")
        self.assertEqual(gi1["admin"], "auto")
        self.assertEqual(gi1["oper"], "on")
        self.assertEqual(gi1["watts"], 7.0)

    def test_unpowered_port(self):
        entries = self.parse(SHOW_POWER_INLINE)
        gi3 = next(e for e in entries if e["port"] == "Gi1/0/3")
        self.assertEqual(gi3["oper"], "off")
        self.assertEqual(gi3["watts"], 0.0)

    def test_empty_input(self):
        self.assertEqual(self.parse(""), [])


# ---------------------------------------------------------------------------
# Profile to Config Lines Tests
# ---------------------------------------------------------------------------

class TestProfileToConfigLines(unittest.TestCase):
    """Test profile_to_config_lines conversion."""

    def setUp(self):
        from freq.deployers.switch.cisco import profile_to_config_lines
        self.convert = profile_to_config_lines

    def test_access_profile(self):
        profile = {"mode": "access", "vlan": 50, "spanning_tree": "portfast"}
        lines = self.convert(profile)
        self.assertIn("switchport mode access", lines)
        self.assertIn("switchport access vlan 50", lines)
        self.assertIn("spanning-tree portfast", lines)
        self.assertIn("no shutdown", lines)

    def test_trunk_profile(self):
        profile = {"mode": "trunk", "allowed_vlans": [1, 10, 25], "native_vlan": 1}
        lines = self.convert(profile)
        self.assertIn("switchport mode trunk", lines)
        self.assertIn("switchport trunk allowed vlan 1,10,25", lines)
        self.assertIn("switchport trunk native vlan 1", lines)

    def test_shutdown_profile(self):
        profile = {"description": "Unused port", "shutdown": True}
        lines = self.convert(profile)
        self.assertIn("shutdown", lines)
        self.assertIn("description Unused port", lines)
        self.assertNotIn("no shutdown", lines)
        # Shutdown profile should be short — no mode/vlan config
        self.assertNotIn("switchport mode access", lines)

    def test_poe_enabled(self):
        profile = {"mode": "access", "vlan": 50, "poe": True}
        lines = self.convert(profile)
        self.assertIn("power inline auto", lines)

    def test_poe_disabled(self):
        profile = {"mode": "access", "vlan": 50, "poe": False}
        lines = self.convert(profile)
        self.assertIn("power inline never", lines)

    def test_port_security(self):
        profile = {
            "mode": "access", "vlan": 50,
            "port_security": {"max_mac": 1, "violation": "restrict"},
        }
        lines = self.convert(profile)
        self.assertIn("switchport port-security", lines)
        self.assertIn("switchport port-security maximum 1", lines)
        self.assertIn("switchport port-security violation restrict", lines)

    def test_description_included(self):
        profile = {"description": "Camera-Lobby", "mode": "access", "vlan": 50}
        lines = self.convert(profile)
        self.assertIn("description Camera-Lobby", lines)

    def test_empty_profile(self):
        lines = self.convert({})
        # Should at least have no shutdown and mode
        self.assertIn("no shutdown", lines)
        self.assertIn("switchport mode access", lines)


# ---------------------------------------------------------------------------
# Port Range Expansion Tests
# ---------------------------------------------------------------------------

class TestExpandPortRange(unittest.TestCase):
    """Test _expand_port_range utility."""

    def setUp(self):
        from freq.modules.switch_orchestration import _expand_port_range
        self.expand = _expand_port_range

    def test_single_port(self):
        self.assertEqual(self.expand("Gi1/0/5"), ["Gi1/0/5"])

    def test_range(self):
        ports = self.expand("Gi1/0/1-4")
        self.assertEqual(len(ports), 4)
        self.assertEqual(ports[0], "Gi1/0/1")
        self.assertEqual(ports[3], "Gi1/0/4")

    def test_comma_separated(self):
        ports = self.expand("Gi1/0/1,Gi1/0/5")
        self.assertEqual(len(ports), 2)

    def test_mixed(self):
        ports = self.expand("Gi1/0/1-3,Gi1/0/10")
        self.assertEqual(len(ports), 4)
        self.assertEqual(ports[3], "Gi1/0/10")

    def test_full_range_24(self):
        ports = self.expand("Gi1/0/1-24")
        self.assertEqual(len(ports), 24)


# ---------------------------------------------------------------------------
# CLI Port + Profile Registration Tests
# ---------------------------------------------------------------------------

class TestCLIPortRegistration(unittest.TestCase):
    """Test that port subcommands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    def test_port_status(self):
        args = self._parse("net port status")
        self.assertTrue(hasattr(args, "func"))

    def test_port_configure(self):
        args = self._parse("net port configure switch Gi1/0/5 --vlan 50")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.port, "Gi1/0/5")
        self.assertEqual(args.vlan, "50")

    def test_port_desc(self):
        args = self._parse('net port desc switch Gi1/0/5 --description Camera')
        self.assertEqual(args.description, "Camera")

    def test_port_poe(self):
        args = self._parse("net port poe")
        self.assertTrue(hasattr(args, "func"))

    def test_port_poe_toggle(self):
        args = self._parse("net port poe switch --port Gi1/0/1 --on")
        self.assertTrue(args.on)

    def test_port_find(self):
        args = self._parse("net port find --mac aabb.ccdd.eeff")
        self.assertEqual(args.mac, "aabb.ccdd.eeff")

    def test_port_flap(self):
        args = self._parse("net port flap --port Gi1/0/5")
        self.assertEqual(args.port, "Gi1/0/5")


class TestCLIProfileRegistration(unittest.TestCase):
    """Test that profile subcommands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    def test_profile_list(self):
        args = self._parse("net switch profile list")
        self.assertTrue(hasattr(args, "func"))

    def test_profile_show(self):
        args = self._parse("net switch profile show camera")
        self.assertEqual(args.name, "camera")

    def test_profile_create(self):
        args = self._parse("net switch profile create test --mode access --vlan 50")
        self.assertEqual(args.name, "test")
        self.assertEqual(args.mode, "access")
        self.assertEqual(args.vlan, "50")

    def test_profile_apply(self):
        args = self._parse("net switch profile apply camera switch --ports Gi1/0/1-24")
        self.assertEqual(args.name, "camera")
        self.assertEqual(args.target, "switch")
        self.assertEqual(args.ports, "Gi1/0/1-24")

    def test_profile_delete(self):
        args = self._parse("net switch profile delete test")
        self.assertEqual(args.name, "test")


# ---------------------------------------------------------------------------
# Profile Load Tests
# ---------------------------------------------------------------------------

class TestProfileLoading(unittest.TestCase):
    """Test profile TOML loading from disk."""

    def test_load_profiles_from_conf(self):
        """Load the bundled switch-profiles.toml."""
        import os
        import sys

        # Point cfg.conf_dir at our real conf directory
        cfg = MockConfig()
        cfg.conf_dir = os.path.join(os.path.dirname(__file__), "..", "conf")

        from freq.modules.switch_orchestration import _load_profiles
        profiles = _load_profiles(cfg)
        self.assertIn("camera", profiles)
        self.assertIn("dead", profiles)
        self.assertIn("trunk-uplink", profiles)
        self.assertIn("access-default", profiles)

    def test_camera_profile_structure(self):
        import os
        cfg = MockConfig()
        cfg.conf_dir = os.path.join(os.path.dirname(__file__), "..", "conf")

        from freq.modules.switch_orchestration import _load_profiles
        profiles = _load_profiles(cfg)
        cam = profiles["camera"]
        self.assertEqual(cam["mode"], "access")
        self.assertEqual(cam["vlan"], 50)
        self.assertTrue(cam["poe"])

    def test_load_empty_dir(self):
        """Missing profiles file returns empty dict."""
        import tempfile
        cfg = MockConfig()
        cfg.conf_dir = tempfile.mkdtemp()
        from freq.modules.switch_orchestration import _load_profiles
        profiles = _load_profiles(cfg)
        self.assertEqual(profiles, {})


if __name__ == "__main__":
    unittest.main()
