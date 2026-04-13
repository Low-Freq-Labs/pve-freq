"""Login/home shell copy contract tests.

Proves app.html login overlay and home empty-state copy match DC01
operational tone: no marketing voice, no comfort language, no
consumer-style "Your Dashboard is Empty" framing, no "ready-made
dashboard" pitch. The shell must read like operator console chrome,
not a hosted SaaS onboarding.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLoginOverlayCopy(unittest.TestCase):
    """Login overlay tagline must be operational, not marketing."""

    def _html(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            return f.read()

    def _login_block(self):
        src = self._html()
        # Extract the login overlay div content
        marker = 'id="login-overlay"'
        idx = src.index(marker)
        # Grab ~1500 chars from the marker — covers the overlay block
        return src[idx: idx + 2000]

    def test_login_overlay_exists(self):
        self.assertIn('id="login-overlay"', self._html(),
                       "Login overlay must still be present")

    def test_no_fleet_dashboard_in_login_tagline(self):
        """Login overlay MUST NOT display 'FLEET DASHBOARD' — marketing voice."""
        block = self._login_block()
        self.assertNotIn("FLEET DASHBOARD", block,
                          "Login tagline must not shout 'FLEET DASHBOARD'")

    def test_login_tagline_is_operator_console(self):
        """Login overlay must identify itself as an operator console."""
        block = self._login_block()
        self.assertIn("operator console", block,
                       "Login tagline must say 'operator console'")

    def test_login_tagline_is_lowercase(self):
        """DC01 tone: lowercase label, no caps marketing shouts."""
        block = self._login_block()
        # "operator console" appears in lowercase
        self.assertNotIn("OPERATOR CONSOLE", block,
                          "Tagline must be lowercase, not caps marketing")


class TestLoginLoadingStateCopy(unittest.TestCase):
    """The JS-rendered load screen (after successful login) must also
    drop 'FLEET DASHBOARD' marketing tagline."""

    def _js(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            return f.read()

    def _show_app_block(self):
        src = self._js()
        # _showApp writes the load overlay
        idx = src.index("function _showApp")
        return src[idx: idx + 2000]

    def test_show_app_no_fleet_dashboard(self):
        block = self._show_app_block()
        self.assertNotIn("FLEET DASHBOARD", block,
                          "_showApp load screen must not show 'FLEET DASHBOARD'")

    def test_show_app_uses_operator_console(self):
        block = self._show_app_block()
        self.assertIn("operator console", block,
                       "_showApp load screen must identify as operator console")


class TestHomeEmptyStateCopy(unittest.TestCase):
    """The home empty-state card must read like operator chrome, not a
    product onboarding modal."""

    def _html(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            return f.read()

    def _empty_block(self):
        src = self._html()
        idx = src.index('id="home-empty"')
        # Empty state block ends at </div> — grab enough context
        return src[idx: idx + 900]

    def test_home_empty_exists(self):
        self.assertIn('id="home-empty"', self._html(),
                       "Home empty-state block must still be present")

    def test_no_consumer_dashboard_empty_phrase(self):
        """'Your Dashboard is Empty' is consumer app framing, not operator."""
        block = self._empty_block()
        self.assertNotIn("Your Dashboard is Empty", block,
                          "Must not use 'Your Dashboard is Empty' consumer framing")
        self.assertNotIn("Your Dashboard", block,
                          "Must not address the operator with 'Your Dashboard'")

    def test_no_ready_made_dashboard_phrase(self):
        """'ready-made dashboard' is marketing copy, not operator language."""
        block = self._empty_block()
        self.assertNotIn("ready-made", block,
                          "Must not market a 'ready-made' dashboard")
        self.assertNotIn("ready made", block,
                          "Must not market a 'ready made' dashboard")

    def test_empty_state_is_operational(self):
        """Empty state must state the operational fact, not feel-good framing."""
        block = self._empty_block()
        # Should say something like "no widgets configured"
        self.assertIn("no widgets configured", block,
                       "Empty state must say 'no widgets configured'")

    def test_empty_state_references_real_actions(self):
        """Empty state must name the actual LAYOUT and QUICK START controls."""
        block = self._empty_block()
        self.assertIn("LAYOUT", block,
                       "Empty state must reference LAYOUT control")
        self.assertIn("QUICK START", block,
                       "Empty state must reference QUICK START control")

    def test_empty_state_no_comfort_language(self):
        """No 'hit', 'just', 'simply', 'easy' comfort filler words."""
        block = self._empty_block()
        banned = ["hit Quick", "Simply ", "just click", "easy", "easily"]
        for phrase in banned:
            self.assertNotIn(phrase, block,
                              f"Empty state must not use comfort language: '{phrase}'")


if __name__ == "__main__":
    unittest.main()
