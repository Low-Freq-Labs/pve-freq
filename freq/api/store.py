"""Storage domain API handlers -- /api/infra/truenas, /api/storage/health,
/api/truenas/snapshot, /api/truenas/service, /api/truenas/scrub, /api/truenas/reboot.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for TrueNAS management, storage health, and write operations.
Why:   Decouples storage logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import re

from freq.api.helpers import json_response, get_cfg, get_json_body, get_param
from freq.core.config import load_config
from freq.core.ssh import run as ssh_run_fn
from freq.modules.serve import _check_session_role


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


# -- TrueNAS Helper ----------------------------------------------------------

def _truenas_ssh(cfg, cmd, timeout=15):
    """SSH to TrueNAS and return result."""
    return ssh_run_fn(
        host=cfg.truenas_ip, command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="truenas", use_sudo=False,
    )


# -- TrueNAS Snapshot Operations (admin) ------------------------------------

_SAFE_ZFS_NAME = re.compile(r'^[a-zA-Z0-9_/.\-]+$')


def handle_truenas_snapshot(handler):
    """POST /api/truenas/snapshot -- create, delete, or rollback ZFS snapshots.

    Body: {"action": "create|delete|rollback", "dataset": "pool/ds", "name": "snap1"}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    action = body.get("action", "")
    dataset = body.get("dataset", "").strip()
    name = body.get("name", "").strip()

    if not dataset or not _SAFE_ZFS_NAME.match(dataset):
        json_response(handler, {"error": "Invalid dataset name"}, 400); return

    if action == "create":
        if not name or not _SAFE_ZFS_NAME.match(name):
            json_response(handler, {"error": "Invalid snapshot name"}, 400); return
        cmd = f"zfs snapshot {dataset}@{name}"
    elif action == "delete":
        if not name or not _SAFE_ZFS_NAME.match(name):
            json_response(handler, {"error": "Invalid snapshot name"}, 400); return
        cmd = f"zfs destroy {dataset}@{name}"
    elif action == "rollback":
        if not name or not _SAFE_ZFS_NAME.match(name):
            json_response(handler, {"error": "Invalid snapshot name"}, 400); return
        cmd = f"zfs rollback -r {dataset}@{name}"
    elif action == "list":
        cmd = f"zfs list -t snapshot -r -o name,creation,used,referenced -s creation {dataset} 2>/dev/null"
        r = _truenas_ssh(cfg, cmd)
        json_response(handler, {
            "ok": r.returncode == 0,
            "output": r.stdout[:4000] if r.returncode == 0 else "",
            "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return
    else:
        json_response(handler, {"error": f"Unknown action: {action}"}, 400); return

    r = _truenas_ssh(cfg, cmd, timeout=30)
    json_response(handler, {
        "ok": r.returncode == 0,
        "action": action,
        "target": f"{dataset}@{name}",
        "output": r.stdout[:2000] if r.returncode == 0 else "",
        "error": r.stderr[:200] if r.returncode != 0 else "",
    })


# -- TrueNAS Service Control (admin) ---------------------------------------

_TRUENAS_SERVICES = {
    "smb", "nfs", "iscsitarget", "ssh", "cifs", "ftp", "snmp", "ups",
    "lldp", "smartd", "collectd",
}


def handle_truenas_service(handler):
    """POST /api/truenas/service -- start, stop, or restart a TrueNAS service.

    Body: {"action": "start|stop|restart", "service": "smb"}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    action = body.get("action", "")
    service = body.get("service", "").strip().lower()

    if action not in ("start", "stop", "restart"):
        json_response(handler, {"error": "action must be start, stop, or restart"}, 400); return
    if service not in _TRUENAS_SERVICES:
        json_response(handler, {"error": f"Unknown service: {service}. Allowed: {', '.join(sorted(_TRUENAS_SERVICES))}"}, 400); return

    cmd = f"midclt call service.{action} {service}"
    r = _truenas_ssh(cfg, cmd, timeout=20)
    json_response(handler, {
        "ok": r.returncode == 0,
        "action": action,
        "service": service,
        "output": r.stdout[:1000] if r.returncode == 0 else "",
        "error": r.stderr[:200] if r.returncode != 0 else "",
    })


# -- TrueNAS Scrub (admin) -------------------------------------------------


def handle_truenas_scrub(handler):
    """POST /api/truenas/scrub -- trigger a ZFS pool scrub.

    Body: {"pool": "tank"}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    pool = body.get("pool", "").strip()
    if not pool or not _SAFE_ZFS_NAME.match(pool):
        json_response(handler, {"error": "Invalid pool name"}, 400); return

    cmd = f"zpool scrub {pool}"
    r = _truenas_ssh(cfg, cmd, timeout=10)
    json_response(handler, {
        "ok": r.returncode == 0,
        "pool": pool,
        "output": r.stdout[:500] if r.returncode == 0 else "",
        "error": r.stderr[:200] if r.returncode != 0 else "",
    })


# -- TrueNAS Reboot (admin) ------------------------------------------------


def handle_truenas_reboot(handler):
    """POST /api/truenas/reboot -- reboot TrueNAS system.

    Body: {"confirm": true}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    if not body.get("confirm"):
        json_response(handler, {"error": "Must set confirm: true"}, 400); return

    r = _truenas_ssh(cfg, "reboot", timeout=5)
    json_response(handler, {"ok": True, "message": "Reboot command sent"})


# -- TrueNAS Dataset Management (admin) ------------------------------------


def handle_truenas_dataset(handler):
    """POST /api/truenas/dataset -- create, delete, or modify ZFS datasets.

    Body: {"action": "list|create|delete|set",
           "dataset": "pool/ds", "properties": {"compression": "lz4", "quota": "100G"}}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    action = body.get("action", "list")
    dataset = body.get("dataset", "").strip()

    if action == "list":
        pool = dataset or ""
        cmd = f"zfs list -r -o name,used,avail,refer,mountpoint,compression,quota {pool} 2>/dev/null"
        r = _truenas_ssh(cfg, cmd)
        json_response(handler, {
            "ok": r.returncode == 0,
            "output": r.stdout[:4000] if r.returncode == 0 else "",
            "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return

    if not dataset or not _SAFE_ZFS_NAME.match(dataset):
        json_response(handler, {"error": "Invalid dataset name"}, 400); return

    if action == "create":
        props = body.get("properties", {})
        cmd = "zfs create"
        for k, v in props.items():
            if _SAFE_ZFS_NAME.match(k) and _SAFE_ZFS_NAME.match(str(v)):
                cmd += f" -o {k}={v}"
        cmd += f" {dataset}"
        r = _truenas_ssh(cfg, cmd, timeout=20)
        json_response(handler, {
            "ok": r.returncode == 0, "action": "create", "dataset": dataset,
            "output": r.stdout[:1000], "error": r.stderr[:200] if r.returncode != 0 else "",
        })

    elif action == "delete":
        if not body.get("confirm"):
            json_response(handler, {"error": "Must set confirm: true to delete dataset"}, 400); return
        cmd = f"zfs destroy {dataset}"
        r = _truenas_ssh(cfg, cmd, timeout=20)
        json_response(handler, {
            "ok": r.returncode == 0, "action": "delete", "dataset": dataset,
            "output": r.stdout[:1000], "error": r.stderr[:200] if r.returncode != 0 else "",
        })

    elif action == "set":
        props = body.get("properties", {})
        if not props:
            json_response(handler, {"error": "properties required"}, 400); return
        results = []
        for k, v in props.items():
            if not _SAFE_ZFS_NAME.match(k):
                results.append({"property": k, "ok": False, "error": "Invalid property name"})
                continue
            cmd = f"zfs set {k}={v} {dataset}"
            r = _truenas_ssh(cfg, cmd, timeout=10)
            results.append({"property": k, "value": str(v), "ok": r.returncode == 0,
                            "error": r.stderr[:100] if r.returncode != 0 else ""})
        json_response(handler, {"ok": all(x["ok"] for x in results), "results": results})

    else:
        json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- TrueNAS Share Management (admin) --------------------------------------


def handle_truenas_share(handler):
    """POST /api/truenas/share -- manage SMB and NFS shares.

    Body: {"action": "list|create|delete", "type": "smb|nfs",
           "name": "share_name", "path": "/mnt/pool/dataset",
           "options": {...}}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    action = body.get("action", "list")
    share_type = body.get("type", "smb").lower()

    if share_type not in ("smb", "nfs"):
        json_response(handler, {"error": "type must be smb or nfs"}, 400); return

    if action == "list":
        if share_type == "smb":
            cmd = "midclt call sharing.smb.query '[]' 2>/dev/null"
        else:
            cmd = "midclt call sharing.nfs.query '[]' 2>/dev/null"
        r = _truenas_ssh(cfg, cmd, timeout=15)
        json_response(handler, {
            "ok": r.returncode == 0, "type": share_type,
            "output": r.stdout[:4000] if r.returncode == 0 else "",
            "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return

    if action == "create":
        name = body.get("name", "").strip()
        path = body.get("path", "").strip()
        if not name or not path:
            json_response(handler, {"error": "name and path required"}, 400); return
        if "'" in name or "'" in path or '"' in name or '"' in path:
            json_response(handler, {"error": "Invalid characters"}, 400); return

        if share_type == "smb":
            cmd = f"midclt call sharing.smb.create '{{\"name\":\"{name}\",\"path\":\"{path}\",\"purpose\":\"DEFAULT_SHARE\"}}'"
        else:
            networks = body.get("networks", ["10.25.0.0/16"])
            nets_json = ",".join(f'"{n}"' for n in networks)
            cmd = f"midclt call sharing.nfs.create '{{\"path\":\"{path}\",\"networks\":[{nets_json}]}}'"

        r = _truenas_ssh(cfg, cmd, timeout=20)
        json_response(handler, {
            "ok": r.returncode == 0, "action": "create", "type": share_type,
            "name": name, "path": path,
            "output": r.stdout[:1000] if r.returncode == 0 else "",
            "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return

    if action == "delete":
        share_id = body.get("id")
        if share_id is None:
            json_response(handler, {"error": "id required for delete"}, 400); return
        cmd = f"midclt call sharing.{share_type}.delete {share_id}"
        r = _truenas_ssh(cfg, cmd, timeout=15)
        json_response(handler, {
            "ok": r.returncode == 0, "action": "delete", "type": share_type,
            "id": share_id,
            "output": r.stdout[:500], "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return

    json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- TrueNAS Replication Control (admin) ------------------------------------


def handle_truenas_replication(handler):
    """POST /api/truenas/replication -- list or run replication tasks.

    Body: {"action": "list|run", "id": 1}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    action = body.get("action", "list")

    if action == "list":
        cmd = "midclt call replication.query '[]' 2>/dev/null"
        r = _truenas_ssh(cfg, cmd, timeout=15)
        json_response(handler, {
            "ok": r.returncode == 0,
            "output": r.stdout[:4000] if r.returncode == 0 else "",
            "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return

    if action == "run":
        task_id = body.get("id")
        if task_id is None:
            json_response(handler, {"error": "id required"}, 400); return
        cmd = f"midclt call replication.run {task_id}"
        r = _truenas_ssh(cfg, cmd, timeout=30)
        json_response(handler, {
            "ok": r.returncode == 0, "action": "run", "id": task_id,
            "output": r.stdout[:1000] if r.returncode == 0 else "",
            "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return

    json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- TrueNAS App Management (admin) ----------------------------------------


def handle_truenas_app(handler):
    """POST /api/truenas/app -- manage TrueNAS SCALE apps.

    Body: {"action": "list|start|stop", "name": "app_name", "replicas": 1}
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return

    cfg = load_config()
    if not cfg.truenas_ip:
        json_response(handler, {"error": "TrueNAS not configured"}, 400); return

    body = get_json_body(handler)
    action = body.get("action", "list")

    if action == "list":
        cmd = "midclt call chart.release.query '[]' 2>/dev/null || midclt call app.query '[]' 2>/dev/null || echo '[]'"
        r = _truenas_ssh(cfg, cmd, timeout=20)
        json_response(handler, {
            "ok": r.returncode == 0,
            "output": r.stdout[:4000] if r.returncode == 0 else "",
            "error": r.stderr[:200] if r.returncode != 0 else "",
        })
        return

    name = body.get("name", "").strip()
    if not name:
        json_response(handler, {"error": "name required"}, 400); return
    if "'" in name or '"' in name:
        json_response(handler, {"error": "Invalid characters"}, 400); return

    if action == "start":
        replicas = body.get("replicas", 1)
        cmd = f"midclt call chart.release.scale '{name}' '{{\"replica_count\":{replicas}}}' 2>/dev/null || midclt call app.start '{name}' 2>/dev/null"
        r = _truenas_ssh(cfg, cmd, timeout=30)
        json_response(handler, {
            "ok": r.returncode == 0, "action": "start", "name": name,
            "output": r.stdout[:500], "error": r.stderr[:200] if r.returncode != 0 else "",
        })

    elif action == "stop":
        cmd = f"midclt call chart.release.scale '{name}' '{{\"replica_count\":0}}' 2>/dev/null || midclt call app.stop '{name}' 2>/dev/null"
        r = _truenas_ssh(cfg, cmd, timeout=30)
        json_response(handler, {
            "ok": r.returncode == 0, "action": "stop", "name": name,
            "output": r.stdout[:500], "error": r.stderr[:200] if r.returncode != 0 else "",
        })

    else:
        json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register storage API routes into the master route table."""
    routes["/api/infra/truenas"] = handle_truenas
    routes["/api/storage/health"] = handle_storage_health
    routes["/api/truenas/snapshot"] = handle_truenas_snapshot
    routes["/api/truenas/service"] = handle_truenas_service
    routes["/api/truenas/scrub"] = handle_truenas_scrub
    routes["/api/truenas/reboot"] = handle_truenas_reboot
    routes["/api/truenas/dataset"] = handle_truenas_dataset
    routes["/api/truenas/share"] = handle_truenas_share
    routes["/api/truenas/replication"] = handle_truenas_replication
    routes["/api/truenas/app"] = handle_truenas_app
