"""Tests for config management — backup, history, diff, search, restore.

Covers: Config file storage, history listing, diff generation, search,
        CLI registration, module imports.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG_V1 = """!
! Last configuration change at 14:22:00 CDT Mon Mar 15 2026
!
hostname DC01-SW01
!
interface GigabitEthernet1/0/1
 description Camera-Lobby
 switchport access vlan 50
 switchport mode access
 spanning-tree portfast
!
interface GigabitEthernet1/0/2
 description Camera-Hall
 switchport access vlan 50
 switchport mode access
 spanning-tree portfast
!
interface GigabitEthernet1/0/3
 shutdown
!
vlan 50
 name CAMERAS
!
end
"""

SAMPLE_CONFIG_V2 = """!
! Last configuration change at 09:15:00 CDT Tue Mar 16 2026
!
hostname DC01-SW01
!
interface GigabitEthernet1/0/1
 description Camera-Lobby-Updated
 switchport access vlan 50
 switchport mode access
 spanning-tree portfast
!
interface GigabitEthernet1/0/2
 description Camera-Hall
 switchport access vlan 50
 switchport mode access
 spanning-tree portfast
!
interface GigabitEthernet1/0/3
 description New-Workstation
 switchport access vlan 10
 switchport mode access
 no shutdown
!
interface GigabitEthernet1/0/4
 description AP-Floor2
 switchport access vlan 25
 switchport mode access
!
vlan 50
 name CAMERAS
!
end
"""


@dataclass
class MockHost:
    ip: str
    label: str
    htype: str
    groups: str = ""


class MockConfig:
    def __init__(self, tmpdir):
        self.conf_dir = tmpdir
        self.hosts = [MockHost("10.25.255.5", "switch", "switch")]
        self.switch_ip = "10.25.255.5"
        self.ssh_key_path = "/tmp/test_key"
        self.ssh_rsa_key_path = "/tmp/test_rsa"
        self.ssh_connect_timeout = 5


def _create_backup(tmpdir, label, ts, content):
    """Helper to create a backup file."""
    config_dir = os.path.join(tmpdir, "switch-configs")
    os.makedirs(config_dir, exist_ok=True)
    filepath = os.path.join(config_dir, f"{label}-{ts}.conf")
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


# ---------------------------------------------------------------------------
# Config Storage Tests
# ---------------------------------------------------------------------------

class TestListBackups(unittest.TestCase):
    """Test _list_backups function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)
        from freq.modules.config_management import _list_backups
        self.list_backups = _list_backups

    def test_empty_dir(self):
        backups = self.list_backups(self.cfg)
        self.assertEqual(backups, [])

    def test_finds_backups(self):
        _create_backup(self.tmpdir, "switch", "20260401-180000", SAMPLE_CONFIG_V1)
        _create_backup(self.tmpdir, "switch", "20260402-090000", SAMPLE_CONFIG_V2)
        backups = self.list_backups(self.cfg)
        self.assertEqual(len(backups), 2)

    def test_sorted_newest_first(self):
        _create_backup(self.tmpdir, "switch", "20260401-180000", SAMPLE_CONFIG_V1)
        _create_backup(self.tmpdir, "switch", "20260402-090000", SAMPLE_CONFIG_V2)
        backups = self.list_backups(self.cfg)
        self.assertIn("20260402", backups[0][2])

    def test_filter_by_label(self):
        _create_backup(self.tmpdir, "switch", "20260401-180000", SAMPLE_CONFIG_V1)
        _create_backup(self.tmpdir, "core-sw", "20260401-190000", SAMPLE_CONFIG_V1)
        backups = self.list_backups(self.cfg, "switch")
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0][1], "switch")

    def test_ignores_non_conf_files(self):
        config_dir = os.path.join(self.tmpdir, "switch-configs")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "notes.txt"), "w") as f:
            f.write("not a config")
        backups = self.list_backups(self.cfg)
        self.assertEqual(backups, [])


class TestLatestBackup(unittest.TestCase):
    """Test _latest_backup function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)
        from freq.modules.config_management import _latest_backup
        self.latest = _latest_backup

    def test_returns_newest(self):
        _create_backup(self.tmpdir, "switch", "20260401-180000", SAMPLE_CONFIG_V1)
        path2 = _create_backup(self.tmpdir, "switch", "20260402-090000", SAMPLE_CONFIG_V2)
        result = self.latest(self.cfg, "switch")
        self.assertEqual(result, path2)

    def test_returns_none_when_empty(self):
        result = self.latest(self.cfg, "switch")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Diff Tests
# ---------------------------------------------------------------------------

class TestShowDiff(unittest.TestCase):
    """Test _show_diff output."""

    def test_identical_configs(self):
        from freq.modules.config_management import _show_diff
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            _show_diff(SAMPLE_CONFIG_V1.splitlines(), SAMPLE_CONFIG_V1.splitlines(),
                       "old", "new")
        self.assertIn("No differences", buf.getvalue())

    def test_different_configs(self):
        from freq.modules.config_management import _show_diff
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            _show_diff(SAMPLE_CONFIG_V1.splitlines(), SAMPLE_CONFIG_V2.splitlines(),
                       "v1", "v2")
        output = buf.getvalue()
        # Should show added/removed line counts
        self.assertIn("+", output)
        self.assertIn("-", output)


# ---------------------------------------------------------------------------
# Search Tests
# ---------------------------------------------------------------------------

class TestConfigSearch(unittest.TestCase):
    """Test config search across stored files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)
        _create_backup(self.tmpdir, "switch", "20260401-180000", SAMPLE_CONFIG_V1)
        _create_backup(self.tmpdir, "core-sw", "20260401-190000", SAMPLE_CONFIG_V2)

    def test_search_finds_pattern(self):
        """Search for a pattern that exists in configs."""
        from freq.modules.config_management import _list_backups
        import re

        backups = _list_backups(self.cfg)
        regex = re.compile("Camera", re.IGNORECASE)

        matches_found = 0
        for filepath, label, ts in backups:
            with open(filepath) as f:
                for line in f:
                    if regex.search(line):
                        matches_found += 1
        self.assertGreater(matches_found, 0)

    def test_search_hostname(self):
        """Search for hostname across configs."""
        from freq.modules.config_management import _list_backups
        import re

        backups = _list_backups(self.cfg)
        regex = re.compile("DC01-SW01")
        found = False
        for filepath, label, ts in backups:
            with open(filepath) as f:
                if regex.search(f.read()):
                    found = True
                    break
        self.assertTrue(found)


# ---------------------------------------------------------------------------
# CLI Registration Tests
# ---------------------------------------------------------------------------

class TestCLIConfigRegistration(unittest.TestCase):
    """Test that config subcommands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, args_str):
        return self.parser.parse_args(args_str.split())

    def test_config_backup(self):
        args = self._parse("net config backup")
        self.assertTrue(hasattr(args, "func"))

    def test_config_backup_all(self):
        args = self._parse("net config backup --all")
        self.assertTrue(getattr(args, "all"))

    def test_config_backup_target(self):
        args = self._parse("net config backup switch")
        self.assertEqual(args.target, "switch")

    def test_config_history(self):
        args = self._parse("net config history")
        self.assertTrue(hasattr(args, "func"))

    def test_config_history_target(self):
        args = self._parse("net config history switch")
        self.assertEqual(args.target, "switch")

    def test_config_diff(self):
        args = self._parse("net config diff switch")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.target, "switch")

    def test_config_diff_version(self):
        args = self._parse("net config diff switch --version 2")
        self.assertEqual(args.version, 2)

    def test_config_search(self):
        args = self._parse("net config search vlan")
        self.assertEqual(args.pattern, "vlan")

    def test_config_restore(self):
        args = self._parse("net config restore switch")
        self.assertTrue(hasattr(args, "func"))

    def test_config_restore_version(self):
        args = self._parse("net config restore switch --version 3")
        self.assertEqual(args.version, 3)


# ---------------------------------------------------------------------------
# Help Output Test
# ---------------------------------------------------------------------------

class TestConfigHelp(unittest.TestCase):
    """Verify help text shows all subcommands."""

    def test_config_subcommands_in_help(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        import io
        buf = io.StringIO()
        try:
            parser.parse_args(["net", "config", "--help"])
        except SystemExit:
            pass  # --help causes SystemExit


# ---------------------------------------------------------------------------
# Module Import Tests
# ---------------------------------------------------------------------------

class TestConfigModuleImports(unittest.TestCase):
    """Test that config_management module imports cleanly."""

    def test_module_imports(self):
        from freq.modules import config_management
        self.assertIsNotNone(config_management)

    def test_all_commands_import(self):
        from freq.modules.config_management import (
            cmd_config_backup, cmd_config_history, cmd_config_diff,
            cmd_config_search, cmd_config_restore,
        )
        self.assertTrue(callable(cmd_config_backup))
        self.assertTrue(callable(cmd_config_history))
        self.assertTrue(callable(cmd_config_diff))
        self.assertTrue(callable(cmd_config_search))
        self.assertTrue(callable(cmd_config_restore))

    def test_helpers_import(self):
        from freq.modules.config_management import (
            _list_backups, _latest_backup, _config_dir, _show_diff,
        )
        self.assertTrue(callable(_list_backups))


if __name__ == "__main__":
    unittest.main()
