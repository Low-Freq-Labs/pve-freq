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
        """needs_update must fire when tls_cert/tls_key are absent or stale."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('"tls_cert" not in content', src)
        self.assertIn('"tls_key" not in content', src)
        self.assertIn('f\'tls_cert = "{cert_path}"\' not in content', src)
        self.assertIn('f\'tls_key = "{key_path_tls}"\' not in content', src)

    def test_cert_generated_flag(self):
        """cert_generated flag tracked so new cert always writes freq.toml."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("cert_generated = True", src)

    def test_missing_cert_or_key_regenerates_pair(self):
        """Phase 9l must regenerate if either cert or key is missing."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("not os.path.isfile(cert_path) or not os.path.isfile(key_path_tls)", src)


class TestInstallerPreservesGeneratedTls(unittest.TestCase):
    """Local source installs must not delete generated dashboard TLS assets."""

    def test_local_rsync_excludes_tls_dir(self):
        src = (FREQ_ROOT / "install.sh").read_text()
        local_copy = src.split("rsync -a --delete", 1)[1].split('"$SOURCE/" "$INSTALL_DIR/"', 1)[0]
        self.assertIn("--exclude='tls/'", local_copy)

    def test_fresh_systemd_install_creates_distinct_bootstrap_tls(self):
        src = (FREQ_ROOT / "install.sh").read_text()
        self.assertIn("freq-bootstrap.crt", src)
        self.assertIn("freq-bootstrap.key", src)
        self.assertIn("pve-freq-setup.service", src)
        self.assertIn("setup_dashboard_service_unit", src)
        self.assertIn("systemctl enable --now pve-freq-setup.service", src)
        self.assertNotEqual(src.find("freq-bootstrap.crt"), -1)

    def test_bootstrap_identity_is_not_final_service_identity(self):
        src = (FREQ_ROOT / "install.sh").read_text()
        self.assertIn("detect_setup_account", src)
        self.assertIn('${SUDO_USER:-}', src)
        self.assertIn("Data ownership deferred until init creates runtime account", src)


if __name__ == "__main__":
    unittest.main()
