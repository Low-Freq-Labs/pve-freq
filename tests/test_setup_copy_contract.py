"""Setup copy contract tests.

Proves setup.html and setup.js use DC01 operational tone, not generic
homelab marketing. No soft reassurance, no "datacenter management CLI
for homelabbers" tagline, no "Choose a strong password" coaching.
"""

import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSetupHtmlCopy(unittest.TestCase):
    """Setup HTML copy must match DC01 operational tone."""

    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/setup.html")) as f:
            return f.read()

    def test_no_homelabbers_tagline(self):
        self.assertNotIn("homelabbers", self._src(),
                          "Setup must not market to 'homelabbers'")

    def test_no_homelab_in_tagline(self):
        src = self._src()
        hero_block = src.split('<header class="setup-hero">')[1].split('</header>')[0]
        self.assertNotIn("homelab", hero_block.lower(),
                          "Setup hero block must not mention homelab")

    def test_tagline_is_operational(self):
        src = self._src()
        logo_block = src.split('<header class="setup-hero">')[1].split('</header>')[0]
        self.assertTrue(
            "first-run" in logo_block.lower() or "full init" in logo_block.lower(),
            "Setup tagline must identify as first-run full init"
        )

    def test_no_soft_password_coaching(self):
        src = self._src()
        self.assertNotIn("Choose a strong password", src,
                          "Must not coach with 'Choose a strong password'")

    def test_run_panel_references_real_init_flow(self):
        """Run panel must reference backend runner and setup/status truth."""
        src = self._src()
        run = src.split('class="panel panel-run"')[1].split("</section>")[0]
        self.assertIn("/api/setup/status", run,
                       "Run panel must point at setup/status truth")
        self.assertIn("initialized/configured", run,
                       "Run panel must not claim success before configured status")

    def test_step_0_not_dashboard_admin_account(self):
        """Step 0 must not call itself 'Dashboard admin account' — that's
        the old standalone-dashboard model. The first web user is the
        'first operator'; freq-admin is a separate SSH service account
        deployed by init."""
        src = self._src()
        step0 = src.split('class="panel panel-operator"')[1].split("</section>")[0]
        self.assertNotIn("Dashboard admin account", step0,
                          "Step 0 must not use old 'Dashboard admin account' framing")
        self.assertNotIn("Dashboard admin", step0,
                          "Step 0 must not use 'Dashboard admin' phrasing")

    def test_step_0_mentions_first_operator_or_login(self):
        """Step 0 heading/description must identify as operator/login setup."""
        src = self._src()
        step0 = src.split('class="panel panel-operator"')[1].split("</section>")[0]
        self.assertTrue(
            "operator" in step0.lower() or "web login" in step0.lower(),
            "Step 0 must identify as first operator / web login setup"
        )

    def test_step_0_clarifies_service_account_separation(self):
        """Operator copy must disambiguate web operator and service account."""
        src = self._src()
        step0 = src.split('class="panel panel-operator"')[1].split("</section>")[0]
        self.assertIn("fleet service account", step0,
                       "Operator panel must name the separate fleet service account")
        self.assertIn("full init", step0,
                       "Operator panel must say full init deploys runtime identity")

    def test_run_panel_not_dashboard_admin_configured(self):
        """Run panel must not say 'Dashboard admin is configured' — that's
        the old account model."""
        src = self._src()
        step3 = src.split('class="panel panel-run"')[1].split("</section>")[0]
        self.assertNotIn("Dashboard admin is configured", step3,
                          "Run panel must not use old 'Dashboard admin is configured' phrasing")

    def test_setup_collects_real_init_inputs(self):
        """Setup must collect the inputs needed for full headless init."""
        src = self._src()
        self.assertIn("Service account", src)
        self.assertIn("PVE nodes", src)
        self.assertIn("Device credentials", src)
        self.assertIn("VM contract path", src)
        self.assertIn("Device credentials path", src)
        self.assertIn("Certificate path", src)

    def test_ssl_contract_has_defer_adopt_and_bootstrap_paths(self):
        """SSL setup must not force Cloudflare during base init."""
        src = self._src()
        self.assertIn("Finish init without SSL", src)
        self.assertIn("Adopt existing SSL", src)
        self.assertIn("Bootstrap new SSL after init", src)
        self.assertIn("Cloudflare token path", src)


class TestSetupJsCopy(unittest.TestCase):
    """Setup JavaScript strings must match DC01 tone."""

    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/setup.js")) as f:
            return f.read()

    def test_summary_references_init_flow(self):
        src = self._src()
        self.assertIn("zero-state-web-init-v1", src,
                       "Setup JS must collect the full web init payload contract")
        self.assertIn("/api/setup/init/start", src,
                       "Setup JS must call the backend init runner endpoint")
        self.assertIn("/api/setup/status", src,
                       "Setup JS must use setup/status as final truth")

    def test_summary_names_freq_admin_as_init_artifact(self):
        """JS must keep the runtime service-account default explicit."""
        src = self._src()
        self.assertIn("freq-admin", src,
                       "Setup JS must name freq-admin as the default service account")

    def test_js_payload_includes_two_ssl_objects(self):
        """Payload must distinguish adopt-existing from bootstrap-new SSL."""
        src = self._src()
        self.assertIn("adopt_existing", src)
        self.assertIn("bootstrap_new", src)
        self.assertIn("defer_base_init_ssl", src)
        self.assertIn("/api/cert/lifecycle/reconcile", src)
        self.assertIn("cert_targets", src)
        self.assertIn("target_source", src)

    def test_js_preserves_credential_path_fields(self):
        """Path-mode credentials must remain path fields for the backend."""
        src = self._src()
        self.assertIn("bootstrap_password_file", src)
        self.assertIn("bootstrap_key_path", src)
        self.assertIn("service_account_password_file", src)
        self.assertIn("dashboard_password_file", src)
        self.assertIn("vm_contract", src)
        self.assertIn("device_credentials_file", src)
        self.assertIn("password_file", src)

    def test_summary_not_dashboard_admin_label(self):
        """Summary must not label the first user as 'Dashboard admin' —
        that's the old standalone-dashboard model."""
        src = self._src()
        self.assertNotIn("Dashboard admin:", src,
                          "Summary must not label first user as 'Dashboard admin:'")

    def test_no_hobbyist_language(self):
        src = self._src()
        banned = ["homelab", "your FREQ instance", "Your fleet"]
        for phrase in banned:
            self.assertNotIn(phrase, src,
                              f"Setup JS must not use hobbyist phrase: {phrase}")


class TestSetupDeviceCredentialWriter(unittest.TestCase):
    """Web setup inline device credentials must become init-readable TOML."""

    def test_web_switch_row_writes_switch_section_and_secret_file(self):
        from freq.modules.serve import _write_setup_device_credentials

        with tempfile.TemporaryDirectory() as td:
            path = _write_setup_device_credentials(td, {
                "switch_1": {
                    "type": "switch",
                    "target": "10.25.255.5",
                    "username": "freq-ops",
                    "secret": "switch-secret",
                }
            })
            with open(path) as f:
                content = f.read()

            self.assertIn("[switch]", content)
            self.assertIn('user = "freq-ops"', content)
            self.assertIn('host = "10.25.255.5"', content)
            self.assertIn("password_file =", content)
            self.assertNotIn("[switch_1]", content)

    def test_web_bmc_row_writes_idrac_section(self):
        from freq.modules.serve import _write_setup_device_credentials

        with tempfile.TemporaryDirectory() as td:
            path = _write_setup_device_credentials(td, {
                "bmc_1": {
                    "type": "bmc",
                    "target": "bmc-10",
                    "username": "freq-ops",
                    "secret": "idrac-secret",
                }
            })
            with open(path) as f:
                content = f.read()

            self.assertIn("[idrac]", content)
            self.assertIn('label = "bmc-10"', content)
            self.assertIn('user = "freq-ops"', content)
            self.assertIn("password_file =", content)
            self.assertNotIn("[bmc_1]", content)


if __name__ == "__main__":
    unittest.main()
