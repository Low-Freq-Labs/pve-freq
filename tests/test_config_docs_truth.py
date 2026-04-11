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

    def setUp(self):
        from freq.core.config import _DEFAULTS
        self.defaults = _DEFAULTS

        with open(os.path.join(REPO_ROOT, "docs", "CONFIGURATION.md")) as f:
            self.doc = f.read()

    # SSH defaults
    def test_service_account_default(self):
        """Doc says freq-admin, code must agree."""
        self.assertEqual(self.defaults["ssh_service_account"], "freq-admin")
        self.assertIn('"freq-admin"', self.doc)

    def test_connect_timeout_default(self):
        self.assertEqual(self.defaults["ssh_connect_timeout"], 5)
        self.assertIn("| `connect_timeout` | int | `5`", self.doc)

    def test_max_parallel_default(self):
        self.assertEqual(self.defaults["ssh_max_parallel"], 5)
        self.assertIn("| `max_parallel` | int | `5`", self.doc)

    def test_ssh_mode_default(self):
        self.assertEqual(self.defaults["ssh_mode"], "sudo")
        self.assertIn('"sudo"', self.doc)

    # VM defaults
    def test_vm_cores_default(self):
        self.assertEqual(self.defaults["vm_default_cores"], 2)
        self.assertIn("| `cores` | int | `2`", self.doc)

    def test_vm_ram_default(self):
        self.assertEqual(self.defaults["vm_default_ram"], 2048)
        self.assertIn("| `ram` | int | `2048`", self.doc)

    def test_vm_disk_default(self):
        self.assertEqual(self.defaults["vm_default_disk"], 32)
        self.assertIn("| `disk` | int | `32`", self.doc)

    def test_vm_cpu_default(self):
        self.assertEqual(self.defaults["vm_cpu"], "x86-64-v2-AES")
        self.assertIn('"x86-64-v2-AES"', self.doc)

    def test_vm_nameserver_default(self):
        self.assertEqual(self.defaults["vm_nameserver"], "1.1.1.1")
        self.assertIn('"1.1.1.1"', self.doc)

    # Service ports
    def test_dashboard_port_default(self):
        self.assertEqual(self.defaults["dashboard_port"], 8888)
        self.assertIn("| `dashboard_port` | int | `8888`", self.doc)

    def test_watchdog_port_default(self):
        self.assertEqual(self.defaults["watchdog_port"], 9900)
        self.assertIn("| `watchdog_port` | int | `9900`", self.doc)

    def test_agent_port_default(self):
        self.assertEqual(self.defaults["agent_port"], 9990)
        self.assertIn("| `agent_port` | int | `9990`", self.doc)

    # Safety
    def test_max_failure_percent_default(self):
        self.assertEqual(self.defaults["max_failure_percent"], 50)
        self.assertIn("| `max_failure_percent` | int | `50`", self.doc)

    # General
    def test_brand_default(self):
        self.assertEqual(self.defaults["brand"], "PVE FREQ")
        self.assertIn('"PVE FREQ"', self.doc)

    def test_build_default(self):
        self.assertEqual(self.defaults["build"], "default")
        self.assertIn('"default"', self.doc)


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
