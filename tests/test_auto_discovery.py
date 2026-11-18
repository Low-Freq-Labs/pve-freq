"""FREQ Auto-Discovery Tests — validate.sanitize_label, is_protected_vmid (tags),
update_host_label, resolve_host_ip, serve.get_vm_tags, _resolve_container_vm_ip.

All SSH/PVE calls are mocked. Tests cover edge cases found during v2.2.0 audit.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.core.validate import sanitize_label, is_protected_vmid


# ── sanitize_label ──────────────────────────────────────────────────

class TestSanitizeLabel(unittest.TestCase):
    """Test PVE VM name → safe host label conversion."""

    CASES = (
        ("simple-lowercase", "MyServer", "myserver"),
        ("underscores", "my_vm_host", "my-vm-host"),
        ("spaces", "my vm host", "my-vm-host"),
        ("special-characters", "test@server!#2", "testserver2"),
        ("consecutive-hyphens", "my--vm---host", "my-vm-host"),
        ("leading-trailing-hyphen", "-leading-", "leading"),
        ("multiple-edge-hyphens", "---multi---", "multi"),
        ("unicode", "café-server", "caf-server"),
        ("maximum-length-truncation", "a" * 100, "a" * 64),
        ("truncation-strips-trailing-hyphen", "a" * 63 + "-b", "a" * 63),
        ("empty", "", "unknown"),
        ("all-special-characters", "@#$%^&", "unknown"),
        ("whitespace-only", "   ", "unknown"),
        ("mixed-separators", "My_VM Host-2", "my-vm-host-2"),
        ("dots-stripped", "web.server.01", "webserver01"),
        ("numbers-preserved", "pve01", "pve01"),
        ("already-safe", "clean-name-123", "clean-name-123"),
    )

    def test_sanitize_label_matrix(self):
        self.assertEqual(len(self.CASES), 17)
        case_ids = tuple(case_id for case_id, _, _ in self.CASES)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case_id, value, expected in self.CASES:
            with self.subTest(case=case_id, value=value):
                self.assertEqual(sanitize_label(value), expected)


# ── is_protected_vmid with tags ─────────────────────────────────────

class TestIsProtectedVmid(unittest.TestCase):
    """Test VMID protection: PVE tags + static lists + ranges."""

    CASES = (
        ("prod-tag", 500, [], [], ["prod"], True, True),
        ("protected-tag", 500, [], [], ["protected"], True, True),
        ("unrelated-tags", 500, [], [], ["dev", "test"], False, True),
        ("static-id", 900, [900, 901], [], None, True, False),
        ("static-range-midpoint", 950, [], [(900, 999)], None, True, False),
        ("static-range-start", 900, [], [(900, 999)], None, True, False),
        ("static-range-end", 999, [], [(900, 999)], None, True, False),
        ("outside-static-range", 899, [], [(900, 999)], None, False, False),
        ("tag-and-static", 900, [900], [], ["prod"], True, True),
        ("omitted-tags-no-static", 500, [], [], None, False, False),
        ("none-tags-no-static", 500, [], [], None, False, True),
        ("none-tags-static-fallback", 500, [500], [], None, True, True),
        ("empty-tags", 500, [], [], [], False, True),
        ("invalid-vmid", "not-a-number", [500], [(900, 999)], None, False, False),
        ("string-vmid", "900", [900], [], None, True, False),
    )

    def test_protected_vmid_policy_matrix(self):
        self.assertEqual(len(self.CASES), 15)
        case_ids = tuple(case_id for case_id, *_rest in self.CASES)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case_id, value, protected_ids, protected_ranges, tags, expected, pass_tags in self.CASES:
            with self.subTest(case=case_id, value=value):
                if pass_tags:
                    actual = is_protected_vmid(
                        value,
                        protected_ids,
                        protected_ranges,
                        vm_tags=tags,
                    )
                else:
                    actual = is_protected_vmid(value, protected_ids, protected_ranges)
                self.assertIs(actual, expected)

# ── update_host_label ───────────────────────────────────────────────

class TestUpdateHostLabel(unittest.TestCase):
    """Test updating a host's label in hosts.toml by IP match."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.hosts_file = os.path.join(self.tmpdir, "hosts.toml")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, hosts):
        from freq.core.config import Host, save_hosts_toml
        host_objs = [Host(**h) for h in hosts]
        save_hosts_toml(self.hosts_file, host_objs)
        cfg = MagicMock()
        cfg.hosts_file = self.hosts_file
        cfg.hosts = host_objs
        return cfg

    def test_ip_match_updates_label(self):
        from freq.modules.hosts import update_host_label
        cfg = self._make_cfg([
            {"ip": "192.168.10.1", "label": "old-name", "htype": "linux", "groups": "cluster"},
        ])
        result = update_host_label(cfg, "192.168.10.1", "new-name")
        self.assertTrue(result)
        with open(self.hosts_file) as f:
            content = f.read()
        self.assertIn("new-name", content)
        self.assertNotIn("old-name", content)

    def test_no_match_returns_false(self):
        from freq.modules.hosts import update_host_label
        cfg = self._make_cfg([
            {"ip": "192.168.10.1", "label": "server", "htype": "linux"},
        ])
        result = update_host_label(cfg, "192.168.10.99", "new-name")
        self.assertFalse(result)
        with open(self.hosts_file) as f:
            content = f.read()
        self.assertIn("server", content)

    def test_preserves_type_and_groups(self):
        from freq.modules.hosts import update_host_label
        cfg = self._make_cfg([
            {"ip": "192.168.10.1", "label": "server", "htype": "docker", "groups": "media,prod"},
        ])
        update_host_label(cfg, "192.168.10.1", "new-server")
        with open(self.hosts_file) as f:
            content = f.read()
        self.assertIn("docker", content)
        self.assertIn("media,prod", content)

    def test_missing_hosts_returns_false(self):
        from freq.modules.hosts import update_host_label
        cfg = MagicMock()
        cfg.hosts = []
        cfg.hosts_file = os.path.join(self.tmpdir, "nonexistent.toml")
        result = update_host_label(cfg, "10.0.0.1", "test")
        self.assertFalse(result)


# ── resolve_host_ip ─────────────────────────────────────────────────

class TestResolveHostIp(unittest.TestCase):
    """Test host IP lookup from hosts.conf by label."""

    def test_label_found(self):
        from freq.modules.hosts import resolve_host_ip
        from freq.core.types import Host
        cfg = MagicMock()
        cfg.hosts = [
            Host(ip="192.168.10.1", label="plex", htype="docker"),
            Host(ip="192.168.10.2", label="tdarr", htype="docker"),
        ]
        self.assertEqual(resolve_host_ip(cfg, "plex"), "192.168.10.1")

    def test_label_not_found(self):
        from freq.modules.hosts import resolve_host_ip
        from freq.core.types import Host
        cfg = MagicMock()
        cfg.hosts = [
            Host(ip="192.168.10.1", label="plex", htype="docker"),
        ]
        self.assertEqual(resolve_host_ip(cfg, "nonexistent"), "")

    def test_empty_hosts(self):
        from freq.modules.hosts import resolve_host_ip
        cfg = MagicMock()
        cfg.hosts = []
        self.assertEqual(resolve_host_ip(cfg, "anything"), "")


# ── get_vm_tags / is_vm_tagged ──────────────────────────────────────

class TestVmTagCache(unittest.TestCase):
    """Test serve.py VM tag cache accessors."""

    def test_get_vm_tags_cache_hit(self):
        from freq.modules import serve
        # Directly populate cache
        with serve._bg_lock:
            serve._bg_cache["vm_tags"] = {"tags": {100: ["prod", "critical"]}}
        result = serve.get_vm_tags(100)
        self.assertEqual(result, ["prod", "critical"])

    def test_get_vm_tags_cache_miss(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache["vm_tags"] = {"tags": {100: ["prod"]}}
        result = serve.get_vm_tags(999)
        self.assertEqual(result, [])

    def test_get_vm_tags_empty_cache(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache["vm_tags"] = None
        result = serve.get_vm_tags(100)
        self.assertEqual(result, [])

    def test_is_vm_tagged_true(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache["vm_tags"] = {"tags": {200: ["prod", "media"]}}
        self.assertTrue(serve.is_vm_tagged(200, "prod"))

    def test_is_vm_tagged_false(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache["vm_tags"] = {"tags": {200: ["dev"]}}
        self.assertFalse(serve.is_vm_tagged(200, "prod"))

    def test_is_vm_tagged_no_cache(self):
        from freq.modules import serve
        with serve._bg_lock:
            serve._bg_cache["vm_tags"] = None
        self.assertFalse(serve.is_vm_tagged(200, "prod"))


# ── _resolve_container_vm_ip ────────────────────────────────────────

class TestResolveContainerVmIp(unittest.TestCase):
    """Test container VM IP resolution from hosts.conf labels."""

    def test_resolves_from_label(self):
        from freq.core import config
        from freq.modules import serve
        from freq.core.types import Host

        vm = MagicMock()
        vm.label = "plex"
        vm.ip = "192.168.10.99"  # hardcoded fallback

        # Mock the imports inside _resolve_container_vm_ip
        mock_cfg = MagicMock()
        mock_cfg.hosts = [Host(ip="192.168.10.1", label="plex", htype="docker")]

        with patch.object(config, 'load_config', return_value=mock_cfg):
            result = serve._resolve_container_vm_ip(vm)
        self.assertEqual(result, "192.168.10.1")

    def test_falls_back_to_hardcoded_ip(self):
        from freq.core import config
        from freq.modules import serve

        vm = MagicMock()
        vm.label = "nonexistent"
        vm.ip = "192.168.10.99"

        mock_cfg = MagicMock()
        mock_cfg.hosts = []

        with patch.object(config, 'load_config', return_value=mock_cfg):
            result = serve._resolve_container_vm_ip(vm)
        self.assertEqual(result, "192.168.10.99")

    def test_no_label_returns_hardcoded_ip(self):
        from freq.modules import serve

        vm = MagicMock()
        vm.label = ""
        vm.ip = "192.168.10.99"

        result = serve._resolve_container_vm_ip(vm)
        self.assertEqual(result, "192.168.10.99")


if __name__ == "__main__":
    unittest.main()
