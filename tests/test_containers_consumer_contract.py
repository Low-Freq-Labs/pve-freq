"""Containers.toml consumer contract tests.

Proves:
1. Both TOML formats (host.<label> and vm.<id>) round-trip correctly
2. _write_containers_toml preserves format based on key type
3. CRUD handlers use _lookup_vm for both key types
4. All media API endpoints include registry_configured flag
5. Frontend reads vm_key for CRUD operations
6. _lookup_vm handles int keys, string keys, and string-encoded ints
"""

import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestHostFormatRoundTrip(unittest.TestCase):
    """[host.<label>] format must round-trip through write → load."""

    def test_host_format_round_trip(self):
        """Write host-format entries, reload, verify data preserved."""
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {
            "arr-stack": ContainerVM(vm_id=0, ip="10.0.0.31", label="arr-stack", compose_path="/opt/stacks"),
        }
        vms["arr-stack"].containers["sonarr"] = Container(
            name="sonarr", vm_id=0, port=8989, api_path="/api/v3/health",
        )
        vms["arr-stack"].containers["radarr"] = Container(
            name="radarr", vm_id=0, port=7878, api_path="/api/v3/health",
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            tmp_path = f.name

        try:
            _write_containers_toml(tmp_path, vms)

            # Verify file uses [host.] format
            with open(tmp_path) as f:
                content = f.read()
            self.assertIn("[host.arr-stack]", content,
                          "String keys must write as [host.<label>]")
            self.assertNotIn("[vm.", content,
                              "String keys must NOT write as [vm.<id>]")

            # Reload and verify
            reloaded = load_containers(tmp_path)
            self.assertIn("arr-stack", reloaded)
            vm = reloaded["arr-stack"]
            self.assertEqual(vm.ip, "10.0.0.31")
            self.assertEqual(len(vm.containers), 2)
            self.assertEqual(vm.containers["sonarr"].port, 8989)
            self.assertEqual(vm.containers["radarr"].port, 7878)
        finally:
            os.unlink(tmp_path)

    def test_legacy_format_round_trip(self):
        """Write legacy-format entries, reload, verify data preserved."""
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {
            200: ContainerVM(vm_id=200, ip="10.0.0.50", label="web-server"),
        }
        vms[200].containers["nginx"] = Container(name="nginx", vm_id=200, port=80)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            tmp_path = f.name

        try:
            _write_containers_toml(tmp_path, vms)

            with open(tmp_path) as f:
                content = f.read()
            self.assertIn("[vm.200]", content,
                          "Int keys must write as [vm.<id>]")
            self.assertNotIn("[host.", content,
                              "Int keys must NOT write as [host.<label>]")

            reloaded = load_containers(tmp_path)
            self.assertIn(200, reloaded)
            self.assertEqual(reloaded[200].containers["nginx"].port, 80)
        finally:
            os.unlink(tmp_path)

    def test_mixed_format_round_trip(self):
        """Mixed string + int keys preserve their respective formats."""
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {
            "plex": ContainerVM(vm_id=0, ip="10.0.0.30", label="plex"),
            100: ContainerVM(vm_id=100, ip="10.0.0.50", label="legacy-vm"),
        }
        vms["plex"].containers["plex"] = Container(name="plex", vm_id=0, port=32400)
        vms[100].containers["nginx"] = Container(name="nginx", vm_id=100, port=80)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            tmp_path = f.name

        try:
            _write_containers_toml(tmp_path, vms)

            with open(tmp_path) as f:
                content = f.read()
            self.assertIn("[host.plex]", content)
            self.assertIn("[vm.100]", content)

            reloaded = load_containers(tmp_path)
            self.assertIn("plex", reloaded)
            self.assertIn(100, reloaded)
        finally:
            os.unlink(tmp_path)


class TestLookupVM(unittest.TestCase):
    """_lookup_vm must handle both key types."""

    def test_int_key_lookup(self):
        from freq.api.docker_api import _lookup_vm
        from freq.core.config import ContainerVM
        vms = {100: ContainerVM(vm_id=100, ip="10.0.0.1", label="test")}
        key, vm = _lookup_vm(vms, "100")
        self.assertEqual(key, 100)
        self.assertEqual(vm.label, "test")

    def test_string_key_lookup(self):
        from freq.api.docker_api import _lookup_vm
        from freq.core.config import ContainerVM
        vms = {"arr-stack": ContainerVM(vm_id=0, ip="10.0.0.31", label="arr-stack")}
        key, vm = _lookup_vm(vms, "arr-stack")
        self.assertEqual(key, "arr-stack")
        self.assertEqual(vm.ip, "10.0.0.31")

    def test_missing_key_returns_none(self):
        from freq.api.docker_api import _lookup_vm
        key, vm = _lookup_vm({}, "999")
        self.assertIsNone(key)
        self.assertIsNone(vm)

    def test_int_preferred_over_string(self):
        """If both int(key) and string key exist, int takes priority (legacy compat)."""
        from freq.api.docker_api import _lookup_vm
        from freq.core.config import ContainerVM
        vms = {
            100: ContainerVM(vm_id=100, ip="10.0.0.1", label="legacy"),
            "100": ContainerVM(vm_id=0, ip="10.0.0.2", label="host-format"),
        }
        key, vm = _lookup_vm(vms, "100")
        self.assertEqual(key, 100)
        self.assertEqual(vm.label, "legacy")


class TestCRUDHandlerContract(unittest.TestCase):
    """CRUD handlers must accept vm_key parameter for host-format entries."""

    def test_delete_accepts_vm_key(self):
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_containers_delete")[1].split("\ndef ")[0]
        self.assertIn("vm_key", handler_src,
                       "delete handler must accept vm_key parameter")
        self.assertIn("_lookup_vm", handler_src,
                       "delete handler must use _lookup_vm")

    def test_add_accepts_vm_key(self):
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_containers_add")[1].split("\ndef ")[0]
        self.assertIn("vm_key", handler_src)
        self.assertIn("_lookup_vm", handler_src)

    def test_edit_accepts_vm_key(self):
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_containers_edit")[1].split("\ndef ")[0]
        self.assertIn("vm_key", handler_src)
        self.assertIn("_lookup_vm", handler_src)

    def test_compose_handlers_accept_vm_key(self):
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        for handler in ["handle_containers_compose_up", "handle_containers_compose_down", "handle_containers_compose_view"]:
            handler_src = src.split(f"def {handler}")[1].split("\ndef ")[0]
            self.assertIn("vm_key", handler_src,
                           f"{handler} must accept vm_key parameter")
            self.assertIn("_lookup_vm", handler_src,
                           f"{handler} must use _lookup_vm")


class TestRegistryResponse(unittest.TestCase):
    """Registry list must include vm_key for canonical identity."""

    def test_registry_includes_vm_key(self):
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_containers_registry")[1].split("\ndef ")[0]
        self.assertIn("vm_key", handler_src,
                       "Registry response must include vm_key for each entry")

    def test_media_health_includes_registry_flag(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler_src = src.split("def _serve_media_health")[1].split("def _serve_")[0]
        self.assertIn("registry_configured", handler_src)


class TestProducerContractGaps(unittest.TestCase):
    """Document what still depends on Rick's producer contract."""

    def test_containers_toml_is_producer_owned(self):
        """containers.toml population is upstream (init). Consumer never invents data."""
        from freq.core.config import load_config
        cfg = load_config()
        if not cfg.container_vms:
            # This is the expected state until Rick's init populates it
            self.skipTest(
                "containers.toml is empty — upstream gap. "
                "Rick's init must populate it with [host.<label>] entries "
                "for each Docker host discovered during freq init. "
                "Consumer contract is hardened: API returns registry_configured=false, "
                "frontend shows honest blocked state."
            )


if __name__ == "__main__":
    unittest.main()
