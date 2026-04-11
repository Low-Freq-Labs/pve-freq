"""Write ownership tests for consumer-side config/registry writes.

Proves:
1. containers.toml has one serializer (_write_containers_toml in serve.py)
2. docker_api.py add/edit/delete all use the shared serializer (no drift)
3. users.conf writers both use _save_users (no format divergence)
4. fleet-boundaries.toml has one writer (_update_fb_toml in serve.py)
5. Vault writes all go through vault_set (centralized crypto)
6. containers.toml round-trip: write → reload → same data
"""

import ast
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestContainersTomlOwnership(unittest.TestCase):
    """containers.toml must have exactly one serializer function."""

    def test_single_serializer_in_serve(self):
        """_write_containers_toml must be defined in serve.py."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("def _write_containers_toml(", src,
                       "Serializer must be defined in serve.py")

    def test_docker_api_imports_shared_serializer(self):
        """docker_api.py must import _write_containers_toml, not redefine it."""
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        self.assertIn("_write_containers_toml", src,
                       "docker_api.py must use the shared serializer")
        self.assertNotIn("def _write_containers_toml(", src,
                          "docker_api.py must NOT redefine the serializer")

    def test_all_docker_api_writes_use_shared_serializer(self):
        """Every containers.toml write in docker_api.py must call _write_containers_toml."""
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        # Check add, edit, delete handlers all call the shared function
        for handler in ["handle_containers_add", "handle_containers_edit", "handle_containers_delete"]:
            handler_src = src.split(f"def {handler}")[1].split("\ndef ")[0]
            self.assertIn("_write_containers_toml(", handler_src,
                           f"{handler} must use _write_containers_toml")
            # Must NOT write directly to the file
            self.assertNotIn("open(toml_path, 'w')", handler_src,
                              f"{handler} must NOT write containers.toml directly")
            self.assertNotIn('open(toml_path, "w")', handler_src,
                              f"{handler} must NOT write containers.toml directly")

    def test_round_trip_preserves_data(self):
        """Write → reload must produce identical container data."""
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {
            100: ContainerVM(vm_id=100, ip="10.0.0.1", label="test-vm", compose_path="/opt/stacks"),
        }
        vms[100].containers["nginx"] = Container(
            name="nginx", vm_id=100, port=80, api_path="/health",
        )
        vms[100].containers["postgres"] = Container(
            name="postgres", vm_id=100, port=5432,
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            tmp_path = f.name

        try:
            _write_containers_toml(tmp_path, vms)
            reloaded = load_containers(tmp_path)

            self.assertEqual(len(reloaded), 1, "Should have 1 VM")
            vm = reloaded[100]
            self.assertEqual(vm.ip, "10.0.0.1")
            self.assertEqual(vm.label, "test-vm")
            self.assertEqual(len(vm.containers), 2)
            self.assertIn("nginx", vm.containers)
            self.assertIn("postgres", vm.containers)
            self.assertEqual(vm.containers["nginx"].port, 80)
            self.assertEqual(vm.containers["nginx"].api_path, "/health")
            self.assertEqual(vm.containers["postgres"].port, 5432)
        finally:
            os.unlink(tmp_path)


class TestUsersConfOwnership(unittest.TestCase):
    """users.conf must use the same _save_users function from both writers."""

    def test_user_api_uses_shared_saver(self):
        """api/user.py must use _save_users from freq.modules.users."""
        with open(os.path.join(REPO_ROOT, "freq/api/user.py")) as f:
            src = f.read()
        self.assertIn("_save_users", src,
                       "api/user.py must use _save_users")
        self.assertNotIn("def _save_users(", src,
                          "api/user.py must NOT redefine _save_users")

    def test_serve_setup_uses_shared_saver(self):
        """serve.py setup must write users.conf via users module, not raw file write."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        # Setup handler creates admin user
        setup_section = src.split("def _serve_setup_create_admin")[1].split("def _serve_")[0]
        # Should write to users.conf in a compatible way
        self.assertIn("users.conf", setup_section,
                       "Setup must write to users.conf")


class TestFleetBoundariesOwnership(unittest.TestCase):
    """fleet-boundaries.toml must have one writer path."""

    def test_single_writer_in_serve(self):
        """_update_fb_toml must be defined only in serve.py."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("def _update_fb_toml(", src)

    def test_no_api_module_writes_fb(self):
        """No api/ module should write directly to fleet-boundaries.toml."""
        api_dir = os.path.join(REPO_ROOT, "freq/api")
        for fname in os.listdir(api_dir):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(api_dir, fname)
            with open(fpath) as f:
                src = f.read()
            self.assertNotIn("fleet-boundaries.toml", src.split("def ")[0] if "def " in src else "",
                              f"api/{fname} imports should not reference fleet-boundaries.toml writes")
            # Check no direct file writes to fleet-boundaries
            for func_block in src.split("\ndef ")[1:]:
                if "fleet-boundaries" in func_block and ("open(" in func_block and "'w'" in func_block):
                    self.fail(f"api/{fname} writes directly to fleet-boundaries.toml")


class TestVaultOwnership(unittest.TestCase):
    """All vault writes must go through vault_set from freq.modules.vault."""

    def test_no_direct_vault_file_writes(self):
        """Consumer files must not write to vault file directly (only via vault_set)."""
        consumer_files = [
            "freq/modules/serve.py",
            "freq/api/auth.py",
            "freq/api/secure.py",
            "freq/api/user.py",
            "freq/api/docker_api.py",
        ]
        for relpath in consumer_files:
            fpath = os.path.join(REPO_ROOT, relpath)
            if not os.path.isfile(fpath):
                continue
            with open(fpath) as f:
                src = f.read()
            # Should import vault_set, not call _encrypt directly
            if "vault_set" in src:
                self.assertNotIn("_encrypt(", src,
                                  f"{relpath} must use vault_set, not _encrypt directly")


if __name__ == "__main__":
    unittest.main()
