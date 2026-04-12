"""Tests for deploy-test.sh empty bundle handling.

Bug: contrib/deploy-test.sh failed with 'fatal: Refusing to create empty
bundle' when source and target HEADs already matched. The bundle path
was reached even when no commits were between the two.

Fix: Skip bundle creation when BEHIND=0 or when TARGET_HEAD is unknown
to local git. Runtime sync still runs so deploys are never half-applied.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestDeployHarnessSameHead(unittest.TestCase):
    """deploy-test.sh must handle same-HEAD case without empty bundle."""

    def setUp(self):
        self.script = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()

    def test_checks_behind_count_before_bundle(self):
        """Script must check BEHIND count before calling git bundle create."""
        # Find the bundle creation call
        self.assertIn("git bundle create", self.script)
        # Must be guarded by BEHIND > 0 check
        self.assertIn('"$BEHIND" -eq 0', self.script)

    def test_same_head_exits_cleanly(self):
        """Same-HEAD case must log 'up to date' and skip bundle."""
        self.assertIn("Already up to date", self.script)

    def test_verifies_target_head_exists_locally(self):
        """Before git log, must verify TARGET_HEAD exists in local git."""
        self.assertIn("git rev-parse --quiet --verify", self.script)

    def test_runtime_sync_not_skipped_by_same_head(self):
        """Runtime sync (step 5/6) must run regardless of bundle path."""
        # Runtime sync must be outside the if/else bundle block
        rsync_idx = self.script.find("[5/6] Syncing to runtime install")
        bundle_else_block = self.script.find("git bundle create")
        self.assertGreater(rsync_idx, bundle_else_block,
                           "Runtime sync must come after bundle block (not nested in it)")


class TestBashSyntax(unittest.TestCase):
    """Script must be syntactically valid bash."""

    def test_bash_syntax_valid(self):
        """bash -n must accept the script."""
        import subprocess
        script_path = FREQ_ROOT / "contrib" / "deploy-test.sh"
        r = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, f"bash -n failed: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
