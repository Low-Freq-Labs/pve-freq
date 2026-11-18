"""Security overview population contract from the live polish pass."""

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


if __name__ == "__main__":
    unittest.main()
