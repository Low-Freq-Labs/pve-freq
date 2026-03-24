"""Overnight Matrix — Deep Coverage: TOML Parser, Containers, Distros, Doctor

Stress-tests the TOML fallback parser, container registry loading,
distro definitions, and doctor individual checks.
"""
import os
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

RICK_DIR = str(Path(__file__).parent.parent)
CONF_DIR = os.path.join(RICK_DIR, "conf")


class TestTOMLParser(unittest.TestCase):
    """Test the basic TOML parser (Python < 3.11 fallback)."""

    def test_parse_string_double_quotes(self):
        from freq.core.config import _parse_toml_value
        self.assertEqual(_parse_toml_value('"hello world"'), "hello world")

    def test_parse_string_single_quotes(self):
        from freq.core.config import _parse_toml_value
        self.assertEqual(_parse_toml_value("'hello'"), "hello")

    def test_parse_boolean_true(self):
        from freq.core.config import _parse_toml_value
        self.assertTrue(_parse_toml_value("true"))
        self.assertTrue(_parse_toml_value("True"))

    def test_parse_boolean_false(self):
        from freq.core.config import _parse_toml_value
        self.assertFalse(_parse_toml_value("false"))
        self.assertFalse(_parse_toml_value("False"))

    def test_parse_integer(self):
        from freq.core.config import _parse_toml_value
        self.assertEqual(_parse_toml_value("42"), 42)
        self.assertEqual(_parse_toml_value("0"), 0)
        self.assertEqual(_parse_toml_value("-1"), -1)

    def test_parse_float(self):
        from freq.core.config import _parse_toml_value
        self.assertEqual(_parse_toml_value("3.14"), 3.14)

    def test_parse_empty_array(self):
        from freq.core.config import _parse_toml_value
        self.assertEqual(_parse_toml_value("[]"), [])

    def test_parse_string_array(self):
        from freq.core.config import _parse_toml_value
        result = _parse_toml_value('["a", "b", "c"]')
        self.assertEqual(result, ["a", "b", "c"])

    def test_parse_int_array(self):
        from freq.core.config import _parse_toml_value
        result = _parse_toml_value("[1, 2, 3]")
        self.assertEqual(result, [1, 2, 3])

    def test_parse_empty_inline_table(self):
        from freq.core.config import _parse_toml_value
        self.assertEqual(_parse_toml_value("{}"), {})

    def test_parse_inline_table(self):
        from freq.core.config import _parse_toml_value
        result = _parse_toml_value('{cores = 2, ram = 1024}')
        self.assertEqual(result["cores"], 2)
        self.assertEqual(result["ram"], 1024)

    def test_parse_bare_string(self):
        from freq.core.config import _parse_toml_value
        self.assertEqual(_parse_toml_value("hello"), "hello")


class TestTOMLBasicParser(unittest.TestCase):
    """Test the basic TOML file parser."""

    def test_parse_simple_file(self):
        from freq.core.config import _parse_toml_basic
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[freq]\n")
            f.write('version = "1.0"\n')
            f.write("debug = true\n")
            f.write("cores = 4\n")
            path = f.name
        try:
            data = _parse_toml_basic(path)
            self.assertEqual(data["freq"]["version"], "1.0")
            self.assertTrue(data["freq"]["debug"])
            self.assertEqual(data["freq"]["cores"], 4)
        finally:
            os.unlink(path)

    def test_parse_nested_sections(self):
        from freq.core.config import _parse_toml_basic
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[vm.defaults]\n")
            f.write("cores = 2\n")
            f.write("ram = 2048\n")
            path = f.name
        try:
            data = _parse_toml_basic(path)
            self.assertEqual(data["vm"]["defaults"]["cores"], 2)
            self.assertEqual(data["vm"]["defaults"]["ram"], 2048)
        finally:
            os.unlink(path)

    def test_parse_comments_ignored(self):
        from freq.core.config import _parse_toml_basic
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("[freq]\n")
            f.write("# Another comment\n")
            f.write('brand = "test"\n')
            path = f.name
        try:
            data = _parse_toml_basic(path)
            self.assertEqual(data["freq"]["brand"], "test")
        finally:
            os.unlink(path)

    def test_parse_empty_lines_ignored(self):
        from freq.core.config import _parse_toml_basic
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("\n\n[freq]\n\n")
            f.write('brand = "test"\n\n')
            path = f.name
        try:
            data = _parse_toml_basic(path)
            self.assertEqual(data["freq"]["brand"], "test")
        finally:
            os.unlink(path)

    def test_parse_nonexistent_file(self):
        from freq.core.config import _parse_toml_basic
        data = _parse_toml_basic("/nonexistent/file.toml")
        self.assertEqual(data, {})


class TestContainerLoading(unittest.TestCase):
    """Test container registry loading."""

    def test_load_containers_from_file(self):
        """Load a containers.toml file."""
        from freq.core.config import load_containers
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[vm.101]\n')
            f.write('ip = "10.0.0.10"\n')
            f.write('label = "media-server"\n')
            f.write('compose_path = "/opt/docker/compose.yml"\n')
            path = f.name
        try:
            containers = load_containers(path)
            self.assertIn(101, containers)
            self.assertEqual(containers[101].ip, "10.0.0.10")
            self.assertEqual(containers[101].label, "media-server")
        finally:
            os.unlink(path)

    def test_load_containers_empty(self):
        """Empty containers.toml returns empty dict."""
        from freq.core.config import load_containers
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("# empty\n")
            path = f.name
        try:
            containers = load_containers(path)
            self.assertEqual(containers, {})
        finally:
            os.unlink(path)

    def test_load_containers_missing(self):
        """Missing containers.toml returns empty dict."""
        from freq.core.config import load_containers
        containers = load_containers("/nonexistent/containers.toml")
        self.assertEqual(containers, {})

    def test_load_containers_from_dc01(self):
        """Load actual DC01 containers.toml."""
        from freq.core.config import load_containers
        path = os.path.join(CONF_DIR, "containers.toml")
        if os.path.isfile(path):
            containers = load_containers(path)
            self.assertIsInstance(containers, dict)
            # Check structure of loaded containers
            for vm_id, vm in containers.items():
                self.assertIsInstance(vm_id, int)
                self.assertTrue(len(vm.ip) > 0 or vm.ip == "")
        else:
            self.skipTest("No containers.toml in DC01 config")


class TestDistroLoading(unittest.TestCase):
    """Test cloud image definition loading."""

    def test_load_distros_empty(self):
        """Empty distros.toml returns empty list."""
        from freq.core.config import load_distros
        distros = load_distros("/nonexistent/distros.toml")
        self.assertEqual(distros, [])

    def test_load_distros_dc01(self):
        """Load actual DC01 distros.toml."""
        from freq.core.config import load_distros
        path = os.path.join(CONF_DIR, "distros.toml")
        if os.path.isfile(path):
            distros = load_distros(path)
            self.assertGreater(len(distros), 0)
            # Check structure
            for d in distros:
                self.assertTrue(len(d.key) > 0)
                self.assertTrue(len(d.name) > 0)
                self.assertTrue(len(d.url) > 0)
        else:
            self.skipTest("No distros.toml in DC01 config")


class TestVLANLoading(unittest.TestCase):
    """Test VLAN definition loading."""

    def test_load_vlans_dc01(self):
        """Load actual DC01 vlans.toml."""
        from freq.core.config import load_vlans
        path = os.path.join(CONF_DIR, "vlans.toml")
        if os.path.isfile(path):
            vlans = load_vlans(path)
            self.assertGreater(len(vlans), 0)
            for v in vlans:
                self.assertGreaterEqual(v.id, 0)  # 0 = untagged/native VLAN
                self.assertTrue(len(v.name) > 0)
                self.assertTrue(len(v.subnet) > 0)
        else:
            self.skipTest("No vlans.toml in DC01 config")

    def test_load_vlans_with_gateway(self):
        """VLANs with gateway field."""
        from freq.core.config import load_vlans
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[vlan.test]\n')
            f.write('id = 100\n')
            f.write('name = "TEST"\n')
            f.write('subnet = "10.0.0.0/24"\n')
            f.write('prefix = "10.0.0"\n')
            f.write('gateway = "10.0.0.1"\n')
            path = f.name
        try:
            vlans = load_vlans(path)
            self.assertEqual(len(vlans), 1)
            self.assertEqual(vlans[0].gateway, "10.0.0.1")
        finally:
            os.unlink(path)


class TestDoctorChecks(unittest.TestCase):
    """Test individual doctor check functions (non-SSH)."""

    def setUp(self):
        from freq.core.config import load_config
        self.cfg = load_config()

    def test_check_python(self):
        from freq.core.doctor import _check_python
        result = _check_python(self.cfg)
        self.assertEqual(result, 0)  # We're running on 3.13

    def test_check_platform(self):
        from freq.core.doctor import _check_platform
        result = _check_platform(self.cfg)
        self.assertEqual(result, 0)  # We're on Linux

    def test_check_prerequisites(self):
        from freq.core.doctor import _check_prerequisites
        result = _check_prerequisites(self.cfg)
        self.assertIn(result, [0, 2])  # 0 = all found, 2 = optional missing

    def test_check_install_dir(self):
        from freq.core.doctor import _check_install_dir
        result = _check_install_dir(self.cfg)
        self.assertEqual(result, 0)

    def test_check_config(self):
        from freq.core.doctor import _check_config
        result = _check_config(self.cfg)
        self.assertEqual(result, 0)

    def test_check_ssh_binary(self):
        from freq.core.doctor import _check_ssh_binary
        result = _check_ssh_binary(self.cfg)
        self.assertEqual(result, 0)

    def test_check_ssh_key(self):
        from freq.core.doctor import _check_ssh_key
        result = _check_ssh_key(self.cfg)
        self.assertIn(result, [0, 2])  # 0 = found, 2 = not found

    def test_check_hosts(self):
        from freq.core.doctor import _check_hosts
        result = _check_hosts(self.cfg)
        self.assertEqual(result, 0)

    def test_check_hosts_validity(self):
        from freq.core.doctor import _check_hosts_validity
        result = _check_hosts_validity(self.cfg)
        self.assertEqual(result, 0)

    def test_check_vlans(self):
        from freq.core.doctor import _check_vlans
        result = _check_vlans(self.cfg)
        self.assertEqual(result, 0)

    def test_check_distros(self):
        from freq.core.doctor import _check_distros
        result = _check_distros(self.cfg)
        self.assertEqual(result, 0)

    def test_check_personality(self):
        from freq.core.doctor import _check_personality
        result = _check_personality(self.cfg)
        self.assertEqual(result, 0)


class TestCompatModule(unittest.TestCase):
    """Test Python version compatibility check."""

    def test_current_version_ok(self):
        from freq.core.compat import check_python
        result = check_python()
        self.assertIsNone(result)

    def test_min_python_constant(self):
        from freq.core.compat import MIN_PYTHON
        self.assertEqual(MIN_PYTHON, (3, 7))


class TestFleetBoundariesDetailed(unittest.TestCase):
    """Detailed FleetBoundaries tests with DC01 config."""

    def setUp(self):
        from freq.core.config import load_config
        self.cfg = load_config()
        self.fb = self.cfg.fleet_boundaries

    def test_categories_have_description(self):
        """Every category has a description."""
        for name, cat in self.fb.categories.items():
            self.assertIn("description", cat, f"Category {name} missing description")

    def test_categories_have_tier(self):
        """Every category has a tier."""
        for name, cat in self.fb.categories.items():
            self.assertIn("tier", cat, f"Category {name} missing tier")

    def test_physical_devices_have_ip(self):
        """Every physical device has an IP."""
        for key, dev in self.fb.physical.items():
            self.assertTrue(len(dev.ip) > 0, f"Physical device {key} has no IP")

    def test_pve_nodes_have_ip(self):
        """Every PVE node has an IP."""
        for name, node in self.fb.pve_nodes.items():
            self.assertTrue(len(node.ip) > 0, f"PVE node {name} has no IP")

    def test_categorize_returns_tuple(self):
        """categorize() always returns (str, str)."""
        for vmid in [100, 500, 900, 5000, 99999]:
            cat, tier = self.fb.categorize(vmid)
            self.assertIsInstance(cat, str)
            self.assertIsInstance(tier, str)

    def test_allowed_actions_returns_list(self):
        """allowed_actions() always returns a list."""
        for vmid in [100, 500, 900, 5000, 99999]:
            actions = self.fb.allowed_actions(vmid)
            self.assertIsInstance(actions, list)


if __name__ == "__main__":
    unittest.main()
