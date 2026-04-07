"""Hardware domain API handlers -- /api/infra/idrac, /api/cost/*, /api/gwipe, etc.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for iDRAC management, cost tracking, and hardware wipe.
Why:   Decouples hardware logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import json

from freq.core import log as logger
from freq.api.helpers import json_response
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
    """GET /api/infra/idrac -- iDRAC data + write ops via SSH/racadm.

    Read actions: status, sensors, sel, storage, network, license, firmware, power
    Write actions (admin only): poweron, poweroff, powercycle, hardreset,
        graceshutdown, clearsel, bootpxe, bootbios
    """
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
        if not matched:
            json_response(handler, {"error": f"No iDRAC matching '{target}'"}, 404)
            return
        idrac_ips = matched
    else:
        idrac_ips = targets

    # -- Read actions (no role check) --
    read_actions = {
        "status": "racadm getsysinfo -s",
        "sensors": "racadm getsensorinfo",
        "sel": "racadm getsel -i 1-10",
        "storage": "racadm raid get vdisks",
        "network": "racadm getniccfg",
        "license": "racadm license view",
        "firmware": "racadm getversion",
        "power": "racadm serveraction powerstatus",
    }

    # -- Write actions (admin only) --
    write_actions = {
        "poweron": "racadm serveraction powerup",
        "poweroff": "racadm serveraction powerdown",
        "powercycle": "racadm serveraction powercycle",
        "hardreset": "racadm serveraction hardreset",
        "graceshutdown": "racadm serveraction graceshutdown",
        "clearsel": "racadm clrsel",
        "bootpxe": "racadm set iDRAC.ServerBoot.FirstBootDevice PXE",
        "bootbios": "racadm set iDRAC.ServerBoot.FirstBootDevice BiosSetup",
        "bootnormal": "racadm set iDRAC.ServerBoot.FirstBootDevice Normal",
    }

    if action in write_actions:
        role, err = _check_session_role(handler, "admin")
        if err:
            json_response(handler, {"error": err}, 403)
            return
        if not target:
            json_response(handler, {"error": "target required for write operations"}, 400)
            return
        cmd = write_actions[action]
    elif action in read_actions:
        cmd = read_actions[action]
    else:
        json_response(handler, {"error": f"Unknown action: {action}"}, 400)
        return

    results = []
    idrac_key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
    for name, ip in idrac_ips.items():
        r = ssh_single(
            host=ip,
            command=cmd,
            key_path=idrac_key,
            connect_timeout=3,
            command_timeout=15,
            htype="idrac",
            use_sudo=False,
        )
        results.append(
            {
                "name": name,
                "ip": ip,
                "reachable": r.returncode == 0,
                "output": r.stdout[:2000] if r.returncode == 0 else "",
                "error": r.stderr[:100] if r.returncode != 0 else "",
            }
        )

    json_response(handler, {"action": action, "targets": results})


def handle_cost(handler):
    """GET /api/cost -- return fleet cost estimates per host."""
    from freq.jarvis.cost import load_cost_config, compute_costs, costs_to_dicts, fleet_summary

    cfg = load_config()
    cost_cfg = load_cost_config(cfg.conf_dir)
    with _bg_lock:
        health = _bg_cache.get("health")
    if not health:
        json_response(handler, {"error": "No health data available yet"}, 503)
        return

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
    json_response(
        handler,
        {
            "hosts": costs_to_dicts(costs),
            "summary": summary,
        },
    )


def handle_cost_config(handler):
    """GET /api/cost/config -- return current cost configuration."""
    from freq.jarvis.cost import load_cost_config

    cfg = load_config()
    cost_cfg = load_cost_config(cfg.conf_dir)
    json_response(
        handler,
        {
            "rate_per_kwh": cost_cfg.rate_per_kwh,
            "currency": cost_cfg.currency,
            "pue": cost_cfg.pue,
        },
    )


def handle_cost_waste(handler):
    """GET /api/cost-analysis/waste -- find overprovisioned VMs wasting resources."""
    cfg = load_config()
    try:
        from freq.modules.cost_analysis import _gather_vm_resources, _estimate_vm_monthly_cost

        vms = _gather_vm_resources(cfg)
        if not vms:
            json_response(handler, {"waste": [], "stopped": [], "potential_savings": 0})
            return

        running = [v for v in vms if v.get("status") == "running"]
        waste = []
        total_savings = 0
        for v in running:
            issues = []
            if v.get("vcpu", 0) > 2 and v.get("cpu_usage", 100) < 10:
                issues.append(f"CPU: {v['cpu_usage']:.0f}% of {v['vcpu']} cores")
            if v.get("ram_mb", 0) > 2048 and v.get("mem_usage", 100) < 20:
                issues.append(f"RAM: {v['mem_usage']:.0f}% of {v['ram_mb']}MB")
            if issues:
                current = _estimate_vm_monthly_cost(v["vcpu"], v["ram_mb"] / 1024)
                right = _estimate_vm_monthly_cost(max(v["vcpu"] // 2, 1), max(v["ram_mb"] // 2048, 1))
                savings = round(current - right, 2)
                total_savings += savings
                waste.append(
                    {
                        "vmid": v["vmid"],
                        "name": v.get("name", "?"),
                        "issues": issues,
                        "savings_month": savings,
                        "vcpu": v["vcpu"],
                        "ram_mb": v["ram_mb"],
                        "cpu_usage": round(v.get("cpu_usage", 0), 1),
                        "mem_usage": round(v.get("mem_usage", 0), 1),
                    }
                )

        stopped = [
            {"vmid": v["vmid"], "name": v.get("name", "?"), "vcpu": v.get("vcpu", 0), "ram_mb": v.get("ram_mb", 0)}
            for v in vms
            if v.get("status") != "running"
        ]

        json_response(
            handler,
            {
                "waste": waste,
                "stopped": stopped,
                "potential_savings": round(total_savings, 2),
                "total_vms": len(vms),
                "running": len(running),
            },
        )
    except Exception as e:
        logger.error(f"api_hw_error: waste analysis failed: {e}", endpoint="cost-analysis/waste")
        json_response(handler, {"error": f"Waste analysis failed: {e}"}, 500)


def handle_cost_compare(handler):
    """GET /api/cost-analysis/compare -- on-prem vs cloud cost comparison."""
    cfg = load_config()
    try:
        from freq.modules.cost_analysis import _gather_vm_resources, _estimate_vm_monthly_cost, _estimate_aws_cost

        params = _parse_query(handler)
        rate = float(params.get("rate", ["0.12"])[0])

        vms = _gather_vm_resources(cfg)
        if not vms:
            json_response(handler, {"vms": [], "total_onprem": 0, "total_aws": 0})
            return

        running = [v for v in vms if v.get("status") == "running"]
        total_onprem = 0
        total_aws = 0
        comparisons = []

        for v in running:
            vcpu = v.get("vcpu", 1)
            ram_gb = v.get("ram_mb", 1024) / 1024
            onprem = _estimate_vm_monthly_cost(vcpu, ram_gb, rate)
            aws = _estimate_aws_cost(vcpu, ram_gb)
            total_onprem += onprem
            total_aws += aws
            comparisons.append(
                {
                    "vmid": v["vmid"],
                    "name": v.get("name", "?"),
                    "vcpu": vcpu,
                    "ram_gb": round(ram_gb, 1),
                    "onprem_month": round(onprem, 2),
                    "aws_month": round(aws, 2),
                    "savings": round(aws - onprem, 2),
                }
            )

        pct_cheaper = round((1 - total_onprem / max(total_aws, 1)) * 100)
        json_response(
            handler,
            {
                "vms": comparisons,
                "total_onprem": round(total_onprem, 2),
                "total_aws": round(total_aws, 2),
                "monthly_savings": round(total_aws - total_onprem, 2),
                "annual_savings": round((total_aws - total_onprem) * 12, 2),
                "pct_cheaper_onprem": pct_cheaper,
                "rate_per_kwh": rate,
            },
        )
    except Exception as e:
        logger.error(f"api_hw_error: cost comparison failed: {e}", endpoint="cost-analysis/compare")
        json_response(handler, {"error": f"Cost comparison failed: {e}"}, 500)


def handle_gwipe(handler):
    """GET /api/gwipe -- FREQ WIPE station status and operations."""
    cfg = load_config()
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err})
        return
    import re

    query = _parse_query(handler)
    action = query.get("action", ["status"])[0]
    if not re.match(r"^[a-zA-Z0-9_\-]{1,32}$", action):
        json_response(handler, {"error": "Invalid action"}, 400)
        return
    try:
        host = vault_get(cfg, "gwipe", "gwipe_host") or ""
        key = vault_get(cfg, "gwipe", "gwipe_api_key") or ""
        if not host or not key:
            json_response(handler, {"error": "GWIPE station not configured in vault"})
            return
        import urllib.request, urllib.error

        url = f"http://{host}:7980/api/v1/{action}"
        req = urllib.request.Request(url)
        req.add_header("X-API-Key", key)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        json_response(handler, {"ok": True, "action": action, "data": data})
    except Exception as e:
        logger.error(f"api_hw_error: GWIPE operation failed: {e}", endpoint="gwipe")
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
