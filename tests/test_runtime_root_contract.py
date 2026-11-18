"""Tests for runtime root resolution after deploy+init.

Bug: On live 5005, editable pip install of pve-freq pointed to
/tmp/pve-freq-dev. When CLI commands ran without the freq wrapper
(e.g. sudo python3 -c 'import freq'), sys.path's editable finder
resolved freq.__file__ to /tmp/pve-freq-dev/freq/__init__.py. Then
resolve_install_dir() walked up from that file and returned
/tmp/pve-freq-dev — pointing CLI surfaces at a dev tree instead of
the real runtime.

Root causes:
1. resolve_install_dir walked up from __file__ before checking for
   /opt/pve-freq as a production install.
2. deploy-test.sh never cleared stale editable installs from
   site-packages.

Fix:
1. resolve_install_dir now prefers /opt/pve-freq when it has conf/
   and freq/ — i.e., a real production install. Walk-up fallback
   only runs when no production install exists.
2. deploy-test.sh clears __editable__*pve* finders from site-packages
   (both /usr/local and /home/*/.local) before rsync.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestResolveInstallDirPrefersProduction(unittest.TestCase):
    """resolve_install_dir must prefer /opt/pve-freq over source walk-up."""

    def test_prod_check_before_walkup(self):
        """resolve_install_dir must check /opt/pve-freq BEFORE walking up."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        prod_check_idx = src.find('prod = "/opt/pve-freq"')
        walkup_idx = src.find("walk up from this file")
        self.assertNotEqual(prod_check_idx, -1)
        self.assertNotEqual(walkup_idx, -1)
        self.assertLess(prod_check_idx, walkup_idx,
                        "Production path check must come before walk-up")

    def test_prod_check_validates_conf_and_freq(self):
        """Production check must verify conf/ AND freq/ dirs exist."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        self.assertIn('os.path.join(prod, "conf")', src)
        self.assertIn('os.path.join(prod, "freq")', src)

    def test_freq_dir_env_still_wins(self):
        """FREQ_DIR environment variable must still take absolute priority."""
        src = (FREQ_ROOT / "freq" / "core" / "config.py").read_text()
        # FREQ_DIR check must appear FIRST in resolve_install_dir
        idx = src.find("def resolve_install_dir")
        block = src[idx:idx + 2000]
        env_idx = block.find('os.environ.get("FREQ_DIR")')
        prod_idx = block.find('prod = "/opt/pve-freq"')
        self.assertLess(env_idx, prod_idx, "FREQ_DIR check must come first")


class TestDeployTestClearsEditable(unittest.TestCase):
    """deploy-test.sh must clear stale editable pip installs."""

    def test_clears_editable_finders(self):
        """Script must find and delete __editable__*pve* files."""
        src = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()
        self.assertIn("__editable__*pve*", src)
        self.assertIn("-delete", src)

    def test_clears_both_system_and_user_sites(self):
        """Script must clear both /usr/local and /home/*/.local sites."""
        src = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()
        self.assertIn("/usr/local/lib/python3.*/dist-packages", src)
        self.assertIn("/home/*/.local/lib/python3.*/site-packages", src)


if __name__ == "__main__":
    unittest.main()
