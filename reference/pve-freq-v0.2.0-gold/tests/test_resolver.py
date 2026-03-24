"""Resolver tests — edge cases and integration with real hosts.conf formats.

Tests fleet loading, filtering, and edge cases with various
hosts.conf formats encountered in DC01.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.core.types import Host
from engine.core.resolver import load_fleet, filter_by_scope, filter_by_labels, filter_by_groups


class TestResolverEdgeCases(unittest.TestCase):
    """Test resolver with edge case inputs."""

    def _write_hosts(self, content: str) -> str:
        """Write temp hosts.conf and return path."""
        fd, path = tempfile.mkstemp(suffix=".conf")
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return path

    def test_blank_lines_ignored(self):
        path = self._write_hosts("""
10.0.0.1 host1 linux

10.0.0.2 host2 pve

""")
        fleet = load_fleet(path)
        os.unlink(path)
        self.assertEqual(len(fleet), 2)

    def test_comment_only_file(self):
        path = self._write_hosts("""# This is a comment
# Another comment
# More comments
""")
        fleet = load_fleet(path)
        os.unlink(path)
        self.assertEqual(len(fleet), 0)

    def test_tab_separated(self):
        path = self._write_hosts("10.0.0.1\thost1\tlinux\tgroup1")
        fleet = load_fleet(path)
        os.unlink(path)
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0].label, "host1")
        self.assertEqual(fleet[0].groups, "group1")

    def test_mixed_whitespace(self):
        path = self._write_hosts("10.0.0.1  \t  host1 \t linux  \t  group1,group2")
        fleet = load_fleet(path)
        os.unlink(path)
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0].groups, "group1,group2")

    def test_no_groups_field(self):
        path = self._write_hosts("10.0.0.1 host1 linux")
        fleet = load_fleet(path)
        os.unlink(path)
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0].groups, "")

    def test_malformed_line_too_few_fields(self):
        path = self._write_hosts("""10.0.0.1 host1 linux
10.0.0.2 incomplete
10.0.0.3 host3 pve
""")
        fleet = load_fleet(path)
        os.unlink(path)
        # Only valid lines should be loaded
        self.assertEqual(len(fleet), 2)

    def test_inline_comment_not_supported(self):
        """Inline comments are NOT stripped — they become part of the value."""
        path = self._write_hosts("10.0.0.1 host1 linux group1 # this is a comment")
        fleet = load_fleet(path)
        os.unlink(path)
        # The fourth field will include everything after htype
        self.assertEqual(len(fleet), 1)

    def test_dc01_realistic_format(self):
        """Test with realistic DC01 hosts.conf format."""
        path = self._write_hosts("""# DC01 Fleet Registry
# Format: IP LABEL TYPE [GROUPS]

# PVE Cluster
10.25.25.1   pve01     pve    cluster,prod
10.25.25.2   pve02     pve    cluster,prod
10.25.25.3   pve03     pve    cluster,prod

# Storage
10.25.25.10  truenas   truenas storage

# Network
10.25.25.20  pfsense   pfsense network
10.25.25.60  switch    switch  network

# Media Stack
10.25.100.1  vm101     linux  media,plex
10.25.100.2  vm102     linux  media,arrs
10.25.100.3  vm103     linux  media,download
10.25.100.4  vm104     linux  media,tdarr

# BMC
10.25.25.50  idrac-r530 idrac bmc
""")
        fleet = load_fleet(path)
        os.unlink(path)
        self.assertEqual(len(fleet), 11)

        # Verify types
        types = {h.htype for h in fleet}
        self.assertEqual(types, {"pve", "truenas", "pfsense", "switch", "linux", "idrac"})

        # Filter tests
        linux = filter_by_scope(fleet, ["linux"])
        self.assertEqual(len(linux), 4)

        pve = filter_by_scope(fleet, ["pve"])
        self.assertEqual(len(pve), 3)

        media = filter_by_groups(fleet, ["media"])
        self.assertEqual(len(media), 4)

        cluster = filter_by_groups(fleet, ["cluster"])
        self.assertEqual(len(cluster), 3)

    def test_filter_multiple_scopes(self):
        path = self._write_hosts("""10.0.0.1 h1 linux
10.0.0.2 h2 pve
10.0.0.3 h3 truenas
10.0.0.4 h4 pfsense
""")
        fleet = load_fleet(path)
        os.unlink(path)

        # SSH hardening scope
        filtered = filter_by_scope(fleet, ["linux", "pve", "truenas", "pfsense"])
        self.assertEqual(len(filtered), 4)

        # Linux-only scope
        filtered = filter_by_scope(fleet, ["linux"])
        self.assertEqual(len(filtered), 1)

    def test_filter_labels_partial_match(self):
        """Label filter should be exact match, not partial."""
        path = self._write_hosts("""10.0.0.1 vm101 linux
10.0.0.2 vm102 linux
10.0.0.3 vm1010 linux
""")
        fleet = load_fleet(path)
        os.unlink(path)

        filtered = filter_by_labels(fleet, ["vm101"])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].label, "vm101")

    def test_load_from_freq_dir(self):
        """Test loading via freq_dir parameter."""
        tmpdir = tempfile.mkdtemp()
        conf_dir = os.path.join(tmpdir, "conf")
        os.makedirs(conf_dir)
        with open(os.path.join(conf_dir, "hosts.conf"), "w") as f:
            f.write("10.0.0.1 h1 linux\n")

        fleet = load_fleet(freq_dir=tmpdir)
        self.assertEqual(len(fleet), 1)

        import shutil
        shutil.rmtree(tmpdir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
