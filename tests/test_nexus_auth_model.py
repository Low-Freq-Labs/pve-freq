"""Tests for nonstandard host auth model — managed flag and classification.

Bug: Discovery auto-registered nexus (TrueNAS) as type=linux. Fleet deploy
couldn't deploy freq-admin to it. Fleet status permanently showed it as
DOWN with permission denied, polluting health surfaces.

Root cause: _classify_host_by_name("nexus") returned "linux" because
"nexus" didn't match any TrueNAS patterns. No mechanism existed to mark
discovered-but-not-deployed hosts as unmanaged.

Fix:
1. Added "nexus" to TrueNAS classification patterns
2. Added managed=false field to Host model for hosts that were discovered
   but not deployed to
3. Fleet health probes and fleet status skip unmanaged hosts
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestNexusClassification(unittest.TestCase):
    """Nexus must be classified as TrueNAS, not linux."""

    def test_nexus_classified_as_truenas(self):
        """_classify_host_by_name('nexus') must return 'truenas'."""
        from freq.modules.init_cmd import _classify_host_by_name
        self.assertEqual(_classify_host_by_name("nexus"), "truenas")

    def test_nexus_variants_classified(self):
        """Nexus variations should classify as truenas."""
        from freq.modules.init_cmd import _classify_host_by_name
        for name in ["nexus", "Nexus", "NEXUS", "nexus-backup", "my-nexus"]:
            self.assertEqual(_classify_host_by_name(name), "truenas",
                             f"Expected truenas for '{name}'")

    def test_nas_standalone_classified(self):
        """Standalone 'nas' or hyphen-delimited 'nas' should classify as truenas."""
        from freq.modules.init_cmd import _classify_host_by_name
        self.assertEqual(_classify_host_by_name("nas"), "truenas")
        self.assertEqual(_classify_host_by_name("nas-backup"), "truenas")
        self.assertEqual(_classify_host_by_name("main-nas"), "truenas")

    def test_nas_substring_not_overmatch(self):
        """Names containing 'nas' as substring (not segment) should not match."""
        from freq.modules.init_cmd import _classify_host_by_name
        # "dynasty" contains "nas" but is not a NAS host
        self.assertNotEqual(_classify_host_by_name("dynasty"), "truenas")

    def test_truenas_still_works(self):
        """Explicit TrueNAS names still classify correctly."""
        from freq.modules.init_cmd import _classify_host_by_name
        self.assertEqual(_classify_host_by_name("truenas-core"), "truenas")
        self.assertEqual(_classify_host_by_name("freenas"), "truenas")


class TestManagedHostFlag(unittest.TestCase):
    """Host model must support managed=false for undeployed hosts."""

    def test_host_has_managed_field(self):
        """Host dataclass must have a managed field defaulting to True."""
        from freq.core.types import Host
        h = Host(ip="10.0.0.1", label="test", htype="linux")
        self.assertTrue(h.managed)

    def test_host_managed_false(self):
        """Host with managed=False should be settable."""
        from freq.core.types import Host
        h = Host(ip="10.0.0.1", label="test", htype="truenas", managed=False)
        self.assertFalse(h.managed)

    def test_hosts_toml_roundtrip_managed(self):
        """managed=false must survive hosts.toml write/read cycle."""
        import tempfile
        import os
        from freq.core.types import Host
        from freq.core.config import save_hosts_toml, load_hosts_toml

        hosts = [
            Host(ip="10.0.0.1", label="managed-host", htype="linux", managed=True),
            Host(ip="10.0.0.2", label="unmanaged-host", htype="truenas", managed=False),
        ]
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
        tmp.close()
        try:
            save_hosts_toml(tmp.name, hosts)
            loaded = load_hosts_toml(tmp.name)
            self.assertEqual(len(loaded), 2)
            self.assertTrue(loaded[0].managed)
            self.assertFalse(loaded[1].managed)
        finally:
            os.unlink(tmp.name)


class TestFleetStatusSkipsUnmanaged(unittest.TestCase):
    """Fleet scan and health must skip unmanaged hosts."""

    def test_scan_fleet_skips_unmanaged(self):
        """_scan_fleet source must check managed flag."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('getattr(h, "managed", True)', src)

    def test_serve_health_skips_unmanaged(self):
        """Serve health probe must skip unmanaged hosts."""
        src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn('getattr(h, "managed", True)', src)


if __name__ == "__main__":
    unittest.main()
