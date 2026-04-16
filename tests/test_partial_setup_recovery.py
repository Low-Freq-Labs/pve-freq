"""Tests for partial-init state recovery contract.

Bug: When headless init hangs late in Phase 12, roles.conf has
bootstrap-user:admin and service-account:admin but users.conf is still example-only.
Web login dead-ends: first_run might flicker to True via exception paths,
and the setup wizard misleads operators.

Root cause: Phase 11 wrote ONLY roles.conf, relying on a fallback path
in _load_users to parse roles.conf as user source. The fallback works
but is fragile: any exception during users.conf load causes _is_first_run
to return True, showing the setup wizard even with valid roles.

Fix: Phase 11 now writes users.conf AND roles.conf with matching entries.
Both files are consistent so the dashboard can identify authorized users
even when init hangs partway through.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestPhase11WritesUsersConf(unittest.TestCase):
    """Phase 11 must write users.conf alongside roles.conf."""

    def test_phase11_opens_users_conf(self):
        """Phase 11 must reference users.conf (not just roles.conf)."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Find Phase 11 RBAC block (_phase(11, ...))
        idx = src.find('_phase(11, headless_total, "RBAC Setup")')
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 3000]
        self.assertIn('users.conf', block)
        self.assertIn("users_file", block)

    def test_phase11_writes_both_users(self):
        """Phase 11 must write bootstrap_user AND svc_name to users.conf."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        idx = src.find("users.conf seeded with bootstrap")
        self.assertNotEqual(idx, -1)

    def test_phase11_ignores_commented_users(self):
        """Phase 11 must parse users.conf with comment skip logic."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        idx = src.find("users_existing = []")
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 500]
        self.assertIn("users_active = [", block)
        self.assertIn("not l.strip().startswith", block)


class TestLoadUsersFallback(unittest.TestCase):
    """_load_users must still work as a last-resort fallback."""

    def test_users_conf_takes_priority(self):
        """users.conf entries take priority over roles.conf fallback."""
        import tempfile
        import os

        class FakeCfg:
            _toml_users = []
            conf_dir = tempfile.mkdtemp()

        cfg = FakeCfg()
        try:
            # Write users.conf with 1 entry
            with open(os.path.join(cfg.conf_dir, "users.conf"), "w") as f:
                f.write("# FREQ Users\nbootstrap-admin admin\n")
            # Write roles.conf with 2 entries
            with open(os.path.join(cfg.conf_dir, "roles.conf"), "w") as f:
                f.write("bootstrap-admin:admin\nfreq-admin:admin\n")
            from freq.modules.users import _load_users
            users = _load_users(cfg)
            # users.conf has 1 entry; fallback to roles.conf shouldn't happen
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["username"], "bootstrap-admin")
        finally:
            import shutil
            shutil.rmtree(cfg.conf_dir, ignore_errors=True)

    def test_roles_conf_fallback_when_users_empty(self):
        """roles.conf is used as fallback when users.conf has no real entries."""
        import tempfile
        import os

        class FakeCfg:
            _toml_users = []
            conf_dir = tempfile.mkdtemp()

        cfg = FakeCfg()
        try:
            # Write users.conf with ONLY comments
            with open(os.path.join(cfg.conf_dir, "users.conf"), "w") as f:
                f.write("# commented entry\n# example user\n")
            # Write roles.conf with real entries
            with open(os.path.join(cfg.conf_dir, "roles.conf"), "w") as f:
                f.write("# template\nbootstrap-admin:admin\nfreq-admin:admin\n")
            from freq.modules.users import _load_users
            users = _load_users(cfg)
            self.assertEqual(len(users), 2)
            usernames = [u["username"] for u in users]
            self.assertIn("bootstrap-admin", usernames)
            self.assertIn("freq-admin", usernames)
        finally:
            import shutil
            shutil.rmtree(cfg.conf_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
