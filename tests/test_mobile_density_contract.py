"""Mobile-density contract.

A chromium sweep at 390x844 (iPhone 14 CSS pixels) landed the
following invariants after M-UI-CHROMIUM-POLISH-20260413AE:

1. `.sub-tabs` wraps to a second row instead of pushing the document
   width past the viewport. The security cluster has 8 sub-tabs
   (Overview/Hardening/Access/Vault/Compliance/Firewall/Certs/VPN =
   ~711px of nav row at desktop spacing) and the system cluster has
   9 (~876px). Without flex-wrap:wrap both clusters force horizontal
   scroll on every mobile page load.

2. The /api/ct/list fetch in loadLxcContainers passes {silent:true}
   so a 503 (LXC not installed) hides the section instead of flashing
   a red 'API error: ct/list (503)' toast on every fleet load.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css():
    with open(os.path.join(REPO_ROOT, "freq/data/web/css/app.css")) as f:
        return f.read()


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


class TestSubTabsWrapOnNarrowViewports(unittest.TestCase):
    def test_sub_tabs_block_has_flex_wrap_wrap(self):
        css = _css()
        idx = css.index(".sub-tabs {")
        block = css[idx: css.index("}", idx)]
        self.assertIn(
            "flex-wrap: wrap",
            block,
            ".sub-tabs must set flex-wrap:wrap so the security cluster "
            "(8 sub-tabs) and system cluster (9 sub-tabs) don't force "
            "horizontal scroll on mobile viewports",
        )

    def test_sub_tabs_still_use_flex(self):
        """Guard against anyone 'fixing' the wrap by switching to
        inline-block + overflow:auto, which would hide overflow tabs
        behind a scroll affordance instead of keeping them visible."""
        css = _css()
        idx = css.index(".sub-tabs {")
        block = css[idx: css.index("}", idx)]
        self.assertIn("display: flex", block)


class TestCtListFetchIsSilent(unittest.TestCase):
    """loadLxcContainers hides the section entirely when LXC isn't
    installed. The generic _authFetch toast would fire once per fleet
    load with 'API error: ct/list (503)', which reads as a real defect
    instead of the graceful not-installed signal it is."""

    def test_ct_list_uses_silent(self):
        src = _js()
        idx = src.index("function loadLxcContainers")
        body = src[idx: src.index("\nfunction ", idx)]
        self.assertIn(
            "_authFetch(API.CT_LIST,{silent:true}",
            body,
            "loadLxcContainers must fetch CT_LIST with {silent:true}",
        )

    def test_ct_list_handles_non_ok_gracefully(self):
        src = _js()
        idx = src.index("function loadLxcContainers")
        body = src[idx: src.index("\nfunction ", idx)]
        self.assertIn(
            "if(!r.ok)",
            body,
            "loadLxcContainers must check !r.ok and hide the section "
            "instead of blindly parsing d.containers on an error body",
        )
        self.assertIn(
            "section.style.display='none'",
            body,
            "loadLxcContainers must hide fleet-sec-ct on non-ok",
        )


if __name__ == "__main__":
    unittest.main()
