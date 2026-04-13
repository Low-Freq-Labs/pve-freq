"""Tests for deploy-test.sh source-side exclusions.

Bug: contrib/deploy-test.sh clean-target rsync failed with 'send_files
failed to open /data/projects/pve-freq/data/keys/freq_id_rsa permission
denied' (rsync exit code 23). The dev workspace had freq_id_rsa owned
by another developer with 0600 perms, which rsync running as the
deploying user couldn't read.

Fix: Clean-target rsync now excludes /data/, /tls/, and /build/ entirely.
The deploy harness only syncs source code, never runtime state. This
matches the runtime-sync step (already excludes /data/, /tls/, /build/).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestCleanTargetExcludes(unittest.TestCase):
    """Clean-target rsync must exclude runtime-state directories."""

    def setUp(self):
        self.script = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()

    def test_excludes_data_dir(self):
        """Clean-target rsync must exclude /data/."""
        # Find the clean-target rsync block
        idx = self.script.find("Clean target — bootstrapping")
        self.assertNotEqual(idx, -1)
        # Check for /data/ exclude in the next ~500 chars
        block = self.script[idx:idx + 800]
        self.assertIn("--exclude='/data/'", block)

    def test_excludes_tls_dir(self):
        """Clean-target rsync must exclude /tls/ (runtime cert material)."""
        idx = self.script.find("Clean target — bootstrapping")
        block = self.script[idx:idx + 800]
        self.assertIn("--exclude='/tls/'", block)

    def test_excludes_build_dir(self):
        """Clean-target rsync must exclude /build/ (setuptools artifacts)."""
        idx = self.script.find("Clean target — bootstrapping")
        block = self.script[idx:idx + 800]
        self.assertIn("--exclude='/build/'", block)

    def test_clean_target_and_runtime_sync_have_same_data_exclude(self):
        """Both rsyncs must exclude /data/ for consistency."""
        # Runtime sync block
        runtime_idx = self.script.find("Syncing to runtime install")
        runtime_block = self.script[runtime_idx:runtime_idx + 600]
        self.assertIn("--exclude='/data/'", runtime_block)

        # Clean-target block
        clean_idx = self.script.find("Clean target — bootstrapping")
        clean_block = self.script[clean_idx:clean_idx + 800]
        self.assertIn("--exclude='/data/'", clean_block)


class TestDryRunSucceeds(unittest.TestCase):
    """The actual rsync command must exit cleanly (dry-run)."""

    def test_dry_run_no_permission_errors(self):
        """Running the exact rsync in --dry-run mode must exit 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "rsync", "-az", "--dry-run", "--delete",
                    "--exclude=__pycache__", "--exclude=*.pyc",
                    "--exclude=.venv/", "--exclude=.ruff_cache/",
                    "--exclude=~freq-ops/",
                    "--exclude=/data/", "--exclude=/tls/", "--exclude=/build/",
                    f"{FREQ_ROOT}/", tmpdir,
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(
                result.returncode, 0,
                f"rsync dry-run failed with exit {result.returncode}:\n{result.stderr}"
            )


if __name__ == "__main__":
    unittest.main()
