"""Network domain API handlers -- /api/switch, /api/map/*, /api/netmon/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for switch management, dependency maps, and network monitoring.
Why:   Decouples network logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

from freq.api.helpers import json_response, get_params, get_cfg
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.modules.serve import _parse_query


# -- Handlers ----------------------------------------------------------------


def handle_switch(handler):
    """GET /api/switch -- switch data via SSH."""
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
    r = ssh_single(host=switch_ip, command=cmd, key_path=sw_key,
                    connect_timeout=3, command_timeout=15, htype="switch", use_sudo=False)
    json_response(handler, {"action": action, "host": switch_ip, "reachable": r.returncode == 0,
                            "output": r.stdout if r.returncode == 0 else "", "error": r.stderr[:100] if r.returncode != 0 else ""})


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
        json_response(handler, {"error": "host parameter required"}, 400); return
    depmap = _load_map(cfg)
    impact = _get_impact(depmap, target)
    json_response(handler, impact)


def handle_netmon_interfaces(handler):
    """GET /api/netmon/interfaces -- network interfaces info."""
    json_response(handler, {"info": "Run freq netmon interfaces for live data"})


def handle_netmon_data(handler):
    """GET /api/netmon/data -- get netmon poll data."""
    from freq.modules.netmon import _load_data
    cfg = load_config()
    data = _load_data(cfg)
    json_response(handler, {"snapshots": data.get("snapshots", [])[-20:],
                            "total": len(data.get("snapshots", []))})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register network API routes into the master route table."""
    routes["/api/switch"] = handle_switch
    routes["/api/map/data"] = handle_map_data
    routes["/api/map/impact"] = handle_map_impact
    routes["/api/netmon/interfaces"] = handle_netmon_interfaces
    routes["/api/netmon/data"] = handle_netmon_data
