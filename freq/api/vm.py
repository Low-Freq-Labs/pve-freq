"""VM domain API handlers — /api/vm/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for virtual machine lifecycle operations.
Why:   Decouples VM logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/vm/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.

Maps 1:1 to `freq vm` CLI domain. Each handler is a standalone function
that receives the HTTP handler as its first argument.
"""

import ipaddress
import json
import os
import re
import shlex
import subprocess
import threading
import time
import uuid

from freq.api.helpers import get_json_body, get_params, json_response
from freq.core import log as logger
from freq.core.config import load_config, save_network_profiles_toml
from freq.core.ssh import run as ssh_single
from freq.core.types import VLAN
from freq.core.validate import (
    ip as valid_ip,
)
from freq.core.validate import (
    is_protected_vmid,
)
from freq.core.validate import (
    label as valid_label,
)
from freq.core.validate import (
    vlan_id as valid_vlan,
)
from freq.modules.pve import _find_reachable_node, _find_vm_node, _pve_cmd
from freq.modules.serve import (
    _check_session_role,
    _check_vm_permission,
    _get_discovered_node_ips,
    _get_fleet_vms,
    get_vm_tags,
)

_vm_create_jobs = {}
_vm_create_jobs_lock = threading.Lock()
_VM_CREATE_JOB_TAIL = 400
_vm_create_options_cache = {"ts": 0.0, "payload": None}
_VM_CREATE_OPTIONS_TTL = 30


def _require_post(handler, action="this operation"):
    """Reject non-POST requests for destructive operations."""
    if handler.command != "POST":
        json_response(handler, {"error": f"{action} requires POST"}, 405)
        return True
    return False


def _get_int_param(handler, params, key, default=None, required=False):
    """Parse an integer query parameter and return None after responding on error."""
    raw_default = "" if required else ("" if default is None else str(default))
    raw = params.get(key, [raw_default])[0]
    if raw in ("", None):
        if required:
            json_response(handler, {"error": f"{key} parameter required"}, 400)
            return None
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        json_response(handler, {"error": f"Invalid {key}: {raw}"}, 400)
        return None


def _find_vm_node_ip(cfg, vmid: int) -> str:
    """Resolve the actual PVE node for an existing VM."""
    return _find_vm_node(cfg, vmid, "")


def _node_name_for_ip(cfg, node_ip: str) -> str:
    """Resolve configured PVE node name for a node IP."""
    for idx, ip in enumerate(getattr(cfg, "pve_nodes", []) or []):
        if ip == node_ip and idx < len(getattr(cfg, "pve_node_names", []) or []):
            return cfg.pve_node_names[idx]
    return ""


def _configured_image_storage(cfg, node_ip: str) -> str:
    """Return the configured image storage pool for a node, if any."""
    node_name = _node_name_for_ip(cfg, node_ip)
    storage_map = getattr(cfg, "pve_storage", {}) or {}
    if node_name and isinstance(storage_map.get(node_name), dict):
        pool = str(storage_map[node_name].get("pool", "") or "").strip()
        if pool:
            return pool
    pools = [
        str(info.get("pool", "") or "").strip()
        for info in storage_map.values()
        if isinstance(info, dict) and str(info.get("pool", "") or "").strip()
    ]
    return pools[0] if len(set(pools)) == 1 else ""


def _discover_image_storage(cfg, node_ip: str) -> str:
    """Best-effort live storage discovery for image-capable PVE storage."""
    rows = _node_image_storage_options(cfg, node_ip)
    if rows:
        return rows[0]["id"]
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesm status --content images --enabled 1", timeout=15)
    if ok and stdout:
        parsed = []
        for line in stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3 and parts[2] == "active":
                parsed.append(parts[0])
        for preferred in ("local-zfs", "local-lvm"):
            if preferred in parsed:
                return preferred
        if parsed:
            return parsed[0]
    return ""


def _node_image_storage_options(cfg, node_ip: str):
    """Return enabled image-capable storage pools for a specific PVE node."""
    node_name = _node_name_for_ip(cfg, node_ip)
    if not node_name:
        return []
    stdout, ok = _pve_cmd(
        cfg,
        node_ip,
        f"pvesh get /nodes/{shlex.quote(node_name)}/storage --content images --output-format json",
        timeout=15,
    )
    if ok and stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, list):
                rows = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    storage = str(item.get("storage", "") or "").strip()
                    if not storage:
                        continue
                    if int(item.get("enabled", 1) or 0) != 1 or int(item.get("active", 1) or 0) != 1:
                        continue
                    content = str(item.get("content", "") or "")
                    if "images" not in {part.strip() for part in content.split(",")}:
                        continue
                    rows.append(
                        {
                            "id": storage,
                            "label": storage,
                            "node": node_name,
                            "type": str(item.get("type", "") or ""),
                            "shared": bool(item.get("shared", 0)),
                        }
                    )
                rows.sort(key=lambda row: (1 if row.get("shared") else 0, 0 if row.get("type") in {"zfspool", "lvmthin"} else 1, row["id"]))
                return rows
        except (TypeError, json.JSONDecodeError):
            pass
    return []


def _default_image_storage(cfg, node_ip: str) -> str:
    """Choose the storage pool for VM disks without hardcoding a lab-only default."""
    return _configured_image_storage(cfg, node_ip) or _discover_image_storage(cfg, node_ip) or "local-lvm"


def _resolve_target_storage(cfg, node_ip: str, requested: str):
    """Return a node-valid image storage pool plus any warning."""
    requested = str(requested or "").strip()
    live_rows = _node_image_storage_options(cfg, node_ip) if node_ip else []
    if not live_rows:
        return requested or _default_image_storage(cfg, node_ip), ""
    live_ids = {row["id"] for row in live_rows}
    if requested and requested in live_ids:
        return requested, ""
    fallback = live_rows[0]["id"]
    if requested:
        return fallback, f"requested storage {requested} is not enabled for images on target node; using {fallback}"
    return fallback, ""


def _existing_vm_disk_storage(config_text: str) -> str:
    """Return the storage ID used by an existing VM disk, if visible."""
    preferred_prefixes = ("scsi", "virtio", "sata", "ide")
    for line in (config_text or "").splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if not key.startswith(preferred_prefixes):
            continue
        disk_ref = value.strip().split(",", 1)[0]
        if ":" in disk_ref:
            storage = disk_ref.split(":", 1)[0].strip()
            if storage:
                return storage
    return ""


def _normalize_disk_allocation_size(size: str):
    """Return Proxmox qm allocation size in GB, or an error string."""
    raw = str(size or "").strip()
    match = re.match(r"^(\d+)\s*([GgTt]?[Bb]?)?$", raw)
    if not match:
        return "", "Invalid size (use whole GB/TB, e.g. '32G' or '1T')"
    value = int(match.group(1))
    unit = (match.group(2) or "G").lower().rstrip("b")
    if value <= 0:
        return "", "Invalid size (must be greater than zero)"
    if unit in ("", "g"):
        return str(value), ""
    if unit == "t":
        return str(value * 1024), ""
    return "", "Invalid size (use whole GB/TB, e.g. '32G' or '1T')"


def _parse_qm_snapshot_names(output: str):
    """Parse snapshot names from `qm listsnapshot` tree output."""
    snaps = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[`|\\/\s-]*>\s*", "", line)
        line = re.sub(r"^[`|\\/\s-]+", "", line).strip()
        if not line:
            continue
        parts = line.split()
        if not parts:
            continue
        name = parts[0].strip()
        if name and name.lower() != "current":
            snaps.append(name)
    return snaps


def _clear_health_backoff_for_vmid(cfg, vmid: int):
    """Let health re-probe a VM immediately after an operator starts it.

    A stopped VM can legitimately time out long enough to trip the health
    circuit breaker. Once the VM power action succeeds, keeping the old backoff
    hides recovery from the dashboard even though the operator explicitly
    brought the VM back.
    """
    ips = {
        h.ip
        for h in getattr(cfg, "hosts", [])
        if getattr(h, "vmid", 0) == vmid and getattr(h, "ip", "")
    }
    for vm in getattr(cfg, "container_vms", {}).values():
        if getattr(vm, "vm_id", 0) == vmid and getattr(vm, "ip", ""):
            ips.add(vm.ip)
    if not ips:
        return
    try:
        from freq.modules import serve as serve_module

        with serve_module._bg_lock:
            for ip in ips:
                serve_module._host_fail_count.pop(ip, None)
                serve_module._host_backoff_until.pop(ip, None)
                serve_module._host_backoff_started_at.pop(ip, None)
                serve_module._host_last_error.pop(ip, None)
                serve_module._host_recovering.add(ip)
        logger.info("vm_power_cleared_health_backoff", vmid=vmid, ips=",".join(sorted(ips)))
    except Exception as e:
        logger.warn(f"vm_power: failed to clear health backoff for VM {vmid}: {e}")


def _parse_next_vmid(raw_value: str) -> int:
    """Parse the cluster next VMID output safely."""
    try:
        return int((raw_value or "").strip())
    except (ValueError, TypeError):
        return 0


def _cluster_existing_vmids(cfg, node_ip: str):
    """Return cluster VMIDs, or (None, error) when the list cannot be trusted."""
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/resources --type vm --output-format json")
    if not ok:
        return None, (stdout or "").strip() or "cluster resource lookup failed"
    try:
        rows = json.loads(stdout or "[]")
    except (TypeError, json.JSONDecodeError) as e:
        return None, f"cluster resource lookup returned invalid JSON: {e}"
    if not isinstance(rows, list):
        return None, "cluster resource lookup returned non-list JSON"
    existing = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            existing.add(int(row.get("vmid")))
        except (TypeError, ValueError):
            continue
    return existing, ""


def _create_vmid_ranges(cfg):
    """Return configured VMID ranges where new VMs may be configured."""
    ranges = []
    categories = getattr(getattr(cfg, "fleet_boundaries", None), "categories", {}) or {}
    preferred_order = {"sandbox": 0, "test": 1, "lab": 2, "dev": 3}
    for name, cat in categories.items():
        if not isinstance(cat, dict):
            continue
        start = cat.get("range_start")
        end = cat.get("range_end")
        try:
            start = int(start)
            end = int(end)
        except (TypeError, ValueError):
            continue
        if start <= 0 or end < start:
            continue
        allowed, _ = _check_vm_permission(cfg, start, "configure")
        if not allowed:
            continue
        ranges.append((preferred_order.get(str(name).lower(), 50), start, end, str(name)))
    return sorted(ranges)


def _allocate_create_vmid(cfg, node_ip: str):
    """Allocate an allowed VMID for first-class create without trusting low nextid."""
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
    if not ok:
        return 0, "cluster-nextid", f"cannot allocate VMID: {(stdout or '').strip() or 'cluster nextid failed'}"
    next_vmid = _parse_next_vmid(stdout)
    if next_vmid <= 0:
        return 0, "cluster-nextid", f"Invalid next VMID from cluster: {(stdout or '').strip() or 'empty'}"
    allowed, _ = _check_vm_permission(cfg, next_vmid, "configure")
    if allowed:
        return next_vmid, "cluster-nextid", ""

    existing, err = _cluster_existing_vmids(cfg, node_ip)
    if existing is None:
        return 0, "fleet-boundary-range", f"cannot safely allocate allowed VMID after cluster nextid {next_vmid}: {err}"
    for _order, start, end, name in _create_vmid_ranges(cfg):
        for candidate in range(start, end + 1):
            if candidate in existing:
                continue
            allowed, perm_err = _check_vm_permission(cfg, candidate, "configure")
            if allowed:
                return candidate, f"{name}-range", ""
            return 0, f"{name}-range", f"configured create range {name} is not allowed: {perm_err}"
    return 0, "fleet-boundary-range", f"cluster nextid {next_vmid} is outside create policy and no free configure-capable VMID range is configured"


def _respond_operation(handler, payload, ok, failure_status=502):
    """Return 200 on success and a real error status when the backend action failed."""
    json_response(handler, payload, 200 if ok else failure_status)


def _refresh_fleet_overview_after_mutation(reason: str, vmid: int = 0):
    """Refresh dashboard VM truth after a successful PVE mutation."""
    def _run():
        try:
            from freq.modules import serve as serve_module

            serve_module._bg_probe_fleet_overview()
            logger.info("vm_mutation_refreshed_fleet_overview", reason=reason, vmid=vmid)
        except Exception as e:
            logger.warn(f"vm mutation {reason}: fleet overview refresh failed for VM {vmid}: {e}")

    try:
        threading.Thread(target=_run, name=f"freq-fleet-refresh-{reason}", daemon=True).start()
    except Exception as e:
        logger.warn(f"vm mutation {reason}: fleet overview refresh schedule failed for VM {vmid}: {e}")


def _patch_fleet_overview_vm_status(vmid: int, status: str):
    """Patch cached fleet VM status immediately after a successful power action."""
    if status not in {"running", "stopped"}:
        return
    try:
        from freq.modules import serve as serve_module

        with serve_module._bg_lock:
            fleet = serve_module._bg_cache.get("fleet_overview")
            if not isinstance(fleet, dict):
                return
            changed = False
            for vm in fleet.get("vms", []) or []:
                if int(vm.get("vmid", 0) or 0) == int(vmid):
                    vm["status"] = status
                    changed = True
                    break
            if not changed:
                return
            non_template = [v for v in fleet.get("vms", []) or [] if v.get("category") != "templates"]
            running = sum(1 for v in non_template if v.get("status") == "running")
            stopped = sum(1 for v in non_template if v.get("status") == "stopped")
            summary = fleet.setdefault("summary", {})
            summary["running"] = running
            summary["stopped"] = stopped
            serve_module._bg_cache_ts["fleet_overview"] = time.time()
        try:
            serve_module._sse_broadcast("cache_update", {"key": "fleet_overview", "ts": time.time()})
            serve_module._sse_broadcast("vm_state", {"vmid": vmid, "new": status})
        except Exception:
            pass
        logger.info("vm_power_patched_fleet_overview", vmid=vmid, status=status)
    except Exception as e:
        logger.warn(f"vm power: failed to patch fleet overview status for VM {vmid}: {e}")


def _respond_vm_mutation(handler, payload, ok, reason: str, vmid: int = 0, failure_status=502):
    """Return a VM mutation response after bringing dashboard cache up to date."""
    if ok:
        _refresh_fleet_overview_after_mutation(reason, vmid)
    _respond_operation(handler, payload, ok, failure_status=failure_status)


def _token_param(value: str, label: str):
    """Return a shell-safe Proxmox token or an error message."""
    if not value:
        return "", ""
    if not re.match(r"^[A-Za-z0-9_.:-]+$", value):
        return "", f"Invalid {label}: {value}"
    return value, ""


def _node_ip_for_name(cfg, node_name: str) -> str:
    """Resolve a configured PVE node name to its IP."""
    if not node_name:
        return ""
    for idx, name in enumerate(getattr(cfg, "pve_node_names", []) or []):
        if name == node_name and idx < len(getattr(cfg, "pve_nodes", []) or []):
            return cfg.pve_nodes[idx]
    return ""


def _nic_index_param(handler, params, default=None):
    """Parse a netN index bounded to Proxmox's practical NIC range."""
    idx = _get_int_param(handler, params, "nic", default=default, required=default is None)
    if idx is None:
        return None
    if idx < 0 or idx > 31:
        json_response(handler, {"error": "Invalid nic index (0-31)"}, 400)
        return None
    return idx


def _parse_qm_config_kv(config_text: str) -> dict:
    """Parse `qm config` output into a key/value mapping."""
    config = {}
    for raw_line in (config_text or "").splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        if key:
            config[key] = value.strip()
    return config


def _parse_net_config(value: str) -> tuple[str, dict]:
    """Return the NIC model/MAC prefix and comma key-values from a netN line."""
    parts = [part.strip() for part in (value or "").split(",") if part.strip()]
    if not parts:
        return "virtio", {}
    first = parts[0]
    opts = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        opts[key.strip()] = val.strip()
    if "=" not in first:
        return first or "virtio", opts
    first_key = first.split("=", 1)[0].strip()
    if first_key in {"bridge", "tag", "firewall", "rate", "queues", "link_down", "mtu"}:
        key, val = first.split("=", 1)
        opts[key.strip()] = val.strip()
        return "virtio", opts
    return first, opts


def _build_net_config(existing: str, bridge: str, vlan: str, firewall: str) -> str:
    """Build a netN value while preserving model/MAC where possible."""
    model, opts = _parse_net_config(existing)
    opts["bridge"] = bridge
    if vlan:
        opts["tag"] = vlan
    else:
        opts.pop("tag", None)
    if firewall != "":
        opts["firewall"] = "1" if firewall in {"1", "true", "yes", "on"} else "0"
    ordered = [model]
    for key in ("bridge", "tag", "firewall", "rate", "queues", "link_down", "mtu"):
        if key in opts and opts[key] != "":
            ordered.append(f"{key}={opts[key]}")
    for key in sorted(k for k in opts if k not in {"bridge", "tag", "firewall", "rate", "queues", "link_down", "mtu"}):
        ordered.append(f"{key}={opts[key]}")
    return ",".join(ordered)


def _clone_source_allowed(cfg, vmid: int):
    """Allow read-only clone use of templates while keeping them mutation-protected."""
    cat_name, tier = cfg.fleet_boundaries.categorize(vmid)
    if cat_name == "templates":
        return True, ""
    return _check_vm_permission(cfg, vmid, "clone")


def _template_source(cfg, template_vmid: int):
    """Return the PVE node that owns a template/source VM."""
    if not template_vmid:
        return "", ""
    source_ip = _find_vm_node_ip(cfg, template_vmid)
    return _node_name_for_ip(cfg, source_ip) or "", source_ip or ""


def _coerce_int(value, default=0):
    try:
        if value in ("", None):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value, default=False):
    if value in ("", None):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _vm_create_body(handler):
    body = get_json_body(handler) if handler.command in {"POST", "PUT"} else {}
    if not isinstance(body, dict):
        body = {}
    params = get_params(handler)
    for key, values in params.items():
        if key not in body and values:
            body[key] = values[0]
    return body


def _node_options(cfg, storage_rows=None):
    storage_rows = storage_rows or []
    storage_by_node = {}
    for row in storage_rows:
        node = str(row.get("node", "") or "")
        if node and node not in storage_by_node:
            storage_by_node[node] = row.get("id") or row.get("storage") or row.get("label") or ""
    nodes = []
    for idx, ip in enumerate(getattr(cfg, "pve_nodes", []) or []):
        name = ""
        if idx < len(getattr(cfg, "pve_node_names", []) or []):
            name = cfg.pve_node_names[idx]
        name = name or f"node-{idx + 1}"
        nodes.append(
            {
                "name": name,
                "ip": ip,
                "storage": _configured_image_storage(cfg, ip) or storage_by_node.get(name) or _default_image_storage(cfg, ip),
                "default": idx == 0,
            }
        )
    return nodes


def _storage_options(cfg):
    seen = set()
    stores = []
    for node_name, info in (getattr(cfg, "pve_storage", {}) or {}).items():
        if not isinstance(info, dict):
            continue
        pool = str(info.get("pool", "") or "").strip()
        if not pool or pool in seen:
            continue
        seen.add(pool)
        stores.append({"id": pool, "label": pool, "node": node_name, "type": str(info.get("type", "") or "")})
    for node_ip in getattr(cfg, "pve_nodes", []) or []:
        for row in _node_image_storage_options(cfg, node_ip):
            key = (row["id"], row.get("node", ""))
            if key in seen:
                continue
            seen.add(key)
            stores.append(row)
    if not stores:
        stores.append({"id": "local-lvm", "label": "local-lvm", "node": "", "type": "fallback"})
    return stores


def _gateway_status(subnet, gateway):
    gateway = str(gateway or "").split("/", 1)[0]
    if not subnet or not gateway:
        return {"in_subnet": True, "warning": ""}
    try:
        net = ipaddress.ip_network(subnet, strict=False)
        in_subnet = ipaddress.ip_address(gateway) in net
    except ValueError:
        return {"in_subnet": False, "warning": f"gateway {gateway} cannot be validated against subnet {subnet}"}
    if in_subnet:
        return {"in_subnet": True, "warning": ""}
    return {
        "in_subnet": False,
        "warning": f"configured gateway {gateway} is outside advertised subnet {subnet}",
    }


def _vlan_options(cfg):
    rows = []
    for vlan in _vm_create_vlan_catalog(cfg):
        profile = _profile_by_key(cfg, str(getattr(vlan, "id", "") or getattr(vlan, "name", ""))) or {}
        gateway = getattr(vlan, "gateway", "") or getattr(cfg, "vm_gateway", "")
        gateway_source = "vlan" if getattr(vlan, "gateway", "") else ("global" if gateway else "")
        gateway_status = _gateway_status(getattr(vlan, "subnet", ""), gateway)
        rows.append(
            {
                "id": getattr(vlan, "id", 0),
                "name": getattr(vlan, "name", "") or f"VLAN{getattr(vlan, 'id', 0)}",
                "subnet": getattr(vlan, "subnet", ""),
                "prefix": getattr(vlan, "prefix", ""),
                "gateway": gateway,
                "gateway_source": gateway_source,
                "gateway_in_subnet": gateway_status["in_subnet"],
                "gateway_warning": gateway_status["warning"],
                "bridge": profile.get("bridge") or getattr(cfg, "nic_bridge", "vmbr0"),
                "network_profile": profile.get("id", ""),
            }
        )
    return rows


def _vm_create_vlan_catalog(cfg):
    """Return configured VM networks for the create wizard.

    VM Create must not infer VLAN IDs, gateways, or subnets from private IP
    shape. Those are site policy. Init/discovery can collect facts, but VM
    provisioning only plans against explicit VLAN/network-profile config.
    """
    by_id = {}
    for vlan in getattr(cfg, "vlans", []) or []:
        try:
            by_id[int(getattr(vlan, "id", 0))] = vlan
        except (TypeError, ValueError):
            continue
    return [by_id[k] for k in sorted(by_id)]


def _template_options(cfg):
    templates = []
    try:
        for vm in _get_fleet_vms(cfg):
            if vm.get("category") == "templates" or vm.get("template") is True:
                templates.append(
                    {
                        "vmid": vm.get("vmid"),
                        "name": vm.get("name") or vm.get("label") or f"template-{vm.get('vmid')}",
                        "node": vm.get("node", ""),
                        "status": vm.get("status", ""),
                        "source": "pve",
                    }
                )
    except Exception as e:
        logger.warn(f"vm_create_options: template discovery failed: {e}")
    return templates


def _distro_options(cfg):
    return [
        {
            "key": getattr(d, "key", ""),
            "name": getattr(d, "name", "") or getattr(d, "key", ""),
            "family": getattr(d, "family", ""),
            "tier": getattr(d, "tier", ""),
        }
        for d in (getattr(cfg, "distros", []) or [])
    ]


def _existing_ip_set(cfg):
    used = set()
    for host in getattr(cfg, "hosts", []) or []:
        for ip_value in [getattr(host, "ip", "")] + list(getattr(host, "all_ips", []) or []):
            ip_text = str(ip_value or "").split("/", 1)[0]
            if ip_text:
                used.add(ip_text)
    for ip_value in getattr(cfg, "pve_nodes", []) or []:
        if ip_value:
            used.add(str(ip_value))
    try:
        for vm in _get_fleet_vms(cfg):
            ip_value = str(vm.get("ip", "") or "").split("/", 1)[0]
            if ip_value:
                used.add(ip_value)
    except Exception:
        pass
    return used


def _reserved_host_octets(cfg):
    """Return globally-reserved IPv4 host octets for create suggestions.

    Sonny's operator rule: if .26 already means "pve01" anywhere in the
    managed estate, Create VM must not suggest .26 on another VLAN just
    because that subnet is technically open.
    """
    octets = set()
    for ip_text in _existing_ip_set(cfg):
        try:
            ip_obj = ipaddress.ip_address(str(ip_text).split("/", 1)[0])
        except ValueError:
            continue
        if ip_obj.version == 4:
            octets.add(int(str(ip_obj).rsplit(".", 1)[-1]))
    for vlan in getattr(cfg, "vlans", []) or []:
        gateway = str(getattr(vlan, "gateway", "") or "").split("/", 1)[0]
        try:
            ip_obj = ipaddress.ip_address(gateway)
        except ValueError:
            continue
        if ip_obj.version == 4:
            octets.add(int(str(ip_obj).rsplit(".", 1)[-1]))
    gateway = str(getattr(cfg, "vm_gateway", "") or "").split("/", 1)[0]
    try:
        ip_obj = ipaddress.ip_address(gateway)
        if ip_obj.version == 4:
            octets.add(int(str(ip_obj).rsplit(".", 1)[-1]))
    except ValueError:
        pass
    return octets


def _vlan_by_key(cfg, key):
    key_text = str(key or "").strip().lower()
    vlans = _vm_create_vlan_catalog(cfg)
    if not key_text and vlans:
        return vlans[0]
    for vlan in vlans:
        if key_text in {str(getattr(vlan, "id", "")).lower(), str(getattr(vlan, "name", "")).lower()}:
            return vlan
    return None


def _profile_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")


def _default_network_profile_for_vlan(cfg, vlan):
    vlan_id = int(getattr(vlan, "id", 0) or 0)
    name = getattr(vlan, "name", "") or f"VLAN{vlan_id}"
    pid = _profile_key(name) or f"vlan-{vlan_id}"
    return {
        "id": pid,
        "name": name,
        "vlan": vlan_id,
        "bridge": getattr(cfg, "nic_bridge", "vmbr0"),
        "purpose": "",
        "gateway_role": "",
        "description": "",
    }


def _network_profiles(cfg):
    """Return VM Create network profiles keyed by friendly profile id."""
    profiles = {}
    for vlan in _vm_create_vlan_catalog(cfg):
        profile = _default_network_profile_for_vlan(cfg, vlan)
        profiles[profile["id"]] = profile

    configured = getattr(cfg, "nic_profiles", {}) or {}
    if isinstance(configured, dict):
        for key, raw in configured.items():
            if not isinstance(raw, dict):
                continue
            pid = _profile_key(raw.get("id") or raw.get("key") or key)
            if not pid:
                continue
            base = profiles.get(pid, {})
            merged = dict(base)
            merged.update(
                {
                    "id": pid,
                    "name": raw.get("name") or base.get("name") or pid,
                    "vlan": raw.get("vlan", raw.get("vlan_id", base.get("vlan", ""))),
                    "bridge": raw.get("bridge") or base.get("bridge") or getattr(cfg, "nic_bridge", "vmbr0"),
                    "purpose": raw.get("purpose", base.get("purpose", "")),
                    "gateway_role": raw.get("gateway_role", base.get("gateway_role", "")),
                    "description": raw.get("description", base.get("description", "")),
                }
            )
            profiles[pid] = merged
    return profiles


def _profile_by_key(cfg, key):
    key_text = str(key or "").strip().lower()
    if not key_text:
        return None
    for profile in _network_profiles(cfg).values():
        matches = {
            str(profile.get("id", "")).lower(),
            str(profile.get("name", "")).lower(),
            str(profile.get("vlan", "")).lower(),
        }
        if key_text in matches:
            return profile
    return None


def _profile_vlan(cfg, profile):
    if not profile:
        return None
    vlan = _vlan_by_key(cfg, profile.get("vlan"))
    if vlan:
        return vlan
    try:
        vlan_id = int(profile.get("vlan", 0) or 0)
    except (TypeError, ValueError):
        vlan_id = 0
    if not vlan_id:
        return None
    name = str(profile.get("name") or f"VLAN{vlan_id}")
    return VLAN(id=vlan_id, name=name, subnet="", prefix="", gateway="")


def _network_profile_options(cfg):
    rows = []
    policy = _gateway_policy(cfg)
    def _sort_key(p):
        try:
            vlan_sort = int(p.get("vlan") or 0)
        except (TypeError, ValueError):
            vlan_sort = 0
        return vlan_sort, str(p.get("id", ""))

    for profile in sorted(_network_profiles(cfg).values(), key=_sort_key):
        vlan = _profile_vlan(cfg, profile)
        token = str(profile.get("vlan", "")).lower()
        gateway = getattr(vlan, "gateway", "") or getattr(cfg, "vm_gateway", "")
        gateway_role = str(profile.get("gateway_role") or "").strip().lower()
        if not gateway_role:
            gateway_role = "default" if token in policy["egress"] else "none" if token in policy["no_default"] else ""
        rows.append(
            {
                "id": profile.get("id", ""),
                "name": profile.get("name", ""),
                "purpose": profile.get("purpose", ""),
                "description": profile.get("description", ""),
                "vlan_id": getattr(vlan, "id", profile.get("vlan", "")) if vlan else profile.get("vlan", ""),
                "vlan_name": getattr(vlan, "name", "") if vlan else "",
                "subnet": getattr(vlan, "subnet", "") if vlan else "",
                "prefix": getattr(vlan, "prefix", "") if vlan else "",
                "gateway": gateway,
                "gateway_role": gateway_role,
                "bridge": profile.get("bridge") or getattr(cfg, "nic_bridge", "vmbr0"),
                "tag": str(profile.get("vlan", "") or ""),
                "advanced_label": f"{profile.get('bridge') or getattr(cfg, 'nic_bridge', 'vmbr0')}" + (f" tag {profile.get('vlan')}" if str(profile.get("vlan", "")).strip() else ""),
            }
        )
    return rows


def _candidate_ip_available(ip_text):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", ip_text], capture_output=True, timeout=3)
        return r.returncode != 0
    except (subprocess.TimeoutExpired, OSError):
        return True


def _next_free_ip(cfg, vlan, limit=160):
    subnet = getattr(vlan, "subnet", "") if vlan else ""
    if not subnet:
        return "", "No subnet configured for selected network"
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return "", f"Invalid subnet for selected network: {subnet}"
    used = _existing_ip_set(cfg)
    reserved_octets = _reserved_host_octets(cfg)
    gateway = str(getattr(vlan, "gateway", "") or getattr(cfg, "vm_gateway", "") or "").split("/", 1)[0]
    if gateway:
        used.add(gateway)
    for idx, candidate in enumerate(net.hosts()):
        if idx >= limit:
            break
        ip_text = str(candidate)
        last = int(ip_text.rsplit(".", 1)[-1]) if "." in ip_text else 0
        if last < 10 or ip_text in used or last in reserved_octets:
            continue
        if _candidate_ip_available(ip_text):
            return ip_text, ""
    return "", f"No free IP found in {subnet} within first {limit} usable addresses"


def _inventory_ip_suggestions(cfg, vlan, count=5, limit=160):
    """Cheap next-IP suggestions from inventory only.

    The actual plan path still pings the candidate before committing. Options
    must be fast enough for a modal open, so this does not walk the network.
    """
    subnet = getattr(vlan, "subnet", "") if vlan else ""
    if not subnet:
        return []
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return []
    used = _existing_ip_set(cfg)
    gateway = str(getattr(vlan, "gateway", "") or getattr(cfg, "vm_gateway", "") or "").split("/", 1)[0]
    if gateway:
        used.add(gateway)
    reserved_octets = _reserved_host_octets(cfg)
    ips = []
    for idx, candidate in enumerate(net.hosts()):
        if idx >= limit or len(ips) >= count:
            break
        ip_text = str(candidate)
        last = int(ip_text.rsplit(".", 1)[-1]) if "." in ip_text else 0
        if last < 10 or ip_text in used or last in reserved_octets:
            continue
        ips.append(ip_text)
    return ips


def _gateway_for_vlan(cfg, vlan):
    if not vlan:
        return "", ""
    gateway = str(getattr(vlan, "gateway", "") or "").strip()
    if gateway:
        return gateway, "vlan"
    gateway = str(getattr(cfg, "vm_gateway", "") or "").strip()
    if gateway:
        return gateway, "global"
    return "", ""


def _vlan_rule_token(vlan):
    if not vlan:
        return ""
    return str(getattr(vlan, "id", "") or getattr(vlan, "name", "")).strip().lower()


def _gateway_policy(cfg):
    """Return operator-editable VM gateway rules."""
    raw = getattr(cfg, "vm_gateway_rules", {}) or {}

    def _token_set(value):
        if isinstance(value, (list, tuple, set)):
            return {str(v).strip().lower() for v in value if str(v).strip()}
        if isinstance(value, str):
            return {part.strip().lower() for part in value.split(",") if part.strip()}
        return set()

    egress = _token_set(raw.get("internet_vlans") or raw.get("egress_vlans"))
    no_default = _token_set(raw.get("no_default_gateway_vlans") or raw.get("no_gateway_vlans"))
    mode = str(raw.get("mode") or raw.get("default_gateway_mode") or "").strip().lower()
    if not mode:
        mode = "single_egress" if egress else "vlan_then_global"

    return {"mode": mode, "egress": egress, "no_default": no_default}


def _candidate_ip_for_octet(vlan, host_octet: int):
    subnet = getattr(vlan, "subnet", "") if vlan else ""
    if not subnet:
        return ""
    try:
        net = ipaddress.ip_network(subnet, strict=False)
        base = str(net.network_address).rsplit(".", 1)[0]
        candidate = f"{base}.{int(host_octet)}"
        ip_obj = ipaddress.ip_address(candidate)
        if ip_obj in net and ip_obj not in {net.network_address, net.broadcast_address}:
            return candidate
    except (ValueError, TypeError):
        return ""
    return ""


def _candidate_ip_allowed(cfg, ip_text, pending_ips=None):
    pending_ips = pending_ips or set()
    bare = str(ip_text or "").split("/", 1)[0]
    if not bare or bare in pending_ips:
        return False
    try:
        octet = int(bare.rsplit(".", 1)[-1])
    except (ValueError, TypeError):
        return False
    if octet < 10 or octet in _reserved_host_octets(cfg) or bare in _existing_ip_set(cfg):
        return False
    return _candidate_ip_available(bare)


def _next_common_host_octet(cfg, vlans, limit=160):
    vlans = [v for v in vlans if v and getattr(v, "subnet", "")]
    if not vlans:
        return 0, "No subnet configured for selected network"
    try:
        anchor = ipaddress.ip_network(getattr(vlans[0], "subnet", ""), strict=False)
    except ValueError:
        return 0, f"Invalid subnet for selected network: {getattr(vlans[0], 'subnet', '')}"
    reserved = _reserved_host_octets(cfg)
    for idx, candidate in enumerate(anchor.hosts()):
        if idx >= limit:
            break
        octet = int(str(candidate).rsplit(".", 1)[-1])
        if octet < 10 or octet in reserved:
            continue
        pending = set()
        ok = True
        for vlan in vlans:
            ip_text = _candidate_ip_for_octet(vlan, octet)
            if not ip_text or not _candidate_ip_allowed(cfg, ip_text, pending):
                ok = False
                break
            pending.add(ip_text)
        if ok:
            return octet, ""
    return 0, "No common free host octet found across selected networks"


def _normalise_create_nics(cfg, payload):
    raw_nics = payload.get("nics")
    if isinstance(raw_nics, list) and raw_nics:
        candidates = [item if isinstance(item, dict) else {} for item in raw_nics]
    else:
        candidates = [
            {
                "network_profile": payload.get("network_profile") or payload.get("network_profile_id") or payload.get("profile") or "",
                "vlan": payload.get("vlan") or payload.get("network") or "",
                "ip_mode": payload.get("ip_mode") or ("static" if payload.get("ip") else "static"),
                "ip": payload.get("ip", "auto"),
                "gateway": payload.get("gateway") or payload.get("gw") or "",
                "bridge": payload.get("bridge") or "",
            }
        ]
    normalised = []
    for idx, nic in enumerate(candidates):
        profile_key = nic.get("network_profile") or nic.get("network_profile_id") or nic.get("profile") or ""
        profile = _profile_by_key(cfg, profile_key)
        if not profile and nic.get("network"):
            profile = _profile_by_key(cfg, nic.get("network"))
        vlan_key = nic.get("vlan") or nic.get("vlan_id") or (profile.get("vlan") if profile else "") or nic.get("network") or ""
        vlan = _profile_vlan(cfg, profile) if profile else _vlan_by_key(cfg, vlan_key)
        explicit_gateway = str(nic.get("gateway") or nic.get("gw") or "").strip()
        ip_mode = str(nic.get("ip_mode") or ("static" if nic.get("ip") else "static")).lower()
        if ip_mode == "auto":
            ip_mode = "static"
        default_bridge = profile.get("bridge") if profile else ""
        raw_bridge = str(nic.get("bridge") or "").strip()
        normalised.append(
            {
                "index": idx,
                "vlan": vlan,
                "vlan_key": vlan_key,
                "network_profile": profile.get("id", "") if profile else "",
                "network_profile_name": profile.get("name", "") if profile else "",
                "network_purpose": profile.get("purpose", "") if profile else "",
                "ip_mode": ip_mode,
                "requested_ip": str(nic.get("ip") or "auto").strip(),
                "gateway": explicit_gateway,
                "gateway_source": "request" if explicit_gateway else "",
                "gateway_explicit": bool(explicit_gateway),
                "bridge": default_bridge or raw_bridge or getattr(cfg, "nic_bridge", "vmbr0"),
                "bridge_source": "profile" if default_bridge else ("advanced" if raw_bridge else "default"),
            }
        )
    if any(n["gateway_explicit"] for n in normalised):
        return normalised

    policy = _gateway_policy(cfg)
    egress = []
    for nic in normalised:
        token = _vlan_rule_token(nic["vlan"]) or str(nic["vlan_key"]).strip().lower()
        if token in policy["no_default"]:
            continue
        if token in policy["egress"]:
            egress.append(nic)
    if len(egress) == 1:
        gateway, source = _gateway_for_vlan(cfg, egress[0]["vlan"])
        egress[0]["gateway"] = gateway
        egress[0]["gateway_source"] = "gateway_rule:" + source if source else "gateway_rule"
    elif len(egress) == 0 and policy["mode"] == "vlan_then_global" and normalised:
        gateway, source = _gateway_for_vlan(cfg, normalised[0]["vlan"])
        normalised[0]["gateway"] = gateway
        normalised[0]["gateway_source"] = source
    return normalised


def _gateway_matches_subnet(ip_cidr, gateway):
    if not ip_cidr or not gateway:
        return True
    try:
        interface = ipaddress.ip_interface(ip_cidr)
        return ipaddress.ip_address(gateway) in interface.network
    except ValueError:
        return False


def _vm_create_options_payload(cfg):
    storage = _storage_options(cfg)
    nodes = _node_options(cfg, storage)
    vlans = _vlan_options(cfg)
    network_profiles = _network_profile_options(cfg)
    storage_by_node = {}
    for row in storage:
        node = str(row.get("node", "") or "")
        if node:
            storage_by_node.setdefault(node, []).append(row)
    ip_suggestions = {}
    for vlan in _vm_create_vlan_catalog(cfg):
        key = str(getattr(vlan, "id", "") or getattr(vlan, "name", ""))
        ip_suggestions[key] = _inventory_ip_suggestions(cfg, vlan)
    network_setup_required = not network_profiles
    return {
        "ok": True,
        "schema_version": 4,
        "cache_ttl_s": _VM_CREATE_OPTIONS_TTL,
        "nodes": nodes,
        "storage": storage,
        "storage_by_node": storage_by_node,
        "templates": _template_options(cfg),
        "distros": _distro_options(cfg),
        "vlans": vlans,
        "network_profiles": network_profiles,
        "ip_suggestions": ip_suggestions,
        "network_policy": {
            "default_ip_mode": "static",
            "gateway_source": _gateway_policy(cfg)["mode"],
            "internet_vlans": sorted(_gateway_policy(cfg)["egress"]),
            "no_default_gateway_vlans": sorted(_gateway_policy(cfg)["no_default"]),
            "host_octet_reservation": "global",
            "manual_gateway_default": False,
            "multi_nic": True,
            "primary_input": "network_profile",
            "bridge_input": "advanced",
            "network_setup_required": network_setup_required,
            "network_setup_hint": "Configure VM Network Profiles before creating static-IP VMs." if network_setup_required else "",
            "site_inference": False,
        },
        "cpu": {
            "default": getattr(cfg, "vm_cpu", "x86-64-v2-AES"),
            "choices": ["host", "x86-64-v2-AES", "x86-64-v3", "kvm64"],
        },
        "memory": {
            "default_mb": getattr(cfg, "vm_default_ram", 2048),
            "ballooning_default": True,
        },
        "lifecycle": {
            "start_on_boot_default": False,
            "accepted_keys": ["onboot", "start_on_boot"],
        },
        "disk": {
            "default_gb": getattr(cfg, "vm_default_disk", 32),
            "default_storage": storage[0]["id"],
            "default_by_node": {node["name"]: node["storage"] for node in nodes},
        },
        "bootstrap": {
            "service_account": getattr(cfg, "ssh_service_account", ""),
            "ssh_key_configured": bool(getattr(cfg, "ssh_key_path", "")),
            "method": "cloud-init sshkeys + ciuser",
        },
    }


def _vm_create_plan(cfg, payload, allocate_vmid=False):
    errors = []
    warnings = []
    name = str(payload.get("name") or "").strip()
    if not name:
        errors.append("name is required")
    elif not valid_label(name):
        errors.append("invalid VM name (alphanumeric + hyphens only)")

    node_name = str(payload.get("node") or payload.get("target_node") or "auto").strip() or "auto"
    node_ip = ""
    if node_name != "auto":
        node_name, node_err = _token_param(node_name, "node")
        if node_err:
            errors.append(node_err)
        else:
            node_ip = _node_ip_for_name(cfg, node_name)
            if not node_ip:
                errors.append(f"unknown configured PVE node: {node_name}")
    else:
        nodes = _node_options(cfg)
        if nodes:
            node_name = nodes[0]["name"]
            node_ip = nodes[0]["ip"]
        else:
            errors.append("no PVE nodes configured")

    cores = _coerce_int(payload.get("cores"), getattr(cfg, "vm_default_cores", 2))
    ram = _coerce_int(payload.get("ram") or payload.get("memory_mb"), getattr(cfg, "vm_default_ram", 2048))
    disk = _coerce_int(payload.get("disk") or payload.get("disk_gb"), getattr(cfg, "vm_default_disk", 32))
    balloon = _coerce_int(payload.get("balloon"), 0)
    if cores < 1 or cores > 256:
        errors.append("cores must be between 1 and 256")
    if ram < 256:
        errors.append("memory must be at least 256MB")
    if disk < 1:
        errors.append("disk must be at least 1GB")
    if balloon and balloon >= ram:
        errors.append("balloon memory must be less than assigned memory")

    start_on_boot = _coerce_bool(payload.get("onboot", payload.get("start_on_boot")), False)
    cpu = str(payload.get("cpu") or getattr(cfg, "vm_cpu", "x86-64-v2-AES")).strip()
    machine = str(payload.get("machine") or getattr(cfg, "vm_machine", "q35")).strip()
    scsihw = str(payload.get("scsihw") or getattr(cfg, "vm_scsihw", "virtio-scsi-single")).strip()
    storage_explicit = "storage" in payload and str(payload.get("storage") or "").strip() != ""
    storage = str(payload.get("storage") or (_configured_image_storage(cfg, node_ip) if node_ip else "")).strip()
    storage, storage_err = _token_param(storage, "storage")
    if storage_err:
        errors.append(storage_err)

    template_vmid = _coerce_int(payload.get("template_vmid") or payload.get("source_vmid"), 0)
    template_source_node = ""
    template_source_node_ip = ""
    if template_vmid:
        allowed, err = _clone_source_allowed(cfg, template_vmid)
        if not allowed:
            errors.append(f"template/source blocked: {err}")
        elif node_ip:
            template_source_node, template_source_node_ip = _template_source(cfg, template_vmid)
            if not template_source_node_ip:
                errors.append(f"template/source VMID {template_vmid} was not found on any configured PVE node")

    vmid = _coerce_int(payload.get("vmid") or payload.get("newid") or payload.get("target_vmid"), 0)
    vmid_source = "request" if vmid else ""
    if allocate_vmid and not vmid and node_ip and not errors:
        vmid, vmid_source, vmid_err = _allocate_create_vmid(cfg, node_ip)
        if vmid_err:
            errors.append(vmid_err)
        if vmid <= 0 and not vmid_err:
            errors.append("could not allocate VMID")
    if vmid:
        allowed, err = _check_vm_permission(cfg, vmid, "configure")
        if not allowed:
            errors.append(f"target VMID blocked: {err}")

    if node_ip and not errors and (storage_explicit or not storage):
        storage, storage_warning = _resolve_target_storage(cfg, node_ip, storage)
        if storage_warning:
            warnings.append(storage_warning)

    networks = []
    seen_static_ips = set()
    normalised_nics = _normalise_create_nics(cfg, payload)
    if not any(n["gateway_explicit"] for n in normalised_nics):
        policy = _gateway_policy(cfg)
        egress_count = 0
        for nic in normalised_nics:
            token = _vlan_rule_token(nic["vlan"]) or str(nic["vlan_key"]).strip().lower()
            if token in policy["egress"]:
                egress_count += 1
        if egress_count > 1:
            errors.append("multiple internet-egress NICs selected; choose one gateway network")

    static_nics = [n for n in normalised_nics if n["ip_mode"] == "static"]
    manual_octets = set()
    for nic in static_nics:
        req = nic["requested_ip"]
        if req in {"", "auto"}:
            continue
        try:
            manual_octets.add(int(req.split("/", 1)[0].rsplit(".", 1)[-1]))
        except (ValueError, TypeError):
            pass
    common_octet = 0
    if len(manual_octets) > 1:
        errors.append("static NIC IPs must use the same host octet across networks")
    elif len(manual_octets) == 1:
        common_octet = next(iter(manual_octets))
        if common_octet in _reserved_host_octets(cfg):
            errors.append(f"host octet .{common_octet} is already reserved elsewhere in the fleet")
    elif len(static_nics) > 1:
        common_octet, octet_err = _next_common_host_octet(cfg, [n["vlan"] for n in static_nics])
        if octet_err:
            errors.append(octet_err)

    pending_ips = set()
    for nic in normalised_nics:
        vlan = nic["vlan"]
        ip_mode = nic["ip_mode"]
        requested_ip = nic["requested_ip"]
        cidr = ""
        gateway = nic["gateway"]
        gateway_source = nic["gateway_source"]
        if ip_mode == "static":
            if requested_ip in {"", "auto"}:
                if common_octet:
                    requested_ip = _candidate_ip_for_octet(vlan, common_octet)
                    if not requested_ip or not _candidate_ip_allowed(cfg, requested_ip, pending_ips):
                        errors.append(f"NIC {nic['index']}: host octet .{common_octet} is not available on selected network")
                else:
                    requested_ip, ip_err = _next_free_ip(cfg, vlan)
                    if ip_err:
                        errors.append(f"NIC {nic['index']}: {ip_err}")
            bare_ip = requested_ip.split("/", 1)[0]
            if requested_ip and not valid_ip(bare_ip):
                errors.append(f"NIC {nic['index']}: invalid static IP address")
            try:
                octet = int(bare_ip.rsplit(".", 1)[-1])
                if common_octet and octet != common_octet:
                    errors.append(f"NIC {nic['index']}: static IP must use host octet .{common_octet}")
                if not common_octet and octet in _reserved_host_octets(cfg):
                    errors.append(f"NIC {nic['index']}: host octet .{octet} is already reserved elsewhere in the fleet")
            except (ValueError, TypeError):
                pass
            if bare_ip in seen_static_ips:
                errors.append(f"NIC {nic['index']}: duplicate static IP {bare_ip}")
            if bare_ip:
                seen_static_ips.add(bare_ip)
                pending_ips.add(bare_ip)
            prefix = "24"
            if requested_ip and "/" in requested_ip:
                prefix = requested_ip.split("/", 1)[1]
            elif vlan and getattr(vlan, "subnet", "") and "/" in getattr(vlan, "subnet", ""):
                prefix = getattr(vlan, "subnet").split("/", 1)[1]
            if requested_ip:
                cidr = requested_ip if "/" in requested_ip else f"{requested_ip}/{prefix}"
            if gateway and not valid_ip(gateway):
                errors.append(f"NIC {nic['index']}: invalid gateway IP")
            if cidr and gateway and not _gateway_matches_subnet(cidr, gateway):
                if gateway_source in {"vlan", "global"}:
                    warnings.append(
                        f"NIC {nic['index']}: configured {gateway_source} gateway {gateway} is outside selected IP network {cidr}; verify routed/on-link gateway handling before submit"
                    )
                elif nic["gateway_explicit"]:
                    errors.append(f"NIC {nic['index']}: gateway {gateway} is not in selected IP network {cidr}")
                else:
                    warnings.append(f"NIC {nic['index']}: gateway {gateway} is outside selected IP network {cidr}")
        elif ip_mode != "dhcp":
            errors.append(f"NIC {nic['index']}: ip_mode must be dhcp or static")

        tag = str(getattr(vlan, "id", "") if vlan else (nic["vlan_key"] or "")).strip()
        if tag and not valid_vlan(tag):
            errors.append(f"NIC {nic['index']}: invalid VLAN tag")
        networks.append(
            {
                "index": nic["index"],
                "mode": ip_mode,
                "bridge": nic["bridge"],
                "bridge_source": nic.get("bridge_source", ""),
                "tag": tag,
                "ip": requested_ip,
                "cidr": cidr,
                "gateway": gateway,
                "gateway_source": gateway_source,
                "gateway_in_subnet": _gateway_matches_subnet(cidr, gateway),
                "gateway_warning": _gateway_status(cidr, gateway)["warning"] if cidr and gateway else "",
                "vlan": getattr(vlan, "name", "") if vlan else "",
                "vlan_id": getattr(vlan, "id", 0) if vlan else 0,
                "network_profile": nic.get("network_profile", ""),
                "network_profile_name": nic.get("network_profile_name", ""),
                "purpose": nic.get("network_purpose", ""),
            }
        )
    if not networks:
        errors.append("at least one NIC is required")

    bootstrap = {
        "ciuser": getattr(cfg, "ssh_service_account", ""),
        "ssh_key_path": getattr(cfg, "ssh_key_path", ""),
        "ssh_key_available": bool(getattr(cfg, "ssh_key_path", "") and os.path.isfile(getattr(cfg, "ssh_key_path", "") + ".pub")),
        "nameserver": str(payload.get("nameserver") or getattr(cfg, "vm_nameserver", "")),
    }
    if not bootstrap["ssh_key_available"]:
        warnings.append("service SSH public key is not readable; bootstrap will set ciuser but may not install sshkeys")

    plan = {
        "name": name,
        "vmid": vmid,
        "vmid_source": vmid_source,
        "node": node_name,
        "node_ip": node_ip,
        "mode": "clone" if template_vmid else "create",
        "template_vmid": template_vmid,
        "template_source_node": template_source_node,
        "template_source_node_ip": template_source_node_ip,
        "cores": cores,
        "ram_mb": ram,
        "balloon_mb": balloon,
        "disk_gb": disk,
        "cpu": cpu,
        "machine": machine,
        "scsihw": scsihw,
        "onboot": start_on_boot,
        "start_on_boot": start_on_boot,
        "storage": storage,
        "network": networks[0] if networks else {},
        "networks": networks,
        "bootstrap": bootstrap,
        "steps": [
            "allocate VMID" if not vmid else "use requested VMID",
            "clone template" if template_vmid else "create VM shell",
            "configure CPU/memory/disk",
            "configure boot behavior",
            "configure NIC(s) and cloud-init IP(s)",
            "install service account SSH key via cloud-init",
            "refresh fleet inventory",
        ],
    }
    return {"ok": not errors, "plan": plan, "errors": errors, "warnings": warnings}


def _job_update(job_id, **updates):
    with _vm_create_jobs_lock:
        job = _vm_create_jobs.get(job_id)
        if not job:
            return
        lines = updates.pop("lines", None)
        if lines:
            job.setdefault("lines", []).extend(lines)
            job["lines"] = job["lines"][-_VM_CREATE_JOB_TAIL:]
        job.update(updates)
        job["updated_at"] = time.time()


def _cleanup_created_vm_after_failed_create(cfg, vmid: int, node_ips):
    """Best-effort cleanup for disposable create jobs after partial success."""
    seen = set()
    for node_ip in node_ips:
        if not node_ip or node_ip in seen:
            continue
        seen.add(node_ip)
        try:
            _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge 1", timeout=60)
        except Exception:
            pass


def _run_vm_create_job(job_id, payload):
    cfg = load_config()
    try:
        result = _vm_create_plan(cfg, payload, allocate_vmid=True)
        if not result["ok"]:
            _job_update(job_id, state="failed", errors=result["errors"], finished_at=time.time(), lines=["validation failed"])
            return
        plan = result["plan"]
        _job_update(job_id, state="running", plan=plan, warnings=result["warnings"], lines=[f"planned VM {plan['vmid']} on {plan['node']}"])
        node_ip = plan["node_ip"]
        vmid = plan["vmid"]
        clone_node_ip = node_ip
        cross_node_clone = False
        if plan["mode"] == "clone":
            clone_node_ip = plan.get("template_source_node_ip") or node_ip
            cross_node_clone = bool(clone_node_ip and node_ip and clone_node_ip != node_ip)
            parts = ["qm", "clone", str(plan["template_vmid"]), str(vmid), "--name", plan["name"], "--full", "1"]
            if plan["node"] and not cross_node_clone:
                parts.extend(["--target", plan["node"]])
            if plan["storage"] and not cross_node_clone:
                parts.extend(["--storage", plan["storage"]])
            cmd = " ".join(shlex.quote(p) for p in parts)
        else:
            first_network = (plan.get("networks") or [plan.get("network") or {}])[0]
            net = f"virtio,bridge={first_network.get('bridge') or getattr(cfg, 'nic_bridge', 'vmbr0')}"
            if first_network.get("tag"):
                net += f",tag={first_network['tag']}"
            cmd = (
                f"qm create {vmid} --name {shlex.quote(plan['name'])} --cores {plan['cores']} "
                f"--memory {plan['ram_mb']} --cpu {shlex.quote(plan['cpu'])} "
                f"--machine {shlex.quote(plan['machine'])} --net0 {shlex.quote(net)} "
                f"--scsihw {shlex.quote(plan['scsihw'])} --scsi0 {shlex.quote(plan['storage'] + ':' + str(plan['disk_gb']))}"
            )
            if plan["balloon_mb"]:
                cmd += f" --balloon {plan['balloon_mb']}"
            clone_node_ip = node_ip
        _job_update(job_id, lines=[f"running: {cmd}"])
        stdout, ok = _pve_cmd(cfg, clone_node_ip, cmd, timeout=300)
        if not ok:
            _job_update(job_id, state="failed", error=stdout, finished_at=time.time(), lines=[stdout])
            return

        if cross_node_clone:
            migrate_parts = ["qm", "migrate", str(vmid), plan["node"], "--with-local-disks"]
            if plan["storage"]:
                migrate_parts.extend(["--targetstorage", plan["storage"]])
            migrate_cmd = " ".join(shlex.quote(p) for p in migrate_parts)
            _job_update(job_id, lines=[f"running: {migrate_cmd}"])
            out, ok = _pve_cmd(cfg, clone_node_ip, migrate_cmd, timeout=600)
            if not ok:
                _cleanup_created_vm_after_failed_create(cfg, vmid, [clone_node_ip, node_ip])
                _job_update(job_id, state="failed", error=out, finished_at=time.time(), lines=[out, "cleanup attempted after failed migration"])
                return

        set_cmds = []
        if plan["mode"] == "clone":
            set_cmds.append(f"qm resize {vmid} scsi0 {plan['disk_gb']}G")
        set_cmds.extend([
            f"qm set {vmid} --cores {plan['cores']} --memory {plan['ram_mb']} --cpu {shlex.quote(plan['cpu'])}",
            f"qm set {vmid} --machine {shlex.quote(plan['machine'])} --scsihw {shlex.quote(plan['scsihw'])}",
            f"qm set {vmid} --balloon {plan['balloon_mb']}",
            f"qm set {vmid} --onboot {1 if plan.get('start_on_boot') else 0}",
            f"qm set {vmid} --ciuser {shlex.quote(plan['bootstrap']['ciuser'])}",
            f"qm set {vmid} --citype nocloud",
        ])
        if plan["bootstrap"].get("nameserver"):
            set_cmds.append(f"qm set {vmid} --nameserver {shlex.quote(plan['bootstrap']['nameserver'])}")
        if plan["bootstrap"].get("ssh_key_available"):
            pub = plan["bootstrap"]["ssh_key_path"] + ".pub"
            tmp = f"/tmp/freq-sshkey-{vmid}.pub"
            with open(pub) as f:
                pubkey = f.read().strip()
            set_cmds.append("printf '%s\\n' " + shlex.quote(pubkey) + f" > {tmp}")
            set_cmds.append(f"qm set {vmid} --sshkeys {tmp}")
        for network in plan.get("networks") or [plan["network"]]:
            idx = int(network.get("index", 0) or 0)
            net_value = f"virtio,bridge={network.get('bridge') or getattr(cfg, 'nic_bridge', 'vmbr0')}"
            if network.get("tag"):
                net_value += f",tag={network['tag']}"
            set_cmds.append(f"qm set {vmid} --net{idx} {shlex.quote(net_value)}")
            if network["mode"] == "static":
                ipconfig = f"ip={network['cidr']}"
                if network.get("gateway"):
                    ipconfig += f",gw={network['gateway']}"
            else:
                ipconfig = "ip=dhcp"
            set_cmds.append(f"qm set {vmid} --ipconfig{idx} {shlex.quote(ipconfig)}")
        for set_cmd in set_cmds:
            _job_update(job_id, lines=[f"running: {set_cmd}"])
            out, ok = _pve_cmd(cfg, node_ip, set_cmd, timeout=60)
            if not ok:
                _cleanup_created_vm_after_failed_create(cfg, vmid, [node_ip, clone_node_ip])
                _job_update(job_id, state="failed", error=out, finished_at=time.time(), lines=[out, "cleanup attempted after failed configuration"])
                return
        _refresh_fleet_overview_after_mutation("create-wizard", vmid)
        _job_update(job_id, state="succeeded", result={"ok": True, "vmid": vmid, "name": plan["name"], "node": plan["node"]}, finished_at=time.time(), lines=["create job succeeded"])
    except Exception as e:
        logger.error(f"api_vm_error: create job failed: {e}", endpoint="vm/create/submit")
        _job_update(job_id, state="failed", error=str(e), finished_at=time.time(), lines=[str(e)])


# ── Handlers ────────────────────────────────────────────────────────────


def handle_vm_list(handler):
    """GET /api/vms — VM inventory from PVE cluster, enriched with fleet boundaries."""
    cfg = load_config()
    vm_list = _get_fleet_vms(cfg)
    json_response(handler, {"vms": vm_list, "count": len(vm_list)})


def handle_vm_create_options(handler):
    """GET /api/vm/create/options — first-class VM create wizard options."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    now = time.monotonic()
    cached = _vm_create_options_cache.get("payload")
    if cached is not None and now - float(_vm_create_options_cache.get("ts") or 0) < _VM_CREATE_OPTIONS_TTL:
        payload = dict(cached)
        payload["cached"] = True
        json_response(handler, payload)
        return
    payload = _vm_create_options_payload(cfg)
    _vm_create_options_cache["payload"] = payload
    _vm_create_options_cache["ts"] = now
    json_response(handler, payload)


def _validate_network_profile_payload(cfg, profiles):
    errors = []
    rows = []
    seen = set()
    vlan_keys = {
        str(getattr(v, "id", "")).lower()
        for v in _vm_create_vlan_catalog(cfg)
        if str(getattr(v, "id", "")).strip()
    }
    for idx, raw in enumerate(profiles if isinstance(profiles, list) else []):
        if not isinstance(raw, dict):
            errors.append(f"profile {idx}: object required")
            continue
        pid = _profile_key(raw.get("id") or raw.get("key") or raw.get("name"))
        if not pid:
            errors.append(f"profile {idx}: id required")
            continue
        if pid in seen:
            errors.append(f"profile {idx}: duplicate id {pid}")
            continue
        seen.add(pid)
        name = str(raw.get("name") or pid).strip()
        bridge = str(raw.get("bridge") or "").strip()
        if not re.match(r"^[A-Za-z0-9_.:-]+$", bridge):
            errors.append(f"profile {pid}: valid bridge required")
        vlan = raw.get("vlan", raw.get("vlan_id", ""))
        vlan_text = str(vlan).strip()
        if vlan_text and not valid_vlan(vlan_text):
            errors.append(f"profile {pid}: invalid VLAN tag {vlan_text}")
        if vlan_keys and vlan_text and vlan_text.lower() not in vlan_keys:
            errors.append(f"profile {pid}: VLAN {vlan_text} is not in the VM network catalog")
        gateway_role = str(raw.get("gateway_role") or "").strip().lower()
        if gateway_role and gateway_role not in {"none", "default", "manual"}:
            errors.append(f"profile {pid}: gateway_role must be none, default, or manual")
        rows.append(
            {
                "id": pid,
                "name": name,
                "vlan": int(vlan_text) if vlan_text else "",
                "bridge": bridge,
                "purpose": str(raw.get("purpose") or "").strip(),
                "gateway_role": gateway_role,
                "description": str(raw.get("description") or "").strip(),
            }
        )
    if not isinstance(profiles, list):
        errors.append("profiles must be an array")
    return rows, errors


def handle_vm_network_profiles(handler):
    """GET/POST /api/vm/network-profiles — Settings-owned VM network profile mapping."""
    if handler.command == "GET":
        role, err = _check_session_role(handler, "operator")
        if err:
            json_response(handler, {"error": err}, 403)
            return
        cfg = load_config(force=True)
        json_response(
            handler,
            {
                "ok": True,
                "schema_version": 1,
                "config_file": os.path.join(cfg.conf_dir, "network-profiles.toml"),
                "profiles": _network_profile_options(cfg),
                "advanced_bridge_input": True,
            },
        )
        return
    if _require_post(handler, "VM network profile update"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config(force=True)
    body = get_json_body(handler) or {}
    rows, errors = _validate_network_profile_payload(cfg, body.get("profiles", []))
    if errors:
        json_response(handler, {"ok": False, "errors": errors}, 400)
        return
    path = os.path.join(cfg.conf_dir, "network-profiles.toml")
    try:
        save_network_profiles_toml(path, rows)
    except OSError as e:
        json_response(handler, {"ok": False, "error": f"failed to write network profiles: {e}"}, 500)
        return
    _vm_create_options_cache["payload"] = None
    _vm_create_options_cache["ts"] = 0
    cfg = load_config(force=True)
    json_response(
        handler,
        {
            "ok": True,
            "config_file": path,
            "profiles": _network_profile_options(cfg),
        },
    )


def handle_vm_create_plan(handler):
    """POST /api/vm/create/plan — validate and preview a VM create request."""
    if _require_post(handler, "VM create plan"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    payload = _vm_create_body(handler)
    plan = _vm_create_plan(cfg, payload, allocate_vmid=False)
    json_response(handler, plan, 200 if plan["ok"] else 400)


def handle_vm_create_submit(handler):
    """POST /api/vm/create/submit — launch first-class VM create job."""
    if _require_post(handler, "VM create submit"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    payload = _vm_create_body(handler)
    preview = _vm_create_plan(cfg, payload, allocate_vmid=False)
    if not preview["ok"]:
        json_response(handler, preview, 400)
        return
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with _vm_create_jobs_lock:
        _vm_create_jobs[job_id] = {
            "id": job_id,
            "state": "queued",
            "created_at": now,
            "updated_at": now,
            "lines": ["queued VM create job"],
            "plan": preview["plan"],
            "warnings": preview["warnings"],
        }
    threading.Thread(target=_run_vm_create_job, args=(job_id, payload), daemon=True, name=f"freq-vm-create-{job_id}").start()
    with _vm_create_jobs_lock:
        job = dict(_vm_create_jobs[job_id])
        job["lines"] = list(job.get("lines", []))
    json_response(handler, {"ok": True, "job": job}, 202)


def handle_vm_create_job(handler):
    """GET /api/vm/create/job?id=<job_id> — return VM create job status/log."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = get_params(handler)
    job_id = params.get("id", params.get("job_id", [""]))[0]
    if not job_id:
        with _vm_create_jobs_lock:
            jobs = [dict(job) for job in _vm_create_jobs.values()]
        for job in jobs:
            job["lines"] = list(job.get("lines", []))[-_VM_CREATE_JOB_TAIL:]
        json_response(handler, {"ok": True, "jobs": sorted(jobs, key=lambda j: j.get("created_at", 0), reverse=True)[:20]})
        return
    with _vm_create_jobs_lock:
        job = _vm_create_jobs.get(job_id)
        if job:
            job = dict(job)
            job["lines"] = list(job.get("lines", []))[-_VM_CREATE_JOB_TAIL:]
    if not job:
        json_response(handler, {"error": f"VM create job not found: {job_id}"}, 404)
        return
    json_response(handler, {"ok": True, "job": job})


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
    requested_node = params.get("node", params.get("target_node", [""]))[0]
    cores = _get_int_param(handler, params, "cores", default=2)
    if cores is None:
        return
    ram = _get_int_param(handler, params, "ram", default=2048)
    if ram is None:
        return
    if not name:
        json_response(handler, {"error": "Name required"}, 400)
        return
    if not valid_label(name):
        json_response(handler, {"error": "Invalid VM name (alphanumeric + hyphens only)"}, 400)
        return
    vmid = None
    node_ip = None
    try:
        requested_node, node_err = _token_param(requested_node, "node")
        if node_err:
            json_response(handler, {"error": node_err}, 400)
            return
        node_ip = _node_ip_for_name(cfg, requested_node) if requested_node and requested_node != "auto" else ""
        if requested_node and requested_node != "auto" and not node_ip:
            json_response(handler, {"error": f"Unknown configured PVE node: {requested_node}"}, 400)
            return
        node_ip = node_ip or _find_reachable_node(cfg)
        if not node_ip:
            json_response(handler, {"error": "No PVE node reachable"}, 502)
            return
        vmid, _vmid_source, vmid_err = _allocate_create_vmid(cfg, node_ip)
        if vmid_err:
            json_response(handler, {"error": vmid_err}, 502)
            return
        if vmid <= 0:
            json_response(handler, {"error": "Could not allocate VMID"}, 502)
            return
        cmd = (
            f"qm create {vmid} --name {name} --cores {cores} --memory {ram} "
            f"--cpu {cfg.vm_cpu} --machine {cfg.vm_machine} "
            f"--net0 virtio,bridge={cfg.nic_bridge} --scsihw {cfg.vm_scsihw}"
        )
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
        if not ok:
            # Clean up partially created VM if it exists
            _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge 1", timeout=30)
            _respond_operation(handler, {"ok": False, "vmid": vmid, "name": name, "error": stdout}, ok=False)
        else:
            _refresh_fleet_overview_after_mutation("create", vmid)
            json_response(
                handler,
                {
                    "ok": True,
                    "vmid": vmid,
                    "name": name,
                    "node": _node_name_for_ip(cfg, node_ip) or requested_node or "auto",
                    "error": "",
                },
            )
    except Exception as e:
        logger.error(f"api_vm_error: vm create failed: {e}", endpoint="vm/create")
        if vmid and node_ip:
            try:
                _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge 1", timeout=30)
            except Exception:
                pass
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, params, "vmid", required=True)
    if vmid is None:
        return
    # Fleet boundary check — only admin-tier VMs can be destroyed
    allowed, err = _check_vm_permission(cfg, vmid, "destroy")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return
    if is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges, vm_tags=get_vm_tags(vmid)):
        json_response(handler, {"error": f"VMID {vmid} is PROTECTED"}, 403)
        return
    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return
        _pve_cmd(cfg, node_ip, f"qm stop {vmid}", timeout=30)
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=120)
        _respond_vm_mutation(
            handler,
            {"ok": ok, "vmid": vmid, "error": stdout if not ok else ""},
            ok=ok,
            reason="destroy",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm destroy failed: {e}", endpoint="vm/destroy")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, params, "vmid", required=True)
    if vmid is None:
        return
    snap_name = params.get("name", [f"freq-snap-{vmid}"])[0]
    if not valid_label(snap_name):
        json_response(handler, {"error": "Invalid snapshot name (alphanumeric + hyphens only)"}, 400)
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, vmid, "snapshot")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return
    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm snapshot {vmid} {snap_name}", timeout=120)
        _respond_operation(
            handler, {"ok": ok, "vmid": vmid, "snapshot": snap_name, "error": stdout if not ok else ""}, ok=ok
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm snapshot failed: {e}", endpoint="vm/snapshot")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, params, "vmid", required=True)
    if vmid is None:
        return
    cores = params.get("cores", [None])[0]
    ram = params.get("ram", [None])[0]
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, vmid, "resize")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return
    parts = []
    if cores:
        try:
            cores = int(cores)
        except ValueError:
            json_response(handler, {"error": "Invalid cores value"}, 400)
            return
        parts.append(f"--cores {cores}")
    if ram:
        try:
            ram = int(ram)
        except ValueError:
            json_response(handler, {"error": "Invalid ram value"}, 400)
            return
        parts.append(f"--memory {ram}")
    if not parts:
        json_response(handler, {"error": "Specify cores or ram"}, 400)
        return
    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} {' '.join(parts)}")
        _respond_vm_mutation(
            handler,
            {"ok": ok, "vmid": vmid, "error": stdout if not ok else ""},
            ok=ok,
            reason="resize",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm resize failed: {e}", endpoint="vm/resize")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, params, "vmid", required=True)
    if vmid is None:
        return
    action = params.get("action", ["status"])[0]
    if action not in ("start", "stop", "reset", "status"):
        json_response(handler, {"error": f"Invalid action: {action}"}, 400)
        return
    # Fleet boundary check — power actions require start/stop permission
    if action in ("start", "stop", "reset"):
        perm_action = "start" if action == "start" else "stop"
        allowed, err = _check_vm_permission(cfg, vmid, perm_action)
        if not allowed:
            json_response(handler, {"error": err}, 403)
            return
    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
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
        if ok and action in ("start", "reset"):
            _clear_health_backoff_for_vmid(cfg, vmid)
        if ok and action in ("start", "stop", "reset"):
            _patch_fleet_overview_vm_status(vmid, "running" if action in ("start", "reset") else "stopped")
            _refresh_fleet_overview_after_mutation(f"power-{action}", vmid)
        _respond_operation(
            handler,
            {"ok": ok, "vmid": vmid, "action": action, "output": output, "error": "" if ok else output},
            ok=ok,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm power failed: {e}", endpoint="vm/power")
        json_response(handler, {"error": f"PVE operation failed: {e}"}, 502)


def handle_vm_template(handler):
    """POST /api/vm/template — convert VM to template."""
    if _require_post(handler, "VM template"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = _get_int_param(handler, query, "vmid", required=True)
    if vmid is None:
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return

        r = ssh_single(
            host=node_ip,
            command=f"sudo qm template {vmid}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=120,
            htype="pve",
            use_sudo=False,
            cfg=cfg,
        )
        _respond_vm_mutation(
            handler,
            {"ok": r.returncode == 0, "vmid": vmid, "error": "" if r.returncode == 0 else (r.stderr or r.stdout)},
            ok=r.returncode == 0,
            reason="template",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm template failed: {e}", endpoint="vm/template")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, query, "vmid", required=True)
    name = query.get("name", [""])[0]
    if vmid is None or not name:
        json_response(handler, {"error": "vmid and name parameters required"}, 400)
        return
    if not valid_label(name):
        json_response(handler, {"error": "Invalid VM name (alphanumeric + hyphens only)"}, 400)
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return

        r = ssh_single(
            host=node_ip,
            command=f"sudo qm set {vmid} --name {name}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
            cfg=cfg,
        )
        _respond_vm_mutation(
            handler,
            {"ok": r.returncode == 0, "vmid": vmid, "name": name, "error": "" if r.returncode == 0 else (r.stderr or r.stdout)},
            ok=r.returncode == 0,
            reason="rename",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm rename failed: {e}", endpoint="vm/rename")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


def handle_vm_snapshots(handler):
    """GET /api/vm/snapshots — list snapshots for a VM."""
    cfg = load_config()

    query = get_params(handler)
    vmid = _get_int_param(handler, query, "vmid", required=True)
    if vmid is None:
        return
    node_ip = _find_vm_node_ip(cfg, vmid)
    if not node_ip:
        json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
        return
    r = ssh_single(
        host=node_ip,
        command=f"sudo qm listsnapshot {vmid}",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=15,
        htype="pve",
        use_sudo=False,
        cfg=cfg,
    )
    snaps = _parse_qm_snapshot_names(r.stdout) if r.returncode == 0 else []
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
    vmid = _get_int_param(handler, query, "vmid", required=True)
    snap = query.get("name", [""])[0]
    if vmid is None or not snap:
        json_response(handler, {"error": "vmid and name required"}, 400)
        return
    if not valid_label(snap):
        json_response(handler, {"error": "Invalid snapshot name (alphanumeric + hyphens only)"}, 400)
        return
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return
    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return
        r = ssh_single(
            host=node_ip,
            command=f"sudo qm delsnapshot {vmid} {snap}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=120,
            htype="pve",
            use_sudo=False,
            cfg=cfg,
        )
        _respond_operation(
            handler,
            {
                "ok": r.returncode == 0,
                "vmid": vmid,
                "snapshot": snap,
                "error": "" if r.returncode == 0 else (r.stderr or r.stdout),
            },
            ok=r.returncode == 0,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm snapshot delete failed: {e}", endpoint="vm/snapshot-delete")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, query, "vmid", required=True)
    newid = _get_int_param(handler, query, "newid", required=True)
    if vmid is None or newid is None:
        json_response(handler, {"error": "vmid and newid parameters required"}, 400)
        return
    # Fleet boundary check on BOTH old and new VMID
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return
    allowed2, err2 = _check_vm_permission(cfg, newid, "configure")
    if not allowed2:
        json_response(handler, {"error": f"Target VMID blocked: {err2}"}, 403)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
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
            cfg=cfg,
        )
        if "running" in (r.stdout or ""):
            json_response(handler, {"error": f"VM {vmid} must be stopped first"}, 409)
            return

        cfg_out, cfg_ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}", timeout=15)
        current_name = ""
        if cfg_ok:
            for line in (cfg_out or "").splitlines():
                if line.startswith("name:"):
                    current_name = line.split(":", 1)[1].strip()
                    break
        if current_name and not valid_label(current_name):
            json_response(handler, {"error": f"Current VM name is invalid for clone: {current_name}"}, 400)
            return

        # Clone to new ID then destroy old
        clone_parts = ["sudo", "qm", "clone", str(vmid), str(newid), "--full"]
        if current_name:
            clone_parts.extend(["--name", current_name])
        r = ssh_single(
            host=node_ip,
            command=" ".join(shlex.quote(part) for part in clone_parts),
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=300,
            htype="pve",
            use_sudo=False,
            cfg=cfg,
        )
        if r.returncode != 0:
            json_response(handler, {"error": f"Clone failed: {r.stderr or r.stdout}"}, 502)
            return

        # Destroy old
        r2 = ssh_single(
            host=node_ip,
            command=f"sudo qm destroy {vmid} --purge",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=120,
            htype="pve",
            use_sudo=False,
            cfg=cfg,
        )
        _respond_vm_mutation(
            handler,
            {
                "ok": r2.returncode == 0,
                "old_vmid": vmid,
                "new_vmid": newid,
                "error": "" if r2.returncode == 0 else (r2.stderr or r2.stdout),
            },
            ok=r2.returncode == 0,
            reason="change-id",
            vmid=newid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm change-id failed: {e}", endpoint="vm/change-id")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


def handle_vm_check_ip(handler):
    """GET /api/vm/check-ip — check if an IP is available by pinging it."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    query = get_params(handler)
    ip = query.get("ip", [""])[0]
    if not ip:
        json_response(handler, {"error": "ip required"}, 400)
        return
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, timeout=3)
        in_use = r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        in_use = False
    json_response(handler, {"ip": ip, "in_use": in_use, "available": not in_use})


def handle_vm_add_nic(handler):
    """POST /api/vm/add-nic — add a NIC to a VM without clearing existing ones."""
    if _require_post(handler, "VM add NIC"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()

    query = get_params(handler)
    vmid = _get_int_param(handler, query, "vmid", required=True)
    new_ip = query.get("ip", [""])[0]
    gateway = query.get("gw", [""])[0]
    vlan_id_val = query.get("vlan", [""])[0]
    if vmid is None or not new_ip:
        json_response(handler, {"error": "vmid and ip required"}, 400)
        return
    bare_ip = new_ip.split("/")[0] if "/" in new_ip else new_ip
    if not valid_ip(bare_ip):
        json_response(handler, {"error": "Invalid IP address"}, 400)
        return
    if gateway and not valid_ip(gateway):
        json_response(handler, {"error": "Invalid gateway IP"}, 400)
        return
    if vlan_id_val and not valid_vlan(vlan_id_val):
        json_response(handler, {"error": "Invalid VLAN ID"}, 400)
        return
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
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
            cfg=cfg,
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
            cfg=cfg,
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
            cfg=cfg,
        )
        ok = r1.returncode == 0 and r2.returncode == 0
        err = ""
        if r1.returncode != 0:
            err = f"NIC create failed: {r1.stderr or r1.stdout}"
        elif r2.returncode != 0:
            err = f"IP config failed: {r2.stderr or r2.stdout}"
        _respond_vm_mutation(
            handler,
            {"ok": ok, "vmid": vmid, "nic": f"net{next_nic}", "ip": new_ip, "vlan": vlan_id_val, "error": err},
            ok=ok,
            reason="add-nic",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm add-nic failed: {e}", endpoint="vm/add-nic")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


def handle_vm_update_nic(handler):
    """POST /api/vm/update-nic — update one existing NIC without touching others."""
    if _require_post(handler, "VM update NIC"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    query = get_params(handler)
    vmid = _get_int_param(handler, query, "vmid", required=True)
    nic_idx = _nic_index_param(handler, query)
    if vmid is None or nic_idx is None:
        return
    bridge = query.get("bridge", [getattr(cfg, "nic_bridge", "vmbr0")])[0] or getattr(cfg, "nic_bridge", "vmbr0")
    vlan_id_val = query.get("vlan", [""])[0]
    firewall = query.get("firewall", [""])[0].lower()
    new_ip = query.get("ip", [""])[0]
    gateway = query.get("gw", [""])[0]
    bridge, bridge_err = _token_param(bridge, "bridge")
    if bridge_err:
        json_response(handler, {"error": bridge_err}, 400)
        return
    if vlan_id_val and not valid_vlan(vlan_id_val):
        json_response(handler, {"error": "Invalid VLAN ID"}, 400)
        return
    if firewall and firewall not in {"0", "1", "true", "false", "yes", "no", "on", "off"}:
        json_response(handler, {"error": "Invalid firewall value"}, 400)
        return
    if new_ip:
        bare_ip = new_ip.split("/")[0] if "/" in new_ip else new_ip
        if not valid_ip(bare_ip):
            json_response(handler, {"error": "Invalid IP address"}, 400)
            return
        if gateway and not valid_ip(gateway):
            json_response(handler, {"error": "Invalid gateway IP"}, 400)
            return
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return
        config_text, config_ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}", timeout=15)
        if not config_ok:
            _respond_operation(handler, {"ok": False, "vmid": vmid, "error": config_text}, ok=False)
            return
        config = _parse_qm_config_kv(config_text)
        net_key = f"net{nic_idx}"
        if net_key not in config:
            json_response(handler, {"error": f"{net_key} does not exist on VM {vmid}"}, 404)
            return
        net_value = _build_net_config(config[net_key], bridge, vlan_id_val, firewall)
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} --{net_key} {shlex.quote(net_value)}", timeout=30)
        if ok and new_ip:
            cidr = new_ip if "/" in new_ip else new_ip + "/24"
            gw_part = f",gw={gateway}" if gateway else ""
            stdout, ok = _pve_cmd(
                cfg,
                node_ip,
                f"qm set {vmid} --ipconfig{nic_idx} {shlex.quote('ip=' + cidr + gw_part)}",
                timeout=30,
            )
        _respond_vm_mutation(
            handler,
            {
                "ok": ok,
                "vmid": vmid,
                "nic": net_key,
                "bridge": bridge,
                "vlan": vlan_id_val,
                "ip": new_ip,
                "error": stdout if not ok else "",
            },
            ok=ok,
            reason="update-nic",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm update-nic failed: {e}", endpoint="vm/update-nic")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


def handle_vm_delete_nic(handler):
    """POST /api/vm/delete-nic — delete one NIC and matching ipconfig."""
    if _require_post(handler, "VM delete NIC"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    query = get_params(handler)
    vmid = _get_int_param(handler, query, "vmid", required=True)
    nic_idx = _nic_index_param(handler, query)
    if vmid is None or nic_idx is None:
        return
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return
        net_key = f"net{nic_idx}"
        ip_key = f"ipconfig{nic_idx}"
        config_text, config_ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}", timeout=15)
        if config_ok and net_key not in _parse_qm_config_kv(config_text):
            json_response(handler, {"error": f"{net_key} does not exist on VM {vmid}"}, 404)
            return
        deleted = []
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} --delete {net_key}", timeout=30)
        if ok:
            deleted.append(net_key)
            ip_out, ip_ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} --delete {ip_key}", timeout=30)
            if ip_ok:
                deleted.append(ip_key)
            else:
                stdout = ip_out
        _respond_vm_mutation(
            handler,
            {"ok": ok, "vmid": vmid, "deleted": deleted, "error": stdout if not ok else ""},
            ok=ok,
            reason="delete-nic",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm delete-nic failed: {e}", endpoint="vm/delete-nic")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, query, "vmid", required=True)
    if vmid is None:
        return
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
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
            cfg=cfg,
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
                        cfg=cfg,
                    )
                    if r2.returncode == 0:
                        deleted.append(key)

        _refresh_fleet_overview_after_mutation("clear-nics", vmid)
        json_response(handler, {"ok": True, "vmid": vmid, "cleared": deleted, "count": len(deleted)})
    except Exception as e:
        logger.error(f"api_vm_error: vm clear-nics failed: {e}", endpoint="vm/clear-nics")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, query, "vmid", required=True)
    new_ip = query.get("ip", [""])[0]
    gateway = query.get("gw", [""])[0]
    if vmid is None or not new_ip:
        json_response(handler, {"error": "vmid and ip parameters required"}, 400)
        return
    bare_ip = new_ip.split("/")[0] if "/" in new_ip else new_ip
    if not valid_ip(bare_ip):
        json_response(handler, {"error": "Invalid IP address"}, 400)
        return
    if gateway and not valid_ip(gateway):
        json_response(handler, {"error": "Invalid gateway IP"}, 400)
        return
    # Fleet boundary check
    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    # Create the virtual NIC (net*) with VLAN tag + set cloud-init IP (ipconfig*)
    nic_idx = _get_int_param(handler, query, "nic", default=0)
    if nic_idx is None:
        return
    vlan_id_val = query.get("vlan", [""])[0]
    if vlan_id_val and not valid_vlan(vlan_id_val):
        json_response(handler, {"error": "Invalid VLAN ID"}, 400)
        return
    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
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
            cfg=cfg,
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
            cfg=cfg,
        )
        ok = r1.returncode == 0 and r2.returncode == 0
        err = ""
        if r1.returncode != 0:
            err = f"NIC create failed: {r1.stderr or r1.stdout}"
        elif r2.returncode != 0:
            err = f"IP config failed: {r2.stderr or r2.stdout}"
        _respond_vm_mutation(
            handler,
            {"ok": ok, "vmid": vmid, "ip": new_ip, "nic": nic_idx, "error": err},
            ok=ok,
            reason="change-ip",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm change-ip failed: {e}", endpoint="vm/change-ip")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


def handle_vm_push_key(handler):
    """POST /api/vm/push-key — push the freq SSH key to a target VM.

    Body: JSON {"ip": "<target>"}. F18 of
    R-SECURITY-TRUST-AUDIT-20260413P moved this from GET to POST
    because the handler modifies remote state (writes
    authorized_keys on target_ip) and a GET endpoint that mutates
    state violates the HTTP semantic contract: a stray operator
    visiting a malicious link triggered the push, the target IP
    landed in URL leak channels, and CSRF mitigation depended
    entirely on SameSite=Strict instead of being defense-in-depth.
    """
    if _require_post(handler, "VM push key"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    body = get_json_body(handler)
    target_ip = str(body.get("ip", "")).strip()
    if not target_ip or not valid_ip(target_ip):
        json_response(handler, {"error": "Valid IP required in JSON body {\"ip\": ...}"}, 400)
        return

    # Read the public key
    pub_path = cfg.ssh_key_path + ".pub"
    if not os.path.isfile(pub_path):
        json_response(handler, {"error": f"Public key not found: {pub_path}"}, 500)
        return
    with open(pub_path) as f:
        pubkey = f.read().strip()
    if not pubkey:
        json_response(handler, {"error": "Public key file is empty"}, 500)
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
        cfg=cfg,
    )
    if r.returncode != 0:
        json_response(handler, {"error": f"Key push failed: {r.stderr or r.stdout}"}, 502)
        return

    # Verify: try connecting as the deployed service account with the FREQ key
    r2 = ssh_single(
        host=target_ip,
        command="echo ok",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=5,
        htype="docker",
        use_sudo=False,
        cfg=cfg,
    )
    verified = r2.returncode == 0 and "ok" in (r2.stdout or "")
    json_response(handler, {"ok": True, "verified": verified, "ip": target_ip})


def handle_vm_add_disk(handler):
    """POST /api/vm/add-disk — add a disk to a VM."""
    if _require_post(handler, "VM add disk"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    vmid = _get_int_param(handler, params, "vmid", required=True)
    if vmid is None:
        return
    size = params.get("size", [""])[0]  # e.g. "32G"
    storage = params.get("storage", [""])[0]

    if not vmid or not size:
        json_response(handler, {"error": "vmid and size required"}, 400)
        return

    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    allocation_size, size_err = _normalize_disk_allocation_size(size)
    if size_err:
        json_response(handler, {"error": size_err}, 400)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return

        # Find next available scsi slot
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
        if not ok:
            json_response(handler, {"error": f"Cannot read VM config: {stdout}"}, 502)
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

        storage_target = storage or _existing_vm_disk_storage(stdout) or _default_image_storage(cfg, node_ip)
        cmd = f"qm set {vmid} --scsi{next_idx} {storage_target}:{allocation_size}"
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=60)
        _respond_vm_mutation(
            handler,
            {
                "ok": ok,
                "vmid": vmid,
                "disk": f"scsi{next_idx}",
                "size": size,
                "storage": storage_target,
                "error": stdout if not ok else "",
            },
            ok=ok,
            reason="add-disk",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm add-disk failed: {e}", endpoint="vm/add-disk")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    vmid = _get_int_param(handler, params, "vmid", required=True)
    if vmid is None:
        return
    tags = params.get("tags", [""])[0]  # comma-separated

    if not vmid:
        json_response(handler, {"error": "vmid required"}, 400)
        return

    allowed, err = _check_vm_permission(cfg, vmid, "configure")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    # Validate tag names
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag and not re.match(r"^[a-zA-Z0-9_-]+$", tag):
                json_response(handler, {"error": f"Invalid tag name: {tag}"}, 400)
                return

    try:
        node_ip = _find_vm_node_ip(cfg, vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return

        # PVE uses semicolon-separated tags
        pve_tags = ";".join(t.strip() for t in tags.split(",") if t.strip()) if tags else ""
        cmd = f'qm set {vmid} --tags "{pve_tags}"'
        stdout, ok = _pve_cmd(cfg, node_ip, cmd)
        _respond_vm_mutation(
            handler,
            {
                "ok": ok,
                "vmid": vmid,
                "tags": tags,
                "error": stdout if not ok else "",
            },
            ok=ok,
            reason="tag",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm tag failed: {e}", endpoint="vm/tag")
        json_response(handler, {"error": f"SSH operation failed: {e}"}, 502)


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
    source_vmid = _get_int_param(handler, params, "vmid", required=True)
    if source_vmid is None:
        return
    name = params.get("name", [""])[0]
    target_node = params.get("target_node", params.get("node", [""]))[0]
    storage = params.get("storage", [""])[0]
    full = params.get("full", ["1"])[0] == "1"
    explicit_newid = (
        params.get("newid")
        or params.get("new_vmid")
        or params.get("target_vmid")
        or [""]
    )[0]

    if not source_vmid:
        json_response(handler, {"error": "vmid (source) required"}, 400)
        return

    allowed, err = _clone_source_allowed(cfg, source_vmid)
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return
    target_node, target_node_err = _token_param(target_node, "target_node")
    if target_node_err:
        json_response(handler, {"error": target_node_err}, 400)
        return
    storage, storage_err = _token_param(storage, "storage")
    if storage_err:
        json_response(handler, {"error": storage_err}, 400)
        return

    try:
        node_ip = _find_vm_node_ip(cfg, source_vmid)
        if not node_ip:
            json_response(handler, {"error": f"Cannot find VM {source_vmid} on any PVE node"}, 404)
            return

        if explicit_newid:
            parsed_new_vmid = _parse_next_vmid(explicit_newid)
        else:
            stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
            if not ok:
                json_response(handler, {"error": "Cannot get next VMID"}, 502)
                return
            parsed_new_vmid = _parse_next_vmid(stdout.strip())
        if parsed_new_vmid <= 0:
            source = explicit_newid or "cluster nextid"
            json_response(handler, {"error": f"Invalid target VMID from {source}"}, 400)
            return

        target_allowed, target_err = _check_vm_permission(cfg, parsed_new_vmid, "configure")
        if not target_allowed:
            json_response(handler, {"error": f"Target VMID blocked: {target_err}"}, 403)
            return

        parts = ["qm", "clone", str(source_vmid), str(parsed_new_vmid)]
        if name:
            from freq.core.validate import shell_safe_name

            if not shell_safe_name(name):
                json_response(handler, {"error": f"Invalid VM name: {name}"}, 400)
                return
            parts.extend(["--name", name])
        if target_node:
            parts.extend(["--target", target_node])
        if storage:
            parts.extend(["--storage", storage])
        if full:
            parts.extend(["--full", "1"])

        cmd = " ".join(shlex.quote(part) for part in parts)
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=300)
        if not ok:
            _pve_cmd(cfg, node_ip, f"qm destroy {parsed_new_vmid} --purge 1", timeout=30)
        _respond_vm_mutation(
            handler,
            {
                "ok": ok,
                "source_vmid": source_vmid,
                "new_vmid": parsed_new_vmid,
                "name": name,
                "target_node": target_node,
                "storage": storage,
                "full_clone": full,
                "error": stdout if not ok else "",
            },
            ok=ok,
            reason="clone",
            vmid=parsed_new_vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm clone failed: {e}", endpoint="vm/clone")
        json_response(handler, {"error": f"Clone failed: {e}"}, 502)


def handle_vm_migrate(handler):
    """POST /api/vm/migrate — live migrate a VM to another node.

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
    vmid = _get_int_param(handler, params, "vmid", required=True)
    if vmid is None:
        return
    target_node = params.get("target_node", [""])[0]
    delete_snaps = params.get("delete_snapshots", ["0"])[0] == "1"

    if not vmid or not target_node:
        json_response(handler, {"error": "vmid and target_node required"}, 400)
        return

    allowed, err = _check_vm_permission(cfg, vmid, "migrate")
    if not allowed:
        json_response(handler, {"error": err}, 403)
        return

    if not re.match(r"^[a-zA-Z0-9_-]+$", target_node):
        json_response(handler, {"error": f"Invalid node name: {target_node}"}, 400)
        return

    try:
        from freq.modules.vm import _check_snapshots, _delete_snapshots, _find_best_local_storage, _find_vm_node

        # Find source node
        source_ip = _find_vm_node(cfg, vmid)
        if not source_ip:
            json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
            return

        # Resolve source node name
        source_node = "unknown"
        for i, ip in enumerate(cfg.pve_nodes):
            if ip == source_ip and i < len(cfg.pve_node_names):
                source_node = cfg.pve_node_names[i]
                break

        if source_node == target_node:
            json_response(handler, {"error": f"VM {vmid} is already on {target_node}"}, 409)
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
                409,
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

        _respond_vm_mutation(
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
            ok=ok,
            reason="migrate",
            vmid=vmid,
        )
    except Exception as e:
        logger.error(f"api_vm_error: vm migrate failed: {e}", endpoint="vm/migrate")
        json_response(handler, {"error": f"Migration failed: {e}"}, 502)


def handle_vm_wizard_defaults(handler):
    """GET /api/vm/wizard-defaults — defaults for VM creation wizard."""
    cfg = load_config()
    options = _vm_create_options_payload(cfg)
    profiles = getattr(cfg, "template_profiles", {})
    json_response(
        handler,
        {
            "schema_version": 1,
            "first_class": {
                "options_endpoint": "/api/vm/create/options",
                "plan_endpoint": "/api/vm/create/plan",
                "submit_endpoint": "/api/vm/create/submit",
                "job_endpoint": "/api/vm/create/job",
            },
            "defaults": {
                "cores": cfg.vm_default_cores,
                "ram": cfg.vm_default_ram,
                "disk": cfg.vm_default_disk,
                "cpu": cfg.vm_cpu,
                "storage": _configured_image_storage(cfg, cfg.pve_nodes[0] if cfg.pve_nodes else ""),
            },
            "profiles": profiles,
            "nodes": cfg.pve_node_names,
            "vlans": [{"name": v.name, "id": v.id, "subnet": v.subnet} for v in cfg.vlans],
            "distros": [{"key": d.key, "name": d.name} for d in cfg.distros],
            "options": options,
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
            cfg=cfg,
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
    if _require_post(handler, "VM rollback"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    params = get_params(handler)
    vmid = _get_int_param(handler, params, "vmid", required=True)
    snap_name = params.get("name", [""])[0]
    start_after = params.get("start", ["true"])[0].lower() != "false"
    if vmid is None:
        return

    cfg = load_config()

    if is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges):
        json_response(handler, {"error": f"VMID {vmid} is protected"}, 403)
        return
    node_ip = _find_vm_node_ip(cfg, vmid)
    if not node_ip:
        json_response(handler, {"error": f"Cannot find VM {vmid} on any PVE node"}, 404)
        return

    # Get snapshots
    snap_out, snap_ok = _pve_cmd(cfg, node_ip, f"qm listsnapshot {vmid}", timeout=10)
    if not snap_ok:
        json_response(handler, {"error": f"Cannot list snapshots for VM {vmid}"}, 500)
        return

    snaps = _parse_qm_snapshot_names(snap_out)

    if not snaps:
        json_response(handler, {"error": f"No snapshots found for VM {vmid}"}, 404)
        return

    if not snap_name:
        snap_name = snaps[-1]
    elif snap_name not in snaps:
        json_response(handler, {"error": f"Snapshot '{snap_name}' not found", "available": snaps}, 404)
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
    from urllib.parse import parse_qs, urlparse

    from freq.core.ssh import run as ssh_fn

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
            cfg=cfg,
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
                cfg=cfg,
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
    routes["/api/vm/create/options"] = handle_vm_create_options
    routes["/api/vm/network-profiles"] = handle_vm_network_profiles
    routes["/api/vm/create/plan"] = handle_vm_create_plan
    routes["/api/vm/create/submit"] = handle_vm_create_submit
    routes["/api/vm/create/job"] = handle_vm_create_job
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
    routes["/api/vm/update-nic"] = handle_vm_update_nic
    routes["/api/vm/delete-nic"] = handle_vm_delete_nic
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
