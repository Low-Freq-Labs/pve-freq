"""Systemd operator truth tests.

Proves:
1. Service file uses the default service account user (freq-admin)
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

    def test_uses_code_default_user(self):
        """Static template must match the shipped default service account."""
        src = self._service_src()
        self.assertIn("User=freq-admin", src,
                       "Static template must use code default (freq-admin)")

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

    def test_installer_generates_service_file(self):
        """Installer must generate service file (templates from freq.toml)."""
        src = self._installer_src()
        self.assertIn("freq-serve.service", src)
        self.assertIn("svc_user", src,
                       "Installer must detect service account from freq.toml")


class TestInitGeneratedSystemdTruth(unittest.TestCase):
    """init_cmd-generated service unit must match the shipped systemd contract."""

    def _init_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/init_cmd.py")) as f:
            return f.read()

    def test_uses_network_online_target(self):
        src = self._init_src()
        self.assertIn("After=network-online.target", src)
        self.assertIn("Wants=network-online.target", src)

    def test_sets_group_to_service_account(self):
        src = self._init_src()
        self.assertIn('f"Group={svc_name}', src)


if __name__ == "__main__":
    unittest.main()
