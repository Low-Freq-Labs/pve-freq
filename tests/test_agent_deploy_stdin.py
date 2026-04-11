"""Tests for metrics agent deploy — SSH stdin must not be blocked by -n flag.

Bug: Agent deploy used 'ssh -n' with subprocess.run(input=agent_code).
The -n flag redirects stdin from /dev/null, overriding the input parameter.
Result: sudo tee received empty stdin → empty collector.py → agent exits
immediately on every start (restart counter >11000).

Root cause: The SSH command that pipes agent code via stdin included -n
(no stdin), which is correct for non-interactive commands but wrong when
we need to pipe data to the remote command.

Fix: Removed -n from the agent upload SSH command. The -n flag is still
used for all other non-interactive SSH commands (connectivity checks,
slot queries, etc.) where stdin is not needed.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestAgentUploadNoSshN(unittest.TestCase):
    """Agent upload SSH must not use -n flag (needs stdin for tee)."""

    def test_agent_upload_no_ssh_n(self):
        """The agent upload subprocess.run must not include -n in SSH args."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        import re
        # Find the subprocess.run that pipes agent_code
        match = re.search(
            r'# No -n flag.*?subprocess\.run\(\s*\["ssh"\]',
            src, re.DOTALL
        )
        self.assertIsNotNone(match, "Agent upload must use ['ssh'] without -n")

    def test_agent_upload_uses_input(self):
        """Agent upload must pipe code via input= parameter."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("input=agent_code", src)


class TestAgentCollectorExists(unittest.TestCase):
    """agent_collector.py must exist and be non-empty."""

    def test_collector_exists(self):
        """agent_collector.py must exist in the source tree."""
        collector = FREQ_ROOT / "freq" / "agent_collector.py"
        self.assertTrue(collector.is_file())

    def test_collector_has_http_server(self):
        """Collector must run an HTTP server (not a one-shot script)."""
        src = (FREQ_ROOT / "freq" / "agent_collector.py").read_text()
        self.assertIn("HTTPServer", src)
        self.assertIn("serve_forever", src)

    def test_collector_has_health_endpoint(self):
        """Collector must serve /health for verification."""
        src = (FREQ_ROOT / "freq" / "agent_collector.py").read_text()
        self.assertIn("/health", src)


if __name__ == "__main__":
    unittest.main()
