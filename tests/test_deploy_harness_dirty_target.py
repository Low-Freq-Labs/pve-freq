"""Tests for deploy-test.sh dirty-target handling.

Bug: On a dirty /tmp/pve-freq-dev source tree (e.g. a leftover local
edit from a prior E2E run or mid-test diagnostic patch), the fast-path
bundle apply step ran `git pull /tmp/pve-freq-deploy-bundle.git HEAD
--ff-only` and aborted with 'Your local changes to the following files
would be overwritten by merge: freq/modules/init_cmd.py'. The whole
deploy run blocked right before the E2E init even started — the
harness couldn't self-heal from an unclean dev VM state.

Fix: Before the bundle path runs, check `git status --porcelain` on
the remote source tree. If anything is dirty, announce it and run
`git reset --hard HEAD && git clean -fd` in REMOTE_DIR so the fast-path
becomes deterministic. REMOTE_DIR is /tmp/pve-freq-dev on the E2E VM —
a disposable dev tree — so resetting is the correct self-heal, not a
destructive surprise.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestDeployHarnessDirtyTarget(unittest.TestCase):
    """deploy-test.sh must self-heal a dirty remote source tree."""

    def setUp(self):
        self.script = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()

    def test_checks_porcelain_status(self):
        """Must run git status --porcelain on the remote REMOTE_DIR."""
        self.assertIn("git status --porcelain", self.script)

    def test_resets_hard_when_dirty(self):
        """Must run git reset --hard HEAD when dirty output is non-empty."""
        self.assertIn("git reset --hard HEAD", self.script)

    def test_cleans_untracked_when_dirty(self):
        """Must run git clean -fd alongside reset to drop untracked crud."""
        self.assertIn("git clean -fd", self.script)

    def test_dirty_check_runs_before_bundle_apply(self):
        """Dirty reset must happen before `git pull ... --ff-only`."""
        reset_idx = self.script.find("git reset --hard HEAD")
        pull_idx = self.script.find("git pull /tmp/pve-freq-deploy-bundle.git")
        self.assertNotEqual(reset_idx, -1)
        self.assertNotEqual(pull_idx, -1)
        self.assertLess(reset_idx, pull_idx,
                        "Dirty reset must run before the bundle git pull")

    def test_dirty_check_only_when_target_exists(self):
        """Dirty check must be inside the else branch (target has a tree)."""
        # The porcelain check should appear after the TARGET_HEAD non-empty else,
        # not in the clean-bootstrap branch which has no git tree to check.
        bootstrap_idx = self.script.find("Clean target — bootstrapping source tree")
        porcelain_idx = self.script.find("git status --porcelain")
        else_idx = self.script.find("LOCAL_HEAD=$(git rev-parse HEAD)")
        self.assertNotEqual(bootstrap_idx, -1)
        self.assertNotEqual(porcelain_idx, -1)
        self.assertNotEqual(else_idx, -1)
        self.assertLess(bootstrap_idx, else_idx)
        self.assertLess(else_idx, porcelain_idx,
                        "Dirty check belongs in the existing-tree else branch")

    def test_dirty_announcement_is_deterministic(self):
        """Dirty reset must log a deterministic message so operators can see why."""
        self.assertIn("Target tree dirty", self.script)


class TestBashSyntax(unittest.TestCase):
    """Script must still be syntactically valid bash after edit."""

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
