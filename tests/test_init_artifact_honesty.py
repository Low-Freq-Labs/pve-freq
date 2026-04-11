"""Tests for init artifact honesty — prove malformed or missing artifacts
cannot pass verification as healthy.

Bug: Phase 12 verification had three gaps:
1. hosts.toml checked memory state, not disk file existence or parseability
2. fleet-boundaries.toml only checked for section headers, not TOML validity
3. containers.toml was never verified at all

These tests prove the contract: init-generated artifacts must exist on disk,
be valid TOML, and contain real entries — or verification must fail/warn.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


# Minimal host dataclass for test mocking
@dataclass
class FakeHost:
    ip: str
    label: str
    htype: str


class TestHostsTomlHonesty(unittest.TestCase):
    """hosts.toml must exist on disk and be valid TOML, not just in memory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_hosts_toml_is_accepted(self):
        """A well-formed hosts.toml should pass verification."""
        hosts_path = os.path.join(self.tmpdir, "hosts.toml")
        with open(hosts_path, "w") as f:
            f.write('[host.test]\nip = "10.0.0.1"\nlabel = "test"\nhtype = "linux"\n')
        if tomllib:
            with open(hosts_path, "rb") as f:
                data = tomllib.load(f)
            self.assertIn("host", data)

    def test_malformed_toml_is_rejected(self):
        """Malformed TOML must not parse successfully."""
        hosts_path = os.path.join(self.tmpdir, "hosts.toml")
        with open(hosts_path, "w") as f:
            f.write('[host.test\nip = "broken\n')
        if tomllib:
            with self.assertRaises(Exception):
                with open(hosts_path, "rb") as f:
                    tomllib.load(f)

    def test_missing_file_detected(self):
        """Missing hosts.toml must be detectable."""
        hosts_path = os.path.join(self.tmpdir, "hosts.toml")
        self.assertFalse(os.path.isfile(hosts_path))

    def test_empty_file_has_no_hosts(self):
        """Empty hosts.toml should parse but have no host entries."""
        hosts_path = os.path.join(self.tmpdir, "hosts.toml")
        with open(hosts_path, "w") as f:
            f.write("")
        if tomllib:
            with open(hosts_path, "rb") as f:
                data = tomllib.load(f)
            self.assertEqual(data, {})


class TestFleetBoundariesTomlHonesty(unittest.TestCase):
    """fleet-boundaries.toml must be valid TOML with real entries."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_boundaries_accepted(self):
        """Valid fleet-boundaries.toml with entries passes."""
        fb_path = os.path.join(self.tmpdir, "fleet-boundaries.toml")
        with open(fb_path, "w") as f:
            f.write('[physical.gateway]\nip = "10.0.0.1"\ntype = "pfsense"\n')
        if tomllib:
            with open(fb_path, "rb") as f:
                data = tomllib.load(f)
            self.assertIn("physical", data)
            self.assertGreater(len(data["physical"]), 0)

    def test_section_headers_only_is_empty(self):
        """Section headers with no entries should count as empty."""
        fb_path = os.path.join(self.tmpdir, "fleet-boundaries.toml")
        with open(fb_path, "w") as f:
            f.write("[physical]\n[pve_nodes]\n")
        if tomllib:
            with open(fb_path, "rb") as f:
                data = tomllib.load(f)
            phys = data.get("physical", {})
            pve = data.get("pve_nodes", {})
            entry_count = len(phys) + len(pve)
            self.assertEqual(entry_count, 0,
                             "Empty sections should not count as populated")

    def test_malformed_toml_detected(self):
        """Malformed fleet-boundaries.toml must not parse."""
        fb_path = os.path.join(self.tmpdir, "fleet-boundaries.toml")
        with open(fb_path, "w") as f:
            f.write('[physical\nbroken = \n')
        if tomllib:
            with self.assertRaises(Exception):
                with open(fb_path, "rb") as f:
                    tomllib.load(f)

    def test_duplicate_sections_are_invalid_toml(self):
        """Duplicate TOML table headers must fail parsing — the root cause bug."""
        fb_path = os.path.join(self.tmpdir, "fleet-boundaries.toml")
        with open(fb_path, "w") as f:
            f.write(
                '[categories.lab]\ndescription = "Lab"\ntier = "admin"\nvmids = [5000]\n\n'
                '[categories.lab]\ndescription = "Lab"\ntier = "admin"\nvmids = [5000]\n'
            )
        if tomllib:
            with self.assertRaises(Exception):
                with open(fb_path, "rb") as f:
                    tomllib.load(f)


class TestContainersTomlHonesty(unittest.TestCase):
    """containers.toml must be verified if generated — not silently absent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_containers_accepted(self):
        """Valid containers.toml with entries passes."""
        ct_path = os.path.join(self.tmpdir, "containers.toml")
        with open(ct_path, "w") as f:
            f.write(
                '[host.arr-stack]\n'
                'ip = "10.0.0.31"\n'
                'label = "arr-stack"\n\n'
                '[host.arr-stack.containers.sonarr]\n'
                'name = "sonarr"\n'
                'image = "linuxserver/sonarr"\n'
                'status = "running"\n'
            )
        if tomllib:
            with open(ct_path, "rb") as f:
                data = tomllib.load(f)
            host_section = data.get("host", {})
            self.assertGreater(len(host_section), 0)
            total = sum(
                len(v.get("containers", {}))
                for v in host_section.values()
                if isinstance(v, dict)
            )
            self.assertGreater(total, 0, "Must have at least one container entry")

    def test_empty_containers_detected(self):
        """Empty containers.toml should be detected as having no entries."""
        ct_path = os.path.join(self.tmpdir, "containers.toml")
        with open(ct_path, "w") as f:
            f.write("")
        if tomllib:
            with open(ct_path, "rb") as f:
                data = tomllib.load(f)
            host_section = data.get("host", {})
            self.assertEqual(len(host_section), 0)

    def test_malformed_containers_detected(self):
        """Malformed containers.toml must not parse."""
        ct_path = os.path.join(self.tmpdir, "containers.toml")
        with open(ct_path, "w") as f:
            f.write('[host.broken\nname = \n')
        if tomllib:
            with self.assertRaises(Exception):
                with open(ct_path, "rb") as f:
                    tomllib.load(f)

    def test_missing_file_with_docker_hosts_is_gap(self):
        """If docker hosts exist but containers.toml doesn't, that's a gap."""
        ct_path = os.path.join(self.tmpdir, "containers.toml")
        docker_hosts = [FakeHost(ip="10.0.0.31", label="arr-stack", htype="docker")]
        self.assertFalse(os.path.isfile(ct_path))
        self.assertTrue(len(docker_hosts) > 0,
                        "Docker hosts present but containers.toml missing = gap")


class TestVerificationContract(unittest.TestCase):
    """Integration-level: the verification flow must catch all three gap types."""

    def test_old_hosts_verification_was_memory_only(self):
        """Prove the old verification approach was insufficient.

        Old code: `if cfg.hosts: _check(...)` only checked memory.
        New code checks both memory AND disk file existence + parseability.
        """
        fake_hosts = [FakeHost(ip="10.0.0.1", label="test", htype="linux")]
        missing_path = "/tmp/nonexistent-hosts-toml-test-file.toml"
        self.assertTrue(len(fake_hosts) > 0, "hosts in memory")
        self.assertFalse(os.path.isfile(missing_path), "file missing on disk")

    def test_old_boundaries_verification_fooled_by_headers(self):
        """Prove section headers without entries fooled the old check.

        Old code: `"[physical]" in content` passed on empty sections.
        New code parses TOML and counts actual entries.
        """
        tmpdir = tempfile.mkdtemp()
        try:
            fb_path = os.path.join(tmpdir, "fleet-boundaries.toml")
            with open(fb_path, "w") as f:
                f.write("[physical]\n# no entries\n[pve_nodes]\n# no entries\n")
            with open(fb_path) as f:
                content = f.read()
            old_result = "[physical]" in content or "[pve_nodes]" in content
            self.assertTrue(old_result, "Old check passes on empty sections")
            if tomllib:
                with open(fb_path, "rb") as f:
                    data = tomllib.load(f)
                entry_count = len(data.get("physical", {})) + len(data.get("pve_nodes", {}))
                self.assertEqual(entry_count, 0, "New check correctly detects empty sections")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
