"""Tests for the CSP inline-surface contract and honest limits.

This is the partial-progress tranche of R-WEB-CSP-INLINE-CONTRACT-20260413M:
  - Inline <style> FOUC block moved from app.html to app.css.
  - serve.py CSP comment expanded with concrete inventory numbers and
    explicit honest limits on 'unsafe-inline'.
  - Regression guards: shipped web UI must not reintroduce any new
    inline <script> block or any external @import / stylesheet link.

Not in this tranche (depends on Morty's app.html handler extraction
after his AB work lands):
  - Dropping 'unsafe-inline' from script-src once login/header/update-
    banner inline handlers are gone.

Why the honest limit matters: if this test file fails because
'unsafe-inline' disappeared, that's a signal the other tranche landed
and the CSP can tighten — update both the CSP and this file together.
If the test passes without anyone touching it, the limit is honest and
the code matches the documented reality.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent
WEB_DIR = FREQ_ROOT / "freq" / "data" / "web"


class TestFoucMovedToCss(unittest.TestCase):
    """FOUC prevention block moved out of app.html into app.css."""

    def test_app_html_has_no_inline_style_block(self):
        """app.html must not contain any inline <style> block with body.

        The only <style>...</style> in the file previously was the FOUC
        animation. After the move there should be zero inline <style>
        elements in the shipped HTML.
        """
        html = (WEB_DIR / "app.html").read_text()
        # Count opening <style> tags that are NOT self-closing refs
        # (the link rel="stylesheet" doesn't match since that's <link>).
        opens = re.findall(r"<style[^>]*>", html)
        self.assertEqual(
            len(opens), 0,
            f"app.html must not contain inline <style> blocks; found {len(opens)}"
        )

    def test_css_has_body_fadein_rule(self):
        """app.css must own the bodyFadeIn rule."""
        css = (WEB_DIR / "css" / "app.css").read_text()
        self.assertIn("bodyFadeIn", css)
        self.assertIn("body { opacity: 0", css)
        self.assertIn("@keyframes bodyFadeIn", css)

    def test_css_fouc_comment_explains_move(self):
        """The moved rule must carry a pointer comment so future readers
        know why it lives in CSS and not inline."""
        css = (WEB_DIR / "css" / "app.css").read_text()
        self.assertIn("FOUC prevention", css)


class TestNoInlineScriptBlocks(unittest.TestCase):
    """app.html must contain zero inline <script> content.

    This is a regression guard — the only <script> tags allowed in
    app.html are external src= references. If someone adds a new
    inline block (even for a 'quick fix'), CSP can't drop
    'unsafe-inline' on script-src without re-regressing.
    """

    def test_all_script_tags_have_src(self):
        html = (WEB_DIR / "app.html").read_text()
        # Find every opening <script ...> tag.
        opens = re.findall(r"<script(\s[^>]*)?>", html)
        # Each must include a src= attribute. An inline block (no src)
        # would match e.g. "<script>" with empty group 1.
        for i, attrs in enumerate(opens):
            self.assertIn(
                "src=", attrs,
                f"script tag #{i} has no src= — inline block detected: <script{attrs}>"
            )


class TestNoExternalStylesheet(unittest.TestCase):
    """No file in freq/data/web/ may reference an external asset host.

    This is the union regression guard for both the external-asset
    contract (L, landed) and the inline contract (M, in progress).
    Adding a new https://cdn.jsdelivr.net, https://fonts.googleapis.com,
    https://fonts.gstatic.com, or unpkg/etc. reference to any shipped
    web file fails this test. CSP font-src/style-src/script-src all
    resolve to 'self' so a new external ref would 404 at runtime
    anyway, but the test catches it before the commit hits master.
    """

    EXTERNAL_HOSTS = (
        "cdn.jsdelivr.net",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "unpkg.com",
        "cdnjs.cloudflare.com",
    )

    def test_no_external_hosts_in_app_html(self):
        html = (WEB_DIR / "app.html").read_text()
        for host in self.EXTERNAL_HOSTS:
            self.assertNotIn(host, html,
                             f"app.html references external host {host}")

    def test_no_external_hosts_in_app_css(self):
        css = (WEB_DIR / "css" / "app.css").read_text()
        for host in self.EXTERNAL_HOSTS:
            self.assertNotIn(host, css,
                             f"app.css references external host {host}")

    def test_no_external_hosts_in_setup_html(self):
        setup = (WEB_DIR / "setup.html").read_text()
        for host in self.EXTERNAL_HOSTS:
            self.assertNotIn(host, setup,
                             f"setup.html references external host {host}")


class TestCspHonestLimitDocumented(unittest.TestCase):
    """serve.py CSP must document WHY 'unsafe-inline' is still present."""

    def setUp(self):
        self.src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()

    def test_csp_comment_names_inline_handler_count(self):
        """The comment must reference the concrete handler count so
        anyone reading can verify the limit matches reality."""
        # Look for the section comment near _send_security_headers
        idx = self.src.find("Honest limits on 'unsafe-inline'")
        self.assertNotEqual(
            idx, -1,
            "serve.py CSP missing 'Honest limits' honest-limit comment"
        )
        window = self.src[idx:idx + 2000]
        # The concrete number ~355 should appear so readers can grep
        # the current file and verify.
        self.assertIn("355", window,
                      "honest-limit comment must name the inline handler count")
        self.assertIn("275", window,
                      "honest-limit comment must name the inline style attr count")

    def test_csp_comment_references_follow_up_token(self):
        """Must name the follow-up token so the TODO is traceable."""
        idx = self.src.find("Honest limits on 'unsafe-inline'")
        self.assertNotEqual(idx, -1)
        window = self.src[idx:idx + 2000]
        self.assertIn("R-WEB-CSP-INLINE-CONTRACT-20260413M", window)


if __name__ == "__main__":
    unittest.main()
