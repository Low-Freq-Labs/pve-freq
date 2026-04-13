"""Launch/load overlay contract tests.

Proves the post-login _showApp() launch sequence reads like an ops
console entering live state, not a product splash screen. Pins the
evidence-first vocabulary: COLD START / CONNECTING / FLEET / HEALTH /
MEDIA / ONLINE with lowercase factual detail lines — no "Dashboard
ready" comfort copy, no purple progress bar branding, no "LOADING"
placeholder.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


def _show_app_block():
    src = _js()
    idx = src.index("function _showApp")
    return src[idx: src.index("\nfunction _checkForUpdate")]


class TestLoadOverlayVocabulary(unittest.TestCase):
    """Launch sequence vocabulary must be evidence-first."""

    def test_initial_status_is_cold_start(self):
        """The initial status label must be 'COLD START', not 'LOADING'."""
        block = _show_app_block()
        self.assertIn("COLD START", block,
                       "Initial load status must be 'COLD START'")
        self.assertNotIn(">LOADING<", block,
                          "Must not use 'LOADING' placeholder status")
        # The ID selector target text should be COLD START not LOADING
        m = re.search(r'id="load-status"[^>]*>([^<]+)<', block)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1).strip(), "COLD START",
                         "load-status initial text must be 'COLD START'")

    def test_final_status_is_online(self):
        """The final status label must be 'ONLINE', not 'LOADED' or 'READY'."""
        block = _show_app_block()
        self.assertIn("'ONLINE'", block,
                       "Final load status must be 'ONLINE'")

    def test_final_detail_is_operator_console_live(self):
        """Final detail must say 'operator console live' — not 'Dashboard ready'."""
        block = _show_app_block()
        self.assertIn("operator console live", block,
                       "Final detail must say 'operator console live'")
        self.assertNotIn("Dashboard ready", block,
                          "Must not use 'Dashboard ready' comfort copy")

    def test_initial_detail_is_awaiting_fleet(self):
        """Initial detail must describe what's being fetched, lowercase."""
        block = _show_app_block()
        self.assertIn("awaiting fleet overview", block,
                       "Initial detail must say 'awaiting fleet overview'")
        # No "Fetching fleet data..." marketing spinner language
        self.assertNotIn("Fetching fleet data", block,
                          "Must not use 'Fetching fleet data...' spinner copy")


class TestLoadBarTreatment(unittest.TestCase):
    """The progress bar must not be purple-branded."""

    def test_load_bar_not_purple(self):
        """load-bar background must not be var(--purple) — use neutral text."""
        block = _show_app_block()
        # Find the load-bar div declaration
        m = re.search(r'id="load-bar"[^>]*style="([^"]+)"', block)
        self.assertIsNotNone(m, "load-bar must have inline style")
        style = m.group(1)
        self.assertNotIn("var(--purple)", style,
                          "load-bar background must not be purple")

    def test_load_bar_is_slim(self):
        """Progress bar must be 2px slim, not 4px branded accent."""
        block = _show_app_block()
        m = re.search(r'id="load-bar"[^>]*style="([^"]+)"', block)
        style = m.group(1)
        # Check the parent container height — slim track
        container_m = re.search(r'height:(\d+)px;background:var\(--input-border\)', block)
        self.assertIsNotNone(container_m, "load-bar parent track must exist")
        height = int(container_m.group(1))
        self.assertLessEqual(height, 2,
                              f"Progress bar track must be <=2px slim (got {height}px)")


class TestStageVocabulary(unittest.TestCase):
    """The five stages must use evidence-first labels tied to actual
    API calls, not generic loading terms."""

    def test_stages_are_connecting_fleet_health_media_online(self):
        """The five _p() calls must drive through the evidence-first stages."""
        block = _show_app_block()
        for label in ["'CONNECTING'", "'FLEET'", "'HEALTH'", "'MEDIA'", "'ONLINE'"]:
            self.assertIn(label, block,
                           f"Launch stage {label} must be present")

    def test_failure_detail_is_lowercase_operational(self):
        """Failure fallback lines must be lowercase operational, not
        title-case marketing ('Fleet overview unavailable')."""
        block = _show_app_block()
        self.assertIn("fleet overview unavailable", block,
                       "Fleet failure message must be lowercase")
        self.assertIn("health probe unavailable", block,
                       "Health failure message must be lowercase")
        # Old title-case versions must be gone
        self.assertNotIn("Fleet overview unavailable", block,
                          "Must not use title-case 'Fleet overview unavailable'")
        self.assertNotIn("Health check unavailable", block,
                          "Must not use 'Health check unavailable' — use lowercase 'health probe unavailable'")


class TestHeaderUserButtonChrome(unittest.TestCase):
    """The header user button appears only post-login — it's the first
    piece of post-auth chrome the operator sees, so it must also drop
    the purple hover and thick 2px border branding."""

    def test_user_button_no_purple_hover(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        idx = src.index('id="header-user-btn"')
        btn = src[idx: src.index("</button>", idx)]
        self.assertNotIn("var(--purple)", btn,
                          "header-user-btn must not hover to purple")

    def test_user_button_thin_border(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        idx = src.index('id="header-user-btn"')
        btn = src[idx: src.index("</button>", idx)]
        self.assertIn("border:1px solid", btn,
                       "header-user-btn must use 1px border, not 2px branded accent")


if __name__ == "__main__":
    unittest.main()
