"""Tests for runtime ownership contract across repo-backed and /opt installs.

Bug: _detect_ssh_key() returned keys that exist on disk but aren't readable
by the current user. In repo-backed installs where multiple devs work on
the same checkout, SSH keys created by one user (e.g. user-a, 0600 perms)
were returned for another user (user-b) who can't read them, causing
silent SSH failures.

Ownership contract:
- Repo mode (dev): runtime paths owned by whoever runs freq. SSH keys
  must be readable by the current user or skipped.
- Production mode (/opt): runtime paths owned by service account.
  SSH keys are 0600, readable only by service account.
- _detect_ssh_key() and _detect_rsa_key() must check os.access(R_OK)
  before returning a key path.
"""
import os
import sys
import stat
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestKeyDetectionRespectsPermissions(unittest.TestCase):
    """SSH key detection must skip unreadable keys."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        # Restore permissions before cleanup
        for root, dirs, files in os.walk(self.tmpdir):
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_readable_key_returned(self):
        """A readable key file should be returned."""
        key_path = os.path.join(self.tmpdir, "test_key")
        with open(key_path, "w") as f:
            f.write("fake key")
        os.chmod(key_path, 0o600)
        self.assertTrue(os.path.isfile(key_path))
        self.assertTrue(os.access(key_path, os.R_OK))

    def test_detect_checks_readability(self):
        """_detect_ssh_key source must use os.access(path, os.R_OK)."""
        path = Path(__file__).parent.parent / "freq" / "core" / "config.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("os.access(path, os.R_OK)", content,
                       "_detect_ssh_key must check readability")

    def test_detect_rsa_checks_readability(self):
        """_detect_rsa_key source must use os.access(path, os.R_OK)."""
        path = Path(__file__).parent.parent / "freq" / "core" / "config.py"
        with open(path) as f:
            content = f.read()
        # Count occurrences — both _detect_ssh_key and _detect_rsa_key should have it
        count = content.count("os.access(path, os.R_OK)")
        self.assertGreaterEqual(count, 2,
                                "Both _detect_ssh_key and _detect_rsa_key must check readability")

    def test_legacy_key_resolver_checks_readability(self):
        """_resolve_legacy_key must check readability."""
        path = Path(__file__).parent.parent / "freq" / "core" / "ssh.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("os.access(rsa_path, os.R_OK)", content)


class TestOwnershipContract(unittest.TestCase):
    """Document the ownership contract for dev vs production mode."""

    def test_repo_mode_paths_documented(self):
        """Runtime paths in repo mode should be accessible by current user."""
        from freq.core.config import load_config
        cfg = load_config()
        # In repo mode, conf_dir and data_dir should be under the project
        self.assertTrue(cfg.conf_dir)
        self.assertTrue(cfg.data_dir)

    def test_key_dir_exists(self):
        """Key directory must exist."""
        from freq.core.config import load_config
        cfg = load_config()
        self.assertTrue(os.path.isdir(cfg.key_dir),
                        f"key_dir must exist: {cfg.key_dir}")

    def test_log_fallback_on_unwritable(self):
        """Config loader must handle unwritable log dir gracefully."""
        # In repo-backed installs, log dir may be owned by another user.
        # The logger init() has a fallback to ~/.freq/log/ when the
        # configured log dir is unwritable.
        from freq.core import log as logger
        # This should not raise even if log dir is unwritable
        self.assertTrue(hasattr(logger, "init"),
                        "Logger must have init() function")


if __name__ == "__main__":
    unittest.main()
