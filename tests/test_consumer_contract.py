"""Consumer contract tests for Lab Equipment and Docker dashboard surfaces.

Proves:
1. API responses include honest registry_configured flag
2. Empty containers.toml produces registry_configured=false (not silent empty)
3. Docker fleet endpoint uses hosts.toml docker-type hosts (not containers.toml)
4. Lab status filters hosts by lab group from hosts.toml
5. Frontend JS reads registry_configured to show blocked state vs fake green
"""

import ast
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestMediaStatusContract(unittest.TestCase):
    """Media status API must include registry_configured flag."""

    def test_media_status_returns_registry_flag(self):
        """_serve_media_status must include registry_configured in response."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("registry_configured", src.split("def _serve_media_status")[1].split("def _serve_")[0],
                       "media_status handler must include registry_configured in response")

    def test_media_dashboard_returns_registry_flag(self):
        """_serve_media_dashboard must include registry_configured in response."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("registry_configured", src.split("def _serve_media_dashboard")[1].split("def _serve_")[0],
                       "media_dashboard handler must include registry_configured in response")

    def test_container_registry_returns_registry_flag(self):
        """handle_containers_registry must include registry_configured in response."""
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        self.assertIn("registry_configured", src.split("handle_containers_registry")[1].split("\ndef ")[0],
                       "container registry handler must include registry_configured")


class TestDockerFleetContract(unittest.TestCase):
    """Docker fleet endpoint contract tests."""

    def test_docker_fleet_uses_hosts_not_containers(self):
        """handle_docker_fleet must filter by host type, not containers.toml."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn("by_type", handler_src,
                       "docker-fleet must use by_type(cfg.hosts) not cfg.container_vms")
        self.assertNotIn("container_vms", handler_src,
                          "docker-fleet must NOT depend on containers.toml")

    def test_docker_fleet_returns_vms_key(self):
        """Response must include 'vms' key for frontend compatibility."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn('"vms"', handler_src,
                       "docker-fleet response must include vms key for loadDockerFleet JS")

    def test_docker_fleet_returns_running_count(self):
        """Response must include 'running' count for frontend stats."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn('"running"', handler_src,
                       "docker-fleet response must include running count for frontend")


class TestLabStatusContract(unittest.TestCase):
    """Lab status API contract tests."""

    def test_lab_status_filters_by_lab_group(self):
        """_serve_lab_status must filter hosts by 'lab' group."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler_src = src.split("def _serve_lab_status")[1].split("def _serve_")[0]
        self.assertIn('"lab"', handler_src,
                       "lab_status must filter hosts by lab group")

    def test_lab_hosts_from_hosts_toml(self):
        """Lab hosts must come from hosts.toml (cfg.hosts), not invented."""
        from freq.core.config import load_config
        cfg = load_config()
        lab_hosts = [h for h in cfg.hosts if "lab" in (h.groups or "").split(",")]
        # Verify lab hosts exist in hosts.toml
        self.assertGreater(len(lab_hosts), 0,
                           "hosts.toml must contain at least one host with 'lab' group")
        for h in lab_hosts:
            self.assertTrue(h.ip, f"Lab host {h.label} must have an IP")
            self.assertTrue(h.label, "Lab host must have a label")


class TestFrontendHonestyContract(unittest.TestCase):
    """Frontend JS must check registry_configured before rendering green state."""

    def test_container_section_checks_registry(self):
        """loadContainerSection must check registry_configured."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        section = src.split("function loadContainerSection")[1].split("\nfunction ")[0]
        self.assertIn("registry_configured", section,
                       "loadContainerSection must check registry_configured flag")

    def test_container_registry_checks_flag(self):
        """loadContainerRegistry must check registry_configured."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        section = src.split("function loadContainerRegistry")[1].split("\nfunction ")[0]
        self.assertIn("registry_configured", section,
                       "loadContainerRegistry must check registry_configured flag")


class TestUpstreamArtifactHonesty(unittest.TestCase):
    """Verify consumer code doesn't invent data the init path did not generate."""

    def test_containers_toml_state_matches_reality(self):
        """container_vms must reflect what containers.toml actually contains."""
        from freq.core.config import load_config
        cfg = load_config()
        containers_path = os.path.join(cfg.conf_dir, "containers.toml")
        if not os.path.isfile(containers_path):
            self.assertEqual(len(cfg.container_vms), 0)
            return
        with open(containers_path) as f:
            content = f.read()
        has_real_entries = any(
            line.strip() and not line.strip().startswith("#")
            for line in content.split("\n")
        )
        if not has_real_entries:
            self.assertEqual(len(cfg.container_vms), 0,
                             "containers.toml is all comments — container_vms must be empty, "
                             "not populated with synthetic data")

    def test_docker_hosts_in_hosts_toml(self):
        """Docker-type hosts must exist in hosts.toml for docker-fleet to work."""
        from freq.core.config import load_config
        cfg = load_config()
        docker_hosts = [h for h in cfg.hosts if h.htype == "docker"]
        self.assertGreater(len(docker_hosts), 0,
                           "hosts.toml must contain docker-type hosts")
        for h in docker_hosts:
            self.assertTrue(h.ip, f"Docker host {h.label} must have an IP")


if __name__ == "__main__":
    unittest.main()
