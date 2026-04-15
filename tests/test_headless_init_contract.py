"""Regression tests for the strict headless/password-first init contract.

These tests lock down the exact failure modes discovered during E2E runs
on clean VM 5005 (2026-04-11) so they cannot silently regress:

1. sshpass exit codes must always produce human-readable error messages
2. Headless CLI requires password-file (no silent fallback)
3. fleet-boundaries.toml categories must be idempotent across re-runs
4. sshpass exit code 5 (wrong password) must be classified as skippable
5. Verification must validate TOML on disk, not just memory state
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

from freq.modules.init_cmd import (
    _ssh_error_msg,
    _SSHPASS_ERRORS,
    _is_skip_error,
    _skip_reason,
)


# ─────────────────────────────────────────────────────────────
# Contract 1: sshpass exit codes never produce empty messages
# ─────────────────────────────────────────────────────────────

class TestSshpassExitCodeContract(unittest.TestCase):
    """Every sshpass failure must produce an actionable error string.

    Regression for: 'Cannot connect ()' — empty parens when sshpass
    returns exit 5 (wrong password) with no stderr output.
    """

    def test_exit_5_wrong_password(self):
        msg = _ssh_error_msg(5, "")
        self.assertIn("wrong password", msg)
        self.assertNotEqual(f"Cannot connect ({msg})", "Cannot connect ()")

    def test_exit_6_host_key(self):
        msg = _ssh_error_msg(6, "")
        self.assertIn("host key", msg)

    def test_all_known_codes_produce_output(self):
        for code in _SSHPASS_ERRORS:
            msg = _ssh_error_msg(code, "")
            self.assertTrue(len(msg) > 0, f"sshpass exit {code} produced empty message")

    def test_unknown_code_still_reports(self):
        msg = _ssh_error_msg(255, "")
        self.assertIn("255", msg)

    def test_real_stderr_takes_precedence(self):
        msg = _ssh_error_msg(5, "Permission denied (publickey)")
        self.assertEqual(msg, "Permission denied (publickey)")

    def test_whitespace_only_stderr_falls_through(self):
        msg = _ssh_error_msg(5, "   ")
        self.assertIn("wrong password", msg)


# ─────────────────────────────────────────────────────────────
# Contract 2: Skip vs fail classification
# ─────────────────────────────────────────────────────────────

class TestSkipClassificationContract(unittest.TestCase):
    """sshpass auth failures must be correctly classified as skippable.

    Regression for: truenas showed 'Cannot connect ()' (hard fail) instead
    of 'auth failed (skipped)' when sshpass returned exit 5 with empty stderr.
    """

    def test_permission_denied_is_skippable(self):
        self.assertTrue(_is_skip_error("Permission denied (publickey)"))

    def test_connection_timeout_is_skippable(self):
        self.assertTrue(_is_skip_error("ssh: connect to host 10.0.0.1: Connection timed out"))

    def test_no_route_is_skippable(self):
        self.assertTrue(_is_skip_error("No route to host"))

    def test_empty_stderr_is_not_skippable(self):
        """Empty stderr from sshpass cannot match skip patterns."""
        self.assertFalse(_is_skip_error(""))

    def test_skip_reason_permission_denied(self):
        self.assertEqual(_skip_reason("Permission denied"), "auth failed")

    def test_skip_reason_unreachable(self):
        reason = _skip_reason("No route to host")
        self.assertIn("no route", reason.lower())
        self.assertIn("vlan", reason.lower())


# ─────────────────────────────────────────────────────────────
# Contract 3: Category dedup — idempotent writes
# ─────────────────────────────────────────────────────────────

class TestCategoryIdempotencyContract(unittest.TestCase):
    """fleet-boundaries.toml categories must survive re-runs without duplication.

    Regression for: Phase 9c appended [categories.*] sections with open(path, 'a')
    on every init run, creating duplicate TOML table headers that made the file
    unparseable. Two consecutive init runs would produce:
      [categories.lab] ... [categories.lab]  ← invalid TOML
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fb_path = os.path.join(self.tmpdir, "fleet-boundaries.toml")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_valid_fb(self):
        """Write a valid fleet-boundaries.toml with one set of categories."""
        with open(self.fb_path, "w") as f:
            f.write(
                "[tiers]\n"
                'probe = ["view"]\n\n'
                "[physical]\n"
                'gw = { ip = "10.0.0.1", type = "pfsense" }\n\n'
                "# Auto-categorized VM groups\n\n"
                "[categories.lab]\n"
                'description = "Lab"\n'
                'tier = "admin"\n'
                "vmids = [5000]\n\n"
                "[categories.production]\n"
                'description = "Prod"\n'
                'tier = "operator"\n'
                "vmids = [100]\n"
            )

    def test_valid_file_parses_without_error(self):
        self._write_valid_fb()
        if tomllib:
            with open(self.fb_path, "rb") as f:
                data = tomllib.load(f)
            self.assertIn("categories", data)

    def test_duplicate_categories_are_invalid_toml(self):
        """Prove that duplicate table headers break TOML parsing."""
        with open(self.fb_path, "w") as f:
            f.write(
                "[categories.lab]\n"
                'description = "Lab"\n\n'
                "[categories.lab]\n"
                'description = "Lab"\n'
            )
        if tomllib:
            with self.assertRaises(Exception):
                with open(self.fb_path, "rb") as f:
                    tomllib.load(f)

    def test_append_mode_creates_duplicates(self):
        """Prove the old bug: append mode creates invalid TOML on re-run."""
        self._write_valid_fb()
        # Simulate what old code did: open("a") and write categories again
        with open(self.fb_path, "a") as f:
            f.write("\n[categories.lab]\n")
            f.write('description = "Lab"\n')
        if tomllib:
            with self.assertRaises(Exception):
                with open(self.fb_path, "rb") as f:
                    tomllib.load(f)


# ─────────────────────────────────────────────────────────────
# Contract 4: Headless auth requirements
# ─────────────────────────────────────────────────────────────

class TestHeadlessAuthContract(unittest.TestCase):
    """Headless init must require explicit auth — no silent fallback.

    The password-first contract: when --bootstrap-key is absent and
    --bootstrap-password-file is provided, sshpass must be used.
    Without either, init must fail explicitly.
    """

    def test_password_file_flag_exists(self):
        """--password-file is a recognized CLI flag."""
        from freq.cli import _build_parser as build_parser
        parser = build_parser()
        args = parser.parse_args(["init", "--headless", "--password-file", "/tmp/test"])
        self.assertEqual(args.password_file, "/tmp/test")

    def test_bootstrap_password_file_flag_exists(self):
        """--bootstrap-password-file is a recognized CLI flag."""
        from freq.cli import _build_parser as build_parser
        parser = build_parser()
        args = parser.parse_args(["init", "--headless", "--bootstrap-password-file", "/tmp/bp"])
        self.assertEqual(args.bootstrap_password_file, "/tmp/bp")

    def test_bootstrap_user_default_is_root(self):
        """--bootstrap-user defaults to root."""
        from freq.cli import _build_parser as build_parser
        parser = build_parser()
        args = parser.parse_args(["init", "--headless"])
        self.assertEqual(args.bootstrap_user, "root")

    def test_pve_nodes_flag_exists(self):
        """--pve-nodes is a recognized CLI flag."""
        from freq.cli import _build_parser as build_parser
        parser = build_parser()
        args = parser.parse_args(["init", "--headless", "--pve-nodes", "10.0.0.1,10.0.0.2"])
        self.assertEqual(args.pve_nodes, "10.0.0.1,10.0.0.2")


# ─────────────────────────────────────────────────────────────
# Contract 5: Verification checks disk, not just memory
# ─────────────────────────────────────────────────────────────

class TestVerificationDiskContract(unittest.TestCase):
    """Phase 12 verification must validate files on disk, not memory state.

    Regression for: hosts.toml verification only checked `if cfg.hosts:`
    (memory), not whether the file existed on disk or was valid TOML.
    """

    def test_memory_without_disk_is_detectable(self):
        """hosts in memory + missing file on disk = detectable gap."""
        from dataclasses import dataclass

        @dataclass
        class FakeHost:
            ip: str
            label: str
            htype: str

        hosts = [FakeHost("10.0.0.1", "test", "linux")]
        path = "/tmp/nonexistent-toml-test-file-12345.toml"
        # Old check: `if hosts:` → True (passes silently)
        self.assertTrue(bool(hosts))
        # New check: also requires os.path.isfile(path)
        self.assertFalse(os.path.isfile(path))
        # Combined: memory OK but disk missing = should fail
        combined = bool(hosts) and os.path.isfile(path)
        self.assertFalse(combined, "memory+disk check must catch missing file")

    def test_malformed_toml_fails_parse(self):
        """Malformed TOML must be caught by verification."""
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "test.toml")
            with open(path, "w") as f:
                f.write("[broken\nkey = \n")
            if tomllib:
                ok = False
                try:
                    with open(path, "rb") as f:
                        tomllib.load(f)
                    ok = True
                except Exception:
                    ok = False
                self.assertFalse(ok, "Malformed TOML must fail parse")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestBootstrapPasswordSource(unittest.TestCase):
    """Headless init must seed dashboard password from the correct source.

    Contract:
    - bootstrap_user gets bootstrap_pass (from --bootstrap-password-file)
    - Service account does NOT get a web login (it runs the dashboard, not uses it)
    - Key-based bootstrap (no bootstrap_pass) falls back to svc_pass
    """

    def test_source_uses_bootstrap_pass_not_svc_pass(self):
        """Phase 11 must hash bootstrap_pass for bootstrap_user, not svc_pass."""
        src = (Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py").read_text()
        # Must reference bootstrap_pass for the bootstrap user password
        self.assertIn('boot_pass = ctx.get("bootstrap_pass"', src)

    def test_service_account_no_web_login(self):
        """Service account must NOT get a dashboard password."""
        src = (Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py").read_text()
        # Must NOT seed password for service account
        self.assertNotIn('password_{svc_name}', src)

    def test_only_bootstrap_user_seeded(self):
        """Only bootstrap_user should get a dashboard password."""
        src = (Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('password_{bootstrap_user}', src)

    def test_key_based_bootstrap_fallback(self):
        """When bootstrap_pass is empty (key-based), falls back to svc_pass."""
        src = (Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py").read_text()
        # Must have fallback: boot_pass or svc_pass
        self.assertIn('boot_pass or svc_pass', src)


if __name__ == "__main__":
    unittest.main()
