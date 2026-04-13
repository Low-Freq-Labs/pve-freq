"""Tests for Phase 12 verification time bound.

Bug: Clean headless init hung late in Phase 12 verification. The fleet
host loop ran serially: ~22 hosts × 20s VERIFY_TIMEOUT × retry paths
for legacy devices = potentially 500+ seconds. Combined with the
dashboard background probes (started at end of Phase 9) running their
own device verification commands, the process appeared hung.

Fix: Phase 12 fleet verification now runs in parallel (ThreadPoolExecutor,
8 workers) with a hard 90-second total cap. Any hosts that don't return
within the cap are recorded as 'Phase 12 timeout'. This guarantees
headless init completes or fails deterministically regardless of
slow/broken fleet hosts.

Also skips unmanaged hosts (managed=false) from the verification loop.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestPhase12Parallelized(unittest.TestCase):
    """Phase 12 fleet verification must be parallelized with a bounded timeout."""

    def test_uses_threadpool(self):
        """Fleet loop must use concurrent.futures.ThreadPoolExecutor."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Find the Phase 12 fleet verification section
        idx = src.find("Fleet host connectivity — ALL platform types")
        self.assertNotEqual(idx, -1)
        block = src[idx:idx + 3000]
        self.assertIn("ThreadPoolExecutor(max_workers=8)", block)

    def test_has_total_timeout_cap(self):
        """Must set PHASE12_FLEET_TIMEOUT and pass to as_completed."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("PHASE12_FLEET_TIMEOUT", src)
        self.assertIn("as_completed(futures, timeout=PHASE12_FLEET_TIMEOUT)", src)

    def test_handles_timeout_gracefully(self):
        """Must catch concurrent.futures.TimeoutError and record timeouts."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        idx = src.find("Fleet host connectivity — ALL platform types")
        block = src[idx:idx + 3000]
        self.assertIn("concurrent.futures.TimeoutError", block)
        self.assertIn("Phase 12 timeout", block)

    def test_timeout_is_reasonable(self):
        """PHASE12_FLEET_TIMEOUT must be between 30 and 300 seconds."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        import re
        match = re.search(r'PHASE12_FLEET_TIMEOUT\s*=\s*(\d+)', src)
        self.assertIsNotNone(match)
        timeout = int(match.group(1))
        self.assertGreaterEqual(timeout, 30)
        self.assertLessEqual(timeout, 300)


class TestUnmanagedHostsSkipped(unittest.TestCase):
    """Phase 12 must not verify unmanaged hosts."""

    def test_filters_managed_true(self):
        """Fleet loop must filter hosts by managed attribute."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        idx = src.find("Fleet host connectivity — ALL platform types")
        block = src[idx:idx + 3000]
        self.assertIn('getattr(h, "managed", True)', block)


if __name__ == "__main__":
    unittest.main()
