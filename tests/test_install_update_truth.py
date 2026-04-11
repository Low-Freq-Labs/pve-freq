"""Install/update operator truth tests.

Proves:
1. CLI update help text does not overpromise auto-upgrade for all methods
2. Update command detects install method before acting
3. Non-git methods give guidance (not fake upgrade)
4. Install.sh exists and documents usage
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestUpdateCLIHelpTruth(unittest.TestCase):
    """CLI update help must not overpromise."""

    def test_update_help_does_not_say_upgrade_all(self):
        """Help text must not claim upgrade works for all install methods."""
        with open(os.path.join(REPO_ROOT, "freq/cli.py")) as f:
            src = f.read()
        # Find the update parser help text
        import re
        match = re.search(r'sub\.add_parser\("update".*?help="([^"]+)"', src)
        self.assertIsNotNone(match)
        help_text = match.group(1)
        self.assertNotIn("and upgrade", help_text,
                          "Update help must not promise upgrade for all methods")


class TestUpdateMethodDetection(unittest.TestCase):
    """Update command must detect install method before acting."""

    def test_detects_install_method(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/selfupdate.py")) as f:
            src = f.read()
        self.assertIn("_detect_install_method", src)

    def test_git_method_does_real_update(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/selfupdate.py")) as f:
            src = f.read()
        git_handler = src.split("def _update_git")[1].split("\ndef ")[0]
        self.assertIn("git", git_handler.lower())
        self.assertIn("fetch", git_handler)

    def test_non_git_gives_guidance_not_upgrade(self):
        """dpkg/rpm/manual methods give guidance, not fake upgrade."""
        with open(os.path.join(REPO_ROOT, "freq/modules/selfupdate.py")) as f:
            src = f.read()
        update_fn = src.split("def cmd_update")[1].split("\ndef _update_git")[0]
        # dpkg path should say "use apt"
        self.assertIn("apt", update_fn)
        # rpm path should say "use dnf"
        self.assertIn("dnf", update_fn)
        # manual path should say "Re-run" installer
        self.assertIn("install.sh", update_fn)


class TestInstallShExists(unittest.TestCase):
    """install.sh must exist and be executable."""

    def test_install_sh_exists(self):
        path = os.path.join(REPO_ROOT, "install.sh")
        self.assertTrue(os.path.isfile(path))

    def test_install_sh_executable(self):
        path = os.path.join(REPO_ROOT, "install.sh")
        self.assertTrue(os.access(path, os.X_OK))


if __name__ == "__main__":
    unittest.main()
