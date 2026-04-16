"""Tests for the RBAC bootstrap and PVE token drift doctor probes.

 tasks 2 and 3: the two new doctor probes
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

    def test_fail_when_no_non_service_admin(self):
        """Only service account as admin → fail (no human can log in).

        upgraded from warn(2)
        to fail(1). No non-service admin means no human can log into the
        web dashboard — this is a real RBAC failure, not a warning.
        """
        from freq.core.doctor import _check_rbac_bootstrap

        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "roles.conf"), "freq-admin:admin\n")
            _write(os.path.join(d, "users.conf"), "freq-admin admin\n")
            cfg = _make_cfg(d, svc_account="freq-admin")
            result = _check_rbac_bootstrap(cfg)
            self.assertEqual(result, 1, "No non-service admin must fail, not warn")

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
    """The PVE token drift probe must iterate the runtime RW token across
    every configured PVE node and report per-node pass/fail.

    the doctor probe checks ONLY
    the runtime RW token now. The legacy RO token at
    /etc/freq/credentials/pve-token (PVE_TOKEN_ID=... format) was a
    infrastructure-only construct and was pulled out of the product
    runtime doctor surface — keeping it conflated two distinct trust
    roots and trained operators to ignore "ro token unreadable" warnings.
    """

    def test_pass_when_no_pve_nodes(self):
        """No PVE nodes configured → pass trivially (nothing to drift)."""
        from freq.core.doctor import _check_pve_token_drift

        cfg = _make_cfg("/tmp", pve_nodes=[])
        result = _check_pve_token_drift(cfg)
        self.assertEqual(result, 0)

    def test_warn_when_rw_credential_unreadable(self):
        """PVE nodes exist but RW token file unreadable → warn."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1"])
        with patch.object(doctor, "_read_credential_text", return_value=""):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 2)

    def test_pass_when_rw_token_valid_on_all_nodes(self):
        """RW token returns 200 on every node → pass."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1", "10.0.0.2"])
        cfg.ssh_service_account = "freq-admin"
        cfg.pve_api_token_id = "freq-admin@pam!freq-rw"

        with patch.object(doctor, "_read_credential_text", return_value="uuid-rw-secret"), \
             patch.object(doctor, "_probe_pve_api_token", return_value=(200, "ok")):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 0)

    def test_fail_when_any_node_rejects_rw_token(self):
        """Any node returning non-200 for the RW token → fail."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1", "10.0.0.2"])
        cfg.ssh_service_account = "freq-admin"
        cfg.pve_api_token_id = "freq-admin@pam!freq-rw"

        def _fake_probe(ip, token_id, token_secret):
            if ip == "10.0.0.2":
                return 401, "invalid token"
            return 200, "ok"

        with patch.object(doctor, "_read_credential_text", return_value="uuid-rw-secret"), \
             patch.object(doctor, "_probe_pve_api_token", side_effect=_fake_probe):
            result = doctor._check_pve_token_drift(cfg)
        self.assertEqual(result, 1)

    def test_iterates_every_node_for_rw_token(self):
        """Probe must call _probe_pve_api_token for every node with the RW token."""
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1", "10.0.0.2", "10.0.0.3"])
        cfg.ssh_service_account = "freq-admin"
        cfg.pve_api_token_id = "freq-admin@pam!freq-rw"

        calls = []

        def _capturing_probe(ip, token_id, token_secret):
            calls.append((ip, token_id))
            return 200, "ok"

        with patch.object(doctor, "_read_credential_text", return_value="uuid-rw-secret"), \
             patch.object(doctor, "_probe_pve_api_token", side_effect=_capturing_probe):
            doctor._check_pve_token_drift(cfg)

        self.assertEqual(len(calls), 3, "1 token × 3 nodes = 3 probe calls")
        ips = sorted({ip for ip, _ in calls})
        self.assertEqual(ips, ["10.0.0.1", "10.0.0.2", "10.0.0.3"])
        token_ids = {tid for _, tid in calls}
        self.assertEqual(
            token_ids,
            {"freq-admin@pam!freq-rw"},
            "Probe must use the svc-account-derived RW token id only — "
            "no legacy freq-ops@pam!freq-ro Jarvis token in product runtime",
        )

    def test_legacy_ro_token_not_probed(self):
        """The Jarvis-legacy RO token at /etc/freq/credentials/pve-token must not be read.

        the RO token concept was
        pulled out of product runtime doctor. _read_credential_text must
        be called only for the RW token path; the RO path is gone.
        """
        from freq.core import doctor

        cfg = _make_cfg("/tmp", pve_nodes=["10.0.0.1"])
        cfg.ssh_service_account = "freq-admin"
        cfg.pve_api_token_id = "freq-admin@pam!freq-rw"

        read_calls = []

        def _capturing_read(path):
            read_calls.append(path)
            return "uuid-rw-secret"

        with patch.object(doctor, "_read_credential_text", side_effect=_capturing_read), \
             patch.object(doctor, "_probe_pve_api_token", return_value=(200, "ok")):
            doctor._check_pve_token_drift(cfg)

        for path in read_calls:
            self.assertNotIn(
                "/etc/freq/credentials/pve-token\"",
                f'"{path}"',
                f"Legacy RO token path must not be read: {path}",
            )
            # The exact RO file path is /etc/freq/credentials/pve-token (no -rw).
            # Distinguish from the RW path /etc/freq/credentials/pve-token-rw.
            self.assertFalse(
                path.endswith("/pve-token"),
                f"Legacy RO token path must not be read: {path}",
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
            _read_credential_text("/nonexistent/path/sample-test-xyz"), ""
        )


if __name__ == "__main__":
    unittest.main()
