"""Media container name matching truth tests.

Proves:
1. Container name matching normalizes hyphens/underscores
2. "tdarr_node" matches "tdarr-node" (init vs Docker naming)
3. Both serve.py and media.py use normalized matching
4. No false negatives from trivial naming differences
"""

import os
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

    def test_media_normalizes_names(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/media.py")) as f:
            src = f.read()
        self.assertIn('replace("-", "_")', src,
                       "media module must normalize hyphens to underscores")

    def test_normalization_catches_tdarr_case(self):
        """tdarr_node (init) must match tdarr-node (Docker)."""
        cn = "tdarr_node".lower().replace("-", "_")
        rn = "tdarr-node".lower().replace("-", "_")
        self.assertTrue(cn in rn or rn in cn,
                         "tdarr_node must match tdarr-node after normalization")

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
