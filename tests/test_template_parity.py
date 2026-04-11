"""Tests for package template / conf example parity.

Bug: freq/data/conf-templates/*.example and conf/*.example diverged
silently. Package templates (seeded by bootstrap_conf) had different
content than the top-level examples. New users got different defaults
depending on whether they installed via install.sh (conf/ examples)
or bootstrap_conf() (package templates).

Contract: freq/data/conf-templates/ is the canonical source.
conf/*.example must be identical copies. Docker conf/*.example
must also match (synced separately).
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = FREQ_ROOT / "freq" / "data" / "conf-templates"
CONF_DIR = FREQ_ROOT / "conf"


class TestTemplateConfParity(unittest.TestCase):
    """Package templates and conf/ examples must be identical."""

    def test_all_templates_have_conf_example(self):
        """Every package template must have a matching conf/ example."""
        templates = sorted(TEMPLATES_DIR.glob("*.example"))
        missing = []
        for t in templates:
            conf_path = CONF_DIR / t.name
            if not conf_path.is_file():
                missing.append(t.name)
        self.assertEqual(missing, [],
                         f"Templates without conf/ examples: {missing}")

    def test_all_conf_examples_have_template(self):
        """Every conf/ example must have a matching package template."""
        examples = sorted(CONF_DIR.glob("*.example"))
        missing = []
        for e in examples:
            tmpl_path = TEMPLATES_DIR / e.name
            if not tmpl_path.is_file():
                missing.append(e.name)
        self.assertEqual(missing, [],
                         f"Conf examples without templates: {missing}")

    def test_content_is_identical(self):
        """Package template and conf/ example content must be byte-identical."""
        templates = sorted(TEMPLATES_DIR.glob("*.example"))
        diffs = []
        for t in templates:
            conf_path = CONF_DIR / t.name
            if conf_path.is_file():
                t_content = t.read_bytes()
                c_content = conf_path.read_bytes()
                if t_content != c_content:
                    diffs.append(t.name)
        self.assertEqual(diffs, [],
                         f"Content differs: {diffs}")


class TestTemplateDefaults(unittest.TestCase):
    """Package templates must encode the correct default values."""

    def test_freq_toml_default_service_account(self):
        """freq.toml.example must show freq-admin as default."""
        content = (TEMPLATES_DIR / "freq.toml.example").read_text()
        self.assertIn("freq-admin", content)

    def test_personality_templates_exist(self):
        """Personality templates must be available for bootstrap seeding."""
        personality_dir = TEMPLATES_DIR / "personality"
        self.assertTrue(personality_dir.is_dir(),
                        "personality/ must exist in package templates")
        self.assertTrue((personality_dir / "default.toml").is_file(),
                        "default.toml personality must exist")


if __name__ == "__main__":
    unittest.main()
