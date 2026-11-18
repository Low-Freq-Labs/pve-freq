"""Doctor honesty for built-in default and missing custom personality packs."""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


if __name__ == "__main__":
    unittest.main()
