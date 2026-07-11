import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestSNMPSetupUIContract(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "freq/data/web/app.html").read_text()
        self.js = (ROOT / "freq/data/web/js/app.js").read_text()
        self.css = (ROOT / "freq/data/web/css/app.css").read_text()

    def test_network_page_mounts_guided_snmp_setup(self):
        for prefix in ("fleet", "network"):
            self.assertIn(f'id="{prefix}-snmp-setup-section"', self.html)
            self.assertIn(f'id="{prefix}-snmp-setup-stats"', self.html)
            self.assertIn(f'id="{prefix}-snmp-setup-main"', self.html)
        self.assertEqual(self.html.count('data-network-role="snmp-setup-section"'), 2)
        self.assertEqual(self.html.count('data-network-role="snmp-setup-stats"'), 2)
        self.assertEqual(self.html.count('data-network-role="snmp-setup-main"'), 2)
        self.assertIn('data-action="snmpSetupProbe"', self.html)

    def test_network_surface_ids_are_unique_and_js_scopes_to_active_view(self):
        for duplicate_id in ("netmon-out", "snmp-setup-section", "snmp-setup-stats", "snmp-setup-main"):
            self.assertNotIn(f'id="{duplicate_id}"', self.html)
        self.assertIn("function _networkSurfaceRoot()", self.js)
        self.assertIn("_networkSurfaceElement('netmon-out')", self.js)
        self.assertNotIn("getElementById('netmon-out')", self.js)

    def test_js_uses_backend_contract_and_action_allowlist(self):
        for token in (
            "SNMP_SETUP_PLAN:'/api/v1/net/snmp/setup/plan'",
            "SNMP_SETUP_STATUS:'/api/v1/net/snmp/setup/status'",
            "SNMP_SETUP_CREDENTIALS:'/api/v1/net/snmp/setup/credentials'",
            "SNMP_SETUP_APPLY:'/api/v1/net/snmp/setup/apply'",
            "snmpSetupCredentialDryRun:snmpSetupCredentialDryRun",
            "snmpSetupDryRun:snmpSetupDryRun",
            "snmpSetupApply:snmpSetupApply",
        ):
            self.assertIn(token, self.js)

    def test_apply_is_confirmed_and_dry_run_gated(self):
        self.assertIn("Run a dry run before applying SNMP setup", self.js)
        self.assertIn("confirm:!dryRun", self.js)
        self.assertIn("confirmAction('Apply SNMP setup", self.js)

    def test_target_table_surfaces_class_mutation_caveat_and_result(self):
        for token in (
            "setup_class",
            "mutation",
            "caveats",
            "current_state",
            "snmp-target-table",
            "snmp-result-summary",
        ):
            self.assertIn(token, self.js + self.css)


if __name__ == "__main__":
    unittest.main()
