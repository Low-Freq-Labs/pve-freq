"""M-UI-LIVE-POLISH-20260413AG — live chromium polish contract.

Locks down the fixes from the live 8888 polish pass:

1. loadSecurityOverview must fill the Policies section (previously
   loadRisk+loadSecPosture only; the 'Policies' section header sat
   above an empty body on every security overview load).

2. loadGitops must render an inline placeholder in the COMMIT HISTORY
   panel when gitops isn't configured. Previously it set
   log.innerHTML='' leaving the COMMIT HISTORY section header over
   dead space.

3. Fleet CORE SYSTEMS and PVE node cards must use responsive
   auto-fill grids instead of fixed repeat(N,1fr) column counts, so
   host-card / infra-role-card children don't clip below their
   intrinsic width on a 390px mobile viewport.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


def _function_body(src: str, name: str) -> str:
    idx = src.index(f"function {name}(")
    rest = src[idx:]
    m = re.search(r"\n(?:function |var [A-Za-z_]+=function)", rest[1:])
    if m is None:
        return rest
    return rest[: m.start() + 1]


class TestSecurityOverviewFillsPolicies(unittest.TestCase):
    """Policies section is in app.html at every security overview load.
    loadSecurityOverview must fill it; otherwise the section header
    sits above an empty body."""

    def test_load_security_overview_calls_load_policies(self):
        body = _function_body(_js(), "loadSecurityOverview")
        self.assertIn(
            "loadPolicies()",
            body,
            "loadSecurityOverview must call loadPolicies() so the "
            "Policies section body is populated on every security "
            "overview load",
        )

    def test_load_security_overview_still_calls_risk_and_posture(self):
        """Regression guard: don't lose the existing loaders while
        adding loadPolicies()."""
        body = _function_body(_js(), "loadSecurityOverview")
        self.assertIn("loadRisk()", body)
        self.assertIn("loadSecPosture()", body)


class TestGitopsCommitHistoryPlaceholder(unittest.TestCase):
    """When gitops is not configured, the commit history log panel
    must render an inline placeholder instead of being wiped to
    empty. Otherwise the COMMIT HISTORY header sits above dead space."""

    def test_not_enabled_branch_renders_log_placeholder(self):
        body = _function_body(_js(), "loadGitops")
        # Grab the not-enabled branch specifically
        idx = body.index("!d.enabled")
        branch = body[idx: idx + 800]
        self.assertNotIn(
            "log.innerHTML=''",
            branch,
            "loadGitops not-enabled branch must not wipe log.innerHTML "
            "to empty — render an inline placeholder so the COMMIT "
            "HISTORY section doesn't read as broken",
        )
        self.assertIn(
            "Commit history is empty until gitops is configured",
            branch,
            "loadGitops not-enabled branch must render a placeholder "
            "that points the operator back at the config",
        )


class TestFleetGridsResponsive(unittest.TestCase):
    """Fleet page grids must use auto-fill with a minmax() min track
    so narrow (mobile) viewports collapse columns instead of
    crushing host-card / infra-role-card children below their
    intrinsic width."""

    def test_core_systems_grid_uses_auto_fill(self):
        src = _js()
        # Anchor on the _assembleFleetOutput function body so we hit
        # the rendered markup, not any comment or unrelated mention
        # of 'CORE SYSTEMS' elsewhere in the file.
        body = _function_body(src, "_assembleFleetOutput")
        self.assertIn("CORE SYSTEMS", body)
        # Must NOT use the old fixed repeat(N,1fr) pattern anywhere in
        # the function body (both the core-systems and pve-vms grids
        # were converted to auto-fill).
        self.assertNotRegex(
            body,
            r"grid-template-columns:repeat\(\s*\d\s*,\s*1fr\s*\)",
            "CORE SYSTEMS grid must not use a fixed repeat(N,1fr) "
            "column count — use minmax() auto-fill so it collapses "
            "to 1 column on mobile",
        )
        self.assertIn(
            "repeat(auto-fill,minmax(180px,1fr))",
            body,
            "CORE SYSTEMS grid must use auto-fill with minmax(180px,1fr)",
        )
        self.assertIn(
            'class="core-systems-grid"',
            body,
            "CORE SYSTEMS grid must carry the core-systems-grid class",
        )

    def test_pve_node_inner_grid_uses_auto_fill(self):
        """The 3-column sub-group grid inside each pve node card
        (UTILIZATION / VMs / CONTAINERS) must auto-fill."""
        src = _js()
        # There are two branches (live-metrics vs no-pve-api) — both
        # must carry the auto-fill pattern. Count occurrences of the
        # new pattern; legacy fixed 1fr 1fr 1fr should be gone from
        # pve node cards.
        pve_section = src[src.index("function _assembleFleetOutput") - 4000:
                          src.index("function _assembleFleetOutput")]
        self.assertNotIn(
            "grid-template-columns:1fr 1fr 1fr",
            pve_section,
            "PVE node inner grid must not hard-code 1fr 1fr 1fr — "
            "use minmax() auto-fill so sub-groups stack on mobile",
        )
        # At least two occurrences of the auto-fill replacement (live
        # branch + no-api branch).
        self.assertGreaterEqual(
            pve_section.count("repeat(auto-fill,minmax(140px,1fr))"),
            2,
            "Both PVE node card branches (live-metrics, no-api) must "
            "use the auto-fill responsive grid",
        )

    def test_pve_vms_grid_uses_auto_fill(self):
        """The .pve-vms grid (VMs sub-list expanded under each PVE
        node) must also auto-fill so VM cards don't crush to 4 cols
        wide on mobile."""
        src = _js()
        idx = src.index('class="pve-vms"')
        block = src[idx: idx + 400]
        self.assertNotRegex(
            block,
            r"grid-template-columns:repeat\(\s*'?\s*\+\s*cols\s*\+\s*'?\s*,\s*1fr\s*\)",
            "pve-vms grid must not use the dynamic repeat(cols,1fr) "
            "pattern — use minmax() auto-fill",
        )
        self.assertIn(
            "repeat(auto-fill,minmax(160px,1fr))",
            block,
            "pve-vms grid must use auto-fill with a 160px min track",
        )


if __name__ == "__main__":
    unittest.main()
