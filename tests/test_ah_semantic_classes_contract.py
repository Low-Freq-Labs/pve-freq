"""M-UI-INLINE-STYLE-REGRESSION-POLISH-20260413AH contract.

Partner pass to Rick's Q strict CSP sweep. Locks down the 15 semantic
composition classes AH extracted from the inner composition of:

  - #terminal-overlay (term-shell-*)
  - #search-overlay (search-overlay-*)
  - #shortcuts-modal (shortcuts-*)
  - the SYSTEM → CHAOS destructive banner (destructive-banner)
  - the home view top toolbar (view-toolbar / view-toolbar-row)

These were chosen because each names a distinct UI surface rather than
a generic utility. Naming them semantically is a maintainability win
on top of the CSP win (each extraction drops one sha256 from the
unsafe-hashes CSP list that Rick's Q hybrid generates at serve
startup). Opposite of Rick's Q id-rules block, which moves bespoke
inline styles out of HTML attrs verbatim — necessary for the single-
use ones but not satisfying on its own.

Regression guard: every class defined here must be used in app.html,
and the pattern it replaced must NOT live in app.html anymore (so a
future edit can't quietly reintroduce the inline style).
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _html():
    with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
        return f.read()


def _css():
    with open(os.path.join(REPO_ROOT, "freq/data/web/css/app.css")) as f:
        return f.read()


AH_CLASSES = [
    # terminal shell inner composition
    "term-shell-col",
    "term-shell-title-row",
    "term-shell-btn-row",
    "term-shell-tag",
    "term-shell-close",
    # global search overlay inner composition
    "search-overlay-card",
    "search-overlay-input-row",
    "search-overlay-input",
    "search-overlay-footer",
    # shortcuts modal inner composition
    "shortcuts-card",
    "shortcuts-heading",
    "shortcuts-grid",
    # chaos destructive banner
    "destructive-banner",
    # home view toolbar
    "view-toolbar",
    "view-toolbar-row",
]


class TestAhSemanticClassesDefined(unittest.TestCase):
    """Every AH class must be defined in app.css and carry the
    20260413AH block marker nearby so the provenance is greppable."""

    def setUp(self):
        self.css = _css()

    def test_ah_block_marker_present(self):
        self.assertIn(
            "20260413AH SEMANTIC COMPOSITION CLASSES",
            self.css,
            "app.css must contain the 20260413AH block header comment",
        )
        self.assertIn(
            "20260413AH-semantic-block-end",
            self.css,
            "app.css must contain the 20260413AH block end marker",
        )

    def test_each_class_defined_in_ah_block(self):
        start = self.css.index("20260413AH SEMANTIC COMPOSITION CLASSES")
        end = self.css.index("20260413AH-semantic-block-end")
        block = self.css[start:end]
        for cls in AH_CLASSES:
            with self.subTest(cls=cls):
                self.assertRegex(
                    block,
                    rf"\.{re.escape(cls)}\s*\{{",
                    f"AH block must define .{cls}",
                )


class TestAhClassesUsedInHtml(unittest.TestCase):
    """Every AH class must be referenced in app.html. A class defined
    in CSS but not used in HTML means the extraction failed to update
    the consumer — silent bug."""

    def setUp(self):
        self.html = _html()

    def test_each_class_used_in_html(self):
        for cls in AH_CLASSES:
            with self.subTest(cls=cls):
                self.assertRegex(
                    self.html,
                    rf'class="[^"]*\b{re.escape(cls)}\b',
                    f"app.html must use .{cls} on at least one element",
                )


class TestAhInlineStylesRemoved(unittest.TestCase):
    """The pre-extraction inline style strings must NOT live in
    app.html anymore. These are verbatim fingerprints of the styles
    AH replaced — if any of them reappear, a regression slipped in."""

    def setUp(self):
        self.html = _html()

    FORBIDDEN_INLINE = [
        # term-shell-col
        'style="display:flex;flex-direction:column;height:100%;max-width:1400px;margin:0 auto"',
        # term-shell-tag
        'style="color:var(--green);font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;font-family:var(--font-ui)"',
        # term-shell-close
        'style="font-size:9px;padding:2px 8px;color:var(--red)"',
        # search-overlay-card
        'style="max-width:560px;margin:0 auto;background:var(--bg);border:1px solid var(--border);border-radius:12px;overflow:hidden"',
        # search-overlay-input-row
        'style="padding:12px 16px;border-bottom:1px solid var(--border)"',
        # search-overlay-input
        'style="width:100%;background:transparent;border:none;outline:none;color:var(--text);font-size:16px;font-family:var(--font-ui)"',
        # search-overlay-footer
        'style="padding:8px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);display:flex;gap:16px"',
        # shortcuts-card
        'style="max-width:400px;margin:0 auto;background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:24px"',
        # shortcuts-heading
        'style="margin:0 0 16px;color:var(--purple-light)"',
        # shortcuts-grid
        'style="display:grid;grid-template-columns:auto 1fr;gap:8px 16px;font-size:13px"',
        # destructive-banner
        'style="background:rgba(255,60,60,0.08);border:1px solid rgba(255,60,60,0.3);border-radius:6px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:var(--text-dim)"',
        # view-toolbar
        'style="border-bottom:1px solid var(--border);padding:6px 0;margin-bottom:12px"',
        # view-toolbar-row
        'style="display:flex;gap:4px;align-items:center;min-height:32px;flex-wrap:wrap"',
    ]

    def test_no_forbidden_inline_style_regressed(self):
        for forbidden in self.FORBIDDEN_INLINE:
            with self.subTest(forbidden=forbidden[:60] + "..."):
                self.assertNotIn(
                    forbidden,
                    self.html,
                    f"Inline style regressed — should be a class: {forbidden[:80]}...",
                )


class TestAhDoesNotBreakQInvariants(unittest.TestCase):
    """AH must not have removed anything from Rick's Q work. The
    chrome semantic classes Rick landed (.pve-freq-wordmark /
    .nav-ver-label / .nav-divider / .header-time-label) must still
    be present and applied."""

    def setUp(self):
        self.html = _html()
        self.css = _css()

    def test_q_chrome_classes_still_defined(self):
        for cls in ("pve-freq-wordmark", "nav-ver-label",
                    "nav-divider", "header-time-label"):
            with self.subTest(cls=cls):
                self.assertIn(
                    f".{cls}",
                    self.css,
                    f"Q chrome class .{cls} must still be defined",
                )

    def test_q_id_rules_block_still_present(self):
        self.assertIn("20260413Q-id-rules-begin", self.css)
        self.assertIn("20260413Q-id-rules-end", self.css)


if __name__ == "__main__":
    unittest.main()
