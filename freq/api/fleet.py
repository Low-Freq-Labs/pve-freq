"""Fleet domain API handlers -- /api/fleet/*, /api/status, /api/health, etc.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for fleet-wide visibility, health, topology, inventory.
Why:   Decouples fleet ops from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import json
import os
import re
import time
import concurrent.futures

from freq.api.helpers import require_post,  json_response, get_params
from freq.core.config import load_config
from freq.core import resolve as res
from freq.core import log as logger
from freq.core.ssh import run as ssh_single, run_many as ssh_run_many, result_for
from freq.modules.serve import (
    _bg_cache,
    _bg_lock,
    _bg_cache_ts,
    _bg_cache_errors,
    _get_fleet_vms,
    _get_discovered_nodes,
    _get_discovered_node_ips,
    _check_session_role,
    _parse_query,
    _parse_query_flat,
    _parse_pct,
    _activity_feed,
    _activity_lock,
)
from freq.jarvis.agent import _load_agents
import freq


# -- Handlers ----------------------------------------------------------------


def handle_status(handler):
    """GET /api/status -- fleet host status via SSH uptime probe."""
    cfg = load_config()
    hosts = cfg.hosts
    start = time.monotonic()

    results = ssh_run_many(
        hosts=hosts,
        command="uptime -p 2>/dev/null || uptime",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=5,
        max_parallel=10,
        use_sudo=False,
        cfg=cfg,
    )

    duration = round(time.monotonic() - start, 1)
    up = 0
    down = 0
    host_data = []

    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode == 0:
            up += 1
            uptime = r.stdout.strip().replace("up ", "")[:40]
            host_data.append(
                {
                    "label": h.label,
                    "ip": h.ip,
                    "type": h.htype,
                    "status": "up",
                    "uptime": uptime,
                }
            )
        else:
            down += 1
            host_data.append(
                {
                    "label": h.label,
                    "ip": h.ip,
                    "type": h.htype,
                    "status": "down",
                    "uptime": "",
                }
            )

    json_response(
        handler,
        {
            "total": len(hosts),
            "up": up,
            "down": down,
            "duration": duration,
            "hosts": host_data,
        },
    )


def handle_health_api(handler):
    """GET /api/health -- fleet health from background cache, always instant."""
    role, err = _check_session_role(handler, "viewer")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    with _bg_lock:
        cached = _bg_cache.get("health")
    if cached:
        age_seconds = round(time.time() - _bg_cache_ts.get("health", 0), 1)
        response = dict(cached)
        response["cached"] = True
        response["age"] = age_seconds
        response["age_seconds"] = age_seconds
        probe_err = _bg_cache_errors.get("health")
        if probe_err:
            response["probe_status"] = "error"
            response["probe_error"] = probe_err["error"]
            response["probe_failed_at"] = probe_err["failed_at"]
            response["probe_consecutive_failures"] = probe_err["consecutive"]
        else:
            response["probe_status"] = "ok"
        json_response(handler, response)
        return
    # Fallback: no cache yet (first few seconds after cold start)
    cfg = load_config()
    start = time.monotonic()

    HEALTH_CMDS = {
        "linux": (
            'echo "$(hostname)|$(nproc)|'
            "$(free -m | awk '/Mem:/ {printf \"%d/%dMB\", $3, $2}')|"
            "$(df -h / | awk 'NR==2 {print $5}')|"
            "$(cat /proc/loadavg | awk '{print $1}')|"
            '$(docker ps -q 2>/dev/null | wc -l)"'
        ),
        "pfsense": (
            'echo "$(hostname)|$(sysctl -n hw.ncpu)|'
            "$(sysctl -n hw.physmem hw.usermem 2>/dev/null | "
            "awk 'NR==1{t=$1} NR==2{u=$1} END{printf \"%d/%dMB\", (t-u)/1048576, t/1048576}')|"
            "$(df -h / | awk 'NR==2 {print $5}')|"
            "$(sysctl -n vm.loadavg | awk '{print $2}')|0\""
        ),
        "switch": "show processes cpu | include CPU",
    }

    def _probe_host(h):
        htype = h.htype
        cmd = HEALTH_CMDS.get(htype, HEALTH_CMDS["linux"])
        use_sudo = htype not in ("switch", "idrac")
        probe_key = (cfg.ssh_rsa_key_path or cfg.ssh_key_path) if htype in ("idrac", "switch") else cfg.ssh_key_path
        r = ssh_single(
            host=h.ip,
            command=cmd,
            key_path=probe_key,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=15,
            htype=htype,
            use_sudo=use_sudo,
            cfg=cfg,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {
                "label": h.label,
                "ip": h.ip,
                "type": htype,
                "groups": getattr(h, "groups", "") or "",
                "status": "unreachable",
                "cores": "-",
                "ram": "-",
                "disk": "-",
                "load": "-",
                "docker": "0",
            }

        if htype == "switch":
            m = re.search(r"one minute:\s*(\d+)%", r.stdout)
            cpu_pct = m.group(1) if m else "0"
            r2 = ssh_single(
                host=h.ip,
                command="show processes memory | include Processor",
                key_path=probe_key,
                connect_timeout=3,
                command_timeout=10,
                htype="switch",
                use_sudo=False,
                cfg=cfg,
            )
            ram = "-"
            if r2.returncode == 0 and r2.stdout:
                parts = r2.stdout.split()
                try:
                    idx_t = parts.index("Total:") + 1
                    idx_u = parts.index("Used:") + 1
                    total_mb = int(parts[idx_t]) // 1048576
                    used_mb = int(parts[idx_u]) // 1048576
                    ram = f"{used_mb}/{total_mb}MB"
                except (ValueError, IndexError):
                    pass
            load_val = f"{float(cpu_pct) / 100:.2f}" if cpu_pct != "0" else "0.00"
            return {
                "label": h.label,
                "ip": h.ip,
                "type": htype,
                "groups": getattr(h, "groups", "") or "",
                "status": "healthy",
                "cores": "1",
                "ram": ram,
                "disk": "-",
                "load": load_val,
                "docker": "0",
            }

        parts = r.stdout.strip().split("|")
        return {
            "label": h.label,
            "ip": h.ip,
            "type": htype,
            "groups": getattr(h, "groups", "") or "",
            "status": "healthy",
            "cores": parts[1] if len(parts) > 1 else "?",
            "ram": parts[2] if len(parts) > 2 else "?",
            "disk": parts[3] if len(parts) > 3 else "?",
            "load": parts[4] if len(parts) > 4 else "?",
            "docker": parts[5].strip() if len(parts) > 5 else "0",
        }

    host_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.ssh_max_parallel) as pool:
        futures = {pool.submit(_probe_host, h): h for h in cfg.hosts}
        for f in concurrent.futures.as_completed(futures):
            try:
                host_data.append(f.result())
            except Exception as e:
                h = futures[f]
                logger.warn(f"health probe failed for {h.label}: {e}")
                host_data.append(
                    {
                        "label": h.label,
                        "ip": h.ip,
                        "type": h.htype,
                        "groups": getattr(h, "groups", "") or "",
                        "status": "unreachable",
                        "cores": "-",
                        "ram": "-",
                        "disk": "-",
                        "load": "-",
                        "docker": "0",
                    }
                )

    duration = round(time.monotonic() - start, 1)
    result = {"duration": duration, "hosts": host_data}
    json_response(handler, result)


def handle_fleet_overview(handler):
    """GET /api/fleet/overview -- master endpoint, served from background cache."""
    with _bg_lock:
        cached = _bg_cache.get("fleet_overview")
    if cached:
        age_seconds = round(time.time() - _bg_cache_ts.get("fleet_overview", 0), 1)
        response = dict(cached)
        response["cached"] = True
        response["age"] = age_seconds
        response["age_seconds"] = age_seconds
        probe_err = _bg_cache_errors.get("fleet_overview")
        if probe_err:
            response["probe_status"] = "error"
            response["probe_error"] = probe_err["error"]
        else:
            response["probe_status"] = "ok"
        json_response(handler, response)
    else:
        json_response(
            handler,
            {
                "vms": [],
                "vm_nics": {},
                "physical": [],
                "pve_nodes": [],
                "vlans": [],
                "nic_profiles": {},
                "categories": {},
                "summary": {
                    "total_vms": 0,
                    "running": 0,
                    "stopped": 0,
                    "prod_count": 0,
                    "lab_count": 0,
                    "template_count": 0,
                },
                "duration": 0,
                "_loading": True,
            },
        )


def handle_fleet_ntp(handler):
    """GET /api/fleet/ntp -- fleet NTP status."""
    cfg = load_config()
    results_data = []
    results = ssh_run_many(
        hosts=cfg.hosts,
        command="timedatectl show --property=NTPSynchronized --value 2>/dev/null; date '+%H:%M:%S'",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=10,
        max_parallel=10,
        use_sudo=False,
    )
    for h in cfg.hosts:
        r = result_for(results, h)
        if r and r.returncode == 0:
            lines = r.stdout.strip().split("\n")
            synced = lines[0].strip() == "yes" if lines else False
            time_str = lines[1].strip() if len(lines) > 1 else "?"
            results_data.append(
                {
                    "label": h.label,
                    "synced": synced,
                    "time": time_str,
                }
            )
        else:
            results_data.append({"label": h.label, "synced": False, "time": "unreachable"})
    json_response(handler, {"hosts": results_data})


def handle_fleet_updates(handler):
    """GET /api/fleet/updates -- fleet update status."""
    cfg = load_config()
    results_data = []
    results = ssh_run_many(
        hosts=cfg.hosts,
        command="if command -v apt >/dev/null 2>&1; then "
        "  apt list --upgradable 2>/dev/null | grep -c upgradable; echo apt; "
        "else echo 0; echo unknown; fi",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=30,
        max_parallel=10,
        use_sudo=False,
    )
    for h in cfg.hosts:
        r = result_for(results, h)
        if r and r.returncode == 0:
            lines = r.stdout.strip().split("\n")
            count = lines[0].strip() if lines else "0"
            pkg_mgr = lines[1].strip() if len(lines) > 1 else "?"
            try:
                count_int = int(count)
            except ValueError:
                count_int = 0
            results_data.append(
                {
                    "label": h.label,
                    "updates": count_int,
                    "pkg_mgr": pkg_mgr,
                }
            )
        else:
            results_data.append({"label": h.label, "updates": -1, "pkg_mgr": "?"})
    json_response(handler, {"hosts": results_data})


def handle_agents(handler):
    """GET /api/agents -- agent registry."""
    cfg = load_config()
    agents = _load_agents(cfg)
    agent_list = [
        {
            "name": a.get("name"),
            "template": a.get("template"),
            "vmid": a.get("vmid"),
            "status": a.get("status"),
            "created": a.get("created"),
        }
        for a in agents.values()
    ]
    json_response(handler, {"agents": agent_list, "count": len(agent_list)})


def handle_info(handler):
    """GET /api/info -- FREQ installation info."""
    cfg = load_config()
    from freq.core.personality import load_pack

    pack = load_pack(cfg.conf_dir, cfg.build)
    json_response(
        handler,
        {
            "version": freq.__version__,
            "brand": cfg.brand,
            "build": cfg.build,
            "hosts": len(cfg.hosts),
            "pve_nodes": len(_get_discovered_nodes()),
            "cluster": cfg.cluster_name,
            "install_dir": cfg.install_dir,
            "subtitle": getattr(pack, "subtitle", cfg.brand) if pack else cfg.brand,
            "dashboard_header": getattr(pack, "dashboard_header", "PVE FREQ Dashboard")
            if pack
            else "PVE FREQ Dashboard",
        },
    )


def handle_exec(handler):
    """GET /api/exec -- execute a command across fleet hosts via API."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = _parse_query(handler)
    target = params.get("target", ["all"])[0]
    cmd = params.get("cmd", [""])[0]

    if not cmd:
        json_response(handler, {"error": "No command specified"}, 400)
        return

    cfg = load_config()

    if target == "all":
        hosts = cfg.hosts
    else:
        group = res.by_group(cfg.hosts, target)
        if group:
            hosts = group
        else:
            ttype = res.by_type(cfg.hosts, target)
            if ttype:
                hosts = ttype
            else:
                host = res.by_target(cfg.hosts, target)
                hosts = [host] if host else []

    if not hosts:
        json_response(handler, {"error": f"No hosts matched: {target}", "results": []}, 400)
        return

    results = ssh_run_many(
        hosts=hosts,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=15,
        max_parallel=10,
        use_sudo=False,
    )

    result_list = []
    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode == 0:
            result_list.append({"host": h.label, "ok": True, "output": r.stdout, "error": ""})
        else:
            result_list.append(
                {"host": h.label, "ok": False, "output": "", "error": r.stderr[:100] if r else "no response"}
            )

    json_response(handler, {"target": target, "command": cmd, "results": result_list})


def handle_deploy_agent(handler):
    """POST /api/deploy-agent -- deploy FREQ metrics agent to fleet hosts (admin only)."""
    if require_post(handler, "Agent deploy"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    params = get_params(handler)
    target = params.get("target", ["all"])[0]
    cfg = load_config()

    # Resolve hosts
    if target.lower() == "all":
        hosts = cfg.hosts
    else:
        h = res.by_target(cfg.hosts, target)
        if not h:
            json_response(handler, {"error": f"Host not found: {target}"}, 404)
            return
        hosts = [h]

    # Read agent source
    agent_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent_collector.py")
    try:
        with open(agent_src) as f:
            agent_code = f.read()
    except FileNotFoundError:
        json_response(handler, {"error": f"Agent source not found: {agent_src}"}, 500)
        return

    from freq.modules.init_cmd import AGENT_REMOTE_PATH, AGENT_REMOTE_DIR

    agent_port = cfg.agent_port
    remote_path = AGENT_REMOTE_PATH
    service_name = "freq-agent"

    results = []
    for h in hosts:
        host_result = {"host": h.label, "ip": h.ip, "steps": []}

        # Step 1: Create directory
        r = ssh_single(
            host=h.ip,
            command=f"mkdir -p {AGENT_REMOTE_DIR}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype=h.htype,
            use_sudo=True,
        )
        if r.returncode != 0:
            host_result["status"] = "failed"
            host_result["error"] = "Cannot create directory"
            host_result["steps"].append({"step": "mkdir", "ok": False})
            results.append(host_result)
            continue
        host_result["steps"].append({"step": "mkdir", "ok": True})

        # Step 2: Upload agent
        upload_cmd = f"cat > {remote_path} << 'FREQAGENTEOF'\n{agent_code}\nFREQAGENTEOF"
        r = ssh_single(
            host=h.ip,
            command=upload_cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype=h.htype,
            use_sudo=True,
        )
        if r.returncode != 0:
            host_result["status"] = "failed"
            host_result["error"] = "Cannot upload agent"
            host_result["steps"].append({"step": "upload", "ok": False})
            results.append(host_result)
            continue
        host_result["steps"].append({"step": "upload", "ok": True})

        # Step 3: chmod + systemd unit
        r = ssh_single(
            host=h.ip,
            command=f"chmod +x {remote_path}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=5,
            htype=h.htype,
            use_sudo=True,
        )
        host_result["steps"].append({"step": "chmod", "ok": r.returncode == 0, "error": r.stderr if r.returncode != 0 else ""})
        if r.returncode != 0:
            host_result["status"] = "failed"
            host_result["error"] = "chmod failed"
            results.append(host_result)
            continue

        unit = (
            f"[Unit]\nDescription=FREQ Metrics Agent\nAfter=network.target\n\n"
            f"[Service]\nExecStart=/usr/bin/python3 {remote_path} --port {agent_port}\n"
            f"Restart=always\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\n"
        )
        svc_cmd = f"cat > /etc/systemd/system/{service_name}.service << 'FREQSVCEOF'\n{unit}\nFREQSVCEOF"
        r = ssh_single(
            host=h.ip,
            command=svc_cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype=h.htype,
            use_sudo=True,
        )
        host_result["steps"].append({"step": "systemd_unit", "ok": r.returncode == 0, "error": r.stderr if r.returncode != 0 else ""})
        if r.returncode != 0:
            host_result["status"] = "failed"
            host_result["error"] = "systemd unit creation failed"
            results.append(host_result)
            continue

        # Step 4: Enable and start
        r = ssh_single(
            host=h.ip,
            command=f"systemctl daemon-reload && systemctl enable {service_name} && systemctl restart {service_name}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=30,
            htype=h.htype,
            use_sudo=True,
        )
        host_result["steps"].append({"step": "start", "ok": r.returncode == 0, "error": r.stderr if r.returncode != 0 else ""})
        if r.returncode != 0:
            host_result["status"] = "failed"
            host_result["error"] = "service start failed"
            results.append(host_result)
            continue

        # Step 5: Verify
        time.sleep(1)
        r = ssh_single(
            host=h.ip,
            command=f"curl -s http://localhost:{agent_port}/health 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=5,
            htype=h.htype,
            use_sudo=False,
        )
        healthy = r.returncode == 0 and "ok" in r.stdout
        host_result["steps"].append({"step": "verify", "ok": healthy})
        host_result["status"] = "deployed" if healthy else "deployed_unverified"
        host_result["agent_port"] = agent_port
        results.append(host_result)

    deployed = sum(1 for r in results if r.get("status") == "deployed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    json_response(
        handler,
        {
            "results": results,
            "deployed": deployed,
            "failed": failed,
            "total": len(results),
            "agent_port": agent_port,
        },
    )


def handle_infra_overview(handler):
    """GET /api/infra/overview -- full infrastructure overview."""
    cfg = load_config()

    cmd = (
        'echo "$(hostname)|$(cat /etc/os-release 2>/dev/null | grep -oP \'(?<=PRETTY_NAME=\\").*(?=\\")\' || echo unknown)|'
        "$(nproc)|$(free -m | awk '/Mem:/ {printf \\\"%d/%dMB\\\", $3, $2}')|"
        "$(df -h / | awk 'NR==2 {print $5}')|"
        "$(docker ps -q 2>/dev/null | wc -l)|"
        '$(systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l)"'
    )

    results = ssh_run_many(
        hosts=cfg.hosts,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=10,
        max_parallel=10,
        use_sudo=False,
    )

    layers = []
    for h in cfg.hosts:
        r = result_for(results, h)
        if r and r.returncode == 0 and r.stdout:
            parts = r.stdout.split("|")
            layers.append(
                {
                    "label": h.label,
                    "ip": h.ip,
                    "type": h.htype,
                    "status": "up",
                    "hostname": parts[0] if len(parts) > 0 else "?",
                    "os": parts[1] if len(parts) > 1 else "?",
                    "cores": parts[2] if len(parts) > 2 else "?",
                    "ram": parts[3] if len(parts) > 3 else "?",
                    "disk_pct": parts[4] if len(parts) > 4 else "?",
                    "containers": int(parts[5]) if len(parts) > 5 and parts[5].strip().isdigit() else 0,
                    "services": int(parts[6]) if len(parts) > 6 and parts[6].strip().isdigit() else 0,
                }
            )
        else:
            layers.append(
                {
                    "label": h.label,
                    "ip": h.ip,
                    "type": h.htype,
                    "status": "down",
                }
            )

    pve_info = {"nodes": [], "vms": []}
    for node_ip in _get_discovered_node_ips():
        r = ssh_single(
            host=node_ip,
            command="pvesh get /cluster/resources --type vm --output-format json 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="pve",
            use_sudo=True,
        )
        if r.returncode == 0 and r.stdout:
            try:
                vms = json.loads(r.stdout)
                for v in vms:
                    pve_info["vms"].append(
                        {
                            "vmid": v.get("vmid"),
                            "name": v.get("name", ""),
                            "node": v.get("node", ""),
                            "status": v.get("status", ""),
                            "cpu": v.get("maxcpu", 0),
                            "ram_mb": v.get("maxmem", 0) // (1024 * 1024) if v.get("maxmem") else 0,
                        }
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warn(f"infra overview VM parse failed: {e}")
            break

    infra = {}
    if cfg.pfsense_ip:
        infra["pfsense"] = {"ip": cfg.pfsense_ip, "status": "unknown"}
    if cfg.truenas_ip:
        infra["truenas"] = {"ip": cfg.truenas_ip, "status": "unknown"}

    json_response(
        handler,
        {
            "hosts": layers,
            "pve": pve_info,
            "infra": infra,
            "cluster": cfg.cluster_name,
        },
    )


def handle_infra_quick(handler):
    """GET /api/infra/quick -- infra device summary from background cache."""
    with _bg_lock:
        cached = _bg_cache.get("infra_quick")
    if cached:
        age_seconds = round(time.time() - _bg_cache_ts.get("infra_quick", 0), 1)
        response = dict(cached)
        response["cached"] = True
        response["age"] = age_seconds
        response["age_seconds"] = age_seconds
        probe_err = _bg_cache_errors.get("infra_quick")
        if probe_err:
            response["probe_status"] = "error"
            response["probe_error"] = probe_err["error"]
        else:
            response["probe_status"] = "ok"
        json_response(handler, response)
        return
    json_response(handler, {"devices": [], "duration": 0, "warming": True})


def handle_diagnose(handler):
    """GET /api/diagnose -- run deep diagnostic for a specific host."""
    cfg = load_config()
    query = _parse_query(handler)
    target = query.get("target", [""])[0]
    if not target:
        json_response(handler, {"error": "target parameter required"}, 400)
        return
    try:
        host = res.by_target(cfg.hosts, target)
        if not host:
            json_response(handler, {"error": f"Unknown host: {target}"}, 404)
            return
        checks = {}
        cmds = {
            "uptime": "uptime",
            "disk": "df -h --output=target,pcent,avail | head -20",
            "memory": "free -h",
            "load": "cat /proc/loadavg",
            "services": "systemctl list-units --state=failed --no-pager --no-legend 2>/dev/null || echo 'N/A'",
            "docker": "docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo 'No docker'",
            "network": "ip -br addr 2>/dev/null || ifconfig 2>/dev/null || echo 'N/A'",
            "journal_errors": "journalctl -p err --since '1 hour ago' --no-pager -q 2>/dev/null | tail -20 || echo 'N/A'",
        }
        for label, cmd in cmds.items():
            r = ssh_single(
                host=host.ip,
                command=cmd,
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=15,
                htype=host.htype,
                use_sudo=False,
            )
            checks[label] = r.stdout if r.returncode == 0 else f"ERROR: {r.stderr or r.stdout}"
        json_response(handler, {"host": target, "ip": host.ip, "checks": checks})
    except Exception as e:
        logger.error(f"api_fleet_error: diagnose failed: {e}", endpoint="diagnose")
        json_response(handler, {"error": f"Diagnose failed: {e}"}, 500)


def handle_log(handler):
    """GET /api/log -- view remote host logs via SSH."""
    cfg = load_config()
    query = _parse_query(handler)
    target = query.get("target", [""])[0]
    lines = int(query.get("lines", ["50"])[0])
    unit = query.get("unit", [""])[0]
    if not target:
        json_response(handler, {"error": "target parameter required"}, 400)
        return
    try:
        host = res.by_target(cfg.hosts, target)
        if not host:
            json_response(handler, {"error": f"Unknown host: {target}"}, 404)
            return
        cmd = f"journalctl --no-pager -n {min(lines, 500)}"
        if unit:
            cmd += f" -u {unit}"
        r = ssh_single(
            host=host.ip,
            command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=15,
            htype=host.htype,
            use_sudo=True,
        )
        json_response(
            handler,
            {
                "host": target,
                "ip": host.ip,
                "lines": r.stdout.split("\n") if r.returncode == 0 else [],
                "error": "" if r.returncode == 0 else (r.stderr or r.stdout),
            },
        )
    except Exception as e:
        logger.error(f"api_fleet_error: log fetch failed: {e}", endpoint="log")
        json_response(handler, {"error": f"Log fetch failed: {e}"}, 500)


def handle_fleet_health_score(handler):
    """GET /api/fleet/health-score -- composite fleet health score 0-100."""
    with _bg_lock:
        health = _bg_cache.get("health")
        fleet = _bg_cache.get("fleet_overview")

    if not health and not fleet:
        json_response(handler, {
            "score": 0, "grade": "?", "factors": [],
            "max_score": 100, "error": "No health data available yet",
            "cached": False, "stale": True,
        }, 503)
        return

    score = 100
    factors = []

    if health and isinstance(health, dict):
        hosts = health.get("hosts", [])
        total = len(hosts)
        healthy = sum(1 for h in hosts if h.get("status") == "healthy")
        unhealthy = total - healthy

        if total > 0:
            host_pct = round(healthy / total * 100)
            if host_pct < 100:
                penalty = min(40, (100 - host_pct) * 2)
                score -= penalty
                factors.append(
                    {"factor": "hosts_down", "penalty": penalty, "detail": f"{unhealthy}/{total} hosts unhealthy"}
                )

            high_ram = sum(1 for h in hosts if _parse_pct(h.get("ram", "")) > 80)
            high_disk = sum(1 for h in hosts if _parse_pct(h.get("disk", "")) > 80)
            if high_ram > 0:
                penalty = min(15, high_ram * 5)
                score -= penalty
                factors.append({"factor": "ram_pressure", "penalty": penalty, "detail": f"{high_ram} host(s) >80% RAM"})
            if high_disk > 0:
                penalty = min(15, high_disk * 5)
                score -= penalty
                factors.append(
                    {"factor": "disk_pressure", "penalty": penalty, "detail": f"{high_disk} host(s) >80% disk"}
                )

    if fleet and isinstance(fleet, dict):
        vms = fleet.get("vms", [])
        stopped = sum(1 for v in vms if v.get("status") == "stopped")
        total_vms = len(vms)
        if total_vms > 0 and stopped > total_vms * 0.3:
            penalty = min(10, stopped)
            score -= penalty
            factors.append(
                {"factor": "vms_stopped", "penalty": penalty, "detail": f"{stopped}/{total_vms} VMs stopped"}
            )

    score = max(0, min(100, score))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

    health_age = round(time.time() - _bg_cache_ts.get("health", 0), 1) if health else None
    fleet_age = round(time.time() - _bg_cache_ts.get("fleet_overview", 0), 1) if fleet else None
    stale = (health_age is not None and health_age > 120) or (fleet_age is not None and fleet_age > 120)

    json_response(
        handler,
        {
            "score": score,
            "grade": grade,
            "factors": factors,
            "max_score": 100,
            "cached": True,
            "health_age_seconds": health_age,
            "fleet_age_seconds": fleet_age,
            "stale": stale,
        },
    )


def handle_topology_enhanced(handler):
    """GET /api/fleet/topology-enhanced -- topology with VLAN grouping."""
    cfg = load_config()
    with _bg_lock:
        fleet = _bg_cache.get("fleet_overview")
        health = _bg_cache.get("health")

    vlan_groups = {}
    for vlan in cfg.vlans:
        vlan_groups[vlan.name] = {
            "id": vlan.id,
            "name": vlan.name,
            "subnet": vlan.subnet,
            "gateway": vlan.gateway,
            "hosts": [],
        }

    health_hosts = health.get("hosts", []) if health and isinstance(health, dict) else []
    for h in health_hosts:
        ip = h.get("ip", "")
        matched = False
        for vlan in cfg.vlans:
            if vlan.prefix and ip.startswith(vlan.prefix):
                vlan_groups[vlan.name]["hosts"].append(
                    {
                        "label": h.get("label", ""),
                        "ip": ip,
                        "type": h.get("type", ""),
                        "status": h.get("status", ""),
                    }
                )
                matched = True
                break
        if not matched:
            if "untagged" not in vlan_groups:
                vlan_groups["untagged"] = {
                    "id": 0,
                    "name": "Untagged",
                    "subnet": "",
                    "gateway": "",
                    "hosts": [],
                }
            vlan_groups["untagged"]["hosts"].append(
                {
                    "label": h.get("label", ""),
                    "ip": ip,
                    "type": h.get("type", ""),
                    "status": h.get("status", ""),
                }
            )

    nodes = {}
    if fleet and isinstance(fleet, dict):
        for vm in fleet.get("vms", []):
            node = vm.get("node", "unknown")
            if node not in nodes:
                nodes[node] = {"name": node, "vms": 0, "running": 0}
            nodes[node]["vms"] += 1
            if vm.get("status") == "running":
                nodes[node]["running"] += 1

    health_age = round(time.time() - _bg_cache_ts.get("health", 0), 1) if health else None
    fleet_age = round(time.time() - _bg_cache_ts.get("fleet_overview", 0), 1) if fleet else None
    json_response(
        handler,
        {
            "vlans": list(vlan_groups.values()),
            "nodes": list(nodes.values()),
            "total_hosts": len(health_hosts),
            "total_vlans": len(cfg.vlans),
            "cached": True,
            "health_age_seconds": health_age,
            "fleet_age_seconds": fleet_age,
            "stale": (health_age is not None and health_age > 120) or (fleet_age is not None and fleet_age > 120),
        },
    )


def handle_fleet_heatmap(handler):
    """GET /api/fleet/heatmap -- resource usage per host for heatmap viz."""
    with _bg_lock:
        health = _bg_cache.get("health")

    heatmap = []
    if health and isinstance(health, dict):
        for h in health.get("hosts", []):
            if h.get("status") != "healthy":
                continue
            ram_pct = _parse_pct(h.get("ram", ""))
            disk_pct = _parse_pct(h.get("disk", ""))
            try:
                load = float(h.get("load", "0"))
            except (ValueError, TypeError):
                load = 0
            heatmap.append(
                {
                    "label": h.get("label", ""),
                    "type": h.get("type", ""),
                    "ram_pct": round(ram_pct, 1),
                    "disk_pct": round(disk_pct, 1),
                    "load": round(load, 2),
                    "containers": int(h.get("docker", "0") or 0),
                }
            )

    health_age = round(time.time() - _bg_cache_ts.get("health", 0), 1) if health else None
    json_response(handler, {
        "hosts": heatmap,
        "count": len(heatmap),
        "cached": True,
        "age_seconds": health_age,
        "stale": health_age is not None and health_age > 120,
    })


def handle_topology(handler):
    """GET /api/topology -- network topology data for visualization."""
    with _bg_lock:
        health = _bg_cache.get("health")
        fo_cached = _bg_cache.get("infra_quick")

    health_map = {}
    if health and "hosts" in health:
        for h in health["hosts"]:
            health_map[h.get("label", "")] = h

    cfg = load_config()
    fb = cfg.fleet_boundaries
    nodes = []
    links = []

    for pn in _get_discovered_nodes():
        pn_name = pn.get("name", "") if isinstance(pn, dict) else pn.name
        pn_ip = pn.get("ip", "") if isinstance(pn, dict) else pn.ip
        status = "healthy"
        h = health_map.get(pn_name, {})
        if h.get("status") == "unreachable":
            status = "unreachable"
        nodes.append(
            {
                "id": f"pve:{pn_name}",
                "label": pn_name,
                "type": "pve",
                "ip": pn_ip,
                "status": status,
                "ram": h.get("ram", ""),
                "disk": h.get("disk", ""),
                "load": h.get("load", ""),
            }
        )

    vm_list = _get_fleet_vms(cfg)
    for vm in vm_list:
        node_id = f"pve:{vm['node']}"
        vm_id = f"vm:{vm['vmid']}"
        status = "running" if vm.get("status") == "running" else "stopped"
        h = health_map.get(vm.get("name", ""), {})
        if h.get("status") == "unreachable" and status == "running":
            status = "unreachable"
        nodes.append(
            {
                "id": vm_id,
                "label": vm.get("name", str(vm["vmid"])),
                "type": "vm",
                "vmid": vm["vmid"],
                "status": status,
                "category": vm.get("category", ""),
                "node": vm["node"],
                "ram": h.get("ram", ""),
                "disk": h.get("disk", ""),
                "docker": h.get("docker", "0"),
            }
        )
        links.append({"source": node_id, "target": vm_id})

    for dev in fb.physical.values():
        nodes.append(
            {
                "id": f"dev:{dev.key}",
                "label": dev.label,
                "type": dev.device_type,
                "ip": dev.ip,
                "status": "healthy",
            }
        )

    json_response(
        handler,
        {
            "nodes": nodes,
            "links": links,
            "pve_count": len(_get_discovered_nodes()),
            "vm_count": len(vm_list),
        },
    )


def handle_activity(handler):
    """GET /api/activity -- recent system events."""
    params = _parse_query_flat(handler.path)
    try:
        limit = min(int(params.get("limit", "50")), 200)
    except (ValueError, TypeError):
        limit = 50
    with _activity_lock:
        events = list(_activity_feed)[:limit]
    json_response(handler, {"events": events, "count": len(events)})


def handle_docker_fleet(handler):
    """GET /api/docker-fleet -- fleet-wide container inventory."""
    cfg = load_config()
    from freq.core.resolve import by_type
    from freq.core.ssh import run_many as ssh_run_many_fn, result_for

    docker_hosts = by_type(cfg.hosts, "docker")
    if not docker_hosts:
        json_response(handler, {"hosts": [], "total_containers": 0})
        return

    results = ssh_run_many_fn(
        hosts=docker_hosts,
        command="docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=30,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    hosts_data = []
    total = 0
    for host in docker_hosts:
        r = result_for(results, host)
        containers = []
        if r and r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n"):
                parts = line.split("|")
                containers.append(
                    {
                        "name": parts[0] if len(parts) > 0 else "?",
                        "image": parts[1] if len(parts) > 1 else "",
                        "status": parts[2] if len(parts) > 2 else "",
                    }
                )
            total += len(containers)
        hosts_data.append(
            {
                "label": host.label,
                "ip": host.ip,
                "containers": containers,
                "count": len(containers),
                "reachable": r is not None and r.returncode == 0 if r else False,
            }
        )

    json_response(
        handler,
        {
            "hosts": hosts_data,
            "total_containers": total,
            "total_hosts": len(docker_hosts),
        },
    )


def handle_inventory(handler):
    """GET /api/inventory -- full fleet inventory."""
    from freq.modules.inventory import _gather_hosts, _gather_vms, _gather_containers

    cfg = load_config()
    hosts = _gather_hosts(cfg)
    vms = _gather_vms(cfg)
    containers = _gather_containers(cfg)
    json_response(
        handler,
        {
            "hosts": hosts,
            "vms": vms,
            "containers": containers,
            "meta": {"host_count": len(hosts), "vm_count": len(vms), "container_count": len(containers)},
        },
    )


def handle_inventory_hosts(handler):
    """GET /api/inventory/hosts -- host inventory only."""
    from freq.modules.inventory import _gather_hosts

    cfg = load_config()
    hosts = _gather_hosts(cfg)
    json_response(handler, {"hosts": hosts, "count": len(hosts)})


def handle_inventory_vms(handler):
    """GET /api/inventory/vms -- VM inventory only."""
    from freq.modules.inventory import _gather_vms

    cfg = load_config()
    vms = _gather_vms(cfg)
    json_response(handler, {"vms": vms, "count": len(vms)})


def handle_inventory_containers(handler):
    """GET /api/inventory/containers -- container inventory only."""
    from freq.modules.inventory import _gather_containers

    cfg = load_config()
    containers = _gather_containers(cfg)
    json_response(handler, {"containers": containers, "count": len(containers)})


def handle_compare(handler):
    """GET /api/compare -- compare two hosts."""
    from freq.modules.compare import _gather_host_info
    from freq.core.resolve import by_target as resolve_host

    cfg = load_config()
    params = _parse_query(handler)
    a = params.get("a", [""])[0].strip()
    b = params.get("b", [""])[0].strip()
    if not a or not b:
        json_response(handler, {"error": "Parameters 'a' and 'b' required"}, 400)
        return
    host_a = resolve_host(cfg.hosts, a)
    host_b = resolve_host(cfg.hosts, b)
    if not host_a or not host_b:
        json_response(handler, {"error": "Host not found"}, 404)
        return
    info_a = _gather_host_info(cfg, host_a)
    info_b = _gather_host_info(cfg, host_b)
    json_response(handler, {"host_a": info_a, "host_b": info_b})


def handle_report(handler):
    """GET /api/report -- generate fleet report."""
    from freq.modules.report import _generate_report

    cfg = load_config()
    report = _generate_report(cfg)
    json_response(handler, report)


def handle_discover(handler):
    """GET /api/discover -- discover hosts on network."""
    cfg = load_config()
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    query = _parse_query(handler)
    subnet = query.get("subnet", [""])[0]
    try:
        import io, contextlib
        from freq.modules.discover import cmd_discover

        class Args:
            pass

        args = Args()
        args.subnet = subnet or None
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_discover(cfg, None, args)
        json_response(handler, {"ok": result == 0, "output": buf.getvalue()})
    except Exception as e:
        logger.error(f"api_fleet_error: discovery failed: {e}", endpoint="discover")
        json_response(handler, {"error": f"Discovery failed: {e}"}, 500)


def handle_watchdog_health(handler):
    """GET /api/watchdog/health -- proxy to WATCHDOG daemon."""
    import urllib.request
    import urllib.error
    from urllib.parse import urlparse as _urlparse

    cfg = load_config()
    wd_port = cfg.watchdog_port
    parsed = _urlparse(handler.path)
    target_url = f"http://127.0.0.1:{wd_port}{parsed.path}"
    if parsed.query:
        target_url += f"?{parsed.query}"
    try:
        req = urllib.request.Request(target_url, method=handler.command)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            json_response(handler, data, resp.status)
    except urllib.error.URLError:
        json_response(
            handler, {"error": f"WATCHDOG daemon not reachable at localhost:{wd_port}", "watchdog_down": True}
        )
    except Exception as e:
        logger.error(f"api_fleet_error: watchdog proxy error: {e}", endpoint="watchdog/health")
        json_response(handler, {"error": f"Proxy error: {e}"}, 502)


def handle_federation_status(handler):
    """GET /api/federation/status -- return federation status and registered sites."""
    from freq.jarvis.federation import load_sites, sites_to_dicts, federation_summary

    cfg = load_config()
    sites = load_sites(cfg.data_dir)
    json_response(
        handler,
        {
            "sites": sites_to_dicts(sites),
            "summary": federation_summary(sites),
        },
    )


def handle_federation_register(handler):
    """POST /api/federation/register -- register a new remote FREQ site."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.federation import register_site

    cfg = load_config()
    params = _parse_query_flat(handler.path)
    name = params.get("name", "").strip()
    url = params.get("url", "").strip()
    secret = params.get("secret", "")
    if not name or not url:
        json_response(handler, {"error": "Missing name or url parameter"}, 400)
        return
    ok, msg = register_site(cfg.data_dir, name, url, secret)
    json_response(handler, {"ok": ok, "message": msg})


def handle_federation_unregister(handler):
    """POST /api/federation/unregister -- remove a registered remote site."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.federation import unregister_site

    cfg = load_config()
    params = _parse_query_flat(handler.path)
    name = params.get("name", "").strip()
    if not name:
        json_response(handler, {"error": "Missing name parameter"}, 400)
        return
    ok, msg = unregister_site(cfg.data_dir, name)
    json_response(handler, {"ok": ok, "message": msg})


def handle_federation_poll(handler):
    """POST /api/federation/poll -- trigger a poll of all remote sites."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.federation import poll_all_sites, sites_to_dicts, federation_summary

    cfg = load_config()
    sites = poll_all_sites(cfg.data_dir)
    json_response(
        handler,
        {
            "ok": True,
            "sites": sites_to_dicts(sites),
            "summary": federation_summary(sites),
        },
    )


def handle_federation_toggle(handler):
    """POST /api/federation/toggle -- enable or disable a registered site."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.federation import load_sites, save_sites

    cfg = load_config()
    params = _parse_query_flat(handler.path)
    name = params.get("name", "").strip()
    if not name:
        json_response(handler, {"error": "Missing name parameter"}, 400)
        return
    sites = load_sites(cfg.data_dir)
    found = False
    enabled = False
    for s in sites:
        if s.name == name:
            s.enabled = not s.enabled
            enabled = s.enabled
            found = True
            break
    if not found:
        json_response(handler, {"error": f"Site '{name}' not found"}, 404)
        return
    save_sites(cfg.data_dir, sites)
    json_response(handler, {"ok": True, "enabled": enabled})


def handle_host_detail(handler):
    """GET /api/host/detail -- deep detail for a single host."""
    cfg = load_config()
    query = _parse_query(handler)
    label = query.get("host", [""])[0]

    host = res.by_target(cfg.hosts, label)
    if not host:
        json_response(handler, {"error": f"Host not found: {label}"}, 404)
        return

    def _cmd(command, timeout=10):
        r = ssh_single(
            host=host.ip,
            command=command,
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=timeout,
            htype=host.htype,
            use_sudo=False,
        )
        return r.stdout.strip() if r.returncode == 0 else ""

    detail = {
        "label": host.label,
        "ip": host.ip,
        "type": host.htype,
        "groups": host.groups,
        "hostname": _cmd("hostname -f 2>/dev/null || hostname"),
        "os": _cmd("cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'"),
        "kernel": _cmd("uname -r"),
        "uptime": _cmd("uptime -p 2>/dev/null || uptime"),
        "cpu_model": _cmd("grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs"),
        "cores": _cmd("nproc"),
        "ram": _cmd("free -m | awk '/Mem:/ {printf \"%d/%dMB (%d%%)\", $3, $2, $3/$2*100}'"),
        "load": _cmd("cat /proc/loadavg | awk '{print $1, $2, $3}'"),
        "disk": _cmd('df -h / | awk \'NR==2 {print $3"/"$2" ("$5" used)"}\''),
        "ips": _cmd("ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $NF\": \"$2}'"),
        "gateway": _cmd("ip route show default 2>/dev/null | awk '{print $3}' | head -1"),
        "dns": _cmd("grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | tr '\\n' ' '"),
        "listening_ports": _cmd(
            "ss -tlnp 2>/dev/null | grep LISTEN | awk '{print $4}' | sed 's/.*://' | sort -un | tr '\\n' ' '"
        ),
        "docker_count": _cmd("docker ps -q 2>/dev/null | wc -l"),
        "docker_containers": [],
        "failed_services": _cmd("systemctl --failed --no-legend 2>/dev/null | head -5 || echo none"),
        "running_services": _cmd("systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l"),
        "ssh_root_login": _cmd("grep -i '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'"),
        "ssh_password_auth": _cmd(
            "grep -i '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'"
        ),
        "last_login": _cmd("last -1 --time-format iso 2>/dev/null | head -1"),
        "ntp_synced": _cmd("timedatectl show --property=NTPSynchronized --value 2>/dev/null"),
        "ntp_service": _cmd("systemctl is-active systemd-timesyncd 2>/dev/null"),
        "updates_available": _cmd(
            "if command -v apt >/dev/null 2>&1; then "
            "  apt list --upgradable 2>/dev/null | grep -c upgradable; "
            "elif command -v dnf >/dev/null 2>&1; then "
            "  dnf check-update 2>/dev/null | grep -c '^[a-zA-Z]'; "
            "else echo 0; fi"
        ),
        "pkg_manager": _cmd(
            "if command -v apt >/dev/null 2>&1; then echo APT; "
            "elif command -v dnf >/dev/null 2>&1; then echo DNF; "
            "elif command -v zypper >/dev/null 2>&1; then echo ZYPPER; "
            "else echo UNKNOWN; fi"
        ),
    }

    dc = _cmd("docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null")
    if dc:
        for line in dc.split("\n"):
            parts = line.split("|")
            if len(parts) >= 3:
                detail["docker_containers"].append({"name": parts[0], "status": parts[1], "image": parts[2]})

    json_response(handler, detail)


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register fleet API routes into the master route table."""
    routes["/api/status"] = handle_status
    routes["/api/health"] = handle_health_api
    routes["/api/fleet/overview"] = handle_fleet_overview
    routes["/api/fleet/ntp"] = handle_fleet_ntp
    routes["/api/fleet/updates"] = handle_fleet_updates
    routes["/api/agents"] = handle_agents
    routes["/api/info"] = handle_info
    routes["/api/exec"] = handle_exec
    routes["/api/deploy-agent"] = handle_deploy_agent
    routes["/api/infra/overview"] = handle_infra_overview
    routes["/api/infra/quick"] = handle_infra_quick
    routes["/api/diagnose"] = handle_diagnose
    routes["/api/log"] = handle_log
    routes["/api/fleet/health-score"] = handle_fleet_health_score
    routes["/api/fleet/topology-enhanced"] = handle_topology_enhanced
    routes["/api/fleet/heatmap"] = handle_fleet_heatmap
    routes["/api/topology"] = handle_topology
    routes["/api/activity"] = handle_activity
    routes["/api/docker-fleet"] = handle_docker_fleet
    routes["/api/inventory"] = handle_inventory
    routes["/api/inventory/hosts"] = handle_inventory_hosts
    routes["/api/inventory/vms"] = handle_inventory_vms
    routes["/api/inventory/containers"] = handle_inventory_containers
    routes["/api/compare"] = handle_compare
    routes["/api/report"] = handle_report
    routes["/api/discover"] = handle_discover
    routes["/api/watchdog/health"] = handle_watchdog_health
    routes["/api/federation/status"] = handle_federation_status
    routes["/api/federation/register"] = handle_federation_register
    routes["/api/federation/unregister"] = handle_federation_unregister
    routes["/api/federation/poll"] = handle_federation_poll
    routes["/api/federation/toggle"] = handle_federation_toggle
    routes["/api/host/detail"] = handle_host_detail
