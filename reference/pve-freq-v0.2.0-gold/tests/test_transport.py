"""SSH transport tests with mocked subprocess.

Tests the async SSH transport layer without requiring real SSH connections.
Verifies platform-specific command construction, timeout handling, and
error recovery.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.core.types import Host, CmdResult
from engine.core.transport import SSHTransport, PLATFORM_SSH


class TestSSHCommandConstruction(unittest.TestCase):
    """Test that SSH commands are built correctly for each platform."""

    def test_linux_command(self):
        """Linux: svc-admin, sudo prefix, no extra crypto."""
        plat = PLATFORM_SSH["linux"]
        self.assertEqual(plat["user"], "svc-admin")
        self.assertEqual(plat["sudo"], "sudo ")
        self.assertEqual(plat["extra"], [])

    def test_pve_command(self):
        """PVE: same as linux."""
        plat = PLATFORM_SSH["pve"]
        self.assertEqual(plat["user"], "svc-admin")
        self.assertEqual(plat["sudo"], "sudo ")

    def test_pfsense_command(self):
        """pfSense: root, no sudo."""
        plat = PLATFORM_SSH["pfsense"]
        self.assertEqual(plat["user"], "root")
        self.assertEqual(plat["sudo"], "")

    def test_idrac_command(self):
        """iDRAC: legacy crypto, no sudo."""
        plat = PLATFORM_SSH["idrac"]
        self.assertEqual(plat["user"], "svc-admin")
        self.assertEqual(plat["sudo"], "")
        # Must have diffie-hellman and ssh-rsa
        extra_str = " ".join(plat["extra"])
        self.assertIn("diffie-hellman-group14-sha1", extra_str)
        self.assertIn("ssh-rsa", extra_str)

    def test_switch_command(self):
        """Switch: jarvis-ai, legacy ciphers."""
        plat = PLATFORM_SSH["switch"]
        self.assertEqual(plat["user"], "jarvis-ai")
        extra_str = " ".join(plat["extra"])
        self.assertIn("aes128-cbc", extra_str)
        self.assertIn("3des-cbc", extra_str)

    def test_truenas_command(self):
        """TrueNAS: svc-admin, sudo."""
        plat = PLATFORM_SSH["truenas"]
        self.assertEqual(plat["user"], "svc-admin")
        self.assertEqual(plat["sudo"], "sudo ")


class TestTransportInit(unittest.TestCase):
    """Test transport initialization."""

    def test_default_timeouts(self):
        t = SSHTransport(password="test")
        self.assertEqual(t.connect_timeout, 10)
        self.assertEqual(t.command_timeout, 30)

    def test_custom_timeouts(self):
        t = SSHTransport(password="test", connect_timeout=5, command_timeout=60)
        self.assertEqual(t.connect_timeout, 5)
        self.assertEqual(t.command_timeout, 60)


class TestTransportExecute(unittest.TestCase):
    """Test transport execute with mocked subprocess."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_successful_command(self, mock_exec):
        """Successful command returns stdout and rc=0."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"hello\n", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        transport = SSHTransport(password="test")
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        result = self._run(transport.execute(host, "echo hello"))

        self.assertEqual(result.stdout, "hello")
        self.assertEqual(result.returncode, 0)
        self.assertGreater(result.duration, 0)

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_failed_command(self, mock_exec):
        """Failed command returns stderr and non-zero rc."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error\n")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        transport = SSHTransport(password="test")
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        result = self._run(transport.execute(host, "false"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "error")

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_sudo_prefix_linux(self, mock_exec):
        """Linux sudo=True should prefix command with 'sudo '."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        transport = SSHTransport(password="test")
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        self._run(transport.execute(host, "cat /etc/shadow", sudo=True))

        # Check that the command passed to subprocess includes sudo
        call_args = mock_exec.call_args[0]
        # The last argument should be the command
        self.assertEqual(call_args[-1], "sudo cat /etc/shadow")

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_no_sudo_pfsense(self, mock_exec):
        """pfSense sudo=True should NOT add sudo (already root)."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        transport = SSHTransport(password="test")
        host = Host(ip="10.0.0.1", label="test", htype="pfsense")
        self._run(transport.execute(host, "cat /etc/ssh/sshd_config", sudo=True))

        call_args = mock_exec.call_args[0]
        # pfSense: no sudo prefix
        self.assertEqual(call_args[-1], "cat /etc/ssh/sshd_config")

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_timeout_handling(self, mock_exec):
        """Timeout should return CmdResult with rc=-1."""
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = asyncio.TimeoutError()
        mock_proc.kill = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_exec.return_value = mock_proc

        transport = SSHTransport(password="test", command_timeout=1)
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        result = self._run(transport.execute(host, "sleep 999"))

        self.assertEqual(result.returncode, -1)
        self.assertIn("timed out", result.stderr)

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_exception_handling(self, mock_exec):
        """Exception during execute should return CmdResult with error."""
        mock_exec.side_effect = OSError("Connection refused")

        transport = SSHTransport(password="test")
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        result = self._run(transport.execute(host, "echo test"))

        self.assertEqual(result.returncode, -1)
        self.assertIn("Connection refused", result.stderr)


class TestTransportPing(unittest.TestCase):
    """Test async ping."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_ping_success(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_exec.return_value = mock_proc

        transport = SSHTransport(password="test")
        result = self._run(transport.ping("10.0.0.1"))
        self.assertTrue(result)

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_ping_failure(self, mock_exec):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.wait.return_value = 1
        mock_exec.return_value = mock_proc

        transport = SSHTransport(password="test")
        result = self._run(transport.ping("10.0.0.1"))
        self.assertFalse(result)

    @patch("engine.core.transport.asyncio.create_subprocess_exec")
    def test_ping_exception(self, mock_exec):
        mock_exec.side_effect = OSError("Network unreachable")

        transport = SSHTransport(password="test")
        result = self._run(transport.ping("10.0.0.1"))
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
