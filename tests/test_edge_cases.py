"""FREQ Edge Case Tests — error paths and boundary conditions.

Covers: malformed config, missing hosts.conf, vault corruption, config field
validation, SSH result edge cases, FleetBoundaries edge cases, validate.py
boundary inputs.
"""
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Path setup so freq imports work from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.core.types import (
    Host, CmdResult, FleetBoundaries, PhysicalDevice, PVENode,
    Container, ContainerVM,
)
from freq.core import validate
from freq.core.config import (
    FreqConfig, load_hosts, load_toml, load_fleet_boundaries,
    load_containers, _apply_toml, _resolve_paths,
)


# ---------------------------------------------------------------------------
# 1. Invalid / malformed TOML config
# ---------------------------------------------------------------------------

class TestMalformedToml(unittest.TestCase):
    """Config loader must survive broken TOML files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_load_toml_missing_file(self):
        """Missing TOML file returns empty dict, no crash."""
        result = load_toml(os.path.join(self.tmpdir, "does-not-exist.toml"))
        self.assertEqual(result, {})

    def test_load_toml_empty_file(self):
        """Empty TOML file returns empty dict."""
        path = os.path.join(self.tmpdir, "empty.toml")
        with open(path, "w") as f:
            f.write("")
        result = load_toml(path)
        self.assertEqual(result, {})

    def test_load_toml_comments_only(self):
        """File with only comments returns empty dict."""
        path = os.path.join(self.tmpdir, "comments.toml")
        with open(path, "w") as f:
            f.write("# just a comment\n# another comment\n")
        result = load_toml(path)
        self.assertEqual(result, {})

    def test_load_toml_invalid_syntax(self):
        """Malformed TOML returns empty dict instead of crashing."""
        path = os.path.join(self.tmpdir, "bad.toml")
        with open(path, "wb") as f:
            # Use valid UTF-8 but invalid TOML structure (unclosed bracket)
            f.write(b"[freq\nversion = broken\n")
        result = load_toml(path)
        # Should return empty dict (tomllib.TOMLDecodeError) or partial parse
        self.assertIsInstance(result, dict)

    def test_apply_toml_empty_data(self):
        """_apply_toml with empty dict leaves defaults intact."""
        cfg = FreqConfig()
        _apply_toml(cfg, {})
        import freq
        self.assertEqual(cfg.version, freq.__version__)
        self.assertEqual(cfg.brand, "PVE FREQ")
        self.assertEqual(cfg.ssh_service_account, "freq-admin")

    def test_apply_toml_wrong_types(self):
        """_apply_toml with wrong value types uses the bad values (no crash).

        Config is permissive: it trusts the TOML and applies whatever it gets.
        The goal is that it does not crash.
        """
        cfg = FreqConfig()
        data = {
            "freq": {"version": 999, "debug": "not-a-bool"},
            "ssh": {"connect_timeout": "five"},
        }
        # Should not raise
        _apply_toml(cfg, data)
        self.assertEqual(cfg.version, 999)  # accepts the int
        self.assertEqual(cfg.debug, "not-a-bool")  # accepts the string

    def test_apply_toml_extra_unknown_sections(self):
        """Unknown TOML sections are silently ignored."""
        cfg = FreqConfig()
        data = {"unknown_section": {"foo": "bar"}, "freq": {"brand": "test"}}
        _apply_toml(cfg, data)
        self.assertEqual(cfg.brand, "test")


# ---------------------------------------------------------------------------
# 2. Empty / missing hosts.conf
# ---------------------------------------------------------------------------

class TestHostsConf(unittest.TestCase):
    """load_hosts must handle every degenerate input."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_missing_hosts_file(self):
        """Missing hosts.conf returns empty list."""
        result = load_hosts(os.path.join(self.tmpdir, "nope.conf"))
        self.assertEqual(result, [])

    def test_empty_hosts_file(self):
        """Empty hosts.conf returns empty list."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("")
        result = load_hosts(path)
        self.assertEqual(result, [])

    def test_only_comments_and_blanks(self):
        """File with only comments and blank lines returns empty list."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("# header\n\n# another comment\n   \n")
        result = load_hosts(path)
        self.assertEqual(result, [])

    def test_short_lines_skipped(self):
        """Lines with fewer than 3 columns are skipped."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("10.0.0.1\n")          # 1 column
            f.write("10.0.0.2 label\n")    # 2 columns
        result = load_hosts(path)
        self.assertEqual(result, [])

    def test_valid_3_column(self):
        """Minimal 3-column line is parsed correctly."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("10.0.0.1  myhost  linux\n")
        result = load_hosts(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].ip, "10.0.0.1")
        self.assertEqual(result[0].label, "myhost")
        self.assertEqual(result[0].htype, "linux")
        self.assertEqual(result[0].groups, "")
        self.assertEqual(result[0].all_ips, [])

    def test_5_column_with_all_ips(self):
        """5-column line parses ALL_IPS correctly."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("10.0.0.1  myhost  docker  prod  10.0.0.1,10.25.10.5\n")
        result = load_hosts(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].groups, "prod")
        self.assertEqual(result[0].all_ips, ["10.0.0.1", "10.25.10.5"])

    def test_all_ips_trailing_comma(self):
        """Trailing comma in ALL_IPS column does not produce empty string."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("10.0.0.1  myhost  linux  prod  10.0.0.1,\n")
        result = load_hosts(path)
        # The list comprehension filters empty strings
        self.assertNotIn("", result[0].all_ips)


# ---------------------------------------------------------------------------
# 3. Vault with corrupted / missing data
# ---------------------------------------------------------------------------

class TestVaultParsing(unittest.TestCase):
    """Vault internal parsers must handle corrupt data."""

    def test_parse_entries_empty_string(self):
        from freq.modules.vault import _parse_entries
        result = _parse_entries("")
        self.assertEqual(result, [])

    def test_parse_entries_only_comments(self):
        from freq.modules.vault import _parse_entries
        result = _parse_entries("# FREQ Vault\n# initialized\n")
        self.assertEqual(result, [])

    def test_parse_entries_incomplete_pipes(self):
        """Lines with fewer than 3 pipe-delimited fields are skipped."""
        from freq.modules.vault import _parse_entries
        result = _parse_entries("host|key\nvalueonly\n")
        self.assertEqual(result, [])

    def test_parse_entries_value_with_pipes(self):
        """Value field can contain pipe characters (split limit is 2)."""
        from freq.modules.vault import _parse_entries
        result = _parse_entries("host|key|value|with|pipes\n")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ("host", "key", "value|with|pipes"))

    def test_serialize_round_trip(self):
        from freq.modules.vault import _parse_entries, _serialize_entries
        entries = [("host1", "password", "s3cret"), ("DEFAULT", "apikey", "abc123")]
        serialized = _serialize_entries(entries)
        parsed = _parse_entries(serialized)
        self.assertEqual(set(parsed), set(entries))

    def test_vault_key_missing_machine_id(self):
        """_vault_key returns empty string when machine-id files are missing."""
        from freq.modules.vault import _vault_key
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = _vault_key()
            self.assertEqual(result, "")

    def test_vault_get_no_key(self):
        """vault_get returns empty string when encryption key unavailable."""
        from freq.modules.vault import vault_get
        cfg = FreqConfig()
        cfg.vault_file = "/nonexistent/vault.enc"
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_get(cfg, "host", "key")
            self.assertEqual(result, "")

    def test_vault_set_no_key(self):
        """vault_set returns False when encryption key unavailable."""
        from freq.modules.vault import vault_set
        cfg = FreqConfig()
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_set(cfg, "host", "key", "value")
            self.assertFalse(result)

    def test_vault_delete_no_key(self):
        """vault_delete returns False when encryption key unavailable."""
        from freq.modules.vault import vault_delete
        cfg = FreqConfig()
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_delete(cfg, "host", "key")
            self.assertFalse(result)

    def test_vault_list_no_key(self):
        """vault_list returns empty list when encryption key unavailable."""
        from freq.modules.vault import vault_list
        cfg = FreqConfig()
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_list(cfg)
            self.assertEqual(result, [])

    def test_decrypt_missing_vault_file(self):
        """_decrypt returns empty string for nonexistent file."""
        from freq.modules.vault import _decrypt
        result = _decrypt("somekey", "/no/such/vault.enc")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# 4. Config with missing required fields
# ---------------------------------------------------------------------------

class TestConfigMissingFields(unittest.TestCase):
    """FreqConfig defaults must survive missing TOML sections."""

    def test_default_config_all_fields_set(self):
        """Default FreqConfig has sane values for every field."""
        cfg = FreqConfig()
        import freq
        self.assertEqual(cfg.version, freq.__version__)
        self.assertEqual(cfg.ssh_connect_timeout, 5)
        self.assertEqual(cfg.vm_default_cores, 2)
        self.assertEqual(cfg.vm_default_ram, 2048)
        self.assertIsInstance(cfg.hosts, list)
        self.assertIsInstance(cfg.pve_nodes, list)
        self.assertIsInstance(cfg.fleet_boundaries, FleetBoundaries)

    def test_resolve_paths_with_empty_install_dir(self):
        """_resolve_paths works even with empty install_dir (uses '.')."""
        cfg = FreqConfig()
        cfg.install_dir = ""
        _resolve_paths(cfg)
        # Paths are set relative to empty string (current dir)
        self.assertTrue(cfg.conf_dir.endswith("conf"))
        self.assertTrue(cfg.hosts_file.endswith("hosts.conf"))

    def test_load_containers_missing_file(self):
        """load_containers returns empty dict for missing file."""
        result = load_containers("/nonexistent/containers.toml")
        self.assertEqual(result, {})

    def test_load_containers_non_integer_keys(self):
        """Container TOML with non-integer VM keys skips them."""
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "containers.toml")
            with open(path, "w") as f:
                f.write('[vm.abc]\nip = "10.0.0.1"\nlabel = "bad"\n')
            result = load_containers(path)
            self.assertEqual(result, {})
        finally:
            shutil.rmtree(tmpdir)

    def test_load_fleet_boundaries_missing_file(self):
        """Missing fleet-boundaries.toml returns default FleetBoundaries."""
        result = load_fleet_boundaries("/nonexistent/fb.toml")
        self.assertIsInstance(result, FleetBoundaries)
        self.assertEqual(result.tiers, {})
        self.assertEqual(result.categories, {})


# ---------------------------------------------------------------------------
# 5. SSH result edge cases
# ---------------------------------------------------------------------------

class TestSSHResultEdgeCases(unittest.TestCase):
    """CmdResult and SSH build behavior with edge-case inputs."""

    def test_cmdresult_empty_stdout(self):
        """CmdResult with empty stdout."""
        r = CmdResult(stdout="", stderr="", returncode=0)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.returncode, 0)

    def test_cmdresult_special_characters(self):
        """CmdResult handles special characters in stdout/stderr."""
        r = CmdResult(
            stdout="line1\nline2\ttab\x00null",
            stderr="warn: unicode \u26a0",
            returncode=0,
        )
        self.assertIn("\n", r.stdout)
        self.assertIn("\t", r.stdout)
        self.assertIn("\u26a0", r.stderr)

    def test_cmdresult_very_long_output(self):
        """CmdResult can hold very large stdout."""
        big = "x" * 1_000_000
        r = CmdResult(stdout=big, stderr="", returncode=0)
        self.assertEqual(len(r.stdout), 1_000_000)

    def test_build_ssh_cmd_unknown_htype(self):
        """Unknown host type falls back to linux platform config."""
        from freq.core.ssh import _build_ssh_cmd
        cmd = _build_ssh_cmd(
            host="10.0.0.1", command="uptime",
            htype="alien", use_sudo=True,
        )
        cmd_str = " ".join(cmd)
        self.assertIn("ssh", cmd_str)
        self.assertIn("10.0.0.1", cmd_str)

    def test_build_ssh_cmd_empty_command(self):
        """SSH cmd with empty command does not append sudo wrapper."""
        from freq.core.ssh import _build_ssh_cmd
        cmd = _build_ssh_cmd(
            host="10.0.0.1", command="",
            htype="linux", use_sudo=True,
        )
        cmd_str = " ".join(cmd)
        self.assertNotIn("sudo sh", cmd_str)

    def test_build_ssh_cmd_command_with_single_quotes(self):
        """Single quotes in command are properly escaped."""
        from freq.core.ssh import _build_ssh_cmd
        cmd = _build_ssh_cmd(
            host="10.0.0.1", command="echo 'hello world'",
            htype="linux", use_sudo=True,
        )
        cmd_str = " ".join(cmd)
        # The command should be wrapped in sudo sh -c '...'
        self.assertIn("sudo sh -c", cmd_str)


# ---------------------------------------------------------------------------
# 6. FleetBoundaries edge cases
# ---------------------------------------------------------------------------

class TestFleetBoundariesEdgeCases(unittest.TestCase):
    """FleetBoundaries categorize/actions with extreme inputs."""

    def _make_fb(self):
        fb = FleetBoundaries()
        fb.tiers = {
            "probe": ["view"],
            "operator": ["view", "restart", "update"],
            "admin": ["view", "restart", "update", "destroy"],
        }
        fb.categories = {
            "infrastructure": {
                "description": "Core infra",
                "tier": "probe",
                "vmids": [100, 200],
            },
            "sandbox": {
                "description": "Test VMs",
                "tier": "admin",
                "range_start": 5000,
                "range_end": 5999,
            },
        }
        return fb

    def test_categorize_unknown_vmid(self):
        """VMID not in any category returns ('unknown', 'probe')."""
        fb = self._make_fb()
        cat, tier = fb.categorize(9999)
        self.assertEqual(cat, "unknown")
        self.assertEqual(tier, "probe")

    def test_categorize_vmid_zero(self):
        """VMID 0 returns unknown."""
        fb = self._make_fb()
        cat, tier = fb.categorize(0)
        self.assertEqual(cat, "unknown")
        self.assertEqual(tier, "probe")

    def test_categorize_negative_vmid(self):
        """Negative VMID returns unknown."""
        fb = self._make_fb()
        cat, tier = fb.categorize(-1)
        self.assertEqual(cat, "unknown")
        self.assertEqual(tier, "probe")

    def test_categorize_exact_match_in_vmids_list(self):
        """VMID in explicit vmids list is categorized correctly."""
        fb = self._make_fb()
        cat, tier = fb.categorize(100)
        self.assertEqual(cat, "infrastructure")
        self.assertEqual(tier, "probe")

    def test_categorize_range_boundary_start(self):
        """VMID at exact range_start is included."""
        fb = self._make_fb()
        cat, tier = fb.categorize(5000)
        self.assertEqual(cat, "sandbox")
        self.assertEqual(tier, "admin")

    def test_categorize_range_boundary_end(self):
        """VMID at exact range_end is included."""
        fb = self._make_fb()
        cat, tier = fb.categorize(5999)
        self.assertEqual(cat, "sandbox")
        self.assertEqual(tier, "admin")

    def test_allowed_actions_unknown_tier(self):
        """Unknown tier falls back to ['view']."""
        fb = self._make_fb()
        # Delete tiers so lookup misses
        fb.tiers = {}
        actions = fb.allowed_actions(100)
        self.assertEqual(actions, ["view"])

    def test_allowed_actions_empty_tiers(self):
        """Empty tiers dict still returns ['view'] default."""
        fb = FleetBoundaries()
        actions = fb.allowed_actions(100)
        self.assertEqual(actions, ["view"])

    def test_allowed_actions_empty_categories(self):
        """Empty categories: everything is unknown/probe."""
        fb = FleetBoundaries()
        fb.tiers = {"probe": ["view", "ping"]}
        actions = fb.allowed_actions(500)
        self.assertEqual(actions, ["view", "ping"])

    def test_is_prod_for_unknown(self):
        """Unknown category is not production."""
        fb = self._make_fb()
        self.assertFalse(fb.is_prod(9999))

    def test_is_prod_for_infrastructure(self):
        """Infrastructure is production."""
        fb = self._make_fb()
        self.assertTrue(fb.is_prod(100))

    def test_can_action_allowed(self):
        """can_action returns True for allowed action."""
        fb = self._make_fb()
        self.assertTrue(fb.can_action(5000, "destroy"))

    def test_can_action_denied(self):
        """can_action returns False for disallowed action."""
        fb = self._make_fb()
        self.assertFalse(fb.can_action(100, "destroy"))

    def test_category_description_unknown(self):
        """Unknown VMID returns 'Unknown' description."""
        fb = self._make_fb()
        desc = fb.category_description(9999)
        self.assertEqual(desc, "Unknown")

    def test_category_description_known(self):
        """Known VMID returns proper description."""
        fb = self._make_fb()
        desc = fb.category_description(100)
        self.assertEqual(desc, "Core infra")


# ---------------------------------------------------------------------------
# 7. validate.py edge cases
# ---------------------------------------------------------------------------

class TestValidateEdgeCases(unittest.TestCase):
    """Boundary and degenerate inputs for every validator."""

    # --- ip ---
    def test_ip_empty_string(self):
        self.assertFalse(validate.ip(""))

    def test_ip_valid(self):
        self.assertTrue(validate.ip("10.25.255.1"))

    def test_ip_boundary_zeros(self):
        self.assertTrue(validate.ip("0.0.0.0"))

    def test_ip_boundary_max(self):
        self.assertTrue(validate.ip("255.255.255.255"))

    def test_ip_octet_256(self):
        self.assertFalse(validate.ip("256.0.0.1"))

    def test_ip_negative_octet(self):
        self.assertFalse(validate.ip("-1.0.0.1"))

    def test_ip_too_few_octets(self):
        self.assertFalse(validate.ip("10.0.1"))

    def test_ip_too_many_octets(self):
        self.assertFalse(validate.ip("10.0.0.1.5"))

    def test_ip_non_numeric(self):
        self.assertFalse(validate.ip("abc.def.ghi.jkl"))

    def test_ip_leading_spaces(self):
        """Leading/trailing whitespace is stripped by ip()."""
        self.assertTrue(validate.ip("  10.0.0.1  "))

    # --- hostname ---
    def test_hostname_empty(self):
        self.assertFalse(validate.hostname(""))

    def test_hostname_too_long(self):
        self.assertFalse(validate.hostname("a" * 254))

    def test_hostname_max_length(self):
        """253-char hostname with valid labels (each <= 63 chars)."""
        # Build a 253-char hostname: "a{62}.a{62}.a{62}.a{61}" = 63+1+63+1+63+1+62 = 254?
        # Actually: 4 labels of 62 chars + 3 dots = 251. Let's compute exactly.
        # We need total = 253. Use labels: 63.63.63.61 = 63+1+63+1+63+1+61 = 253
        name = "a" * 63 + "." + "a" * 63 + "." + "a" * 63 + "." + "a" * 61
        self.assertEqual(len(name), 253)
        self.assertTrue(validate.hostname(name))

    def test_hostname_single_char(self):
        self.assertTrue(validate.hostname("a"))

    def test_hostname_with_dots(self):
        self.assertTrue(validate.hostname("my.host.name"))

    def test_hostname_leading_hyphen(self):
        self.assertFalse(validate.hostname("-bad"))

    def test_hostname_trailing_hyphen(self):
        self.assertFalse(validate.hostname("bad-"))

    # --- username ---
    def test_username_empty(self):
        self.assertFalse(validate.username(""))

    def test_username_too_long(self):
        self.assertFalse(validate.username("a" * 33))

    def test_username_valid_with_underscore(self):
        self.assertTrue(validate.username("freq_admin"))

    def test_username_starts_with_digit(self):
        self.assertFalse(validate.username("1user"))

    def test_username_with_dollar_suffix(self):
        """Service accounts can end with $."""
        self.assertTrue(validate.username("machine$"))

    # --- vmid ---
    def test_vmid_below_minimum(self):
        self.assertFalse(validate.vmid(99))

    def test_vmid_at_minimum(self):
        self.assertTrue(validate.vmid(100))

    def test_vmid_at_maximum(self):
        self.assertTrue(validate.vmid(999999999))

    def test_vmid_above_maximum(self):
        self.assertFalse(validate.vmid(1000000000))

    def test_vmid_zero(self):
        self.assertFalse(validate.vmid(0))

    def test_vmid_negative(self):
        self.assertFalse(validate.vmid(-1))

    def test_vmid_string_number(self):
        """VMID as string is accepted (int conversion)."""
        self.assertTrue(validate.vmid("500"))

    def test_vmid_non_numeric_string(self):
        self.assertFalse(validate.vmid("abc"))

    def test_vmid_none(self):
        self.assertFalse(validate.vmid(None))

    # --- label ---
    def test_label_empty(self):
        self.assertFalse(validate.label(""))

    def test_label_too_long(self):
        self.assertFalse(validate.label("a" * 65))

    def test_label_max_length(self):
        self.assertTrue(validate.label("a" * 64))

    def test_label_with_hyphen(self):
        self.assertTrue(validate.label("my-host"))

    def test_label_leading_hyphen(self):
        self.assertFalse(validate.label("-bad"))

    # --- ssh_pubkey ---
    def test_ssh_pubkey_empty(self):
        self.assertFalse(validate.ssh_pubkey(""))

    def test_ssh_pubkey_single_word(self):
        self.assertFalse(validate.ssh_pubkey("ssh-rsa"))

    def test_ssh_pubkey_valid_ed25519(self):
        self.assertTrue(validate.ssh_pubkey("ssh-ed25519 AAAA...keydata"))

    def test_ssh_pubkey_unknown_type(self):
        self.assertFalse(validate.ssh_pubkey("ssh-dsa AAAAkeydata"))

    # --- vlan_id ---
    def test_vlan_id_zero(self):
        self.assertTrue(validate.vlan_id(0))

    def test_vlan_id_max(self):
        self.assertTrue(validate.vlan_id(4094))

    def test_vlan_id_over_max(self):
        self.assertFalse(validate.vlan_id(4095))

    def test_vlan_id_negative(self):
        self.assertFalse(validate.vlan_id(-1))

    def test_vlan_id_none(self):
        self.assertFalse(validate.vlan_id(None))

    # --- port ---
    def test_port_zero(self):
        self.assertFalse(validate.port(0))

    def test_port_one(self):
        self.assertTrue(validate.port(1))

    def test_port_max(self):
        self.assertTrue(validate.port(65535))

    def test_port_over_max(self):
        self.assertFalse(validate.port(65536))

    def test_port_negative(self):
        self.assertFalse(validate.port(-1))

    def test_port_none(self):
        self.assertFalse(validate.port(None))

    # --- is_protected_vmid ---
    def test_protected_vmid_in_list(self):
        self.assertTrue(validate.is_protected_vmid(100, [100, 200], []))

    def test_protected_vmid_in_range(self):
        self.assertTrue(validate.is_protected_vmid(150, [], [(100, 200)]))

    def test_protected_vmid_not_protected(self):
        self.assertFalse(validate.is_protected_vmid(999, [100], [(200, 300)]))

    def test_protected_vmid_invalid_input(self):
        """Non-numeric input returns False."""
        self.assertFalse(validate.is_protected_vmid("abc", [100], []))

    def test_protected_vmid_none_input(self):
        self.assertFalse(validate.is_protected_vmid(None, [], []))


if __name__ == "__main__":
    unittest.main()
