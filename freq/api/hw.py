"""Hardware domain API handlers -- /api/infra/idrac, /api/cost/*, /api/gwipe, etc.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for iDRAC management, cost tracking, and hardware wipe.
Why:   Decouples hardware logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import json
import time

from freq.api.helpers import json_response, get_params, get_cfg
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.modules.serve import (
    _bg_cache,
    _bg_lock,
    _parse_query,
    _check_session_role,
)
from freq.modules.vault import vault_get


# -- Handlers ----------------------------------------------------------------


def handle_idrac(handler):
    """GET /api/infra/idrac -- iDRAC data via SSH/racadm."""
    cfg = load_config()
    params = _parse_query(handler)
    action = params.get("action", ["status"])[0]
    target = params.get("target", [""])[0]

    fb = cfg.fleet_boundaries
    targets = {}
    for key, dev in fb.physical.items():
        if dev.device_type == "idrac":
            targets[dev.label] = dev.ip

    if target:
        matched = {k: v for k, v in targets.items() if target.lower() in k.lower()}
        idrac_ips = matched if matched else targets
    else:
        idrac_ips = targets

    actions = {
        "status": "racadm getsysinfo -s",
        "sensors": "racadm getsensorinfo",
        "sel": "racadm getsel -i 1-10",
        "storage": "racadm raid get vdisks",
        "network": "racadm getniccfg",
        "license": "racadm license view",
        "firmware": "racadm getversion",
    }

    cmd = actions.get(action, actions["status"])
    results = []

    idrac_key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
    for name, ip in idrac_ips.items():
        r = ssh_single(host=ip, command=cmd, key_path=idrac_key,
                        connect_timeout=3, command_timeout=15,
                        htype="idrac", use_sudo=False)
        results.append({
            "name": name,
            "ip": ip,
            "reachable": r.returncode == 0,
            "output": r.stdout[:2000] if r.returncode == 0 else "",
            "error": r.stderr[:100] if r.returncode != 0 else "",
        })

    json_response(handler, {"action": action, "targets": results})


def handle_cost(handler):
    """GET /api/cost -- return fleet cost estimates per host."""
    from freq.jarvis.cost import load_cost_config, compute_costs, costs_to_dicts, fleet_summary
    cfg = load_config()
    cost_cfg = load_cost_config(cfg.conf_dir)
    with _bg_lock:
        health = _bg_cache.get("health")
    if not health:
        json_response(handler, {"error": "No health data available yet"}, 503); return

    idrac_power = {}
    with _bg_lock:
        infra = _bg_cache.get("infra_quick")
    if infra:
        for dev in infra.get("devices", []):
            if dev.get("type") == "idrac" and dev.get("reachable"):
                from freq.jarvis.cost import parse_idrac_power
                watts = parse_idrac_power(dev.get("raw_sensors", ""))
                if watts > 0:
                    idrac_power[dev.get("label", "")] = watts

    costs = compute_costs(health, idrac_power, cost_cfg)
    summary = fleet_summary(costs, cost_cfg)
    json_response(handler, {
        "hosts": costs_to_dicts(costs),
        "summary": summary,
    })


def handle_cost_config(handler):
    """GET /api/cost/config -- return current cost configuration."""
    from freq.jarvis.cost import load_cost_config
    cfg = load_config()
    cost_cfg = load_cost_config(cfg.conf_dir)
    json_response(handler, {
        "rate_per_kwh": cost_cfg.rate_per_kwh,
        "currency": cost_cfg.currency,
        "pue": cost_cfg.pue,
    })


def handle_cost_waste(handler):
    """GET /api/cost-analysis/waste -- cost waste analysis."""
    json_response(handler, {"info": "Run freq cost-analysis waste for live data"})


def handle_cost_compare(handler):
    """GET /api/cost-analysis/compare -- cost comparison."""
    json_response(handler, {"info": "Run freq cost-analysis compare for live data"})


def handle_gwipe(handler):
    """GET /api/gwipe -- FREQ WIPE station status and operations."""
    cfg = load_config()
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}); return
    query = _parse_query(handler)
    action = query.get("action", ["status"])[0]
    try:
        host = vault_get(cfg, "gwipe", "gwipe_host") or ""
        key = vault_get(cfg, "gwipe", "gwipe_api_key") or ""
        if not host or not key:
            json_response(handler, {"error": "GWIPE station not configured in vault"}); return
        import urllib.request, urllib.error
        url = f"http://{host}:7980/api/v1/{action}"
        req = urllib.request.Request(url)
        req.add_header("X-API-Key", key)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        json_response(handler, {"ok": True, "action": action, "data": data})
    except Exception as e:
        json_response(handler, {"error": f"GWIPE operation failed: {e}"}, 500)


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register hardware API routes into the master route table."""
    routes["/api/infra/idrac"] = handle_idrac
    routes["/api/cost"] = handle_cost
    routes["/api/cost/config"] = handle_cost_config
    routes["/api/cost-analysis/waste"] = handle_cost_waste
    routes["/api/cost-analysis/compare"] = handle_cost_compare
    routes["/api/gwipe"] = handle_gwipe
