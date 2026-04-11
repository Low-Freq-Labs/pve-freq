"""Tests for serve.py cache system and background probe logic — Tier 5B.

Covers:
- _cache_path() — cache file path generation for various key names
- _save_disk_cache() / _load_disk_cache() — disk persistence round-trip
- Disk cache expiry (stale timestamps)
- Disk cache corruption handling (invalid JSON on disk)
- _bg_cache / _bg_cache_ts / _bg_lock — in-memory cache + thread safety
- _bg_probe_health() — background health probe (mocked SSH)
- _bg_probe_infra() — background infra probe (mocked SSH)
- BG_CACHE_REFRESH_INTERVAL constant validation
"""
import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════
# 1. Cache path generation
# ═══════════════════════════════════════════════════════════════════

class TestCachePathGeneration(unittest.TestCase):
    """_cache_path(name) builds the correct filesystem path."""

    def setUp(self):
        from freq.modules.serve import _cache_path, _init_cache_dir, _get_cache_dir
        _init_cache_dir()
        self.fn = _cache_path
        self.cache_dir = _get_cache_dir()

    def test_health_key(self):
        p = self.fn("health")
        self.assertEqual(p, os.path.join(self.cache_dir, "health.json"))

    def test_infra_quick_key(self):
        p = self.fn("infra_quick")
        self.assertEqual(p, os.path.join(self.cache_dir, "infra_quick.json"))

    def test_arbitrary_key_format(self):
        p = self.fn("my_custom_probe")
        self.assertTrue(p.endswith("my_custom_probe.json"))
        self.assertTrue(p.startswith(self.cache_dir))

    def test_empty_key(self):
        """Empty string key should still produce a valid path."""
        p = self.fn("")
        self.assertEqual(p, os.path.join(self.cache_dir, ".json"))

    def test_idempotent(self):
        self.assertEqual(self.fn("health"), self.fn("health"))


# ═══════════════════════════════════════════════════════════════════
# 2. Disk cache write/read cycle
# ═══════════════════════════════════════════════════════════════════

class TestDiskCacheWriteRead(unittest.TestCase):
    """Round-trip: _save_disk_cache → file → _load_disk_cache."""

    def setUp(self):
        import tempfile, shutil
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cache_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _patch_cache_dir(self):
        return patch("freq.modules.serve.CACHE_DIR", self.tmpdir)

    def _patch_cache_path(self, key):
        fpath = os.path.join(self.tmpdir, f"{key}.json")
        return patch("freq.modules.serve._cache_path", return_value=fpath), fpath

    def test_save_creates_file(self):
        from freq.modules.serve import _save_disk_cache
        fpath = os.path.join(self.tmpdir, "health.json")
        with self._patch_cache_dir(), \
             patch("freq.modules.serve._cache_path", return_value=fpath):
            _save_disk_cache("health", {"hosts": []})
        self.assertTrue(os.path.isfile(fpath))

    def test_save_writes_valid_json_with_data_and_ts(self):
        from freq.modules.serve import _save_disk_cache
        fpath = os.path.join(self.tmpdir, "health.json")
        with self._patch_cache_dir(), \
             patch("freq.modules.serve._cache_path", return_value=fpath):
            _save_disk_cache("health", {"count": 7})
        with open(fpath) as f:
            blob = json.load(f)
        self.assertEqual(blob["data"]["count"], 7)
        self.assertIn("ts", blob)
        self.assertIsInstance(blob["ts"], float)

    def test_load_restores_data_into_bg_cache(self):
        """Save then load — _bg_cache[key] should contain the data."""
        from freq.modules.serve import (
            _save_disk_cache, _load_disk_cache, _bg_cache, _bg_cache_ts, _bg_lock,
        )
        # Save health data
        fpath_h = os.path.join(self.tmpdir, "health.json")
        fpath_i = os.path.join(self.tmpdir, "infra_quick.json")

        def fake_path(name):
            return os.path.join(self.tmpdir, f"{name}.json")

        with self._patch_cache_dir(), \
             patch("freq.modules.serve._cache_path", side_effect=fake_path):
            _save_disk_cache("health", {"hosts": ["a", "b"]})
            # Clear in-memory cache
            with _bg_lock:
                _bg_cache["health"] = None
                _bg_cache_ts["health"] = 0
            # Load from disk
            _load_disk_cache()

        with _bg_lock:
            self.assertEqual(_bg_cache["health"], {"hosts": ["a", "b"]})
            self.assertGreater(_bg_cache_ts["health"], 0)

    def test_save_timestamp_is_recent(self):
        from freq.modules.serve import _save_disk_cache
        fpath = os.path.join(self.tmpdir, "test.json")
        before = time.time()
        with self._patch_cache_dir(), \
             patch("freq.modules.serve._cache_path", return_value=fpath):
            _save_disk_cache("test", {})
        with open(fpath) as f:
            ts = json.load(f)["ts"]
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, time.time())


# ═══════════════════════════════════════════════════════════════════
# 3. Disk cache expiry (stale timestamps)
# ═══════════════════════════════════════════════════════════════════

class TestDiskCacheExpiry(unittest.TestCase):
    """_load_disk_cache reads ts from file — stale data is still loaded
    but callers can check _bg_cache_ts to decide freshness."""

    def setUp(self):
        import tempfile, shutil
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cache_exp_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_stale_timestamp_still_loaded(self):
        """_load_disk_cache loads the ts from disk regardless of age."""
        from freq.modules.serve import _load_disk_cache, _bg_cache, _bg_cache_ts, _bg_lock
        stale_ts = time.time() - 99999
        fpath = os.path.join(self.tmpdir, "health.json")
        with open(fpath, "w") as f:
            json.dump({"data": {"stale": True}, "ts": stale_ts}, f)

        def fake_path(name):
            return os.path.join(self.tmpdir, f"{name}.json")

        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir), \
             patch("freq.modules.serve._cache_path", side_effect=fake_path):
            _load_disk_cache()

        with _bg_lock:
            self.assertEqual(_bg_cache["health"], {"stale": True})
            self.assertAlmostEqual(_bg_cache_ts["health"], stale_ts, places=1)

    def test_missing_ts_defaults_to_zero(self):
        """If JSON has no 'ts' key, timestamp defaults to 0."""
        from freq.modules.serve import _load_disk_cache, _bg_cache_ts, _bg_lock
        fpath = os.path.join(self.tmpdir, "health.json")
        with open(fpath, "w") as f:
            json.dump({"data": {"ok": True}}, f)

        def fake_path(name):
            return os.path.join(self.tmpdir, f"{name}.json")

        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir), \
             patch("freq.modules.serve._cache_path", side_effect=fake_path):
            _load_disk_cache()

        with _bg_lock:
            self.assertEqual(_bg_cache_ts["health"], 0)


# ═══════════════════════════════════════════════════════════════════
# 4. Disk cache corruption handling
# ═══════════════════════════════════════════════════════════════════

class TestDiskCacheCorruption(unittest.TestCase):
    """Invalid JSON on disk must not crash _load_disk_cache."""

    def setUp(self):
        import tempfile, shutil
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cache_corrupt_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_invalid_json_does_not_crash(self):
        from freq.modules.serve import _load_disk_cache, _bg_cache, _bg_lock
        # Reset shared state so we can verify corruption leaves it untouched
        with _bg_lock:
            _bg_cache["health"] = None
            _bg_cache["infra_quick"] = None

        fpath = os.path.join(self.tmpdir, "health.json")
        with open(fpath, "w") as f:
            f.write("{{{invalid json!!")

        def fake_path(name):
            return os.path.join(self.tmpdir, f"{name}.json")

        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir), \
             patch("freq.modules.serve._cache_path", side_effect=fake_path):
            # Must not raise
            _load_disk_cache()

        # health should remain None (not updated by corrupt file)
        with _bg_lock:
            self.assertIsNone(_bg_cache["health"])

    def test_empty_file_does_not_crash(self):
        from freq.modules.serve import _load_disk_cache
        fpath = os.path.join(self.tmpdir, "health.json")
        with open(fpath, "w") as f:
            f.write("")

        def fake_path(name):
            return os.path.join(self.tmpdir, f"{name}.json")

        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir), \
             patch("freq.modules.serve._cache_path", side_effect=fake_path):
            _load_disk_cache()  # must not raise

    def test_truncated_json_does_not_crash(self):
        from freq.modules.serve import _load_disk_cache
        fpath = os.path.join(self.tmpdir, "health.json")
        with open(fpath, "w") as f:
            f.write('{"data": {"ho')  # truncated

        def fake_path(name):
            return os.path.join(self.tmpdir, f"{name}.json")

        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir), \
             patch("freq.modules.serve._cache_path", side_effect=fake_path):
            _load_disk_cache()  # must not raise


# ═══════════════════════════════════════════════════════════════════
# 5. _save_disk_cache error handling
# ═══════════════════════════════════════════════════════════════════

class TestSaveDiskCacheErrors(unittest.TestCase):
    """_save_disk_cache swallows OSError gracefully."""

    def setUp(self):
        import tempfile, shutil
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cache_err_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_write_to_directory_path_does_not_raise(self):
        from freq.modules.serve import _save_disk_cache
        # Point _cache_path at a directory — open() will fail with IsADirectoryError
        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir), \
             patch("freq.modules.serve._cache_path", return_value=self.tmpdir):
            _save_disk_cache("test", {"a": 1})  # must not raise


# ═══════════════════════════════════════════════════════════════════
# 6. Background probe: health data structure (mocked SSH)
# ═══════════════════════════════════════════════════════════════════

def _make_ssh_result(rc=0, stdout="", stderr=""):
    """Create a fake SSH result object."""
    r = MagicMock()
    r.returncode = rc
    r.stdout = stdout
    r.stderr = stderr
    return r


def _make_host(label, ip, htype="linux", groups=""):
    """Create a fake Host dataclass-like object."""
    h = MagicMock()
    h.label = label
    h.ip = ip
    h.htype = htype
    h.groups = groups
    return h


def _make_cfg_for_health(hosts, container_vms=None, ssh_key_path="/tmp/k",
                          ssh_rsa_key_path=None, ssh_connect_timeout=2, ssh_max_parallel=2):
    cfg = MagicMock()
    cfg.hosts = hosts
    cfg.container_vms = container_vms or {}
    cfg.ssh_key_path = ssh_key_path
    cfg.ssh_rsa_key_path = ssh_rsa_key_path
    cfg.ssh_connect_timeout = ssh_connect_timeout
    cfg.ssh_max_parallel = ssh_max_parallel
    return cfg


class TestBgProbeHealth(unittest.TestCase):
    """_bg_probe_health() structure and cache update with mocked SSH."""

    def _run_probe(self, hosts, ssh_side_effect):
        from freq.modules.serve import _bg_probe_health, _bg_cache, _bg_cache_ts, _bg_lock
        cfg = _make_cfg_for_health(hosts)

        with patch("freq.modules.serve.load_config", return_value=cfg), \
             patch("freq.modules.serve.ssh_single", side_effect=ssh_side_effect), \
             patch("freq.modules.serve._save_disk_cache"), \
             patch("os.path.isfile", return_value=False):
            _bg_probe_health()

        with _bg_lock:
            return _bg_cache["health"], _bg_cache_ts["health"]

    def test_healthy_linux_host(self):
        hosts = [_make_host("web01", "10.0.0.1")]
        ssh_out = "web01|4|1024/4096MB|23%|0.42|3"
        data, ts = self._run_probe(hosts, [_make_ssh_result(0, ssh_out)])

        self.assertIn("hosts", data)
        self.assertEqual(len(data["hosts"]), 1)
        h = data["hosts"][0]
        self.assertEqual(h["label"], "web01")
        self.assertEqual(h["status"], "healthy")
        self.assertEqual(h["cores"], "4")
        self.assertEqual(h["ram"], "1024/4096MB")
        self.assertEqual(h["disk"], "23%")
        self.assertEqual(h["load"], "0.42")
        self.assertEqual(h["docker"], "3")

    def test_unreachable_host(self):
        hosts = [_make_host("dead01", "10.0.0.99")]
        data, _ = self._run_probe(hosts, [_make_ssh_result(1, "")])

        h = data["hosts"][0]
        self.assertEqual(h["status"], "unreachable")
        self.assertEqual(h["cores"], "-")
        self.assertEqual(h["ram"], "-")

    def test_result_has_duration_and_probed_at(self):
        hosts = [_make_host("h1", "10.0.0.1")]
        data, _ = self._run_probe(hosts, [_make_ssh_result(0, "h1|2|512/1024MB|10%|0.1|0")])

        self.assertIn("duration", data)
        self.assertIn("probed_at", data)
        self.assertIsInstance(data["duration"], float)
        self.assertIsInstance(data["probed_at"], float)

    def test_multiple_hosts(self):
        hosts = [
            _make_host("h1", "10.0.0.1"),
            _make_host("h2", "10.0.0.2"),
        ]
        data, _ = self._run_probe(hosts, [
            _make_ssh_result(0, "h1|2|512/1024MB|10%|0.1|0"),
            _make_ssh_result(0, "h2|8|2048/8192MB|55%|1.5|5"),
        ])
        self.assertEqual(len(data["hosts"]), 2)

    def test_cache_ts_updated(self):
        before = time.time()
        hosts = [_make_host("h1", "10.0.0.1")]
        _, ts = self._run_probe(hosts, [_make_ssh_result(0, "h1|1|64/128MB|5%|0.0|0")])
        self.assertGreaterEqual(ts, before)

    def test_config_load_failure_returns_early(self):
        """If load_config raises, probe should return without crashing."""
        from freq.modules.serve import _bg_probe_health, _bg_cache, _bg_lock
        with _bg_lock:
            _bg_cache["health"] = "sentinel"
        with patch("freq.modules.serve.load_config", side_effect=RuntimeError("bad cfg")):
            _bg_probe_health()  # must not raise
        # Cache should remain untouched
        with _bg_lock:
            self.assertEqual(_bg_cache["health"], "sentinel")


# ═══════════════════════════════════════════════════════════════════
# 7. Background probe: infra data structure (mocked SSH)
# ═══════════════════════════════════════════════════════════════════

def _make_physical_device(key, ip, label, device_type):
    d = MagicMock()
    d.key = key
    d.ip = ip
    d.label = label
    d.device_type = device_type
    return d


def _make_cfg_for_infra(physical_devices, ssh_key_path="/tmp/k", ssh_rsa_key_path=None):
    cfg = MagicMock()
    fb = MagicMock()
    fb.physical = physical_devices  # dict of key -> PhysicalDevice mock
    cfg.fleet_boundaries = fb
    cfg.ssh_key_path = ssh_key_path
    cfg.ssh_rsa_key_path = ssh_rsa_key_path
    return cfg


class TestBgProbeInfra(unittest.TestCase):
    """_bg_probe_infra() structure and cache update with mocked SSH."""

    def _run_probe(self, devices_dict, ssh_side_effect):
        from freq.modules.serve import _bg_probe_infra, _bg_cache, _bg_cache_ts, _bg_lock
        cfg = _make_cfg_for_infra(devices_dict)

        with patch("freq.modules.serve.load_config", return_value=cfg), \
             patch("freq.modules.serve.ssh_single", side_effect=ssh_side_effect), \
             patch("freq.modules.serve._save_disk_cache"):
            _bg_probe_infra()

        with _bg_lock:
            return _bg_cache["infra_quick"], _bg_cache_ts["infra_quick"]

    def test_pfsense_device_reachable(self):
        devs = {"fw01": _make_physical_device("fw01", "10.0.0.1", "Firewall", "pfsense")}
        ssh_out = "150|up 30 days, 2 users|em0 em1 em2 lo0 enc0 pflog0"
        data, ts = self._run_probe(devs, [_make_ssh_result(0, ssh_out)])

        self.assertIn("devices", data)
        self.assertEqual(len(data["devices"]), 1)
        d = data["devices"][0]
        self.assertTrue(d["reachable"])
        self.assertEqual(d["metrics"]["states"], "150")

    def test_unreachable_device(self):
        devs = {"sw01": _make_physical_device("sw01", "10.0.0.2", "Switch", "switch")}
        data, _ = self._run_probe(devs, [_make_ssh_result(1, "")])

        d = data["devices"][0]
        self.assertFalse(d["reachable"])
        self.assertEqual(d["metrics"], {})

    def test_result_has_duration_and_probed_at(self):
        devs = {"fw01": _make_physical_device("fw01", "10.0.0.1", "Firewall", "pfsense")}
        data, _ = self._run_probe(devs, [_make_ssh_result(1, "")])

        self.assertIn("duration", data)
        self.assertIn("probed_at", data)

    def test_config_load_failure_returns_early(self):
        from freq.modules.serve import _bg_probe_infra, _bg_cache, _bg_lock
        with _bg_lock:
            _bg_cache["infra_quick"] = "sentinel"
        with patch("freq.modules.serve.load_config", side_effect=RuntimeError("bad")):
            _bg_probe_infra()
        with _bg_lock:
            self.assertEqual(_bg_cache["infra_quick"], "sentinel")


# ═══════════════════════════════════════════════════════════════════
# 8. Thread safety of _bg_cache with _bg_lock
# ═══════════════════════════════════════════════════════════════════

class TestThreadSafety(unittest.TestCase):
    """Concurrent access to _bg_cache through _bg_lock."""

    def test_lock_is_threading_lock(self):
        from freq.modules.serve import _bg_lock
        self.assertIsInstance(_bg_lock, type(threading.Lock()))

    def test_concurrent_writes_do_not_corrupt(self):
        """Multiple threads writing to _bg_cache under _bg_lock
        should not produce corrupted state."""
        from freq.modules.serve import _bg_cache, _bg_cache_ts, _bg_lock

        errors = []

        def writer(val):
            try:
                for _ in range(50):
                    with _bg_lock:
                        _bg_cache["health"] = {"v": val}
                        _bg_cache_ts["health"] = float(val)
                        # Read back immediately — should be our value
                        read_back = _bg_cache["health"]["v"]
                        if read_back != val:
                            errors.append(f"expected {val}, got {read_back}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [], f"Thread safety errors: {errors}")

    def test_lock_protects_read_during_write(self):
        """Reads under lock see a consistent snapshot."""
        from freq.modules.serve import _bg_cache, _bg_cache_ts, _bg_lock

        with _bg_lock:
            _bg_cache["health"] = {"snapshot": True}
            _bg_cache_ts["health"] = 999.0
            self.assertEqual(_bg_cache["health"]["snapshot"], True)
            self.assertEqual(_bg_cache_ts["health"], 999.0)


# ═══════════════════════════════════════════════════════════════════
# 9. Cache refresh interval constant validation
# ═══════════════════════════════════════════════════════════════════

class TestCacheConstants(unittest.TestCase):
    """Validate cache-related module constants."""

    def test_refresh_interval_is_positive_int(self):
        from freq.modules.serve import BG_CACHE_REFRESH_INTERVAL
        self.assertIsInstance(BG_CACHE_REFRESH_INTERVAL, int)
        self.assertGreater(BG_CACHE_REFRESH_INTERVAL, 0)

    def test_refresh_interval_is_15(self):
        from freq.modules.serve import BG_CACHE_REFRESH_INTERVAL
        self.assertEqual(BG_CACHE_REFRESH_INTERVAL, 15)

    def test_cache_dir_is_string_path(self):
        from freq.modules.serve import _init_cache_dir, CACHE_DIR
        if CACHE_DIR is None:
            _init_cache_dir()
        from freq.modules.serve import CACHE_DIR as resolved
        self.assertIsInstance(resolved, str)
        self.assertTrue(resolved.endswith(os.path.join("data", "cache")))

    def test_bg_cache_has_expected_keys(self):
        from freq.modules.serve import _bg_cache
        self.assertIn("health", _bg_cache)
        self.assertIn("infra_quick", _bg_cache)

    def test_bg_cache_ts_matches_cache_keys(self):
        from freq.modules.serve import _bg_cache, _bg_cache_ts
        self.assertEqual(set(_bg_cache.keys()), set(_bg_cache_ts.keys()))


# ═══════════════════════════════════════════════════════════════════
# SSE Event Bus
# ═══════════════════════════════════════════════════════════════════

class TestSSEEventBus(unittest.TestCase):
    """Tests for the SSE pub/sub mechanism."""

    def setUp(self):
        from freq.modules.serve import _sse_clients, _sse_lock
        # Clear any leftover clients between tests
        with _sse_lock:
            _sse_clients.clear()

    def tearDown(self):
        from freq.modules.serve import _sse_clients, _sse_lock
        with _sse_lock:
            _sse_clients.clear()

    def test_subscribe_adds_client(self):
        from freq.modules.serve import _sse_subscribe, _sse_clients
        q = _sse_subscribe()
        self.assertIn(q, _sse_clients)

    def test_unsubscribe_removes_client(self):
        from freq.modules.serve import _sse_subscribe, _sse_unsubscribe, _sse_clients
        q = _sse_subscribe()
        _sse_unsubscribe(q)
        self.assertNotIn(q, _sse_clients)

    def test_unsubscribe_missing_is_safe(self):
        import queue as _q
        from freq.modules.serve import _sse_unsubscribe
        _sse_unsubscribe(_q.Queue())  # Should not raise

    def test_broadcast_delivers_to_all(self):
        from freq.modules.serve import _sse_subscribe, _sse_broadcast
        q1 = _sse_subscribe()
        q2 = _sse_subscribe()
        _sse_broadcast("cache_update", {"key": "health"})
        self.assertFalse(q1.empty())
        self.assertFalse(q2.empty())
        msg1 = q1.get_nowait()
        msg2 = q2.get_nowait()
        self.assertEqual(msg1["type"], "cache_update")
        self.assertEqual(msg2["data"]["key"], "health")

    def test_broadcast_drops_slow_client(self):
        import queue as _q
        from freq.modules.serve import _sse_subscribe, _sse_broadcast, _sse_clients
        q = _sse_subscribe()
        # Fill the queue (maxsize=50)
        for i in range(50):
            q.put_nowait({"type": "filler", "data": {}})
        # Next broadcast should drop this client
        _sse_broadcast("cache_update", {"key": "test"})
        self.assertNotIn(q, _sse_clients)

    def test_broadcast_no_clients_is_safe(self):
        from freq.modules.serve import _sse_broadcast
        _sse_broadcast("test", {"foo": "bar"})  # Should not raise

    def test_broadcast_event_structure(self):
        from freq.modules.serve import _sse_subscribe, _sse_broadcast
        q = _sse_subscribe()
        _sse_broadcast("vm_state", {"vmid": 100, "old": "running", "new": "stopped"})
        msg = q.get_nowait()
        self.assertEqual(msg["type"], "vm_state")
        self.assertEqual(msg["data"]["vmid"], 100)
        self.assertEqual(msg["data"]["old"], "running")


if __name__ == "__main__":
    unittest.main()
