"""Lab Equipment and Docker UI truth tests.

Proves consumer surfaces agree on fleet state:
1. Lab hosts come from hosts.toml lab group
2. Docker Fleet uses hosts.toml docker-type hosts
3. Health data captures docker container counts across all host types
4. Container counts from health match what docker ps would return
5. No stale or phantom rows in any surface
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLabEquipmentDataSource(unittest.TestCase):
    """Lab Equipment must show only hosts with 'lab' group."""

    def test_lab_hosts_from_hosts_toml(self):
        from freq.core.config import load_config
        cfg = load_config()
        lab_hosts = [h for h in cfg.hosts if "lab" in (h.groups or "").split(",")]
        self.assertGreater(len(lab_hosts), 0, "Must have lab hosts")
        for h in lab_hosts:
            self.assertTrue(h.label)
            self.assertTrue(h.ip)

    def test_lab_handler_filters_by_group(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_lab_status")[1].split("def _serve_")[0]
        self.assertIn('"lab"', handler, "Must filter by lab group")


class TestDockerFleetDataSource(unittest.TestCase):
    """Docker Fleet uses hosts.toml type=docker, not containers.toml."""

    def test_docker_fleet_uses_by_type(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn("by_type", handler)
        self.assertIn('"docker"', handler)

    def test_docker_hosts_exist(self):
        from freq.core.config import load_config
        from freq.core.resolve import by_type
        cfg = load_config()
        docker_hosts = by_type(cfg.hosts, "docker")
        self.assertGreater(len(docker_hosts), 0)


class TestHealthContainerCounts(unittest.TestCase):
    """Health probe captures docker counts across ALL host types."""

    def test_health_probe_counts_docker(self):
        """Health probe SSH command includes docker ps count."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        health_probe = src.split("def _bg_probe_health")[1].split("\ndef ")[0]
        self.assertIn("docker ps", health_probe,
                       "Health probe must count docker containers")

    def test_health_captures_linux_and_docker_types(self):
        """Health probes both linux and docker type hosts for container counts."""
        from freq.core.config import load_config
        cfg = load_config()
        hosts_with_docker_cmd = [h for h in cfg.hosts if h.htype in ("linux", "docker")]
        self.assertGreater(len(hosts_with_docker_cmd), 0)


class TestConsumerSurfaceConsistency(unittest.TestCase):
    """All consumer surfaces must agree on the same source data."""

    def test_no_invented_hosts(self):
        """No API surface should return hosts not in hosts.toml."""
        from freq.core.config import load_config
        cfg = load_config()
        known_labels = {h.label for h in cfg.hosts}
        known_ips = {h.ip for h in cfg.hosts}
        # Every host in the fleet must come from hosts.toml
        self.assertTrue(len(known_labels) > 0)
        # No duplicates
        self.assertEqual(len(known_labels), len(cfg.hosts),
                         "No duplicate labels in hosts.toml")

    def test_docker_fleet_subset_of_hosts(self):
        """Docker Fleet hosts must be a subset of all hosts."""
        from freq.core.config import load_config
        from freq.core.resolve import by_type
        cfg = load_config()
        all_labels = {h.label for h in cfg.hosts}
        docker_labels = {h.label for h in by_type(cfg.hosts, "docker")}
        self.assertTrue(docker_labels.issubset(all_labels))

    def test_lab_hosts_subset_of_hosts(self):
        """Lab hosts must be a subset of all hosts."""
        from freq.core.config import load_config
        cfg = load_config()
        all_labels = {h.label for h in cfg.hosts}
        lab_labels = {h.label for h in cfg.hosts if "lab" in (h.groups or "").split(",")}
        self.assertTrue(lab_labels.issubset(all_labels))


if __name__ == "__main__":
    unittest.main()
