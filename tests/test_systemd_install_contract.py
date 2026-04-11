"""Tests for systemd install path and runtime identity contract.

Bug: install.sh --with-systemd copied contrib/freq-serve.service verbatim
with hardcoded FREQ_DIR=/opt/pve-freq. Custom --dir installs got a unit
file pointing to the wrong path. Service account was hardcoded too.

Fix: install.sh now generates the unit file inline with templated
INSTALL_DIR and detected service account, matching the actual install.
contrib/freq-serve.service remains as a reference/example only.

Contract:
- Unit Environment=FREQ_DIR must match actual install dir
- Unit User/Group must match configured service account
- ExecStart must use /usr/local/bin/freq (the wrapper, not python direct)
- contrib/freq-serve.service is reference only — never copied verbatim
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestSystemdUnitTemplate(unittest.TestCase):
    """install.sh must template the systemd unit, not copy verbatim."""

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
        """Systemd unit must use $INSTALL_DIR, not hardcoded /opt/pve-freq."""
        with open(FREQ_ROOT / "install.sh") as f:
            content = f.read()
        # The generated unit must reference ${INSTALL_DIR}
        self.assertIn("FREQ_DIR=${INSTALL_DIR}", content,
                       "Unit must template FREQ_DIR from INSTALL_DIR")

    def test_install_sh_detects_service_account(self):
        """install.sh must detect service account from config."""
        with open(FREQ_ROOT / "install.sh") as f:
            content = f.read()
        self.assertIn("svc_user", content,
                       "Must detect service account for User= field")

    def test_contrib_unit_is_reference_only(self):
        """contrib/freq-serve.service must exist as reference."""
        self.assertTrue((FREQ_ROOT / "contrib" / "freq-serve.service").is_file())


class TestContribUnitDefaults(unittest.TestCase):
    """contrib/freq-serve.service must have sane defaults for reference."""

    def test_uses_freq_ops_user(self):
        """Reference unit should use freq-ops (not freq-admin)."""
        with open(FREQ_ROOT / "contrib" / "freq-serve.service") as f:
            content = f.read()
        self.assertIn("User=freq-ops", content)

    def test_uses_opt_pve_freq(self):
        """Reference unit uses default /opt/pve-freq path."""
        with open(FREQ_ROOT / "contrib" / "freq-serve.service") as f:
            content = f.read()
        self.assertIn("FREQ_DIR=/opt/pve-freq", content)

    def test_uses_freq_serve_command(self):
        """Reference unit starts freq serve via wrapper."""
        with open(FREQ_ROOT / "contrib" / "freq-serve.service") as f:
            content = f.read()
        self.assertIn("freq serve", content)


if __name__ == "__main__":
    unittest.main()
