"""Disaster recovery domain API handlers -- /api/backup/*, /api/journal, /api/zfs, etc.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for backup management, journaling, migration, and ZFS ops.
Why:   Decouples DR logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import json
import os

from freq.api.helpers import json_response, get_params, get_cfg
from freq.core.config import load_config
from freq.core import log as logger
from freq.modules.serve import (
    _parse_query,
    _parse_query_flat,
    _check_session_role,
    _check_vm_permission,
)
from freq.modules.pve import _find_reachable_node, _pve_cmd


# -- Handlers ----------------------------------------------------------------


def handle_backup(handler):
    """GET /api/backup -- backup management: list, create, status, prune."""
    cfg = load_config()
    query = _parse_query(handler)
    action = query.get("action", ["list"])[0]
    target = query.get("target", [""])[0]
    try:
        import io, contextlib
        from freq.modules.backup import cmd_backup
        class Args:
            pass
        args = Args()
        args.action = action
        args.target = target or None
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_backup(cfg, None, args)
        json_response(handler, {"ok": result == 0, "output": buf.getvalue(), "action": action})
    except Exception as e:
        json_response(handler, {"error": f"Backup operation failed: {e}"}, 500)


def handle_backup_list(handler):
    """GET /api/backup/list -- list all VM snapshots and config exports."""
    cfg = load_config()
    result = {"snapshots": [], "exports": []}

    try:
        node_ip = _find_reachable_node(cfg)
        if node_ip:
            stdout, ok = _pve_cmd(cfg, node_ip,
                                  "pvesh get /cluster/resources --type vm --output-format json")
            if ok and stdout:
                try:
                    vms = json.loads(stdout)
                    for vm in vms:
                        vmid = vm.get("vmid", 0)
                        name = vm.get("name", "?")
                        snap_out, snap_ok = _pve_cmd(cfg, node_ip,
                                                      f"qm listsnapshot {vmid} 2>/dev/null")
                        if snap_ok and snap_out.strip():
                            for line in snap_out.strip().split("\n"):
                                line = line.strip()
                                if not line or "current" in line.lower():
                                    continue
                                parts = line.split()
                                snap_name = parts[0].replace("`-", "").replace("->", "").strip()
                                if snap_name:
                                    result["snapshots"].append({
                                        "vmid": vmid, "vm_name": name,
                                        "snapshot": snap_name,
                                    })
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.warning(f"backup list: failed to get snapshots: {e}")

    export_dir = os.path.join(cfg.data_dir, "backups")
    if os.path.isdir(export_dir):
        for f in sorted(os.listdir(export_dir), reverse=True)[:20]:
            fpath = os.path.join(export_dir, f)
            result["exports"].append({
                "filename": f,
                "size_kb": os.path.getsize(fpath) // 1024 if os.path.isfile(fpath) else 0,
            })

    json_response(handler, result)


def handle_backup_create(handler):
    """POST /api/backup/create -- create a VM snapshot."""
    cfg = load_config()
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}); return

    query = _parse_query_flat(handler.path)
    vmid = int(query.get("vmid", "0"))
    snap_name = query.get("name", f"freq-snap-{vmid}")

    if not vmid:
        json_response(handler, {"error": "vmid required"}); return

    allowed, err_msg = _check_vm_permission(cfg, vmid, "snapshot")
    if not allowed:
        json_response(handler, {"error": err_msg}); return

    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_-]+$', snap_name):
        json_response(handler, {"error": f"Invalid snapshot name: {snap_name}"}); return

    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"}); return
        cmd = f"qm snapshot {vmid} {snap_name} --description 'Created by FREQ dashboard'"
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
        json_response(handler, {
            "ok": ok, "vmid": vmid, "snapshot": snap_name,
            "error": stdout if not ok else "",
        })
    except Exception as e:
        json_response(handler, {"error": f"Snapshot failed: {e}"})


def handle_backup_restore(handler):
    """POST /api/backup/restore -- rollback a VM to a snapshot."""
    cfg = load_config()
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}); return

    query = _parse_query_flat(handler.path)
    vmid = int(query.get("vmid", "0"))
    snap_name = query.get("name", "")

    if not vmid or not snap_name:
        json_response(handler, {"error": "vmid and name required"}); return

    allowed, err_msg = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err_msg}); return

    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_-]+$', snap_name):
        json_response(handler, {"error": f"Invalid snapshot name: {snap_name}"}); return

    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"}); return
        cmd = f"qm rollback {vmid} {snap_name}"
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=300)
        json_response(handler, {
            "ok": ok, "vmid": vmid, "snapshot": snap_name,
            "error": stdout if not ok else "",
        })
    except Exception as e:
        json_response(handler, {"error": f"Restore failed: {e}"})


def handle_backup_policy_list(handler):
    """GET /api/backup-policy/list -- list backup policies."""
    from freq.modules.backup_policy import _load_policies
    cfg = load_config()
    policies = _load_policies(cfg)
    json_response(handler, {"policies": policies, "count": len(policies)})


def handle_backup_policy_status(handler):
    """GET /api/backup-policy/status -- get backup policy enforcement status."""
    from freq.modules.backup_policy import _load_state, _load_policies
    cfg = load_config()
    state = _load_state(cfg)
    policies = _load_policies(cfg)
    state["policy_count"] = len(policies)
    json_response(handler, state)


def handle_journal(handler):
    """GET /api/journal -- journal entries."""
    cfg = load_config()
    path = os.path.join(cfg.data_dir, "log", "journal.jsonl")
    entries = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    entries.append(json.loads(line.strip()))
                except (json.JSONDecodeError, ValueError):
                    pass
    json_response(handler, {"entries": entries[-50:], "count": len(entries)})


def handle_migrate_plan(handler):
    """GET /api/migrate-plan -- get migration recommendations."""
    json_response(handler, {
        "info": "Migration planning requires live PVE access. Use CLI.",
        "usage": "freq migrate-plan",
    })


def handle_migrate_vmware_status(handler):
    """GET /api/migrate-vmware/status -- get VMware migration status."""
    from freq.modules.migrate_vmware import _load_state
    cfg = load_config()
    state = _load_state(cfg)
    json_response(handler, state)


def handle_zfs(handler):
    """GET /api/zfs -- ZFS pool status and operations."""
    cfg = load_config()
    query = _parse_query(handler)
    action = query.get("action", ["status"])[0]
    try:
        import io, contextlib
        from freq.modules.infrastructure import cmd_truenas
        class Args:
            pass
        args = Args()
        args.action = action
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_truenas(cfg, None, args)
        json_response(handler, {"ok": result == 0, "output": buf.getvalue(), "action": action})
    except Exception as e:
        json_response(handler, {"error": f"ZFS operation failed: {e}"}, 500)


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register DR API routes into the master route table."""
    routes["/api/backup"] = handle_backup
    routes["/api/backup/list"] = handle_backup_list
    routes["/api/backup/create"] = handle_backup_create
    routes["/api/backup/restore"] = handle_backup_restore
    routes["/api/backup-policy/list"] = handle_backup_policy_list
    routes["/api/backup-policy/status"] = handle_backup_policy_status
    routes["/api/journal"] = handle_journal
    routes["/api/migrate-plan"] = handle_migrate_plan
    routes["/api/migrate-vmware/status"] = handle_migrate_vmware_status
    routes["/api/zfs"] = handle_zfs
