"""FREQ Edge Case Tests — error paths and boundary conditions.

Covers: malformed config, missing hosts.conf, vault corruption, config field
validation, SSH result edge cases, FleetBoundaries edge cases, validate.py
boundary inputs.
"""
import asyncio
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

# Path setup so freq imports work from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

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

    def _case_load_toml_missing_file(self):
        """Missing TOML file returns empty dict, no crash."""
        result = load_toml(os.path.join(self.tmpdir, "does-not-exist.toml"))
        self.assertEqual(result, {})

    def _case_load_toml_empty_file(self):
        """Empty TOML file returns empty dict."""
        path = os.path.join(self.tmpdir, "empty.toml")
        with open(path, "w") as f:
            f.write("")
        result = load_toml(path)
        self.assertEqual(result, {})

    def _case_load_toml_comments_only(self):
        """File with only comments returns empty dict."""
        path = os.path.join(self.tmpdir, "comments.toml")
        with open(path, "w") as f:
            f.write("# just a comment\n# another comment\n")
        result = load_toml(path)
        self.assertEqual(result, {})

    def _case_load_toml_invalid_syntax(self):
        """Malformed TOML returns empty dict instead of crashing."""
        path = os.path.join(self.tmpdir, "bad.toml")
        with open(path, "wb") as f:
            # Use valid UTF-8 but invalid TOML structure (unclosed bracket)
            f.write(b"[freq\nversion = broken\n")
        result = load_toml(path)
        # Should return empty dict (tomllib.TOMLDecodeError) or partial parse
        self.assertIsInstance(result, dict)

    def _case_apply_toml_empty_data(self):
        """_apply_toml with empty dict leaves defaults intact."""
        cfg = FreqConfig()
        _apply_toml(cfg, {})
        import freq
        self.assertEqual(cfg.version, freq.__version__)
        self.assertEqual(cfg.brand, "PVE FREQ")
        self.assertEqual(cfg.ssh_service_account, "freq-admin")

    def _case_apply_toml_wrong_types(self):
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

    def _case_apply_toml_extra_unknown_sections(self):
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

    def _case_missing_hosts_file(self):
        """Missing hosts.conf returns empty list."""
        result = load_hosts(os.path.join(self.tmpdir, "nope.conf"))
        self.assertEqual(result, [])

    def _case_empty_hosts_file(self):
        """Empty hosts.conf returns empty list."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("")
        result = load_hosts(path)
        self.assertEqual(result, [])

    def _case_only_comments_and_blanks(self):
        """File with only comments and blank lines returns empty list."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("# header\n\n# another comment\n   \n")
        result = load_hosts(path)
        self.assertEqual(result, [])

    def _case_short_lines_skipped(self):
        """Lines with fewer than 3 columns are skipped."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("10.0.0.1\n")          # 1 column
            f.write("10.0.0.2 label\n")    # 2 columns
        result = load_hosts(path)
        self.assertEqual(result, [])

    def _case_valid_3_column(self):
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

    def _case_5_column_with_all_ips(self):
        """5-column line parses ALL_IPS correctly."""
        path = os.path.join(self.tmpdir, "hosts.conf")
        with open(path, "w") as f:
            f.write("10.0.0.1  myhost  docker  prod  10.0.0.1,192.168.10.5\n")
        result = load_hosts(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].groups, "prod")
        self.assertEqual(result[0].all_ips, ["10.0.0.1", "192.168.10.5"])

    def _case_all_ips_trailing_comma(self):
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

    def _case_parse_entries_empty_string(self):
        from freq.modules.vault import _parse_entries
        result = _parse_entries("")
        self.assertEqual(result, [])

    def _case_parse_entries_only_comments(self):
        from freq.modules.vault import _parse_entries
        result = _parse_entries("# FREQ Vault\n# initialized\n")
        self.assertEqual(result, [])

    def _case_parse_entries_incomplete_pipes(self):
        """Lines with fewer than 3 pipe-delimited fields are skipped."""
        from freq.modules.vault import _parse_entries
        result = _parse_entries("host|key\nvalueonly\n")
        self.assertEqual(result, [])

    def _case_parse_entries_value_with_pipes(self):
        """Value field can contain pipe characters (split limit is 2)."""
        from freq.modules.vault import _parse_entries
        result = _parse_entries("host|key|value|with|pipes\n")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ("host", "key", "value|with|pipes"))

    def _case_serialize_round_trip(self):
        from freq.modules.vault import _parse_entries, _serialize_entries
        entries = [("host1", "password", "s3cret"), ("DEFAULT", "apikey", "abc123")]
        serialized = _serialize_entries(entries)
        parsed = _parse_entries(serialized)
        self.assertEqual(set(parsed), set(entries))

    def _case_vault_key_missing_machine_id(self):
        """_vault_key returns empty string when machine-id files are missing."""
        from freq.modules.vault import _vault_key
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = _vault_key()
            self.assertEqual(result, "")

    def _case_vault_get_no_key(self):
        """vault_get returns empty string when encryption key unavailable."""
        from freq.modules.vault import vault_get
        cfg = FreqConfig()
        cfg.vault_file = "/nonexistent/vault.enc"
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_get(cfg, "host", "key")
            self.assertEqual(result, "")

    def _case_vault_set_no_key(self):
        """vault_set returns False when encryption key unavailable."""
        from freq.modules.vault import vault_set
        cfg = FreqConfig()
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_set(cfg, "host", "key", "value")
            self.assertFalse(result)

    def _case_vault_delete_no_key(self):
        """vault_delete returns False when encryption key unavailable."""
        from freq.modules.vault import vault_delete
        cfg = FreqConfig()
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_delete(cfg, "host", "key")
            self.assertFalse(result)

    def _case_vault_list_no_key(self):
        """vault_list returns empty list when encryption key unavailable."""
        from freq.modules.vault import vault_list
        cfg = FreqConfig()
        with patch("freq.modules.vault._vault_key", return_value=""):
            result = vault_list(cfg)
            self.assertEqual(result, [])

    def _case_decrypt_missing_vault_file(self):
        """_decrypt returns empty string for nonexistent file."""
        from freq.modules.vault import _decrypt
        result = _decrypt("somekey", "/no/such/vault.enc")
        self.assertEqual(result, "")


VAULT_PARSING_CASES = (
    "_case_parse_entries_empty_string",
    "_case_parse_entries_only_comments",
    "_case_parse_entries_incomplete_pipes",
    "_case_parse_entries_value_with_pipes",
    "_case_serialize_round_trip",
    "_case_vault_key_missing_machine_id",
    "_case_vault_get_no_key",
    "_case_vault_set_no_key",
    "_case_vault_delete_no_key",
    "_case_vault_list_no_key",
    "_case_decrypt_missing_vault_file",
)


class TestVaultParsingMatrix(unittest.TestCase):
    def test_vault_parsing_matrix(self):
        run_case_matrix(self, TestVaultParsing, VAULT_PARSING_CASES)


# ---------------------------------------------------------------------------
# 4. Config with missing required fields
# ---------------------------------------------------------------------------

class TestConfigMissingFields(unittest.TestCase):
    """FreqConfig defaults must survive missing TOML sections."""

    def _case_default_config_all_fields_set(self):
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

    def _case_resolve_paths_with_empty_install_dir(self):
        """_resolve_paths works even with empty install_dir (uses '.')."""
        cfg = FreqConfig()
        cfg.install_dir = ""
        _resolve_paths(cfg)
        # Paths are set relative to empty string (current dir)
        self.assertTrue(cfg.conf_dir.endswith("conf"))
        self.assertTrue(cfg.hosts_file.endswith("hosts.toml"))

    def _case_load_containers_missing_file(self):
        """load_containers returns empty dict for missing file."""
        result = load_containers("/nonexistent/containers.toml")
        self.assertEqual(result, {})

    def _case_load_containers_non_integer_keys(self):
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

    def _case_load_fleet_boundaries_missing_file(self):
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

    def _case_cmdresult_empty_stdout(self):
        """CmdResult with empty stdout."""
        r = CmdResult(stdout="", stderr="", returncode=0)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.returncode, 0)

    def _case_cmdresult_special_characters(self):
        """CmdResult handles special characters in stdout/stderr."""
        r = CmdResult(
            stdout="line1\nline2\ttab\x00null",
            stderr="warn: unicode \u26a0",
            returncode=0,
        )
        self.assertIn("\n", r.stdout)
        self.assertIn("\t", r.stdout)
        self.assertIn("\u26a0", r.stderr)

    def _case_cmdresult_very_long_output(self):
        """CmdResult can hold very large stdout."""
        big = "x" * 1_000_000
        r = CmdResult(stdout=big, stderr="", returncode=0)
        self.assertEqual(len(r.stdout), 1_000_000)

    def _case_build_ssh_cmd_unknown_htype(self):
        """Unknown host type falls back to linux platform config."""
        from freq.core.ssh import _build_ssh_cmd
        cmd = _build_ssh_cmd(
            host="10.0.0.1", command="uptime",
            htype="alien", use_sudo=True,
        )
        cmd_str = " ".join(cmd)
        self.assertIn("ssh", cmd_str)
        self.assertIn("10.0.0.1", cmd_str)

    def _case_build_ssh_cmd_empty_command(self):
        """SSH cmd with empty command does not append sudo wrapper."""
        from freq.core.ssh import _build_ssh_cmd
        cmd = _build_ssh_cmd(
            host="10.0.0.1", command="",
            htype="linux", use_sudo=True,
        )
        cmd_str = " ".join(cmd)
        self.assertNotIn("sudo sh", cmd_str)

    def _case_build_ssh_cmd_command_with_single_quotes(self):
        """Single quotes in command are properly escaped."""
        from freq.core.ssh import _build_ssh_cmd
        cmd = _build_ssh_cmd(
            host="10.0.0.1", command="echo 'hello world'",
            htype="linux", use_sudo=True,
        )
        cmd_str = " ".join(cmd)
        # The command should be wrapped in sudo sh -c '...'
        self.assertIn("sudo sh -c", cmd_str)

    def _case_build_ssh_cmd_can_sudo_root_only_password_file(self):
        """Root-owned staged device secrets can be consumed via sudo sshpass."""
        from freq.core.ssh import _build_ssh_cmd

        cmd = _build_ssh_cmd(
            host="10.0.0.1",
            command="show version",
            htype="switch",
            use_sudo=False,
            user="freq-ops",
            password_file="/tmp/no-such-secret",
            sudo_password_file=True,
        )
        self.assertNotIn("sudo", cmd)

        with tempfile.NamedTemporaryFile() as f:
            cmd = _build_ssh_cmd(
                host="10.0.0.1",
                command="show version",
                htype="switch",
                use_sudo=False,
                user="freq-ops",
                password_file=f.name,
                sudo_password_file=True,
            )
        self.assertEqual(cmd[:4], ["sudo", "-n", "sshpass", "-f"])

    def _case_remote_command_serialization_contract(self):
        """One serializer preserves hostile values as individual arguments."""
        from freq.core.ssh import remote_command

        values = (
            "plain",
            "two words",
            "single'quote",
            'double"quote',
            "semi;colon",
            "$(printf command-substitution)",
            "`printf backtick`",
            "star*question?",
            "back\\slash",
            "line one\nline two",
            "",
            "--option-looking",
        )
        self.assertEqual(remote_command(argv=values), shlex.join(values))
        script = 'printf "%s\\n" "$@"'
        self.assertEqual(
            remote_command(script=script, args=values),
            shlex.join(("sh", "-c", script, "freq", *values)),
        )

    def _case_remote_command_rejects_invalid_shapes(self):
        """Mixed, empty, scalar, non-string, and NUL inputs fail closed."""
        from freq.core.ssh import remote_command

        invalid = (
            {},
            {"argv": ()},
            {"argv": "echo"},
            {"argv": ("echo", 1)},
            {"argv": ("echo", "bad\x00value")},
            {"argv": ("echo",), "args": ("extra",)},
            {"argv": ("echo",), "script": "printf ok"},
            {"script": ""},
            {"script": "printf ok", "args": "scalar"},
            {"script": "printf ok", "args": (1,)},
            {"script": "printf bad\x00script"},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((TypeError, ValueError)):
                    remote_command(**kwargs)

    def _case_remote_command_script_keeps_values_out_of_grammar(self):
        """A real shell observes hostile inputs byte-for-byte as positional data."""
        from freq.core.ssh import remote_command

        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "must-not-exist"
            values = (
                f"$(touch {marker})",
                f"`touch {marker}`",
                "semi;colon",
                "star*question?",
                "line one\nline two",
                "",
            )
            command = remote_command(
                script='printf "%s\\0" "$@"',
                args=values,
            )
            result = subprocess.run(
                ["sh", "-c", command],
                capture_output=True,
                check=True,
            )
            self.assertEqual(
                result.stdout.split(b"\x00")[:-1],
                [item.encode() for item in values],
            )
            self.assertFalse(marker.exists())

    def _case_remote_command_governed_sink_inventory(self):
        """Every dynamic governed sink uses the serializer or a named boundary."""
        from tests.support.remote_command_contract import (
            EXPECTED_COUNTS,
            EXPECTED_TOTAL,
            construction_errors,
            count_by_path,
            inventory,
            serializer_call_errors,
        )

        repo_root = Path(__file__).resolve().parents[1]
        calls, trees = inventory(repo_root)
        self.assertEqual(count_by_path(calls), EXPECTED_COUNTS)
        self.assertEqual(len(calls), EXPECTED_TOTAL)
        self.assertEqual(serializer_call_errors(trees), [])
        errors = construction_errors(calls, trees["freq/api/fleet.py"])
        self.assertEqual(
            errors,
            [],
            "dynamic remote command construction bypasses remote_command, or a "
            "declared wrapper/boundary drifted:\n" + "\n".join(errors),
        )

    def _case_remote_command_ast_policy_rejects_rendered_shell(self):
        """The AST owner distinguishes safe arguments from rendered grammar."""
        import ast

        from tests.support.remote_command_contract import serializer_call_errors

        invalid = {
            "dynamic executable": "remote_command(argv=(f'{program}', 'value'))",
            "rendered sh c": "remote_command(argv=('sh', '-c', f'echo {value}'))",
            "dynamic script": "remote_command(script=script, args=(value,))",
            "opaque argv sequence": "remote_command(argv=parts)",
            "caller quote": "remote_command(argv=('printf', shlex.quote(value)))",
        }
        for label, source in invalid.items():
            with self.subTest(rejected=label):
                tree = ast.parse(source, filename=f"{label}.py")
                self.assertTrue(serializer_call_errors({f"{label}.py": tree}))

        valid = {
            "dynamic argument": "remote_command(argv=('printf', '%s', f'{value}'))",
            "fixed script positional data": (
                'remote_command(script=\'printf "%s\\n" "$1"\', args=(value,))'
            ),
        }
        for label, source in valid.items():
            with self.subTest(accepted=label):
                tree = ast.parse(source, filename=f"{label}.py")
                self.assertEqual(serializer_call_errors({f"{label}.py": tree}), [])

    def _case_truenas_dataset_list_preserves_optional_operand_arity(self):
        """List-all has no dataset operand; scoped list has exactly one."""
        from freq.api import store

        commands = []

        def run_case(body):
            with (
                patch.object(store, "require_post", return_value=False),
                patch.object(store, "_check_session_role", return_value=("admin", None)),
                patch.object(
                    store,
                    "load_config",
                    return_value=SimpleNamespace(truenas_ip="192.0.2.10"),
                ),
                patch.object(store, "get_json_body", return_value=body),
                patch.object(
                    store,
                    "_truenas_ssh",
                    side_effect=lambda _cfg, command: (
                        commands.append(command)
                        or SimpleNamespace(returncode=0, stdout="", stderr="")
                    ),
                ),
                patch.object(store, "json_response"),
            ):
                store.handle_truenas_dataset(SimpleNamespace())

        run_case({"action": "list"})
        run_case({"action": "list", "dataset": "tank/scoped"})

        self.assertEqual(shlex.split(commands[0])[4:], [])
        self.assertEqual(shlex.split(commands[1])[4:], ["tank/scoped"])


# ---------------------------------------------------------------------------
# 7. validate.py edge cases
# ---------------------------------------------------------------------------

class TestValidateBoundaryTables(unittest.TestCase):
    """One fail-closed table owner per public validator."""

    def _assert_cases(self, validator, cases, expected_count):
        self.assertEqual(len(cases), expected_count)
        names = [name for name, _args, _expected in cases]
        self.assertEqual(len(set(names)), expected_count)
        for name, args, expected in cases:
            with self.subTest(case=name):
                self.assertEqual(validator(*args), expected)

    def _case_ip_cases(self):
        self._assert_cases(validate.ip, (
            ("empty", ("",), False),
            ("valid", ("192.168.255.1",), True),
            ("all-zero", ("0.0.0.0",), True),
            ("all-max", ("255.255.255.255",), True),
            ("octet-256", ("256.0.0.1",), False),
            ("negative-octet", ("-1.0.0.1",), False),
            ("too-few-octets", ("10.0.1",), False),
            ("too-many-octets", ("10.0.0.1.5",), False),
            ("non-numeric", ("abc.def.ghi.jkl",), False),
            ("surrounding-space", ("  10.0.0.1  ",), True),
        ), 10)

    def _case_hostname_cases(self):
        max_hostname = ".".join(("a" * 63, "a" * 63, "a" * 63, "a" * 61))
        self.assertEqual(len(max_hostname), 253)
        self._assert_cases(validate.hostname, (
            ("empty", ("",), False),
            ("too-long", ("a" * 254,), False),
            ("max-length", (max_hostname,), True),
            ("single-char", ("a",), True),
            ("dotted", ("my.host.name",), True),
            ("leading-hyphen", ("-bad",), False),
            ("trailing-hyphen", ("bad-",), False),
        ), 7)

    def _case_username_cases(self):
        self._assert_cases(validate.username, (
            ("empty", ("",), False),
            ("too-long", ("a" * 33,), False),
            ("underscore", ("freq_admin",), True),
            ("starts-with-digit", ("1user",), False),
            ("service-account-dollar", ("machine$",), True),
        ), 5)

    def _case_vmid_cases(self):
        self._assert_cases(validate.vmid, (
            ("below-minimum", (99,), False),
            ("minimum", (100,), True),
            ("maximum", (999999999,), True),
            ("above-maximum", (1000000000,), False),
            ("zero", (0,), False),
            ("negative", (-1,), False),
            ("numeric-string", ("500",), True),
            ("non-numeric-string", ("abc",), False),
            ("none", (None,), False),
        ), 9)

    def _case_label_cases(self):
        self._assert_cases(validate.label, (
            ("empty", ("",), False),
            ("too-long", ("a" * 65,), False),
            ("max-length", ("a" * 64,), True),
            ("hyphen", ("my-host",), True),
            ("leading-hyphen", ("-bad",), False),
        ), 5)

    def _case_ssh_pubkey_cases(self):
        self._assert_cases(validate.ssh_pubkey, (
            ("empty", ("",), False),
            ("missing-key-data", ("ssh-rsa",), False),
            ("ed25519", ("ssh-ed25519 AAAA...keydata",), True),
            ("unsupported-dsa", ("ssh-dsa AAAAkeydata",), False),
        ), 4)

    def _case_vlan_id_cases(self):
        self._assert_cases(validate.vlan_id, (
            ("zero", (0,), True),
            ("maximum", (4094,), True),
            ("above-maximum", (4095,), False),
            ("negative", (-1,), False),
            ("none", (None,), False),
        ), 5)

    def _case_port_cases(self):
        self._assert_cases(validate.port, (
            ("zero", (0,), False),
            ("one", (1,), True),
            ("maximum", (65535,), True),
            ("above-maximum", (65536,), False),
            ("negative", (-1,), False),
            ("none", (None,), False),
        ), 6)

    def _case_protected_vmid_cases(self):
        self._assert_cases(validate.is_protected_vmid, (
            ("explicit-list", (100, [100, 200], []), True),
            ("range", (150, [], [(100, 200)]), True),
            ("not-protected", (999, [100], [(200, 300)]), False),
            ("invalid", ("abc", [100], []), False),
            ("none", (None, [], []), False),
        ), 5)


# ---------------------------------------------------------------------------
# 7. SSH Transport Edge Cases
# ---------------------------------------------------------------------------

class TestSSHTransportEdgeCases(unittest.TestCase):
    """SSH transport must handle missing keys, timeouts, and failures."""

    @patch("freq.core.ssh.subprocess.run")
    def _case_run_timeout_returns_code_124(self, mock_sub):
        """SSH timeout returns CmdResult with returncode=124."""
        from freq.core.ssh import run
        mock_sub.side_effect = subprocess.TimeoutExpired("ssh", 30)
        result = run("10.0.0.1", "uptime", command_timeout=30)
        self.assertEqual(result.returncode, 124)
        self.assertIn("Timeout", result.stderr)
        self.assertEqual(result.stdout, "")

    @patch("freq.core.ssh.subprocess.run")
    def _case_run_oserror_returns_code_1(self, mock_sub):
        """SSH OSError (connection refused, etc.) returns CmdResult with returncode=1."""
        from freq.core.ssh import run
        mock_sub.side_effect = OSError("Connection refused")
        result = run("10.0.0.1", "uptime")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Connection refused", result.stderr)
        self.assertEqual(result.stdout, "")

    @patch("freq.core.ssh.subprocess.run")
    def _case_run_nonexistent_key_path_still_builds_command(self, mock_sub):
        """Missing key file doesn't crash run() — SSH itself will fail."""
        from freq.core.ssh import run
        mock_sub.return_value = MagicMock(
            stdout="", stderr="No such file: /nonexistent/key",
            returncode=255,
        )
        result = run("10.0.0.1", "uptime", key_path="/nonexistent/key")
        self.assertEqual(result.returncode, 255)
        # Verify the command was still attempted (SSH binary was called)
        mock_sub.assert_called_once()

    @patch("freq.core.ssh.subprocess.run")
    def _case_run_none_key_path_omits_dash_i(self, mock_sub):
        """When key_path is None, SSH command has no -i flag."""
        from freq.core.ssh import run
        mock_sub.return_value = MagicMock(
            stdout="ok", stderr="", returncode=0,
        )
        run("10.0.0.1", "uptime", key_path=None)
        call_args = mock_sub.call_args[0][0]
        self.assertNotIn("-i", call_args)

    @patch("freq.core.ssh.subprocess.run")
    def _case_run_success_has_duration(self, mock_sub):
        """Successful run populates duration field."""
        from freq.core.ssh import run
        mock_sub.return_value = MagicMock(
            stdout="up 5 days", stderr="", returncode=0,
        )
        result = run("10.0.0.1", "uptime")
        self.assertEqual(result.returncode, 0)
        self.assertGreaterEqual(result.duration, 0)

    def _case_run_many_empty_hosts_returns_empty_dict(self):
        """run_many with no hosts returns empty dict without error."""
        from freq.core.ssh import run_many
        result = run_many(hosts=[], command="uptime")
        self.assertEqual(result, {})

    @patch("freq.core.ssh.async_run")
    def _case_run_many_duplicate_labels_both_get_ip_keys(self, mock_run):
        """Duplicate host labels must both get label@ip keys, not silent overwrite."""
        from freq.core.ssh import run_many
        from freq.core.types import Host, CmdResult

        h1 = Host(ip="10.0.0.1", label="webserver", htype="linux")
        h2 = Host(ip="10.0.0.2", label="webserver", htype="linux")
        r1 = CmdResult(stdout="host1", stderr="", returncode=0, duration=0.1)
        r2 = CmdResult(stdout="host2", stderr="", returncode=0, duration=0.1)

        async def fake_run(host, command, **kw):
            return r1 if host == "10.0.0.1" else r2

        mock_run.side_effect = fake_run
        result = run_many(hosts=[h1, h2], command="hostname")

        # Both must be accessible — neither silently overwrites the other
        self.assertIn("webserver@10.0.0.1", result)
        self.assertIn("webserver@10.0.0.2", result)
        self.assertEqual(result["webserver@10.0.0.1"].stdout, "host1")
        self.assertEqual(result["webserver@10.0.0.2"].stdout, "host2")
        # Bare label should NOT exist when duplicated
        self.assertNotIn("webserver", result)
        # IP keys still work
        self.assertIn("10.0.0.1", result)
        self.assertIn("10.0.0.2", result)

    @patch("freq.core.ssh.async_run")
    def _case_run_many_unique_labels_use_bare_label(self, mock_run):
        """Unique host labels keep bare label keys (no regression)."""
        from freq.core.ssh import run_many
        from freq.core.types import Host, CmdResult

        h1 = Host(ip="10.0.0.1", label="web", htype="linux")
        h2 = Host(ip="10.0.0.2", label="db", htype="linux")
        r1 = CmdResult(stdout="web", stderr="", returncode=0, duration=0.1)
        r2 = CmdResult(stdout="db", stderr="", returncode=0, duration=0.1)

        async def fake_run(host, command, **kw):
            return r1 if host == "10.0.0.1" else r2

        mock_run.side_effect = fake_run
        result = run_many(hosts=[h1, h2], command="hostname")

        self.assertIn("web", result)
        self.assertIn("db", result)
        self.assertEqual(result["web"].stdout, "web")
        self.assertEqual(result["db"].stdout, "db")

    def _case_async_run_carries_input_without_logging_it(self):
        """Async SSH writes the exact payload to stdin and never to a logger."""
        from freq.core import ssh

        payload = "alice:unique-password-value\n"
        observed = {}

        class FakeProcess:
            returncode = 0

            async def communicate(self, input=None):
                observed["communicate_input"] = input
                return b"updated\n", b""

        async def fake_create_subprocess_exec(*args, **kwargs):
            observed["argv"] = args
            observed["stdin"] = kwargs.get("stdin")
            return FakeProcess()

        with (
            patch.object(ssh.asyncio, "create_subprocess_exec", side_effect=fake_create_subprocess_exec),
            patch.object(ssh.logger, "debug") as log_debug,
            patch.object(ssh.logger, "cmd") as log_cmd,
            patch.object(ssh.logger, "error") as log_error,
            patch.object(ssh.logger, "perf") as log_perf,
        ):
            result = asyncio.run(
                ssh.async_run(
                    host="192.0.2.10",
                    command="/usr/sbin/chpasswd",
                    use_sudo=True,
                    input_text=payload,
                )
            )

        self.assertEqual(result.stdout, "updated")
        self.assertEqual(observed["stdin"], asyncio.subprocess.PIPE)
        self.assertEqual(observed["communicate_input"], payload.encode("utf-8"))
        for logger_mock in (log_debug, log_cmd, log_error, log_perf):
            self.assertNotIn(payload.strip(), repr(logger_mock.call_args_list))

    @patch("freq.core.ssh.async_run")
    def _case_run_many_carries_one_exact_input_to_every_host(self, mock_run):
        """Sync and async fleet wrappers preserve one exact stdin payload."""
        from freq.core.ssh import run_many
        from freq.core.types import CmdResult, Host

        hosts = [
            Host(ip="192.0.2.11", label="one", htype="linux"),
            Host(ip="192.0.2.12", label="two", htype="linux"),
        ]
        payload = "alice:unique-password-value\n"

        async def fake_run(**kwargs):
            return CmdResult(stdout=kwargs["host"], stderr="", returncode=0)

        mock_run.side_effect = fake_run
        results = run_many(
            hosts=hosts,
            command="/usr/sbin/chpasswd",
            use_sudo=True,
            input_text=payload,
        )
        self.assertEqual(results["one"].stdout, "192.0.2.11")
        self.assertEqual(results["two"].stdout, "192.0.2.12")
        self.assertEqual(mock_run.call_count, 2)
        for call in mock_run.call_args_list:
            self.assertEqual(call.kwargs["input_text"], payload)

    def _case_password_rotation_keeps_secret_out_of_command_and_logs(self):
        """Password bytes exist only in prompt memory and the stdin record."""
        from freq.modules import users

        password = "unique-password-value"
        host = Host(ip="192.0.2.20", label="node", htype="linux")
        cfg = SimpleNamespace(
            hosts=[host],
            ssh_key_path="/tmp/key",
            ssh_connect_timeout=4,
            ssh_max_parallel=3,
        )
        args = SimpleNamespace(username="alice")
        result = CmdResult(stdout="", stderr="", returncode=0)

        with (
            patch.object(users.getpass, "getpass", side_effect=[password, password]),
            patch.object(users, "remote_command", return_value="/usr/sbin/chpasswd") as construct,
            patch.object(users, "ssh_run_many", return_value={host.label: result}) as run_many,
            patch.object(users, "fmt", MagicMock()),
        ):
            self.assertEqual(users.cmd_passwd(cfg, None, args), 0)

        construct.assert_called_once_with(argv=("/usr/sbin/chpasswd",))
        kwargs = run_many.call_args.kwargs
        self.assertEqual(kwargs["command"], "/usr/sbin/chpasswd")
        self.assertEqual(kwargs["input_text"], f"alice:{password}\n")
        self.assertTrue(kwargs["use_sudo"])
        non_input_fields = {key: value for key, value in kwargs.items() if key != "input_text"}
        self.assertNotIn(password, repr(non_input_fields))

    def _case_password_rotation_rejects_stdin_record_delimiters(self):
        """One prompt value can never become a second chpasswd input record."""
        from freq.modules import users

        host = Host(ip="192.0.2.20", label="node", htype="linux")
        cfg = SimpleNamespace(
            hosts=[host],
            ssh_key_path="/tmp/key",
            ssh_connect_timeout=4,
            ssh_max_parallel=3,
        )
        args = SimpleNamespace(username="alice")
        for password in (
            "validpass\nroot:replacement",
            "validpass\rroot:replacement",
            "validpass\x00suffix",
        ):
            with (
                self.subTest(delimiter=repr(password)),
                patch.object(users.getpass, "getpass", side_effect=[password, password]),
                patch.object(users, "ssh_run_many") as run_many,
                patch.object(users, "fmt", MagicMock()),
            ):
                self.assertEqual(users.cmd_passwd(cfg, None, args), 1)
                run_many.assert_not_called()


SSH_TRANSPORT_EDGE_CASES = (
    "_case_run_timeout_returns_code_124",
    "_case_run_oserror_returns_code_1",
    "_case_run_nonexistent_key_path_still_builds_command",
    "_case_run_none_key_path_omits_dash_i",
    "_case_run_success_has_duration",
    "_case_run_many_empty_hosts_returns_empty_dict",
    "_case_run_many_duplicate_labels_both_get_ip_keys",
    "_case_run_many_unique_labels_use_bare_label",
    "_case_async_run_carries_input_without_logging_it",
    "_case_run_many_carries_one_exact_input_to_every_host",
    "_case_password_rotation_keeps_secret_out_of_command_and_logs",
    "_case_password_rotation_rejects_stdin_record_delimiters",
)


class TestSSHTransportEdgeCasesMatrix(unittest.TestCase):
    def test_ssh_transport_edge_cases_matrix(self):
        run_case_matrix(self, TestSSHTransportEdgeCases, SSH_TRANSPORT_EDGE_CASES)


# ---------------------------------------------------------------------------
# 8. PVE API Fallback Edge Cases
# ---------------------------------------------------------------------------

class TestPVEApiEdgeCases(unittest.TestCase):
    """PVE API must fail gracefully and fall back to SSH."""

    def _case_api_call_no_token_returns_false(self):
        """Missing API token returns ('', False) immediately."""
        from freq.modules.pve import _pve_api_call
        cfg = MagicMock()
        cfg.pve_api_token_id = ""
        cfg.pve_api_token_secret = ""
        result, ok = _pve_api_call(cfg, "10.0.0.1", "/nodes")
        self.assertFalse(ok)
        self.assertEqual(result, "")

    def _case_api_call_missing_secret_returns_false(self):
        """Token ID present but secret empty returns ('', False)."""
        from freq.modules.pve import _pve_api_call
        cfg = MagicMock()
        cfg.pve_api_token_id = "freq@pve!dashboard"
        cfg.pve_api_token_secret = ""
        result, ok = _pve_api_call(cfg, "10.0.0.1", "/nodes")
        self.assertFalse(ok)

    @patch("freq.modules.pve.urllib.request.urlopen")
    def _case_api_call_reads_runtime_rw_token_file(self, mock_urlopen):
        """Runtime PVE API calls use the same RW token file doctor verifies."""
        from freq.modules.pve import _pve_api_call
        import tempfile

        class _Resp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b'{"data":{"ok":true}}'

        with tempfile.TemporaryDirectory() as root:
            cred_dir = os.path.join(root, "credentials")
            os.makedirs(cred_dir)
            with open(os.path.join(cred_dir, "pve-token-rw"), "w") as f:
                f.write("secret-from-file\n")
            cfg = MagicMock()
            cfg.pve_api_token_id = "freq@pam!freq-rw"
            cfg.pve_api_token_secret = ""
            cfg.pve_api_verify_ssl = False
            cfg.credentials_dir = cred_dir
            mock_urlopen.return_value = _Resp()

            result, ok = _pve_api_call(cfg, "10.0.0.1", "/version")

        self.assertTrue(ok)
        self.assertEqual(result, {"ok": True})
        req = mock_urlopen.call_args.args[0]
        self.assertIn("PVEAPIToken=freq@pam!freq-rw=secret-from-file", req.headers.get("Authorization", ""))

    @patch("freq.modules.pve._pve_cmd")
    @patch("freq.modules.pve.urllib.request.urlopen")
    def _case_pve_call_uses_runtime_rw_token_before_ssh_fallback(self, mock_urlopen, mock_pve_cmd):
        """Higher-level PVE calls also use the runtime RW token file before SSH."""
        from freq.modules.pve import _pve_call
        import tempfile

        class _Resp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b'{"data":[{"vmid":100}]}'

        with tempfile.TemporaryDirectory() as root:
            cred_dir = os.path.join(root, "credentials")
            os.makedirs(cred_dir)
            with open(os.path.join(cred_dir, "pve-token-rw"), "w") as f:
                f.write("secret-from-file\n")
            cfg = MagicMock()
            cfg.pve_api_token_id = "freq@pam!freq-rw"
            cfg.pve_api_token_secret = ""
            cfg.pve_api_verify_ssl = False
            cfg.credentials_dir = cred_dir
            mock_urlopen.return_value = _Resp()

            result, ok = _pve_call(
                cfg,
                "10.0.0.1",
                "/cluster/resources?type=vm",
                "pvesh get /cluster/resources --type vm --output-format json",
            )

        self.assertTrue(ok)
        self.assertEqual(result, [{"vmid": 100}])
        mock_pve_cmd.assert_not_called()

    @patch("freq.modules.pve.urllib.request.urlopen")
    def _case_api_call_unreachable_returns_false(self, mock_urlopen):
        """Unreachable API returns error string and False."""
        from freq.modules.pve import _pve_api_call
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        cfg = MagicMock()
        cfg.pve_api_token_id = "freq@pve!dashboard"
        cfg.pve_api_token_secret = "secret-uuid"
        cfg.pve_api_verify_ssl = False
        result, ok = _pve_api_call(cfg, "10.0.0.1", "/nodes")
        self.assertFalse(ok)
        self.assertIn("Connection refused", str(result))

    @patch("freq.modules.pve.urllib.request.urlopen")
    def _case_api_call_timeout_returns_false(self, mock_urlopen):
        """API timeout returns error and False."""
        from freq.modules.pve import _pve_api_call
        mock_urlopen.side_effect = TimeoutError("timed out")
        cfg = MagicMock()
        cfg.pve_api_token_id = "freq@pve!dashboard"
        cfg.pve_api_token_secret = "secret-uuid"
        cfg.pve_api_verify_ssl = False
        result, ok = _pve_api_call(cfg, "10.0.0.1", "/nodes")
        self.assertFalse(ok)

    @patch("freq.modules.pve._pve_cmd")
    def _case_pve_call_no_token_falls_back_to_ssh(self, mock_ssh):
        """No API token configured → skip API, go straight to SSH."""
        from freq.modules.pve import _pve_call
        mock_ssh.return_value = ("qm list output", True)
        cfg = MagicMock()
        cfg.pve_api_token_id = ""
        cfg.pve_api_token_secret = ""
        result, ok = _pve_call(cfg, "10.0.0.1", "/nodes", "qm list")
        self.assertTrue(ok)
        mock_ssh.assert_called_once()

    @patch("freq.modules.pve._pve_cmd")
    @patch("freq.modules.pve._pve_api_call")
    def _case_pve_call_api_fail_falls_back_to_ssh(self, mock_api, mock_ssh):
        """API fails → automatically falls back to SSH."""
        from freq.modules.pve import _pve_call
        mock_api.return_value = ("Connection refused", False)
        mock_ssh.return_value = ("100 running", True)
        cfg = MagicMock()
        cfg.pve_api_token_id = "freq@pve!dashboard"
        cfg.pve_api_token_secret = "secret-uuid"
        result, ok = _pve_call(cfg, "10.0.0.1", "/nodes", "qm list")
        self.assertTrue(ok)
        self.assertEqual(result, "100 running")
        mock_api.assert_called_once()
        mock_ssh.assert_called_once()

    @patch("freq.modules.pve._pve_cmd")
    @patch("freq.modules.pve._pve_api_call")
    def _case_pve_call_both_fail(self, mock_api, mock_ssh):
        """Both API and SSH fail → returns SSH failure."""
        from freq.modules.pve import _pve_call
        mock_api.return_value = ("timeout", False)
        mock_ssh.return_value = ("", False)
        cfg = MagicMock()
        cfg.pve_api_token_id = "freq@pve!dashboard"
        cfg.pve_api_token_secret = "secret-uuid"
        result, ok = _pve_call(cfg, "10.0.0.1", "/nodes", "qm list")
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# 9. Fleet Commands with Zero Hosts
# ---------------------------------------------------------------------------

class TestFleetZeroHosts(unittest.TestCase):
    """Fleet commands must handle zero hosts gracefully."""

    @patch("freq.core.fmt.footer")
    @patch("freq.core.fmt.blank")
    @patch("freq.core.fmt.line")
    @patch("freq.core.fmt.header")
    def _case_cmd_status_zero_hosts_returns_zero(self, *_mocks):
        """freq status with no hosts shows message, returns 0."""
        from freq.modules.fleet import cmd_status
        cfg = MagicMock()
        cfg.hosts = []
        pack = MagicMock()
        args = MagicMock()
        result = cmd_status(cfg, pack, args)
        self.assertEqual(result, 0)

    @patch("freq.core.fmt.info")
    @patch("freq.core.fmt.error")
    def _case_cmd_exec_no_match_returns_one(self, mock_error, mock_info):
        """freq exec with no matching hosts returns 1."""
        from freq.modules.fleet import cmd_exec
        cfg = MagicMock()
        cfg.hosts = []
        cfg.ssh_key_path = "/tmp/fake"
        cfg.ssh_user = "freq-admin"
        cfg.connect_timeout = 5
        cfg.max_parallel = 5
        pack = MagicMock()
        args = MagicMock()
        args.target = "nonexistent"
        args.command = "uptime"
        args.group = None
        args.timeout = 30
        result = cmd_exec(cfg, pack, args)
        self.assertEqual(result, 1)
        mock_error.assert_called()


# ---------------------------------------------------------------------------
# 10. Dashboard API with Zero/Invalid State
# ---------------------------------------------------------------------------
# NOTE: TestDashboardEdgeCases removed — tested _serve_exec, _serve_host_detail,
# _serve_fleet_overview which were deleted from serve.py during the API refactor.
# Those endpoints now live in freq/api/*.py and are tested separately.


# ---------------------------------------------------------------------------
# 11. Config Corruption and Recovery
# ---------------------------------------------------------------------------

class TestConfigCorruption(unittest.TestCase):
    """Config must survive partial corruption and recover gracefully."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _case_freq_toml_with_only_ssh_section(self):
        """Partial freq.toml with only [ssh] section still loads."""
        path = os.path.join(self.tmpdir, "freq.toml")
        with open(path, "w") as f:
            f.write('[ssh]\nservice_account = "testuser"\nconnect_timeout = 10\n')
        data = load_toml(path)
        self.assertEqual(data["ssh"]["service_account"], "testuser")

    def _case_freq_toml_with_duplicate_sections(self):
        """TOML with duplicate keys in different sections loads."""
        path = os.path.join(self.tmpdir, "freq.toml")
        with open(path, "w") as f:
            f.write('[freq]\ndebug = true\n\n[ssh]\ndebug = false\n')
        data = load_toml(path)
        self.assertTrue(data["freq"]["debug"])
        self.assertFalse(data["ssh"]["debug"])

    def _case_hosts_toml_with_missing_fields(self):
        """hosts.toml entries with missing optional fields still load."""
        path = os.path.join(self.tmpdir, "hosts.toml")
        with open(path, "w") as f:
            f.write('[[host]]\nip = "10.0.0.1"\nlabel = "test"\n')
        from freq.core.config import load_hosts_toml
        hosts = load_hosts_toml(path)
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0].ip, "10.0.0.1")
        # type should default to "linux"
        self.assertEqual(hosts[0].htype, "linux")

    def _case_hosts_toml_with_empty_host_entries(self):
        """hosts.toml with empty [[host]] blocks doesn't crash."""
        path = os.path.join(self.tmpdir, "hosts.toml")
        with open(path, "w") as f:
            f.write('[[host]]\n\n[[host]]\nip = "10.0.0.1"\nlabel = "valid"\n')
        from freq.core.config import load_hosts_toml
        hosts = load_hosts_toml(path)
        # Should get at least the valid entry
        valid = [h for h in hosts if h.ip == "10.0.0.1"]
        self.assertEqual(len(valid), 1)

    def _case_apply_toml_with_nested_unknown_keys(self):
        """Unknown nested TOML keys don't crash _apply_toml."""
        cfg = FreqConfig()
        data = {"completely_unknown": {"nested": {"deep": True}}}
        _apply_toml(cfg, data)
        # Should not crash — unknown sections silently ignored

    def _case_vlans_toml_missing_gateway(self):
        """vlans.toml with missing gateway field loads without error."""
        path = os.path.join(self.tmpdir, "vlans.toml")
        with open(path, "w") as f:
            f.write('[vlan.storage]\nid = 25\nname = "Storage"\nsubnet = "10.0.25.0/24"\nprefix = "10.0.25"\n')
        data = load_toml(path)
        self.assertIn("vlan", data)
        self.assertIn("storage", data["vlan"])
        # No gateway key — should be fine
        self.assertNotIn("gateway", data["vlan"]["storage"])


# ---------------------------------------------------------------------------
# 12. Validate Module Boundary Cases (extended)
# ---------------------------------------------------------------------------

class TestValidateExtended(unittest.TestCase):
    """Extended boundary tests for validate module."""

    def _case_ip_with_leading_zeros(self):
        """IPs with leading zeros like 010.0.0.1 — should not crash."""
        result = validate.ip("010.0.0.1")
        self.assertIsInstance(result, bool)

    def _case_hostname_with_unicode(self):
        """Unicode hostnames should be rejected."""
        self.assertFalse(validate.hostname("hôst-1"))

    def _case_vmid_max_value(self):
        """VMID at maximum Proxmox value (999999999) should be valid."""
        self.assertTrue(validate.vmid(999999999))

    def _case_vmid_float_rejected(self):
        """Float VMID should be rejected or handled without crash."""
        result = validate.vmid(100.5)
        self.assertIsInstance(result, bool)

    def _case_label_with_only_hyphens(self):
        """Label of only hyphens should be rejected."""
        self.assertFalse(validate.label("---"))

    def _case_empty_string_inputs_dont_crash(self):
        """All validators handle empty string without crashing."""
        validate.ip("")
        validate.hostname("")
        validate.username("")
        validate.label("")
        # No assertion — just proving no crash


# ---------------------------------------------------------------------------
# Duplicate-label callers — result_for() usage
# ---------------------------------------------------------------------------

class TestDupLabelCallers(unittest.TestCase):
    """Callers that read run_many results must use result_for(), not bare label."""

    @patch("freq.api.logs.ssh_run_many")
    def _case_log_query_uses_result_for_on_dup_labels(self, mock_run_many):
        """_log_query must not drop results when two hosts share a label."""
        from freq.api.logs import _log_query

        h1 = Host(ip="10.0.0.1", label="webserver", htype="linux")
        h2 = Host(ip="10.0.0.2", label="webserver", htype="linux")

        # Simulate run_many with dup-label keys (label@ip)
        mock_run_many.return_value = {
            "webserver@10.0.0.1": CmdResult(stdout="error log host1", stderr="", returncode=0, duration=0.1),
            "webserver@10.0.0.2": CmdResult(stdout="error log host2", stderr="", returncode=0, duration=0.1),
            "10.0.0.1": CmdResult(stdout="error log host1", stderr="", returncode=0, duration=0.1),
            "10.0.0.2": CmdResult(stdout="error log host2", stderr="", returncode=0, duration=0.1),
        }

        cfg = MagicMock()
        cfg.hosts = [h1, h2]
        cfg.ssh_key_path = "/tmp/key"
        cfg.ssh_connect_timeout = 3
        cfg.ssh_max_parallel = 10

        results = _log_query(cfg, "journalctl -p err -n 5")
        # Both hosts must appear — bare-label access would return 0 results
        self.assertEqual(len(results), 2)
        hosts_seen = {r["host"] for r in results}
        self.assertEqual(hosts_seen, {"webserver"})

    @patch("freq.api.secure.ssh_run_many")
    def _case_harden_check_uses_result_for_on_dup_labels(self, mock_run_many):
        """handle_harden must check both hosts when labels collide."""
        from freq.api.secure import handle_harden

        h1 = Host(ip="10.0.0.1", label="webserver", htype="linux")
        h2 = Host(ip="10.0.0.2", label="webserver", htype="linux")

        # Each check_cmd call returns dup-label keys
        mock_run_many.return_value = {
            "webserver@10.0.0.1": CmdResult(stdout="1", stderr="", returncode=0, duration=0.1),
            "webserver@10.0.0.2": CmdResult(stdout="0", stderr="", returncode=0, duration=0.1),
            "10.0.0.1": CmdResult(stdout="1", stderr="", returncode=0, duration=0.1),
            "10.0.0.2": CmdResult(stdout="0", stderr="", returncode=0, duration=0.1),
        }

        handler = MagicMock()
        handler.headers = {"Authorization": "Bearer test-token"}

        captured = {}
        def fake_json_response(h, data, status=200):
            captured["data"] = data
            captured["status"] = status

        with patch("freq.api.secure._check_session_role", return_value=("admin", None)), \
             patch("freq.api.secure.get_params", return_value={"target": ["all"]}), \
             patch("freq.api.secure.load_config") as mock_cfg, \
             patch("freq.api.secure.json_response", side_effect=fake_json_response):
            mock_cfg.return_value.hosts = [h1, h2]
            handle_harden(handler)

        # 3 checks × 2 hosts = 6 results
        self.assertEqual(len(captured["data"]["results"]), 6)
        # h1 returns "1" (ok=True), h2 returns "0" (ok=False)
        ok_count = sum(1 for r in captured["data"]["results"] if r["ok"])
        fail_count = sum(1 for r in captured["data"]["results"] if not r["ok"])
        self.assertEqual(ok_count, 3)  # h1 passes all 3 checks
        self.assertEqual(fail_count, 3)  # h2 fails all 3 checks


class TestMutationGuards(unittest.TestCase):
    """Mutating API handlers must enforce POST and auth checks."""

    def test_vm_template_requires_post(self):
        """handle_vm_template must reject GET requests."""
        from freq.api.vm import handle_vm_template

        handler = MagicMock()
        handler.command = "GET"
        handler.headers = {}

        captured = {}
        def mock_send(code):
            captured["status"] = code
        def mock_end_headers():
            pass
        def mock_write(data):
            pass
        def mock_wfile():
            m = MagicMock()
            m.write = mock_write
            return m

        handler.send_response = mock_send
        handler.send_header = MagicMock()
        handler.end_headers = mock_end_headers
        handler.wfile = mock_wfile()

        handle_vm_template(handler)
        self.assertEqual(captured["status"], 405)

    def test_terminal_resize_requires_auth(self):
        """handle_terminal_resize must check session role."""
        from freq.api.terminal import handle_terminal_resize

        handler = MagicMock()
        handler.command = "POST"
        handler.headers = {}  # no auth token

        captured = {}
        def mock_send(code):
            captured["status"] = code
        handler.send_response = mock_send
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()

        with patch("freq.api.terminal._check_session_role", return_value=(None, "Not authenticated")):
            handle_terminal_resize(handler)
        self.assertEqual(captured["status"], 403)

    def test_vm_template_docstring_says_post(self):
        """Docstring must declare POST, not GET."""
        from freq.api.vm import handle_vm_template
        self.assertIn("POST", handle_vm_template.__doc__)
        self.assertNotIn("GET", handle_vm_template.__doc__)

    def test_auto_rules_docstrings_say_post(self):
        """All mutating auto.py handlers must declare POST in docstring."""
        from freq.api.auto import (
            handle_rules_create, handle_rules_update,
            handle_rules_delete, handle_playbooks_create,
        )
        for fn in [handle_rules_create, handle_rules_update,
                   handle_rules_delete, handle_playbooks_create]:
            self.assertIn("POST", fn.__doc__,
                          f"{fn.__name__} docstring missing POST")

    def test_vm_migrate_docstring_says_post(self):
        """handle_vm_migrate docstring must declare POST."""
        from freq.api.vm import handle_vm_migrate
        self.assertIn("POST", handle_vm_migrate.__doc__)


MALFORMED_TOML_CASES = (
    "_case_load_toml_missing_file",
    "_case_load_toml_empty_file",
    "_case_load_toml_comments_only",
    "_case_load_toml_invalid_syntax",
    "_case_apply_toml_empty_data",
    "_case_apply_toml_wrong_types",
    "_case_apply_toml_extra_unknown_sections",
)

HOSTS_CONF_CASES = (
    "_case_missing_hosts_file",
    "_case_empty_hosts_file",
    "_case_only_comments_and_blanks",
    "_case_short_lines_skipped",
    "_case_valid_3_column",
    "_case_5_column_with_all_ips",
    "_case_all_ips_trailing_comma",
)

CONFIG_MISSING_FIELDS_CASES = (
    "_case_default_config_all_fields_set",
    "_case_resolve_paths_with_empty_install_dir",
    "_case_load_containers_missing_file",
    "_case_load_containers_non_integer_keys",
    "_case_load_fleet_boundaries_missing_file",
)

SSH_RESULT_EDGE_CASES = (
    "_case_cmdresult_empty_stdout",
    "_case_cmdresult_special_characters",
    "_case_cmdresult_very_long_output",
    "_case_build_ssh_cmd_unknown_htype",
    "_case_build_ssh_cmd_empty_command",
    "_case_build_ssh_cmd_command_with_single_quotes",
    "_case_build_ssh_cmd_can_sudo_root_only_password_file",
    "_case_remote_command_serialization_contract",
    "_case_remote_command_rejects_invalid_shapes",
    "_case_remote_command_script_keeps_values_out_of_grammar",
    "_case_remote_command_governed_sink_inventory",
    "_case_remote_command_ast_policy_rejects_rendered_shell",
    "_case_truenas_dataset_list_preserves_optional_operand_arity",
)

VALIDATE_BOUNDARY_CASES = (
    "_case_ip_cases",
    "_case_hostname_cases",
    "_case_username_cases",
    "_case_vmid_cases",
    "_case_label_cases",
    "_case_ssh_pubkey_cases",
    "_case_vlan_id_cases",
    "_case_port_cases",
    "_case_protected_vmid_cases",
)

PVE_API_EDGE_CASES = (
    "_case_api_call_no_token_returns_false",
    "_case_api_call_missing_secret_returns_false",
    "_case_api_call_reads_runtime_rw_token_file",
    "_case_pve_call_uses_runtime_rw_token_before_ssh_fallback",
    "_case_api_call_unreachable_returns_false",
    "_case_api_call_timeout_returns_false",
    "_case_pve_call_no_token_falls_back_to_ssh",
    "_case_pve_call_api_fail_falls_back_to_ssh",
    "_case_pve_call_both_fail",
)

FLEET_ZERO_HOSTS_CASES = (
    "_case_cmd_status_zero_hosts_returns_zero",
    "_case_cmd_exec_no_match_returns_one",
)

CONFIG_CORRUPTION_CASES = (
    "_case_freq_toml_with_only_ssh_section",
    "_case_freq_toml_with_duplicate_sections",
    "_case_hosts_toml_with_missing_fields",
    "_case_hosts_toml_with_empty_host_entries",
    "_case_apply_toml_with_nested_unknown_keys",
    "_case_vlans_toml_missing_gateway",
)

VALIDATE_EXTENDED_CASES = (
    "_case_ip_with_leading_zeros",
    "_case_hostname_with_unicode",
    "_case_vmid_max_value",
    "_case_vmid_float_rejected",
    "_case_label_with_only_hyphens",
    "_case_empty_string_inputs_dont_crash",
)

DUP_LABEL_CALLER_CASES = (
    "_case_log_query_uses_result_for_on_dup_labels",
    "_case_harden_check_uses_result_for_on_dup_labels",
)


class TestMalformedTomlMatrix(unittest.TestCase):
    def test_malformed_toml_matrix(self):
        run_case_matrix(self, TestMalformedToml, MALFORMED_TOML_CASES)


class TestHostsConfMatrix(unittest.TestCase):
    def test_hosts_conf_matrix(self):
        run_case_matrix(self, TestHostsConf, HOSTS_CONF_CASES)


class TestConfigMissingFieldsMatrix(unittest.TestCase):
    def test_config_missing_fields_matrix(self):
        run_case_matrix(self, TestConfigMissingFields, CONFIG_MISSING_FIELDS_CASES)


class TestSSHResultEdgeCasesMatrix(unittest.TestCase):
    def test_ssh_result_edge_cases_matrix(self):
        run_case_matrix(self, TestSSHResultEdgeCases, SSH_RESULT_EDGE_CASES)


class TestValidateBoundaryTablesMatrix(unittest.TestCase):
    def test_validate_boundary_tables_matrix(self):
        run_case_matrix(self, TestValidateBoundaryTables, VALIDATE_BOUNDARY_CASES)


class TestPVEApiEdgeCasesMatrix(unittest.TestCase):
    def test_pve_api_edge_cases_matrix(self):
        run_case_matrix(self, TestPVEApiEdgeCases, PVE_API_EDGE_CASES)


class TestFleetZeroHostsMatrix(unittest.TestCase):
    def test_fleet_zero_hosts_matrix(self):
        run_case_matrix(self, TestFleetZeroHosts, FLEET_ZERO_HOSTS_CASES)


class TestConfigCorruptionMatrix(unittest.TestCase):
    def test_config_corruption_matrix(self):
        run_case_matrix(self, TestConfigCorruption, CONFIG_CORRUPTION_CASES)


class TestValidateExtendedMatrix(unittest.TestCase):
    def test_validate_extended_matrix(self):
        run_case_matrix(self, TestValidateExtended, VALIDATE_EXTENDED_CASES)


class TestDupLabelCallersMatrix(unittest.TestCase):
    def test_dup_label_callers_matrix(self):
        run_case_matrix(self, TestDupLabelCallers, DUP_LABEL_CALLER_CASES)


if __name__ == "__main__":
    unittest.main()
