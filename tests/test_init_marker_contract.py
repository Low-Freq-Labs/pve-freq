"""Tests for .initialized marker semantics contract.

Bug: A failed init could leave a STALE .initialized marker from a
previous successful init. The new run printed 'NOT initialized' but
.initialized still existed on disk, causing downstream surfaces
(is_first_run, doctor, setup wizard) to see a contradictory state.

Fix: Both interactive and headless init clear any existing .initialized marker
immediately after crossing the explicit Phase-1 point of no return. An
interruption before that boundary preserves prior truth. If the new run fails
after crossing, no marker exists; if it succeeds, _phase_verify re-writes it.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestInitMarkerClearedOnStart(unittest.TestCase):
    """Init run must clear stale marker immediately after Phase-1 PONR."""

    def test_headless_clears_marker(self):
        """_init_headless must cross Phase-1 PONR before clearing the marker."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        helper = src.split("def _cross_init_point_of_no_return", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("os.unlink(INIT_MARKER)", helper)
        headless = src.split("def _init_headless", 1)[1].split(
            "\ndef _headless_local_account", 1
        )[0]
        self.assertLess(
            headless.index("_begin_init_phase(phases[0], headless_total, ctx)"),
            headless.index(
                "_cross_init_point_of_no_return(cfg, ctx, clear_runtime_truth=True)"
            ),
        )

    def test_interactive_clears_marker(self):
        """cmd_init must cross Phase-1 PONR before clearing the marker."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        helper = src.split("def _cross_init_point_of_no_return", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("os.unlink(INIT_MARKER)", helper)
        prepare = src.split(
            "def _prepare_interactive_init_before_ponr",
            1,
        )[1].split("\ndef ", 1)[0]
        self.assertIn(
            "_begin_init_phase(phases[0], total, context, dry_run=dry_run)",
            prepare,
        )
        interactive = src.split("def cmd_init", 1)[1].split("\ndef _print_status_table", 1)[0]
        self.assertLess(
            interactive.index("_prepare_interactive_init_before_ponr("),
            interactive.index(
                "_cross_init_point_of_no_return(cfg, ctx, clear_runtime_truth=False)"
            ),
        )


class TestMarkerWrittenOnlyOnSuccess(unittest.TestCase):
    """_phase_verify must only write marker when fails == 0."""

    def test_verify_writes_on_success(self):
        """_phase_verify writes marker when fails == 0."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Find the "Mark initialized" block near the end of _phase_verify
        idx = src.find("Mark initialized — unreachable hosts are warnings")
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 800]
        self.assertIn("if fails == 0:", block)
        self.assertIn("open(INIT_MARKER", block)

    def test_phase_verify_is_only_marker_writer(self):
        """Headless/interactive summaries must not rewrite .initialized."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertEqual(
            src.count('open(INIT_MARKER, "w")'),
            1,
            ".initialized must be written only by _phase_verify",
        )

    def test_verify_does_not_write_on_failure(self):
        """_phase_verify returns False and skips marker write when fails > 0."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        idx = src.find('fmt.step_fail(f"NOT initialized')
        self.assertNotEqual(idx, -1)
        failure_branch = src[src.rfind("else:", 0, idx):idx + 300]
        self.assertIn("os.unlink(INIT_MARKER)", failure_branch)
        self.assertNotIn('open(INIT_MARKER, "w")', failure_branch)


if __name__ == "__main__":
    unittest.main()
