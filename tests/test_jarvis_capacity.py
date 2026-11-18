"""Tests for freq.jarvis.capacity — fleet capacity planner."""
import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

from freq.jarvis.capacity import (
    save_snapshot, load_snapshots, _capacity_dir,
    _parse_ram_pct, _parse_disk_pct, _linear_regression,
    compute_projections, should_snapshot, cmd_capacity,
    SNAPSHOT_PREFIX, MIN_WEEKS_FOR_PROJECTION,
)


class TestSnapshotIO(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cap_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_save_snapshot_creates_file(self):
        health = {"hosts": [{"label": "h1", "ram": "4096/8192MB", "disk": "50%", "load": "2.0", "status": "ok"}]}
        fname = save_snapshot(self.tmpdir, health)
        self.assertTrue(fname.startswith(SNAPSHOT_PREFIX))
        self.assertTrue(fname.endswith(".json"))

    def _case_save_and_load_roundtrip(self):
        health = {"hosts": [
            {"label": "h1", "ram": "4096/8192MB", "disk": "50%", "load": "2.0", "status": "ok", "docker": "3"},
            {"label": "h2", "ram": "1024/2048MB", "disk": "80%", "load": "1.0", "status": "ok"},
        ]}
        save_snapshot(self.tmpdir, health)
        snaps = load_snapshots(self.tmpdir)
        self.assertEqual(len(snaps), 1)
        self.assertIn("h1", snaps[0]["hosts"])
        self.assertEqual(snaps[0]["hosts"]["h1"]["ram"], "4096/8192MB")
        self.assertEqual(snaps[0]["hosts"]["h1"]["docker"], "3")

    def _case_load_empty_dir_returns_empty(self):
        self.assertEqual(load_snapshots(self.tmpdir), [])

    def _case_load_skips_corrupt_json(self):
        cap_dir = _capacity_dir(self.tmpdir)
        os.makedirs(cap_dir, exist_ok=True)
        with open(os.path.join(cap_dir, f"{SNAPSHOT_PREFIX}bad.json"), "w") as f:
            f.write("{{{invalid")
        self.assertEqual(load_snapshots(self.tmpdir), [])

    def _case_load_skips_non_snapshot_files(self):
        cap_dir = _capacity_dir(self.tmpdir)
        os.makedirs(cap_dir, exist_ok=True)
        with open(os.path.join(cap_dir, "readme.txt"), "w") as f:
            f.write("not a snapshot")
        self.assertEqual(load_snapshots(self.tmpdir), [])

    def _case_save_skips_empty_labels(self):
        health = {"hosts": [{"label": "", "ram": "100/200MB"}, {"label": "h1", "ram": "100/200MB"}]}
        save_snapshot(self.tmpdir, health)
        snaps = load_snapshots(self.tmpdir)
        self.assertEqual(len(snaps[0]["hosts"]), 1)
        self.assertIn("h1", snaps[0]["hosts"])


class TestParsing(unittest.TestCase):
    def _case_parse_ram_pct_valid(self):
        self.assertAlmostEqual(_parse_ram_pct("4096/8192MB"), 50.0, places=1)

    def _case_parse_ram_pct_full(self):
        self.assertAlmostEqual(_parse_ram_pct("8192/8192MB"), 100.0, places=1)

    def _case_parse_ram_pct_invalid(self):
        self.assertEqual(_parse_ram_pct("invalid"), -1)
        self.assertEqual(_parse_ram_pct(""), -1)
        self.assertEqual(_parse_ram_pct(None), -1)

    def _case_parse_ram_pct_zero_total(self):
        self.assertEqual(_parse_ram_pct("0/0MB"), -1)

    def _case_parse_disk_pct_valid(self):
        self.assertEqual(_parse_disk_pct("45%"), 45.0)

    def _case_parse_disk_pct_full(self):
        self.assertEqual(_parse_disk_pct("100%"), 100.0)

    def _case_parse_disk_pct_invalid(self):
        self.assertEqual(_parse_disk_pct("unknown"), -1)
        self.assertEqual(_parse_disk_pct(""), -1)
        self.assertEqual(_parse_disk_pct(None), -1)


class TestLinearRegression(unittest.TestCase):
    def _case_two_points(self):
        slope, intercept = _linear_regression([(0, 0), (1, 1)])
        self.assertAlmostEqual(slope, 1.0, places=3)
        self.assertAlmostEqual(intercept, 0.0, places=3)

    def _case_three_points_rising(self):
        slope, intercept = _linear_regression([(0, 10), (1, 20), (2, 30)])
        self.assertAlmostEqual(slope, 10.0, places=3)

    def _case_flat_line(self):
        slope, _ = _linear_regression([(0, 50), (1, 50), (2, 50)])
        self.assertAlmostEqual(slope, 0.0, places=3)

    def _case_negative_slope(self):
        slope, _ = _linear_regression([(0, 100), (1, 50), (2, 0)])
        self.assertTrue(slope < 0)

    def _case_single_point_returns_zero_slope(self):
        slope, _ = _linear_regression([(5, 50)])
        self.assertEqual(slope, 0)

    def _case_empty_returns_zero(self):
        slope, intercept = _linear_regression([])
        self.assertEqual(slope, 0)
        self.assertEqual(intercept, 0)

    def _case_identical_x_returns_zero_slope(self):
        slope, _ = _linear_regression([(5, 10), (5, 20)])
        self.assertEqual(slope, 0)


class TestProjections(unittest.TestCase):
    def _make_snapshots(self, count, ram_series=None, disk_series=None):
        """Generate count snapshots spaced 7 days apart."""
        snaps = []
        base = time.time() - (count * 7 * 86400)
        for i in range(count):
            epoch = base + i * 7 * 86400
            ram = ram_series[i] if ram_series else f"{4096 + i * 100}/8192MB"
            disk = disk_series[i] if disk_series else f"{40 + i * 2}%"
            snaps.append({
                "epoch": epoch,
                "hosts": {
                    "h1": {"ram": ram, "disk": disk, "load": str(2 + i * 0.1)},
                },
            })
        return snaps

    def _case_insufficient_data(self):
        snaps = self._make_snapshots(1)
        self.assertEqual(compute_projections(snaps), {})

    def _case_rising_trend(self):
        snaps = self._make_snapshots(4, ram_series=["4000/8192MB", "5000/8192MB", "6000/8192MB", "7000/8192MB"])
        proj = compute_projections(snaps)
        self.assertIn("h1", proj)
        self.assertIn("ram", proj["h1"])
        self.assertEqual(proj["h1"]["ram"]["trend_direction"], "rising")

    def _case_stable_trend(self):
        snaps = self._make_snapshots(4, ram_series=["4096/8192MB"] * 4)
        proj = compute_projections(snaps)
        self.assertIn("h1", proj)
        self.assertIn("ram", proj["h1"])
        self.assertEqual(proj["h1"]["ram"]["trend_direction"], "stable")

    def _case_falling_trend(self):
        snaps = self._make_snapshots(4, ram_series=["7000/8192MB", "6000/8192MB", "5000/8192MB", "4000/8192MB"])
        proj = compute_projections(snaps)
        self.assertIn("h1", proj)
        self.assertEqual(proj["h1"]["ram"]["trend_direction"], "falling")

    def _case_days_to_threshold_capped(self):
        # Very slight rise — days_to_80pct should be capped at 3650
        snaps = self._make_snapshots(3, ram_series=["100/8192MB", "101/8192MB", "102/8192MB"])
        proj = compute_projections(snaps)
        if "h1" in proj and "ram" in proj["h1"]:
            d = proj["h1"]["ram"]["days_to_80pct"]
            if d > 0:
                self.assertLessEqual(d, 3650)

    def _case_sparkline_present(self):
        snaps = self._make_snapshots(3)
        proj = compute_projections(snaps)
        if "h1" in proj and "ram" in proj["h1"]:
            self.assertIn("sparkline", proj["h1"]["ram"])
            self.assertIsInstance(proj["h1"]["ram"]["sparkline"], list)

    def _case_empty_snapshots(self):
        self.assertEqual(compute_projections([]), {})


class TestShouldSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cap_should_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_no_snapshots_returns_true(self):
        self.assertTrue(should_snapshot(self.tmpdir))

    def _case_recent_snapshot_returns_false(self):
        health = {"hosts": [{"label": "h1", "status": "ok"}]}
        save_snapshot(self.tmpdir, health)
        self.assertFalse(should_snapshot(self.tmpdir, interval_hours=168))

    def _case_old_snapshot_returns_true(self):
        cap_dir = _capacity_dir(self.tmpdir)
        os.makedirs(cap_dir, exist_ok=True)
        path = os.path.join(cap_dir, f"{SNAPSHOT_PREFIX}old.json")
        with open(path, "w") as f:
            json.dump({"epoch": time.time() - 800000}, f)
        self.assertTrue(should_snapshot(self.tmpdir, interval_hours=168))


class _LockProbe:
    def __init__(self):
        self.active = False
        self.entries = 0
        self.exits = 0

    def __enter__(self):
        if self.active:
            raise AssertionError("capacity snapshot lock entered recursively")
        self.active = True
        self.entries += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.active = False
        self.exits += 1


class _GuardedCache:
    def __init__(self, lock, health):
        self.lock = lock
        self.health = health

    def get(self, key):
        if not self.lock.active:
            raise AssertionError("capacity snapshot cache read without its owner lock")
        if key != "health":
            raise AssertionError(f"unexpected capacity snapshot cache key: {key}")
        return self.health


class TestCapacitySnapshotCommand(unittest.TestCase):
    def _run_snapshot(self, health, saved_name):
        from freq.modules import serve
        from freq.services import dashboard_state

        lock = _LockProbe()
        cache = _GuardedCache(lock, health)
        cfg = SimpleNamespace(data_dir="/var/lib/freq-test")
        args = SimpleNamespace(action="snapshot")

        with (
            mock.patch.object(serve, "_bg_cache", cache),
            mock.patch.object(serve, "_bg_lock", lock),
            mock.patch.object(dashboard_state, "background_cache", cache),
            mock.patch.object(dashboard_state, "background_cache_lock", lock),
            mock.patch("freq.jarvis.capacity.save_snapshot", return_value=saved_name) as save,
            mock.patch("freq.core.fmt.error") as error,
            mock.patch("freq.core.fmt.header") as header,
            mock.patch("freq.core.fmt.step_ok") as step_ok,
            mock.patch("freq.core.fmt.footer") as footer,
        ):
            result = cmd_capacity(cfg, None, args)

        self.assertEqual(lock.entries, 1)
        self.assertEqual(lock.exits, 1)
        self.assertFalse(lock.active)
        return result, cfg, save, error, header, step_ok, footer

    def _case_missing_health_fails_honestly(self):
        result, _, save, error, header, step_ok, footer = self._run_snapshot(None, "unused.json")

        self.assertEqual(result, 1)
        save.assert_not_called()
        error.assert_called_once_with("No health data available. Is freq serve running?")
        header.assert_not_called()
        step_ok.assert_not_called()
        footer.assert_not_called()

    def _case_snapshot_saves_exact_health_and_reports_success(self):
        health = {"hosts": [{"label": "pve1", "status": "ok"}]}
        result, cfg, save, error, header, step_ok, footer = self._run_snapshot(
            health, "capacity-20260717.json"
        )

        self.assertEqual(result, 0)
        self.assertIs(save.call_args.args[1], health)
        save.assert_called_once_with(cfg.data_dir, health)
        error.assert_not_called()
        header.assert_called_once_with("Capacity Snapshot")
        step_ok.assert_called_once_with("Saved: capacity-20260717.json")
        footer.assert_called_once_with()

    def _case_empty_save_result_stays_nonfatal_and_quiet(self):
        health = {"hosts": []}
        result, cfg, save, error, header, step_ok, footer = self._run_snapshot(health, "")

        self.assertEqual(result, 0)
        save.assert_called_once_with(cfg.data_dir, health)
        error.assert_not_called()
        header.assert_not_called()
        step_ok.assert_not_called()
        footer.assert_not_called()


SNAPSHOT_IO_CASES = (
    "_case_save_snapshot_creates_file", "_case_save_and_load_roundtrip",
    "_case_load_empty_dir_returns_empty", "_case_load_skips_corrupt_json",
    "_case_load_skips_non_snapshot_files", "_case_save_skips_empty_labels",
)
CAPACITY_PARSING_CASES = (
    "_case_parse_ram_pct_valid", "_case_parse_ram_pct_full", "_case_parse_ram_pct_invalid",
    "_case_parse_ram_pct_zero_total", "_case_parse_disk_pct_valid",
    "_case_parse_disk_pct_full", "_case_parse_disk_pct_invalid",
)
LINEAR_REGRESSION_CASES = (
    "_case_two_points", "_case_three_points_rising", "_case_flat_line",
    "_case_negative_slope", "_case_single_point_returns_zero_slope",
    "_case_empty_returns_zero", "_case_identical_x_returns_zero_slope",
)
CAPACITY_PROJECTION_CASES = (
    "_case_insufficient_data", "_case_rising_trend", "_case_stable_trend",
    "_case_falling_trend", "_case_days_to_threshold_capped",
    "_case_sparkline_present", "_case_empty_snapshots",
)
SHOULD_SNAPSHOT_CASES = (
    "_case_no_snapshots_returns_true", "_case_recent_snapshot_returns_false",
    "_case_old_snapshot_returns_true",
)
CAPACITY_SNAPSHOT_COMMAND_CASES = (
    "_case_missing_health_fails_honestly",
    "_case_snapshot_saves_exact_health_and_reports_success",
    "_case_empty_save_result_stays_nonfatal_and_quiet",
)


class TestSnapshotIOMatrix(unittest.TestCase):
    def test_snapshot_io_matrix(self):
        run_case_matrix(self, TestSnapshotIO, SNAPSHOT_IO_CASES)


class TestCapacityParsingMatrix(unittest.TestCase):
    def test_capacity_parsing_matrix(self):
        run_case_matrix(self, TestParsing, CAPACITY_PARSING_CASES)


class TestLinearRegressionMatrix(unittest.TestCase):
    def test_linear_regression_matrix(self):
        run_case_matrix(self, TestLinearRegression, LINEAR_REGRESSION_CASES)


class TestCapacityProjectionsMatrix(unittest.TestCase):
    def test_capacity_projections_matrix(self):
        run_case_matrix(self, TestProjections, CAPACITY_PROJECTION_CASES)


class TestShouldSnapshotMatrix(unittest.TestCase):
    def test_should_snapshot_matrix(self):
        run_case_matrix(self, TestShouldSnapshot, SHOULD_SNAPSHOT_CASES)


class TestCapacitySnapshotCommandMatrix(unittest.TestCase):
    def test_capacity_snapshot_command_matrix(self):
        run_case_matrix(self, TestCapacitySnapshotCommand, CAPACITY_SNAPSHOT_COMMAND_CASES)
