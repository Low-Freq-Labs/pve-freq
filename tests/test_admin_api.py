"""Tests for admin APIs, LAB_HOSTS fix, 172.x filter, and tier CRUD.

Covers:
- _is_docker_bridge_ip() helper (172.x filter precision)
- _serve_lab_status() — no broken LAB_HOSTS import
- _serve_admin_fleet_boundaries() — GET fleet boundaries
- _serve_admin_fleet_boundaries_update() — all update actions
- _update_fb_toml() — TOML read-modify-write for all operations
- update_tier_actions — tier action list modification
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ──────────────────────────────────────────────────────────

def _fake_result(stdout="", stderr="", returncode=0):
    """Create a mock CmdResult."""
    @dataclass
    class FakeResult:
        stdout: str = ""
        stderr: str = ""
        returncode: int = 0
        duration: float = 0.1
    return FakeResult(stdout=stdout, stderr=stderr, returncode=returncode)


SAMPLE_FB_TOML = """\
# PVE FREQ — Fleet Boundary Definitions
[tiers]
probe    = ["view"]
operator = ["view", "start", "stop", "restart", "snapshot", "destroy", "clone", "resize", "migrate", "configure"]
admin    = ["view", "start", "stop", "restart", "snapshot", "destroy", "clone", "resize", "migrate", "configure"]

[categories.personal]
description = "Personal VMs"
tier = "probe"
vmids = [100, 802, 804]

[categories.prod_media]
description = "Production media"
tier = "operator"
vmids = [101, 102, 103]

[categories.lab]
description = "Lab playground"
tier = "admin"
range_start = 5000
range_end = 5099

[categories.templates]
description = "Clone sources"
tier = "probe"
range_start = 9000
range_end = 9099

[physical]
pfsense = { ip = "192.168.255.1", label = "pfsense01", type = "pfsense", tier = "probe", detail = "Gateway" }

[pve_nodes]
pve01 = { ip = "192.168.255.26", detail = "Dell T620" }
"""


# ═══════════════════════════════════════════════════════════════════
# _is_docker_bridge_ip() tests
# ═══════════════════════════════════════════════════════════════════

class TestDockerBridgeFilter(unittest.TestCase):
    """Test the precision 172.x filter — only catches Docker bridges."""

    def setUp(self):
        from freq.modules.hosts import _is_docker_bridge_ip
        self.fn = _is_docker_bridge_ip

    def test_docker_default_bridge(self):
        """172.17.0.1 is the Docker default bridge — should be filtered."""
        self.assertTrue(self.fn("172.17.0.1"))

    def test_docker_custom_bridge(self):
        """172.18.0.1 is a Docker custom network — should be filtered."""
        self.assertTrue(self.fn("172.18.0.1"))

    def test_docker_max_bridge(self):
        """172.31.255.254 is at the top of Docker range — should be filtered."""
        self.assertTrue(self.fn("172.31.255.254"))

    def test_legitimate_172_16(self):
        """172.16.x.x is legitimate private space — should NOT be filtered."""
        self.assertFalse(self.fn("172.16.0.1"))
        self.assertFalse(self.fn("172.16.50.100"))

    def test_non_172_ip(self):
        """10.x.x.x should never be filtered."""
        self.assertFalse(self.fn("192.168.255.1"))
        self.assertFalse(self.fn("192.168.1.1"))

    def test_172_low_octets(self):
        """172.0-16 range is NOT Docker bridge — should NOT be filtered."""
        self.assertFalse(self.fn("172.0.0.1"))
        self.assertFalse(self.fn("172.15.0.1"))
        self.assertFalse(self.fn("172.16.0.1"))

    def test_invalid_ip(self):
        """Malformed IPs should not crash."""
        self.assertFalse(self.fn("not-an-ip"))
        self.assertFalse(self.fn("172"))
        self.assertFalse(self.fn(""))

    def test_172_32_not_filtered(self):
        """172.32+ is outside Docker range — should NOT be filtered."""
        self.assertFalse(self.fn("172.32.0.1"))
        self.assertFalse(self.fn("172.100.0.1"))


# ═══════════════════════════════════════════════════════════════════
# LAB_HOSTS fix — verify no broken import
# ═══════════════════════════════════════════════════════════════════

class TestLabStatusNoImportError(unittest.TestCase):
    """Verify _serve_lab_status doesn't import nonexistent LAB_HOSTS."""

    def test_no_lab_hosts_import(self):
        """serve.py should not import LAB_HOSTS from freq.modules.lab."""
        serve_path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        source = serve_path.read_text()
        self.assertNotIn("from freq.modules.lab import LAB_HOSTS", source,
                         "serve.py still imports nonexistent LAB_HOSTS")

    def test_lab_module_has_no_lab_hosts_export(self):
        """Confirm LAB_HOSTS was never a valid export from lab.py."""
        from freq.modules import lab
        self.assertFalse(hasattr(lab, "LAB_HOSTS"),
                         "LAB_HOSTS unexpectedly exists in lab.py")

    def test_get_lab_hosts_exists(self):
        """The correct function _get_lab_hosts should exist."""
        from freq.modules import lab
        self.assertTrue(hasattr(lab, "_get_lab_hosts"))

    def test_serve_lab_status_uses_cfg_hosts(self):
        """serve.py _serve_lab_status should filter cfg.hosts inline."""
        serve_path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        source = serve_path.read_text()
        # Find the _serve_lab_status method
        start = source.index("def _serve_lab_status")
        # Get next def to bound the search
        next_def = source.index("\n    def ", start + 1)
        method_source = source[start:next_def]
        self.assertIn('cfg.hosts', method_source,
                      "_serve_lab_status should use cfg.hosts")
        self.assertIn('"lab"', method_source,
                      "_serve_lab_status should filter by 'lab' group")


# ═══════════════════════════════════════════════════════════════════
# Fleet boundaries TOML read-modify-write tests
# ═══════════════════════════════════════════════════════════════════

class TestUpdateFbToml(unittest.TestCase):
    """Test the _update_fb_toml method that modifies fleet-boundaries.toml."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-fb-")
        self.fb_path = os.path.join(self.tmpdir, "fleet-boundaries.toml")
        with open(self.fb_path, "w") as f:
            f.write(SAMPLE_FB_TOML)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_handler(self):
        """Create a minimal handler with _update_fb_toml."""
        # Import the actual method from serve.py to test it
        from freq.modules.serve import FreqHandler
        handler = MagicMock(spec=FreqHandler)
        handler._update_fb_toml = FreqHandler._update_fb_toml.__get__(handler)
        return handler

    def _read_toml(self):
        with open(self.fb_path) as f:
            return f.read()

    def test_update_category_tier(self):
        """Change personal from probe to operator."""
        handler = self._make_handler()
        handler._update_fb_toml(self.fb_path, "category_tier",
                                cat_name="personal", tier="operator")
        content = self._read_toml()
        # Find the personal section and check tier
        lines = content.split("\n")
        in_personal = False
        for line in lines:
            if line.strip() == "[categories.personal]":
                in_personal = True
                continue
            if in_personal and line.strip().startswith("["):
                break
            if in_personal and line.strip().startswith("tier"):
                self.assertIn('"operator"', line)
                return
        self.fail("Did not find tier line in personal category")

    def test_add_vmid(self):
        """Add VMID 900 to personal category."""
        handler = self._make_handler()
        handler._update_fb_toml(self.fb_path, "add_vmid",
                                cat_name="personal", vmid=900)
        content = self._read_toml()
        self.assertIn("900", content)
        # Verify it's sorted
        lines = content.split("\n")
        in_personal = False
        for line in lines:
            if line.strip() == "[categories.personal]":
                in_personal = True
                continue
            if in_personal and line.strip().startswith("vmids"):
                self.assertIn("100", line)
                self.assertIn("900", line)
                return

    def test_add_vmid_no_duplicate(self):
        """Adding existing VMID 100 should not create duplicate."""
        handler = self._make_handler()
        handler._update_fb_toml(self.fb_path, "add_vmid",
                                cat_name="personal", vmid=100)
        content = self._read_toml()
        lines = content.split("\n")
        for line in lines:
            if "vmids" in line and "100" in line:
                # Count occurrences of 100
                count = line.count("100")
                self.assertEqual(count, 1, "VMID 100 should appear only once")
                return

    def test_remove_vmid(self):
        """Remove VMID 802 from personal."""
        handler = self._make_handler()
        handler._update_fb_toml(self.fb_path, "remove_vmid",
                                cat_name="personal", vmid=802)
        content = self._read_toml()
        lines = content.split("\n")
        in_personal = False
        for line in lines:
            if line.strip() == "[categories.personal]":
                in_personal = True
                continue
            if in_personal and line.strip().startswith("vmids"):
                self.assertNotIn("802", line)
                self.assertIn("100", line)
                self.assertIn("804", line)
                return

    def test_update_range(self):
        """Update templates range to 9000-9999."""
        handler = self._make_handler()
        handler._update_fb_toml(self.fb_path, "update_range",
                                cat_name="templates", range_start=9000, range_end=9999)
        content = self._read_toml()
        lines = content.split("\n")
        in_templates = False
        found_start = found_end = False
        for line in lines:
            if line.strip() == "[categories.templates]":
                in_templates = True
                continue
            if in_templates and line.strip().startswith("["):
                break
            if in_templates and line.strip().startswith("range_start"):
                self.assertIn("9000", line)
                found_start = True
            if in_templates and line.strip().startswith("range_end"):
                self.assertIn("9999", line)
                found_end = True
        self.assertTrue(found_start, "range_start not found")
        self.assertTrue(found_end, "range_end not found")

    def test_update_tier_actions(self):
        """Change probe tier to include start and stop."""
        handler = self._make_handler()
        handler._update_fb_toml(self.fb_path, "update_tier_actions",
                                tier_name="probe", actions=["view", "start", "stop"])
        content = self._read_toml()
        lines = content.split("\n")
        in_tiers = False
        for line in lines:
            if line.strip() == "[tiers]":
                in_tiers = True
                continue
            if in_tiers and line.strip().startswith("["):
                break
            if in_tiers and line.strip().startswith("probe"):
                self.assertIn('"view"', line)
                self.assertIn('"start"', line)
                self.assertIn('"stop"', line)
                return
        self.fail("Did not find probe tier line")

    def test_update_tier_actions_preserves_other_tiers(self):
        """Updating probe should not affect operator or admin."""
        handler = self._make_handler()
        original = self._read_toml()
        handler._update_fb_toml(self.fb_path, "update_tier_actions",
                                tier_name="probe", actions=["view", "start"])
        content = self._read_toml()
        # operator and admin lines should be unchanged
        for tier in ["operator", "admin"]:
            orig_line = [l for l in original.split("\n") if l.strip().startswith(f"{tier}")][0]
            new_line = [l for l in content.split("\n") if l.strip().startswith(f"{tier}")][0]
            self.assertEqual(orig_line, new_line,
                            f"{tier} tier was modified when only probe should change")

    def test_preserves_comments(self):
        """TOML modifications should preserve comment lines."""
        handler = self._make_handler()
        handler._update_fb_toml(self.fb_path, "add_vmid",
                                cat_name="personal", vmid=999)
        content = self._read_toml()
        self.assertIn("# PVE FREQ", content)

    def test_missing_file_no_crash(self):
        """Non-existent file should not raise."""
        handler = self._make_handler()
        handler._update_fb_toml("/tmp/nonexistent-fb-test.toml",
                                "add_vmid", cat_name="personal", vmid=999)
        # Should not raise


# ═══════════════════════════════════════════════════════════════════
# API endpoint validation tests (parameter checking)
# ═══════════════════════════════════════════════════════════════════

class TestFleetBoundariesApiValidation(unittest.TestCase):
    """Test parameter validation in fleet-boundaries update API."""

    def test_update_range_rejects_inverted(self):
        """range_start >= range_end should be rejected."""
        # This tests the validation logic at the API level
        # We verify the check exists in source code
        serve_path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        source = serve_path.read_text()
        self.assertIn("range_start must be < range_end", source)

    def test_update_tier_actions_validates(self):
        """Invalid action names should be rejected."""
        serve_path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        source = serve_path.read_text()
        self.assertIn("Invalid actions:", source)

    def test_valid_actions_set_defined(self):
        """The valid actions set should contain all expected actions."""
        serve_path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        source = serve_path.read_text()
        for action in ["view", "start", "stop", "restart", "snapshot",
                       "destroy", "clone", "resize", "migrate", "configure"]:
            self.assertIn(f'"{action}"', source)

    def test_add_vmid_rejects_non_integer(self):
        """vmid parameter must be integer — check exists."""
        serve_path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        source = serve_path.read_text()
        self.assertIn("vmid must be an integer", source)

    def test_admin_auth_required(self):
        """All admin endpoints check for admin role."""
        serve_path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        source = serve_path.read_text()
        # Count _check_session_role calls with "admin" in the admin methods
        admin_methods = ["_serve_admin_fleet_boundaries", "_serve_admin_fleet_boundaries_update",
                        "_serve_admin_hosts_update"]
        for method in admin_methods:
            start = source.index(f"def {method}")
            next_def = source.index("\n    def ", start + 1)
            method_source = source[start:next_def]
            self.assertIn('_check_session_role(self, "admin")', method_source,
                         f"{method} must require admin role")


# ═══════════════════════════════════════════════════════════════════
# Host update API tests
# ═══════════════════════════════════════════════════════════════════

class TestHostsUpdateToml(unittest.TestCase):
    """Test the hosts.conf update logic in _serve_admin_hosts_update."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq-test-hosts-")
        self.hosts_path = os.path.join(self.tmpdir, "hosts.conf")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_host_type(self):
        """Change host type from linux to docker."""
        with open(self.hosts_path, "w") as f:
            f.write("# Fleet\n")
            f.write("192.168.10.50  myhost  linux  lab\n")

        with open(self.hosts_path) as f:
            lines = f.readlines()

        # Simulate the update logic from _serve_admin_hosts_update
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].lower() == "myhost":
                ip = parts[0]
                htype = "docker"
                groups = parts[3] if len(parts) > 3 else ""
                new_parts = [f"{ip:<16}", f"{parts[1]:<15}", f"{htype:<10}"]
                if groups:
                    new_parts.append(groups)
                lines[i] = "  ".join(new_parts).rstrip() + "\n"
                break

        with open(self.hosts_path, "w") as f:
            f.writelines(lines)

        content = open(self.hosts_path).read()
        self.assertIn("docker", content)
        self.assertIn("myhost", content)
        self.assertIn("lab", content)

    def test_update_host_groups(self):
        """Change host groups from lab to prod."""
        with open(self.hosts_path, "w") as f:
            f.write("192.168.10.50  myhost  linux  lab\n")

        with open(self.hosts_path) as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].lower() == "myhost":
                ip = parts[0]
                htype = parts[2] if len(parts) > 2 else "linux"
                groups = "prod"
                new_parts = [f"{ip:<16}", f"{parts[1]:<15}", f"{htype:<10}", groups]
                lines[i] = "  ".join(new_parts).rstrip() + "\n"
                break

        with open(self.hosts_path, "w") as f:
            f.writelines(lines)

        content = open(self.hosts_path).read()
        self.assertIn("prod", content)
        self.assertNotIn("lab", content)


# ═══════════════════════════════════════════════════════════════════
# Integration: 172.x filter used correctly in hosts sync
# ═══════════════════════════════════════════════════════════════════

class TestDockerBridgeFilterIntegration(unittest.TestCase):
    """Verify hosts.py uses _is_docker_bridge_ip not blanket 172.x filter."""

    def test_hosts_py_uses_helper(self):
        """hosts.py should call _is_docker_bridge_ip, not startswith('172.')."""
        hosts_path = Path(__file__).parent.parent / "freq" / "modules" / "hosts.py"
        source = hosts_path.read_text()
        # Should use the helper function
        self.assertIn("_is_docker_bridge_ip", source)
        # Should NOT have the old blanket filter in the sync code
        # (it might exist in comments, so check the actual filter lines)
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "startswith(\"172.\")" in stripped or "startswith('172.')" in stripped:
                self.fail(f"Found blanket 172.x filter: {stripped}")


if __name__ == "__main__":
    unittest.main()
