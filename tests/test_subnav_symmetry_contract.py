"""Sub-navigation symmetry contract.

Fleet has a two-item static strip. Security and System are generated from one
definition per group so a new sibling cannot disappear from one copied row.
Each view owns only a mount declaring its group and active view.
"""

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(os.path.join(REPO_ROOT, path)) as handle:
        return handle.read()


CLUSTERS = {
    "fleet": ["fleet", "network"],
    "security": [
        "security", "sec-hardening", "sec-access", "sec-compliance",
        "firewall", "certs", "vpn",
    ],
    "system": [
        "tools", "playbooks", "gitops", "chaos", "dns", "dr",
        "incidents", "metrics", "automation", "plugins",
    ],
}


def _extract_view_block(html: str, view: str) -> str:
    marker = f'id="{view}-view"'
    idx = html.index(marker)
    start = html.rfind("<div", 0, idx)
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
                return html[start:nxt_close + len("</div>")]
            depth -= 1
            pos = nxt_close
    raise AssertionError(f"could not locate closing </div> for {view}-view")


def _group_definition(js: str, group: str) -> str:
    match = re.search(rf"\n  {re.escape(group)}:\[(.*?)\n  \]", js, re.DOTALL)
    if not match:
        raise AssertionError(f"missing SUBNAV_GROUPS.{group} definition")
    return match.group(1)


def _group_views(js: str, group: str) -> list[str]:
    return re.findall(r"\{view:'([^']+)'", _group_definition(js, group))


class TestClusterSubTabSymmetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read("freq/data/web/app.html")
        cls.js = _read("freq/data/web/js/app.js")

    def test_fleet_static_rows_remain_complete_and_active(self):
        for view in CLUSTERS["fleet"]:
            block = _extract_view_block(self.html, view)
            for sibling in CLUSTERS["fleet"]:
                self.assertIn(f'data-view="{sibling}"', block)
            self.assertRegex(
                block,
                rf'class="sub-tab active-sub" data-view="{re.escape(view)}"',
            )

    def test_security_has_one_complete_canonical_definition(self):
        self.assertEqual(_group_views(self.js, "security"), CLUSTERS["security"])

    def test_system_has_one_complete_canonical_definition(self):
        self.assertEqual(_group_views(self.js, "system"), CLUSTERS["system"])

    def test_every_generated_view_declares_its_group_and_active_state(self):
        for group in ("security", "system"):
            for view in CLUSTERS[group]:
                with self.subTest(group=group, view=view):
                    block = _extract_view_block(self.html, view)
                    self.assertIn(f'data-subnav-group="{group}"', block)
                    self.assertIn(f'data-subnav-active="{view}"', block)

    def test_generated_mounts_do_not_copy_buttons(self):
        for group in ("security", "system"):
            for view in CLUSTERS[group]:
                block = _extract_view_block(self.html, view)
                match = re.search(
                    rf'<div class="sub-tabs"[^>]*data-subnav-group="{group}"[^>]*>(.*?)</div>',
                    block,
                    re.DOTALL,
                )
                self.assertIsNotNone(match, f"missing generated subnav mount for {view}")
                self.assertNotIn("<button", match.group(1))

    def test_renderer_preserves_active_state_and_chaos_accent(self):
        self.assertIn("item.view===active?' active-sub':''", self.js)
        self.assertIn("{view:'chaos',label:'Chaos',className:'c-red'}", self.js)
        self.assertIn("button.dataset.view=item.view", self.js)

    def test_every_canonical_target_has_a_view_element(self):
        referenced = set(CLUSTERS["fleet"])
        referenced.update(_group_views(self.js, "security"))
        referenced.update(_group_views(self.js, "system"))
        missing = [view for view in referenced if f'id="{view}-view"' not in self.html]
        self.assertFalse(missing, f"subnav targets have no matching view: {sorted(missing)!r}")


if __name__ == "__main__":
    unittest.main()
