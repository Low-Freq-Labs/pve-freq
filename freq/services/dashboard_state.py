"""Single-owner runtime state for dashboard probes and API consumers."""

import collections
import threading
import time

server_start_time = time.monotonic()

background_cache = {
    "infra_quick": None,
    "health": None,
    "update": None,
    "fleet_overview": None,
    "hosts_sync": None,
    "pve_nodes": None,
    "vm_tags": None,
}
background_cache_timestamps = {
    "infra_quick": 0,
    "health": 0,
    "update": 0,
    "fleet_overview": 0,
    "hosts_sync": 0,
    "pve_nodes": 0,
    "vm_tags": 0,
}
background_cache_errors = {}
background_cache_from_disk = set()
background_cache_lock = threading.Lock()

activity_feed: collections.deque = collections.deque(maxlen=200)
activity_lock = threading.Lock()


def build_config_projection(cfg, discovered_nodes, kill_chain):
    """Build the authenticated dashboard config payload without transport."""
    return {
        "version": cfg.version,
        "brand": cfg.brand,
        "build": cfg.build,
        "ssh_account": cfg.ssh_service_account,
        "ssh_timeout": cfg.ssh_connect_timeout,
        "ssh_parallel": cfg.ssh_max_parallel,
        "pve_nodes": cfg.pve_nodes,
        "cluster": cfg.cluster_name,
        "timezone": cfg.timezone,
        "truenas_ip": cfg.truenas_ip,
        "pfsense_ip": cfg.pfsense_ip,
        "install_dir": cfg.install_dir,
        "hosts_count": len(cfg.hosts),
        "vlans_count": len(cfg.vlans),
        "distros_count": len(cfg.distros),
        "protected_vmids": cfg.protected_vmids,
        "pve_nodes_discovered": [n.get("name", "") for n in discovered_nodes],
        "kill_chain": kill_chain
        or ["Operator", "VPN", "Firewall", "Switch", "Network", "Target"],
    }


def build_distro_catalog(distros):
    """Project configured distro records for authenticated dashboard transport."""
    return [
        {
            "key": distro.key,
            "name": distro.name,
            "family": distro.family,
            "tier": distro.tier,
            "url": distro.url,
        }
        for distro in distros
    ]
