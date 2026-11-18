"""Owner contract for container-registry persistence and host resolution."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402

from freq.core import config, resolve  # noqa: E402
from freq.core.config import Container, ContainerVM  # noqa: E402
from freq.modules import serve  # noqa: E402


class TestContainerRegistryOwner(unittest.TestCase):
    """Freeze registry bytes and current-label resolution before relocation."""

    def _case_serializer_preserves_exact_mixed_registry_bytes(self):
        vms = {
            "arr": ContainerVM(vm_id=0, ip="10.0.0.31", label="arr", compose_path="/opt/arr"),
            200: ContainerVM(vm_id=200, ip="10.0.0.50", label="legacy"),
        }
        vms["arr"].containers["sonarr"] = Container(
            name="sonarr",
            vm_id=0,
            port=8989,
            image="lscr.io/sonarr",
            status="running",
            api_path="/api",
            auth_type="bearer",
            auth_header="Authorization",
            vault_key="sonarr-key",
        )
        vms[200].containers["nginx"] = Container(name="nginx", vm_id=200, port=80)
        expected = (
            "# FREQ Container Registry\n\n"
            "\n[vm.200]\n"
            'ip = "10.0.0.50"\n'
            'label = "legacy"\n'
            "\n[vm.200.containers.nginx]\n"
            'name = "nginx"\n'
            "port = 80\n"
            "\n[host.arr]\n"
            'ip = "10.0.0.31"\n'
            'compose_path = "/opt/arr"\n'
            "\n[host.arr.containers.sonarr]\n"
            'name = "sonarr"\n'
            'image = "lscr.io/sonarr"\n'
            'status = "running"\n'
            "port = 8989\n"
            'api_path = "/api"\n'
            'auth_type = "bearer"\n'
            'auth_header = "Authorization"\n'
            'vault_key = "sonarr-key"\n'
        )

        with tempfile.NamedTemporaryFile(delete=False) as output:
            path = output.name
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))

        serve._write_containers_toml(path, vms)

        self.assertEqual(Path(path).read_text(), expected)

    def _case_resolver_prefers_current_host_label_ip(self):
        vm = ContainerVM(vm_id=100, ip="10.0.0.99", label="arr")
        cfg = SimpleNamespace(hosts=[])

        with (
            mock.patch.object(serve, "load_config", return_value=cfg),
            mock.patch.object(config, "load_config", return_value=cfg),
            mock.patch.object(resolve, "resolve_host_ip", return_value="10.0.0.31") as resolver,
        ):
            result = serve._resolve_container_vm_ip(vm)

        self.assertEqual(result, "10.0.0.31")
        resolver.assert_called_once_with(cfg, "arr")

    def _case_serializer_propagates_final_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "missing", "containers.toml")

            with self.assertRaises(OSError):
                serve._write_containers_toml(path, {})

    def _case_unresolved_label_falls_back_to_registry_ip(self):
        vm = ContainerVM(vm_id=100, ip="10.0.0.99", label="missing")
        cfg = SimpleNamespace(hosts=[])

        with (
            mock.patch.object(serve, "load_config", return_value=cfg),
            mock.patch.object(config, "load_config", return_value=cfg),
            mock.patch.object(resolve, "resolve_host_ip", return_value=None) as resolver,
        ):
            result = serve._resolve_container_vm_ip(vm)

        self.assertEqual(result, "10.0.0.99")
        resolver.assert_called_once_with(cfg, "missing")

    def _case_resolver_exception_falls_back_to_registry_ip(self):
        vm = ContainerVM(vm_id=100, ip="10.0.0.99", label="broken")
        cfg = SimpleNamespace(hosts=[])

        with (
            mock.patch.object(serve, "load_config", return_value=cfg),
            mock.patch.object(config, "load_config", return_value=cfg),
            mock.patch.object(
                resolve,
                "resolve_host_ip",
                side_effect=RuntimeError("resolver unavailable"),
            ) as resolver,
        ):
            result = serve._resolve_container_vm_ip(vm)

        self.assertEqual(result, "10.0.0.99")
        resolver.assert_called_once_with(cfg, "broken")

    def _case_empty_label_uses_registry_ip_without_config_lookup(self):
        vm = ContainerVM(vm_id=100, ip="10.0.0.99", label="")

        with (
            mock.patch.object(serve, "load_config") as serve_load,
            mock.patch.object(config, "load_config") as config_load,
            mock.patch.object(resolve, "resolve_host_ip") as resolver,
        ):
            result = serve._resolve_container_vm_ip(vm)

        self.assertEqual(result, "10.0.0.99")
        serve_load.assert_not_called()
        config_load.assert_not_called()
        resolver.assert_not_called()


CONTAINER_REGISTRY_CASES = (
    "_case_serializer_preserves_exact_mixed_registry_bytes",
    "_case_serializer_propagates_final_write_failure",
    "_case_resolver_prefers_current_host_label_ip",
    "_case_unresolved_label_falls_back_to_registry_ip",
    "_case_resolver_exception_falls_back_to_registry_ip",
    "_case_empty_label_uses_registry_ip_without_config_lookup",
)


class TestContainerRegistryMatrix(unittest.TestCase):
    def test_container_registry_matrix(self):
        run_case_matrix(self, TestContainerRegistryOwner, CONTAINER_REGISTRY_CASES)


if __name__ == "__main__":
    unittest.main()
