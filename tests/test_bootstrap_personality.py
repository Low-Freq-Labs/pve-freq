"""Tests for bootstrap personality seeding contract.

Bug: bootstrap_conf() returned False immediately when conf/ was non-empty,
skipping personality/ and plugins/ seeding. In repo-backed installs, conf/
has freq.toml but no personality/ directory, causing doctor to warn about
missing default pack even though package templates exist.

Fix: bootstrap_conf() now always seeds personality/ and plugins/ into
existing conf/ trees (incremental seeding). Never overwrites existing files.
"""
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBootstrapPersonalitySeeding(unittest.TestCase):
    """personality/ must be seeded even when conf/ already has files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create a minimal install dir that simulates repo checkout
        self.install_dir = os.path.join(self.tmpdir, "pve-freq")
        self.conf_dir = os.path.join(self.install_dir, "conf")
        os.makedirs(self.conf_dir)
        # Pre-populate conf/ (simulates repo checkout)
        with open(os.path.join(self.conf_dir, "freq.toml"), "w") as f:
            f.write("[freq]\nversion = \"1.0.0\"\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_existing_conf_gets_personality_seeded(self):
        """conf/ with files but no personality/ should get personality seeded."""
        from freq.core.config import bootstrap_conf
        self.assertTrue(os.path.isfile(os.path.join(self.conf_dir, "freq.toml")))
        self.assertFalse(os.path.isdir(os.path.join(self.conf_dir, "personality")))
        result = bootstrap_conf(self.install_dir)
        # Returns False (not a full bootstrap — conf already existed)
        self.assertFalse(result)
        # But personality/ should now exist
        personality_dir = os.path.join(self.conf_dir, "personality")
        self.assertTrue(os.path.isdir(personality_dir),
                        "personality/ should be seeded into existing conf/")
        # And should contain the default pack
        self.assertTrue(os.path.isfile(os.path.join(personality_dir, "default.toml")),
                        "default.toml must be seeded")

    def test_existing_personality_not_overwritten(self):
        """If personality/ already exists with custom files, don't overwrite."""
        from freq.core.config import bootstrap_conf
        personality_dir = os.path.join(self.conf_dir, "personality")
        os.makedirs(personality_dir)
        custom = os.path.join(personality_dir, "default.toml")
        with open(custom, "w") as f:
            f.write("# custom personality\n")
        bootstrap_conf(self.install_dir)
        with open(custom) as f:
            content = f.read()
        self.assertEqual(content, "# custom personality\n",
                         "Existing personality file must not be overwritten")

    def test_full_bootstrap_still_works(self):
        """Empty install dir should do full bootstrap."""
        from freq.core.config import bootstrap_conf
        fresh_dir = os.path.join(self.tmpdir, "fresh")
        os.makedirs(fresh_dir)
        result = bootstrap_conf(fresh_dir)
        self.assertTrue(result)
        self.assertTrue(os.path.isdir(os.path.join(fresh_dir, "conf")))


class TestPersonalityLoadFallback(unittest.TestCase):
    """Personality loader must fall back to defaults when file is missing."""

    def test_missing_pack_returns_defaults(self):
        """load_pack with missing file returns default PersonalityPack."""
        from freq.core.personality import load_pack
        pack = load_pack("/nonexistent/path", "default")
        self.assertEqual(pack.name, "default")
        # Default values should be populated
        self.assertIsInstance(pack.subtitle, str)

    def test_existing_pack_loads_fields(self):
        """load_pack with valid file reads fields correctly."""
        from freq.core.personality import load_pack
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "personality"))
            with open(os.path.join(tmpdir, "personality", "test.toml"), "w") as f:
                f.write('subtitle = "Test Pack"\nvibe_enabled = true\n')
            pack = load_pack(tmpdir, "test")
            self.assertEqual(pack.subtitle, "Test Pack")
            self.assertTrue(pack.vibe_enabled)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
