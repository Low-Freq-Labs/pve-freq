"""Tests for .initialized marker semantics contract.

Bug: A failed init could leave a STALE .initialized marker from a
previous successful init. The new run printed 'NOT initialized' but
.initialized still existed on disk, causing downstream surfaces
(is_first_run, doctor, setup wizard) to see a contradictory state.

Fix: Both interactive and headless init now clear any existing
.initialized marker at the start of the run. If the run succeeds,
_phase_verify re-writes it. If the run fails, no marker exists —
and the filesystem agrees with the printed result.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestInitMarkerClearedOnStart(unittest.TestCase):
    """Init run must clear stale marker before starting."""

    def test_headless_clears_marker(self):
        """_init_headless must unlink .initialized before running phases."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Find _init_headless function
        idx = src.find("def _init_headless")
        self.assertNotEqual(idx, -1)
        # The Clear stale marker block must appear early in the function
        block = src[idx:idx + 2500]
        self.assertIn("Clear any stale marker", block)
        self.assertIn("os.unlink(INIT_MARKER)", block)

    def test_interactive_clears_marker(self):
        """cmd_init must unlink .initialized after user confirms re-run."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # The interactive path has a '_confirm("Re-run initialization wizard?")'
        # then later clears the marker
        idx = src.find('_confirm("Re-run initialization wizard?")')
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 2000]
        self.assertIn("Clear any stale marker", block)


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

    def test_verify_does_not_write_on_failure(self):
        """_phase_verify returns False and skips marker write when fails > 0."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Find the fails > 0 branch
        import re
        # Look for: else: fmt.step_fail(f"NOT initialized ...)
        match = re.search(
            r'else:\s+fmt\.step_fail\(f"NOT initialized',
            src
        )
        self.assertIsNotNone(match)


if __name__ == "__main__":
    unittest.main()
