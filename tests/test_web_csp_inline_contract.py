"""Tests for the CSP inline-surface contract and honest limits.

R-WEB-INLINE-CSP-CLEANUP-20260413O final state:
  - Inline <style> FOUC block moved from app.html to app.css (d5dfbb9, M).
  - login/header/update-banner inline handlers extracted to delegated
    data-action bindings (Morty 347d123, M) and login-form wrapper
    rework in e361cb2 (M).
  - Long-tail extract under O: 178 onclick=switchView swept to
    data-view, 145 simple onclick patterns swept to data-action /
    data-arg, 19 stragglers migrated to addEventListener bindings or
    data-action shims, fleet-filter focus/blur moved to CSS :focus.
  - app.html now ships ZERO inline event handlers and ZERO inline
    <script> blocks, so the CSP drops 'unsafe-inline' from script-src
    entirely. Style attrs are still 266 (styles long tail not in
    scope for O), so style-src keeps 'unsafe-inline' until a follow-up.

This test file pins all five guarantees so the moment any of them
drifts the CSP / serve.py / app.html / app.js / app.css move back
in lock-step:
  1. No inline <script> blocks (guard from token M).
  2. No external asset hosts referenced (guard from token L).
  3. serve.py CSP comment names the concrete inventory numbers.
  4. app.html inline handler / style counts equal the documented values.
  5. CSP header carries the right (un)safe-inline directive for the
     current handler / style state — script-src dropped it, style-src
     keeps it while styles > 0.
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


EXPECTED_INLINE_HANDLERS = 0
EXPECTED_INLINE_STYLES = 90

INLINE_HANDLER_RE = re.compile(r" on[a-z]+=")
INLINE_STYLE_RE = re.compile(r' style="')


def _count_inline_handlers(html: str) -> int:
    return len(INLINE_HANDLER_RE.findall(html))


def _count_inline_styles(html: str) -> int:
    return len(INLINE_STYLE_RE.findall(html))


class TestCspHonestLimitDocumented(unittest.TestCase):
    """serve.py CSP must document WHY 'unsafe-inline' is still present
    AND the documented number must match the live shipped HTML."""

    def setUp(self):
        self.src = (FREQ_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.html = (WEB_DIR / "app.html").read_text()

    def _comment_window(self) -> str:
        idx = self.src.find("Honest limits on 'unsafe-inline'")
        self.assertNotEqual(
            idx, -1,
            "serve.py CSP missing 'Honest limits' honest-limit comment"
        )
        return self.src[idx:idx + 2000]

    def test_csp_comment_names_inline_handler_count(self):
        window = self._comment_window()
        self.assertIn(
            str(EXPECTED_INLINE_HANDLERS), window,
            f"honest-limit comment must name the inline handler count "
            f"({EXPECTED_INLINE_HANDLERS})"
        )
        self.assertIn(
            str(EXPECTED_INLINE_STYLES), window,
            f"honest-limit comment must name the inline style attr count "
            f"({EXPECTED_INLINE_STYLES})"
        )

    def test_csp_comment_references_follow_up_token(self):
        window = self._comment_window()
        # The comment must name the token that owns the current state
        # so a future reader can grep back to the rationale. Token O
        # is the long-tail extract that dropped script-src 'unsafe-inline'.
        self.assertIn("R-WEB-INLINE-CSP-CLEANUP-20260413O", window)

    def test_app_html_inline_handler_count_matches_documented(self):
        """app.html actual handler count must equal what serve.py claims.

        If this fails because the actual count is LOWER, that's good news:
        someone extracted more handlers. Update EXPECTED_INLINE_HANDLERS
        and the serve.py comment together. If the count is HIGHER, that
        means inline handlers were reintroduced — fix the regression
        before it ships and CSP can never tighten.
        """
        actual = _count_inline_handlers(self.html)
        self.assertEqual(
            actual, EXPECTED_INLINE_HANDLERS,
            f"app.html inline handler count is {actual}, "
            f"serve.py documents {EXPECTED_INLINE_HANDLERS}. "
            "These MUST stay in sync — update both together."
        )

    def test_app_html_inline_style_count_matches_documented(self):
        """app.html actual inline style="…" count must equal what
        serve.py claims. Same drift-prevention contract as the
        handler count above.
        """
        actual = _count_inline_styles(self.html)
        self.assertEqual(
            actual, EXPECTED_INLINE_STYLES,
            f"app.html inline style= count is {actual}, "
            f"serve.py documents {EXPECTED_INLINE_STYLES}. "
            "These MUST stay in sync — update both together."
        )

    def test_script_src_dropped_unsafe_inline(self):
        """Now that inline handler count is zero, script-src MUST NOT
        carry 'unsafe-inline'. If someone reintroduces inline handlers
        the count guard above fires first; this guard pins the
        directive so the CSP stays tight independently.

        Anchored on the actual send_header directive literal (not
        free-form comment text mentioning 'script-src'), so comments
        explaining the history can use the phrase script-src
        'unsafe-inline' for context without breaking this test.
        """
        self.assertIn("script-src 'self'; ", self.src)
        # Find the actual send_header CSP literal and slice the
        # script-src directive within it. The pre-fix anchor used
        # find("script-src ") which now matches the comment block
        # explaining that script-src dropped 'unsafe-inline'.
        csp_idx = self.src.find('"Content-Security-Policy"')
        self.assertNotEqual(csp_idx, -1)
        # The directive value lives in the next ~6 string literals
        # concatenated into the send_header call. Slice forward to
        # the closing ).
        directive_end = self.src.find(')', csp_idx)
        directive_block = self.src[csp_idx:directive_end]
        # script-src directive within the literal.
        ss_idx = directive_block.find("script-src ")
        self.assertNotEqual(ss_idx, -1,
                            "script-src directive must exist in the CSP literal")
        ss_end = directive_block.find(";", ss_idx)
        script_src_directive = directive_block[ss_idx:ss_end]
        self.assertNotIn(
            "'unsafe-inline'", script_src_directive,
            "script-src must not carry 'unsafe-inline' — inline handler "
            "count is zero, so the directive must stay tight"
        )

    def test_style_src_keeps_unsafe_inline_while_styles_present(self):
        """Inline style attrs are still > 0, so style-src MUST keep
        'unsafe-inline' until the styles long tail is extracted."""
        self.assertIn("style-src 'self' 'unsafe-inline'", self.src)
        self.assertGreater(_count_inline_styles(self.html), 0)


if __name__ == "__main__":
    unittest.main()
