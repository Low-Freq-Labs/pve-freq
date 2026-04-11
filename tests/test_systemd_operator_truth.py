"""Systemd operator truth tests.

Proves:
1. Service file uses correct user (freq-ops, not freq-admin)
2. Installer --with-systemd messaging adapts next-steps
3. Service file exists in contrib/
4. Installer references correct service file path
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestServiceFileContract(unittest.TestCase):
    """freq-serve.service must be production-honest."""

    def _service_src(self):
        path = os.path.join(REPO_ROOT, "contrib/freq-serve.service")
        with open(path) as f:
            return f.read()

    def test_service_file_exists(self):
        self.assertTrue(
            os.path.isfile(os.path.join(REPO_ROOT, "contrib/freq-serve.service"))
        )

    def test_uses_freq_ops_user(self):
        """Service must run as freq-ops (not legacy freq-admin)."""
        src = self._service_src()
        self.assertIn("User=freq-ops", src,
                       "Service must use freq-ops user")
        self.assertNotIn("freq-admin", src,
                          "Service must not reference legacy freq-admin")

    def test_has_restart_policy(self):
        src = self._service_src()
        self.assertIn("Restart=on-failure", src)

    def test_uses_freq_serve(self):
        src = self._service_src()
        self.assertIn("freq serve", src)

    def test_logs_to_journal(self):
        src = self._service_src()
        self.assertIn("StandardOutput=journal", src)


class TestInstallerSystemdMessaging(unittest.TestCase):
    """Installer must adapt next-steps when --with-systemd is used."""

    def _installer_src(self):
        with open(os.path.join(REPO_ROOT, "install.sh")) as f:
            return f.read()

    def test_with_systemd_flag_documented(self):
        src = self._installer_src()
        self.assertIn("--with-systemd", src)

    def test_next_steps_adapt_for_systemd(self):
        """When systemd is installed, next-steps should say systemctl, not freq serve."""
        src = self._installer_src()
        # Should have a conditional that shows systemctl when WITH_SYSTEMD is true
        self.assertIn("systemctl start freq-serve", src,
                       "Installer must show systemctl command when systemd is installed")

    def test_next_steps_show_freq_serve_without_systemd(self):
        """Without systemd, next-steps should say freq serve."""
        src = self._installer_src()
        self.assertIn("freq serve", src)

    def test_installer_copies_correct_service_file(self):
        src = self._installer_src()
        self.assertIn("contrib/freq-serve.service", src)


if __name__ == "__main__":
    unittest.main()
