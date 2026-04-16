"""Setup/init-check truth tests.

Proves:
1. Web setup completion writes setup-complete + .web-setup-complete (NOT .initialized)
2. .web-setup-complete marker content distinguishes web setup from CLI init
3. Setup UX text does NOT claim full initialization is complete
4. Setup summary shows honest "next steps" for fleet configuration
5. _is_first_run checks all three marker paths
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSetupCompletionMarkers(unittest.TestCase):
    """Setup complete writes .web-setup-complete, NOT .initialized."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _serve_setup_complete")[1].split("def _serve_")[0]

    def test_writes_setup_complete_marker(self):
        src = self._handler_src()
        self.assertIn("setup-complete", src)

    def test_writes_web_setup_marker(self):
        src = self._handler_src()
        self.assertIn(".web-setup-complete", src)

    def test_does_not_write_initialized(self):
        """Web wizard must NOT write .initialized — only freq init does."""
        src = self._handler_src()
        self.assertNotIn('".initialized"', src,
                          "Web wizard must not write .initialized marker")

    def test_web_setup_marker_says_web_setup(self):
        """The .web-setup-complete content must say 'web setup'."""
        src = self._handler_src()
        self.assertIn("web setup", src,
                       ".web-setup-complete marker must say 'web setup'")


class TestFirstRunDetection(unittest.TestCase):
    """_is_first_run checks all three markers."""

    def test_checks_all_markers(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        fn = src.split("def _is_first_run")[1].split("\ndef ")[0]
        self.assertIn("setup-complete", fn)
        self.assertIn(".initialized", fn)
        self.assertIn(".web-setup-complete", fn)


class TestSetupUXHonesty(unittest.TestCase):
    """Setup UI must not claim full initialization is complete."""

    def test_setup_html_does_not_say_ready(self):
        """Setup completion must NOT say 'Your FREQ instance is ready'."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/setup.html")) as f:
            src = f.read()
        self.assertNotIn("Your FREQ instance is ready", src,
                          "Setup must not claim full readiness — fleet config still needed")

    def test_setup_html_says_first_run(self):
        """Setup heading must indicate this is the first-run pass, not a
        full init. Current DC01 tone uses 'first-run' lowercase."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/setup.html")) as f:
            src = f.read()
        self.assertIn("first-run", src.lower(),
                       "Setup heading must say 'first-run' not just 'complete'")

    def test_setup_summary_points_to_init(self):
        """Setup JS summary must show the next lifecycle step: freq init.
        (Old guidance pointed at freq doctor; the real lifecycle is now
        bootstrap -> web setup -> freq init -> .initialized marker.)"""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/setup.js")) as f:
            src = f.read()
        self.assertIn("Next", src,
                       "Summary must show a 'Next' step")
        self.assertIn("freq init", src,
                       "Summary must tell user to run freq init")
        self.assertNotIn("freq doctor", src,
                          "Old 'freq doctor' guidance must be gone — init is the next step")

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
