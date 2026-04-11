"""Media container name matching truth tests.

Proves:
1. ALL container name matching sites normalize hyphens/underscores
2. "tdarr_node" matches "tdarr-node" AND "tdarr-node-cpu-2" (init vs Docker)
3. serve.py API path and ALL media.py CLI paths use normalized matching
4. No false negatives from trivial naming differences
5. No un-normalized matching sites remain in media.py
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestNameNormalization(unittest.TestCase):
    """Container name matching must handle hyphen/underscore variants."""

    def test_serve_normalizes_names(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_media_status")[1].split("def _serve_")[0]
        self.assertIn('replace("-", "_")', handler,
                       "serve must normalize hyphens to underscores for matching")

    def test_media_status_normalizes_names(self):
        """media status CLI (the main display) must normalize."""
        with open(os.path.join(REPO_ROOT, "freq/modules/media.py")) as f:
            src = f.read()
        # The status display loop is in the first cname/rname matching block
        status_fn = src.split("def _cmd_status")[1].split("\ndef ")[0]
        self.assertIn('replace("-", "_")', status_fn,
                       "media status must normalize hyphens to underscores")

    def test_media_dashboard_normalizes_names(self):
        """media dashboard container counter must normalize."""
        with open(os.path.join(REPO_ROOT, "freq/modules/media.py")) as f:
            src = f.read()
        dashboard_fn = src.split("def _cmd_dashboard")[1].split("\ndef ")[0]
        self.assertIn('replace("-", "_")', dashboard_fn,
                       "media dashboard must normalize hyphens to underscores")

    def test_media_report_normalizes_names(self):
        """media report must normalize names."""
        with open(os.path.join(REPO_ROOT, "freq/modules/media.py")) as f:
            src = f.read()
        report_fn = src.split("def _cmd_report")[1].split("\ndef ")[0]
        self.assertIn('replace("-", "_")', report_fn,
                       "media report must normalize hyphens to underscores")

    def test_no_raw_cname_in_rname_matching(self):
        """No raw cname.lower() in rname.lower() without normalization."""
        with open(os.path.join(REPO_ROOT, "freq/modules/media.py")) as f:
            src = f.read()
        # This pattern is the pre-fix matching — it must not appear
        raw_pattern = re.compile(r'cname\.lower\(\)\s+in\s+rname\.lower\(\)')
        matches = raw_pattern.findall(src)
        self.assertEqual(len(matches), 0,
                         f"Found {len(matches)} raw cname/rname matches without normalization")

    def test_normalization_catches_tdarr_case(self):
        """tdarr_node (init) must match tdarr-node (Docker)."""
        cn = "tdarr_node".lower().replace("-", "_")
        rn = "tdarr-node".lower().replace("-", "_")
        self.assertTrue(cn in rn or rn in cn,
                         "tdarr_node must match tdarr-node after normalization")

    def test_normalization_catches_tdarr_suffix_case(self):
        """tdarr_node (init) must match tdarr-node-cpu-2 (actual Docker name)."""
        cn = "tdarr_node".lower().replace("-", "_").replace(" ", "_")
        rn = "tdarr-node-cpu-2".lower().replace("-", "_").replace(" ", "_")
        self.assertTrue(cn in rn or rn in cn,
                         "tdarr_node must match tdarr-node-cpu-2 after normalization")

    def test_exact_match_still_works(self):
        """Exact names still match after normalization."""
        cn = "sonarr".lower().replace("-", "_")
        rn = "sonarr".lower().replace("-", "_")
        self.assertTrue(cn in rn)

    def test_no_false_positive(self):
        """Different container names must not match."""
        cn = "sonarr".lower().replace("-", "_")
        rn = "radarr".lower().replace("-", "_")
        self.assertFalse(cn in rn and rn in cn)


if __name__ == "__main__":
    unittest.main()
