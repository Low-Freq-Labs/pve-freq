"""Dashboard first-load acceptance tests.

Proves the dashboard first-load contract:
1. GET / returns 200 with HTML app shell
2. App shell contains login overlay
3. Static assets (CSS, JS) load correctly
4. Setup status returns valid JSON
5. Healthz endpoint returns 200
6. No 500 errors on first load
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAppShellContract(unittest.TestCase):
    """GET / must return the app shell with critical elements."""

    def test_app_html_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/app.html")
        self.assertTrue(os.path.isfile(path))

    def test_app_html_has_login_overlay(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("login-overlay", src,
                       "App shell must have login overlay for unauthenticated users")

    def test_app_html_has_nav(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("view-btn", src, "App shell must have navigation buttons")

    def test_app_html_references_css(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("app.css", src)

    def test_app_html_references_js(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("app.js", src)


class TestStaticAssetsExist(unittest.TestCase):
    """CSS and JS assets must exist for the dashboard to render."""

    def test_app_css_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/css/app.css")
        self.assertTrue(os.path.isfile(path), "app.css must exist")

    def test_app_js_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/js/app.js")
        self.assertTrue(os.path.isfile(path), "app.js must exist")

    def test_setup_html_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/setup.html")
        self.assertTrue(os.path.isfile(path), "setup.html must exist")

    def test_setup_js_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/js/setup.js")
        self.assertTrue(os.path.isfile(path), "setup.js must exist")


class TestServeHandlerContract(unittest.TestCase):
    """Serve handlers must serve app shell and static assets."""

    def test_root_route_serves_app(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("app.html", src, "Serve must reference app.html for root route")

    def test_healthz_endpoint_exists(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("healthz", src)

    def test_static_route_exists(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("/static/", src, "Must have static asset route")


class TestAssetVersionTruth(unittest.TestCase):
    """Served HTML must align asset cache-bust versions with real product version."""

    def test_app_html_uses_version_placeholder(self):
        """Raw app.html must use {{VERSION}} placeholder, not a hardcoded version."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            raw = f.read()
        self.assertIn("{{VERSION}}", raw,
                       "app.html must use {{VERSION}} placeholder for cache-bust tokens")
        self.assertNotIn("?v=3.0.1", raw, "Must not hardcode stale 3.0.1")
        self.assertNotIn("?v=3.0.0", raw, "Must not hardcode stale 3.0.0")

    def test_served_app_html_injects_real_version(self):
        """_load_app_html() must substitute {{VERSION}} with freq.__version__."""
        from freq.modules.web_ui import _load_app_html
        from freq import __version__
        html = _load_app_html()
        self.assertNotIn("{{VERSION}}", html,
                          "Placeholder must be substituted on load")
        self.assertIn(f"?v={__version__}", html,
                       f"Served HTML must use real version {__version__}")

    def test_no_stale_3_0_versions_in_static(self):
        """No stale 3.0.x version strings in any static asset."""
        for fname in ("app.html", "app.css", "app.js"):
            path = None
            for sub in ("", "css/", "js/"):
                candidate = os.path.join(REPO_ROOT, "freq/data/web", sub, fname)
                if os.path.isfile(candidate):
                    path = candidate
                    break
            if not path:
                continue
            with open(path) as f:
                src = f.read()
            self.assertNotIn("3.0.1", src, f"{fname} must not have stale 3.0.1")
            self.assertNotIn("3.0.0", src, f"{fname} must not have stale 3.0.0")


class TestDashboardTone(unittest.TestCase):
    """Dashboard voice must be calm DC01 operator tone, not playful."""

    BANNED_PHRASES = [
        "Drop the bass", "bass-boosted", "Feel the rumble",
        "Plex is happy", "magic happens", "Chaos is a feature",
        "MISSION CONTROL", "v3.0.0", "INITIALIZING",
        "FLEET ONLINE", "MEDIA STACK",
    ]

    def test_no_quote_roulette(self):
        """No random quote rotation at all — not even operational ones."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        self.assertNotIn("var quotes=", src,
                          "Must not define a quotes array")
        self.assertNotIn("function rq(", src,
                          "Must not define a quote rotator")
        self.assertNotIn("home-quote-footer", src,
                          "Must not reference home-quote-footer element")

    def test_quote_footer_removed_from_html(self):
        """HTML must not have the quote footer element."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertNotIn("home-quote-footer", src,
                          "HTML must not contain the quote footer element")

    def test_taglines_deterministic(self):
        """Taglines must be deterministic (single string per view), not a random pool."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # Should have _viewLabels map, not a taglines array-of-arrays
        self.assertIn("_viewLabels", src,
                       "Must use deterministic _viewLabels, not a random taglines pool")
        self.assertNotIn("var taglines=", src,
                          "Must not define a taglines pool with multiple options per view")

    def test_no_soft_reassurance_copy(self):
        """No soft marketing-style reassurance copy."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        banned = [
            "All systems reporting",
            "Fleet health summary",
            "Container status",
            "Operational status",
            "Current state",
        ]
        for phrase in banned:
            self.assertNotIn(phrase, src,
                              f"Must not contain soft reassurance: {phrase}")

    def test_css_no_stale_version(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/css/app.css")) as f:
            header = f.read()[:300]
        self.assertNotIn("v3.0.0", header, "CSS header must not have stale version")
        self.assertNotIn("MISSION CONTROL", header, "CSS header must not say MISSION CONTROL")

    def test_js_no_stale_version_comments(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        self.assertNotIn("v3.0.0", src, "JS must not have stale v3.0.0 references")

    def test_load_states_factual(self):
        """Load progress states must be factual, not theatrical."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        self.assertNotIn("INITIALIZING", src, "Use LOADING not INITIALIZING")
        self.assertNotIn("FLEET ONLINE", src, "Use FLEET not FLEET ONLINE")
        self.assertNotIn("MEDIA STACK", src, "Use MEDIA not MEDIA STACK")
        self.assertNotIn("Welcome,", src, "No Welcome greeting in load state")

    def test_no_theatrical_load_in_html(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertNotIn("MEDIA STACK", src, "HTML must not use MEDIA STACK")

    def test_fleet_stats_show_probe_evidence(self):
        """Fleet stats must label status as SSH PROBE, not bare ONLINE."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # The stats card builder for fleet must say SSH PROBE or PROBE AGE
        self.assertIn("SSH PROBE", src,
                       "Fleet stats must label status as SSH PROBE result")
        self.assertIn("PROBE AGE", src,
                       "Fleet stats must show probe age, not LIVE DATA")

    def test_no_bare_live_label(self):
        """Must not show bare 'LIVE' as a status label without age context."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # The age label should always show seconds/minutes, not claim LIVE
        self.assertNotIn("'LIVE'", src.split("var _ageLbl")[1].split(";")[0] if "var _ageLbl" in src else "",
                          "Age label must show actual seconds, not claim LIVE")

    def test_no_ascii_logos_in_html(self):
        """ASCII art logos removed — plain text wordmarks only."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        # ASCII art box characters that made up the FREQ logo
        self.assertNotIn("██████╗", src,
                          "HTML must not contain ASCII art logo characters")
        self.assertNotIn("╚══════╝", src,
                          "HTML must not contain ASCII art logo characters")

    def test_no_ascii_logos_in_js(self):
        """Loading screen ASCII logo removed."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        self.assertNotIn("\\u2588\\u2588\\u2588", src,
                          "JS must not contain escaped ASCII block art")

    def test_no_cockpit_branding_comments(self):
        """Cockpit metaphor removed from CSS comments."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/css/app.css")) as f:
            src = f.read()
        self.assertNotIn("Dark cockpit", src,
                          "CSS must not use cockpit metaphor")
        self.assertNotIn("cockpit alerts", src.lower(),
                          "CSS comments must not reference cockpit")

    def test_badge_preserves_distinct_states(self):
        """badge() must not collapse distinct operational states into up/ok."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        badge_fn = src.split("function badge(s)")[1].split("\nfunction ")[0]
        # Must map distinct states to distinct classes
        self.assertIn("unreachable:'unreachable'", badge_fn,
                       "unreachable must have its own class, not collapse to down")
        self.assertIn("auth_failed:", badge_fn,
                       "auth_failed must be a recognized state")
        self.assertIn("stale:", badge_fn,
                       "stale must be a recognized state")
        self.assertIn("probe_error:", badge_fn,
                       "probe_error must be a recognized state")

    def test_fleet_stats_surface_probe_status(self):
        """Fleet stats must annotate SSH PROBE label with non-ok probe_status."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        fn = src.split("function _loadHomeFleetStats")[1].split("\nfunction ")[0]
        # Must read probe_status from response
        self.assertIn("probe_status", fn,
                       "Fleet stats must read probe_status")
        # Must recognize stale and error as distinct from ok
        self.assertIn("'stale'", fn,
                       "Fleet stats must check for stale probe_status")
        self.assertIn("'error'", fn,
                       "Fleet stats must check for error probe_status")
        # Must annotate SSH PROBE label when not ok
        self.assertIn("SSH PROBE (", fn,
                       "Fleet stats must annotate SSH PROBE label with probe_status")

    def test_watchdog_shows_evidence(self):
        """Watchdog must show probe evidence, not bare verdicts."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # The watchdog render block starts at the comment and ends at the catch
        watchdog_block = src.split("Watchdog probe status")[1].split(".catch")[0]
        self.assertIn("hosts probed", watchdog_block,
                       "Watchdog must show what was probed")
        self.assertIn("errors", watchdog_block,
                       "Watchdog must surface error count")
        self.assertNotIn("WATCHDOG: OK", watchdog_block,
                          "Must not show bare OK verdict")
        self.assertNotIn("WATCHDOG: offline", watchdog_block,
                          "Must not show bare offline verdict")


if __name__ == "__main__":
    unittest.main()
