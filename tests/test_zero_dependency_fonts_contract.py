"""Zero-dependency font contract tests.

Proves the shipped web UI has no runtime dependency on Google Fonts
(or any external font host). Users running DC01 in air-gapped
environments must get a usable UI without outbound calls to
fonts.googleapis.com / fonts.gstatic.com.

The visual direction is preserved via local/system fallbacks:
- 'Outfit' kept as the first choice — falls back to
  -apple-system / SF Pro Display / Segoe UI / Roboto / Ubuntu /
  system-ui when not locally installed
- 'JetBrains Mono' kept as first mono choice — falls back to
  SF Mono / Fira Code / Cascadia Code / Menlo / Consolas /
  DejaVu Sans Mono
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css():
    with open(os.path.join(REPO_ROOT, "freq/data/web/css/app.css")) as f:
        return f.read()


def _html():
    with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
        return f.read()


class TestNoGoogleFontsRuntimeImport(unittest.TestCase):
    """app.css must not @import from fonts.googleapis.com."""

    def test_no_google_fonts_import_in_css(self):
        css = _css()
        self.assertNotIn("fonts.googleapis.com", css,
                          "app.css must not import from fonts.googleapis.com")
        self.assertNotIn("fonts.gstatic.com", css,
                          "app.css must not reference fonts.gstatic.com")

    def test_no_at_import_url(self):
        """No @import url(...) at all — a blanket guard."""
        css = _css()
        # Allow @import for local files, but none currently exist
        self.assertNotIn("@import url(", css,
                          "app.css must not use @import url() for runtime font fetch")


class TestNoGoogleFontsInHtml(unittest.TestCase):
    """app.html must not link to fonts.googleapis.com either."""

    def test_no_google_fonts_link_in_html(self):
        html = _html()
        self.assertNotIn("fonts.googleapis.com", html,
                          "app.html must not <link> to fonts.googleapis.com")
        self.assertNotIn("fonts.gstatic.com", html,
                          "app.html must not reference fonts.gstatic.com")


class TestSystemFontFallbacks(unittest.TestCase):
    """Font variables must declare system fallback stacks so the UI
    renders correctly even when Outfit / JetBrains Mono are absent."""

    def test_font_ui_has_system_fallbacks(self):
        css = _css()
        # The --font-ui var must include at least one system-stack entry
        # after 'Outfit'
        idx = css.find("--font-ui:")
        self.assertGreater(idx, 0, "--font-ui must be declared")
        line = css[idx: css.find(";", idx)]
        self.assertIn("-apple-system", line,
                       "--font-ui must include -apple-system")
        self.assertIn("system-ui", line,
                       "--font-ui must include system-ui")
        self.assertIn("sans-serif", line,
                       "--font-ui must end with sans-serif")

    def test_font_mono_has_system_fallbacks(self):
        css = _css()
        idx = css.find("--font-mono:")
        self.assertGreater(idx, 0, "--font-mono must be declared")
        line = css[idx: css.find(";", idx)]
        # Must contain at least one common mono system font
        has_system_mono = any(
            name in line for name in ["SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono"]
        )
        self.assertTrue(has_system_mono,
                         "--font-mono must include a system mono (SF Mono/Menlo/Consolas/DejaVu)")
        self.assertIn("monospace", line,
                       "--font-mono must end with monospace")


if __name__ == "__main__":
    unittest.main()
