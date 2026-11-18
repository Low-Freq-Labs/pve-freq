"""Portable bootstrap/service identity and shipped-literal owners.

The bootstrap login is operator input.  Product code may not know one site's
login name, and the managed runtime account must be valid, non-root, and
different from the effective bootstrap login.  Tests construct the forbidden
site literal from fragments so the shipped-byte owner needs no self-exemption.
"""
import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent


class TestIsManagedServiceAccountName(unittest.TestCase):
    """F3-3: portable managed-account validation."""

    def test_service_name_equal_to_actual_bootstrap_is_rejected(self):
        from freq.core.config import is_managed_service_account_name
        site_login = "freq" + "-ops"
        self.assertFalse(
            is_managed_service_account_name(site_login, bootstrap_user=site_login)
        )
        self.assertTrue(
            is_managed_service_account_name("svc-portable", bootstrap_user=site_login)
        )

    def test_freq_admin_is_accepted(self):
        from freq.core.config import is_managed_service_account_name
        self.assertTrue(is_managed_service_account_name("freq-admin", bootstrap_user="root"))

    def test_arbitrary_user_chosen_name_is_accepted(self):
        from freq.core.config import is_managed_service_account_name
        self.assertTrue(is_managed_service_account_name("operator", bootstrap_user="installer"))
        self.assertTrue(is_managed_service_account_name("svc-pve", bootstrap_user="root"))

    def test_empty_or_none_is_rejected(self):
        from freq.core.config import is_managed_service_account_name
        self.assertFalse(is_managed_service_account_name(""))
        self.assertFalse(is_managed_service_account_name(None))
        self.assertFalse(is_managed_service_account_name("Bad Name"))

    def test_no_site_specific_reserved_set_and_root_is_rejected(self):
        from freq.core import config

        self.assertFalse(hasattr(config, "RESERVED_SERVICE_ACCOUNT_NAMES"))
        self.assertFalse(config.is_managed_service_account_name("root"))
        self.assertFalse(config.is_managed_service_account_name("pve-freq-setup"))


class TestConfigLoadRejectsReservedSvcName(unittest.TestCase):
    """F3-4: absence defaults once; explicit invalid state stays visible."""

    def test_explicit_empty_service_account_remains_invalid_live_state(self):
        from freq.core.config import (
            FreqConfig,
            _apply_toml,
            validated_runtime_service_account,
        )

        cfg = FreqConfig()
        # Sanity: default is freq-admin
        self.assertEqual(cfg.ssh_service_account, "freq-admin")

        _apply_toml(cfg, {"ssh": {"service_account": ""}})
        self.assertEqual(cfg.ssh_service_account, "")
        with self.assertRaisesRegex(ValueError, "ssh.service_account"):
            validated_runtime_service_account(cfg)

    def test_freq_toml_with_valid_name_passes_through(self):
        from freq.core.config import FreqConfig, _apply_toml

        cfg = FreqConfig()
        toml_data = {
            "ssh": {"service_account": "operator"},
            "fleet": {"operator_exclude_labels": [" Control_Host ", "edge"]},
        }
        captured = io.StringIO()
        with redirect_stderr(captured):
            _apply_toml(cfg, toml_data)

        self.assertEqual(cfg.ssh_service_account, "operator")
        self.assertEqual(cfg.operator_exclude_labels, ["control-host", "edge"])
        self.assertEqual(captured.getvalue(), "")

    def test_freq_toml_with_no_service_account_uses_default(self):
        from freq.core.config import FreqConfig, _apply_toml

        cfg = FreqConfig()
        _apply_toml(cfg, {})
        self.assertEqual(cfg.ssh_service_account, "freq-admin")
        from freq.core.config import validated_runtime_service_account
        self.assertEqual(validated_runtime_service_account(cfg), "freq-admin")

    def test_operator_exclude_labels_persist_and_round_trip(self):
        """F3-6: explicit site policy survives the product config writer."""
        from freq.core.config import FreqConfig, _apply_toml, load_toml
        from freq.modules.init_cmd import _update_toml

        with tempfile.TemporaryDirectory() as root:
            cfg = FreqConfig()
            cfg.conf_dir = root
            path = os.path.join(root, "freq.toml")
            with open(path, "w") as handle:
                handle.write("[fleet]\noperator_exclude_labels = []\n")
            _update_toml(
                cfg,
                "fleet",
                "operator_exclude_labels",
                [" Control_Host ", "edge"],
            )
            persisted = load_toml(path)

        loaded = FreqConfig()
        _apply_toml(loaded, persisted)
        self.assertEqual(loaded.operator_exclude_labels, ["control-host", "edge"])


class TestPhase3RejectsReservedSvcName(unittest.TestCase):
    """Interactive/headless paths compare against their actual bootstrap user.

    The Phase 3 rejection runs inside an interactive flow that calls
    _input() and _read_password(). Mocking those for a live test is
    fragile; static source pins catch the rejection logic at the
    location it must appear.
    """

    def _validator_source(self):
        import inspect

        from freq.modules.init_cmd import _validate_service_account_choice
        return inspect.getsource(_validate_service_account_choice)

    def _phase3_source(self):
        import inspect

        from freq.modules.init_cmd import _phase_service_account
        return inspect.getsource(_phase_service_account)

    def test_phase3_imports_validator(self):
        src = self._validator_source()
        self.assertIn("from freq.core.config import", src)
        self.assertIn(
            "is_managed_service_account_name",
            src,
            "The shared service-account validator must import the canonical validator from config.py",
        )

    def test_phase3_calls_validator_after_username_format_check(self):
        src = self._validator_source()
        # The validator call must appear in the function body.
        self.assertIn(
            "is_managed_service_account_name(svc_name, bootstrap_user=bootstrap_user)",
            src,
            "The shared service-account validator must call is_managed_service_account_name on svc_name",
        )

    def test_phase3_fails_before_useradd_on_reserved_name(self):
        """The validator call must appear BEFORE the useradd/sudoers writes.

        If the rejection happens after useradd, the bootstrap account
        gets clobbered before init can refuse — defeats the purpose.
        """
        src = self._phase3_source()
        # Strip Python comment lines so the keyword search hits real code,
        # not the docstring/comment that explains what we're protecting against
        # (which legitimately mentions chpasswd/useradd/sudoers).
        code_lines = []
        for line in src.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                code_lines.append("")  # placeholder so line numbers stay stable
            else:
                code_lines.append(line)
        code = "\n".join(code_lines)

        validator_idx = code.find("_validate_service_account_choice(svc_name, ctx.get(\"bootstrap_user\"))")
        useradd_idx = code.find('"useradd"')
        chpasswd_idx = code.find("/usr/sbin/chpasswd")
        sudoers_idx = code.find("_setup_sudoers(svc_name)")
        self.assertNotEqual(validator_idx, -1, "Phase 3 must call the shared validator")

        for label, idx in [("useradd", useradd_idx), ("chpasswd", chpasswd_idx), ("_setup_sudoers", sudoers_idx)]:
            if idx == -1:
                continue
            self.assertLess(
                validator_idx,
                idx,
                f"_validate_service_account_choice() must run BEFORE {label} "
                f"so a reserved name is rejected before any write to the "
                f"bootstrap account",
            )

    def test_phase3_returns_1_on_reserved_name(self):
        """The rejection branch must `return 1` so init aborts cleanly."""
        src = self._phase3_source()
        # Look for the rejection block — it should mention reserved + return 1.
        match = re.search(
            r'if not _validate_service_account_choice\(svc_name, ctx\.get\("bootstrap_user"\)\):.*?return 1',
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "Phase 3 must return 1 when svc_name is reserved",
        )

    def test_phase3_error_message_cites_identity_contract(self):
        src = self._validator_source()
        self.assertIn("must differ from bootstrap", src)
        self.assertNotIn("RESERVED_SERVICE_ACCOUNT_NAMES", src)

    def test_headless_init_validates_cli_service_account_before_local_account(self):
        import inspect

        from freq.modules.init_cmd import _init_headless

        src = inspect.getsource(_init_headless)
        svc_idx = src.find('getattr(args, "service_account"')
        validator_idx = src.find("_validate_service_account_choice(svc_name, bootstrap_user)")
        ctx_idx = src.find('"svc_name": svc_name')
        phase3_idx = src.find("_headless_local_account(cfg, ctx)")
        self.assertNotEqual(svc_idx, -1, "headless init must read --service-account")
        self.assertNotEqual(validator_idx, -1, "headless init must validate --service-account")
        self.assertLess(svc_idx, validator_idx)
        self.assertLess(validator_idx, ctx_idx)
        self.assertLess(ctx_idx, phase3_idx)

    def test_console_and_dry_run_copy_use_actual_bootstrap_role(self):
        """F3-2: backend operator copy is derived or identity-neutral."""
        import inspect

        from freq.modules.init_cmd import _init_dry_run, _phase_service_account

        site_login = "freq" + "-ops"
        phase_source = inspect.getsource(_phase_service_account)
        dry_run_source = inspect.getsource(_init_dry_run)
        self.assertNotIn(site_login, phase_source.lower())
        self.assertNotIn(site_login, dry_run_source.lower())
        self.assertIn('ctx.get("bootstrap_user"', phase_source)


class TestInstallShRejectsReservedSvcName(unittest.TestCase):
    """Installer chooses only actual caller/root and has no site-name case."""

    def test_install_sh_warns_and_falls_back_on_freq_ops(self):
        with open(os.path.join(REPO_ROOT, "install.sh")) as f:
            src = f.read()

        # Extract detect_service_account body
        detect_match = re.search(
            r'detect_service_account\(\)\s*\{(.*?)^\}',
            src,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(detect_match, "detect_service_account must exist")
        body = detect_match.group(1)

        forbidden = "freq" + "-ops"
        self.assertNotIn(forbidden, body)
        self.assertIn('"root"', body)

    def test_install_sh_default_is_freq_admin(self):
        with open(os.path.join(REPO_ROOT, "install.sh")) as f:
            src = f.read()
        self.assertIn('local svc_user="freq-admin"', src)
        setup = re.search(r'detect_setup_account\(\)\s*\{(.*?)^\}', src, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(setup)
        self.assertNotIn("freq" + "-ops", setup.group(1))
        self.assertNotIn("SUDO_USER", setup.group(1))
        self.assertIn('"$SETUP_ACCOUNT"', setup.group(1))
        self.assertIn("useradd --system", setup.group(1))


class TestNoShippedSiteIdentityLiterals(unittest.TestCase):
    """F3-5: shipped bytes have an empty site-identity allowlist.

    Identity-literal policy excludes docs because the identity contract must
    describe historical/site identity.  Path-teaching policy is separate and
    includes docs/help because those surfaces must teach container paths.
    """

    @staticmethod
    def _scan(blobs, forbidden):
        if not blobs:
            raise AssertionError("shipped-byte inventory must not be empty")
        violations = []
        for name, payload in blobs:
            lowered = payload.lower()
            for needle in forbidden:
                if needle.encode() in lowered:
                    violations.append(f"{name}:{needle}")
        return violations

    def test_no_site_identity_literals_in_shipped_product_bytes(self):
        forbidden = (("freq" + "-ops"), ("ne" + "xus"))
        shipped = [
            path
            for path in (REPO_ROOT / "freq").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        ]
        shipped.append(REPO_ROOT / "install.sh")
        self.assertGreater(len(shipped), 50, "shipped-byte inventory unexpectedly collapsed")
        blobs = [(path.relative_to(REPO_ROOT).as_posix(), path.read_bytes()) for path in shipped]
        violations = self._scan(blobs, forbidden)
        self.assertEqual(violations, [])

    def test_shipped_literal_scanner_detects_constructed_positive_fixture(self):
        forbidden = (("freq" + "-ops"), ("ne" + "xus"))
        positive = b"portable prefix " + forbidden[0].encode() + b" portable suffix"
        self.assertEqual(
            self._scan([("constructed-positive", positive)], forbidden),
            ["constructed-positive:" + forbidden[0]],
        )
        with self.assertRaisesRegex(AssertionError, "must not be empty"):
            self._scan([], forbidden)


if __name__ == "__main__":
    unittest.main()
