"""Package template operator truth tests.

Proves:
1. All template sources agree on default service_account name
2. Package template matches code default
3. Top-level example matches package template
4. Docker example matches package template
5. No silent drift between install paths
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")


def _extract_service_account(path):
    """Extract service_account value from a freq.toml example."""
    with open(path) as f:
        for line in f:
            m = re.match(r'^service_account\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
    return None


class TestServiceAccountConsistency(unittest.TestCase):
    """All template sources must agree on the default service account."""

    def test_code_default_is_freq_admin(self):
        from freq.core.config import _DEFAULTS
        self.assertEqual(_DEFAULTS["ssh_service_account"], "freq-admin")

    def test_package_template_matches_code_default(self):
        path = os.path.join(REPO_ROOT, "freq/data/conf-templates/freq.toml.example")
        val = _extract_service_account(path)
        self.assertEqual(val, "freq-admin",
                         "Package template must use code default freq-admin")

    def test_top_level_example_matches_code_default(self):
        path = os.path.join(REPO_ROOT, "conf/freq.toml.example")
        val = _extract_service_account(path)
        self.assertEqual(val, "freq-admin",
                         "Top-level example must use code default freq-admin")

    @unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
    def test_docker_example_matches_code_default(self):
        path = os.path.join(DOCKER_REPO, "conf/freq.toml.example")
        val = _extract_service_account(path)
        self.assertEqual(val, "freq-admin",
                         "Docker example must use code default freq-admin")

    def test_all_three_match(self):
        """Package template, top-level example, and code default must all agree."""
        from freq.core.config import _DEFAULTS
        pkg = _extract_service_account(
            os.path.join(REPO_ROOT, "freq/data/conf-templates/freq.toml.example"))
        top = _extract_service_account(
            os.path.join(REPO_ROOT, "conf/freq.toml.example"))
        code = _DEFAULTS["ssh_service_account"]
        self.assertEqual(pkg, top, "Package and top-level examples must match")
        self.assertEqual(pkg, code, "Package template must match code default")


class TestLiveConfigIsCustomization(unittest.TestCase):
    """Live config can differ from defaults — that's a customization, not a bug."""

    def test_live_config_may_differ_from_default(self):
        from freq.core.config import load_config, _DEFAULTS
        cfg = load_config()
        # This is expected — live config is customized by init
        # The test just documents the relationship
        if cfg.ssh_service_account != _DEFAULTS["ssh_service_account"]:
            # Customized — this is fine
            pass
        # What matters is that the DEFAULTS are consistent with templates


if __name__ == "__main__":
    unittest.main()
