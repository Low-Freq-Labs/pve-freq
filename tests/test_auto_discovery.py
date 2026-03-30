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

    def test_simple_lowercase(self):
        self.assertEqual(sanitize_label("MyServer"), "myserver")

    def test_underscores_to_hyphens(self):
        self.assertEqual(sanitize_label("my_vm_host"), "my-vm-host")

    def test_spaces_to_hyphens(self):
        self.assertEqual(sanitize_label("my vm host"), "my-vm-host")

    def test_strips_special_chars(self):
        self.assertEqual(sanitize_label("test@server!#2"), "testserver2")

    def test_consecutive_hyphens_collapsed(self):
        self.assertEqual(sanitize_label("my--vm---host"), "my-vm-host")

    def test_leading_trailing_hyphens_stripped(self):
        self.assertEqual(sanitize_label("-leading-"), "leading")
        self.assertEqual(sanitize_label("---multi---"), "multi")

    def test_unicode_stripped(self):
        self.assertEqual(sanitize_label("café-server"), "caf-server")

    def test_max_length_truncation(self):
        long_name = "a" * 100
        result = sanitize_label(long_name)
        self.assertEqual(len(result), 64)
        self.assertEqual(result, "a" * 64)

    def test_truncation_strips_trailing_hyphen(self):
        # Name that would end with hyphen after truncation
        name = "a" * 63 + "-b"
        result = sanitize_label(name)
        self.assertLessEqual(len(result), 64)
        self.assertFalse(result.endswith("-"))

    def test_empty_returns_unknown(self):
        self.assertEqual(sanitize_label(""), "unknown")

    def test_all_special_chars_returns_unknown(self):
        self.assertEqual(sanitize_label("@#$%^&"), "unknown")

    def test_whitespace_only_returns_unknown(self):
        self.assertEqual(sanitize_label("   "), "unknown")

    def test_mixed_separators(self):
        self.assertEqual(sanitize_label("My_VM Host-2"), "my-vm-host-2")

    def test_dots_stripped(self):
        self.assertEqual(sanitize_label("web.server.01"), "webserver01")

    def test_preserves_numbers(self):
        self.assertEqual(sanitize_label("pve01"), "pve01")

    def test_already_safe(self):
        self.assertEqual(sanitize_label("clean-name-123"), "clean-name-123")


# ── is_protected_vmid with tags ─────────────────────────────────────

class TestIsProtectedVmid(unittest.TestCase):
    """Test VMID protection: PVE tags + static lists + ranges."""

    def test_prod_tag_protects(self):
        self.assertTrue(is_protected_vmid(500, [], [], vm_tags=["prod"]))

    def test_protected_tag_protects(self):
        self.assertTrue(is_protected_vmid(500, [], [], vm_tags=["protected"]))

    def test_unrelated_tag_no_protection(self):
        self.assertFalse(is_protected_vmid(500, [], [], vm_tags=["dev", "test"]))

    def test_tag_overrides_empty_static(self):
        self.assertTrue(is_protected_vmid(500, [], [], vm_tags=["prod"]))

    def test_static_id_protects(self):
        self.assertTrue(is_protected_vmid(900, [900, 901], []))

    def test_static_range_protects(self):
        self.assertTrue(is_protected_vmid(950, [], [(900, 999)]))

    def test_range_boundary_start(self):
        self.assertTrue(is_protected_vmid(900, [], [(900, 999)]))

    def test_range_boundary_end(self):
        self.assertTrue(is_protected_vmid(999, [], [(900, 999)]))

    def test_outside_range_not_protected(self):
        self.assertFalse(is_protected_vmid(899, [], [(900, 999)]))

    def test_tag_plus_static_both_protect(self):
        # Tag check is first, so this tests that both paths work
        self.assertTrue(is_protected_vmid(900, [900], [], vm_tags=["prod"]))

    def test_no_tags_no_static_not_protected(self):
        self.assertFalse(is_protected_vmid(500, [], []))

    def test_none_tags_falls_through(self):
        # vm_tags=None means tags not available, fall through to static
        self.assertFalse(is_protected_vmid(500, [], [], vm_tags=None))
        self.assertTrue(is_protected_vmid(500, [500], [], vm_tags=None))

    def test_empty_tags_falls_through(self):
        # Empty list means VM has no tags
        self.assertFalse(is_protected_vmid(500, [], [], vm_tags=[]))

    def test_invalid_vmid_returns_false(self):
        self.assertFalse(is_protected_vmid("not-a-number", [500], [(900, 999)]))

    def test_string_vmid_works(self):
        self.assertTrue(is_protected_vmid("900", [900], []))


# ── update_host_label ───────────────────────────────────────────────

class TestUpdateHostLabel(unittest.TestCase):
    """Test updating a host's label in hosts.conf by IP match."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.hosts_file = os.path.join(self.tmpdir, "hosts.conf")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cfg(self, lines):
        with open(self.hosts_file, "w") as f:
            f.write("\n".join(lines) + "\n")
        cfg = MagicMock()
        cfg.hosts_file = self.hosts_file
        return cfg

    def test_ip_match_updates_label(self):
        from freq.modules.hosts import update_host_label
        cfg = self._make_cfg([
            "# FREQ Fleet Registry",
            "192.168.10.1  old-name  linux  cluster",
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
            "192.168.10.1  server  linux",
        ])
        result = update_host_label(cfg, "192.168.10.99", "new-name")
        self.assertFalse(result)
        with open(self.hosts_file) as f:
            content = f.read()
        self.assertIn("server", content)

    def test_preserves_comments(self):
        from freq.modules.hosts import update_host_label
        cfg = self._make_cfg([
            "# This is a comment",
            "192.168.10.1  server  linux",
        ])
        update_host_label(cfg, "192.168.10.1", "renamed")
        with open(self.hosts_file) as f:
            lines = f.readlines()
        self.assertTrue(lines[0].startswith("#"))

    def test_preserves_type_and_groups(self):
        from freq.modules.hosts import update_host_label
        cfg = self._make_cfg([
            "192.168.10.1  server  docker  media,prod",
        ])
        update_host_label(cfg, "192.168.10.1", "new-server")
        with open(self.hosts_file) as f:
            content = f.read()
        self.assertIn("docker", content)
        self.assertIn("media,prod", content)

    def test_missing_file_returns_false(self):
        from freq.modules.hosts import update_host_label
        cfg = MagicMock()
        cfg.hosts_file = os.path.join(self.tmpdir, "nonexistent.conf")
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
        from freq.modules import serve
        from freq.core.types import Host

        vm = MagicMock()
        vm.label = "plex"
        vm.ip = "192.168.10.99"  # hardcoded fallback

        # Mock the imports inside _resolve_container_vm_ip
        mock_cfg = MagicMock()
        mock_cfg.hosts = [Host(ip="192.168.10.1", label="plex", htype="docker")]

        with patch.object(serve, 'load_config', return_value=mock_cfg):
            result = serve._resolve_container_vm_ip(vm)
        self.assertEqual(result, "192.168.10.1")

    def test_falls_back_to_hardcoded_ip(self):
        from freq.modules import serve

        vm = MagicMock()
        vm.label = "nonexistent"
        vm.ip = "192.168.10.99"

        mock_cfg = MagicMock()
        mock_cfg.hosts = []

        with patch.object(serve, 'load_config', return_value=mock_cfg):
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
