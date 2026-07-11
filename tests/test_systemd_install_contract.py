"""Tests for the canonical systemd install and runtime identity contract.

Bug: install.sh, init, Docker, and a contrib artifact described overlapping
dashboard lifecycles with different paths, accounts, and restart behavior.

Fix: install.sh and freq init now call the same Python renderer. The stale
contrib unit with a hardcoded account was removed.

Contract:
- Unit Environment=FREQ_DIR must match actual install dir
- Unit User/Group must match configured service account
- ExecStart must use /usr/local/bin/freq (the wrapper, not python direct)
- contrib/freq-serve.service does not exist as a competing definition
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestSystemdUnitTemplate(unittest.TestCase):
    """install.sh must consume the canonical renderer."""

    def test_install_sh_does_not_copy_contrib_unit(self):
        """install.sh must NOT use 'cp' for the service unit."""
        with open(FREQ_ROOT / "install.sh") as f:
            content = f.read()
        # Find the systemd section
        in_systemd = False
        for line in content.split("\n"):
            if "WITH_SYSTEMD" in line and "true" in line:
                in_systemd = True
            if in_systemd and "cp " in line and "freq-serve.service" in line:
                self.fail("install.sh still copies contrib unit verbatim — "
                          "must generate inline with templated paths")

    def test_install_sh_templates_install_dir(self):
        """Installer passes its actual install directory to the renderer."""
        with open(FREQ_ROOT / "install.sh") as f:
            content = f.read()
        self.assertIn('dashboard_service_unit(sys.argv[1], sys.argv[2])', content)
        self.assertIn('PYTHONPATH="${INSTALL_DIR}" python3 -', content)
        self.assertIn('"${svc_user}" "${INSTALL_DIR}"', content)

    def test_install_sh_detects_service_account(self):
        """install.sh must detect service account from config."""
        with open(FREQ_ROOT / "install.sh") as f:
            content = f.read()
        self.assertIn("svc_user", content,
                       "Must detect service account for User= field")

    def test_contrib_unit_is_retired(self):
        """A wrong-account static unit must not compete with the renderer."""
        self.assertFalse((FREQ_ROOT / "contrib" / "freq-serve.service").exists())


class TestCanonicalUnitDefaults(unittest.TestCase):
    """The renderer owns host-systemd behavior."""

    def test_uses_default_service_account_user(self):
        from freq.core.service_units import dashboard_service_unit

        content = dashboard_service_unit("freq-admin", "/opt/pve-freq")
        self.assertIn("User=freq-admin", content)

    def test_uses_opt_pve_freq(self):
        """Canonical unit uses the supplied absolute runtime path."""
        from freq.core.service_units import dashboard_service_unit

        content = dashboard_service_unit("freq-admin", "/opt/pve-freq")
        self.assertIn('Environment="FREQ_DIR=/opt/pve-freq"', content)

    def test_uses_freq_serve_command(self):
        """Canonical unit starts freq serve via the installed wrapper."""
        from freq.core.service_units import dashboard_service_unit

        content = dashboard_service_unit("freq-admin", "/opt/pve-freq")
        self.assertIn('ExecStart="/usr/local/bin/freq" serve', content)


if __name__ == "__main__":
    unittest.main()
