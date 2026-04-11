"""Tests for hosts registry format contract — all paths use TOML.

Bug: Module docstrings, comments, help text, and error messages referenced
'hosts.conf' (the legacy flat-file format) even though all actual I/O uses
hosts.toml (TOML format). This created confusion about which format is
canonical.

Contract: hosts.toml is the only registry format. Legacy hosts.conf is
auto-migrated on first load (config.py), then all operations use TOML.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestNoStaleHostsConfReferences(unittest.TestCase):
    """Core registry modules must not reference hosts.conf as current format."""

    def _count_hosts_conf_refs(self, filepath, exclude_migration=True):
        """Count 'hosts.conf' references, optionally excluding migration code."""
        count = 0
        with open(filepath) as f:
            for i, line in enumerate(f, 1):
                if "hosts.conf" in line:
                    # Exclude legitimate migration references
                    if exclude_migration and any(w in line.lower() for w in
                                                  ["migrat", "legacy", "deprecated", "auto-migrat"]):
                        continue
                    count += 1
        return count

    def test_hosts_module_no_stale_refs(self):
        """freq/modules/hosts.py must not reference hosts.conf as current."""
        path = FREQ_ROOT / "freq" / "modules" / "hosts.py"
        refs = self._count_hosts_conf_refs(path)
        self.assertEqual(refs, 0,
                         f"hosts.py has {refs} stale hosts.conf reference(s)")

    def test_serve_module_no_stale_refs(self):
        """freq/modules/serve.py must not reference hosts.conf as current."""
        path = FREQ_ROOT / "freq" / "modules" / "serve.py"
        refs = self._count_hosts_conf_refs(path)
        self.assertEqual(refs, 0,
                         f"serve.py has {refs} stale hosts.conf reference(s)")

    def test_infrastructure_no_stale_refs(self):
        """freq/modules/infrastructure.py must not reference hosts.conf."""
        path = FREQ_ROOT / "freq" / "modules" / "infrastructure.py"
        refs = self._count_hosts_conf_refs(path)
        self.assertEqual(refs, 0,
                         f"infrastructure.py has {refs} stale hosts.conf reference(s)")


class TestHostsRegistryFormat(unittest.TestCase):
    """The hosts registry must use TOML format end-to-end."""

    def test_config_hosts_file_is_toml(self):
        """cfg.hosts_file must point to hosts.toml, not hosts.conf."""
        from freq.core.config import load_config
        cfg = load_config()
        self.assertTrue(cfg.hosts_file.endswith(".toml"),
                        f"hosts_file should be .toml, got: {cfg.hosts_file}")

    def test_append_host_writes_toml(self):
        """append_host_toml must write TOML array format."""
        import tempfile, os
        from freq.core.config import append_host_toml
        from freq.core.types import Host
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "hosts.toml")
            host = Host(ip="10.0.0.1", label="test", htype="linux")
            append_host_toml(path, host)
            with open(path) as f:
                content = f.read()
            self.assertIn("[[host]]", content, "Must use TOML array-of-tables format")
            self.assertIn('ip = "10.0.0.1"', content)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_load_hosts_toml_round_trips(self):
        """Write then load must preserve host data."""
        import tempfile, os
        from freq.core.config import append_host_toml, load_hosts_toml
        from freq.core.types import Host
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "hosts.toml")
            host = Host(ip="10.0.0.1", label="webserver", htype="linux", groups="prod")
            append_host_toml(path, host)
            hosts = load_hosts_toml(path)
            self.assertEqual(len(hosts), 1)
            self.assertEqual(hosts[0].ip, "10.0.0.1")
            self.assertEqual(hosts[0].label, "webserver")
            self.assertEqual(hosts[0].htype, "linux")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
