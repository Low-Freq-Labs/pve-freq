"""Tests for hosts.toml duplicate prevention after init.

Bug: Green init wrote every discovered host twice to hosts.toml.
Phase 1 seeded hosts.toml from template (with commented examples),
then Phase 7 used append_host_toml which adds to the existing file.
If anything later re-appends or if the template already contained
matching entries, duplicates accumulate.

Fix: Phase 7 discovery registration now uses save_hosts_toml (overwrite)
instead of append_host_toml. This writes the canonical set of hosts
from cfg.hosts, preventing duplicates from template leftovers or
repeated registration.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestDiscoveryUsesSaveNotAppend(unittest.TestCase):
    """Phase 7 discovery must use save_hosts_toml, not append."""

    def test_headless_registration_uses_save(self):
        """Headless auto-registration must use save_hosts_toml."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        import re
        # Find the headless auto-register block
        block = re.search(
            r'# Auto-register all in headless mode.*?save_hosts_toml\(cfg\.hosts_file, cfg\.hosts\)',
            src, re.DOTALL
        )
        self.assertIsNotNone(block, "Headless registration must use save_hosts_toml")

    def test_interactive_bulk_registration_uses_save(self):
        """Interactive bulk registration must use save_hosts_toml."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # The bulk "Register all N discovered hosts?" path
        self.assertIn("save_hosts_toml(cfg.hosts_file, cfg.hosts)", src)


class TestSaveHostsTomlNoDuplicates(unittest.TestCase):
    """save_hosts_toml must write exactly one entry per host."""

    def test_save_produces_no_duplicates(self):
        """Writing hosts with save_hosts_toml then reading back gives same count."""
        from freq.core.types import Host
        from freq.core.config import save_hosts_toml, load_hosts_toml

        hosts = [
            Host(ip="10.0.0.1", label="host1", htype="linux"),
            Host(ip="10.0.0.2", label="host2", htype="pve"),
            Host(ip="10.0.0.3", label="host3", htype="docker"),
        ]
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
        tmp.close()
        try:
            save_hosts_toml(tmp.name, hosts)
            loaded = load_hosts_toml(tmp.name)
            self.assertEqual(len(loaded), 3)
            ips = [h.ip for h in loaded]
            self.assertEqual(len(ips), len(set(ips)), "No duplicate IPs after save")
        finally:
            os.unlink(tmp.name)

    def test_save_overwrites_existing(self):
        """save_hosts_toml overwrites — doesn't append to existing content."""
        from freq.core.types import Host
        from freq.core.config import save_hosts_toml, load_hosts_toml

        hosts = [Host(ip="10.0.0.1", label="host1", htype="linux")]
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
        tmp.close()
        try:
            # Write template content first
            with open(tmp.name, "w") as f:
                f.write("# Template\n# [[host]]\n# ip = \"192.168.1.1\"\n")
            # Save overwrites
            save_hosts_toml(tmp.name, hosts)
            loaded = load_hosts_toml(tmp.name)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].ip, "10.0.0.1")
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
