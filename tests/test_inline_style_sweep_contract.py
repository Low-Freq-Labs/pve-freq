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


class TestStyleSrcMatchesInlineStyleCount(unittest.TestCase):
    """If the live inline style count is zero, the CSP header MUST
    drop 'unsafe-inline' from style-src. If non-zero, it MUST keep
    it. Pin both halves so the directive can never drift from the
    count."""

    @classmethod
    def setUpClass(cls):
        cls.html = APP_HTML.read_text()
        cls.src = SERVE_PY.read_text()

    def _style_src_directive(self) -> str:
        # Anchor on the actual send_header CSP literal, not free-form
        # comment text mentioning 'style-src'.
        csp_idx = self.src.find('"Content-Security-Policy"')
        self.assertNotEqual(csp_idx, -1)
        directive_end = self.src.find(')', csp_idx)
        directive_block = self.src[csp_idx:directive_end]
        ss_idx = directive_block.find("style-src ")
        self.assertNotEqual(ss_idx, -1)
        ss_end = directive_block.find(";", ss_idx)
        return directive_block[ss_idx:ss_end]

    def test_directive_matches_count(self):
        count = len(re.findall(r' style="', self.html))
        directive = self._style_src_directive()
        if count == 0:
            self.assertNotIn(
                "'unsafe-inline'", directive,
                f"app.html has 0 inline style attrs — style-src MUST NOT "
                f"carry 'unsafe-inline' (currently: {directive!r})",
            )
        else:
            self.assertIn(
                "'unsafe-inline'", directive,
                f"app.html has {count} inline style attrs — style-src MUST "
                f"keep 'unsafe-inline' until they are extracted "
                f"(currently: {directive!r})",
            )


if __name__ == "__main__":
    unittest.main()
