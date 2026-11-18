"""PVE cluster-node discovery independent of the dashboard transport."""

import json
import time

from freq.core import log as logger
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.services import dashboard_state as _dashboard_state

NODE_DISCOVERY_INTERVAL = 300

_bg_cache = _dashboard_state.background_cache
_bg_cache_ts = _dashboard_state.background_cache_timestamps
_bg_lock = _dashboard_state.background_cache_lock


def _bg_discover_pve_nodes():
    """Discover PVE cluster nodes from API + corosync config.

    Queries any reachable seed node (from freq.toml) for:
    - /cluster/resources --type node -> node names, status, hardware stats
    - /etc/pve/corosync.conf -> node name to IP mapping

    Results cached in _bg_cache["pve_nodes"] for 5 minutes.
    Falls back to freq.toml static list if discovery fails.
    """
    with _bg_lock:
        last = _bg_cache_ts.get("pve_nodes", 0)
    if time.time() - last < NODE_DISCOVERY_INTERVAL:
        return

    try:
        cfg = load_config()
        # Find first reachable seed node
        seed_ip = None
        for ip in cfg.pve_nodes:
            r = ssh_single(
                host=ip,
                command="echo ok",
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=5,
                htype="pve",
                use_sudo=False,
                cfg=cfg,
            )
            if r.returncode == 0:
                seed_ip = ip
                break

        if not seed_ip:
            logger.warn("PVE node discovery: no reachable seed node")
            with _bg_lock:
                _bg_cache_ts["pve_nodes"] = time.time()
            return

        # Get node names + stats from cluster API
        r = ssh_single(
            host=seed_ip,
            command="pvesh get /cluster/resources --type node --output-format json",
            key_path=cfg.ssh_key_path,
            command_timeout=15,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
        )

        node_stats = {}
        if r.returncode == 0 and r.stdout:
            try:
                for n in json.loads(r.stdout):
                    name = n.get("node", "")
                    if name:
                        node_stats[name] = {
                            "status": "online" if n.get("status") == "online" else "offline",
                            "cores": n.get("maxcpu", 0),
                            "ram_gb": round(n.get("maxmem", 0) / (1024**3)),
                        }
            except json.JSONDecodeError:
                pass

        # Get IPs from corosync config
        r2 = ssh_single(
            host=seed_ip,
            command="cat /etc/pve/corosync.conf 2>/dev/null",
            key_path=cfg.ssh_key_path,
            command_timeout=10,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
        )

        node_ips = {}
        if r2.returncode == 0 and r2.stdout:
            current_name = None
            for line in r2.stdout.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    current_name = line.split(":", 1)[1].strip()
                elif line.startswith("ring0_addr:") and current_name:
                    node_ips[current_name] = line.split(":", 1)[1].strip()
                    current_name = None

        # Build discovered nodes
        discovered = []
        for name, stats in node_stats.items():
            discovered.append(
                {
                    "name": name,
                    "ip": node_ips.get(name, ""),
                    "status": stats["status"],
                    "cores": stats["cores"],
                    "ram_gb": stats["ram_gb"],
                }
            )

        result = {"nodes": discovered, "discovered_at": time.time()} if discovered else None
    except Exception as e:
        logger.error(f"PVE node discovery failed: {e}")
        result = None

    with _bg_lock:
        _bg_cache["pve_nodes"] = result
        _bg_cache_ts["pve_nodes"] = time.time()


def _get_discovered_node_ips():
    """Get PVE node IPs, preferring discovery over freq.toml."""
    with _bg_lock:
        discovered = _bg_cache.get("pve_nodes")
    if discovered and discovered.get("nodes"):
        ips = [n["ip"] for n in discovered["nodes"] if n.get("ip")]
        if ips:
            return ips
    cfg = load_config()
    return list(cfg.pve_nodes)


def find_reachable_pve_node(cfg):
    """Find the first reachable PVE node. Returns IP string or None.

    Prefers auto-discovered nodes, falls back to freq.toml static list.
    """
    node_ips = _get_discovered_node_ips()
    for ip in node_ips:
        r = ssh_single(
            host=ip,
            command="sudo pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="pve",
            use_sudo=False,
            cfg=cfg,
        )
        if r.returncode == 0:
            return ip
    return None


def read_backup_schedules(cfg):
    """Read the raw PVE backup-schedule configuration from a reachable node."""
    node_ip = find_reachable_pve_node(cfg)
    if not node_ip:
        return {"schedules": [], "error": "No PVE node reachable"}

    result = ssh_single(
        host=node_ip,
        command="cat /etc/pve/jobs.cfg 2>/dev/null || echo ''",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=10,
        htype="pve",
        use_sudo=True,
        cfg=cfg,
    )
    return {
        "raw": result.stdout if result and result.returncode == 0 else "",
        "ok": result is not None and result.returncode == 0,
    }


def _get_discovered_nodes():
    """Get PVE node rows, preferring discovery over fleet boundaries."""
    with _bg_lock:
        discovered = _bg_cache.get("pve_nodes")
    if discovered and discovered.get("nodes"):
        return discovered["nodes"]
    cfg = load_config()
    fb = cfg.fleet_boundaries
    return [{"name": n.name, "ip": n.ip, "detail": getattr(n, "detail", "")} for n in fb.pve_nodes.values()]
