"""Hosts registry operator truth tests.

Proves:
1. hosts.toml is the primary fleet registry (not hosts.conf)
2. Operator-visible help text references hosts.toml
3. Config loader uses hosts.toml as primary, hosts.conf as legacy fallback
4. Legacy hosts.conf triggers auto-migration to hosts.toml
5. No operator-facing code claims hosts.conf is the primary format
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestHostsTomlIsPrimary(unittest.TestCase):
    """hosts.toml is the primary fleet registry format."""

    def test_config_loads_hosts_toml(self):
        """load_config sets hosts_file to hosts.toml."""
        from freq.core.config import load_config
        cfg = load_config()
        self.assertTrue(cfg.hosts_file.endswith("hosts.toml"),
                         f"hosts_file should be hosts.toml, got {cfg.hosts_file}")

    def test_hosts_toml_exists(self):
        from freq.core.config import load_config
        cfg = load_config()
        self.assertTrue(os.path.isfile(cfg.hosts_file),
                         "hosts.toml must exist")

    def test_config_loader_prefers_toml(self):
        """Config loader must check hosts.toml before hosts.conf."""
        with open(os.path.join(REPO_ROOT, "freq/core/config.py")) as f:
            src = f.read()
        # The loading section should check hosts.toml first
        load_section = src.split("# Load fleet data")[1].split("# Load")[0]
        toml_idx = load_section.index("hosts.toml")
        conf_idx = load_section.index("hosts.conf")
        self.assertLess(toml_idx, conf_idx,
                         "hosts.toml must be checked before hosts.conf")


class TestLegacyMigration(unittest.TestCase):
    """Legacy hosts.conf triggers auto-migration."""

    def test_migration_path_exists(self):
        with open(os.path.join(REPO_ROOT, "freq/core/config.py")) as f:
            src = f.read()
        self.assertIn("auto-migrated hosts.conf to hosts.toml", src,
                       "Config loader must have auto-migration path")

    def test_deprecation_warning_exists(self):
        with open(os.path.join(REPO_ROOT, "freq/core/config.py")) as f:
            src = f.read()
        self.assertIn("_deprecation_warn", src,
                       "Legacy format must trigger deprecation warning")


class TestOperatorFacingLanguage(unittest.TestCase):
    """Operator-visible text must reference hosts.toml, not hosts.conf."""

    def test_cli_help_says_hosts_toml(self):
        """CLI help text must reference hosts.toml."""
        with open(os.path.join(REPO_ROOT, "freq/cli.py")) as f:
            src = f.read()
        # Find help= strings that mention hosts
        import re
        helps = re.findall(r'help="[^"]*hosts\.[^"]*"', src)
        for h in helps:
            self.assertNotIn("hosts.conf", h,
                              f"CLI help still references hosts.conf: {h}")

    def test_config_docstring_updated(self):
        with open(os.path.join(REPO_ROOT, "freq/core/config.py")) as f:
            lines = f.readlines()
        # First docstring (module-level)
        docstring = "".join(lines[:25])
        self.assertNotIn("Reads freq.toml (primary) and legacy bash-style configs (hosts.conf",
                          docstring,
                          "Config docstring should not present hosts.conf as current")

    def test_gitops_docstring_updated(self):
        with open(os.path.join(REPO_ROOT, "freq/jarvis/gitops.py")) as f:
            lines = f.readlines()
        docstring = "".join(lines[:10])
        self.assertNotIn("hosts.conf", docstring,
                          "GitOps docstring should reference hosts.toml")


if __name__ == "__main__":
    unittest.main()
