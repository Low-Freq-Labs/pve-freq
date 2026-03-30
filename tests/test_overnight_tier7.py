"""Overnight Matrix — Tier 7: Personality System

Tests 7.1-7.9: Personality packs, fallbacks, celebrate, splash.
No network calls. Pure personality system.
"""
import os
import sys
import unittest
import tempfile
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "configs")
RICK_DIR = str(Path(__file__).parent.parent)
CONF_DIR = os.path.join(RICK_DIR, "conf")


def _personality_conf_dir():
    """Return a conf dir that has personality/ — prefer conf/, fall back to package data."""
    conf_personality = os.path.join(CONF_DIR, "personality")
    if os.path.isdir(conf_personality) and os.path.isfile(
        os.path.join(conf_personality, "personal.toml")
    ):
        return CONF_DIR
    # Fall back to package data
    try:
        from freq.data import get_data_path
        pkg = str(get_data_path() / "conf-templates")
        if os.path.isdir(os.path.join(pkg, "personality")):
            return pkg
    except ImportError:
        pass
    return CONF_DIR


class TestTier7Personality(unittest.TestCase):
    """Tier 7: Personality system tests."""

    # --- 7.1: Load default pack ---
    def test_7_1_load_default_pack(self):
        """Default pack loads with neutral values."""
        from freq.core.personality import load_pack
        pdir = _personality_conf_dir()
        pack = load_pack(pdir, "default")
        self.assertEqual(pack.name, "default")
        self.assertEqual(pack.subtitle, "P V E  F R E Q")
        self.assertFalse(pack.vibe_enabled)
        self.assertEqual(pack.dashboard_header, "PVE FREQ Dashboard")

    # --- 7.2: Load personal pack ---
    def test_7_2_load_personal_pack(self):
        """Personal pack loads with custom branding values."""
        from freq.core.personality import load_pack
        pdir = _personality_conf_dir()
        pack = load_pack(pdir, "personal")
        self.assertEqual(pack.name, "personal")
        self.assertEqual(pack.subtitle, "L O W  F R E Q  L A B S")
        self.assertTrue(pack.vibe_enabled)
        self.assertEqual(pack.vibe_probability, 47)
        self.assertEqual(pack.dashboard_header, "LOW FREQ Labs Dashboard")
        self.assertTrue(len(pack.celebrations) > 10)
        self.assertTrue(len(pack.taglines) > 5)
        self.assertTrue(len(pack.quotes) > 5)

    # --- 7.3: Load nonexistent pack ---
    def test_7_3_load_nonexistent_pack(self):
        """Nonexistent pack falls back to defaults, no crash."""
        from freq.core.personality import load_pack
        pack = load_pack(_personality_conf_dir(), "enterprise")
        self.assertEqual(pack.name, "enterprise")
        self.assertEqual(pack.subtitle, "P V E  F R E Q")
        self.assertEqual(pack.celebrations, [])
        self.assertEqual(pack.taglines, [])
        self.assertEqual(pack.quotes, [])
        self.assertEqual(pack.dashboard_header, "PVE FREQ Dashboard")

    # --- 7.4: Missing personality directory entirely ---
    def test_7_4_missing_personality_dir(self):
        """No personality directory — falls back to hardcoded defaults."""
        from freq.core.personality import load_pack
        pack = load_pack("/nonexistent/conf", "default")
        self.assertEqual(pack.name, "default")
        self.assertEqual(pack.subtitle, "P V E  F R E Q")
        self.assertEqual(pack.celebrations, [])
        self.assertEqual(pack.dashboard_header, "PVE FREQ Dashboard")

    # --- 7.5: Celebrate with None pack ---
    def test_7_5_celebrate_with_empty_pack(self):
        """celebrate() with pack that has no celebrations doesn't crash."""
        from freq.core.personality import PersonalityPack, celebrate
        pack = PersonalityPack()
        pack.celebrations = []
        msg = celebrate(pack)
        self.assertEqual(msg, "Done.")  # Fallback

    def test_7_5b_celebrate_with_celebrations(self):
        """celebrate() with valid pack returns a celebration."""
        from freq.core.personality import load_pack, celebrate
        pdir = _personality_conf_dir()
        pack = load_pack(pdir, "personal")
        msg = celebrate(pack)
        self.assertTrue(len(msg) > 0)
        if pack.celebrations:
            self.assertIn(msg, pack.celebrations)

    def test_7_5c_celebrate_premier(self):
        """celebrate() with operation returns premier message if available."""
        from freq.core.personality import load_pack, celebrate
        pdir = _personality_conf_dir()
        pack = load_pack(pdir, "personal")
        if "create" in pack.premier:
            msg = celebrate(pack, "create")
            self.assertIn("VM", msg)

    # --- 7.6: Splash with default pack ---
    def test_7_6_splash_default(self):
        """splash() with default pack shows 'PVE FREQ' subtitle."""
        from freq.core.personality import load_pack, splash
        pack = load_pack(_personality_conf_dir(), "default")
        # Capture stdout
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            splash(pack, "2.0.0")
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        # Check subtitle appears
        self.assertIn("P V E  F R E Q", output)
        self.assertIn("v2.0.0", output)

    # --- 7.7: Splash with personal pack ---
    def test_7_7_splash_personal(self):
        """splash() with personal pack shows 'LOW FREQ Labs' subtitle."""
        from freq.core.personality import load_pack, splash
        pack = load_pack(_personality_conf_dir(), "personal")
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            splash(pack, "2.0.0")
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertIn("L O W  F R E Q  L A B S", output)

    # --- 7.8: Dashboard header via default pack ---
    def test_7_8_dashboard_header_default(self):
        """Default pack dashboard_header = 'PVE FREQ Dashboard'."""
        from freq.core.personality import load_pack
        pack = load_pack(_personality_conf_dir(), "default")
        self.assertEqual(pack.dashboard_header, "PVE FREQ Dashboard")

    # --- 7.9: Dashboard header via personal pack ---
    def test_7_9_dashboard_header_personal(self):
        """Personal pack dashboard_header = 'LOW FREQ Labs Dashboard'."""
        from freq.core.personality import load_pack
        pdir = _personality_conf_dir()
        pack = load_pack(pdir, "personal")
        self.assertEqual(pack.dashboard_header, "LOW FREQ Labs Dashboard")

    # --- Extra: tagline and quote fallbacks ---
    def test_tagline_fallback(self):
        """tagline() with empty pack returns fallback."""
        from freq.core.personality import PersonalityPack, tagline
        pack = PersonalityPack()
        pack.taglines = []
        msg = tagline(pack)
        self.assertEqual(msg, "Full frequency. Full efficiency.")

    def test_quote_fallback(self):
        """quote() with empty pack returns fallback."""
        from freq.core.personality import PersonalityPack, quote
        pack = PersonalityPack()
        pack.quotes = []
        msg = quote(pack)
        self.assertIn("configure once", msg)

    def test_vibe_check_disabled(self):
        """vibe_check() returns None when vibes disabled."""
        from freq.core.personality import PersonalityPack, vibe_check
        pack = PersonalityPack()
        pack.vibe_enabled = False
        for _ in range(100):
            result = vibe_check(pack)
            self.assertIsNone(result)

    def test_vibe_check_no_messages(self):
        """vibe_check() returns None when enabled but no messages defined."""
        from freq.core.personality import PersonalityPack, vibe_check
        pack = PersonalityPack()
        pack.vibe_enabled = True
        pack.vibe_probability = 1  # Always trigger
        pack.vibe_common = []
        pack.vibe_rare = []
        pack.vibe_legendary = []
        for _ in range(10):
            result = vibe_check(pack)
            self.assertIsNone(result)

    def test_show_vibe_no_crash(self):
        """show_vibe() doesn't crash with any pack state."""
        from freq.core.personality import PersonalityPack, show_vibe
        import io
        pack = PersonalityPack()
        pack.vibe_enabled = False
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            show_vibe(pack)  # Should not crash
        finally:
            sys.stdout = old_stdout


if __name__ == "__main__":
    unittest.main()
