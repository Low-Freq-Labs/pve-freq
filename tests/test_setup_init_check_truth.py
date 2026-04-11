"""Setup/init-check truth tests.

Proves:
1. Web setup completion writes both markers (setup-complete + .initialized)
2. .initialized marker content distinguishes web setup from CLI init
3. Setup UX text does NOT claim full initialization is complete
4. Setup summary shows honest "next steps" for fleet configuration
5. _is_first_run checks both marker paths
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSetupCompletionMarkers(unittest.TestCase):
    """Setup complete writes both markers for cross-tool compatibility."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _serve_setup_complete")[1].split("def _serve_")[0]

    def test_writes_setup_complete_marker(self):
        src = self._handler_src()
        self.assertIn("setup-complete", src)

    def test_writes_initialized_marker(self):
        src = self._handler_src()
        self.assertIn(".initialized", src)

    def test_initialized_marker_says_web_setup(self):
        """The .initialized content must distinguish web setup from CLI init."""
        src = self._handler_src()
        self.assertIn("web setup", src,
                       ".initialized marker must say 'web setup' to distinguish from CLI init")


class TestFirstRunDetection(unittest.TestCase):
    """_is_first_run checks both setup-complete and .initialized markers."""

    def test_checks_both_markers(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        fn = src.split("def _is_first_run")[1].split("\ndef ")[0]
        self.assertIn("setup-complete", fn)
        self.assertIn(".initialized", fn)


class TestSetupUXHonesty(unittest.TestCase):
    """Setup UI must not claim full initialization is complete."""

    def test_setup_html_does_not_say_ready(self):
        """Setup completion must NOT say 'Your FREQ instance is ready'."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/setup.html")) as f:
            src = f.read()
        self.assertNotIn("Your FREQ instance is ready", src,
                          "Setup must not claim full readiness — fleet config still needed")

    def test_setup_html_says_initial(self):
        """Setup heading must indicate this is initial, not complete setup."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/setup.html")) as f:
            src = f.read()
        self.assertIn("Initial Setup", src,
                       "Setup heading must say 'Initial Setup' not just 'Setup Complete'")

    def test_setup_summary_shows_next_steps(self):
        """Setup JS summary must show next steps for fleet configuration."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/setup.js")) as f:
            src = f.read()
        self.assertIn("Next steps", src)
        self.assertIn("freq doctor", src,
                       "Summary must tell user to run freq doctor")

    def test_setup_html_mentions_fleet_discovery(self):
        """Setup completion text must mention fleet discovery is separate."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/setup.html")) as f:
            src = f.read()
        # The description should mention that fleet work is still needed
        pane3 = src.split("pane-3")[1].split("</div>")[0] if "pane-3" in src else ""
        self.assertTrue(
            "fleet" in pane3.lower() or "discovery" in pane3.lower() or "host" in pane3.lower(),
            "Setup completion must mention fleet/discovery/host work remaining"
        )


if __name__ == "__main__":
    unittest.main()
