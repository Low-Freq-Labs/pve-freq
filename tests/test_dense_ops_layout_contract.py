"""Dense operations layout contract tests.

Proves the dashboard shell uses DC01 dense-ops density targets rather
than generic landing-page spacing. Pins a lower bound on how much
vertical/horizontal chrome the primary surfaces can eat before the
layout starts drifting back toward a marketing dashboard.

Targets taken from the task spec:
- top-of-screen summary blocks read as dense
- widget/card padding holds at a tight operational baseline
- sections don't leave huge gaps between blocks
- body line-height stays tight for desktop dense reading

These assertions deliberately bound MAXIMUMS, not exact values, so
future density tweaks under the ceiling pass without edits.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css():
    with open(os.path.join(REPO_ROOT, "freq/data/web/css/app.css")) as f:
        return f.read()


def _extract_first_rule(css: str, selector: str) -> str:
    """Return the body of the first rule whose LEADING selector matches
    exactly. Anchors at start-of-line so `.st` does not accidentally
    catch the `.stats .st` compound rule."""
    pattern = re.compile(
        rf"(?:^|\n)\s*{re.escape(selector)}\s*\{{", re.MULTILINE
    )
    m = pattern.search(css)
    if not m:
        raise AssertionError(f"CSS rule not found: {selector}")
    brace = css.find("{", m.start())
    end = css.find("}", brace)
    return css[brace + 1: end]


def _px(rule: str, prop: str) -> list:
    """Return all pixel values declared for `prop` in the rule body."""
    m = re.search(rf"{re.escape(prop)}\s*:\s*([^;]+);", rule)
    if not m:
        return []
    return [int(x) for x in re.findall(r"(\d+)px", m.group(1))]


class TestPrimaryLayoutDensity(unittest.TestCase):
    """The main shell surfaces — header and body container — must stay
    dense enough for desktop ops use."""

    def test_mn_header_padding_tight(self):
        """.mn-header padding must be tight: y<=8px, x<=28px. Generic
        dashboard shells often leave 10-16px y and 32-48px x which
        costs a full row of information density above the fold."""
        rule = _extract_first_rule(_css(), ".mn-header")
        px = _px(rule, "padding")
        self.assertTrue(px, ".mn-header must declare padding")
        self.assertLessEqual(px[0], 8, f".mn-header vertical padding must be <=8px (got {px[0]}px)")
        if len(px) > 1:
            self.assertLessEqual(px[1], 28, f".mn-header horizontal padding must be <=28px (got {px[1]}px)")

    def test_mn_body_padding_tight(self):
        """.mn-body padding must be tight: y<=16px, x<=32px."""
        rule = _extract_first_rule(_css(), ".mn-body")
        px = _px(rule, "padding")
        self.assertTrue(px, ".mn-body must declare padding")
        self.assertLessEqual(px[0], 16, f".mn-body vertical padding must be <=16px (got {px[0]}px)")
        if len(px) > 1:
            self.assertLessEqual(px[1], 32, f".mn-body horizontal padding must be <=32px (got {px[1]}px)")

    def test_body_line_height_dense(self):
        """body line-height must be <=1.55 — dense desktop reading, not
        1.65+ prose-style spacing. There can be multiple `body { }` rules
        in app.css (e.g. a FOUC-prevention rule and the main typography
        rule). Scan all of them and assert the main rule declares a
        tight line-height."""
        css = _css()
        # Find all body { ... } blocks
        found = False
        for m in re.finditer(r"(?:^|\n)body\s*\{([^}]*)\}", css):
            body_rule = m.group(1)
            lh = re.search(r"line-height\s*:\s*([\d.]+)", body_rule)
            if lh:
                found = True
                self.assertLessEqual(float(lh.group(1)), 1.55,
                                      f"body line-height must be <=1.55 (got {lh.group(1)})")
        self.assertTrue(found,
                         "at least one body rule must declare line-height")


class TestTopOfScreenStatsDensity(unittest.TestCase):
    """.stats and .st (stat tiles above the fold) must read as dense."""

    def test_stats_margin_bottom_small(self):
        """Stats row must not dump >12px whitespace before the next
        section — dense ops dashboards lean on proximity."""
        rule = _extract_first_rule(_css(), ".stats")
        m = re.search(r"margin-bottom\s*:\s*([^;]+);", rule)
        self.assertIsNotNone(m, ".stats must declare margin-bottom")
        val = m.group(1).strip()
        # Allow either px value or a small CSS variable (gap-xs or gap-sm)
        if val.endswith("px"):
            self.assertLessEqual(int(val.replace("px", "")), 12,
                                  f".stats margin-bottom must be <=12px (got {val})")
        else:
            self.assertTrue(
                "gap-xs" in val or "gap-sm" in val,
                f".stats margin-bottom must use gap-xs/gap-sm (got {val})"
            )

    def test_stat_tile_padding_tight(self):
        """.st (stat tile) padding must be tight: y<=6px, x<=12px."""
        rule = _extract_first_rule(_css(), ".st")
        px = _px(rule, "padding")
        self.assertTrue(px, ".st must declare padding")
        self.assertLessEqual(px[0], 6, f".st vertical padding must be <=6px (got {px[0]}px)")
        if len(px) > 1:
            self.assertLessEqual(px[1], 12, f".st horizontal padding must be <=12px (got {px[1]}px)")


class TestSectionDensity(unittest.TestCase):
    """Collapsible sections must not stack up giant vertical gaps."""

    def test_section_margin_bottom_tight(self):
        """Sections must stack with <=16px gap, not 28px."""
        rule = _extract_first_rule(_css(), ".section")
        m = re.search(r"margin-bottom\s*:\s*([^;]+);", rule)
        self.assertIsNotNone(m, ".section must declare margin-bottom")
        val = m.group(1).strip()
        if val.endswith("px"):
            self.assertLessEqual(int(val.replace("px", "")), 16,
                                  f".section margin-bottom must be <=16px (got {val})")

    def test_section_header_padding_tight(self):
        """Section header must not pad >8px vertical, >16px horizontal."""
        rule = _extract_first_rule(_css(), ".section-header")
        px = _px(rule, "padding")
        self.assertTrue(px, ".section-header must declare padding")
        self.assertLessEqual(px[0], 8, f".section-header vertical padding must be <=8px (got {px[0]}px)")
        if len(px) > 1:
            self.assertLessEqual(px[1], 16, f".section-header horizontal padding must be <=16px (got {px[1]}px)")


class TestCardDensity(unittest.TestCase):
    """.crd, .host-card, .infra-role-card must stay dense."""

    def test_crd_padding_tight(self):
        rule = _extract_first_rule(_css(), ".crd")
        px = _px(rule, "padding")
        self.assertTrue(px, ".crd must declare padding")
        self.assertLessEqual(px[0], 10, f".crd vertical padding must be <=10px (got {px[0]}px)")

    def test_host_card_padding_tight(self):
        rule = _extract_first_rule(_css(), ".host-card")
        px = _px(rule, "padding")
        self.assertTrue(px, ".host-card must declare padding")
        self.assertLessEqual(px[0], 8, f".host-card vertical padding must be <=8px (got {px[0]}px)")

    def test_infra_role_card_padding_tight(self):
        rule = _extract_first_rule(_css(), ".infra-role-card")
        px = _px(rule, "padding")
        self.assertTrue(px, ".infra-role-card must declare padding")
        self.assertLessEqual(px[0], 12, f".infra-role-card vertical padding must be <=12px (got {px[0]}px)")


class TestSubTabsDensity(unittest.TestCase):
    """Sub-tab navigation must sit tight against the section below."""

    def test_sub_tabs_margin_bottom_tight(self):
        rule = _extract_first_rule(_css(), ".sub-tabs")
        m = re.search(r"margin-bottom\s*:\s*([^;]+);", rule)
        self.assertIsNotNone(m, ".sub-tabs must declare margin-bottom")
        val = m.group(1).strip()
        if val.endswith("px"):
            self.assertLessEqual(int(val.replace("px", "")), 10,
                                  f".sub-tabs margin-bottom must be <=10px (got {val})")
        else:
            self.assertTrue(
                "gap-xs" in val or "gap-sm" in val,
                f".sub-tabs margin-bottom must use gap-xs/gap-sm (got {val})"
            )


if __name__ == "__main__":
    unittest.main()
