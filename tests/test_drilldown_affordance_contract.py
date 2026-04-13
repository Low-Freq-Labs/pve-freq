"""Drilldown affordance contract tests.

Proves that clickable fleet cards — host-card and infra-role-card —
expose a visible drilldown affordance to operators. Datadog/Grafana
fleet surfaces make drilldown targets obvious via hover chevrons or
explicit "view detail" icons; FREQ previously relied only on a JS
onclick handler with no visual hint that a tile was navigable.

Baseline rules enforced here:
1. Any host-card wired for drilldown (onclick, data-action, or
   cursor-ptr class) must get cursor:pointer from CSS, not ad-hoc
   inline style.
2. Drillable host-cards must expose a ::after chevron hint.
3. infra-role-card is always clickable and must also expose a
   ::after chevron hint.
4. Chevron hint is subtle (only visible on hover, no layout shift).
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css():
    with open(os.path.join(REPO_ROOT, "freq/data/web/css/app.css")) as f:
        return f.read()


class TestHostCardDrilldownAffordance(unittest.TestCase):
    """Clickable host cards need a visible drilldown hint."""

    def test_clickable_host_card_has_pointer_cursor(self):
        """host-card[onclick], host-card.cursor-ptr, host-card[data-action]
        must all get cursor:pointer from CSS."""
        css = _css()
        # Must reference all three selectors together and set cursor
        self.assertIn(".host-card[onclick]", css,
                       "CSS must target host-card[onclick] for drilldown")
        self.assertIn(".host-card.cursor-ptr", css,
                       "CSS must target host-card.cursor-ptr for drilldown")
        self.assertIn(".host-card[data-action]", css,
                       "CSS must target host-card[data-action] for drilldown")
        # The combined selector must declare cursor: pointer
        m = re.search(
            r"\.host-card\[onclick\],\s*\n?\s*\.host-card\.cursor-ptr,\s*\n?\s*"
            r"\.host-card\[data-action\]\s*\{[^}]*cursor\s*:\s*pointer",
            css,
            re.MULTILINE,
        )
        self.assertIsNotNone(m, "Drillable host-card must declare cursor:pointer")

    def test_clickable_host_card_has_chevron_hint(self):
        """Drillable host-card must expose a ::after chevron hint."""
        css = _css()
        # Look for ::after on drillable host-card with the chevron glyph
        m = re.search(
            r"\.host-card\[onclick\]::after[^{]*\{[^}]*content",
            css,
        )
        self.assertIsNotNone(m,
                              "host-card[onclick]::after must declare chevron content")
        # The chevron glyph is a right-angle (›) — \203A in CSS escape
        self.assertIn(r"\203A", css,
                       "Drilldown hint must use › (\\203A) chevron glyph")

    def test_chevron_hint_hidden_by_default(self):
        """Chevron must be opacity:0 by default, revealed on hover."""
        css = _css()
        # Find the ::after rule for host-card[onclick] and confirm opacity:0
        idx = css.find(".host-card[onclick]::after")
        self.assertGreater(idx, 0)
        rule = css[idx: css.find("}", idx)]
        self.assertIn("opacity: 0", rule,
                       "Chevron hint must start at opacity:0")

    def test_chevron_hint_revealed_on_hover(self):
        """On hover, chevron must animate in (opacity > 0)."""
        css = _css()
        idx = css.find(".host-card[onclick]:hover::after")
        self.assertGreater(idx, 0,
                            "CSS must declare :hover::after rule for drilldown chevron")
        rule = css[idx: css.find("}", idx)]
        self.assertIn("opacity", rule,
                       ":hover::after must set opacity > 0")

    def test_chevron_does_not_intercept_clicks(self):
        """pointer-events:none — the chevron is a hint, not a click target."""
        css = _css()
        idx = css.find(".host-card[onclick]::after")
        rule = css[idx: css.find("}", idx)]
        self.assertIn("pointer-events: none", rule,
                       "Chevron hint must not intercept clicks")


class TestInfraRoleCardDrilldownAffordance(unittest.TestCase):
    """infra-role-card is always clickable — must also expose chevron."""

    def test_infra_role_card_has_chevron_after(self):
        css = _css()
        self.assertIn(".infra-role-card::after", css,
                       "infra-role-card must declare ::after chevron hint")
        idx = css.find(".infra-role-card::after")
        rule = css[idx: css.find("}", idx)]
        self.assertIn("content", rule, "::after must declare content")
        self.assertIn("opacity: 0", rule,
                       "::after must start hidden")

    def test_infra_role_card_chevron_revealed_on_hover(self):
        css = _css()
        self.assertIn(".infra-role-card:hover::after", css,
                       "infra-role-card:hover::after must exist")

    def test_infra_role_card_retains_cursor_pointer(self):
        """infra-role-card base rule must still declare cursor:pointer."""
        css = _css()
        idx = css.find(".infra-role-card {")
        self.assertGreater(idx, 0, ".infra-role-card rule must exist")
        rule = css[idx: css.find("}", idx)]
        self.assertIn("cursor: pointer", rule,
                       ".infra-role-card must keep cursor:pointer")


class TestAffordanceLanguageConsistency(unittest.TestCase):
    """host-card and infra-role-card must use the same chevron glyph so
    operators learn one affordance and apply it everywhere."""

    def test_same_chevron_glyph_in_both(self):
        css = _css()
        # Both ::after rules must use the same \203A glyph
        host_idx = css.find(".host-card[onclick]::after")
        role_idx = css.find(".infra-role-card::after")
        host_rule = css[host_idx: css.find("}", host_idx)]
        role_rule = css[role_idx: css.find("}", role_idx)]
        self.assertIn(r"\203A", host_rule,
                       "host-card chevron must use \\203A")
        self.assertIn(r"\203A", role_rule,
                       "infra-role-card chevron must use \\203A")


if __name__ == "__main__":
    unittest.main()
