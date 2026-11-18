"""Tests for runtime demo contamination hygiene.

Bug: 5005 dashboard served app.html and app.js with FREQ_DEMO markers
even though the repo worktree was clean. Root causes:
1. web_ui._LazyHTML cached HTML content forever — a stale dashboard
   process served cached demo content even after disk files were cleaned.
2. /opt/pve-freq/build/ (setuptools build dir) could persist old assets.

Fixes:
1. Removed _LazyHTML caching and module attribute aliases. Public loader
   functions re-read the complete frontend bundle on every request.
2. deploy-test.sh now explicitly removes ${RUNTIME_DIR}/build before
   rsync and excludes /build/ from the sync to prevent stale artifacts.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestNoLazyHtmlCache(unittest.TestCase):
    """web_ui must not cache HTML content — every access should re-read."""

    def test_no_lazy_html_class(self):
        """_LazyHTML class must be removed."""
        src = (FREQ_ROOT / "freq" / "modules" / "web_ui.py").read_text()
        self.assertNotIn("class _LazyHTML", src)

    def test_no_persistent_cache(self):
        """Module must not have a _cache attribute."""
        src = (FREQ_ROOT / "freq" / "modules" / "web_ui.py").read_text()
        self.assertNotIn("self._cache = None", src)

    def test_getattr_calls_loader(self):
        """Only explicit public fresh-read loaders may expose HTML."""
        src = (FREQ_ROOT / "freq" / "modules" / "web_ui.py").read_text()
        self.assertNotIn("def __getattr__", src)
        self.assertNotIn('if name == "APP_HTML"', src)
        self.assertNotIn('if name == "SETUP_HTML"', src)
        self.assertIn("def load_app_html()", src)
        self.assertIn("def load_setup_html()", src)


class TestLoadingFreshHtml(unittest.TestCase):
    """Public HTML loaders must return current disk content."""

    def test_app_html_is_fresh_on_access(self):
        """Repeated loader calls must read the frontend bundle each time."""
        from unittest.mock import patch

        from freq.modules import web_ui

        original = web_ui.read_asset
        with patch.object(web_ui, "read_asset", wraps=original) as reader:
            html1 = web_ui.load_app_html()
            html2 = web_ui.load_app_html()
        self.assertIsInstance(html1, str)
        self.assertIsInstance(html2, str)
        self.assertEqual(html1, html2)
        self.assertEqual(reader.call_count, 2 * len(web_ui.FRONTEND_ASSET_MANIFEST))


class TestDeployHarnessCleansBuildDir(unittest.TestCase):
    """deploy-test.sh must remove stale build/ artifacts."""

    def test_removes_build_dir(self):
        """Script must rm -rf ${RUNTIME_DIR}/build before rsync."""
        src = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()
        self.assertIn("rm -rf ${RUNTIME_DIR}/build", src)

    def test_rsync_excludes_build(self):
        """Rsync must exclude /build/ to prevent stale artifacts syncing in."""
        src = (FREQ_ROOT / "contrib" / "deploy-test.sh").read_text()
        self.assertIn("--exclude='/build/'", src)


if __name__ == "__main__":
    unittest.main()
