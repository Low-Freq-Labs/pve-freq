"""Tests for metrics agent deployment and its portable health probe.

Bug: Agent deploy used 'ssh -n' with subprocess.run(input=agent_code).
The -n flag redirects stdin from /dev/null, overriding the input parameter.
Result: sudo tee received empty stdin → empty collector.py → agent exits
immediately on every start (restart counter >11000).

Root cause: The SSH command that pipes agent code via stdin included -n
(no stdin), which is correct for non-interactive commands but wrong when
we need to pipe data to the remote command.

Fix: The three old upload implementations were replaced by the canonical
agent_deployment backend. It writes a literal heredoc through the normal SSH
transport, so collector bytes and SSH stdin flags can no longer diverge.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


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


class TestAgentHealthCheckCommand(unittest.TestCase):
    """Agent health verification must not require curl on target hosts."""

    def test_remote_health_command_has_python_fallback(self):
        from freq.modules.agent_health import remote_agent_health_command

        cmd = remote_agent_health_command(9990)
        self.assertIn("command -v curl", cmd)
        self.assertIn("command -v python3", cmd)
        self.assertIn("urllib.request", cmd)
        self.assertIn("command -v wget", cmd)
        self.assertIn("FREQ_AGENT_HEALTH_CHECK_NO_CLIENT", cmd)

    def test_init_verification_uses_shared_agent_health_command(self):
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        block = src.split("# Metrics agent verification for every generic systemd agent host.")[1].split("# Dashboard readiness")[0]
        self.assertIn("remote_agent_health_command(agent_port)", block)
        self.assertIn("StrictHostKeyChecking=accept-new", block)
        self.assertNotIn("curl -s http://localhost:{agent_port}/health", block)

    def test_canonical_deployer_uses_shared_agent_health_command(self):
        src = (FREQ_ROOT / "freq" / "modules" / "agent_deployment.py").read_text()
        self.assertIn("remote_agent_health_command(port)", src)


if __name__ == "__main__":
    unittest.main()
