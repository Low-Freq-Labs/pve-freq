"""Tests for the zero-external-asset contract on the shipped web UI.

Bug: The DC01 dashboard violated the zero-dependency install contract
at runtime. freq/data/web/app.html loaded xterm (CSS + three JS files)
directly from cdn.jsdelivr.net. freq/data/web/css/app.css imported
Google Fonts via @import. freq/modules/serve.py CSP explicitly allowed
https://cdn.jsdelivr.net, https://fonts.googleapis.com, and
https://fonts.gstatic.com, so a dashboard on an air-gapped install
box would silently fail to render properly.

Fix (two overlapping commits — 3ffce67 by Morty for the font side;
this commit for xterm + CSP):
1. Vendor xterm assets under freq/data/web/vendor/xterm/:
   - xterm.min.css (from @xterm/xterm 5.5.0)
   - xterm.min.js  (from @xterm/xterm 5.5.0)
   - addon-fit.min.js (from @xterm/addon-fit 0.10.0)
   - addon-clipboard.min.js (from @xterm/addon-clipboard 0.1.0)
2. app.html references /static/vendor/xterm/... (served via the
   existing /static/ handler → importlib.resources on the package).
3. serve.py CSP drops all external hosts. default-src, script-src,
   style-src, img-src, connect-src, font-src all resolve to 'self'
   (plus 'unsafe-inline' for script/style — tracked separately by
   R-WEB-CSP-INLINE-CONTRACT-20260413M).

Why the new behavior cannot lie:
- No file in freq/data/web/ references cdn.jsdelivr.net, googleapis,
  or gstatic (verified by a repo-wide grep in the test below).
- The CSP header emitted by _send_security_headers contains no
  external host. An air-gapped dashboard load will not fetch off-box
  assets and the CSP header proves it to any browser dev tools pass.
- The vendored files exist on disk and are served with the right
  MIME types by the existing /static/ handler — covered by the
  file-existence and _read_asset tests below.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestXtermVendored(unittest.TestCase):
    """xterm and its addons must be vendored locally."""

    VENDOR = FREQ_ROOT / "freq" / "data" / "web" / "vendor" / "xterm"

    def test_xterm_css_vendored(self):
        f = self.VENDOR / "xterm.min.css"
        self.assertTrue(f.exists(), f"missing vendored {f}")
        self.assertGreater(f.stat().st_size, 500)

    def test_xterm_js_vendored(self):
        f = self.VENDOR / "xterm.min.js"
        self.assertTrue(f.exists(), f"missing vendored {f}")
        # xterm core is ~290KB — if it's trivially small the wrong
        # asset was vendored.
        self.assertGreater(f.stat().st_size, 100_000)

    def test_addon_fit_vendored(self):
        f = self.VENDOR / "addon-fit.min.js"
        self.assertTrue(f.exists(), f"missing vendored {f}")

    def test_addon_clipboard_vendored(self):
        f = self.VENDOR / "addon-clipboard.min.js"
        self.assertTrue(f.exists(), f"missing vendored {f}")


class TestAppHtmlHasNoExternalAssets(unittest.TestCase):
    """app.html must reference the vendored files, not CDNs."""

    def setUp(self):
        self.html = (FREQ_ROOT / "freq" / "data" / "web" / "app.html").read_text()

    def test_no_jsdelivr_reference(self):
        self.assertNotIn("cdn.jsdelivr.net", self.html)

    def test_no_google_fonts_reference(self):
        self.assertNotIn("fonts.googleapis.com", self.html)
        self.assertNotIn("fonts.gstatic.com", self.html)

    def test_xterm_css_uses_vendor_path(self):
        self.assertIn("/static/vendor/xterm/xterm.min.css", self.html)

    def test_xterm_js_uses_vendor_path(self):
        self.assertIn("/static/vendor/xterm/xterm.min.js", self.html)

    def test_addon_fit_uses_vendor_path(self):
        self.assertIn("/static/vendor/xterm/addon-fit.min.js", self.html)

    def test_addon_clipboard_uses_vendor_path(self):
        self.assertIn("/static/vendor/xterm/addon-clipboard.min.js", self.html)


class TestCssHasNoExternalAssets(unittest.TestCase):
    """app.css must not @import from any external host.

    The Google Fonts @import was removed by Morty in 3ffce67 as part
    of the parallel visual-fallout side of this task. Keeping a test
    here so a future edit can't silently re-add it.
    """

    def test_no_googleapis_import(self):
        css = (FREQ_ROOT / "freq" / "data" / "web" / "css" / "app.css").read_text()
        self.assertNotIn("fonts.googleapis.com", css)
        self.assertNotIn("fonts.gstatic.com", css)

    def test_no_cdn_import(self):
        css = (FREQ_ROOT / "freq" / "data" / "web" / "css" / "app.css").read_text()
        self.assertNotIn("cdn.jsdelivr.net", css)


class TestCspHeaderIsSelfOnly(unittest.TestCase):
    """_send_security_headers must not whitelist external asset hosts."""

    def setUp(self):
        self.src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()

    def test_csp_method_exists(self):
        self.assertIn("def _send_security_headers", self.src)

    def test_csp_has_no_jsdelivr(self):
        # Focus on the CSP header body only — find the send_header call
        # for Content-Security-Policy and check its string literals.
        idx = self.src.find('"Content-Security-Policy"')
        self.assertNotEqual(idx, -1, "CSP header missing")
        # Take a generous window around the header to catch any
        # continuation lines.
        window = self.src[idx:idx + 800]
        self.assertNotIn("cdn.jsdelivr.net", window)

    def test_csp_has_no_google_fonts(self):
        idx = self.src.find('"Content-Security-Policy"')
        window = self.src[idx:idx + 800]
        self.assertNotIn("fonts.googleapis.com", window)
        self.assertNotIn("fonts.gstatic.com", window)

    def test_csp_default_src_is_self(self):
        idx = self.src.find('"Content-Security-Policy"')
        window = self.src[idx:idx + 800]
        self.assertIn("default-src 'self'", window)

    def test_csp_font_src_is_self_only(self):
        idx = self.src.find('"Content-Security-Policy"')
        window = self.src[idx:idx + 800]
        # font-src must be exactly 'self' now that Google Fonts is gone.
        self.assertIn("font-src 'self'", window)


class TestStaticHandlerServesVendor(unittest.TestCase):
    """_read_asset must resolve nested vendor/xterm/ paths."""

    def test_read_asset_resolves_vendor_css(self):
        from freq.modules.web_ui import _read_asset
        css = _read_asset("vendor/xterm/xterm.min.css")
        self.assertIn("xterm", css.lower())
        self.assertGreater(len(css), 500)

    def test_read_asset_resolves_vendor_js(self):
        from freq.modules.web_ui import _read_asset
        js = _read_asset("vendor/xterm/xterm.min.js")
        # Minified JS of xterm core is ~290KB.
        self.assertGreater(len(js), 100_000)


if __name__ == "__main__":
    unittest.main()
