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

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

RICK_DIR = str(Path(__file__).parent.parent)
CONF_DIR = os.path.join(RICK_DIR, "conf")


class TestTOMLLoading(unittest.TestCase):
    """Test TOML loading via tomllib (Python 3.11+)."""

    def test_load_simple_file(self):
        from freq.core.config import load_toml
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[freq]\n")
            f.write('version = "1.0"\n')
            f.write("debug = true\n")
            f.write("cores = 4\n")
            path = f.name
        try:
            data = load_toml(path)
            self.assertEqual(data["freq"]["version"], "1.0")
            self.assertTrue(data["freq"]["debug"])
            self.assertEqual(data["freq"]["cores"], 4)
        finally:
            os.unlink(path)

    def test_load_nested_sections(self):
        from freq.core.config import load_toml
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[vm.defaults]\n")
            f.write("cores = 2\n")
            f.write("ram = 2048\n")
            path = f.name
        try:
            data = load_toml(path)
            self.assertEqual(data["vm"]["defaults"]["cores"], 2)
            self.assertEqual(data["vm"]["defaults"]["ram"], 2048)
        finally:
            os.unlink(path)

    def test_load_nonexistent_file(self):
        from freq.core.config import load_toml
        data = load_toml("/nonexistent/file.toml")
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

    def test_load_containers_from_config(self):
        """Load a representative config without canonical local state."""
        from freq.core.config import load_containers

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "containers.toml"
            path.write_text(
                '[vm.101]\n'
                'ip = "10.0.0.10"\n'
                'label = "media-server"\n'
                'compose_path = "/opt/docker/compose.yml"\n'
            )
            containers = load_containers(str(path))

        self.assertEqual(tuple(containers), (101,))
        self.assertEqual(containers[101].ip, "10.0.0.10")
        self.assertEqual(containers[101].label, "media-server")


class TestDistroLoading(unittest.TestCase):
    """Test cloud image definition loading."""

    def test_load_distros_empty(self):
        """Empty distros.toml returns empty list."""
        from freq.core.config import load_distros
        distros = load_distros("/nonexistent/distros.toml")
        self.assertEqual(distros, [])

    def test_load_distros_from_config(self):
        """Load a representative distro config without repository-local state."""
        from freq.core.config import load_distros

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "distros.toml"
            path.write_text(
                '[distro.debian-12]\n'
                'name = "Debian 12 Bookworm"\n'
                'url = "https://example.invalid/debian-12.qcow2"\n'
                'filename = "debian-12.qcow2"\n'
            )
            distros = load_distros(str(path))

        self.assertEqual(len(distros), 1)
        self.assertEqual(distros[0].key, "debian-12")
        self.assertEqual(distros[0].name, "Debian 12 Bookworm")
        self.assertEqual(distros[0].url, "https://example.invalid/debian-12.qcow2")


class TestVLANLoading(unittest.TestCase):
    """Test VLAN definition loading."""

    def test_load_vlans_from_config(self):
        """Load representative VLANs without canonical local state."""
        from freq.core.config import load_vlans

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vlans.toml"
            path.write_text(
                '[vlan.management]\n'
                'id = 100\n'
                'name = "MANAGEMENT"\n'
                'subnet = "10.0.0.0/24"\n'
                'prefix = "10.0.0"\n'
                'gateway = "10.0.0.1"\n'
            )
            vlans = load_vlans(str(path))

        self.assertEqual(len(vlans), 1)
        self.assertEqual(vlans[0].id, 100)
        self.assertEqual(vlans[0].name, "MANAGEMENT")
        self.assertEqual(vlans[0].subnet, "10.0.0.0/24")

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

    def _case_check_python(self):
        from freq.core.doctor import _check_python
        result = _check_python(self.cfg)
        self.assertEqual(result, 0)  # We're running on 3.13

    def _case_check_platform(self):
        from freq.core.doctor import _check_platform
        result = _check_platform(self.cfg)
        self.assertEqual(result, 0)  # We're on Linux

    def _case_check_prerequisites(self):
        from freq.core.doctor import _check_prerequisites
        result = _check_prerequisites(self.cfg)
        self.assertIn(result, [0, 2])  # 0 = all found, 2 = optional missing

    def _case_check_install_dir(self):
        from freq.core.doctor import _check_install_dir
        result = _check_install_dir(self.cfg)
        self.assertIn(result, [0, 1, 2])  # 0 = ok, 1/2 = dir missing (CI)

    def _case_check_config(self):
        from freq.core.doctor import _check_config
        result = _check_config(self.cfg)
        # 0 = config found, 2 = config missing (CI without freq.toml)
        self.assertIn(result, [0, 2])

    def _case_check_ssh_binary(self):
        from freq.core.doctor import _check_ssh_binary
        result = _check_ssh_binary(self.cfg)
        self.assertEqual(result, 0)

    def _case_check_ssh_key(self):
        from freq.core.doctor import _check_ssh_key
        result = _check_ssh_key(self.cfg)
        self.assertIn(result, [0, 2])  # 0 = found, 2 = not found

    def _case_check_hosts(self):
        from freq.core.doctor import _check_hosts
        result = _check_hosts(self.cfg)
        # 0 = hosts found, 2 = hosts.conf missing (CI)
        self.assertIn(result, [0, 2])

    def _case_check_hosts_allows_probe_only_firewall(self):
        from freq.core.config import FreqConfig
        from freq.core.doctor import _check_hosts
        from freq.core.types import FleetBoundaries, Host, PhysicalDevice

        cfg = FreqConfig()
        cfg.hosts = [
            Host(
                ip="10.0.0.1",
                label="firewall",
                htype="pfsense",
                managed=False,
            )
        ]
        cfg.fleet_boundaries = FleetBoundaries(
            physical={
                "firewall": PhysicalDevice(
                    key="firewall",
                    ip="10.0.0.1",
                    label="firewall",
                    device_type="pfsense",
                    tier="probe",
                    scope="core",
                )
            }
        )

        self.assertEqual(_check_hosts(cfg), 0)

    def _case_check_hosts_rejects_unmanaged_core_switch(self):
        from freq.core.config import FreqConfig
        from freq.core.doctor import _check_hosts
        from freq.core.types import FleetBoundaries, Host, PhysicalDevice

        cfg = FreqConfig()
        cfg.hosts = [
            Host(
                ip="10.0.0.5",
                label="switch",
                htype="switch",
                managed=False,
            )
        ]
        cfg.fleet_boundaries = FleetBoundaries(
            physical={
                "switch": PhysicalDevice(
                    key="switch",
                    ip="10.0.0.5",
                    label="switch",
                    device_type="switch",
                    tier="probe",
                    scope="core",
                )
            }
        )

        self.assertEqual(_check_hosts(cfg), 1)

    def _case_check_hosts_validity(self):
        from freq.core.doctor import _check_hosts_validity
        result = _check_hosts_validity(self.cfg)
        self.assertEqual(result, 0)

    def _case_check_vlans(self):
        from freq.core.doctor import _check_vlans
        result = _check_vlans(self.cfg)
        self.assertEqual(result, 0)

    def _case_check_distros(self):
        from freq.core.doctor import _check_distros
        result = _check_distros(self.cfg)
        self.assertEqual(result, 0)

    def _case_check_personality(self):
        from freq.core.doctor import _check_personality
        result = _check_personality(self.cfg)
        # 0 = personality dir found, 2 = missing (CI without conf/personality/)
        self.assertIn(result, [0, 2])


DOCTOR_CHECK_CASES = (
    "_case_check_python",
    "_case_check_platform",
    "_case_check_prerequisites",
    "_case_check_install_dir",
    "_case_check_config",
    "_case_check_ssh_binary",
    "_case_check_ssh_key",
    "_case_check_hosts",
    "_case_check_hosts_allows_probe_only_firewall",
    "_case_check_hosts_rejects_unmanaged_core_switch",
    "_case_check_hosts_validity",
    "_case_check_vlans",
    "_case_check_distros",
    "_case_check_personality",
)


class TestDoctorChecksMatrix(unittest.TestCase):
    def test_doctor_checks_matrix(self):
        self.assertEqual(len(DOCTOR_CHECK_CASES), 14)
        run_case_matrix(self, TestDoctorChecks, DOCTOR_CHECK_CASES)

class TestCompatModule(unittest.TestCase):
    """Test Python version compatibility check."""

    def test_current_version_ok(self):
        from freq.core.compat import check_python
        result = check_python()
        self.assertIsNone(result)

    def test_min_python_constant(self):
        from freq.core.compat import MIN_PYTHON
        self.assertEqual(MIN_PYTHON, (3, 11))


if __name__ == "__main__":
    unittest.main()
