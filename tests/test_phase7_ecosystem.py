"""Tests for Phase 7 — The Ecosystem (WS19: Plugin System).
Covers: Module imports, CLI registration, registry operations, scaffold generation.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class MockConfig:
    def __init__(self, tmpdir):
        self.conf_dir = tmpdir
        self.log_file = "/dev/null"
        self.debug = False
        self.ascii_mode = False
        self.version = "3.0.0"
        self.build = "test"
        os.makedirs(os.path.join(tmpdir, "plugins"), exist_ok=True)


class TestPhase7Imports(unittest.TestCase):
    """Verify all Phase 7 modules import cleanly."""

    def test_plugin_manager(self):
        from freq.modules.plugin_manager import (
            cmd_plugin_list, cmd_plugin_info, cmd_plugin_install,
            cmd_plugin_remove, cmd_plugin_create, cmd_plugin_search,
            cmd_plugin_update, cmd_plugin_types,
        )
        for fn in (cmd_plugin_list, cmd_plugin_info, cmd_plugin_install,
                   cmd_plugin_remove, cmd_plugin_create, cmd_plugin_search,
                   cmd_plugin_update, cmd_plugin_types):
            self.assertTrue(callable(fn))

    def test_plugin_types_constant(self):
        from freq.modules.plugin_manager import PLUGIN_TYPES
        self.assertIn("command", PLUGIN_TYPES)
        self.assertIn("deployer", PLUGIN_TYPES)
        self.assertIn("notification", PLUGIN_TYPES)
        self.assertIn("policy", PLUGIN_TYPES)
        self.assertIn("importer", PLUGIN_TYPES)
        self.assertIn("exporter", PLUGIN_TYPES)
        self.assertIn("widget", PLUGIN_TYPES)
        self.assertEqual(len(PLUGIN_TYPES), 7)

    def test_scaffold_templates(self):
        from freq.modules.plugin_manager import SCAFFOLD_TEMPLATES
        self.assertIn("command", SCAFFOLD_TEMPLATES)
        self.assertIn("deployer", SCAFFOLD_TEMPLATES)
        self.assertIn("notification", SCAFFOLD_TEMPLATES)
        self.assertIn("policy", SCAFFOLD_TEMPLATES)

    def test_api_module(self):
        from freq.api.plugin import register
        self.assertTrue(callable(register))


class TestPhase7CLI(unittest.TestCase):
    """Verify all plugin CLI commands are registered."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def _parse(self, s):
        return self.parser.parse_args(s.split())

    def test_plugin_list(self):
        args = self._parse("plugin list")
        self.assertTrue(hasattr(args, "func"))

    def test_plugin_info(self):
        args = self._parse("plugin info test-name")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.name, "test-name")

    def test_plugin_install(self):
        args = self._parse("plugin install https://example.com/p.py")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.source, "https://example.com/p.py")

    def test_plugin_remove(self):
        args = self._parse("plugin remove test-plugin")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.name, "test-plugin")

    def test_plugin_create(self):
        args = self._parse("plugin create --name my-plugin --type deployer")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.name, "my-plugin")
        self.assertEqual(args.type, "deployer")

    def test_plugin_search(self):
        args = self._parse("plugin search firewall")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.query, "firewall")

    def test_plugin_update(self):
        args = self._parse("plugin update")
        self.assertTrue(hasattr(args, "func"))

    def test_plugin_update_specific(self):
        args = self._parse("plugin update my-plugin")
        self.assertTrue(hasattr(args, "func"))
        self.assertEqual(args.name, "my-plugin")

    def test_plugin_types(self):
        args = self._parse("plugin types")
        self.assertTrue(hasattr(args, "func"))


class TestPluginRegistry(unittest.TestCase):
    """Test plugin registry read/write operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_registry(self):
        from freq.modules.plugin_manager import _load_registry
        reg = _load_registry(self.cfg)
        self.assertEqual(reg, {"plugins": {}})

    def test_save_and_load(self):
        from freq.modules.plugin_manager import _load_registry, _save_registry
        reg = _load_registry(self.cfg)
        reg["plugins"]["test"] = {
            "type": "command",
            "version": "1.0.0",
            "description": "Test plugin",
        }
        _save_registry(self.cfg, reg)

        # Reload and verify
        reg2 = _load_registry(self.cfg)
        self.assertIn("test", reg2["plugins"])
        self.assertEqual(reg2["plugins"]["test"]["version"], "1.0.0")

    def test_registry_file_location(self):
        from freq.modules.plugin_manager import _save_registry, _registry_path
        _save_registry(self.cfg, {"plugins": {}})
        path = _registry_path(self.cfg)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.endswith("plugins/registry.json"))


class TestPluginScaffold(unittest.TestCase):
    """Test plugin scaffold generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = MockConfig(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_command_scaffold(self):
        from freq.modules.plugin_manager import SCAFFOLD_TEMPLATES
        template = SCAFFOLD_TEMPLATES["command"]
        content = template.format(name="test-cmd", description="A test command")
        self.assertIn('NAME = "test-cmd"', content)
        self.assertIn('PLUGIN_TYPE = "command"', content)
        self.assertIn("def run(cfg, pack, args):", content)

    def test_deployer_scaffold(self):
        from freq.modules.plugin_manager import SCAFFOLD_TEMPLATES
        template = SCAFFOLD_TEMPLATES["deployer"]
        content = template.format(name="mikrotik", description="MikroTik", category="switch")
        self.assertIn('CATEGORY = "switch"', content)
        self.assertIn('VENDOR = "mikrotik"', content)
        self.assertIn("def deploy(", content)
        self.assertIn("def get_facts(", content)

    def test_notification_scaffold(self):
        from freq.modules.plugin_manager import SCAFFOLD_TEMPLATES
        template = SCAFFOLD_TEMPLATES["notification"]
        content = template.format(name="pagerduty", description="PagerDuty alerts")
        self.assertIn('PLUGIN_TYPE = "notification"', content)
        self.assertIn("def send(", content)

    def test_policy_scaffold(self):
        from freq.modules.plugin_manager import SCAFFOLD_TEMPLATES
        template = SCAFFOLD_TEMPLATES["policy"]
        content = template.format(name="pci-dss", description="PCI DSS checks")
        self.assertIn('PLUGIN_TYPE = "policy"', content)
        self.assertIn("def check(", content)


class TestPluginDiscoveryIntegration(unittest.TestCase):
    """Test that plugin discovery still works with new system."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.plugin_dir = os.path.join(self.tmpdir, "plugins")
        os.makedirs(self.plugin_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_discover_finds_valid_plugin(self):
        from freq.core.plugins import discover_plugins
        plugin_code = '''
NAME = "test-discover"
DESCRIPTION = "Test plugin"
def run(cfg, pack, args):
    return 0
'''
        with open(os.path.join(self.plugin_dir, "test_discover.py"), "w") as f:
            f.write(plugin_code)

        plugins = discover_plugins(self.plugin_dir)
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["name"], "test-discover")

    def test_discover_skips_invalid(self):
        from freq.core.plugins import discover_plugins
        # Plugin missing NAME
        with open(os.path.join(self.plugin_dir, "bad.py"), "w") as f:
            f.write("DESCRIPTION = 'no name'\ndef run(cfg, pack, args): return 0\n")

        plugins = discover_plugins(self.plugin_dir)
        self.assertEqual(len(plugins), 0)

    def test_discover_skips_underscore(self):
        from freq.core.plugins import discover_plugins
        with open(os.path.join(self.plugin_dir, "_internal.py"), "w") as f:
            f.write("NAME = 'internal'\ndef run(cfg, pack, args): return 0\n")

        plugins = discover_plugins(self.plugin_dir)
        self.assertEqual(len(plugins), 0)

    def test_discover_empty_dir(self):
        from freq.core.plugins import discover_plugins
        plugins = discover_plugins(self.plugin_dir)
        self.assertEqual(len(plugins), 0)

    def test_discover_nonexistent_dir(self):
        from freq.core.plugins import discover_plugins
        plugins = discover_plugins("/nonexistent/path")
        self.assertEqual(len(plugins), 0)


class TestDeployerRegistry(unittest.TestCase):
    """Verify deployer registry still works — no regressions."""

    def test_resolve_htype_legacy(self):
        from freq.deployers import resolve_htype
        self.assertEqual(resolve_htype("pfsense"), ("firewall", "pfsense"))
        self.assertEqual(resolve_htype("linux"), ("server", "linux"))

    def test_resolve_htype_new_format(self):
        from freq.deployers import resolve_htype
        self.assertEqual(resolve_htype("switch:cisco"), ("switch", "cisco"))
        self.assertEqual(resolve_htype("bmc:idrac"), ("bmc", "idrac"))

    def test_resolve_htype_unknown(self):
        from freq.deployers import resolve_htype
        self.assertEqual(resolve_htype("mystery"), ("unknown", "mystery"))

    def test_list_deployers(self):
        from freq.deployers import list_deployers
        deployers = list_deployers()
        self.assertIsInstance(deployers, list)
        # Should find at least cisco and pfsense
        categories = [d[0] for d in deployers]
        self.assertIn("switch", categories)
        self.assertIn("firewall", categories)

    def test_get_deployer_cisco(self):
        from freq.deployers import get_deployer
        mod = get_deployer("switch", "cisco")
        self.assertIsNotNone(mod)
        self.assertTrue(hasattr(mod, "get_facts"))


if __name__ == "__main__":
    unittest.main()
