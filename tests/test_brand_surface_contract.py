"""Brand surface contract tests.

Proves /api/info and the shell render context-aware brand surfaces —
cluster, mode, fleet size — instead of generic "PVE FREQ Dashboard"
app chrome. Operators logged into DC01 should see "DC01" in the
login/header/home surfaces, not the product name.

Strategy:
- handle_info must build dashboard_header and subtitle from cfg truth
  when no personality pack overrides them
- Default header must NOT fall through to the generic "PVE FREQ
  Dashboard" string — it must be either brand + cluster or brand +
  'operator console'
- Default subtitle must be a factual host/node count, not the brand
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fleet_src():
    with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
        return f.read()


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


class TestHandleInfoContextAware(unittest.TestCase):
    """handle_info must build context-aware defaults."""

    def _fn(self):
        src = _fleet_src()
        return src.split("def handle_info")[1].split("\ndef ")[0]

    def test_no_hardcoded_pve_freq_dashboard_fallback(self):
        """handle_info must NOT fall through to 'PVE FREQ Dashboard'
        as the ultimate default — that's app chrome, not ops truth."""
        fn = self._fn()
        # The generic string can only appear as a comparison against
        # a personality pack override (to reject it), not as a value
        # assignment. Count occurrences and assert it's only used to
        # reject, not to default.
        occurrences = fn.count('"PVE FREQ Dashboard"')
        # Allow up to 1 occurrence: the "reject this generic pack
        # override" check. More than that means it's leaking as a
        # default.
        self.assertLessEqual(occurrences, 1,
                              "PVE FREQ Dashboard must not be a default — only a rejected generic pack value")

    def test_default_header_uses_cluster_when_present(self):
        """The default header must carry cluster_name when set."""
        fn = self._fn()
        self.assertIn("cfg.brand", fn,
                       "Default header must include cfg.brand")
        self.assertIn("cluster", fn.lower(),
                       "Default header logic must reference cluster")
        # When cluster is set, header must be brand + cluster
        self.assertIn("f\"{cfg.brand}", fn,
                       "Default header must be an f-string starting with cfg.brand")

    def test_default_header_falls_back_to_operator_console(self):
        """When cluster_name is empty, header falls back to
        'operator console' — never 'Dashboard'."""
        fn = self._fn()
        self.assertIn("operator console", fn,
                       "Default header fallback must be 'operator console'")

    def test_default_subtitle_is_factual_count(self):
        """Default subtitle must be a factual host/pve-node count."""
        fn = self._fn()
        self.assertIn("hosts", fn)
        self.assertIn("pve nodes", fn,
                       "Default subtitle must report 'pve nodes' count")

    def test_pack_override_still_honored_when_non_generic(self):
        """Personality packs can still override header/subtitle, but
        only when the override is non-empty and non-generic."""
        fn = self._fn()
        self.assertIn("pack_header", fn,
                       "handle_info must check pack header override")
        self.assertIn("pack_subtitle", fn,
                       "handle_info must check pack subtitle override")
        # The reject condition for generic pack values
        self.assertIn('pack_header != "PVE FREQ Dashboard"', fn,
                       "Must reject generic 'PVE FREQ Dashboard' pack value")


class TestFrontendConsumesContextHeader(unittest.TestCase):
    """The loadHome frontend handler must surface the cluster-aware
    dashboard_header instead of hardcoding a generic title."""

    def test_no_hardcoded_dashboard_suffix(self):
        """document.title must not force '... Dashboard' suffix."""
        src = _js()
        self.assertNotIn("'+'+'Dashboard'", src)
        self.assertNotIn("+' Dashboard'", src,
                          "document.title must not hardcode ' Dashboard' suffix")

    def test_document_title_uses_dashboard_header(self):
        src = _js()
        # loadHome must pull dashboard_header from the info response
        idx = src.find("function loadHome")
        self.assertGreater(idx, 0)
        block = src[idx: idx + 2000]
        self.assertIn("d.dashboard_header", block,
                       "loadHome must consume d.dashboard_header from /api/info")

    def test_nav_version_carries_cluster_context(self):
        """The #nav-ver pill next to the wordmark must carry cluster
        context from dashboard_header, not just the version string."""
        src = _js()
        idx = src.find("function loadHome")
        block = src[idx: idx + 2000]
        # Must reference dashboard_header in nav-ver rendering
        self.assertIn("nav-ver", block)
        # Must do something with dashboard_header alongside the version
        self.assertIn("d.dashboard_header", block)


if __name__ == "__main__":
    unittest.main()
