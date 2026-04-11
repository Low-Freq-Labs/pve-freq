"""Regression tests for CONTRIBUTING.md developer guide truthfulness.

Proves: code patterns and examples in CONTRIBUTING.md match the
actual codebase conventions. A contributor following the guide must
produce code that works with the current architecture.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read_contributing():
    with open(os.path.join(REPO_ROOT, "CONTRIBUTING.md")) as f:
        return f.read()


class TestContributingApiPattern(unittest.TestCase):
    """API endpoint guide must match actual handler patterns."""

    def setUp(self):
        self.doc = _read_contributing()

    def test_guide_uses_freq_api_modules(self):
        """Guide must direct new endpoints to freq/api/, not serve.py."""
        self.assertIn("freq/api/", self.doc)
        # Must NOT show the old tuple-based route format
        self.assertNotIn('("_handle_', self.doc,
                         "Guide must not show old tuple route format")

    def test_guide_shows_handler_signature(self):
        """Handler example must use (handler) signature, not (self, params)."""
        self.assertIn("def handle_my_feature(handler):", self.doc)
        self.assertNotIn("(self, params)", self.doc,
                         "Old (self, params) signature must not appear in guide")

    def test_guide_shows_require_post(self):
        """Guide must mention require_post for POST endpoints."""
        self.assertIn("require_post", self.doc)

    def test_guide_shows_check_session_role(self):
        """Guide must show auth check pattern."""
        self.assertIn("check_session_role", self.doc)

    def test_guide_shows_json_response(self):
        """Guide must use json_response helper."""
        self.assertIn("json_response", self.doc)

    def test_guide_mentions_api_reference_update(self):
        """Guide must remind contributors to update API-REFERENCE.md."""
        self.assertIn("API-REFERENCE.md", self.doc)


class TestContributingCliPattern(unittest.TestCase):
    """CLI command guide must match actual dispatcher patterns."""

    def setUp(self):
        self.doc = _read_contributing()

    def test_guide_shows_add_parser(self):
        """Guide must show argparse add_parser pattern."""
        self.assertIn("add_parser", self.doc)

    def test_guide_shows_set_defaults(self):
        """Guide must show set_defaults(func=...) pattern."""
        self.assertIn("set_defaults", self.doc)

    def test_guide_shows_lazy_import(self):
        """Guide must show lazy import pattern in dispatcher."""
        self.assertIn("from freq.modules", self.doc)


class TestContributingDevSetup(unittest.TestCase):
    """Development setup instructions must be valid."""

    def setUp(self):
        self.doc = _read_contributing()

    def test_shows_pip_install_editable(self):
        """Dev setup must use pip install -e ."""
        self.assertIn("pip install -e .", self.doc)

    def test_shows_pytest(self):
        """Test command must use pytest."""
        self.assertIn("pytest", self.doc)

    def test_zero_deps_rule_documented(self):
        """Zero dependencies rule must be documented."""
        self.assertIn("No external Python packages", self.doc)

    def test_repo_url_correct(self):
        """Clone URL must match pyproject homepage."""
        self.assertIn("Low-Freq-Labs/pve-freq", self.doc)


if __name__ == "__main__":
    unittest.main()
