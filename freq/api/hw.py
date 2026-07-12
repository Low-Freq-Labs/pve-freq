"""Hardware domain API handlers -- /api/infra/idrac, /api/cost/*, /api/gwipe, etc.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for iDRAC management, cost tracking, and hardware wipe.
Why:   Decouples hardware logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import copy
import json
import os
import re
import time

from freq.api.helpers import json_response, require_post
from freq.core import log as logger
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.modules import serve as serve_module
from freq.modules.serve import (
    _bg_cache,
    _bg_cache_ts,
    _bg_lock,
    _check_session_role,
    _parse_query,
)
from freq.modules.vault import vault_get

IDRAC_READ_CONNECT_TIMEOUT = 10
IDRAC_READ_COMMAND_TIMEOUT = 30
IDRAC_INVENTORY_COMMAND_TIMEOUT = 75
IDRAC_STATUS_CACHE_SECONDS = 360
# Share the same iDRAC throttle as background health/infra probes. These
# legacy controllers have tiny SSH session limits, and a per-module lock still
# lets dashboard reads collide with service health probes inside one process.
IDRAC_SESSION_LOCK = serve_module.IDRAC_SESSION_LOCK
IDRAC_SESSION_GAP_SECONDS = serve_module.IDRAC_SESSION_GAP_SECONDS
_idrac_read_cache = {}


def _read_named_cache(cfg, name: str):
    path = os.path.join(cfg.data_dir, "cache", f"{name}.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, 0.0
    if isinstance(raw, dict) and "data" in raw:
        return raw.get("data"), float(raw.get("ts") or 0)
    return raw, 0.0


def _cached_idrac_result(ip: str, cmd: str):
    item = _idrac_read_cache.get((ip, cmd))
    if not item:
        return None
    if time.time() - item["ts"] > IDRAC_STATUS_CACHE_SECONDS:
        return None
    return type(
        "R",
        (),
        {
            "returncode": 0,
            "stdout": item["stdout"],
            "stderr": "",
            "duration": 0.0,
            "from_cache": True,
        },
    )()


def _store_idrac_result(ip: str, cmd: str, r) -> None:
    if getattr(r, "returncode", 1) != 0 or not (getattr(r, "stdout", "") or "").strip():
        return
    _idrac_read_cache[(ip, cmd)] = {"ts": time.time(), "stdout": r.stdout}


def _idrac_status_from_probe_cache(cfg, name: str, ip: str):
    """Return fresh BMC status from background probe truth when available."""
    now = time.time()
    with _bg_lock:
        health = _bg_cache.get("health") or {}
        health_ts = _bg_cache_ts.get("health", 0) or 0
        infra = _bg_cache.get("infra_quick") or {}
        infra_ts = _bg_cache_ts.get("infra_quick", 0) or 0

    # The background threads persist cache to disk independently of API reads.
    # A dashboard button must not open a scarce iDRAC SSH session just because
    # this worker's in-memory cache is cold or slightly behind the persisted
    # truth written by the probe loop.
    if not isinstance(health, dict) or not health.get("hosts"):
        health, health_ts = _read_named_cache(cfg, "health")
        health = health if isinstance(health, dict) else {}
    if not isinstance(infra, dict) or not infra.get("devices"):
        infra, infra_ts = _read_named_cache(cfg, "infra_quick")
        infra = infra if isinstance(infra, dict) else {}

    for row in health.get("hosts", []) or []:
        if row.get("ip") != ip and str(row.get("label", "")).lower() != name.lower():
            continue
        age = now - float(row.get("probed_at") or health_ts or 0)
        if age > IDRAC_STATUS_CACHE_SECONDS:
            continue
        state = str(row.get("state") or row.get("status") or "").lower()
        if state not in {"live", "healthy", "recovering"}:
            continue
        metrics = row.get("management_metrics") or row
        model = metrics.get("model") or row.get("model") or "unknown"
        power = metrics.get("power") or row.get("power") or "unknown"
        output = (
            "System Information:\n"
            f"System Model            = {model}\n"
            f"Power Status            = {power}\n"
            f"iDRAC Probe Source      = health cache ({age:.0f}s old)\n"
        )
        return type("R", (), {"returncode": 0, "stdout": output, "stderr": "", "duration": 0.0})()

    for row in infra.get("devices", []) or []:
        if row.get("ip") != ip and str(row.get("label", "")).lower() != name.lower():
            continue
        age = now - float(infra_ts or 0)
        if age > IDRAC_STATUS_CACHE_SECONDS or not row.get("reachable"):
            continue
        metrics = row.get("metrics") or {}
        model = metrics.get("model") or "unknown"
        power = metrics.get("power") or "unknown"
        output = (
            "System Information:\n"
            f"System Model            = {model}\n"
            f"Power Status            = {power}\n"
            f"iDRAC Probe Source      = infra cache ({age:.0f}s old)\n"
        )
        return type("R", (), {"returncode": 0, "stdout": output, "stderr": "", "duration": 0.0})()

    return None


def _is_auth_failure(text: str) -> bool:
    low = (text or "").lower()
    return "permission denied" in low or "publickey" in low or "authentication failed" in low


def _idrac_failure_evidence(r) -> str:
    stderr = (getattr(r, "stderr", "") or "").strip()
    stdout = (getattr(r, "stdout", "") or "").strip()
    combined = f"{stderr}\n{stdout}".lower()
    if "no more sessions are available" in combined:
        return (
            "iDRAC SSH session limit reached. Wait for old BMC sessions to expire, "
            "then retry one action at a time."
        )
    if stderr:
        return stderr[:300]
    if stdout:
        return stdout[:300]
    return f"SSH command failed with rc={getattr(r, 'returncode', '?')} and no stderr"


def _run_idrac_read(cfg, ip: str, cmd: str, command_timeout: int = IDRAC_READ_COMMAND_TIMEOUT):
    """Run iDRAC reads in the same order as init/infra quick.

    Dell iDRAC is legacy SSH. The product contract is key-first with the
    deployed service account, then password fallback only when auth fails.
    Generic ssh.run prefers legacy_password_file when present, so call it
    with a copy that disables password auth for the first pass.
    """
    if cmd == "racadm getsysinfo -s":
        cached = _cached_idrac_result(ip, cmd)
        if cached is not None:
            return cached

    with IDRAC_SESSION_LOCK:
        since = time.monotonic() - serve_module._idrac_last_session_at
        if since < IDRAC_SESSION_GAP_SECONDS:
            time.sleep(IDRAC_SESSION_GAP_SECONDS - since)
        idrac_key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
        key_cfg = copy.copy(cfg)
        key_cfg.legacy_password_file = ""
        r = ssh_single(
            host=ip,
            command=cmd,
            user=cfg.ssh_service_account,
            key_path=idrac_key,
            connect_timeout=IDRAC_READ_CONNECT_TIMEOUT,
            command_timeout=command_timeout,
            htype="idrac",
            use_sudo=False,
            cfg=key_cfg,
            failure_log_level="warn",
        )
        if r.returncode != 0 and _is_auth_failure(f"{r.stderr}\n{r.stdout}") and getattr(cfg, "legacy_password_file", ""):
            r = ssh_single(
                host=ip,
                command=cmd,
                user=cfg.ssh_service_account,
                key_path=idrac_key,
                connect_timeout=IDRAC_READ_CONNECT_TIMEOUT,
                command_timeout=command_timeout,
                htype="idrac",
                use_sudo=False,
                cfg=cfg,
                failure_log_level="warn",
            )
        serve_module._idrac_last_session_at = time.monotonic()
    _store_idrac_result(ip, cmd, r)
    return r


def _idrac_int(value):
    m = re.search(r"([0-9][0-9,]*)", str(value or ""))
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def _idrac_status_bad(value):
    low = str(value or "").lower()
    return any(token in low for token in ("error", "critical", "failed", "failure", "degraded"))


def _parse_idrac_hwinventory(text: str) -> dict:
    """Parse Dell iDRAC `racadm hwinventory` output into operator stats."""
    blocks = []
    current = None
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) <= {"-"}:
            continue
        m = re.match(r"\[InstanceID:\s*(.+?)\s*\]", stripped)
        if m:
            if current:
                blocks.append(current)
            current = {"instance_id": m.group(1).strip(), "fields": {}}
            continue
        if current and "=" in stripped:
            key, value = stripped.split("=", 1)
            current["fields"][key.strip()] = value.strip()
    if current:
        blocks.append(current)

    system = {}
    cpus = []
    dimms = []
    disks = []
    controllers = []
    psus = []
    fans = []
    for block in blocks:
        inst = block["instance_id"]
        fields = block["fields"]
        low = inst.lower()
        if low.startswith("system."):
            system = fields
        elif low.startswith("cpu.socket"):
            cpus.append(fields)
        elif low.startswith("dimm."):
            dimms.append(fields)
        elif low.startswith("disk.bay"):
            disks.append(fields)
        elif low.startswith("raid.") or "perc" in str(fields.get("ProductName") or fields.get("Model") or "").lower():
            controllers.append(fields)
        elif low.startswith("powersupply.") or low.startswith("psu."):
            psus.append(fields)
        elif low.startswith("fan."):
            fans.append(fields)

    cpu_models = sorted(
        {c.get("Model") or c.get("DeviceDescription") for c in cpus if c.get("Model") or c.get("DeviceDescription")}
    )
    cpu_cores = sum(_idrac_int(c.get("NumberOfEnabledCores")) or 0 for c in cpus)
    cpu_threads = sum(_idrac_int(c.get("NumberOfEnabledThreads")) or 0 for c in cpus)
    cpu_socket_count = len(cpus) or (_idrac_int(system.get("PopulatedCPUSockets")) or 0)
    cpu_statuses = [c.get("PrimaryStatus") for c in cpus if c.get("PrimaryStatus")]

    ram_mb = _idrac_int(system.get("SysMemTotalSize")) or 0
    if not ram_mb:
        ram_mb = sum(_idrac_int(d.get("Size")) or _idrac_int(d.get("SizeInMB")) or 0 for d in dimms)
    dimm_populated = _idrac_int(system.get("PopulatedDIMMSlots")) or len(
        [d for d in dimms if (_idrac_int(d.get("Size")) or _idrac_int(d.get("SizeInMB")) or 0) > 0]
    )

    disk_total_bytes = sum(_idrac_int(d.get("SizeInBytes")) or 0 for d in disks)
    disk_bad = [
        d
        for d in disks
        if _idrac_status_bad(d.get("PrimaryStatus"))
        or _idrac_status_bad(d.get("RaidStatus"))
        or _idrac_status_bad(d.get("PredictiveFailureState"))
    ]
    media_counts = {}
    for disk in disks:
        media = disk.get("MediaType") or "unknown"
        media_counts[media] = media_counts.get(media, 0) + 1

    controller = controllers[0] if controllers else {}
    raid_controller = (
        controller.get("ProductName")
        or controller.get("Model")
        or controller.get("DeviceDescription")
        or ""
    )
    raid_cache_mb = _idrac_int(controller.get("CacheSizeInMB")) or _idrac_int(controller.get("CacheSize")) or 0

    health_fields = {
        "system_rollup": system.get("RollupStatus") or system.get("PrimaryStatus") or "",
        "cpu_status": system.get("CPURollupStatus") or ", ".join(cpu_statuses),
        "memory_status": system.get("MemoryRollupStatus") or "",
        "storage_status": system.get("StorageRollupStatus") or ("ERROR" if disk_bad else "OK" if disks else ""),
        "fan_status": system.get("FanRollupStatus") or "",
        "psu_status": system.get("PSRollupStatus") or "",
    }
    bad_health = [k for k, v in health_fields.items() if _idrac_status_bad(v)]

    return {
        "cpu_sockets": cpu_socket_count,
        "cpu_cores": cpu_cores,
        "cpu_threads": cpu_threads,
        "cpu_models": cpu_models,
        "cpu_model": ", ".join(cpu_models[:2]),
        "ram_mb": ram_mb,
        "ram_gb": round(ram_mb / 1024, 1) if ram_mb else 0,
        "dimm_populated": dimm_populated,
        "dimm_slots": _idrac_int(system.get("MaxDIMMSlots")) or 0,
        "disk_count": len(disks),
        "disk_total_bytes": disk_total_bytes,
        "disk_total_tb": round(disk_total_bytes / 1000**4, 1) if disk_total_bytes else 0,
        "disk_bad_count": len(disk_bad),
        "disk_media": media_counts,
        "raid_controller": raid_controller,
        "raid_cache_mb": raid_cache_mb,
        "power_state": system.get("PowerState") or "",
        "system_model": system.get("Model") or system.get("ProductName") or "",
        "service_tag": system.get("ServiceTag") or system.get("ChassisServiceTag") or "",
        "psu_count": len(psus),
        "fan_count": len(fans),
        "bad_health": bad_health,
        "health_ok": not bad_health,
        **health_fields,
    }


# -- Handlers ----------------------------------------------------------------


def handle_idrac(handler):
    """GET /api/infra/idrac -- iDRAC data + write ops via SSH/racadm.

    Read actions: status, sensors, sel, storage, network, license, firmware, power,
        inventory
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
        json_response(
            handler,
            {
                "error": (
                    "target required for iDRAC actions; legacy iDRAC controllers "
                    "have tiny SSH session limits, so dashboard reads are one BMC at a time"
                )
            },
            400,
        )
        return

    # -- Read actions (no role check) --
    read_actions = {
        "status": "racadm getsysinfo -s",
        "sensors": "racadm getsensorinfo",
        "sel": "racadm getsel",
        "storage": "racadm raid get status",
        "network": "racadm getniccfg",
        "license": "racadm license view",
        "firmware": "racadm getversion",
        "power": "racadm serveraction powerstatus",
        "inventory": "racadm hwinventory",
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
    for name, ip in idrac_ips.items():
        command_timeout=IDRAC_READ_COMMAND_TIMEOUT
        if action == "inventory":
            command_timeout = IDRAC_INVENTORY_COMMAND_TIMEOUT
        r = _idrac_status_from_probe_cache(cfg, name, ip) if action == "status" else None
        if r is None:
            r = _run_idrac_read(cfg, ip, cmd, command_timeout=command_timeout)
        item = {
            "name": name,
            "ip": ip,
            "reachable": r.returncode == 0,
            "output": r.stdout[:4000] if r.returncode == 0 else "",
            "error": _idrac_failure_evidence(r) if r.returncode != 0 else "",
        }
        if action == "inventory" and r.returncode == 0:
            item["inventory"] = _parse_idrac_hwinventory(r.stdout)
        results.append(item)

    json_response(handler, {"action": action, "targets": results})


def handle_cost(handler):
    """GET /api/cost -- return fleet cost estimates per host."""
    from freq.jarvis.cost import compute_costs, costs_to_dicts, fleet_summary, load_cost_config

    cfg = load_config()
    cost_cfg = load_cost_config(cfg.conf_dir)
    with _bg_lock:
        health = _bg_cache.get("health")
        _health_ts = _bg_cache_ts.get("health", 0)
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
    age = round(time.time() - _health_ts, 1)
    json_response(
        handler,
        {
            "hosts": costs_to_dicts(costs),
            "summary": summary,
            "cached": True,
            "age_seconds": age,
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
        from freq.modules.cost_analysis import _estimate_vm_monthly_cost, _gather_vm_resources

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
        from freq.modules.cost_analysis import _estimate_aws_cost, _estimate_vm_monthly_cost, _gather_vm_resources

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
    """POST /api/gwipe -- FREQ WIPE station status and operations."""
    if require_post(handler, "GWIPE operation"):
        return
    cfg = load_config()
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
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
            json_response(handler, {"error": "GWIPE station not configured in vault"}, 400)
            return
        import urllib.error
        import urllib.request

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
