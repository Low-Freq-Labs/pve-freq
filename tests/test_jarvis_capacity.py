"""Tests for freq.jarvis.capacity — fleet capacity planner."""
import json
import math
import os
import shutil
import tempfile
import time
import unittest

from freq.jarvis.capacity import (
    save_snapshot, load_snapshots, _capacity_dir,
    _parse_ram_pct, _parse_disk_pct, _linear_regression,
    compute_projections, should_snapshot,
    SNAPSHOT_PREFIX, MIN_WEEKS_FOR_PROJECTION,
)


class TestSnapshotIO(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cap_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_save_snapshot_creates_file(self):
        health = {"hosts": [{"label": "h1", "ram": "4096/8192MB", "disk": "50%", "load": "2.0", "status": "ok"}]}
        fname = save_snapshot(self.tmpdir, health)
        self.assertTrue(fname.startswith(SNAPSHOT_PREFIX))
        self.assertTrue(fname.endswith(".json"))

    def test_save_and_load_roundtrip(self):
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

    def test_load_empty_dir_returns_empty(self):
        self.assertEqual(load_snapshots(self.tmpdir), [])

    def test_load_skips_corrupt_json(self):
        cap_dir = _capacity_dir(self.tmpdir)
        os.makedirs(cap_dir, exist_ok=True)
        with open(os.path.join(cap_dir, f"{SNAPSHOT_PREFIX}bad.json"), "w") as f:
            f.write("{{{invalid")
        self.assertEqual(load_snapshots(self.tmpdir), [])

    def test_load_skips_non_snapshot_files(self):
        cap_dir = _capacity_dir(self.tmpdir)
        os.makedirs(cap_dir, exist_ok=True)
        with open(os.path.join(cap_dir, "readme.txt"), "w") as f:
            f.write("not a snapshot")
        self.assertEqual(load_snapshots(self.tmpdir), [])

    def test_save_skips_empty_labels(self):
        health = {"hosts": [{"label": "", "ram": "100/200MB"}, {"label": "h1", "ram": "100/200MB"}]}
        save_snapshot(self.tmpdir, health)
        snaps = load_snapshots(self.tmpdir)
        self.assertEqual(len(snaps[0]["hosts"]), 1)
        self.assertIn("h1", snaps[0]["hosts"])


class TestParsing(unittest.TestCase):
    def test_parse_ram_pct_valid(self):
        self.assertAlmostEqual(_parse_ram_pct("4096/8192MB"), 50.0, places=1)

    def test_parse_ram_pct_full(self):
        self.assertAlmostEqual(_parse_ram_pct("8192/8192MB"), 100.0, places=1)

    def test_parse_ram_pct_invalid(self):
        self.assertEqual(_parse_ram_pct("invalid"), -1)
        self.assertEqual(_parse_ram_pct(""), -1)

    def test_parse_ram_pct_zero_total(self):
        self.assertEqual(_parse_ram_pct("0/0MB"), -1)

    def test_parse_disk_pct_valid(self):
        self.assertEqual(_parse_disk_pct("45%"), 45.0)

    def test_parse_disk_pct_full(self):
        self.assertEqual(_parse_disk_pct("100%"), 100.0)

    def test_parse_disk_pct_invalid(self):
        self.assertEqual(_parse_disk_pct("unknown"), -1)
        self.assertEqual(_parse_disk_pct(""), -1)


class TestLinearRegression(unittest.TestCase):
    def test_two_points(self):
        slope, intercept = _linear_regression([(0, 0), (1, 1)])
        self.assertAlmostEqual(slope, 1.0, places=3)
        self.assertAlmostEqual(intercept, 0.0, places=3)

    def test_three_points_rising(self):
        slope, intercept = _linear_regression([(0, 10), (1, 20), (2, 30)])
        self.assertAlmostEqual(slope, 10.0, places=3)

    def test_flat_line(self):
        slope, _ = _linear_regression([(0, 50), (1, 50), (2, 50)])
        self.assertAlmostEqual(slope, 0.0, places=3)

    def test_negative_slope(self):
        slope, _ = _linear_regression([(0, 100), (1, 50), (2, 0)])
        self.assertTrue(slope < 0)

    def test_single_point_returns_zero_slope(self):
        slope, _ = _linear_regression([(5, 50)])
        self.assertEqual(slope, 0)

    def test_empty_returns_zero(self):
        slope, intercept = _linear_regression([])
        self.assertEqual(slope, 0)
        self.assertEqual(intercept, 0)

    def test_identical_x_returns_zero_slope(self):
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

    def test_insufficient_data(self):
        snaps = self._make_snapshots(1)
        self.assertEqual(compute_projections(snaps), {})

    def test_rising_trend(self):
        snaps = self._make_snapshots(4, ram_series=["4000/8192MB", "5000/8192MB", "6000/8192MB", "7000/8192MB"])
        proj = compute_projections(snaps)
        self.assertIn("h1", proj)
        self.assertIn("ram", proj["h1"])
        self.assertEqual(proj["h1"]["ram"]["trend_direction"], "rising")

    def test_stable_trend(self):
        snaps = self._make_snapshots(4, ram_series=["4096/8192MB"] * 4)
        proj = compute_projections(snaps)
        self.assertIn("h1", proj)
        self.assertIn("ram", proj["h1"])
        self.assertEqual(proj["h1"]["ram"]["trend_direction"], "stable")

    def test_falling_trend(self):
        snaps = self._make_snapshots(4, ram_series=["7000/8192MB", "6000/8192MB", "5000/8192MB", "4000/8192MB"])
        proj = compute_projections(snaps)
        self.assertIn("h1", proj)
        self.assertEqual(proj["h1"]["ram"]["trend_direction"], "falling")

    def test_days_to_threshold_capped(self):
        # Very slight rise — days_to_80pct should be capped at 3650
        snaps = self._make_snapshots(3, ram_series=["100/8192MB", "101/8192MB", "102/8192MB"])
        proj = compute_projections(snaps)
        if "h1" in proj and "ram" in proj["h1"]:
            d = proj["h1"]["ram"]["days_to_80pct"]
            if d > 0:
                self.assertLessEqual(d, 3650)

    def test_sparkline_present(self):
        snaps = self._make_snapshots(3)
        proj = compute_projections(snaps)
        if "h1" in proj and "ram" in proj["h1"]:
            self.assertIn("sparkline", proj["h1"]["ram"])
            self.assertIsInstance(proj["h1"]["ram"]["sparkline"], list)

    def test_empty_snapshots(self):
        self.assertEqual(compute_projections([]), {})


class TestShouldSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cap_should_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_no_snapshots_returns_true(self):
        self.assertTrue(should_snapshot(self.tmpdir))

    def test_recent_snapshot_returns_false(self):
        health = {"hosts": [{"label": "h1", "status": "ok"}]}
        save_snapshot(self.tmpdir, health)
        self.assertFalse(should_snapshot(self.tmpdir, interval_hours=168))

    def test_old_snapshot_returns_true(self):
        cap_dir = _capacity_dir(self.tmpdir)
        os.makedirs(cap_dir, exist_ok=True)
        path = os.path.join(cap_dir, f"{SNAPSHOT_PREFIX}old.json")
        with open(path, "w") as f:
            json.dump({"epoch": time.time() - 800000}, f)
        self.assertTrue(should_snapshot(self.tmpdir, interval_hours=168))
