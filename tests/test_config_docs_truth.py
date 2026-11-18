"""Regression tests for CONFIGURATION.md accuracy.

Proves: default values documented in CONFIGURATION.md match actual
defaults in freq/core/config.py.

Catches: doc says default is "foo" but code uses "bar", which
misleads operators who rely on docs to understand safe defaults.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestConfigDefaultsTruth(unittest.TestCase):
    """CONFIGURATION.md default values must match config.py _DEFAULTS."""

    CASES = (
        ("service-account", "ssh_service_account", "freq-admin", '"freq-admin"'),
        ("connect-timeout", "ssh_connect_timeout", 5, "| `connect_timeout` | int | `5`"),
        ("max-parallel", "ssh_max_parallel", 5, "| `max_parallel` | int | `5`"),
        ("ssh-mode", "ssh_mode", "sudo", '"sudo"'),
        ("vm-cores", "vm_default_cores", 2, "| `cores` | int | `2`"),
        ("vm-ram", "vm_default_ram", 2048, "| `ram` | int | `2048`"),
        ("vm-disk", "vm_default_disk", 32, "| `disk` | int | `32`"),
        ("vm-cpu", "vm_cpu", "x86-64-v2-AES", '"x86-64-v2-AES"'),
        ("vm-nameserver", "vm_nameserver", "1.1.1.1", '"1.1.1.1"'),
        ("dashboard-port", "dashboard_port", 8888, "| `dashboard_port` | int | `8888`"),
        ("watchdog-port", "watchdog_port", 9900, "| `watchdog_port` | int | `9900`"),
        ("watchdog-enabled", "watchdog_enabled", True, "| `watchdog_enabled` | bool | `true`"),
        ("agent-port", "agent_port", 9990, "| `agent_port` | int | `9990`"),
        ("max-failure-percent", "max_failure_percent", 50, "| `max_failure_percent` | int | `50`"),
        ("brand", "brand", "PVE FREQ", '"PVE FREQ"'),
        ("build", "build", "default", '"default"'),
    )

    def setUp(self):
        from freq.core.config import _DEFAULTS
        self.defaults = _DEFAULTS

        with open(os.path.join(REPO_ROOT, "docs", "CONFIGURATION.md")) as f:
            self.doc = f.read()

    def test_config_default_documentation_matrix(self):
        self.assertEqual(len(self.CASES), 16)
        case_ids = tuple(case_id for case_id, *_rest in self.CASES)
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case_id, key, expected, doc_fragment in self.CASES:
            with self.subTest(case=case_id, key=key):
                self.assertEqual(self.defaults[key], expected)
                self.assertIn(doc_fragment, self.doc)

class TestConfigDocStructure(unittest.TestCase):
    """CONFIGURATION.md must document all config files mentioned in README."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "docs", "CONFIGURATION.md")) as f:
            self.doc = f.read()

    def test_documents_freq_toml(self):
        self.assertIn("freq.toml", self.doc)

    def test_documents_hosts_file(self):
        self.assertIn("hosts", self.doc)

    def test_documents_vlans(self):
        self.assertIn("vlans.toml", self.doc)

    def test_documents_fleet_boundaries(self):
        self.assertIn("fleet-boundaries", self.doc)

    def test_documents_rules(self):
        self.assertIn("rules.toml", self.doc)


class TestConfigTemplatesExist(unittest.TestCase):
    """Config templates referenced in docs must exist on disk."""

    def test_freq_toml_example_exists(self):
        path = os.path.join(REPO_ROOT, "freq", "data", "conf-templates",
                           "freq.toml.example")
        self.assertTrue(os.path.isfile(path),
                        "freq.toml.example must exist")

    def test_hosts_toml_example_exists(self):
        path = os.path.join(REPO_ROOT, "freq", "data", "conf-templates",
                           "hosts.toml.example")
        self.assertTrue(os.path.isfile(path),
                        "hosts.toml.example must exist")


if __name__ == "__main__":
    unittest.main()
