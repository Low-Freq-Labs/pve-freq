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
        """Setup collects values and discovery decisions, never file contracts."""
        src = self._src()
        self.assertIn("Service account", src)
        self.assertIn("PVE nodes", src)
        self.assertIn("Credentials for owned devices", src)
        self.assertIn("Review every discovered row", src)
        for legacy in (
            "VM contract path", "Device credentials path", "Owned VMIDs",
            "Template VMIDs", "hosts import", "Cloudflare token path",
        ):
            self.assertNotIn(legacy, src)

    def test_base_flow_defers_optional_certificate_lifecycle(self):
        """Frozen v1 keeps certificate lifecycle out of first-run setup."""
        src = self._src()
        self.assertIn("certificate lifecycle stay deferred", src)
        self.assertNotIn("ssl-fullchain-path", src)
        self.assertNotIn("cloudflare-token-path", src)

    def test_discovery_review_is_the_centerpiece(self):
        src = self._src()
        self.assertIn('id="resource-rows"', src)
        self.assertIn("Every choice is explicit", src)
        self.assertIn("production or lab placement", src)
        self.assertIn('id="discovery-as-of"', src)

    def test_wizard_is_semantic_and_stepped(self):
        src = self._src()
        self.assertIn('class="wizard-rail"', src)
        for step in ("operator", "connect", "discover", "credentials", "launch", "progress"):
            self.assertIn(f'data-step="{step}"', src)


class TestSetupJsCopy(unittest.TestCase):
    """Setup JavaScript strings must match DC01 tone."""

    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/setup.js")) as f:
            return f.read()

    def test_summary_references_init_flow(self):
        src = self._src()
        self.assertIn("zero-state-web-v1", src,
                       "Setup JS must use the frozen browser contract")
        self.assertIn("/api/setup/init/start", src,
                       "Setup JS must call the backend init runner endpoint")
        self.assertIn("/api/setup/status", src,
                       "Setup JS must use setup/status as final truth")

    def test_summary_names_freq_admin_as_init_artifact(self):
        """JS must keep the runtime service-account default explicit."""
        src = self._src()
        self.assertIn("freq-admin", src,
                       "Setup JS must name freq-admin as the default service account")

    def test_js_uses_frozen_endpoint_surface(self):
        src = self._src()
        for endpoint in (
            "/api/auth/verify", "/api/setup/discovery/start",
            "/api/setup/discovery/status", "/api/setup/contract",
            "/api/setup/device-credentials", "/api/setup/init/status",
            "/api/setup/init/logs",
        ):
            self.assertIn(endpoint, src)

    def test_js_removes_legacy_browser_contract_fields(self):
        src = self._src()
        for legacy in (
            "bootstrap_password_file", "bootstrap_key_path",
            "service_account_password_file", "dashboard_password_file",
            "vm_contract", "device_credentials_file", "password_file",
            "owned_vmids", "template_vmids", "hosts_import",
        ):
            self.assertNotIn(legacy, src)

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

    def test_create_admin_failure_does_not_continue_to_init(self):
        """Setup must stop when the first operator session cannot be created."""
        src = self._src()
        create_block = src.split("function createOperator", 1)[1].split("function verifySession", 1)[0]
        self.assertIn(".catch(function(error)", create_block)
        self.assertNotIn("Continuing to init/start", src)
        self.assertNotIn("backend admin auth will be final truth", src)

    def test_setup_js_captures_csrf_for_post_admin_calls(self):
        """Setup page owns its CSRF token because it does not load app.js."""
        src = self._src()
        self.assertIn("model.csrf", src)
        self.assertIn("X-Freq-CSRF", src)
        self.assertIn("rememberSession(data)", src)
        self.assertIn("verifySession()", src)

    def test_setup_post_json_has_timeout_and_operator_failure_state(self):
        """Setup must not leave the browser stuck forever on create-admin."""
        src = self._src()
        self.assertIn("AbortController", src)
        self.assertIn("function getJson", src)
        self.assertIn("timed out", src)
        self.assertIn("operator_exists", src)

    def test_unknown_devices_are_acknowledged_only(self):
        src = self._src()
        self.assertIn("item.kind==='unknown'", src)
        self.assertIn("acknowledged-only in v1", src)
        self.assertIn("input.disabled=unknown", src)

    def test_success_requires_both_markers_and_status_complete(self):
        src = self._src()
        self.assertIn("!job.initialized || !job.web_setup_complete", src)
        self.assertIn("status.state!=='complete'", src)
        self.assertIn("No completion was assumed", src)


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

    def test_root_freq_init_inputs_path_aliases_to_container_mount(self):
        from freq.modules.serve import _setup_existing_secret_file

        alias_dir = "/freq-init-inputs"
        try:
            os.makedirs(alias_dir, exist_ok=True)
            path = os.path.join(alias_dir, "alias-contract-test")
            with open(path, "w") as f:
                f.write("ok\n")
        except OSError as exc:
            self.skipTest(f"{alias_dir} is not writable in this test environment: {exc}")
        try:
            resolved = _setup_existing_secret_file(
                "/root/freq-init-inputs/alias-contract-test",
                "vm_contract",
            )
            self.assertEqual(path, resolved)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_setup_path_validator_accepts_sudo_readable_files(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        helper = src.split("def _setup_existing_secret_file", 1)[1].split("\ndef _read_setup_secret_file", 1)[0]

        self.assertIn("sudo", helper)
        self.assertIn("test", helper)
        self.assertIn("-f", helper)

    def test_setup_secret_reader_can_use_sudo_cat(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        helper = src.split("def _read_setup_secret_file", 1)[1].split("\ndef _toml_scalar", 1)[0]

        self.assertIn("PermissionError", helper)
        self.assertIn("sudo", helper)
        self.assertIn("cat", helper)


if __name__ == "__main__":
    unittest.main()
