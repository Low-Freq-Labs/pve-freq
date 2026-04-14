"""M-UI-SUBNAV-STATE-CONTRACT-20260413AF — sub-tab symmetry contract.

Sonny observed that after clicking some sub-nav paths, half the nav
'disappeared' until he backed out to another sub-nav and re-entered.
The Playwright repro found sec-compliance-view rendered only 5 of the
8 security sub-tabs — Firewall, Certs, VPN were literally missing
from that view's `<div class="sub-tabs">` block, making them
unreachable from the Compliance page. Every other security view had
all 8 buttons.

This is a content-parity bug, not a dynamic state bug. Each sub-view
in the fleet/security/system clusters embeds its OWN copy of the
cluster's sub-tab row (with the active highlight pre-set on the
matching view). When one copy drifts out of sync, an operator who
navigates INTO the short copy gets stuck with a truncated nav row
until they navigate back OUT.

This contract enforces that every sub-view belonging to a cluster
embeds a sub-tab row containing buttons for every sibling in that
cluster. Any future edit that forgets to add a new sub-nav button
to EVERY cluster view breaks the contract loudly instead of being
discovered by a user.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _html():
    with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
        return f.read()


# Cluster definition: the canonical set of sub-views for each top-nav
# cluster. Every sub-view in a cluster must embed a sub-tab row that
# links to every sibling in this list (plus itself as active-sub).
CLUSTERS = {
    "fleet": ["fleet", "topology", "capacity", "network"],
    "security": [
        "security", "sec-hardening", "sec-access", "sec-vault",
        "sec-compliance", "firewall", "certs", "vpn",
    ],
    "tools": [
        "tools", "playbooks", "gitops", "chaos", "dns", "dr",
        "incidents", "metrics", "automation", "plugins",
    ],
}


def _extract_view_block(html: str, view: str) -> str:
    """Extract the inner HTML of the <div id='<view>-view'> ... </div>
    element. Uses a balanced-depth scan to find the matching close tag."""
    marker = f'id="{view}-view"'
    idx = html.index(marker)
    # walk back to the opening <div
    start = html.rfind("<div", 0, idx)
    # walk forward to find the matching </div>
    depth = 0
    pos = start
    while pos < len(html):
        nxt_open = html.find("<div", pos + 1)
        nxt_close = html.find("</div>", pos + 1)
        if nxt_close == -1:
            break
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            pos = nxt_open
        else:
            if depth == 0:
                return html[start: nxt_close + len("</div>")]
            depth -= 1
            pos = nxt_close
    raise AssertionError(f"could not locate closing </div> for {view}-view")


def _sub_tab_row(block: str) -> str:
    """Return the inner contents of the first <div class='sub-tabs'>
    inside the view block, or '' if none."""
    m = re.search(r'<div[^>]*class="sub-tabs"[^>]*>(.*?)</div>', block, re.DOTALL)
    return m.group(1) if m else ""


def _sub_tab_views(row: str) -> set:
    """Extract the set of data-view values on `.sub-tab` buttons in a row."""
    return set(re.findall(r'class="sub-tab[^"]*"\s+data-view="([^"]+)"', row))


class TestClusterSubTabSymmetry(unittest.TestCase):
    """Every sub-view in a cluster must embed a sub-tab row that
    references every sibling in that cluster."""

    def setUp(self):
        self.html = _html()

    def _assert_cluster_view_covers_all(self, cluster: str, view: str, siblings: list):
        block = _extract_view_block(self.html, view)
        row = _sub_tab_row(block)
        self.assertTrue(
            row,
            f"{view}-view must embed a <div class='sub-tabs'> row",
        )
        views_in_row = _sub_tab_views(row)
        missing = set(siblings) - views_in_row
        self.assertFalse(
            missing,
            f"{view}-view sub-tab row is missing siblings from the "
            f"{cluster!r} cluster: {sorted(missing)!r}. This is the "
            f"'half the nav disappears' bug — an operator on {view} "
            f"cannot reach those siblings without navigating away.",
        )

    def test_fleet_cluster_all_views_cover_all_tabs(self):
        siblings = CLUSTERS["fleet"]
        for v in siblings:
            with self.subTest(view=v):
                self._assert_cluster_view_covers_all("fleet", v, siblings)

    def test_security_cluster_all_views_cover_all_tabs(self):
        """Regression test for the sec-compliance defect — that view
        shipped with only 5 of 8 security sub-tabs, hiding firewall/
        certs/vpn when the operator landed on it."""
        siblings = CLUSTERS["security"]
        for v in siblings:
            with self.subTest(view=v):
                self._assert_cluster_view_covers_all("security", v, siblings)

    def test_system_cluster_all_views_cover_all_tabs(self):
        siblings = CLUSTERS["tools"]
        for v in siblings:
            with self.subTest(view=v):
                self._assert_cluster_view_covers_all("tools", v, siblings)


class TestClusterSubTabActiveHighlight(unittest.TestCase):
    """Each cluster view must mark its own sub-tab button with
    active-sub — not a sibling. Otherwise the highlight lies about
    which view the operator is on."""

    def setUp(self):
        self.html = _html()

    def _assert_self_is_active(self, cluster: str, view: str):
        block = _extract_view_block(self.html, view)
        row = _sub_tab_row(block)
        # Look for `class="sub-tab active-sub[ extra classes]" data-view="<view>"`.
        # Some views carry extra classes (e.g. chaos uses `c-red` tint)
        # so the regex must allow trailing tokens inside the class attr.
        m = re.search(
            r'class="sub-tab active-sub(?:\s+[\w-]+)*"\s+data-view="' + re.escape(view) + '"',
            row,
        )
        self.assertIsNotNone(
            m,
            f"{view}-view sub-tab row must mark its OWN button with "
            f"the active-sub class so the highlight matches the page",
        )

    def test_fleet_active_highlight(self):
        for v in CLUSTERS["fleet"]:
            with self.subTest(view=v):
                self._assert_self_is_active("fleet", v)

    def test_security_active_highlight(self):
        for v in CLUSTERS["security"]:
            with self.subTest(view=v):
                self._assert_self_is_active("security", v)

    def test_system_active_highlight(self):
        for v in CLUSTERS["tools"]:
            with self.subTest(view=v):
                self._assert_self_is_active("tools", v)


class TestNoOrphanSubTabButtonViews(unittest.TestCase):
    """Every data-view target referenced from a sub-tab row must
    correspond to an actual <div id='<view>-view'> in app.html. An
    orphan button would click into nothing, dropping the operator
    onto an empty page — another form of 'disappearing nav'."""

    def setUp(self):
        self.html = _html()

    def test_every_sub_tab_target_has_a_view_element(self):
        referenced = set()
        for m in re.finditer(r'class="sub-tab[^"]*"\s+data-view="([^"]+)"', self.html):
            referenced.add(m.group(1))
        missing = [v for v in referenced if f'id="{v}-view"' not in self.html]
        self.assertFalse(
            missing,
            f"sub-tab buttons reference views with no matching "
            f"<div id='<view>-view'> element: {sorted(missing)!r}",
        )


if __name__ == "__main__":
    unittest.main()
