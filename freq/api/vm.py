"""VM domain API handlers — /api/vm/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for virtual machine lifecycle operations.
Why:   Decouples VM logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/vm/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.

Maps 1:1 to `freq vm` CLI domain. Each handler is a standalone function
that receives the HTTP handler as its first argument.
"""

import json
import os
import re
import subprocess

from freq.core import log as logger
from freq.api.helpers import json_response, get_params
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.core.validate import (
    ip as valid_ip,
    label as valid_label,
    is_protected_vmid,
    vlan_id as valid_vlan,
)
from freq.modules.pve import _find_reachable_node, _pve_cmd
from freq.modules.serve import (
    _get_fleet_vms,
    _check_vm_permission,
    get_vm_tags,
    _find_reachable_pve_node,
    _check_session_role,
    _get_discovered_node_ips,
)


def _require_post(handler, action="this operation"):
    """Reject non-POST requests for destructive operations."""
    if handler.command != "POST":
        json_response(handler, {"error": f"{action} requires POST"}, 405)
        return True
    return False


# ── Handlers ────────────────────────────────────────────────────────────


def handle_vm_list(handler):
    """GET /api/vms — VM inventory from PVE cluster, enriched with fleet boundaries."""
    cfg = load_config()
    vm_list = _get_fleet_vms(cfg)
    json_response(handler, {"vms": vm_list, "count": len(vm_list)})


def handle_vm_create(handler):
    """POST /api/vm/create — create a new VM."""
    if _require_post(handler, "VM create"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    name = params.get("name", [""])[0]
    cores = int(params.get("cores", ["2"])[0])
    ram = int(params.get("ram", ["2048"])[0])
    if not name:
        json_response(handler, {"error": "Name required"})
        return
    if not valid_label(name):
        json_response(handler, {"error": "Invalid VM name (alphanumeric + hyphens only)"})
        return
    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return
        stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
        if not ok:
            json_response(handler, {"error": "Cannot allocate VMID"})
            return
        vmid = int(stdout.strip())
        lab_cat = cfg.fleet_boundaries.categories.get("lab", {})
        vmid_floor = lab_cat.get("range_start", 5000)
        if vmid < vmid_floor:
            vmid = vmid_floor
            # Verify the floor VMID isn't already in use
            check_out, check_ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/resources --type vm --output-format json")
            if check_ok:
                try:
                    existing = {v.get("vmid") for v in __import__("json").loads(check_out)}
                    while vmid in existing:
                        vmid += 1
                except Exception:
                    pass  # Best effort — if parse fails, try the original vmid
        cmd = (
            f"qm create {vmid} --name {name} --cores {cores} --memory {ram} "
            f"--cpu {cfg.vm_cpu} --machine {cfg.vm_machine} "
            f"--net0 virtio,bridge={cfg.nic_bridge} --scsihw {cfg.vm_scsihw}"
        )
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
        json_response(handler, {"ok": ok, "vmid": vmid, "name": name, "error": stdout if not ok else ""})
    except Exception as e:
        logger.error(f"api_vm_error: vm create failed: {e}", endpoint="vm/create")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_destroy(handler):
    """POST /api/vm/destroy — destroy a VM."""
    if _require_post(handler, "VM destroy"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = int(params.get("vmid", ["0"])[0])
    # Fleet boundary check — only admin-tier VMs can be destroyed
    allowed, err = _check_vm_permission(cfg, vmid, "destroy")
    if not allowed:
        json_response(handler, {"error": err})
        return
    if is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges, vm_tags=get_vm_tags(vmid)):
        json_response(handler, {"error": f"VMID {vmid} is PROTECTED"})
        return
    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return
        _pve_cmd(cfg, node_ip, f"qm stop {vmid}", timeout=30)
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=120)
        json_response(handler, {"ok": ok, "vmid": vmid, "error": stdout if not ok else ""})
    except Exception as e:
        logger.error(f"api_vm_error: vm destroy failed: {e}", endpoint="vm/destroy")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_snapshot(handler):
    """POST /api/vm/snapshot — take a snapshot of a VM."""
    if _require_post(handler, "VM snapshot"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = int(params.get("vmid", ["0"])[0])
    snap_name = params.get("name", [f"freq-snap-{vmid}"])[0]
    if not valid_label(snap_name):
        json_response(handler, {"error": "Invalid snapshot name (alphanumeric + hyphens only)"})
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, vmid, "snapshot")
    if not allowed:
        json_response(handler, {"error": err})
        return
    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm snapshot {vmid} {snap_name}", timeout=120)
        json_response(handler, {"ok": ok, "vmid": vmid, "snapshot": snap_name, "error": stdout if not ok else ""})
    except Exception as e:
        logger.error(f"api_vm_error: vm snapshot failed: {e}", endpoint="vm/snapshot")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_resize(handler):
    """POST /api/vm/resize — resize VM cores/RAM."""
    if _require_post(handler, "VM resize"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = int(params.get("vmid", ["0"])[0])
    cores = params.get("cores", [None])[0]
    ram = params.get("ram", [None])[0]
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, vmid, "resize")
    if not allowed:
        json_response(handler, {"error": err})
        return
    parts = []
    if cores:
        try:
            cores = int(cores)
        except ValueError:
            json_response(handler, {"error": "Invalid cores value"})
            return
        parts.append(f"--cores {cores}")
    if ram:
        try:
            ram = int(ram)
        except ValueError:
            json_response(handler, {"error": "Invalid ram value"})
            return
        parts.append(f"--memory {ram}")
    if not parts:
        json_response(handler, {"error": "Specify cores or ram"})
        return
    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} {' '.join(parts)}")
        json_response(handler, {"ok": ok, "vmid": vmid, "error": stdout if not ok else ""})
    except Exception as e:
        logger.error(f"api_vm_error: vm resize failed: {e}", endpoint="vm/resize")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_power(handler):
    """POST /api/vm/power — start/stop/reset/status a VM."""
    if _require_post(handler, "VM power"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = int(params.get("vmid", ["0"])[0])
    action = params.get("action", ["status"])[0]
    # Fleet boundary check — power actions require start/stop permission
    if action in ("start", "stop", "reset"):
        perm_action = "start" if action == "start" else "stop"
        allowed, err = _check_vm_permission(cfg, vmid, perm_action)
        if not allowed:
            json_response(handler, {"error": err})
            return
    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return
        ssh_cmds = {
            "start": f"qm start {vmid}",
            "stop": f"qm stop {vmid}",
            "reset": f"qm reset {vmid}",
            "status": f"qm status {vmid}",
        }
        api_actions = {
            "start": ("start", "POST"),
            "stop": ("stop", "POST"),
            "reset": ("reset", "POST"),
            "status": ("current", "GET"),
        }
        ssh_cmd = ssh_cmds.get(action, ssh_cmds["status"])
        api_action, api_method = api_actions.get(action, api_actions["status"])

        # Try API first: resolve node name for this VM
        from freq.modules.pve import _pve_api_call

        ok = False
        result = ""
        if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
            res_data, res_ok = _pve_api_call(cfg, node_ip, "/cluster/resources?type=vm", timeout=10)
            if res_ok and isinstance(res_data, list):
                vm_entry = next((v for v in res_data if v.get("vmid") == vmid), None)
                if vm_entry and vm_entry.get("node"):
                    result, ok = _pve_api_call(
                        cfg,
                        node_ip,
                        f"/nodes/{vm_entry['node']}/qemu/{vmid}/status/{api_action}",
                        method=api_method,
                        timeout=60,
                    )
        if not ok:
            result, ok = _pve_cmd(cfg, node_ip, ssh_cmd, timeout=60)
        output = result if isinstance(result, str) else json.dumps(result) if result else ""
        json_response(
            handler, {"ok": ok, "vmid": vmid, "action": action, "output": output, "error": "" if ok else output}
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm power failed: {e}", endpoint="vm/power")
        json_response(handler, {"error": f"PVE operation failed: {e}"})


def handle_vm_template(handler):
    """GET /api/vm/template — convert VM to template."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    if not vmid:
        json_response(handler, {"error": "vmid parameter required"})
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return

    try:
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "no PVE node reachable"})
            return

        r = ssh_single(
            host=node_ip,
            command=f"sudo qm template {vmid}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=120,
            htype="pve",
            use_sudo=False,
        )
        json_response(handler, {"ok": r.returncode == 0, "vmid": vmid})
    except Exception as e:
        logger.error(f"api_vm_error: vm template failed: {e}", endpoint="vm/template")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_rename(handler):
    """POST /api/vm/rename — rename a VM."""
    if _require_post(handler, "VM rename"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    name = query.get("name", [""])[0]
    if not vmid or not name:
        json_response(handler, {"error": "vmid and name parameters required"})
        return
    if not valid_label(name):
        json_response(handler, {"error": "Invalid VM name (alphanumeric + hyphens only)"})
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return

    try:
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "no PVE node reachable"})
            return

        r = ssh_single(
            host=node_ip,
            command=f"sudo qm set {vmid} --name {name}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        json_response(handler, {"ok": r.returncode == 0, "vmid": vmid, "name": name})
    except Exception as e:
        logger.error(f"api_vm_error: vm rename failed: {e}", endpoint="vm/rename")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_snapshots(handler):
    """GET /api/vm/snapshots — list snapshots for a VM."""
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    if not vmid:
        json_response(handler, {"error": "vmid required"})
        return
    node_ip = _find_reachable_pve_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "no PVE node reachable"})
        return
    r = ssh_single(
        host=node_ip,
        command=f"sudo qm listsnapshot {vmid}",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=15,
        htype="pve",
        use_sudo=False,
    )
    snaps = []
    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if (not line) or ("current" in line.lower() and "->" in line):
                continue
            parts = line.split()
            if parts:
                snap_name = parts[0].replace("`-", "").replace("->", "").strip()
                if snap_name and snap_name != "current":
                    snaps.append(snap_name)
    json_response(handler, {"vmid": vmid, "snapshots": snaps, "count": len(snaps), "live_migration": len(snaps) == 0})


def handle_vm_delete_snapshot(handler):
    """POST /api/vm/delete-snapshot — delete a snapshot from a VM."""
    if _require_post(handler, "VM delete snapshot"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    snap = query.get("name", [""])[0]
    if not vmid or not snap:
        json_response(handler, {"error": "vmid and name required"})
        return
    if not valid_label(snap):
        json_response(handler, {"error": "Invalid snapshot name (alphanumeric + hyphens only)"})
        return
    allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return
    try:
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "no PVE node reachable"})
            return
        r = ssh_single(
            host=node_ip,
            command=f"sudo qm delsnapshot {vmid} {snap}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=120,
            htype="pve",
            use_sudo=False,
        )
        json_response(
            handler,
            {
                "ok": r.returncode == 0,
                "vmid": vmid,
                "snapshot": snap,
                "error": "" if r.returncode == 0 else (r.stderr or r.stdout),
            },
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm snapshot delete failed: {e}", endpoint="vm/snapshot-delete")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_change_id(handler):
    """POST /api/vm/change-id — change VMID. Requires VM to be stopped."""
    if _require_post(handler, "VM change ID"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    newid = query.get("newid", [""])[0]
    if not vmid or not newid:
        json_response(handler, {"error": "vmid and newid parameters required"})
        return
    # Fleet boundary check on BOTH old and new VMID
    allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return
    allowed2, err2 = _check_vm_permission(cfg, int(newid), "configure")
    if not allowed2:
        json_response(handler, {"error": f"Target VMID blocked: {err2}"})
        return

    try:
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "no PVE node reachable"})
            return

        # VM must be stopped first
        r = ssh_single(
            host=node_ip,
            command=f"sudo qm status {vmid}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="pve",
            use_sudo=False,
        )
        if "running" in (r.stdout or ""):
            json_response(handler, {"error": f"VM {vmid} must be stopped first"})
            return

        # Clone to new ID then destroy old
        r = ssh_single(
            host=node_ip,
            command=f"sudo qm clone {vmid} {newid} --full",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=300,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode != 0:
            json_response(handler, {"error": f"Clone failed: {r.stderr or r.stdout}"})
            return

        # Destroy old VM
        r2 = ssh_single(
            host=node_ip,
            command=f"sudo qm destroy {vmid} --purge",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=120,
            htype="pve",
            use_sudo=False,
        )
        json_response(
            handler,
            {
                "ok": r2.returncode == 0,
                "old_vmid": vmid,
                "new_vmid": newid,
                "error": "" if r2.returncode == 0 else (r2.stderr or r2.stdout),
            },
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm change-id failed: {e}", endpoint="vm/change-id")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_check_ip(handler):
    """GET /api/vm/check-ip — check if an IP is available by pinging it."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err})
        return
    query = get_params(handler)
    ip = query.get("ip", [""])[0]
    if not ip:
        json_response(handler, {"error": "ip required"})
        return
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, timeout=3)
        in_use = r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        in_use = False
    json_response(handler, {"ip": ip, "in_use": in_use, "available": not in_use})


def handle_vm_add_nic(handler):
    """GET /api/vm/add-nic — add a NIC to a VM without clearing existing ones."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    new_ip = query.get("ip", [""])[0]
    gateway = query.get("gw", [""])[0]
    vlan_id_val = query.get("vlan", [""])[0]
    if not vmid or not new_ip:
        json_response(handler, {"error": "vmid and ip required"})
        return
    bare_ip = new_ip.split("/")[0] if "/" in new_ip else new_ip
    if not valid_ip(bare_ip):
        json_response(handler, {"error": "Invalid IP address"})
        return
    if gateway and not valid_ip(gateway):
        json_response(handler, {"error": "Invalid gateway IP"})
        return
    if vlan_id_val and not valid_vlan(vlan_id_val):
        json_response(handler, {"error": "Invalid VLAN ID"})
        return
    allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return

    try:
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "no PVE node reachable"})
            return

        # Find the next available NIC index
        r = ssh_single(
            host=node_ip,
            command=f"sudo qm config {vmid}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=15,
            htype="pve",
            use_sudo=False,
        )
        next_nic = 0
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                key = line.split(":")[0].strip()
                if key.startswith("net"):
                    try:
                        idx = int(key.replace("net", ""))
                        if idx >= next_nic:
                            next_nic = idx + 1
                    except ValueError:
                        pass

        cidr = new_ip if "/" in new_ip else new_ip + "/24"
        gw_part = f",gw={gateway}" if gateway else ""
        tag_part = f",tag={vlan_id_val}" if vlan_id_val else ""

        # Create net entry
        r1 = ssh_single(
            host=node_ip,
            command=f"sudo qm set {vmid} --net{next_nic} virtio,bridge={cfg.nic_bridge}{tag_part}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        # Set ipconfig
        r2 = ssh_single(
            host=node_ip,
            command=f"sudo qm set {vmid} --ipconfig{next_nic} ip={cidr}{gw_part}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        ok = r1.returncode == 0 and r2.returncode == 0
        err = ""
        if r1.returncode != 0:
            err = f"NIC create failed: {r1.stderr or r1.stdout}"
        elif r2.returncode != 0:
            err = f"IP config failed: {r2.stderr or r2.stdout}"
        json_response(
            handler, {"ok": ok, "vmid": vmid, "nic": f"net{next_nic}", "ip": new_ip, "vlan": vlan_id_val, "error": err}
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm add-nic failed: {e}", endpoint="vm/add-nic")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_clear_nics(handler):
    """POST /api/vm/clear-nics — clear all NICs and ipconfigs from a VM."""
    if _require_post(handler, "VM clear NICs"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    if not vmid:
        json_response(handler, {"error": "vmid required"})
        return
    allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return

    try:
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "no PVE node reachable"})
            return

        # Get current VM config to find existing NICs
        r = ssh_single(
            host=node_ip,
            command=f"sudo qm config {vmid}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=15,
            htype="pve",
            use_sudo=False,
        )

        deleted = []
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                line = line.strip()
                if ":" not in line:
                    continue
                key = line.split(":")[0].strip()
                if key.startswith("ipconfig") or key.startswith("net"):
                    r2 = ssh_single(
                        host=node_ip,
                        command=f"sudo qm set {vmid} --delete {key}",
                        key_path=cfg.ssh_key_path,
                        connect_timeout=3,
                        command_timeout=15,
                        htype="pve",
                        use_sudo=False,
                    )
                    if r2.returncode == 0:
                        deleted.append(key)

        json_response(handler, {"ok": True, "vmid": vmid, "cleared": deleted, "count": len(deleted)})
    except Exception as e:
        logger.error(f"api_vm_error: vm clear-nics failed: {e}", endpoint="vm/clear-nics")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_change_ip(handler):
    """POST /api/vm/change-ip — change VM IP via cloud-init or manual config."""
    if _require_post(handler, "VM change IP"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = query.get("vmid", [""])[0]
    new_ip = query.get("ip", [""])[0]
    gateway = query.get("gw", [""])[0]
    if not vmid or not new_ip:
        json_response(handler, {"error": "vmid and ip parameters required"})
        return
    bare_ip = new_ip.split("/")[0] if "/" in new_ip else new_ip
    if not valid_ip(bare_ip):
        json_response(handler, {"error": "Invalid IP address"})
        return
    if gateway and not valid_ip(gateway):
        json_response(handler, {"error": "Invalid gateway IP"})
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return

    # Create the virtual NIC (net*) with VLAN tag + set cloud-init IP (ipconfig*)
    try:
        nic_idx = int(query.get("nic", ["0"])[0])
    except ValueError:
        json_response(handler, {"error": "Invalid NIC index"})
        return
    vlan_id_val = query.get("vlan", [""])[0]
    if vlan_id_val and not valid_vlan(vlan_id_val):
        json_response(handler, {"error": "Invalid VLAN ID"})
        return
    try:
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "no PVE node reachable"})
            return

        cidr = new_ip if "/" in new_ip else new_ip + "/24"
        gw_part = f",gw={gateway}" if gateway else ""

        # Create net entry — virtio on bridge with VLAN tag
        tag_part = f",tag={vlan_id_val}" if vlan_id_val else ""
        r1 = ssh_single(
            host=node_ip,
            command=f"sudo qm set {vmid} --net{nic_idx} virtio,bridge={cfg.nic_bridge}{tag_part}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        # Set cloud-init ipconfig
        r2 = ssh_single(
            host=node_ip,
            command=f"sudo qm set {vmid} --ipconfig{nic_idx} ip={cidr}{gw_part}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        ok = r1.returncode == 0 and r2.returncode == 0
        err = ""
        if r1.returncode != 0:
            err = f"NIC create failed: {r1.stderr or r1.stdout}"
        elif r2.returncode != 0:
            err = f"IP config failed: {r2.stderr or r2.stdout}"
        json_response(handler, {"ok": ok, "vmid": vmid, "ip": new_ip, "nic": nic_idx, "error": err})
    except Exception as e:
        logger.error(f"api_vm_error: vm change-ip failed: {e}", endpoint="vm/change-ip")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_push_key(handler):
    """GET /api/vm/push-key — push the freq SSH key to a target VM."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err})
        return
    cfg = load_config()
    from urllib.parse import urlparse, parse_qs

    raw = parse_qs(urlparse(handler.path).query)
    query = {k: v[0] if v else "" for k, v in raw.items()}
    target_ip = query.get("ip", "")
    if not target_ip or not valid_ip(target_ip):
        json_response(handler, {"error": "Valid IP required"})
        return

    # Read the public key
    pub_path = cfg.ssh_key_path + ".pub"
    if not os.path.isfile(pub_path):
        json_response(handler, {"error": f"Public key not found: {pub_path}"})
        return
    with open(pub_path) as f:
        pubkey = f.read().strip()
    if not pubkey:
        json_response(handler, {"error": "Public key file is empty"})
        return

    # SSH as service account (who has sudo) to write the key
    svc_account = cfg.ssh_service_account
    escaped_key = pubkey.replace('"', '\\"')
    cmd = (
        f"sudo mkdir -p /home/{svc_account}/.ssh && "
        f'echo "{escaped_key}" | sudo tee /home/{svc_account}/.ssh/authorized_keys > /dev/null && '
        f"sudo chown -R {svc_account}:{svc_account} /home/{svc_account}/.ssh && "
        f"sudo chmod 700 /home/{svc_account}/.ssh && "
        f"sudo chmod 600 /home/{svc_account}/.ssh/authorized_keys"
    )
    r = ssh_single(
        host=target_ip,
        command=cmd,
        user=svc_account,
        key_path=cfg.ssh_key_path,
        connect_timeout=5,
        command_timeout=15,
        htype="linux",
        use_sudo=False,
    )
    if r.returncode != 0:
        json_response(handler, {"error": f"Key push failed: {r.stderr or r.stdout}"})
        return

    # Verify: try connecting as freq-admin with the freq key
    r2 = ssh_single(
        host=target_ip,
        command="echo ok",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=5,
        htype="docker",
        use_sudo=False,
    )
    verified = r2.returncode == 0 and "ok" in (r2.stdout or "")
    json_response(handler, {"ok": True, "verified": verified, "ip": target_ip})


def handle_vm_add_disk(handler):
    """GET /api/vm/add-disk — add a disk to a VM."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = int(params.get("vmid", ["0"])[0])
    size = params.get("size", [""])[0]  # e.g. "32G"
    storage = params.get("storage", [""])[0]

    if not vmid or not size:
        json_response(handler, {"error": "vmid and size required"})
        return

    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return

    # Validate size format
    if not re.match(r"^\d+[GMTgmt]?$", size):
        json_response(handler, {"error": "Invalid size (e.g. '32G', '100')"})
        return

    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return

        # Find next available scsi slot
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
        if not ok:
            json_response(handler, {"error": f"Cannot read VM config: {stdout}"})
            return

        next_idx = 0
        for line in stdout.split("\n"):
            if line.startswith("scsi") and ":" in line:
                key = line.split(":")[0]
                try:
                    idx = int(key.replace("scsi", ""))
                    if idx >= next_idx:
                        next_idx = idx + 1
                except ValueError:
                    pass

        storage_target = storage or "local-lvm"
        cmd = f"qm set {vmid} --scsi{next_idx} {storage_target}:{size}"
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=60)
        json_response(
            handler,
            {
                "ok": ok,
                "vmid": vmid,
                "disk": f"scsi{next_idx}",
                "size": size,
                "storage": storage_target,
                "error": stdout if not ok else "",
            },
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm add-disk failed: {e}", endpoint="vm/add-disk")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_tag(handler):
    """POST /api/vm/tag — set PVE tags on a VM."""
    if _require_post(handler, "VM tag"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = int(params.get("vmid", ["0"])[0])
    tags = params.get("tags", [""])[0]  # comma-separated

    if not vmid:
        json_response(handler, {"error": "vmid required"})
        return

    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err})
        return

    # Validate tag names
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag and not re.match(r"^[a-zA-Z0-9_-]+$", tag):
                json_response(handler, {"error": f"Invalid tag name: {tag}"})
                return

    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return

        # PVE uses semicolon-separated tags
        pve_tags = ";".join(t.strip() for t in tags.split(",") if t.strip()) if tags else ""
        cmd = f'qm set {vmid} --tags "{pve_tags}"'
        stdout, ok = _pve_cmd(cfg, node_ip, cmd)
        json_response(
            handler,
            {
                "ok": ok,
                "vmid": vmid,
                "tags": tags,
                "error": stdout if not ok else "",
            },
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm tag failed: {e}", endpoint="vm/tag")
        json_response(handler, {"error": f"SSH operation failed: {e}"})


def handle_vm_clone(handler):
    """POST /api/vm/clone — clone a VM."""
    if _require_post(handler, "VM clone"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    source_vmid = int(params.get("vmid", ["0"])[0])
    name = params.get("name", [""])[0]
    target_node = params.get("target_node", [""])[0]
    full = params.get("full", ["1"])[0] == "1"

    if not source_vmid:
        json_response(handler, {"error": "vmid (source) required"})
        return

    allowed, err = _check_vm_permission(cfg, source_vmid, "clone")
    if not allowed:
        json_response(handler, {"error": err})
        return

    try:
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"})
            return

        # Get next available VMID
        stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
        if not ok:
            json_response(handler, {"error": "Cannot get next VMID"})
            return
        new_vmid = stdout.strip()

        parts = [f"qm clone {source_vmid} {new_vmid}"]
        if name:
            from freq.core.validate import shell_safe_name

            if not shell_safe_name(name):
                json_response(handler, {"error": f"Invalid VM name: {name}"})
                return
            parts.append(f"--name {name}")
        if target_node:
            parts.append(f"--target {target_node}")
        if full:
            parts.append("--full")

        cmd = " ".join(parts)
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=300)
        json_response(
            handler,
            {
                "ok": ok,
                "source_vmid": source_vmid,
                "new_vmid": int(new_vmid),
                "name": name,
                "full_clone": full,
                "error": stdout if not ok else "",
            },
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm clone failed: {e}", endpoint="vm/clone")
        json_response(handler, {"error": f"Clone failed: {e}"})


def handle_vm_migrate(handler):
    """GET /api/vm/migrate — live migrate a VM to another node.

    Uses --with-local-disks for direct node-to-node transfer.
    Auto-detects best local storage on target. Checks for snapshots
    that would block live migration.
    """
    if _require_post(handler, "VM migrate"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = int(params.get("vmid", ["0"])[0])
    target_node = params.get("target_node", [""])[0]
    delete_snaps = params.get("delete_snapshots", ["0"])[0] == "1"

    if not vmid or not target_node:
        json_response(handler, {"error": "vmid and target_node required"})
        return

    allowed, err = _check_vm_permission(cfg, vmid, "migrate")
    if not allowed:
        json_response(handler, {"error": err})
        return

    if not re.match(r"^[a-zA-Z0-9_-]+$", target_node):
        json_response(handler, {"error": f"Invalid node name: {target_node}"})
        return

    try:
        from freq.modules.vm import _find_vm_node, _find_best_local_storage, _check_snapshots, _delete_snapshots

        # Find source node
        source_ip = _find_vm_node(cfg, vmid)
        if not source_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"})
            return

        # Resolve source node name
        source_node = "unknown"
        for i, ip in enumerate(cfg.pve_nodes):
            if ip == source_ip and i < len(cfg.pve_node_names):
                source_node = cfg.pve_node_names[i]
                break

        if source_node == target_node:
            json_response(handler, {"error": f"VM {vmid} is already on {target_node}"})
            return

        # Check snapshots — they block live migration
        snapshots = _check_snapshots(cfg, source_ip, vmid)
        if snapshots and not delete_snaps:
            json_response(
                handler,
                {
                    "error": "snapshots_block_migration",
                    "snapshots": snapshots,
                    "count": len(snapshots),
                    "message": f"VM has {len(snapshots)} snapshot(s) that block live migration. Resend with delete_snapshots=1 to remove them.",
                },
            )
            return

        if snapshots and delete_snaps:
            _delete_snapshots(cfg, source_ip, vmid, snapshots)

        # Auto-detect best local storage on target
        target_storage = _find_best_local_storage(cfg, source_ip, target_node)

        # Build migration command — direct node-to-node, no NFS middleman
        migrate_cmd = f"qm migrate {vmid} {target_node} --with-local-disks --online"
        if target_storage:
            migrate_cmd += f" --targetstorage {target_storage}"

        stdout, ok = _pve_cmd(cfg, source_ip, migrate_cmd, timeout=600)

        # Fall back to offline if VM is stopped
        if not ok and "not running" in (stdout or "").lower():
            migrate_cmd = f"qm migrate {vmid} {target_node} --with-local-disks"
            if target_storage:
                migrate_cmd += f" --targetstorage {target_storage}"
            stdout, ok = _pve_cmd(cfg, source_ip, migrate_cmd, timeout=600)

        json_response(
            handler,
            {
                "ok": ok,
                "vmid": vmid,
                "source_node": source_node,
                "target_node": target_node,
                "target_storage": target_storage or "default",
                "online": True,
                "with_local_disks": True,
                "snapshots_deleted": len(snapshots) if delete_snaps and snapshots else 0,
                "error": stdout if not ok else "",
            },
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm migrate failed: {e}", endpoint="vm/migrate")
        json_response(handler, {"error": f"Migration failed: {e}"})


def handle_vm_wizard_defaults(handler):
    """GET /api/vm/wizard-defaults — defaults for VM creation wizard."""
    cfg = load_config()
    profiles = getattr(cfg, "template_profiles", {})
    json_response(
        handler,
        {
            "defaults": {
                "cores": cfg.vm_default_cores,
                "ram": cfg.vm_default_ram,
                "disk": cfg.vm_default_disk,
                "cpu": cfg.vm_cpu,
            },
            "profiles": profiles,
            "nodes": cfg.pve_node_names,
            "vlans": [{"name": v.name, "id": v.id, "subnet": v.subnet} for v in cfg.vlans],
            "distros": [{"key": d.key, "name": d.name} for d in cfg.distros],
        },
    )


def handle_pool(handler):
    """GET /api/pool — list PVE pools."""
    cfg = load_config()
    pools = []
    for ip in _get_discovered_node_ips():
        r = ssh_single(
            host=ip,
            command="sudo pvesh get /pools --output-format json 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=15,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode == 0:
            try:
                pools = json.loads(r.stdout)
            except json.JSONDecodeError:
                pass
            break
    json_response(handler, {"pools": pools})


def handle_rollback(handler):
    """POST /api/rollback — roll back a VM to a snapshot (admin only)."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    params = get_params(handler)
    vmid_str = params.get("vmid", [""])[0]
    snap_name = params.get("name", [""])[0]
    start_after = params.get("start", ["true"])[0].lower() != "false"

    if not vmid_str:
        json_response(handler, {"error": "vmid parameter required"}, 400)
        return
    try:
        vmid = int(vmid_str)
    except ValueError:
        json_response(handler, {"error": f"Invalid VMID: {vmid_str}"}, 400)
        return

    cfg = load_config()

    if is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges):
        json_response(handler, {"error": f"VMID {vmid} is protected"}, 403)
        return
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        json_response(handler, {"error": "Cannot reach any PVE node"}, 503)
        return

    # Get snapshots
    snap_out, snap_ok = _pve_cmd(cfg, node_ip, f"qm listsnapshot {vmid}", timeout=10)
    if not snap_ok:
        json_response(handler, {"error": f"Cannot list snapshots for VM {vmid}"}, 500)
        return

    snaps = []
    for line in snap_out.strip().split("\n"):
        line = line.strip().lstrip("`->").strip()
        if line and "current" not in line.lower():
            parts = line.split()
            if parts:
                snaps.append(parts[0])

    if not snaps:
        json_response(handler, {"error": f"No snapshots found for VM {vmid}"})
        return

    if not snap_name:
        snap_name = snaps[-1]
    elif snap_name not in snaps:
        json_response(handler, {"error": f"Snapshot '{snap_name}' not found", "available": snaps})
        return

    # Get current status
    status_out, _ = _pve_cmd(cfg, node_ip, f"qm status {vmid}", timeout=5)
    was_running = "running" in (status_out or "").lower()

    # Stop if running
    if was_running:
        _pve_cmd(cfg, node_ip, f"qm stop {vmid}", timeout=60)
        import time

        for _ in range(30):
            time.sleep(1)
            s_out, _ = _pve_cmd(cfg, node_ip, f"qm status {vmid}", timeout=5)
            if "stopped" in (s_out or "").lower():
                break

    # Rollback
    rb_out, rb_ok = _pve_cmd(cfg, node_ip, f"qm rollback {vmid} {snap_name}", timeout=120)
    if not rb_ok:
        json_response(handler, {"error": f"Rollback failed: {rb_out}", "snapshot": snap_name}, 500)
        return

    # Start back up if requested
    started = False
    if start_after:
        st_out, st_ok = _pve_cmd(cfg, node_ip, f"qm start {vmid}", timeout=60)
        started = st_ok

    json_response(
        handler,
        {
            "ok": True,
            "vmid": vmid,
            "snapshot": snap_name,
            "was_running": was_running,
            "started": started,
            "available_snapshots": snaps,
        },
    )


def handle_snapshots_stale(handler):
    """GET /api/snapshots/stale — find VM snapshots older than threshold."""
    cfg = load_config()
    from freq.core.ssh import run as ssh_fn

    from urllib.parse import urlparse, parse_qs

    raw = parse_qs(urlparse(handler.path).query)
    params = {k: v[0] if v else "" for k, v in raw.items()}
    try:
        days = int(params.get("days", "30"))
    except (ValueError, TypeError):
        days = 30

    stale = []
    for i, node_ip in enumerate(cfg.pve_nodes):
        node_name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"node{i}"
        # Get all VMIDs
        r = ssh_fn(
            host=node_ip,
            command="sudo qm list 2>/dev/null | tail -n +2 | awk '{print $1, $2}'",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode != 0:
            continue

        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) < 2:
                continue
            vm_id = parts[0]
            vm_name = parts[1]

            # Get snapshots for this VM
            sr = ssh_fn(
                host=node_ip,
                command=f"sudo qm listsnapshot {vm_id} 2>/dev/null | grep -v current | grep -v '^$'",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=15,
                htype="pve",
                use_sudo=False,
            )
            if sr.returncode != 0 or not sr.stdout.strip():
                continue

            for sline in sr.stdout.strip().split("\n"):
                sline = sline.strip()
                if not sline or sline.startswith("`") or "current" in sline.lower():
                    continue
                # Parse snapshot line
                sparts = sline.replace("`->", "").strip().split()
                if len(sparts) >= 1:
                    snap_name = sparts[0]
                    snap_date = " ".join(sparts[1:3]) if len(sparts) >= 3 else ""
                    # Filter by age — only include snapshots older than threshold
                    import datetime

                    is_stale = True  # Default to stale if date can't be parsed
                    if snap_date:
                        try:
                            snap_dt = datetime.datetime.strptime(snap_date, "%Y-%m-%d %H:%M:%S")
                            age_days = (datetime.datetime.now() - snap_dt).days
                            is_stale = age_days >= days
                        except ValueError:
                            pass
                    if is_stale:
                        stale.append(
                            {
                                "vmid": int(vm_id),
                                "vm_name": vm_name,
                                "snapshot": snap_name,
                                "date": snap_date,
                                "node": node_name,
                            }
                        )

    json_response(
        handler,
        {
            "stale": stale,
            "count": len(stale),
            "threshold_days": days,
        },
    )


# ── Route Registration ──────────────────────────────────────────────────


def register(routes: dict):
    """Register VM API routes into the master route table.

    These routes use the same /api/ paths as the legacy serve.py handlers.
    The dispatch in serve.py checks _ROUTES first, then _V1_ROUTES. By
    removing these paths from _ROUTES, dispatch falls through to here.
    """
    routes["/api/vms"] = handle_vm_list
    routes["/api/vm/create"] = handle_vm_create
    routes["/api/vm/destroy"] = handle_vm_destroy
    routes["/api/vm/snapshot"] = handle_vm_snapshot
    routes["/api/vm/resize"] = handle_vm_resize
    routes["/api/vm/power"] = handle_vm_power
    routes["/api/vm/template"] = handle_vm_template
    routes["/api/vm/rename"] = handle_vm_rename
    routes["/api/vm/snapshots"] = handle_vm_snapshots
    routes["/api/vm/delete-snapshot"] = handle_vm_delete_snapshot
    routes["/api/vm/change-id"] = handle_vm_change_id
    routes["/api/vm/check-ip"] = handle_vm_check_ip
    routes["/api/vm/add-nic"] = handle_vm_add_nic
    routes["/api/vm/clear-nics"] = handle_vm_clear_nics
    routes["/api/vm/change-ip"] = handle_vm_change_ip
    routes["/api/vm/push-key"] = handle_vm_push_key
    routes["/api/vm/add-disk"] = handle_vm_add_disk
    routes["/api/vm/tag"] = handle_vm_tag
    routes["/api/vm/clone"] = handle_vm_clone
    routes["/api/vm/migrate"] = handle_vm_migrate
    routes["/api/vm/wizard-defaults"] = handle_vm_wizard_defaults
    routes["/api/pool"] = handle_pool
    routes["/api/rollback"] = handle_rollback
    routes["/api/snapshots/stale"] = handle_snapshots_stale
