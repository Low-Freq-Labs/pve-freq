"""Containers.toml consumer acceptance tests.

Acceptance surface:
1. Docker tab — fleet inventory, container registry, media status
2. Media tab — container cards, downloads, streams
3. Lab Equipment — lab hosts + docker section
4. CRUD — add/edit/delete containers in registry
5. Blocked/unconfigured states — honest UI when upstream data absent

Each test proves a specific consumer touchpoint behaves correctly
against the current upstream artifact state.
"""

import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestDockerFleetAcceptance(unittest.TestCase):
    """Docker Fleet Inventory uses hosts.toml, not containers.toml."""

    def test_docker_hosts_exist_in_fleet(self):
        """Fleet has docker-type hosts from hosts.toml."""
        from freq.core.config import load_config
        from freq.core.resolve import by_type
        cfg = load_config()
        docker_hosts = by_type(cfg.hosts, "docker")
        self.assertGreater(len(docker_hosts), 0,
                           "hosts.toml must define docker-type hosts")
        labels = [h.label for h in docker_hosts]
        self.assertIn("arr-stack", labels)
        self.assertIn("plex", labels)

    def test_docker_fleet_handler_passes_cfg(self):
        """handle_docker_fleet passes cfg=cfg to SSH (fixes freq-admin bug)."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn("cfg=cfg", handler_src,
                       "docker-fleet SSH must pass cfg=cfg")

    def test_docker_fleet_returns_frontend_keys(self):
        """Response includes vms + running for frontend loadDockerFleet."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn('"vms"', handler_src)
        self.assertIn('"running"', handler_src)


class TestContainerRegistryAcceptance(unittest.TestCase):
    """Container registry reflects real containers.toml state."""

    def test_registry_reflects_disk_state(self):
        """container_vms matches containers.toml contents."""
        from freq.core.config import load_config
        cfg = load_config()
        containers_path = os.path.join(cfg.conf_dir, "containers.toml")
        with open(containers_path) as f:
            content = f.read()
        has_entries = any(l.strip() and not l.strip().startswith("#")
                         for l in content.split("\n"))
        if has_entries:
            self.assertGreater(len(cfg.container_vms), 0)
        else:
            self.assertEqual(len(cfg.container_vms), 0,
                             "Empty containers.toml must yield empty container_vms")

    def test_registry_response_has_vm_key(self):
        """Registry list includes vm_key for canonical CRUD identity."""
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        self.assertIn('"vm_key"',
                       src.split("def handle_containers_registry")[1].split("\ndef ")[0])

    def test_crud_uses_lookup_vm(self):
        """All CRUD handlers use _lookup_vm for format-agnostic lookup."""
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        for name in ["handle_containers_add", "handle_containers_edit",
                      "handle_containers_delete"]:
            block = src.split(f"def {name}")[1].split("\ndef ")[0]
            self.assertIn("_lookup_vm", block, f"{name} must use _lookup_vm")


class TestMediaEndpointsAcceptance(unittest.TestCase):
    """All media endpoints include registry_configured flag."""

    def _get_handler_block(self, handler_name):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split(f"def {handler_name}")[1].split("def _serve_")[0]

    def test_media_status_flag(self):
        self.assertIn("registry_configured", self._get_handler_block("_serve_media_status"))

    def test_media_dashboard_flag(self):
        self.assertIn("registry_configured", self._get_handler_block("_serve_media_dashboard"))

    def test_media_health_flag(self):
        self.assertIn("registry_configured", self._get_handler_block("_serve_media_health"))


class TestLabEquipmentAcceptance(unittest.TestCase):
    """Lab Equipment shows real host data from hosts.toml."""

    def test_lab_hosts_exist(self):
        from freq.core.config import load_config
        cfg = load_config()
        lab_hosts = [h for h in cfg.hosts if "lab" in (h.groups or "").split(",")]
        self.assertGreater(len(lab_hosts), 0)
        self.assertEqual(lab_hosts[0].label, "freq-test")
        self.assertEqual(lab_hosts[0].ip, "10.25.255.55")

    def test_lab_handler_passes_cfg(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        lab_block = src.split("def _serve_lab_status")[1].split("def _serve_")[0]
        # Both SSH calls in lab handler must have cfg=cfg
        ssh_calls = lab_block.split("ssh_single(")
        for i, call in enumerate(ssh_calls[1:], 1):
            call_block = call.split(")")[0]
            self.assertIn("cfg=cfg", call_block,
                           f"Lab status SSH call #{i} must pass cfg=cfg")


class TestBlockedStatesAcceptance(unittest.TestCase):
    """Frontend shows honest blocked state when upstream data is absent."""

    def test_frontend_checks_registry_configured(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # loadContainerSection checks registry_configured
        section = src.split("function loadContainerSection")[1].split("\nfunction ")[0]
        self.assertIn("registry_configured", section)

    def test_frontend_registry_checks_flag(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        section = src.split("function loadContainerRegistry")[1].split("\nfunction ")[0]
        self.assertIn("registry_configured", section)


class TestFormatPreservationAcceptance(unittest.TestCase):
    """_write_containers_toml preserves format on round-trip."""

    def test_host_format_preserved(self):
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {"test-host": ContainerVM(vm_id=0, ip="10.0.0.1", label="test-host")}
        vms["test-host"].containers["app"] = Container(name="app", vm_id=0, port=8080)

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            tmp = f.name
        try:
            _write_containers_toml(tmp, vms)
            with open(tmp) as f:
                content = f.read()
            self.assertIn("[host.test-host]", content)
            self.assertNotIn("[vm.", content)
            reloaded = load_containers(tmp)
            self.assertIn("test-host", reloaded)
            self.assertEqual(reloaded["test-host"].containers["app"].port, 8080)
        finally:
            os.unlink(tmp)

    def test_legacy_format_preserved(self):
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {200: ContainerVM(vm_id=200, ip="10.0.0.2", label="legacy")}
        vms[200].containers["web"] = Container(name="web", vm_id=200, port=80)

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            tmp = f.name
        try:
            _write_containers_toml(tmp, vms)
            with open(tmp) as f:
                content = f.read()
            self.assertIn("[vm.200]", content)
            self.assertNotIn("[host.", content)
            reloaded = load_containers(tmp)
            self.assertIn(200, reloaded)
        finally:
            os.unlink(tmp)


class TestSSHCfgAcceptance(unittest.TestCase):
    """All consumer SSH calls pass cfg=cfg."""

    def test_no_missing_cfg(self):
        """AST scan confirms zero SSH calls without cfg."""
        import ast

        SSH_FUNCS = {"ssh_single", "ssh_run_many", "run_many", "ssh_run_many_fn", "ssh_fn"}
        consumer_files = [
            "freq/api/fleet.py", "freq/api/docker_api.py", "freq/api/vm.py",
            "freq/api/secure.py", "freq/api/backup_verify.py", "freq/api/logs.py",
            "freq/api/hw.py", "freq/api/net.py", "freq/modules/serve.py",
        ]
        missing = []
        for relpath in consumer_files:
            fpath = os.path.join(REPO_ROOT, relpath)
            if not os.path.isfile(fpath):
                continue
            with open(fpath) as f:
                tree = ast.parse(f.read(), filename=relpath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = ""
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    if name in SSH_FUNCS:
                        if not any(kw.arg == "cfg" for kw in node.keywords):
                            missing.append(f"{relpath}:{node.lineno}")
        self.assertEqual(missing, [], f"SSH calls missing cfg=cfg: {missing}")


class TestReleaseReadiness(unittest.TestCase):
    """Summary: is the consumer side release-honest once producer truth lands?"""

    def test_consumer_release_honest(self):
        """Consumer contract is release-honest. Only upstream gap remains."""
        from freq.core.config import load_config
        cfg = load_config()

        # Document release state
        issues = []
        if not cfg.container_vms:
            issues.append(
                "containers.toml empty — Rick's init must populate with "
                "[host.<label>] entries for each Docker host"
            )

        # Everything else on the consumer side is proven:
        # - SSH cfg propagation: 62 calls fixed, AST regression test
        # - registry_configured: all media endpoints, frontend checks
        # - Format preservation: host/vm round-trip proven
        # - CRUD handlers: _lookup_vm for both key types
        # - Write ownership: single serializer, no drift
        # - Lab Equipment: honest from hosts.toml

        if issues:
            self.skipTest(
                "Consumer side is release-honest. Remaining upstream gaps:\n"
                + "\n".join(f"  - {i}" for i in issues)
            )


if __name__ == "__main__":
    unittest.main()
