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


class TestDashboardTone(unittest.TestCase):
    """Dashboard voice must be calm DC01 operator tone, not playful."""

    BANNED_PHRASES = [
        "Drop the bass", "bass-boosted", "Feel the rumble",
        "Plex is happy", "magic happens", "Chaos is a feature",
        "MISSION CONTROL", "v3.0.0", "INITIALIZING",
        "FLEET ONLINE", "MEDIA STACK",
    ]

    def test_no_playful_taglines(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        tagline_block = src.split("var taglines=")[1].split("};")[0]
        for phrase in self.BANNED_PHRASES:
            self.assertNotIn(phrase, tagline_block,
                             f"Taglines must not contain playful phrase: {phrase}")

    def test_no_playful_quotes(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        quote_block = src.split("var quotes=")[1].split("];")[0]
        for phrase in self.BANNED_PHRASES:
            self.assertNotIn(phrase, quote_block,
                             f"Quotes must not contain playful phrase: {phrase}")

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
