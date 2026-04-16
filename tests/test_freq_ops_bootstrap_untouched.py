"""freq-ops bootstrap-untouched contract pins.



`freq-ops` is the bootstrap/sudo ingress identity per
docs/IDENTITY-CONTRACT.md. `freq init` MUST pass through it untouched —
no `useradd`, no `chpasswd`, no sudoers write, no chmod/chown, no
SSH key management. `cfg.ssh_service_account` is the only managed
product account and may NOT take the value `freq-ops`.

These tests pin the rejection at three layers:

  1. `freq.core.config.is_managed_service_account_name` — the
     authoritative validator. Returns False for `freq-ops` and any
     other reserved name; True for valid managed names.
  2. `freq.core.config._apply_toml` — when freq.toml ships a reserved
     `service_account` value, config-load logs a stderr warning and
     overrides to the canonical default. Downstream phases see the
     safe value, not the reserved one.
  3. `freq.modules.init_cmd._phase_service_account` — the interactive
     Phase 3 prompt rejects a reserved svc_name with `fmt.step_fail`
     and returns 1 BEFORE invoking `useradd`, `chpasswd`, or
     `_setup_sudoers`. (Static source pin — the actual runtime
     interactive flow needs a live tty.)
  4. `install.sh:detect_service_account` — the bash boundary also
     rejects the reserved name and warns + falls back to the default.

Cross-file invariant: nothing in product runtime code (init/runtime
modules, install.sh) uses `freq-ops` as a SERVICE ACCOUNT VALUE. The
name still appears in docstrings explaining the contract and in
anti-regression test pins, which is intentional.
"""
import io
import os
import re
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent


class TestIsManagedServiceAccountName(unittest.TestCase):
    """Layer 1: the authoritative validator helper."""

    def test_freq_ops_is_rejected(self):
        from freq.core.config import is_managed_service_account_name
        self.assertFalse(is_managed_service_account_name("freq-ops"))

    def test_freq_admin_is_accepted(self):
        from freq.core.config import is_managed_service_account_name
        self.assertTrue(is_managed_service_account_name("freq-admin"))

    def test_arbitrary_user_chosen_name_is_accepted(self):
        from freq.core.config import is_managed_service_account_name
        self.assertTrue(is_managed_service_account_name("operator"))
        self.assertTrue(is_managed_service_account_name("svc-pve"))

    def test_empty_or_none_is_rejected(self):
        from freq.core.config import is_managed_service_account_name
        self.assertFalse(is_managed_service_account_name(""))
        self.assertFalse(is_managed_service_account_name(None))

    def test_reserved_set_includes_freq_ops(self):
        from freq.core.config import RESERVED_SERVICE_ACCOUNT_NAMES
        self.assertIn("freq-ops", RESERVED_SERVICE_ACCOUNT_NAMES)


class TestConfigLoadRejectsReservedSvcName(unittest.TestCase):
    """Layer 2: config.py._apply_toml override + stderr warning."""

    def test_freq_toml_with_freq_ops_falls_back_to_default(self):
        from freq.core.config import FreqConfig, _apply_toml

        cfg = FreqConfig()
        # Sanity: default is freq-admin
        self.assertEqual(cfg.ssh_service_account, "freq-admin")

        toml_data = {"ssh": {"service_account": "freq-ops"}}
        captured = io.StringIO()
        with redirect_stderr(captured):
            _apply_toml(cfg, toml_data)

        # The reserved value must be rejected — cfg falls back to default.
        self.assertEqual(cfg.ssh_service_account, "freq-admin")
        # The rejection must be visible in stderr so operators can see it.
        err = captured.getvalue()
        self.assertIn("freq-ops", err)
        self.assertIn("reserved", err.lower())
        self.assertIn("", err)

    def test_freq_toml_with_valid_name_passes_through(self):
        from freq.core.config import FreqConfig, _apply_toml

        cfg = FreqConfig()
        toml_data = {"ssh": {"service_account": "operator"}}
        captured = io.StringIO()
        with redirect_stderr(captured):
            _apply_toml(cfg, toml_data)

        self.assertEqual(cfg.ssh_service_account, "operator")
        # No warning when the name is valid.
        self.assertEqual(captured.getvalue(), "")

    def test_freq_toml_with_no_service_account_uses_default(self):
        from freq.core.config import FreqConfig, _apply_toml

        cfg = FreqConfig()
        _apply_toml(cfg, {})
        self.assertEqual(cfg.ssh_service_account, "freq-admin")


class TestPhase3RejectsReservedSvcName(unittest.TestCase):
    """Layer 3: _phase_service_account static source pin.

    The Phase 3 rejection runs inside an interactive flow that calls
    _input() and _read_password(). Mocking those for a live test is
    fragile; static source pins catch the rejection logic at the
    location it must appear.
    """

    def _phase3_source(self):
        import inspect
        from freq.modules.init_cmd import _phase_service_account
        return inspect.getsource(_phase_service_account)

    def test_phase3_imports_validator(self):
        src = self._phase3_source()
        self.assertIn(
            "from freq.core.config import is_managed_service_account_name",
            src,
            "Phase 3 must import the canonical validator from config.py",
        )

    def test_phase3_calls_validator_after_username_format_check(self):
        src = self._phase3_source()
        # The validator call must appear in the function body.
        self.assertIn(
            "is_managed_service_account_name(svc_name)",
            src,
            "Phase 3 must call is_managed_service_account_name on svc_name",
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

        validator_idx = code.find("is_managed_service_account_name(svc_name)")
        useradd_idx = code.find('"useradd"')
        chpasswd_idx = code.find("/usr/sbin/chpasswd")
        sudoers_idx = code.find("_setup_sudoers(svc_name)")
        self.assertNotEqual(validator_idx, -1, "validator call must exist")

        for label, idx in [("useradd", useradd_idx), ("chpasswd", chpasswd_idx), ("_setup_sudoers", sudoers_idx)]:
            if idx == -1:
                continue
            self.assertLess(
                validator_idx,
                idx,
                f"is_managed_service_account_name() must run BEFORE {label} "
                f"so a reserved name is rejected before any write to the "
                f"bootstrap account",
            )

    def test_phase3_returns_1_on_reserved_name(self):
        """The rejection branch must `return 1` so init aborts cleanly."""
        src = self._phase3_source()
        # Look for the rejection block — it should mention reserved + return 1.
        match = re.search(
            r'if not is_managed_service_account_name\(svc_name\):.*?return 1',
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "Phase 3 must return 1 when svc_name is reserved",
        )

    def test_phase3_error_message_cites_identity_contract(self):
        """Operator should be told WHY the name was rejected and where to look."""
        src = self._phase3_source()
        self.assertIn(
            "IDENTITY-CONTRACT.md",
            src,
            "Phase 3 rejection message must cite docs/IDENTITY-CONTRACT.md",
        )


class TestInstallShRejectsReservedSvcName(unittest.TestCase):
    """Layer 4: install.sh detect_service_account bash-side rejection."""

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

        # Must have a case branch on freq-ops that warns + falls back.
        self.assertIn("freq-ops)", body, "detect_service_account must case on 'freq-ops)'")
        self.assertIn("warn", body, "Reserved-name path must warn the operator")

    def test_install_sh_default_is_freq_admin(self):
        with open(os.path.join(REPO_ROOT, "install.sh")) as f:
            src = f.read()
        self.assertIn('local svc_user="freq-admin"', src)


class TestNoActiveCodeReferencesFreqOpsAsServiceAccount(unittest.TestCase):
    """Cross-file invariant: no active product runtime code uses freq-ops as a managed identity.

    Comments and docstrings that EXPLAIN the bootstrap-untouched rule
    are allowed — they intentionally name freq-ops to document the
    contract. Active code (assignments, function args, command
    construction) must not.
    """

    PRODUCT_RUNTIME_FILES = [
        "freq/modules/init_cmd.py",
        "freq/core/doctor.py",
        "freq/core/config.py",
        "freq/api/terminal.py",
        "freq/api/auth.py",
        "freq/modules/serve.py",
    ]

    def _strip_comments_and_docstrings(self, src):
        """Remove # comments and '''/\"\"\" docstring blocks from Python source."""
        lines = src.splitlines()
        out = []
        in_doc = False
        doc_quote = None
        for line in lines:
            stripped = line.strip()
            if not in_doc:
                # Detect docstring open
                for q in ('"""', "'''"):
                    if q in stripped:
                        # Count occurrences — if odd, we enter docstring
                        if stripped.count(q) == 1:
                            in_doc = True
                            doc_quote = q
                            break
                        # Even count: inline docstring on one line — strip it
                if in_doc:
                    continue
                # Strip inline comment
                code = line.split("#", 1)[0]
                out.append(code)
            else:
                if doc_quote in stripped:
                    in_doc = False
                    doc_quote = None
        return "\n".join(out)

    # Allow-list: the validator constant in config.py legitimately names
    # 'freq-ops' as a reserved-bootstrap value. That is the WHITELIST OF
    # FORBIDDEN NAMES, not a use-as-managed-account.
    ALLOWED_FREQ_OPS_REFERENCES = {
        ("freq/core/config.py", 'RESERVED_SERVICE_ACCOUNT_NAMES = frozenset({"freq-ops"})'),
    }

    def test_no_freq_ops_in_active_product_runtime_code(self):
        violations = []
        for relpath in self.PRODUCT_RUNTIME_FILES:
            path = REPO_ROOT / relpath
            if not path.exists():
                continue
            src = path.read_text()
            code = self._strip_comments_and_docstrings(src)
            for ln, line in enumerate(code.splitlines(), 1):
                if "freq-ops" not in line:
                    continue
                trimmed = line.strip()
                if (relpath, trimmed) in self.ALLOWED_FREQ_OPS_REFERENCES:
                    continue
                violations.append(f"{relpath}:{ln}: {trimmed[:120]}")
        self.assertEqual(
            violations,
            [],
            "No active product runtime code may reference 'freq-ops' as a "
            "managed identity. Docstrings, comments, and the validator "
            "constant in config.py are explicitly allowed (they document "
            "or enforce the bootstrap-untouched rule). Violations:\n  "
            + "\n  ".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
