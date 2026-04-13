"""Tests for Phase 8 — The Face (WS20: Dashboard Pages).
Covers: HTML view containers, JS view registration, API route registration.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

WEB_DIR = Path(__file__).parent.parent / "freq" / "data" / "web"


class TestDashboardHTML(unittest.TestCase):
    """Verify all v3.0.0 view containers exist in app.html."""

    @classmethod
    def setUpClass(cls):
        cls.html = (WEB_DIR / "app.html").read_text()

    def _assert_view(self, view_id):
        self.assertIn(f'id="{view_id}-view"', self.html,
                       f"Missing view container: {view_id}-view")

    # Existing views
    def test_home_view(self):
        self._assert_view("home")

    def test_fleet_view(self):
        self._assert_view("fleet")

    def test_docker_view(self):
        self._assert_view("docker")

    def test_media_view(self):
        self._assert_view("media")

    def test_security_view(self):
        self._assert_view("security")

    def test_tools_view(self):
        self._assert_view("tools")

    def test_lab_view(self):
        self._assert_view("lab")

    def test_settings_view(self):
        self._assert_view("settings")

    # New v3.0.0 views
    def test_network_view(self):
        self._assert_view("network")

    def test_firewall_view(self):
        self._assert_view("firewall")

    def test_certs_view(self):
        self._assert_view("certs")

    def test_dns_view(self):
        self._assert_view("dns")

    def test_vpn_view(self):
        self._assert_view("vpn")

    def test_dr_view(self):
        self._assert_view("dr")

    def test_incidents_view(self):
        self._assert_view("incidents")

    def test_metrics_view(self):
        self._assert_view("metrics")

    def test_automation_view(self):
        self._assert_view("automation")

    def test_plugins_view(self):
        self._assert_view("plugins")


class TestDashboardJS(unittest.TestCase):
    """Verify JS view system includes all v3.0.0 views."""

    @classmethod
    def setUpClass(cls):
        cls.js = (WEB_DIR / "js" / "app.js").read_text()

    def _assert_in_js(self, pattern):
        self.assertIn(pattern, self.js, f"Missing in app.js: {pattern}")

    # View IDs registered
    def test_view_ids_network(self):
        self._assert_in_js("'network'")

    def test_view_ids_firewall(self):
        self._assert_in_js("'firewall'")

    def test_view_ids_certs(self):
        self._assert_in_js("'certs'")

    def test_view_ids_dns(self):
        self._assert_in_js("'dns'")

    def test_view_ids_vpn(self):
        self._assert_in_js("'vpn'")

    def test_view_ids_dr(self):
        self._assert_in_js("'dr'")

    def test_view_ids_incidents(self):
        self._assert_in_js("'incidents'")

    def test_view_ids_metrics(self):
        self._assert_in_js("'metrics'")

    def test_view_ids_automation(self):
        self._assert_in_js("'automation'")

    def test_view_ids_plugins(self):
        self._assert_in_js("'plugins'")

    # Loader functions defined
    def test_loader_network(self):
        self._assert_in_js("function loadNetworkPage()")

    def test_loader_firewall(self):
        self._assert_in_js("function loadFirewallPage()")

    def test_loader_certs(self):
        self._assert_in_js("function loadCertsPage()")

    def test_loader_dns(self):
        self._assert_in_js("function loadDnsPage()")

    def test_loader_vpn(self):
        self._assert_in_js("function loadVpnPage()")

    def test_loader_dr(self):
        self._assert_in_js("function loadDrPage()")

    def test_loader_incidents(self):
        self._assert_in_js("function loadIncidentsPage()")

    def test_loader_metrics(self):
        self._assert_in_js("function loadMetricsPage()")

    def test_loader_automation(self):
        self._assert_in_js("function loadAutomationPage()")

    def test_loader_plugins(self):
        self._assert_in_js("function loadPluginsPage()")

    # Helper functions
    def test_fetch_helper(self):
        self._assert_in_js("function _fetchAndRender(")

    def test_stat_cards_helper(self):
        self._assert_in_js("function _statCards(")

    def test_status_badge_helper(self):
        self._assert_in_js("function _statusBadge(")

    def test_escape_helper(self):
        self._assert_in_js("function _esc(")

    # Nav grouping
    def test_network_under_fleet(self):
        self._assert_in_js("network:'fleet'")

    def test_firewall_under_security(self):
        self._assert_in_js("firewall:'security'")

    def test_certs_under_security(self):
        self._assert_in_js("certs:'security'")

    def test_vpn_under_security(self):
        self._assert_in_js("vpn:'security'")

    def test_dns_under_tools(self):
        self._assert_in_js("dns:'tools'")

    def test_dr_under_tools(self):
        self._assert_in_js("dr:'tools'")

    def test_incidents_under_tools(self):
        self._assert_in_js("incidents:'tools'")

    def test_plugins_under_tools(self):
        self._assert_in_js("plugins:'tools'")


class TestDashboardSubTabs(unittest.TestCase):
    """Verify sub-tab navigation buttons exist for the listed views.

    Buttons used to be inline `onclick="switchView('X')"`; under
    R-WEB-INLINE-CSP-CLEANUP-20260413O they were swept to
    `data-view="X"` so the existing app.js delegator picks them up
    via `e.target.closest('[data-view]')`. The tab still has to
    exist — we just look for the new attribute marker.
    """

    @classmethod
    def setUpClass(cls):
        cls.html = (WEB_DIR / "app.html").read_text()

    def test_fleet_network_tab(self):
        self.assertIn('data-view="network"', self.html)

    def test_security_firewall_tab(self):
        self.assertIn('data-view="firewall"', self.html)

    def test_security_certs_tab(self):
        self.assertIn('data-view="certs"', self.html)

    def test_security_vpn_tab(self):
        self.assertIn('data-view="vpn"', self.html)

    def test_tools_dns_tab(self):
        self.assertIn('data-view="dns"', self.html)

    def test_tools_dr_tab(self):
        self.assertIn('data-view="dr"', self.html)

    def test_tools_incidents_tab(self):
        self.assertIn('data-view="incidents"', self.html)

    def test_tools_metrics_tab(self):
        self.assertIn('data-view="metrics"', self.html)

    def test_tools_automation_tab(self):
        self.assertIn('data-view="automation"', self.html)

    def test_tools_plugins_tab(self):
        self.assertIn('data-view="plugins"', self.html)


class TestAPIRoutes(unittest.TestCase):
    """Verify API router includes plugin domain."""

    def test_plugin_api_registered(self):
        from freq.api import build_routes
        routes = build_routes()
        plugin_routes = [k for k in routes if "plugin" in k]
        self.assertTrue(len(plugin_routes) > 0,
                        "No plugin API routes registered")

    def test_build_routes_has_plugin_list(self):
        from freq.api import build_routes
        routes = build_routes()
        self.assertIn("plugin/list", str(routes.keys()))


if __name__ == "__main__":
    unittest.main()
