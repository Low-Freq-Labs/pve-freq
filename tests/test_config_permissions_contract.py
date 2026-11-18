"""Tests for config file permission contract — no world-writable config files.

Bug: freq init runs as root with umask 000. Python's open(path, "w")
creates files with mode 0o666 under umask 000. This left freq.toml
world-writable (-rw-rw-rw-) after a successful init.

Root cause: Post-init ownership phase did chmod 755 on conf/ directory
but did not chmod the individual files inside it.

Fix: After chown, explicitly chmod config files to 644 (owner rw,
group/other read-only) and subdirectories to 755.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestPostInitConfigPermissions(unittest.TestCase):
    """Init must harden config file permissions after writing."""

    def test_interactive_path_chmods_config_files(self):
        """Interactive init must chmod config files to 644."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Must contain os.chmod(fpath, 0o644) for config files
        self.assertIn("os.chmod(fpath, 0o644)", src)

    def test_headless_path_chmods_config_files(self):
        """Headless init must also chmod config files to 644."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Must iterate conf_dir and chmod files
        self.assertIn("os.listdir(cfg.conf_dir)", src)
        # Should appear at least twice (interactive + headless)
        count = src.count("os.chmod(fpath, 0o644)")
        self.assertGreaterEqual(count, 2,
                                "Both interactive and headless init must chmod config files")

    def test_subdirs_get_755(self):
        """Config subdirectories (personality/, plugins/) get 755."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        count = src.count("os.chmod(fpath, 0o755)")
        self.assertGreaterEqual(count, 2)

    def test_keys_vault_stay_700(self):
        """keys/ and vault/ directories must remain 700."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('chmod", "700"', src)


class TestDeployTestExcludesTls(unittest.TestCase):
    """deploy-test.sh must not delete TLS certs on deploy."""

    def test_rsync_excludes_tls(self):
        """rsync --delete must exclude /tls/ directory."""
        src = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()
        self.assertIn("--exclude='/tls/'", src)


if __name__ == "__main__":
    unittest.main()
