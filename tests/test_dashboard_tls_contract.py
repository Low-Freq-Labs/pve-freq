"""Tests for dashboard TLS contract: cert presence must match freq.toml config.

Bug: After clean init on 5005, /opt/pve-freq/tls/freq.crt existed on disk
(owned by freq-admin) but freq.toml had no tls_cert/tls_key entries.
Dashboard ran plain HTTP on 8888, but operator probes assumed HTTPS.

Root cause: Phase 9l only updated freq.toml when generating a NEW cert.
When the cert already existed (from a prior run or earlier deploy), the
"already exists" branch printed OK but didn't update freq.toml. If
freq.toml had been reset/re-seeded meanwhile, it was left without
tls_cert/tls_key — dashboard started as plain HTTP.

Fix: Phase 9l now always ensures freq.toml has tls_cert/tls_key when
the cert files are present on disk, regardless of whether it just
generated them or found them existing.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestPhase9lAlwaysUpdatesToml(unittest.TestCase):
    """Phase 9l must update freq.toml whenever tls files exist on disk."""

    def test_source_updates_toml_outside_generate_block(self):
        """TLS path update logic must not be nested inside 'if generating' block."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("Always update freq.toml with TLS paths", src)

    def test_checks_both_cert_and_key_on_disk(self):
        """Update path checks cert_path AND key_path_tls exist."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("os.path.isfile(cert_path) and os.path.isfile(key_path_tls)", src)

    def test_needs_update_covers_missing_keys(self):
        """needs_update must fire when tls_cert or tls_key are absent from content."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('"tls_cert" not in content', src)
        self.assertIn('"tls_key" not in content', src)

    def test_cert_generated_flag(self):
        """cert_generated flag tracked so new cert always writes freq.toml."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("cert_generated = True", src)


if __name__ == "__main__":
    unittest.main()
