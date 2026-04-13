"""Setup copy contract tests.

Proves setup.html and setup.js use DC01 operational tone, not generic
homelab marketing. No soft reassurance, no "datacenter management CLI
for homelabbers" tagline, no "Choose a strong password" coaching.
"""

import os
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
        # The logo <p> tag tagline must not call itself a homelab CLI
        logo_block = src.split('<div class="logo">')[1].split('</div>')[0]
        self.assertNotIn("homelab", logo_block.lower(),
                          "Setup logo block must not mention homelab")

    def test_tagline_is_operational(self):
        src = self._src()
        logo_block = src.split('<div class="logo">')[1].split('</div>')[0]
        # Should mention "first-run setup" or "fleet dashboard"
        self.assertTrue(
            "first-run" in logo_block.lower() or "fleet dashboard" in logo_block.lower(),
            "Setup tagline must identify as first-run setup or fleet dashboard"
        )

    def test_no_soft_password_coaching(self):
        src = self._src()
        self.assertNotIn("Choose a strong password", src,
                          "Must not coach with 'Choose a strong password'")

    def test_step_3_references_real_init_flow(self):
        """Step 3 must reference freq init and partial setup_health."""
        src = self._src()
        step3 = src.split('id="pane-3"')[1].split("</div>")[0]
        self.assertIn("freq init", step3,
                       "Step 3 must point operator to freq init")
        self.assertIn("setup_health", step3,
                       "Step 3 must mention setup_health state")

    def test_step_0_not_dashboard_admin_account(self):
        """Step 0 must not call itself 'Dashboard admin account' — that's
        the old standalone-dashboard model. The first web user is the
        'first operator'; freq-admin is a separate SSH service account
        deployed by init."""
        src = self._src()
        step0 = src.split('id="pane-0"')[1].split("</div>")[0]
        self.assertNotIn("Dashboard admin account", step0,
                          "Step 0 must not use old 'Dashboard admin account' framing")
        self.assertNotIn("Dashboard admin", step0,
                          "Step 0 must not use 'Dashboard admin' phrasing")

    def test_step_0_mentions_first_operator_or_login(self):
        """Step 0 heading/description must identify as operator/login setup."""
        src = self._src()
        step0 = src.split('id="pane-0"')[1].split("</div>")[0]
        self.assertTrue(
            "operator" in step0.lower() or "web login" in step0.lower(),
            "Step 0 must identify as first operator / web login setup"
        )

    def test_step_0_clarifies_service_account_separation(self):
        """Step 0 description must disambiguate: freq-admin is deployed
        by init, not created by this web form."""
        src = self._src()
        step0 = src.split('id="pane-0"')[1].split("</div>")[0]
        self.assertIn("freq-admin", step0,
                       "Step 0 must explicitly name freq-admin")
        self.assertIn("freq init", step0,
                       "Step 0 must say freq-admin is deployed by freq init")

    def test_step_3_not_dashboard_admin_configured(self):
        """Step 3 must not say 'Dashboard admin is configured' — that's
        the old account model."""
        src = self._src()
        step3 = src.split('id="pane-3"')[1].split("</div>")[0]
        self.assertNotIn("Dashboard admin is configured", step3,
                          "Step 3 must not use old 'Dashboard admin is configured' phrasing")

    def test_step_3_describes_real_init_side_effects(self):
        """Step 3 must tell operator what init actually does: deploy
        freq-admin, register hosts, write .initialized."""
        src = self._src()
        step3 = src.split('id="pane-3"')[1].split("</div>")[0]
        self.assertIn("freq-admin", step3,
                       "Step 3 must name freq-admin as what init deploys")
        self.assertIn(".initialized", step3,
                       "Step 3 must mention .initialized marker init writes")


class TestSetupJsCopy(unittest.TestCase):
    """Setup JavaScript strings must match DC01 tone."""

    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/setup.js")) as f:
            return f.read()

    def test_summary_references_init_flow(self):
        src = self._src()
        # Summary should mention freq init and setup_health
        summary_fn = src.split("function renderSummary")[1].split("\nfunction ")[0]
        self.assertIn("freq init", summary_fn,
                       "Summary must point operator to freq init")
        self.assertIn("setup_health", summary_fn,
                       "Summary must explain setup_health=partial state")

    def test_summary_names_freq_admin_as_init_artifact(self):
        """Summary must tell operator that freq init is what deploys
        freq-admin — clears up the admin vs service-account confusion."""
        src = self._src()
        summary_fn = src.split("function renderSummary")[1].split("\nfunction ")[0]
        self.assertIn("freq-admin", summary_fn,
                       "Summary must name freq-admin as an init artifact")

    def test_summary_not_dashboard_admin_label(self):
        """Summary must not label the first user as 'Dashboard admin' —
        that's the old standalone-dashboard model."""
        src = self._src()
        summary_fn = src.split("function renderSummary")[1].split("\nfunction ")[0]
        self.assertNotIn("Dashboard admin:", summary_fn,
                          "Summary must not label first user as 'Dashboard admin:'")

    def test_no_hobbyist_language(self):
        src = self._src()
        banned = ["homelab", "your FREQ instance", "Your fleet"]
        for phrase in banned:
            self.assertNotIn(phrase, src,
                              f"Setup JS must not use hobbyist phrase: {phrase}")


if __name__ == "__main__":
    unittest.main()
