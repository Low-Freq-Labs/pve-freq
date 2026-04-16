"""Tests for install method detection and update behavior contract.

Bug: cmd_update had real behavior only for 'git' installs. 'git-release'
fell through to "Manual install" even though it has a .git directory.
'tarball' and 'local' showed "Manual install" even though they were
installed by install.sh (not manually).

Contract:
- git, git-release: real update via git pull --ff-only
- dpkg: hint to use apt
- rpm: hint to use dnf
- tarball, local: hint to re-run install.sh (with exact command)
- manual/unknown: generic re-run installer hint

Install methods produced by install.sh:
- local: --from-local source copy
- git-release: git clone from GitHub
- tarball: download + extract from GitHub releases
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.modules.selfupdate import _detect_install_method, cmd_update


class TestInstallMethodDetection(unittest.TestCase):
    """_detect_install_method must identify all known install types."""

    def _make_install(self, tmpdir, method=None, has_git=False):
        """Create a fake install dir with optional markers."""
        from dataclasses import dataclass

        @dataclass
        class FakeCfg:
            install_dir: str

        if method:
            with open(os.path.join(tmpdir, ".install-method"), "w") as f:
                f.write(method)
        if has_git:
            os.makedirs(os.path.join(tmpdir, ".git"))
        return FakeCfg(install_dir=tmpdir)

    def test_local_marker(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, method="local")
            self.assertEqual(_detect_install_method(cfg), "local")

    def test_git_release_marker(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, method="git-release")
            self.assertEqual(_detect_install_method(cfg), "git-release")

    def test_tarball_marker(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, method="tarball")
            self.assertEqual(_detect_install_method(cfg), "tarball")

    def test_git_dir_detection(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, has_git=True)
            self.assertEqual(_detect_install_method(cfg), "git")

    def test_marker_takes_priority_over_git_dir(self):
        """install-method marker wins over .git directory presence."""
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d, method="git-release", has_git=True)
            self.assertEqual(_detect_install_method(cfg), "git-release")

    def test_no_markers_is_manual(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._make_install(d)
            self.assertEqual(_detect_install_method(cfg), "manual")


class TestUpdateBehaviorContract(unittest.TestCase):
    """Every install method must have explicit update behavior — no silent fallthrough."""

    KNOWN_METHODS = {"git", "git-release", "tarball", "local", "dpkg", "rpm", "manual"}

    def test_all_methods_have_explicit_branch(self):
        """cmd_update source must handle every known method explicitly."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "selfupdate.py"
        with open(path) as f:
            content = f.read()
        for method in self.KNOWN_METHODS:
            # Each method must appear in an if/elif condition or in a tuple
            self.assertTrue(
                f'"{method}"' in content or f"'{method}'" in content,
                f"Install method '{method}' has no explicit handling in cmd_update"
            )

    def test_git_release_uses_git_update(self):
        """git-release must use the same git pull path as git."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "selfupdate.py"
        with open(path) as f:
            content = f.read()
        # git-release must be in the same branch as git
        self.assertIn('"git-release"', content)
        # Both should call _update_git
        self.assertIn('("git", "git-release")', content)

    def test_tarball_local_show_installer_hint(self):
        """tarball and local must hint to re-run install.sh."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "selfupdate.py"
        with open(path) as f:
            content = f.read()
        self.assertIn('("tarball", "local")', content)
        self.assertIn("install.sh", content)

    @patch("freq.modules.selfupdate._update_git")
    @patch("freq.modules.selfupdate._detect_install_method", return_value="git")
    @patch("freq.modules.selfupdate.fmt")
    def test_git_update_passes_args_to_helper(self, mock_fmt, mock_detect, mock_update):
        cfg = SimpleNamespace(install_dir="/tmp/freq")
        args = SimpleNamespace(yes=True)
        mock_update.return_value = 0

        rc = cmd_update(cfg, None, args)

        self.assertEqual(rc, 0)
        mock_update.assert_called_once_with(cfg, args)


class TestInstallShMarkers(unittest.TestCase):
    """install.sh must write valid markers for each install method."""

    def test_install_sh_writes_local_marker(self):
        with open(Path(__file__).parent.parent / "install.sh") as f:
            content = f.read()
        self.assertIn('"local"', content)

    def test_install_sh_writes_git_release_marker(self):
        with open(Path(__file__).parent.parent / "install.sh") as f:
            content = f.read()
        self.assertIn('"git-release"', content)

    def test_install_sh_writes_tarball_marker(self):
        with open(Path(__file__).parent.parent / "install.sh") as f:
            content = f.read()
        self.assertIn('"tarball"', content)


if __name__ == "__main__":
    unittest.main()
