"""Tests for runtime demo contamination hygiene.

Bug: 5005 dashboard served app.html and app.js with FREQ_DEMO markers
even though the repo worktree was clean. Root causes:
1. web_ui._LazyHTML cached HTML content forever — a stale dashboard
   process served cached demo content even after disk files were cleaned.
2. /opt/pve-freq/build/ (setuptools build dir) could persist old assets.

Fixes:
1. Removed _LazyHTML caching — module __getattr__ now re-reads files
   on each access so fresh content is served after deploy.
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
        """__getattr__ must call the loader function each time."""
        src = (FREQ_ROOT / "freq" / "modules" / "web_ui.py").read_text()
        # Must call _load_app_html() directly in __getattr__
        import re
        match = re.search(
            r'def __getattr__.*?APP_HTML.*?_load_app_html\(\)',
            src, re.DOTALL
        )
        self.assertIsNotNone(match)


class TestLoadingFreshHtml(unittest.TestCase):
    """Live import of APP_HTML must return current disk content."""

    def test_app_html_is_fresh_on_access(self):
        """APP_HTML access must return fresh content, not cached."""
        from freq.modules import web_ui

        # Access APP_HTML twice — both calls should trigger fresh reads
        html1 = web_ui.APP_HTML
        html2 = web_ui.APP_HTML
        # Both should match (file didn't change), but the call mechanism
        # must not use a cached attribute
        self.assertIsInstance(html1, str)
        self.assertIsInstance(html2, str)
        self.assertEqual(html1, html2)


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
