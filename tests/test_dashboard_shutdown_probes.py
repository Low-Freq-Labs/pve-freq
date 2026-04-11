"""Tests for dashboard shutdown with live SSH probe cleanup.

Bug: systemctl stop/restart hung because background SSH probes used
ControlMaster mux sockets that outlived the daemon threads. The mux
master processes were children of the main process and prevented
systemd from declaring the service stopped.

Root cause: Background loops used while True + time.sleep() which
don't respond to shutdown signals. SSH ControlMaster processes with
ControlPersist=300 outlive the Python process exit.

Fix:
1. _shutdown_flag (threading.Event) set by SIGTERM handler
2. Background loops check _shutdown_flag.is_set() and use .wait() instead of sleep()
3. _cleanup_ssh_mux() kills ControlMaster sockets on shutdown
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestShutdownFlag(unittest.TestCase):
    """Background loops must check _shutdown_flag to exit cleanly."""

    def test_shutdown_flag_exists(self):
        """_shutdown_flag must be a threading.Event."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("_shutdown_flag = threading.Event()", src)

    def test_sigterm_sets_flag(self):
        """SIGTERM handler must set _shutdown_flag."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("_shutdown_flag.set()", src)

    def test_health_loop_checks_flag(self):
        """Health loop must check _shutdown_flag."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("while not _shutdown_flag.is_set():", src)

    def test_loops_use_wait_not_sleep(self):
        """Background loops must use _shutdown_flag.wait() instead of time.sleep()."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("_shutdown_flag.wait(BG_CACHE_REFRESH_INTERVAL)", src)
        self.assertIn("_shutdown_flag.wait(60)", src)


class TestSshMuxCleanup(unittest.TestCase):
    """Shutdown must clean up SSH ControlMaster mux sockets."""

    def test_cleanup_function_exists(self):
        """_cleanup_ssh_mux function must exist."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("def _cleanup_ssh_mux(cfg):", src)

    def test_cleanup_called_on_shutdown(self):
        """_cleanup_ssh_mux must be called in the finally block."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("_cleanup_ssh_mux(cfg)", src)

    def test_cleanup_uses_ssh_exit(self):
        """Cleanup must use 'ssh -O exit' to close mux masters."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("-O", src)
        self.assertIn("exit", src)


if __name__ == "__main__":
    unittest.main()
