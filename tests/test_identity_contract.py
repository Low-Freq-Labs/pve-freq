"""Identity contract tests.

These checks make the bootstrap/service-account split executable so the
same drift cannot quietly re-enter the repo.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(relpath):
    with open(os.path.join(REPO_ROOT, relpath)) as f:
        return f.read()


class TestIdentityContractDoc(unittest.TestCase):
    """The canonical identity contract must exist and say the right thing."""

    def test_identity_contract_exists(self):
        path = os.path.join(REPO_ROOT, "docs", "IDENTITY-CONTRACT.md")
        self.assertTrue(os.path.isfile(path), "Identity contract doc must exist")

    def test_identity_contract_pins_core_rules(self):
        src = _read("docs/IDENTITY-CONTRACT.md")
        self.assertIn("`freq-ops` is the bootstrap/sudo identity", src)
        self.assertIn("`cfg.ssh_service_account` is the deployed fleet service account", src)
        self.assertIn("`freq-admin` is only the default deployed service-account name", src)
        # the runtime PVE API
        # identity is derived from cfg.ssh_service_account, NOT the
        # legacy freq-ops@pam@pam token.
        self.assertIn(
            "The runtime PVE API identity is `cfg.ssh_service_account@pam!freq-rw`",
            src,
        )
        # Anti-regression: the legacy identity must not be re-pinned as runtime.
        self.assertNotIn(
            "`freq-ops@pam!freq-rw` is the PVE API identity",
            src,
        )

    def test_identity_contract_covers_init_lifecycle(self):
        src = _read("docs/IDENTITY-CONTRACT.md")
        for heading in (
            "### Before `freq init`",
            "### During `freq init`",
            "### After `freq init`",
        ):
            self.assertIn(heading, src, f"Missing lifecycle checkpoint: {heading}")


class TestIdentityContractInE2EPlan(unittest.TestCase):
    """E2E documentation must include the identity checkpoints."""

    def test_e2e_progress_mentions_identity_contract(self):
        src = _read("docs/E2E-PROGRESS.md")
        self.assertIn("## Identity Contract", src,
                      "E2E plan/progress doc must mention the identity contract")
        self.assertIn("bootstrap/sudo account", src,
                      "E2E doc must distinguish bootstrap identity")
        self.assertIn("Default fleet service account name when unset", src,
                      "E2E doc must pin freq-admin as the default only")


class TestInitLifecycleIdentityBoundaries(unittest.TestCase):
    """The init lifecycle must preserve the identity split end to end."""

    def test_install_default_service_account_is_freq_admin(self):
        src = _read("install.sh")
        detect = src.split("detect_service_account()")[1].split("\n\nbanner()")[0]
        self.assertIn('local svc_user="freq-admin"', detect)

    def test_setup_copy_separates_web_operator_from_service_account(self):
        html = _read("freq/data/web/setup.html")
        js = _read("freq/data/web/js/setup.js")
        self.assertIn("first web operator", html)
        self.assertIn("fleet service account is deployed later by freq init", html)
        self.assertIn("default name is freq-admin", html)
        self.assertIn("default service-account name is freq-admin", js)

    def test_init_phase_plan_keeps_service_account_and_pve_api_separate(self):
        src = _read("freq/modules/init_cmd.py")
        plan_block = src.split('("Phase 2", "Cluster Config + VLAN Discovery"')[1].split('("SSH Account", cfg.ssh_service_account),')[0]
        self.assertIn("Create '{cfg.ssh_service_account}'", plan_block)
        # Phase 6 plan line uses
        # an f-string so the displayed token id always matches the
        # currently-configured service account, not a hardcoded legacy.
        self.assertIn(
            "Create {cfg.ssh_service_account}@pam!freq-rw token",
            plan_block,
        )
        self.assertNotIn("Create freq-ops@pam!freq-rw token", plan_block)

    def test_headless_seed_only_bootstrap_user_gets_dashboard_password(self):
        src = _read("freq/modules/init_cmd.py")
        block = src.split("def _seed_headless_dashboard_auth")[1].split("\ndef ")[0]
        self.assertIn("Only the bootstrap user gets a dashboard password", block)
        self.assertIn("service account runs", block)

    def test_runtime_terminal_uses_configured_service_account(self):
        src = _read("freq/api/terminal.py")
        # the silent `or "freq-admin"`
        # fallback was replaced with an explicit if-not check that logs a warning.
        # The contract: cfg.ssh_service_account is the primary; fallback is visible.
        self.assertIn('ssh_user = cfg.ssh_service_account', src)
        self.assertIn('identity contract violation', src)
        self.assertNotIn('cfg.ssh_service_account or "freq-ops"', src)

    def test_pve_api_identity_uses_service_account(self):
        """Phase 6 must derive the PVE API identity from cfg.ssh_service_account.

        the runtime PVE API token
        is owned by {cfg.ssh_service_account}@pam, not the legacy
        freq-ops@pam.  forbids
        freq-ops as a managed product identity entirely.
        """
        src = _read("freq/modules/init_cmd.py")
        token_block = src.split("def _phase_pve_api_token")[1].split("\ndef ")[0]
        # Single source of truth: derived from svc_name.
        self.assertIn('pve_user = f"{svc_name}@pam"', token_block)
        self.assertIn('full_token_id = f"{pve_user}!{token_name}"', token_block)
        # The legacy hardcoded strings must not return.
        self.assertNotIn("freq-ops@pam!freq-rw", token_block)
        self.assertNotIn("pveum user add freq-ops@pam", token_block)


if __name__ == "__main__":
    unittest.main()
