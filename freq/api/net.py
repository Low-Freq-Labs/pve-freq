"""Network domain API handlers -- /api/v1/net/switch/*, /api/map/*, /api/netmon/*.

Who:   Switch endpoints use deployer getters for vendor-agnostic data.
What:  REST endpoints for switch management, dependency maps, and network monitoring.
Why:   Decouples network logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* and /api/v1/net/*.
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import re

from freq.core import log as logger
from freq.api.helpers import require_post,  json_response, get_param, get_json_body
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single, result_for
from freq.modules.serve import _parse_query, _check_session_role


# -- Switch Deployer Helpers ------------------------------------------------


def _resolve_switch(cfg, target=None):
    """Resolve switch target and load deployer. Returns (ip, label, deployer) or Nones."""
    from freq.modules.switch_orchestration import _resolve_target, _get_deployer

    ip, label, vendor = _resolve_target(target, cfg)
    if not ip:
        return None, None, None
    deployer = _get_deployer(vendor)
    return ip, label, deployer


# -- V1 Switch Endpoints ---------------------------------------------------


def handle_switch_show(handler):
    """GET /api/v1/net/switch/show -- switch overview (facts + interface summary)."""
    cfg = load_config()
    target = get_param(handler, "target")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    facts = deployer.get_facts(ip, cfg)
    interfaces = deployer.get_interfaces(ip, cfg)
    vlans = deployer.get_vlans(ip, cfg)
    up = sum(1 for i in interfaces if i.get("status") == "connected")
    json_response(
        handler,
        {
            "host": label,
            "ip": ip,
            "facts": facts,
            "interface_summary": {"total": len(interfaces), "up": up, "down": len(interfaces) - up},
            "vlan_count": len(vlans),
        },
    )


def handle_switch_facts(handler):
    """GET /api/v1/net/switch/facts -- device facts."""
    cfg = load_config()
    target = get_param(handler, "target")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    facts = deployer.get_facts(ip, cfg)
    json_response(handler, {"host": label, "ip": ip, "facts": facts})


def handle_switch_interfaces(handler):
    """GET /api/v1/net/switch/interfaces -- interface table."""
    cfg = load_config()
    target = get_param(handler, "target")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    interfaces = deployer.get_interfaces(ip, cfg)
    json_response(handler, {"host": label, "ip": ip, "interfaces": interfaces})


def handle_switch_vlans(handler):
    """GET /api/v1/net/switch/vlans -- VLAN table."""
    cfg = load_config()
    target = get_param(handler, "target")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    vlans = deployer.get_vlans(ip, cfg)
    json_response(handler, {"host": label, "ip": ip, "vlans": vlans})


def handle_switch_mac(handler):
    """GET /api/v1/net/switch/mac -- MAC address table."""
    cfg = load_config()
    target = get_param(handler, "target")
    vlan = get_param(handler, "vlan")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    entries = deployer.get_mac_table(ip, cfg)
    if vlan:
        entries = [e for e in entries if e.get("vlan") == int(vlan)]
    json_response(handler, {"host": label, "ip": ip, "mac_table": entries})


def handle_switch_arp(handler):
    """GET /api/v1/net/switch/arp -- ARP table."""
    cfg = load_config()
    target = get_param(handler, "target")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    entries = deployer.get_arp_table(ip, cfg)
    json_response(handler, {"host": label, "ip": ip, "arp_table": entries})


def handle_switch_neighbors(handler):
    """GET /api/v1/net/switch/neighbors -- CDP/LLDP neighbors."""
    cfg = load_config()
    target = get_param(handler, "target")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    neighbors = deployer.get_neighbors(ip, cfg)
    json_response(handler, {"host": label, "ip": ip, "neighbors": neighbors})


def handle_switch_environment(handler):
    """GET /api/v1/net/switch/environment -- temperature, fans, PSU, CPU, memory."""
    cfg = load_config()
    target = get_param(handler, "target")
    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer available"}, 404)
        return
    env = deployer.get_environment(ip, cfg)
    json_response(handler, {"host": label, "ip": ip, "environment": env})


# -- Legacy Endpoint (backwards compat for dashboard) ----------------------


def handle_switch(handler):
    """GET /api/switch -- legacy switch data via SSH (kept for dashboard compat)."""
    cfg = load_config()
    params = _parse_query(handler)
    action = params.get("action", ["status"])[0]
    switch_ip = cfg.switch_ip
    if not switch_ip:
        json_response(handler, {"error": "No switch_ip configured in freq.toml [infrastructure]"}, 400)
        return
    actions = {
        "status": "show version | include uptime",
        "vlans": "show vlan brief",
        "interfaces": "show ip interface brief",
        "mac": "show mac address-table | exclude Drop",
        "trunk": "show interfaces trunk",
        "errors": "show interfaces counters errors",
        "spanning": "show spanning-tree brief",
        "log": "show logging | tail 30",
        "cdp": "show cdp neighbors",
        "inventory": "show inventory",
    }
    cmd = actions.get(action, actions["status"])
    sw_key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
    r = ssh_single(
        host=switch_ip,
        command=cmd,
        key_path=sw_key,
        connect_timeout=3,
        command_timeout=15,
        htype="switch",
        use_sudo=False,
        cfg=cfg,
    )
    json_response(
        handler,
        {
            "action": action,
            "host": switch_ip,
            "reachable": r.returncode == 0,
            "output": r.stdout if r.returncode == 0 else "",
            "error": r.stderr[:100] if r.returncode != 0 else "",
        },
    )


# -- Map/Netmon Endpoints (unchanged) --------------------------------------


def handle_map_data(handler):
    """GET /api/map/data -- get dependency map."""
    from freq.modules.depmap import _load_map

    cfg = load_config()
    json_response(handler, _load_map(cfg))


def handle_map_impact(handler):
    """GET /api/map/impact -- impact analysis for a host."""
    from freq.modules.depmap import _load_map, _get_impact

    cfg = load_config()
    params = _parse_query(handler)
    target = params.get("host", [""])[0].strip()
    if not target:
        json_response(handler, {"error": "host parameter required"}, 400)
        return
    depmap = _load_map(cfg)
    impact = _get_impact(depmap, target)
    json_response(handler, impact)


def handle_netmon_interfaces(handler):
    """GET /api/netmon/interfaces -- live network interface data across fleet."""
    import json as _json

    cfg = load_config()
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"hosts": [], "total_interfaces": 0})
        return

    command = "ip -j addr show 2>/dev/null || echo '[]'"
    from freq.core.ssh import run_many as ssh_run_many, result_for

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    all_hosts = []
    total = 0
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0:
            continue
        try:
            ifaces_raw = _json.loads(r.stdout.strip())
        except (_json.JSONDecodeError, ValueError) as e:
            logger.debug(f"api_net: failed to parse interface data from {h.label}: {e}")
            continue
        ifaces = []
        for iface in ifaces_raw:
            name = iface.get("ifname", "?")
            if name == "lo":
                continue
            state = iface.get("operstate", "UNKNOWN").lower()
            mac = iface.get("address", "-")
            ips = []
            for addr in iface.get("addr_info", []):
                if addr.get("family") == "inet":
                    ips.append(f"{addr['local']}/{addr.get('prefixlen', '?')}")
            ifaces.append(
                {
                    "name": name,
                    "state": state,
                    "mac": mac,
                    "ips": ips,
                    "mtu": iface.get("mtu", 0),
                }
            )
            total += 1
        all_hosts.append({"host": h.label, "interfaces": ifaces})

    json_response(handler, {"hosts": all_hosts, "total_interfaces": total})


def handle_netmon_data(handler):
    """GET /api/netmon/data -- get netmon poll data."""
    from freq.modules.netmon import _load_data

    cfg = load_config()
    data = _load_data(cfg)
    json_response(handler, {"snapshots": data.get("snapshots", [])[-20:], "total": len(data.get("snapshots", []))})


# -- V1 Config Endpoints ----------------------------------------------------


def handle_config_history(handler):
    """GET /api/v1/net/config/history -- config backup history."""
    from freq.modules.config_management import _list_backups
    import os

    cfg = load_config()
    target = get_param(handler, "target")

    backups = _list_backups(cfg, target or None)
    entries = []
    for filepath, label, ts in backups:
        formatted = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
        entries.append(
            {
                "label": label,
                "timestamp": formatted,
                "size": os.path.getsize(filepath),
                "file": os.path.basename(filepath),
            }
        )
    json_response(handler, {"backups": entries})


def handle_config_search(handler):
    """GET /api/v1/net/config/search -- search across stored configs."""
    from freq.modules.config_management import _list_backups

    cfg = load_config()
    pattern = get_param(handler, "pattern")
    if not pattern:
        json_response(handler, {"error": "pattern parameter required"}, 400)
        return

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        json_response(handler, {"error": f"Invalid pattern: {e}"}, 400)
        return

    seen = set()
    results = []
    for filepath, label, ts in _list_backups(cfg):
        if label in seen:
            continue
        seen.add(label)
        with open(filepath) as f:
            lines = f.readlines()
        matches = [(i + 1, l.rstrip()) for i, l in enumerate(lines) if regex.search(l)]
        if matches:
            results.append({"device": label, "matches": [{"line": n, "text": t} for n, t in matches[:20]]})

    json_response(handler, {"pattern": pattern, "results": results, "total_devices": len(results)})


# -- V1 Switch Write Endpoints (admin) -------------------------------------

_SAFE_VLAN_ID = re.compile(r"^\d{1,4}$")
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_\-]{1,32}$")


def handle_switch_vlan_create(handler):
    """POST /api/v1/net/switch/vlan/create -- create a VLAN.

    Body: {"target": "switch-label", "vlan_id": 100, "name": "SERVERS"}
    """
    if require_post(handler, "VLAN create"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    body = get_json_body(handler)
    target = body.get("target", "")
    vlan_id = str(body.get("vlan_id", ""))
    vlan_name = body.get("name", "")

    if not _SAFE_VLAN_ID.match(vlan_id) or not (1 <= int(vlan_id) <= 4094):
        json_response(handler, {"error": "VLAN ID must be 1-4094"}, 400)
        return
    if vlan_name and not _SAFE_NAME.match(vlan_name):
        json_response(handler, {"error": "Invalid VLAN name"}, 400)
        return

    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer"}, 404)
        return

    if not hasattr(deployer, "create_vlan"):
        json_response(handler, {"error": "Deployer does not support VLAN creation"}, 400)
        return

    ok = deployer.create_vlan(ip, cfg, int(vlan_id), vlan_name)
    json_response(
        handler,
        {
            "ok": ok,
            "host": label,
            "ip": ip,
            "vlan_id": int(vlan_id),
            "name": vlan_name,
        },
    )


def handle_switch_vlan_delete(handler):
    """POST /api/v1/net/switch/vlan/delete -- delete a VLAN.

    Body: {"target": "switch-label", "vlan_id": 100}
    """
    if require_post(handler, "VLAN delete"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    body = get_json_body(handler)
    target = body.get("target", "")
    vlan_id = str(body.get("vlan_id", ""))

    if not _SAFE_VLAN_ID.match(vlan_id) or not (1 <= int(vlan_id) <= 4094):
        json_response(handler, {"error": "VLAN ID must be 1-4094"}, 400)
        return
    if int(vlan_id) == 1:
        json_response(handler, {"error": "Cannot delete VLAN 1 (default)"}, 400)
        return

    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer"}, 404)
        return

    if not hasattr(deployer, "delete_vlan"):
        json_response(handler, {"error": "Deployer does not support VLAN deletion"}, 400)
        return

    ok = deployer.delete_vlan(ip, cfg, int(vlan_id))
    json_response(handler, {"ok": ok, "host": label, "vlan_id": int(vlan_id)})


def handle_switch_acl(handler):
    """POST /api/v1/net/switch/acl -- manage ACLs.

    Body: {"action": "list|create|delete|apply|remove",
           "target": "switch-label", "name": "ACL_NAME",
           "entries": ["permit tcp any host 10.0.0.1 eq 80"],
           "port": "GigabitEthernet1/0/1", "direction": "in"}
    """
    if require_post(handler, "ACL management"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    body = get_json_body(handler)
    action = body.get("action", "list")
    target = body.get("target", "")

    ip, label, deployer = _resolve_switch(cfg, target or None)
    if not deployer:
        json_response(handler, {"error": "Switch not found or no deployer"}, 404)
        return

    if action == "list":
        if hasattr(deployer, "get_acls"):
            acls = deployer.get_acls(ip, cfg)
            json_response(handler, {"ok": True, "host": label, "acls": acls})
        else:
            json_response(handler, {"error": "Deployer does not support ACL listing"}, 400)
        return

    acl_name = body.get("name", "")
    if not acl_name or not _SAFE_NAME.match(acl_name):
        json_response(handler, {"error": "Invalid ACL name"}, 400)
        return

    if action == "create":
        entries = body.get("entries", [])
        if not entries or not isinstance(entries, list):
            json_response(handler, {"error": "entries required (list of ACL rules)"}, 400)
            return
        # Validate each ACL entry — must start with permit/deny, no IOS escape sequences
        _ACL_LINE = re.compile(r"^(permit|deny)\s+[a-zA-Z0-9 .:_/\-]+$")
        for entry in entries:
            if not isinstance(entry, str) or not _ACL_LINE.match(entry.strip()):
                json_response(
                    handler, {"error": f"Invalid ACL entry: {entry!r}. Must start with 'permit' or 'deny'."}, 400
                )
                return
        ok = deployer.create_acl(ip, cfg, acl_name, entries)
        json_response(handler, {"ok": ok, "host": label, "name": acl_name})

    elif action == "delete":
        ok = deployer.delete_acl(ip, cfg, acl_name)
        json_response(handler, {"ok": ok, "host": label, "name": acl_name})

    elif action == "apply":
        port = body.get("port", "")
        direction = body.get("direction", "in")
        if not port or not re.match(r"^[a-zA-Z0-9/\-]{1,40}$", port):
            json_response(handler, {"error": "Valid port name required (e.g. GigabitEthernet1/0/1)"}, 400)
            return
        if direction not in ("in", "out"):
            json_response(handler, {"error": "direction must be in or out"}, 400)
            return
        ok = deployer.apply_acl_to_interface(ip, cfg, port, acl_name, direction)
        json_response(handler, {"ok": ok, "host": label, "port": port, "acl": acl_name})

    elif action == "remove":
        port = body.get("port", "")
        direction = body.get("direction", "in")
        if not port or not re.match(r"^[a-zA-Z0-9/\-]{1,40}$", port):
            json_response(handler, {"error": "Valid port name required"}, 400)
            return
        if direction not in ("in", "out"):
            json_response(handler, {"error": "direction must be in or out"}, 400)
            return
        ok = deployer.remove_acl_from_interface(ip, cfg, port, acl_name, direction)
        json_response(handler, {"ok": ok, "host": label, "port": port, "acl": acl_name})

    else:
        json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register network API routes into the master route table."""
    # V1 switch endpoints (deployer-backed)
    routes["/api/v1/net/switch/show"] = handle_switch_show
    routes["/api/v1/net/switch/facts"] = handle_switch_facts
    routes["/api/v1/net/switch/interfaces"] = handle_switch_interfaces
    routes["/api/v1/net/switch/vlans"] = handle_switch_vlans
    routes["/api/v1/net/switch/mac"] = handle_switch_mac
    routes["/api/v1/net/switch/arp"] = handle_switch_arp
    routes["/api/v1/net/switch/neighbors"] = handle_switch_neighbors
    routes["/api/v1/net/switch/environment"] = handle_switch_environment

    # V1 switch write endpoints (admin)
    routes["/api/v1/net/switch/vlan/create"] = handle_switch_vlan_create
    routes["/api/v1/net/switch/vlan/delete"] = handle_switch_vlan_delete
    routes["/api/v1/net/switch/acl"] = handle_switch_acl

    # V1 config endpoints
    routes["/api/v1/net/config/history"] = handle_config_history
    routes["/api/v1/net/config/search"] = handle_config_search

    # Legacy (dashboard compat)
    routes["/api/switch"] = handle_switch

    # Map / Netmon
    routes["/api/map/data"] = handle_map_data
    routes["/api/map/impact"] = handle_map_impact
    routes["/api/netmon/interfaces"] = handle_netmon_interfaces
    routes["/api/netmon/data"] = handle_netmon_data
