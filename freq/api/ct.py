"""LXC container domain API handlers — /api/ct/*.

First-class citizen alongside VMs. Every pct operation exposed via REST API.
Same pattern as vm.py: SSH to PVE node, run pct commands, return JSON.

Operations:
    list, create, destroy, power (start/stop/shutdown/reboot),
    config (view), set (modify), snapshot, rollback, delete-snapshot,
    snapshots (list), clone, migrate, resize, exec
"""

import json
import time

from freq.core import log as logger
from freq.api.helpers import require_post,  json_response, get_params
from freq.core.config import load_config
from freq.core.validate import (
    label as valid_label,
    is_protected_vmid,
)
from freq.modules.pve import _find_reachable_node, _pve_cmd
from freq.modules.serve import (
    _check_session_role,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _ct_id(params):
    """Extract and validate container ID from params."""
    raw = params.get("ctid", params.get("vmid", ["0"]))[0]
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


# ── Handlers ────────────────────────────────────────────────────────────


def handle_ct_list(handler):
    """GET /api/ct/list — list all LXC containers across PVE cluster."""
    cfg = load_config()
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"containers": [], "error": "No PVE node reachable"})
        return

    stdout, ok = _pve_cmd(
        cfg,
        node_ip,
        "pvesh get /cluster/resources --type vm --output-format json",
        timeout=15,
    )
    if not ok:
        json_response(handler, {"containers": [], "error": "Failed to query cluster"})
        return

    try:
        resources = json.loads(stdout)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warn(f"api_ct: invalid PVE response in ct/list: {e}")
        json_response(handler, {"containers": [], "error": "Invalid response from PVE"})
        return

    containers = []
    for r in resources:
        if r.get("type") != "lxc":
            continue
        containers.append(
            {
                "ctid": r.get("vmid"),
                "name": r.get("name", ""),
                "status": r.get("status", "unknown"),
                "node": r.get("node", ""),
                "cpu": r.get("cpu", 0),
                "maxcpu": r.get("maxcpu", 0),
                "mem": r.get("mem", 0),
                "maxmem": r.get("maxmem", 0),
                "mem_pct": round(r.get("mem", 0) / max(r.get("maxmem", 1), 1) * 100, 1),
                "disk": r.get("disk", 0),
                "maxdisk": r.get("maxdisk", 0),
                "uptime": r.get("uptime", 0),
                "tags": r.get("tags", ""),
                "template": r.get("template", 0),
            }
        )

    containers.sort(key=lambda c: c["ctid"])
    running = sum(1 for c in containers if c["status"] == "running")
    json_response(
        handler,
        {
            "containers": containers,
            "count": len(containers),
            "running": running,
            "stopped": len(containers) - running,
        },
    )


def handle_ct_create(handler):
    """POST /api/ct/create — create a new LXC container."""
    if require_post(handler, "Container create"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    template = params.get("template", [""])[0]
    hostname = params.get("hostname", params.get("name", [""]))[0]
    cores = params.get("cores", ["1"])[0]
    ram = params.get("ram", ["512"])[0]
    disk = params.get("disk", ["8"])[0]
    storage = params.get("storage", ["local-lvm"])[0]
    password = params.get("password", [""])[0]
    net = params.get("net", ["name=eth0,bridge=vmbr0,ip=dhcp"])[0]

    if not template:
        json_response(
            handler,
            {"error": "template parameter required (e.g. local:vztmpl/debian-12-standard_12.2-1_amd64.tar.zst)"},
        )
        return
    if not hostname:
        json_response(handler, {"error": "hostname parameter required"}, 400)
        return
    if not valid_label(hostname):
        json_response(handler, {"error": "Invalid hostname (alphanumeric + hyphens only)"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    # Get next ID
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
    if not ok:
        json_response(handler, {"error": "Cannot allocate container ID"}, 400)
        return
    ctid = int(stdout.strip())

    cmd = (
        f"pct create {ctid} {template} "
        f"--hostname {hostname} --cores {cores} --memory {ram} "
        f"--rootfs {storage}:{disk} --net0 {net}"
    )
    if password:
        cmd += f" --password {password}"
    cmd += " --unprivileged 1 --start 0"

    stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
    json_response(
        handler,
        {
            "ok": ok,
            "ctid": ctid,
            "hostname": hostname,
            "error": stdout if not ok else "",
        },
    )


def handle_ct_destroy(handler):
    """POST /api/ct/destroy — destroy an LXC container."""
    if require_post(handler, "Container destroy"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return

    if is_protected_vmid(ctid, cfg.protected_vmids, cfg.protected_ranges):
        json_response(handler, {"error": f"Container {ctid} is PROTECTED"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    # Stop first if running
    _pve_cmd(cfg, node_ip, f"pct stop {ctid}", timeout=30)
    time.sleep(1)
    stdout, ok = _pve_cmd(cfg, node_ip, f"pct destroy {ctid} --purge", timeout=120)
    json_response(handler, {"ok": ok, "ctid": ctid, "error": stdout if not ok else ""})


def handle_ct_power(handler):
    """POST /api/ct/power — start/stop/shutdown/reboot a container."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    action = params.get("action", ["status"])[0]

    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return

    valid_actions = {"start", "stop", "shutdown", "reboot", "status"}
    if action not in valid_actions:
        json_response(handler, {"error": f"Invalid action. Valid: {', '.join(sorted(valid_actions))}"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    if action == "status":
        stdout, ok = _pve_cmd(cfg, node_ip, f"pct status {ctid}", timeout=10)
        json_response(handler, {"ctid": ctid, "status": stdout.strip() if ok else "unknown"})
        return

    timeout = 60 if action in ("start", "reboot") else 30
    stdout, ok = _pve_cmd(cfg, node_ip, f"pct {action} {ctid}", timeout=timeout)
    json_response(
        handler,
        {
            "ok": ok,
            "ctid": ctid,
            "action": action,
            "error": stdout if not ok else "",
        },
    )


def handle_ct_config(handler):
    """GET /api/ct/config — view container configuration."""
    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    stdout, ok = _pve_cmd(cfg, node_ip, f"pct config {ctid}", timeout=10)
    if not ok:
        json_response(handler, {"error": f"Cannot read config for CT {ctid}"}, 400)
        return

    config = {}
    for line in stdout.strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            config[key.strip()] = val.strip()

    json_response(handler, {"ctid": ctid, "config": config})


def handle_ct_set(handler):
    """POST /api/ct/set — modify container configuration."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return

    # Build pct set arguments from params
    allowed_keys = {
        "cores",
        "memory",
        "swap",
        "hostname",
        "description",
        "nameserver",
        "searchdomain",
        "onboot",
        "protection",
        "cpulimit",
        "cpuunits",
        "tags",
    }
    parts = []
    for key in allowed_keys:
        val = params.get(key, [None])[0]
        if val is not None:
            parts.append(f"--{key} {val}")

    # Handle net and rootfs separately (can have complex values)
    for key in ("net0", "net1", "rootfs"):
        val = params.get(key, [None])[0]
        if val is not None:
            parts.append(f"--{key} {val}")

    if not parts:
        json_response(handler, {"error": "No config changes specified"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    cmd = f"pct set {ctid} {' '.join(parts)}"
    stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=30)
    json_response(handler, {"ok": ok, "ctid": ctid, "error": stdout if not ok else ""})


def handle_ct_snapshot(handler):
    """POST /api/ct/snapshot — create a container snapshot."""
    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    snap_name = params.get("name", [f"freq-snap-{ctid}"])[0]

    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return
    if not valid_label(snap_name):
        json_response(handler, {"error": "Invalid snapshot name"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    stdout, ok = _pve_cmd(cfg, node_ip, f"pct snapshot {ctid} {snap_name}", timeout=120)
    json_response(
        handler,
        {
            "ok": ok,
            "ctid": ctid,
            "snapshot": snap_name,
            "error": stdout if not ok else "",
        },
    )


def handle_ct_rollback(handler):
    """POST /api/ct/rollback — roll back a container to a snapshot."""
    if require_post(handler, "Container rollback"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    snap_name = params.get("name", [""])[0]
    start_after = params.get("start", ["true"])[0].lower() != "false"

    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    # List snapshots
    snap_out, snap_ok = _pve_cmd(cfg, node_ip, f"pct listsnapshot {ctid}", timeout=10)
    if not snap_ok:
        json_response(handler, {"error": f"Cannot list snapshots for CT {ctid}"}, 400)
        return

    snaps = []
    for line in snap_out.strip().split("\n"):
        line = line.strip().lstrip("`->").strip()
        if line and "current" not in line.lower():
            parts = line.split()
            if parts:
                snaps.append(parts[0])

    if not snaps:
        json_response(handler, {"error": f"No snapshots for CT {ctid}"}, 404)
        return

    if not snap_name:
        snap_name = snaps[-1]
    elif snap_name not in snaps:
        json_response(handler, {"error": f"Snapshot '{snap_name}' not found", "available": snaps}, 404)
        return

    # Stop if running
    status_out, _ = _pve_cmd(cfg, node_ip, f"pct status {ctid}", timeout=5)
    was_running = "running" in (status_out or "").lower()
    if was_running:
        _pve_cmd(cfg, node_ip, f"pct stop {ctid}", timeout=30)
        for _ in range(15):
            time.sleep(1)
            s_out, _ = _pve_cmd(cfg, node_ip, f"pct status {ctid}", timeout=5)
            if "stopped" in (s_out or "").lower():
                break

    # Rollback
    rb_out, rb_ok = _pve_cmd(cfg, node_ip, f"pct rollback {ctid} {snap_name}", timeout=120)
    if not rb_ok:
        json_response(handler, {"error": f"Rollback failed: {rb_out}"}, 500)
        return

    # Start if requested
    started = False
    if start_after:
        _, started = _pve_cmd(cfg, node_ip, f"pct start {ctid}", timeout=60)

    json_response(
        handler,
        {
            "ok": True,
            "ctid": ctid,
            "snapshot": snap_name,
            "was_running": was_running,
            "started": started,
            "available_snapshots": snaps,
        },
    )


def handle_ct_snapshots(handler):
    """GET /api/ct/snapshots — list container snapshots."""
    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    stdout, ok = _pve_cmd(cfg, node_ip, f"pct listsnapshot {ctid}", timeout=10)
    if not ok:
        json_response(handler, {"snapshots": [], "error": stdout})
        return

    snaps = []
    for line in stdout.strip().split("\n"):
        line = line.strip().lstrip("`->").strip()
        if not line:
            continue
        parts = line.split()
        if parts and "current" not in parts[0].lower():
            snaps.append(
                {
                    "name": parts[0],
                    "date": " ".join(parts[1:3]) if len(parts) >= 3 else "",
                    "description": " ".join(parts[3:]) if len(parts) > 3 else "",
                }
            )

    json_response(handler, {"ctid": ctid, "snapshots": snaps, "count": len(snaps)})


def handle_ct_delete_snapshot(handler):
    """POST /api/ct/delete-snapshot — delete a container snapshot."""
    if require_post(handler, "Snapshot delete"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    snap_name = params.get("name", [""])[0]

    if not ctid or not snap_name:
        json_response(handler, {"error": "ctid and name required"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    stdout, ok = _pve_cmd(cfg, node_ip, f"pct delsnapshot {ctid} {snap_name}", timeout=120)
    json_response(handler, {"ok": ok, "ctid": ctid, "snapshot": snap_name, "error": stdout if not ok else ""})


def handle_ct_clone(handler):
    """POST /api/ct/clone — clone a container."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    new_name = params.get("name", params.get("hostname", [""]))[0]

    if not ctid:
        json_response(handler, {"error": "ctid parameter required"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    # Get next ID
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
    if not ok:
        json_response(handler, {"error": "Cannot allocate container ID"}, 400)
        return
    new_id = int(stdout.strip())

    cmd = f"pct clone {ctid} {new_id}"
    if new_name:
        cmd += f" --hostname {new_name}"

    stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=300)
    json_response(
        handler,
        {
            "ok": ok,
            "source_ctid": ctid,
            "new_ctid": new_id,
            "hostname": new_name,
            "error": stdout if not ok else "",
        },
    )


def handle_ct_migrate(handler):
    """POST /api/ct/migrate — migrate a container to another node."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    target_node = params.get("target", params.get("node", [""]))[0]
    restart = params.get("restart", ["false"])[0].lower() == "true"

    if not ctid or not target_node:
        json_response(handler, {"error": "ctid and target node required"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    cmd = f"pct migrate {ctid} {target_node}"
    if restart:
        cmd += " --restart"

    stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=300)
    json_response(
        handler,
        {
            "ok": ok,
            "ctid": ctid,
            "target": target_node,
            "error": stdout if not ok else "",
        },
    )


def handle_ct_resize(handler):
    """POST /api/ct/resize — resize container disk."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    disk = params.get("disk", ["rootfs"])[0]
    size = params.get("size", [""])[0]

    if not ctid or not size:
        json_response(handler, {"error": "ctid and size required (e.g. size=+5G)"}, 400)
        return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    stdout, ok = _pve_cmd(cfg, node_ip, f"pct resize {ctid} {disk} {size}", timeout=60)
    json_response(
        handler,
        {
            "ok": ok,
            "ctid": ctid,
            "disk": disk,
            "size": size,
            "error": stdout if not ok else "",
        },
    )


def handle_ct_exec(handler):
    """POST /api/ct/exec — execute a command inside a container."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    params = get_params(handler)
    ctid = _ct_id(params)
    command = params.get("command", params.get("cmd", [""]))[0]

    if not ctid or not command:
        json_response(handler, {"error": "ctid and command required"}, 400)
        return

    # Safety: reject obviously dangerous commands
    dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd"]
    for d in dangerous:
        if d in command:
            json_response(handler, {"error": f"Blocked dangerous command pattern: {d}"}, 400)
            return

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node reachable"}, 400)
        return

    stdout, ok = _pve_cmd(
        cfg,
        node_ip,
        f"pct exec {ctid} -- bash -c {repr(command)}",
        timeout=30,
    )
    json_response(
        handler,
        {
            "ok": ok,
            "ctid": ctid,
            "command": command,
            "stdout": stdout[:5000] if ok else "",
            "error": stdout[:2000] if not ok else "",
        },
    )


def handle_ct_templates(handler):
    """GET /api/ct/templates — list available container templates."""
    cfg = load_config()
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"templates": [], "error": "No PVE node reachable"})
        return

    # List templates from all storages
    stdout, ok = _pve_cmd(
        cfg,
        node_ip,
        "pveam list local 2>/dev/null; for s in $(pvesm status --content vztmpl -noheader 2>/dev/null | awk '{print $1}'); do pveam list $s 2>/dev/null; done",
        timeout=15,
    )

    templates = []
    seen = set()
    if ok and stdout:
        for line in stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2 and ".tar" in line:
                volid = parts[0]
                if volid in seen:
                    continue
                seen.add(volid)
                templates.append(
                    {
                        "volid": volid,
                        "name": volid.split("/")[-1] if "/" in volid else volid,
                        "size": parts[1] if len(parts) > 1 else "",
                    }
                )

    json_response(handler, {"templates": templates, "count": len(templates)})


# ── Route Registration ──────────────────────────────────────────────────


def register(routes: dict):
    """Register LXC container API routes."""
    routes["/api/ct/list"] = handle_ct_list
    routes["/api/ct/create"] = handle_ct_create
    routes["/api/ct/destroy"] = handle_ct_destroy
    routes["/api/ct/power"] = handle_ct_power
    routes["/api/ct/config"] = handle_ct_config
    routes["/api/ct/set"] = handle_ct_set
    routes["/api/ct/snapshot"] = handle_ct_snapshot
    routes["/api/ct/rollback"] = handle_ct_rollback
    routes["/api/ct/snapshots"] = handle_ct_snapshots
    routes["/api/ct/delete-snapshot"] = handle_ct_delete_snapshot
    routes["/api/ct/clone"] = handle_ct_clone
    routes["/api/ct/migrate"] = handle_ct_migrate
    routes["/api/ct/resize"] = handle_ct_resize
    routes["/api/ct/exec"] = handle_ct_exec
    routes["/api/ct/templates"] = handle_ct_templates
