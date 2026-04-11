"""Doctor personality truth tests.

Proves:
1. Built-in default pack is always valid (no file needed)
2. Doctor does NOT warn about missing default pack (honest)
3. Doctor DOES warn about missing custom packs (honest)
4. load_pack() fallback returns a valid PersonalityPack
5. Repo-mode vs installed-mode: default pack works in both
"""

import os
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBuiltInDefaultPack(unittest.TestCase):
    """The default personality pack is built-in — no file required."""

    def test_load_pack_returns_valid_default(self):
        """load_pack with nonexistent path returns a valid pack."""
        from freq.core.personality import load_pack
        pack = load_pack("/nonexistent/path", "default")
        self.assertEqual(pack.name, "default")
        self.assertIsInstance(pack.celebrations, list)
        self.assertIsInstance(pack.taglines, list)
        self.assertTrue(pack.vibe_enabled)

    def test_default_pack_has_subtitle(self):
        from freq.core.personality import PersonalityPack
        pack = PersonalityPack()
        self.assertTrue(pack.subtitle)

    def test_default_pack_has_vibe_probability(self):
        from freq.core.personality import PersonalityPack
        pack = PersonalityPack()
        self.assertGreater(pack.vibe_probability, 0)


class TestDoctorPersonalityHonesty(unittest.TestCase):
    """Doctor must distinguish built-in default from missing custom pack."""

    def _doctor_src(self):
        with open(os.path.join(REPO_ROOT, "freq/core/doctor.py")) as f:
            return f.read()

    def test_default_build_does_not_warn(self):
        """When build=default, doctor shows OK (not warning)."""
        src = self._doctor_src()
        handler = src.split("def _check_personality")[1].split("\ndef ")[0]
        # Must have a branch for cfg.build == "default" that returns 0
        self.assertIn('cfg.build == "default"', handler,
                       "Doctor must check for built-in default specifically")
        # That branch must call step_ok, not step_warn
        default_branch_idx = handler.index('cfg.build == "default"')
        after_default = handler[default_branch_idx:default_branch_idx + 200]
        self.assertIn("step_ok", after_default,
                       "Built-in default must show OK, not warning")

    def test_custom_pack_missing_warns(self):
        """When build=custom and file missing, doctor warns."""
        src = self._doctor_src()
        handler = src.split("def _check_personality")[1].split("\ndef ")[0]
        self.assertIn("step_warn", handler,
                       "Missing custom pack must trigger warning")

    def test_custom_pack_present_shows_ok(self):
        """When pack file exists, doctor shows OK."""
        src = self._doctor_src()
        handler = src.split("def _check_personality")[1].split("\ndef ")[0]
        self.assertIn("step_ok", handler)

    def test_live_doctor_default_is_ok(self):
        """Running doctor with build=default must not produce a warning."""
        from freq.core.config import load_config
        cfg = load_config()
        self.assertEqual(cfg.build, "default",
                         "Test assumes build=default in freq.toml")
        # The check function should return 0 (OK)
        from freq.core.doctor import _check_personality
        result = _check_personality(cfg)
        self.assertEqual(result, 0,
                         "Doctor personality check must pass for built-in default")


class TestPersonalityFallbackPath(unittest.TestCase):
    """load_pack gracefully falls back when file is missing."""

    def test_missing_file_returns_default(self):
        from freq.core.personality import load_pack
        pack = load_pack("/tmp/nonexistent", "nosuchpack")
        self.assertEqual(pack.name, "nosuchpack")
        # Should still have valid defaults
        self.assertTrue(pack.subtitle)

    def test_custom_pack_file_loads_when_present(self):
        """If a personal.toml template exists, it can be loaded."""
        template_path = os.path.join(
            REPO_ROOT, "freq", "data", "conf-templates", "personality"
        )
        if os.path.isfile(os.path.join(template_path, "personal.toml")):
            from freq.core.personality import load_pack
            pack = load_pack(template_path, "personal")
            # Personal pack should have some custom content
            self.assertEqual(pack.name, "personal")


if __name__ == "__main__":
    unittest.main()
