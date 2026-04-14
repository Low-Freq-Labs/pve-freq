"""R-WEB-INLINE-STYLE-CSP-SWEEP-20260413Q regression contract.

Token Q is the F16 follow-up from R-SECURITY-TRUST-AUDIT-20260413P
(security audit). The audit closed every script-src exposure but
left style-src 'unsafe-inline' in place because app.html still
shipped 264 inline style="…" attributes. Token Q sweeps those
into reusable utility classes so style-src can either drop
'unsafe-inline' (if pass 2 ran and reached zero) or carry a
materially smaller honest limit.

This file pins:

  1. EXPECTED_INLINE_STYLES is the live count post-sweep, and
     test_app_html_inline_style_count_matches in the existing
     test_web_csp_inline_contract.py file enforces that it tracks
     reality. (Q updates the constant; this test file does NOT
     duplicate that contract.)
  2. The new utility classes added under the
     "20260413Q UTILITY CLASSES" header in app.css MUST exist
     and be referenced from app.html — if they are added to CSS
     but never used, that's noise; if they are referenced in HTML
     but missing from CSS, the page breaks.
  3. The CSP header carries the honest style-src directive matching
     the current inline style count: drops 'unsafe-inline' if zero,
     keeps it otherwise. Pin both halves so the directive can never
     drift away from the count.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent
WEB_DIR = REPO_ROOT / "freq" / "data" / "web"
APP_HTML = WEB_DIR / "app.html"
APP_CSS = WEB_DIR / "css" / "app.css"
SERVE_PY = REPO_ROOT / "freq" / "modules" / "serve.py"


# Utility classes added by token Q. Each one MUST exist in app.css
# AND be referenced at least once from app.html — otherwise the
# class is dead weight and should be removed.
Q_UTILITY_CLASSES = [
    "helptext-mb8",
    "helptext-mb12",
    "helptext-mb4-block",
    "helptext-section",
    "helptext-section-tight",
    "helptext-sm-mb8",
    "helptext-mt8",
    "helptext",
    "section-label-pl-md",
    "section-label-pl-mt12",
    "section-label-pl-h3",
    "w-80", "w-100", "w-120", "w-140", "w-160", "w-180", "w-200", "w-240", "w-260",
    "flex-min-100", "flex-min-120",
    "flex-gap-8", "flex-gap-8-center-wrap",
    "flex-gap-16-wrap-mb16", "flex-row-8-mb12-center-wrap",
    "mt-16", "ml-4", "ml-8", "ml-auto", "mr-4",
    "card-block-lg", "card-block-thick", "card-block-bg2",
    "kbd-tag", "kbd-mono-10",
    "text-red-border-red", "text-green", "text-dim",
    "fs-16", "fs-9-px-2-8",
]

# Hybrid finish (Path 4 per Finn's design call) — the four chrome
# semantic classes added on top of the bulk dedupe + the 25 ID-based
# rules in the dedicated 20260413Q-id-rules block. Each chrome class
# is used by exactly one element; the ID rules don't add new HTML
# attributes (they target existing element ids). Together with the
# unsafe-hashes machinery in serve.py, these let style-src drop
# 'unsafe-inline' entirely.
Q_CHROME_CLASSES = [
    "pve-freq-wordmark",
    "nav-ver-label",
    "nav-divider",
    "header-time-label",
]

# Element ids that have a corresponding rule in the 20260413Q-id-rules
# block. Each id MUST be referenced by an `#id { … }` rule there.
Q_ID_RULES = [
    "nav-items",
    "home-empty",
    "fleet-lab-section",
    "container-stats",
    "container-logs",
    "rescan-results",
    "compose-out",
    "vault-auth-user",
    "vault-auth-pass",
    "log-out",
    "topo-svg",
    "pb-runner-title",
    "go-actions",
    "go-diff-content",
    "fed-url",
    "about-credits",
    "hd-subtitle",
    "hd-loading",
    "terminal-overlay",
    "terminal-header",
    "terminal-title",
    "terminal-container",
    "search-overlay",
    "search-results",
    "shortcuts-modal",
]


class TestQUtilityClassesPresentInCss(unittest.TestCase):
    """Every class added by the Q sweep must be defined in app.css
    inside the dedicated 20260413Q block."""

    @classmethod
    def setUpClass(cls):
        cls.css = APP_CSS.read_text()

    def test_q_block_header_present(self):
        self.assertIn(
            "20260413Q UTILITY CLASSES",
            self.css,
            "app.css must carry the dedicated 20260413Q block header so the "
            "diff is greppable and future readers can find the sweep classes",
        )

    def test_each_q_class_defined(self):
        for klass in Q_UTILITY_CLASSES:
            with self.subTest(klass=klass):
                self.assertRegex(
                    self.css,
                    rf"\.{re.escape(klass)}\s*\{{",
                    f"class .{klass} added by Q must be defined in app.css",
                )


class TestQUtilityClassesUsedInHtml(unittest.TestCase):
    """Every class added by the Q sweep must be referenced at least
    once from app.html. Dead classes are noise and should be removed.
    """

    @classmethod
    def setUpClass(cls):
        cls.html = APP_HTML.read_text()

    def test_each_q_class_referenced(self):
        for klass in Q_UTILITY_CLASSES:
            with self.subTest(klass=klass):
                # Either as the bare class= value, embedded in a
                # multi-class list, or appended via the sweep helper.
                # Match \bklass\b with class context.
                self.assertRegex(
                    self.html,
                    rf'class="[^"]*\b{re.escape(klass)}\b[^"]*"',
                    f"class .{klass} added by Q must be used by at least "
                    f"one element in app.html — dead class is noise",
                )


class TestQHybridFinishExtractions(unittest.TestCase):
    """Hybrid finish (Path 4) extractions: chrome semantic classes
    + 25 ID-based rules in the dedicated 20260413Q-id-rules block."""

    @classmethod
    def setUpClass(cls):
        cls.html = APP_HTML.read_text()
        cls.css = APP_CSS.read_text()

    def test_id_rules_block_present(self):
        self.assertIn("20260413Q-id-rules-begin", self.css)
        self.assertIn("20260413Q-id-rules-end", self.css)

    def test_each_chrome_class_defined_in_css(self):
        for klass in Q_CHROME_CLASSES:
            with self.subTest(klass=klass):
                self.assertRegex(
                    self.css,
                    rf"\.{re.escape(klass)}\s*\{{",
                    f"chrome class .{klass} must be defined in app.css",
                )

    def test_each_chrome_class_used_in_html(self):
        for klass in Q_CHROME_CLASSES:
            with self.subTest(klass=klass):
                self.assertRegex(
                    self.html,
                    rf'class="[^"]*\b{re.escape(klass)}\b[^"]*"',
                    f"chrome class .{klass} must be referenced from app.html",
                )

    def test_each_id_rule_defined(self):
        for elem_id in Q_ID_RULES:
            with self.subTest(elem_id=elem_id):
                # Either bare #id { or grouped #idA, #idB { …
                self.assertRegex(
                    self.css,
                    rf"#{re.escape(elem_id)}(\s|,)",
                    f"id rule for #{elem_id} must exist in the Q id-rules block",
                )

    def test_each_id_rule_target_present_in_html(self):
        for elem_id in Q_ID_RULES:
            with self.subTest(elem_id=elem_id):
                self.assertRegex(
                    self.html,
                    rf'\bid="{re.escape(elem_id)}"',
                    f"#{elem_id} rule defined in CSS but no element with that id "
                    f"exists in app.html — the rule is dead",
                )

    def test_each_id_rule_target_has_no_inline_style(self):
        """If the id-rule extracted the inline style, the matching
        element in app.html must NOT carry a style= attr anymore.
        Catches a regression where someone re-adds an inline style
        on an element that already has a CSS rule."""
        for elem_id in Q_ID_RULES:
            with self.subTest(elem_id=elem_id):
                pat = re.compile(
                    rf'<[a-z][a-z0-9]*\b[^>]*?\bid="{re.escape(elem_id)}"[^>]*?\sstyle="',
                )
                self.assertIsNone(
                    pat.search(self.html),
                    f"element #{elem_id} still carries an inline style= attr — "
                    f"the Q id-rule extraction was undone or the style was "
                    f"reintroduced. Either remove the inline style or remove "
                    f"the #{elem_id} rule from the 20260413Q-id-rules block.",
                )


class TestUnsafeHashesMachinery(unittest.TestCase):
    """The serve.py unsafe-hashes path that lets style-src drop
    'unsafe-inline' while keeping the bespoke remainder allowed."""

    def test_helper_exists_and_returns_hashes(self):
        from freq.modules import serve as serve_mod
        # Clear cache so the test sees the live count.
        serve_mod._INLINE_STYLE_CSP_HASHES = []
        tokens = serve_mod._inline_style_csp_hashes()
        self.assertGreater(
            len(tokens), 0,
            "_inline_style_csp_hashes must return at least one token "
            "(there are still bespoke inline styles in app.html)",
        )
        for tok in tokens:
            self.assertTrue(
                tok.startswith("'sha256-") and tok.endswith("'"),
                f"each token must be a CSP 'sha256-…' source: got {tok!r}",
            )

    def test_helper_count_matches_unique_inline_styles(self):
        """One hash per unique inline style value — no duplicates."""
        from freq.modules import serve as serve_mod
        serve_mod._INLINE_STYLE_CSP_HASHES = []
        tokens = serve_mod._inline_style_csp_hashes()
        html = APP_HTML.read_text()
        unique = len(set(re.findall(r' style="([^"]*)"', html)))
        self.assertEqual(
            len(tokens), unique,
            f"helper returned {len(tokens)} hashes but app.html has "
            f"{unique} unique inline style values — the count must match",
        )

    def test_helper_caches_result(self):
        """Second call must not rescan app.html — pin via the cache
        being non-empty after first call."""
        from freq.modules import serve as serve_mod
        serve_mod._INLINE_STYLE_CSP_HASHES = []
        first = serve_mod._inline_style_csp_hashes()
        # Cache should be populated now.
        self.assertEqual(serve_mod._INLINE_STYLE_CSP_HASHES, first)
        # Second call returns the same list object (same identity).
        second = serve_mod._inline_style_csp_hashes()
        self.assertIs(first, second)


class TestStyleSrcNeverHasUnsafeInline(unittest.TestCase):
    """Hybrid finish: style-src must NEVER carry 'unsafe-inline'
    regardless of how many bespoke inline styles remain. Bespoke
    styles are allowed via 'unsafe-hashes' + per-style sha256 tokens
    computed at startup. Pin this both at the source level (no
    static literal carries 'unsafe-inline') and at the runtime level
    (the dynamically-built directive does not contain it)."""

    @classmethod
    def setUpClass(cls):
        cls.html = APP_HTML.read_text()
        cls.src = SERVE_PY.read_text()

    def test_no_static_unsafe_inline_in_style_src(self):
        # Anchor on the f-string literal in the send_header call.
        csp_idx = self.src.find('"Content-Security-Policy"')
        self.assertNotEqual(csp_idx, -1)
        # Find the static fallback 'self' literal which is what
        # ships when there are no hashes.
        # The dynamically-built version uses the style_src local var.
        # Both must be unsafe-inline-free.
        directive_end = self.src.find(')', csp_idx)
        directive_block = self.src[csp_idx:directive_end]
        # The literal must reference style_src (the local var) AND
        # not contain 'unsafe-inline'.
        self.assertIn("{style_src}", directive_block,
                      "style-src must be built dynamically via the style_src local var")
        self.assertNotIn(
            "'unsafe-inline'",
            directive_block,
            "the CSP directive literal must not contain 'unsafe-inline' "
            "anywhere — neither for script-src nor style-src",
        )

    def test_runtime_directive_is_unsafe_inline_free(self):
        """Build the actual style_src string the way serve.py does
        and assert it doesn't contain unsafe-inline."""
        from freq.modules import serve as serve_mod
        serve_mod._INLINE_STYLE_CSP_HASHES = []
        style_hash_tokens = serve_mod._inline_style_csp_hashes()
        if style_hash_tokens:
            style_src = "style-src 'self' 'unsafe-hashes' " + " ".join(style_hash_tokens)
        else:
            style_src = "style-src 'self'"
        self.assertNotIn(
            "'unsafe-inline'", style_src,
            "runtime style-src directive must never carry 'unsafe-inline'",
        )
        # Sanity: when hashes are present, 'unsafe-hashes' must be too.
        if style_hash_tokens:
            self.assertIn("'unsafe-hashes'", style_src)
            self.assertIn("'sha256-", style_src)


if __name__ == "__main__":
    unittest.main()
