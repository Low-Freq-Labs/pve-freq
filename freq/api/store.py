"""Storage domain API handlers -- /api/infra/truenas, /api/storage/health.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for TrueNAS management and storage health monitoring.
Why:   Decouples storage logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

from freq.api.helpers import json_response, get_cfg
from freq.core.config import load_config
from freq.core.ssh import run as ssh_run_fn


# -- Handlers ----------------------------------------------------------------


def handle_truenas(handler):
    """GET /api/infra/truenas -- TrueNAS data via SSH.

    Delegates to serve.py's _serve_truenas method because the TrueNAS
    handler is 300+ lines with complex SSH orchestration. The handler
    arg IS the FreqHandler instance, so we call the method directly on it.
    """
    handler._serve_truenas()


def handle_storage_health(handler):
    """GET /api/storage/health -- storage pool status across PVE + TrueNAS."""
    cfg = load_config()

    pools = []
    # PVE storage pools
    for i, node_ip in enumerate(cfg.pve_nodes):
        node_name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"node{i}"
        r = ssh_run_fn(
            host=node_ip,
            command="sudo pvesm status 2>/dev/null | tail -n +2",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=15,
            htype="pve", use_sudo=False,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 7:
                    total_bytes = int(parts[3]) if parts[3].isdigit() else 0
                    used_bytes = int(parts[4]) if parts[4].isdigit() else 0
                    avail_bytes = int(parts[5]) if parts[5].isdigit() else 0
                    pct = round(used_bytes / total_bytes * 100, 1) if total_bytes > 0 else 0
                    pools.append({
                        "name": parts[0],
                        "type": parts[1],
                        "status": parts[2],
                        "total_gb": round(total_bytes / (1024**3), 1),
                        "used_gb": round(used_bytes / (1024**3), 1),
                        "avail_gb": round(avail_bytes / (1024**3), 1),
                        "used_pct": pct,
                        "node": node_name,
                        "source": "pve",
                    })

    # TrueNAS pools (if configured)
    if cfg.truenas_ip:
        r = ssh_run_fn(
            host=cfg.truenas_ip,
            command="zpool list -Hp 2>/dev/null | head -10",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=15,
            htype="truenas", use_sudo=False,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 4:
                    try:
                        total = int(parts[1])
                        used = int(parts[2])
                        pools.append({
                            "name": parts[0],
                            "type": "zfs",
                            "status": parts[9] if len(parts) > 9 else "unknown",
                            "total_gb": round(total / (1024**3), 1),
                            "used_gb": round(used / (1024**3), 1),
                            "avail_gb": round((total - used) / (1024**3), 1),
                            "used_pct": round(used / total * 100, 1) if total > 0 else 0,
                            "node": "truenas",
                            "source": "truenas",
                        })
                    except (ValueError, IndexError):
                        pass

    json_response(handler, {
        "pools": pools,
        "count": len(pools),
        "total_tb": round(sum(p["total_gb"] for p in pools) / 1024, 2),
        "used_tb": round(sum(p["used_gb"] for p in pools) / 1024, 2),
    })


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register storage API routes into the master route table."""
    routes["/api/infra/truenas"] = handle_truenas
    routes["/api/storage/health"] = handle_storage_health
