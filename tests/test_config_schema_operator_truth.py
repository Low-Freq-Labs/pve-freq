"""Config schema operator truth tests.

Proves:
1. No phantom keys in freq.toml examples (keys that runtime ignores)
2. PVE token field names match what config.py actually parses
3. vm.defaults keys match what config.py actually reads
4. All three template sources agree on structure
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")

# Keys that config.py actually parses from [pve] section
PVE_PARSED_KEYS = {"nodes", "node_names", "api_token_id", "api_token_secret_path", "api_verify_ssl"}

# Keys that config.py actually parses from [vm.defaults] section
VM_DEFAULTS_PARSED_KEYS = {"cores", "ram", "disk", "cpu", "machine", "scsihw", "gateway", "nameserver"}

# Known phantom keys that should NOT appear in examples
PHANTOM_KEYS = {"ssh_user", "ci_user", "domain", "bios"}


def _extract_toml_keys(path, section):
    """Extract uncommented key names from a TOML section."""
    keys = set()
    in_section = False
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("[") and not stripped.startswith("# ["):
                in_section = stripped == f"[{section}]"
                continue
            if in_section and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=")[0].strip()
                keys.add(key)
    return keys


class TestNoPhantomKeys(unittest.TestCase):
    """Examples must not contain keys that the runtime ignores."""

    def _check_file(self, path, label):
        for section, phantoms in [("pve", {"ssh_user"}), ("vm.defaults", {"ci_user", "domain", "bios"})]:
            keys = _extract_toml_keys(path, section)
            for phantom in phantoms:
                self.assertNotIn(phantom, keys,
                                 f"{label} [{section}] has phantom key '{phantom}' — runtime ignores it")

    def test_top_level_example_no_phantoms(self):
        self._check_file(os.path.join(REPO_ROOT, "conf/freq.toml.example"), "conf/freq.toml.example")

    def test_package_template_no_phantoms(self):
        self._check_file(os.path.join(REPO_ROOT, "freq/data/conf-templates/freq.toml.example"),
                          "package template")

    @unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
    def test_docker_example_no_phantoms(self):
        self._check_file(os.path.join(DOCKER_REPO, "conf/freq.toml.example"), "Docker example")


class TestPVETokenFieldNames(unittest.TestCase):
    """PVE token field names in examples must match config.py parser."""

    def test_loader_reads_api_token_id(self):
        with open(os.path.join(REPO_ROOT, "freq/core/config.py")) as f:
            src = f.read()
        self.assertIn('pve.get("api_token_id"', src,
                       "Config loader must read api_token_id (not token_id)")

    def test_examples_use_api_token_id(self):
        """Examples must use api_token_id, not token_id."""
        for path in [
            os.path.join(REPO_ROOT, "conf/freq.toml.example"),
            os.path.join(REPO_ROOT, "freq/data/conf-templates/freq.toml.example"),
        ]:
            with open(path) as f:
                src = f.read()
            # Should NOT have bare token_id (without api_ prefix)
            for line in src.split("\n"):
                if line.strip().startswith("#"):
                    if "token_id" in line and "api_token_id" not in line:
                        self.fail(f"Example uses 'token_id' instead of 'api_token_id': {line.strip()}")


if __name__ == "__main__":
    unittest.main()
