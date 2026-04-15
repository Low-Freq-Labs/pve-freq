"""Tests for the RBAC bootstrap and PVE token drift doctor probes.

R-DC01-OPS-SURFACES-20260414A tasks 2 and 3: the two new doctor probes
added under this token pin bootstrap-user consistency across
roles.conf / users.conf / vault and per-node per-token PVE API token
acceptance. These tests pin the probe contracts so the operator-truth
surface they create cannot silently regress.

Both probes return the standard doctor triple: 0 pass, 1 fail, 2 warn.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_cfg(tmpdir, svc_account="freq-admin", pve_nodes=None):
    """Build a minimal FreqConfig stand-in for doctor probes."""
    cfg = MagicMock()
    cfg.conf_dir = tmpdir
    cfg.ssh_service_account = svc_account
    cfg.pve_nodes = pve_nodes or []
    cfg.pve_api_token_id = ""
    cfg.pve_api_token_secret = ""
    return cfg


def _write(path, content):
    with open(path, "w") as f:
        f.write(content)


# ─────────────────────────────────────────────────────────────────────
# _check_rbac_bootstrap — task 2 contract
# ─────────────────────────────────────────────────────────────────────


class TestRbacBootstrapProbe(unittest.TestCase):
    """The RBAC bootstrap probe must pin the triple-surface consistency
    between roles.conf, users.conf, and the vault auth/password_<user>
    entry, and it must surface WHICH surface is drifting when it
    disagrees so the operator can fix the right file.
    """

    def test_warn_when_both_files_missing(self):
        """Pre-init state: no roles.conf, no users.conf → warn, not fail."""
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            cfg = _make_cfg(d)
            result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 2, "Pre-init state must warn, not fail")

    def test_warn_when_no_non_service_admin(self):
        """Only service account as admin → warn (no seat for operator)."""
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "freq-admin:admin\n")
            _write(os.path.join(d, "users.conf"), "freq-admin admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 2)

    def test_warn_when_roles_and_users_disagree(self):
        """admin in roles.conf but not users.conf → warn (disagreement).

        Probe is warn-only from operator context because the vault is
        typically 0600 service-account-owned and hard-failing would be
        wrong when the cause is an expected read restriction.
        """
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "alice:admin\n")
            _write(os.path.join(d, "users.conf"), "bob admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            with patch("freq.modules.vault.vault_get", return_value=""):
                result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 2, "Disagreement between files must warn")

    def test_warn_when_vault_hash_missing(self):
        """Common admin in both files but no vault entry → warn.

        The probe cannot distinguish a genuinely-missing hash from a
        read-permission refusal in operator context, so it warns
        rather than fails.
        """
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "alice:admin\n")
            _write(os.path.join(d, "users.conf"), "alice admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            with patch("freq.modules.vault.vault_get", return_value=""):
                result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 2, "Missing vault hash must warn")

    def test_warn_when_vault_unreadable(self):
        """Vault raises on read → warn (not fail — might be transient)."""
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "alice:admin\n")
            _write(os.path.join(d, "users.conf"), "alice admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            with patch(
                "freq.modules.vault.vault_get",
                side_effect=RuntimeError("vault locked"),
            ):
                result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 2)

    def test_pass_when_everything_consistent(self):
        """roles + users agree + vault hash is PBKDF2 → pass."""
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "alice:admin\n")
            _write(os.path.join(d, "users.conf"), "alice admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            pbkdf2_hash = "a" * 32 + "$" + "b" * 64
            with patch(
                "freq.modules.vault.vault_get", return_value=pbkdf2_hash
            ):
                result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 0)

    def test_pass_with_legacy_sha256_hash(self):
        """64-char SHA256 legacy hash is still accepted (PBKDF2 migration
        happens on successful login, not on a diagnostic read)."""
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "alice:admin\n")
            _write(os.path.join(d, "users.conf"), "alice admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            sha256_hash = "a" * 64
            with patch(
                "freq.modules.vault.vault_get", return_value=sha256_hash
            ):
                result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 0)

    def test_warn_on_unexpected_hash_format(self):
        """Non-PBKDF2, non-SHA256 hash → warn (unexpected format)."""
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "alice:admin\n")
            _write(os.path.join(d, "users.conf"), "alice admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            with patch(
                "freq.modules.vault.vault_get", return_value="short-weird-hash"
            ):
                result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 2)

    def test_service_account_excluded_from_admin_selection(self):
        """Even if the service account is listed as admin in both files,
        it must not be the bootstrap user — that's the F1 web-login rule."""
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(
                os.path.join(d, "roles.conf"),
                "freq-admin:admin\nalice:admin\n",
            )
            _write(
                os.path.join(d, "users.conf"),
                "freq-admin admin\nalice admin\n",
            )
            cfg = _make_cfg(d, svc_account="freq-admin")
            pbkdf2_hash = "a" * 32 + "$" + "b" * 64
            captured = {}

            def _fake_vault_get(cfg_, section, key):
                captured["key"] = key
                return pbkdf2_hash

            with patch("freq.modules.vault.vault_get", side_effect=_fake_vault_get):
                result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 0)
            self.assertEqual(
                captured.get("key"),
                "password_alice",
                "Probe must pick alice (non-service) as the bootstrap user",
            )


# ─────────────────────────────────────────────────────────────────────
# _check_pve_token_drift — task 3 contract
# ─────────────────────────────────────────────────────────────────────


class TestPveTokenDriftProbe(unittest.TestCase):
    """The PVE token drift probe must iterate RO and RW token pairs
    across every configured PVE node and report per-node per-token
    pass/fail so the operator can see exactly which combo drifted.
    """

    def test_pass_when_no_pve_nodes(self):
        """No PVE nodes configured → pass trivially (nothing to drift)."""
        from freq.core.doctor import _check_pve_token_drift

        cfg = _make_cfg("/tmp", pve_nodes=[])
        result = _check_pve_token_drift(cfg)
        self.assertEqual(result, 0)

    def test_warn_when_no_credential_files_readable(self):
        """PVE nodes exist but no token files readable → warn."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1"])
        with patch.object(doctor, "_read_credential_text", return_value=""):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 2)

    def test_pass_when_both_tokens_valid_on_all_nodes(self):
        """RW + RO tokens both return 200 on every node → pass."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1", "10.0.0.2"])
        cfg.pve_api_token_id = "freq-ops@pam!freq-rw"

        def _fake_creds(path):
            if "rw" in path:
                return "uuid-rw-secret"
            return "PVE_TOKEN_ID=freq-ops@pam!freq-ro\nPVE_TOKEN_SECRET=uuid-ro-secret\n"

        with patch.object(doctor, "_read_credential_text", side_effect=_fake_creds), \
             patch.object(doctor, "_probe_pve_api_token", return_value=(200, "ok")):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 0)

    def test_fail_when_any_token_node_combo_fails(self):
        """Any RO/RW token × node combo returning non-200 → fail."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1", "10.0.0.2"])
        cfg.pve_api_token_id = "freq-ops@pam!freq-rw"

        def _fake_creds(path):
            if "rw" in path:
                return "uuid-rw-secret"
            return "PVE_TOKEN_ID=freq-ops@pam!freq-ro\nPVE_TOKEN_SECRET=uuid-ro-secret\n"

        def _fake_probe(ip, token_id, token_secret):
            if ip == "10.0.0.2" and "ro" in token_id:
                return 401, "invalid token"
            return 200, "ok"

        with patch.object(doctor, "_read_credential_text", side_effect=_fake_creds), \
             patch.object(doctor, "_probe_pve_api_token", side_effect=_fake_probe):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 1)

    def test_warn_when_only_one_token_readable_but_valid(self):
        """Only RW readable, RO missing, RW valid → warn (partial coverage)."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1"])
        cfg.pve_api_token_id = "freq-ops@pam!freq-rw"

        def _fake_creds(path):
            if "rw" in path:
                return "uuid-rw-secret"
            return ""

        with patch.object(doctor, "_read_credential_text", side_effect=_fake_creds), \
             patch.object(doctor, "_probe_pve_api_token", return_value=(200, "ok")):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 2)

    def test_warn_on_malformed_ro_token_file(self):
        """RO token file present but missing PVE_TOKEN_ID/SECRET → warn."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1"])
        cfg.pve_api_token_id = "freq-ops@pam!freq-rw"

        def _fake_creds(path):
            if "rw" in path:
                return "uuid-rw-secret"
            return "SOME_OTHER_KEY=value\n"

        with patch.object(doctor, "_read_credential_text", side_effect=_fake_creds), \
             patch.object(doctor, "_probe_pve_api_token", return_value=(200, "ok")):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 2)

    def test_iterates_every_token_node_combo(self):
        """Probe must call _probe_pve_api_token for every token × node pair."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1", "10.0.0.2", "10.0.0.3"])
        cfg.pve_api_token_id = "freq-ops@pam!freq-rw"

        def _fake_creds(path):
            if "rw" in path:
                return "uuid-rw-secret"
            return "PVE_TOKEN_ID=freq-ops@pam!freq-ro\nPVE_TOKEN_SECRET=uuid-ro-secret\n"

        calls = []

        def _capturing_probe(ip, token_id, token_secret):
            calls.append((ip, token_id))
            return 200, "ok"

        with patch.object(doctor, "_read_credential_text", side_effect=_fake_creds), \
             patch.object(doctor, "_probe_pve_api_token", side_effect=_capturing_probe):
            doctor._check_pve_token_drift(cfg)

        self.assertEqual(len(calls), 6, "2 tokens × 3 nodes = 6 probe calls")
        ips = sorted({ip for ip, _ in calls})
        self.assertEqual(ips, ["10.0.0.1", "10.0.0.2", "10.0.0.3"])
        token_ids = sorted({tid for _, tid in calls})
        self.assertEqual(
            token_ids,
            ["freq-ops@pam!freq-ro", "freq-ops@pam!freq-rw"],
            "Probe must hit both RO and RW token ids",
        )


class TestReadCredentialTextHelper(unittest.TestCase):
    """The credential reader helper must try direct read first, then
    fall back to sudo -n cat for service-account-owned 0600 files.
    """

    def test_direct_read_works_when_file_is_readable(self):
        from freq.core.doctor import _read_credential_text

        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("direct-secret\n")
            path = f.name
        try:
            self.assertEqual(_read_credential_text(path), "direct-secret")
        finally:
            os.unlink(path)

    def test_returns_empty_when_missing(self):
        from freq.core.doctor import _read_credential_text

        self.assertEqual(
            _read_credential_text("/nonexistent/path/rick-test-xyz"), ""
        )


if __name__ == "__main__":
    unittest.main()
