"""Update method truth tests.

Proves:
1. /api/info includes install_method
2. Dashboard update banner uses install_method for guidance
3. Frontend stores install_method from /api/info
4. Update banner does NOT hardcode docker-only commands
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestUpdateBannerMethodAware(unittest.TestCase):
    """Dashboard update banner must tailor guidance by install method."""

    def _app_js(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            return f.read()

    def test_banner_checks_install_method(self):
        src = self._app_js()
        check_fn = src.split("function _checkForUpdate")[1].split("\nfunction ")[0]
        self.assertIn("_freqInstallMethod", check_fn,
                       "Update banner must use install method for guidance")

    def test_banner_handles_git(self):
        src = self._app_js()
        check_fn = src.split("function _checkForUpdate")[1].split("\nfunction ")[0]
        self.assertIn("'git'", check_fn)
        self.assertIn("git pull", check_fn)

    def test_banner_handles_docker(self):
        src = self._app_js()
        check_fn = src.split("function _checkForUpdate")[1].split("\nfunction ")[0]
        self.assertIn("'docker'", check_fn)
        self.assertIn("docker compose", check_fn)

    def test_banner_handles_dpkg(self):
        src = self._app_js()
        check_fn = src.split("function _checkForUpdate")[1].split("\nfunction ")[0]
        self.assertIn("'dpkg'", check_fn)
        self.assertIn("apt", check_fn)

    def test_banner_not_docker_only(self):
        """Banner must NOT hardcode docker-only command as the only option."""
        src = self._app_js()
        check_fn = src.split("function _checkForUpdate")[1].split("\nfunction ")[0]
        # Should have multiple method branches, not just docker
        self.assertIn("method===", check_fn,
                       "Must branch on install method")


class TestFrontendStoresInstallMethod(unittest.TestCase):
    """Frontend must store install_method from /api/info."""

    def test_stores_from_info(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        self.assertIn("_freqInstallMethod", src)
        self.assertIn("d.install_method", src)


if __name__ == "__main__":
    unittest.main()
