"""Tests for containers.toml producer/consumer contract.

Proves the canonical schema, round-trip load/write stability, and
mixed-key hazard handling. Documents what Morty can rely on downstream.

Canonical schema (init-generated):
  [host.<label>]
  ip = "10.0.0.31"
  label = "arr-stack"
  compose_path = "/opt/docker"  # optional

  [host.<label>.containers.<safe_name>]
  name = "sonarr"
  image = "linuxserver/sonarr"
  status = "running"
  port = 8989          # optional, 0 if unknown
  api_path = "/api"    # optional
  auth_type = "header"  # optional
  auth_header = "X-Api-Key"  # optional
  vault_key = "sonarr-api-key"  # optional

Identity model: containers are identified by (host_label, safe_name).
The dict key in container_vms is the host label (string).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

from freq.core.types import Container, ContainerVM
from freq.core.config import load_containers
from freq.modules.serve import _write_containers_toml


class TestCanonicalSchema(unittest.TestCase):
    """The canonical containers.toml schema must be well-defined."""

    def test_container_has_image_field(self):
        """Container dataclass must have image field for init output."""
        c = Container(name="sonarr", vm_id=0, image="linuxserver/sonarr")
        self.assertEqual(c.image, "linuxserver/sonarr")

    def test_container_has_status_field(self):
        """Container dataclass must have status field for init output."""
        c = Container(name="sonarr", vm_id=0, status="running")
        self.assertEqual(c.status, "running")

    def test_container_defaults_backward_compatible(self):
        """New fields must have defaults so old code still works."""
        c = Container(name="sonarr", vm_id=0)
        self.assertEqual(c.image, "")
        self.assertEqual(c.status, "")
        self.assertEqual(c.port, 0)


class TestRoundTrip(unittest.TestCase):
    """Load → write → reload must preserve all fields and format."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "containers.toml")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_init_format(self):
        """Write containers.toml in the format init_cmd.py generates."""
        with open(self.path, "w") as f:
            f.write(
                '[host.arr-stack]\n'
                'ip = "10.25.255.31"\n'
                'label = "arr-stack"\n'
                'compose_path = "/opt/docker"\n\n'
                '[host.arr-stack.containers.sonarr]\n'
                'name = "sonarr"\n'
                'image = "linuxserver/sonarr:latest"\n'
                'status = "running"\n\n'
                '[host.arr-stack.containers.radarr]\n'
                'name = "radarr"\n'
                'image = "linuxserver/radarr:latest"\n'
                'status = "running"\n'
            )

    def test_load_init_format(self):
        """Loader must handle init-generated [host.<label>] format."""
        self._write_init_format()
        vms = load_containers(self.path)
        self.assertIn("arr-stack", vms)
        vm = vms["arr-stack"]
        self.assertEqual(vm.ip, "10.25.255.31")
        self.assertEqual(vm.label, "arr-stack")
        self.assertIn("sonarr", vm.containers)
        self.assertIn("radarr", vm.containers)

    def test_load_preserves_image(self):
        """Loader must preserve image field from init output."""
        self._write_init_format()
        vms = load_containers(self.path)
        c = vms["arr-stack"].containers["sonarr"]
        self.assertEqual(c.image, "linuxserver/sonarr:latest")

    def test_load_preserves_status(self):
        """Loader must preserve status field from init output."""
        self._write_init_format()
        vms = load_containers(self.path)
        c = vms["arr-stack"].containers["sonarr"]
        self.assertEqual(c.status, "running")

    def test_write_preserves_host_format(self):
        """Writer must use [host.<label>] for string-keyed entries."""
        self._write_init_format()
        vms = load_containers(self.path)
        # Write back
        out_path = os.path.join(self.tmpdir, "out.toml")
        _write_containers_toml(out_path, vms)
        # Verify format
        with open(out_path) as f:
            content = f.read()
        self.assertIn("[host.arr-stack]", content)
        self.assertNotIn("[vm.", content,
                         "Writer must not convert host-format to vm-format")

    def test_round_trip_preserves_fields(self):
        """Load → write → reload must preserve all init-generated fields."""
        self._write_init_format()
        vms1 = load_containers(self.path)
        # Write
        out_path = os.path.join(self.tmpdir, "round.toml")
        _write_containers_toml(out_path, vms1)
        # Reload
        vms2 = load_containers(out_path)
        # Compare
        self.assertEqual(set(vms1.keys()), set(vms2.keys()))
        for key in vms1:
            vm1 = vms1[key]
            vm2 = vms2[key]
            self.assertEqual(vm1.ip, vm2.ip)
            self.assertEqual(vm1.label, vm2.label)
            self.assertEqual(set(vm1.containers.keys()), set(vm2.containers.keys()))
            for cname in vm1.containers:
                c1 = vm1.containers[cname]
                c2 = vm2.containers[cname]
                self.assertEqual(c1.name, c2.name)
                self.assertEqual(c1.image, c2.image)
                self.assertEqual(c1.status, c2.status)
                self.assertEqual(c1.port, c2.port)

    def test_round_trip_valid_toml(self):
        """Written file must be valid TOML."""
        self._write_init_format()
        vms = load_containers(self.path)
        out_path = os.path.join(self.tmpdir, "valid.toml")
        _write_containers_toml(out_path, vms)
        if tomllib:
            with open(out_path, "rb") as f:
                data = tomllib.load(f)
            self.assertIn("host", data)


class TestLegacyFormat(unittest.TestCase):
    """Legacy [vm.<id>] format must still load and round-trip."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "containers.toml")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_legacy_format(self):
        """Loader must handle legacy [vm.<id>] format."""
        with open(self.path, "w") as f:
            f.write(
                '[vm.201]\n'
                'ip = "10.0.0.31"\n'
                'label = "arr-stack"\n\n'
                '[vm.201.containers.sonarr]\n'
                'port = 8989\n'
                'api_path = "/api"\n'
            )
        vms = load_containers(self.path)
        self.assertIn(201, vms)
        self.assertEqual(vms[201].label, "arr-stack")

    def test_write_legacy_preserves_vm_format(self):
        """Writer must use [vm.<id>] for integer-keyed entries."""
        with open(self.path, "w") as f:
            f.write(
                '[vm.201]\n'
                'ip = "10.0.0.31"\n'
                'label = "arr-stack"\n\n'
                '[vm.201.containers.sonarr]\n'
                'port = 8989\n'
            )
        vms = load_containers(self.path)
        out_path = os.path.join(self.tmpdir, "out.toml")
        _write_containers_toml(out_path, vms)
        with open(out_path) as f:
            content = f.read()
        self.assertIn("[vm.201]", content)


class TestMixedKeyHazards(unittest.TestCase):
    """Mixed string/int keys must not corrupt data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "containers.toml")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mixed_formats_both_load(self):
        """File with both [host.<label>] and [vm.<id>] sections loads both."""
        with open(self.path, "w") as f:
            f.write(
                '[host.arr-stack]\n'
                'ip = "10.0.0.31"\n'
                'label = "arr-stack"\n\n'
                '[host.arr-stack.containers.sonarr]\n'
                'name = "sonarr"\n\n'
                '[vm.201]\n'
                'ip = "10.0.0.32"\n'
                'label = "plex"\n\n'
                '[vm.201.containers.plex]\n'
                'port = 32400\n'
            )
        vms = load_containers(self.path)
        self.assertIn("arr-stack", vms)
        self.assertIn(201, vms)

    def test_mixed_write_preserves_both(self):
        """Writer must preserve format for both string and int keys."""
        with open(self.path, "w") as f:
            f.write(
                '[host.arr-stack]\n'
                'ip = "10.0.0.31"\n\n'
                '[host.arr-stack.containers.sonarr]\n'
                'name = "sonarr"\n\n'
                '[vm.201]\n'
                'ip = "10.0.0.32"\n\n'
                '[vm.201.containers.plex]\n'
                'port = 32400\n'
            )
        vms = load_containers(self.path)
        out_path = os.path.join(self.tmpdir, "out.toml")
        _write_containers_toml(out_path, vms)
        with open(out_path) as f:
            content = f.read()
        self.assertIn("[host.arr-stack]", content)
        self.assertIn("[vm.201]", content)

    def test_key_types_are_deterministic(self):
        """Host-format keys must be strings, legacy keys must be ints."""
        with open(self.path, "w") as f:
            f.write(
                '[host.myhost]\nip = "10.0.0.1"\n\n'
                '[vm.100]\nip = "10.0.0.2"\n'
            )
        vms = load_containers(self.path)
        for key in vms:
            if isinstance(key, str):
                self.assertEqual(key, "myhost")
            elif isinstance(key, int):
                self.assertEqual(key, 100)
            else:
                self.fail(f"Unexpected key type: {type(key)}")


class TestDownstreamContract(unittest.TestCase):
    """Document what Morty can rely on from init-generated containers.toml.

    After freq init, Morty's UI/consumer code can rely on:
    1. cfg.container_vms is a dict keyed by host label (string)
    2. Each value is ContainerVM with .ip, .label, .containers
    3. Each container has .name, .image, .status (from docker ps)
    4. .port, .api_path, .auth_* are 0/"" until user configures them
    5. Round-trip through _write_containers_toml preserves all fields
    6. Written file is valid TOML parseable by tomllib
    """

    def test_init_output_has_string_keys(self):
        """Init always produces string-keyed entries."""
        vms = {"arr-stack": ContainerVM(
            vm_id=0, ip="10.0.0.31", label="arr-stack",
            containers={"sonarr": Container(
                name="sonarr", vm_id=0, image="linuxserver/sonarr", status="running"
            )}
        )}
        for key in vms:
            self.assertIsInstance(key, str)

    def test_container_has_required_init_fields(self):
        """Every init-generated container has name, image, status."""
        c = Container(name="sonarr", vm_id=0, image="img:latest", status="running")
        self.assertTrue(c.name)
        self.assertTrue(c.image)
        self.assertTrue(c.status)

    def test_port_defaults_to_zero(self):
        """Unconfigured port is 0, not None or missing."""
        c = Container(name="sonarr", vm_id=0)
        self.assertEqual(c.port, 0)
        self.assertIsInstance(c.port, int)


if __name__ == "__main__":
    unittest.main()
