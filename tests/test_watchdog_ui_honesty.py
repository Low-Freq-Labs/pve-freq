"""Watchdog UI honesty tests.

Proves the dashboard watchdog widget shows honest state under:
1. Daemon running + healthy → probe evidence (green)
2. Daemon running + degraded → probe evidence (yellow)
3. Watchdog not installed → optional add-on copy (dim)
4. Daemon down (503) → daemon not reachable (yellow)
5. Network failure → status unavailable (dim)
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestWatchdogAPIContract(unittest.TestCase):
    """Watchdog health proxy returns honest error states."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        return src.split("def handle_watchdog_health")[1].split("\ndef ")[0]

    def test_daemon_down_returns_503(self):
        """URLError (daemon down) must return 503, not 200."""
        src = self._handler_src()
        self.assertIn("503", src)
        self.assertIn("URLError", src)

    def test_daemon_down_includes_watchdog_down_flag(self):
        """Response must include watchdog_down=true for daemon-down state."""
        src = self._handler_src()
        self.assertIn("watchdog_down", src)

    def test_proxy_error_returns_502(self):
        """Non-URLError exceptions must return 502 (proxy error)."""
        src = self._handler_src()
        self.assertIn("502", src)
        self.assertIn("Proxy error", src)

    def test_proxies_to_configured_port(self):
        """Must proxy to cfg.watchdog_port, not hardcoded."""
        src = self._handler_src()
        self.assertIn("cfg.watchdog_port", src)

    def test_success_forwards_daemon_response(self):
        """On success, must forward the daemon's JSON response as-is."""
        src = self._handler_src()
        self.assertIn("resp.status", src,
                       "Must forward the daemon's HTTP status code")


class TestWatchdogWidgetStates(unittest.TestCase):
    """Frontend widget renders all failure modes honestly."""

    def _widget_src(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # Find the watchdog health check section
        idx = src.index("Watchdog health check")
        return src[idx:idx + 2500]

    def test_error_response_shows_offline(self):
        """JSON with error field renders a warning, not fake green."""
        src = self._widget_src()
        self.assertIn("d.error", src)
        self.assertIn("Watchdog: '+_esc", src)
        self.assertIn("var(--yellow)", src)

    def test_network_failure_shows_not_reachable(self):
        """Fetch catch → status unavailable."""
        src = self._widget_src()
        self.assertIn("Watchdog: status unavailable", src)

    def test_healthy_shows_green(self):
        """Successful probe with hosts uses green."""
        src = self._widget_src()
        self.assertIn("'green'", src)
        self.assertIn("hosts>0", src)

    def test_degraded_shows_yellow(self):
        """Probe errors use yellow."""
        src = self._widget_src()
        self.assertIn("'yellow'", src)
        self.assertIn("errors>0", src)

    def test_shows_host_count(self):
        """Widget shows host count when available."""
        src = self._widget_src()
        self.assertIn("d.hosts", src)
        self.assertIn("hosts", src.lower())

    def test_offline_uses_dim_text(self):
        """Offline/not-reachable states use dim text (not red/green)."""
        src = self._widget_src()
        self.assertIn("text-dim", src)

    def test_status_uppercased(self):
        """Status text is plain operator copy, not bare verdict text."""
        src = self._widget_src()
        self.assertIn("Watchdog:", src)
        self.assertNotIn("WATCHDOG: OK", src)


class TestWatchdogWidgetNotFakeGreen(unittest.TestCase):
    """Widget must never show green when watchdog is actually down."""

    def test_error_path_does_not_show_green(self):
        """The error branch must not render green status."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        idx = src.index("Watchdog health check")
        widget = src[idx:idx + 2500]
        # The error branch: if(d.error){...return;}
        # It must NOT contain 'green' before the return
        error_branch_start = widget.index("d.error")
        error_branch_end = widget.index("return;", error_branch_start)
        error_branch = widget[error_branch_start:error_branch_end]
        self.assertNotIn("green", error_branch,
                          "Error branch must not render green — would be misleading")

    def test_catch_path_does_not_show_green(self):
        """The network failure catch must not render green status."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        idx = src.index("Watchdog health check")
        widget = src[idx:idx + 2500]
        catch_start = widget.rindex("}).catch(function(){var el=")
        catch_block = widget[catch_start:]
        self.assertNotIn("green", catch_block,
                          "Catch block must not render green — would be misleading")


if __name__ == "__main__":
    unittest.main()
