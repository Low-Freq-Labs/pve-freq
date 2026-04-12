"""Tests for truthful skip reasons on unreachable hosts.

Bug: When init skipped truenas-lab as unreachable, the reason was a
generic "unreachable" string. Operators need to know WHY (no route,
connection timed out, connection refused, host down, etc.) to debug.

Fix: _skip_reason() now returns specific reasons for each error class:
- "no route to host (check VLAN/routing)"
- "network unreachable (no route configured)"
- "connection timed out (host down or firewalled)"
- "connection refused (SSH port closed)"
- "auth failed"
- "host key mismatch"
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSkipReasonSpecific(unittest.TestCase):
    """_skip_reason must return specific, actionable reasons."""

    def test_no_route_to_host(self):
        """No route → mentions VLAN/routing."""
        from freq.modules.init_cmd import _skip_reason
        reason = _skip_reason("ssh: connect to host 192.168.1.1 port 22: No route to host")
        self.assertIn("no route", reason.lower())
        self.assertIn("vlan", reason.lower())

    def test_network_unreachable(self):
        """Network unreachable → mentions routing config."""
        from freq.modules.init_cmd import _skip_reason
        reason = _skip_reason("ssh: connect to host 10.0.0.1 port 22: Network is unreachable")
        self.assertIn("network unreachable", reason.lower())

    def test_connection_timed_out(self):
        """Connection timed out → mentions host down/firewall."""
        from freq.modules.init_cmd import _skip_reason
        reason = _skip_reason("ssh: connect to host 192.168.255.25 port 22: Connection timed out")
        self.assertIn("timed out", reason.lower())
        self.assertIn("host down", reason.lower())

    def test_connection_refused(self):
        """Connection refused → mentions SSH port."""
        from freq.modules.init_cmd import _skip_reason
        reason = _skip_reason("ssh: connect to host 10.0.0.1 port 22: Connection refused")
        self.assertIn("refused", reason.lower())
        self.assertIn("ssh port", reason.lower())

    def test_permission_denied(self):
        """Permission denied → auth failed."""
        from freq.modules.init_cmd import _skip_reason
        reason = _skip_reason("Permission denied (publickey,password).")
        self.assertEqual(reason, "auth failed")

    def test_host_key_mismatch(self):
        """Host key verification → host key mismatch."""
        from freq.modules.init_cmd import _skip_reason
        reason = _skip_reason("@@@@@@@@@@@@@@@@@@@@@\nWARNING: Host key verification failed.")
        self.assertEqual(reason, "host key mismatch")

    def test_unknown_error_fallback(self):
        """Unknown errors still return something."""
        from freq.modules.init_cmd import _skip_reason
        reason = _skip_reason("some weird error")
        self.assertEqual(reason, "SSH error")


class TestIsSkipErrorCovers(unittest.TestCase):
    """_is_skip_error must cover all the skip-worthy error strings."""

    def test_covers_no_route(self):
        from freq.modules.init_cmd import _is_skip_error
        self.assertTrue(_is_skip_error("No route to host"))

    def test_covers_network_unreachable(self):
        from freq.modules.init_cmd import _is_skip_error
        self.assertTrue(_is_skip_error("Network is unreachable"))

    def test_covers_timed_out(self):
        from freq.modules.init_cmd import _is_skip_error
        self.assertTrue(_is_skip_error("Connection timed out"))


if __name__ == "__main__":
    unittest.main()
