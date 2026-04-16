"""Phase 6 PVE API token bootstrap — product-contract pins.

 + 

Finn declared the PVE API token bootstrap inside `freq init` a required
product contract. These static tests pin the seven contract surfaces
at the source level so future refactors cannot silently drift them back:

  1. Identity creation     — The PVE API user is {cfg.ssh_service_account}@pam
                               (default freq-admin@pam), derived from the
                               configured service account — NOT the legacy
                               freq-ops@pam identity. See
                               .
  2. Token creation         — token name is freq-rw, full token_id is
                               f"{svc_name}@pam!freq-rw"
  3. Role/ACL reconciliation — PVEAuditor + PVEVMUser granted on EVERY
                               init run, not just on user creation
  4. Secret storage         — written to /etc/freq/credentials/pve-token-rw,
                               the same path doctor + tests hardcode
  5. Readability by runtime — owned root:<svc_name>, mode 0640,
                               non-recursive chown (sibling credentials
                               in /etc/freq/credentials/ keep their
                               own ownership model)
  6. Live verification      — /version probed on EVERY cfg.pve_nodes,
                               ctx['api_token_verified'] is True only
                               when all nodes succeed; audit.record
                               reflects success/partial/unverified
                               truthfully instead of always 'success'
  7. Anti-legacy guard      — the phase 6 source must NOT contain the
                               legacy freq-ops@pam identity as a hardcoded
                               token owner, ensuring the svc-account rename
                               cannot silently regress

Why static pins instead of live integration: Phase 6 requires a live
PVE cluster (SSH, pveum, /version reachable). Running it in CI would
need a mocked PVE, which is separate work. The static pins catch the
most common regression — someone refactoring the phase and removing
one of the contract lines — while staying CI-cheap. Integration
coverage lives in the nightly E2E harness on 5005.
"""
import inspect
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent
INIT_CMD = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()


def _phase6_source():
    """Return just the _phase_pve_api_token function body for targeted pins."""
    from freq.modules.init_cmd import _phase_pve_api_token
    return inspect.getsource(_phase_pve_api_token)


class TestPhase6IdentityAndToken(unittest.TestCase):
    """Contract 1+2: identity + token creation derived from svc_name."""

    def test_pve_user_is_derived_from_svc_name(self):
        """Phase 6 must compute pve_user from cfg.ssh_service_account, not hardcode it."""
        src = _phase6_source()
        # The derivation must appear exactly once at the top of the phase.
        self.assertIn('pve_user = f"{svc_name}@pam"', src,
                       "Phase 6 must derive pve_user from svc_name (the configured service account)")
        self.assertIn('full_token_id = f"{pve_user}!{token_name}"', src,
                       "Phase 6 must compose full_token_id from pve_user + token_name")
        self.assertIn('token_name = "freq-rw"', src,
                       "Token role name must be 'freq-rw'")

    def test_creates_pve_user_on_missing(self):
        """When the service-account PVE user is absent, Phase 6 must create it."""
        src = _phase6_source()
        self.assertIn("pveum user add {pve_user}", src,
                       "Phase 6 must create {pve_user} via pveum user add")

    def test_creates_freq_rw_token_on_pve_user(self):
        """Phase 6 must create the freq-rw token on the service-account PVE user."""
        src = _phase6_source()
        self.assertIn(
            "pveum user token add {pve_user} {token_name}",
            src,
            "Phase 6 must create the token via pveum user token add {pve_user} {token_name}",
        )

    def test_token_uses_privsep_0(self):
        """Token creation must use --privsep 0 so ACL derives from user."""
        src = _phase6_source()
        self.assertIn("--privsep 0", src,
                       "Token must inherit user ACL via --privsep 0")

    def test_deletes_and_recreates_on_token_exists(self):
        """If the token already exists, Phase 6 must delete + recreate to obtain the secret."""
        src = _phase6_source()
        self.assertIn(
            "pveum user token remove {pve_user} {token_name}",
            src,
            "Phase 6 must handle 'token already exists' via delete+recreate",
        )

    def test_default_token_id_fallback_uses_full_token_id(self):
        """When pveum output lacks full-tokenid, Phase 6 must fall back to the svc-derived id."""
        src = _phase6_source()
        self.assertIn("token_id = full_token_id", src,
                       "Token ID default must be full_token_id (svc-derived), not a hardcoded string")


class TestPhase6AntiLegacyGuard(unittest.TestCase):
    """Contract guard: the legacy freq-ops@pam identity must not be hardcoded as a token owner.

    the runtime PVE API token
    belongs to cfg.ssh_service_account, not freq-ops@pam. Any hardcoded
    "freq-ops@pam!freq-rw" or "pveum user add freq-ops@pam" pattern in
    the Phase 6 function is a regression — it would mean the svc-account
    rename was silently undone.
    """

    def test_phase6_has_no_hardcoded_legacy_token_id(self):
        """_phase_pve_api_token must not contain 'freq-ops@pam!freq-rw'."""
        src = _phase6_source()
        self.assertNotIn(
            "freq-ops@pam!freq-rw",
            src,
            "Legacy freq-ops@pam!freq-rw must not be hardcoded in Phase 6 — "
            "identity must derive from cfg.ssh_service_account",
        )

    def test_phase6_has_no_hardcoded_legacy_user_add(self):
        """_phase_pve_api_token must not hardcode 'pveum user add freq-ops@pam'."""
        src = _phase6_source()
        self.assertNotIn(
            "pveum user add freq-ops@pam",
            src,
            "Legacy freq-ops@pam user creation must not be hardcoded in Phase 6",
        )

    def test_phase6_has_no_hardcoded_legacy_acl(self):
        """_phase_pve_api_token must not grant PVEAuditor to a hardcoded freq-ops@pam."""
        src = _phase6_source()
        # The specific hardcoded ACL string must not appear.
        self.assertNotIn(
            "--users freq-ops@pam",
            src,
            "Legacy freq-ops@pam ACL target must not be hardcoded in Phase 6",
        )


class TestPhase6RoleReconciliation(unittest.TestCase):
    """Contract 3: role/ACL reconciliation runs EVERY init, not just on user creation."""

    def test_roles_asserted_outside_user_creation_branch(self):
        """PVEAuditor + PVEVMUser grant must NOT be nested inside the 'not user_exists' branch.

        Prior bug: the acl modify call only ran in `if not user_exists:`.
        A manual `pveum acl delete` on the PVE side would silently drift
        and Phase 6 would print 'user already exists' without re-asserting
        the roles. The fix moves the acl modify unconditionally outside
        the if/else so it runs on every init, reconciling the ACL to
        match the contract on each invocation.
        """
        src = _phase6_source()
        # Locate the acl modify line.
        acl_line_match = re.search(
            r'pveum acl modify / --roles PVEAuditor,PVEVMUser --users \{pve_user\}',
            src,
        )
        self.assertIsNotNone(
            acl_line_match,
            "acl modify for PVEAuditor+PVEVMUser on {pve_user} must exist",
        )

        # The acl modify line must NOT be inside an `if not user_exists:` block.
        pre_slice = src[:acl_line_match.start()]
        if_idx = pre_slice.rfind("if not user_exists:")
        else_idx = pre_slice.rfind("else:")
        reconcile_idx = pre_slice.rfind("Reconciling PVE roles")
        self.assertTrue(
            if_idx == -1 or else_idx > if_idx or reconcile_idx > if_idx,
            "PVEAuditor+PVEVMUser acl modify must run outside the 'not user_exists' branch "
            "so existing users get their ACL reconciled on every init",
        )

    def test_roles_contain_pveauditor_and_pvevmuser(self):
        """Role list must contain both PVEAuditor (read) and PVEVMUser (VM mgmt)."""
        src = _phase6_source()
        self.assertIn("PVEAuditor", src)
        self.assertIn("PVEVMUser", src)


class TestPhase6SecretStorage(unittest.TestCase):
    """Contract 4+5: secret storage path + readability by runtime."""

    def test_cred_dir_is_etc_freq_credentials(self):
        """Phase 6 must write the token secret to /etc/freq/credentials/, not a cfg-derived path."""
        src = _phase6_source()
        self.assertIn('cred_dir = "/etc/freq/credentials"', src,
                       "Phase 6 must write to /etc/freq/credentials/ (matches doctor hardcoded reads)")
        self.assertNotIn("os.path.dirname(cfg.conf_dir), \"credentials\"", src,
                          "Old cfg-derived credentials path must not return")

    def test_cred_file_is_pve_token_rw(self):
        """Cred file name must be pve-token-rw (matches doctor._check_pve_token_drift)."""
        src = _phase6_source()
        self.assertIn('"pve-token-rw"', src)

    def test_cred_file_mode_0640(self):
        """Cred file mode must be 0640 (root-owned, svc_name group-readable)."""
        src = _phase6_source()
        self.assertIn("os.chmod(cred_path, 0o640)", src)

    def test_chown_is_not_recursive_on_shared_dir(self):
        """Chown must target the specific file, not recursive on /etc/freq/credentials/."""
        src = _phase6_source()
        self.assertNotIn(
            "_chown(f\"{svc_name}:{svc_name}\", cred_dir, recursive=True)",
            src,
        )
        self.assertIn("_chown(f\"root:{svc_name}\", cred_path)", src)

    def test_dir_ownership_only_on_fresh_create(self):
        """If /etc/freq/credentials/ preexisted, Phase 6 must not rewrite its ownership."""
        src = _phase6_source()
        self.assertIn("cred_dir_preexists = os.path.isdir(cred_dir)", src)
        self.assertIn("if not cred_dir_preexists:", src)


class TestPhase6MultiNodeVerification(unittest.TestCase):
    """Contract 6: live verification across ALL configured nodes, not just the first."""

    def test_verifies_every_node(self):
        """Phase 6 must iterate cfg.pve_nodes and call /version on each."""
        src = _phase6_source()
        verify_idx = src.find("Verifying PVE API token")
        self.assertNotEqual(verify_idx, -1, "verification step must exist")
        verify_block = src[verify_idx:verify_idx + 3000]
        self.assertIn("for node_ip in pve_nodes:", verify_block,
                       "Verification must loop over every pve_nodes entry")

    def test_tracks_verified_and_failed_nodes_separately(self):
        """Verification must accumulate per-node outcomes."""
        src = _phase6_source()
        self.assertIn("verified_nodes = []", src)
        self.assertIn("failed_nodes = []", src)

    def test_api_token_verified_only_on_full_success(self):
        """ctx['api_token_verified'] must be True only when ALL nodes verified."""
        src = _phase6_source()
        match = re.search(
            r'if verified_nodes and not failed_nodes:.*?ctx\["api_token_verified"\] = True',
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "api_token_verified must be True only when verified_nodes is non-empty AND failed_nodes is empty",
        )


class TestPhase6AuditTruth(unittest.TestCase):
    """Contract 6 audit surface: audit.record must reflect real verification state."""

    def test_audit_records_three_outcomes(self):
        """audit.record must distinguish success / partial / unverified outcomes."""
        src = _phase6_source()
        self.assertIn('audit.record(\n            "create_api_token",', src,
                       "audit.record(create_api_token) must use named/multi-line args")
        self.assertIn('"success"', src)
        self.assertIn('"partial"', src)
        self.assertIn('"unverified"', src)

    def test_audit_success_gated_on_full_verification(self):
        """audit.record('success') must be gated on ctx['api_token_verified'] being True."""
        src = _phase6_source()
        match = re.search(
            r'if ctx\["api_token_verified"\]:\s*\n\s*audit\.record\(\s*\n\s*"create_api_token".*?"success"',
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "audit.record('success') must be gated on ctx['api_token_verified'] == True",
        )


class TestPhase6DoctorPathAlignment(unittest.TestCase):
    """Contract cross-check: the path Phase 6 writes must match the path doctor reads."""

    def test_doctor_reads_etc_freq_credentials_rw_token(self):
        """doctor._check_pve_nodes must read from /etc/freq/credentials/pve-token-rw."""
        doctor_src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn('"/etc/freq/credentials/pve-token-rw"', doctor_src,
                       "doctor must read the RW token from /etc/freq/credentials/pve-token-rw")

    def test_init_writes_to_same_path_doctor_reads(self):
        """Init's cred_path and doctor's read path must match exactly."""
        init_src = INIT_CMD
        doctor_src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn('cred_dir = "/etc/freq/credentials"', init_src)
        self.assertIn('"pve-token-rw"', init_src)
        self.assertIn("/etc/freq/credentials/pve-token-rw", doctor_src)

    def test_doctor_fallback_token_id_uses_svc_name(self):
        """doctor's fallback token_id must derive from cfg.ssh_service_account, not freq-ops@pam.

        when freq.toml has no
        api_token_id at all (pre-init install, or stripped config),
        doctor must fall back to the svc-account-derived id, not the
        legacy freq-ops@pam hardcode.
        """
        doctor_src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        # The svc-name-derived fallback must appear.
        self.assertIn(
            'f"{svc_name}@pam!freq-rw"',
            doctor_src,
            "doctor must derive the fallback token_id from cfg.ssh_service_account",
        )
        # The legacy hardcoded fallback must NOT appear.
        self.assertNotIn(
            '"freq-ops@pam!freq-rw"',
            doctor_src,
            "Legacy freq-ops@pam!freq-rw fallback must be removed from doctor",
        )

    def test_doctor_pve_token_drift_has_no_ro_legacy(self):
        """_check_pve_token_drift must not read the Jarvis-legacy /etc/freq/credentials/pve-token RO file.

        the RO token at
        /etc/freq/credentials/pve-token (PVE_TOKEN_ID=... format) was
        a Jarvis infra-lane construct, not a product runtime concept.
        Keeping it in the runtime doctor check conflated two distinct
        trust roots and trained operators to ignore 'ro token unreadable'
        warnings. Product runtime doctor validates only the RW token.
        """
        doctor_src = (FREQ_ROOT / "freq" / "core" / "doctor.py").read_text()
        # The drift function must not reference the RO token file.
        # Extract the _check_pve_token_drift source.
        drift_match = re.search(
            r'def _check_pve_token_drift.*?(?=\ndef |\Z)',
            doctor_src,
            re.DOTALL,
        )
        self.assertIsNotNone(drift_match, "_check_pve_token_drift must exist")
        drift_src = drift_match.group(0)
        # Drop comment/docstring lines so pins fire only on real code.
        code_lines = []
        in_docstring = False
        for line in drift_src.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            code_lines.append(line)
        code_src = "\n".join(code_lines)

        self.assertNotIn(
            '"/etc/freq/credentials/pve-token"',
            code_src,
            "Jarvis-legacy RO token path must not appear in _check_pve_token_drift code",
        )
        self.assertNotIn(
            "PVE_TOKEN_ID",
            code_src,
            "Jarvis-legacy RO token format (PVE_TOKEN_ID=...) must not appear in _check_pve_token_drift code",
        )
        self.assertNotIn(
            "PVE_TOKEN_SECRET",
            code_src,
            "Jarvis-legacy RO token format (PVE_TOKEN_SECRET=...) must not appear in _check_pve_token_drift code",
        )


if __name__ == "__main__":
    unittest.main()
