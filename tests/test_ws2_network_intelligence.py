"""Tests for WS2 — Network Intelligence: SNMP, topology, find-mac/ip, IPAM.

Covers: SNMP helpers, topology graph, DOT export, CLI registration,
        module imports, SNMP value cleaning.
"""
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
            MockHost("10.25.255.26", "pve01", "pve"),
        ]
        self.switch_ip = "10.25.255.5"
        self.ssh_key_path = "/tmp/test"
        self.ssh_rsa_key_path = "/tmp/test_rsa"
        self.ssh_connect_timeout = 5


# ---------------------------------------------------------------------------
# SNMP Helper Tests
# ---------------------------------------------------------------------------

class TestSNMPCleanValue(unittest.TestCase):
    """Test _clean_snmp_value."""

    def setUp(self):
        from freq.modules.snmp import _clean_snmp_value
        self.clean = _clean_snmp_value

    def test_strip_string_prefix(self):
        self.assertEqual(self.clean('STRING: "DC01-SW01"'), "DC01-SW01")

    def test_strip_integer_prefix(self):
        self.assertEqual(self.clean("INTEGER: 42"), "42")

    def test_strip_gauge32(self):
        self.assertEqual(self.clean("Gauge32: 85"), "85")

    def test_strip_counter32(self):
        self.assertEqual(self.clean("Counter32: 123456"), "123456")

    def test_strip_timeticks(self):
        result = self.clean("Timeticks: (1234567) 1 day, 2:34:56.78")
        self.assertIn("1234567", result)

    def test_no_such_object(self):
        self.assertIsNone(self.clean("No Such Object available on this agent"))

    def test_no_such_instance(self):
        self.assertIsNone(self.clean("No Such Instance currently exists"))

    def test_none_input(self):
        self.assertIsNone(self.clean(None))

    def test_empty(self):
        self.assertIsNone(self.clean(""))

    def test_plain_value(self):
        self.assertEqual(self.clean("GigabitEthernet0/1"), "GigabitEthernet0/1")


class TestSNMPFormatBytes(unittest.TestCase):
    """Test _format_bytes."""

    def setUp(self):
        from freq.modules.snmp import _format_bytes
        self.fmt = _format_bytes

    def test_bytes(self):
        self.assertEqual(self.fmt(500), "500 B")

    def test_kilobytes(self):
        self.assertIn("KB", self.fmt(5_000))

    def test_megabytes(self):
        self.assertIn("MB", self.fmt(5_000_000))

    def test_gigabytes(self):
        self.assertIn("GB", self.fmt(5_000_000_000))


class TestSNMPFormatSpeed(unittest.TestCase):
    """Test _format_speed."""

    def setUp(self):
        from freq.modules.snmp import _format_speed
        self.fmt = _format_speed

    def test_gigabit(self):
        self.assertEqual(self.fmt(1_000_000_000), "1G")

    def test_100meg(self):
        self.assertEqual(self.fmt(100_000_000), "100M")

    def test_10meg(self):
        self.assertEqual(self.fmt(10_000_000), "10M")


class TestSNMPResolveIP(unittest.TestCase):
    """Test _resolve_ip."""

    def setUp(self):
        from freq.modules.snmp import _resolve_ip
        self.resolve = _resolve_ip

    def test_ip_passthrough(self):
        cfg = MockConfig()
        self.assertEqual(self.resolve("10.25.255.5", cfg), "10.25.255.5")

    def test_label_resolution(self):
        cfg = MockConfig()
        self.assertEqual(self.resolve("switch", cfg), "10.25.255.5")

    def test_unknown_label(self):
        cfg = MockConfig()
        self.assertEqual(self.resolve("unknown", cfg), "unknown")


# ---------------------------------------------------------------------------
# Topology Tests
# ---------------------------------------------------------------------------

class TestTopologyStorage(unittest.TestCase):
    """Test topology snapshot storage."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)

    def test_save_and_load(self):
        from freq.modules.topology import _save_topology, _load_latest
        topo = {
            "nodes": [{"name": "sw1", "ip": "10.0.0.1", "type": "switch"}],
            "edges": [{"from_device": "sw1", "from_port": "Gi0/1",
                        "to_device": "sw2", "to_port": "Gi0/1"}],
            "discovered_at": "2026-04-01T12:00:00",
        }
        _save_topology(self.cfg, topo)
        loaded = _load_latest(self.cfg)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded["nodes"]), 1)
        self.assertEqual(len(loaded["edges"]), 1)

    def test_load_empty(self):
        from freq.modules.topology import _load_latest
        result = _load_latest(self.cfg)
        self.assertIsNone(result)

    def test_snapshots_list(self):
        from freq.modules.topology import _save_topology, _list_snapshots
        _save_topology(self.cfg, {"nodes": [], "edges": []})
        snaps = _list_snapshots(self.cfg)
        self.assertEqual(len(snaps), 1)


class TestTopologyEdgeKey(unittest.TestCase):
    """Test edge key generation."""

    def test_edge_key(self):
        from freq.modules.topology import _edge_key
        key = _edge_key("sw1", "Gi0/1", "sw2", "Gi0/2")
        self.assertEqual(key, "sw1:Gi0/1->sw2:Gi0/2")


class TestTopologyDOTExport(unittest.TestCase):
    """Test DOT graph export."""

    def test_dot_format(self):
        from freq.modules.topology import _to_dot
        topo = {
            "nodes": [
                {"name": "sw1", "ip": "10.0.0.1", "model": "C9300", "type": "switch"},
                {"name": "sw2", "ip": "10.0.0.2", "model": "C3750", "type": "discovered"},
            ],
            "edges": [
                {"from_device": "sw1", "from_port": "Gi0/1",
                 "to_device": "sw2", "to_port": "Gi0/1"},
            ],
        }
        dot = _to_dot(topo)
        self.assertIn("graph network", dot)
        self.assertIn('"sw1"', dot)
        self.assertIn('"sw2"', dot)
        self.assertIn("--", dot)
        self.assertIn("Gi0/1", dot)


# ---------------------------------------------------------------------------
# CLI Registration Tests
# ---------------------------------------------------------------------------

class TestCLIWS2Registration(unittest.TestCase):
    """Test that all WS2 subcommands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    # SNMP
    def test_snmp_poll(self):
        args = self._parse("net snmp poll switch")
        self.assertTrue(hasattr(args, "func"))

    def test_snmp_poll_all(self):
        args = self._parse("net snmp poll --all")
        self.assertTrue(getattr(args, "all"))

    def test_snmp_poll_community(self):
        args = self._parse("net snmp poll switch --community private")
        self.assertEqual(args.community, "private")

    def test_snmp_interfaces(self):
        args = self._parse("net snmp interfaces switch")
        self.assertTrue(hasattr(args, "func"))

    def test_snmp_errors(self):
        args = self._parse("net snmp errors switch")
        self.assertTrue(hasattr(args, "func"))

    def test_snmp_cpu(self):
        args = self._parse("net snmp cpu switch")
        self.assertTrue(hasattr(args, "func"))

    # Topology
    def test_topology_discover(self):
        args = self._parse("net topology discover")
        self.assertTrue(hasattr(args, "func"))

    def test_topology_show(self):
        args = self._parse("net topology show")
        self.assertTrue(hasattr(args, "func"))

    def test_topology_export(self):
        args = self._parse("net topology export --format dot")
        self.assertEqual(getattr(args, "format"), "dot")

    def test_topology_export_json(self):
        args = self._parse("net topology export --format json")
        self.assertEqual(getattr(args, "format"), "json")

    def test_topology_diff(self):
        args = self._parse("net topology diff")
        self.assertTrue(hasattr(args, "func"))

    # Find
    def test_find_mac(self):
        args = self._parse("net find-mac aabb.ccdd.eeff")
        self.assertEqual(args.mac, "aabb.ccdd.eeff")

    def test_find_ip(self):
        args = self._parse("net find-ip 10.25.255.5")
        self.assertEqual(args.ip, "10.25.255.5")

    def test_troubleshoot(self):
        args = self._parse("net troubleshoot 10.25.255.5")
        self.assertEqual(args.target, "10.25.255.5")

    # IPAM extensions
    def test_ip_util(self):
        args = self._parse("net ip-util")
        self.assertTrue(hasattr(args, "func"))

    def test_ip_conflict(self):
        args = self._parse("net ip-conflict")
        self.assertTrue(hasattr(args, "func"))


# ---------------------------------------------------------------------------
# Module Import Tests
# ---------------------------------------------------------------------------

class TestWS2ModuleImports(unittest.TestCase):
    """Test that all WS2 modules import cleanly."""

    def test_snmp_imports(self):
        from freq.modules.snmp import (
            cmd_snmp_poll, cmd_snmp_interfaces, cmd_snmp_errors, cmd_snmp_cpu,
            get_system_info, get_interfaces, get_cpu_load,
        )
        self.assertTrue(callable(cmd_snmp_poll))

    def test_topology_imports(self):
        from freq.modules.topology import (
            cmd_topology_discover, cmd_topology_show,
            cmd_topology_export, cmd_topology_diff,
            discover_topology, _to_dot,
        )
        self.assertTrue(callable(cmd_topology_discover))

    def test_net_intelligence_imports(self):
        from freq.modules.net_intelligence import (
            cmd_find_mac, cmd_find_ip, cmd_troubleshoot,
            cmd_ip_utilization, cmd_ip_conflict,
        )
        self.assertTrue(callable(cmd_find_mac))


# ---------------------------------------------------------------------------
# SNMP OID Constants Test
# ---------------------------------------------------------------------------

class TestSNMPOIDs(unittest.TestCase):
    """Verify OID constants are valid format."""

    def test_oids_are_dotted(self):
        from freq.modules import snmp
        oids = [
            snmp.OID_SYS_DESCR, snmp.OID_SYS_UPTIME, snmp.OID_SYS_NAME,
            snmp.OID_IF_DESCR, snmp.OID_IF_IN_OCTETS, snmp.OID_IF_OUT_OCTETS,
            snmp.OID_IF_IN_ERRORS, snmp.OID_IF_OUT_ERRORS, snmp.OID_HR_PROC_LOAD,
        ]
        import re
        for oid in oids:
            self.assertTrue(re.match(r"^[\d.]+$", oid), f"Invalid OID: {oid}")


if __name__ == "__main__":
    unittest.main()
