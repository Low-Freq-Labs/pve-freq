"""FREQ Web Dashboard — lightweight fleet status in a browser.

freq serve — starts a local HTTP server with a fleet dashboard.
Pure Python stdlib (http.server), no Flask/Django/FastAPI needed.
Serves a single-page dashboard with live fleet data via JSON API.

Usage:
  freq serve                  # start on port 8888
  freq serve --port 9090      # custom port
"""
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from freq.core import fmt
from freq.core import log as logger
from freq.core import resolve as res
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single, run_many as ssh_run_many
from freq.core.validate import (
    ip as valid_ip, label as valid_label,
    is_protected_vmid, vlan_id as valid_vlan,
)
from freq.modules.pve import _find_reachable_node, _pve_cmd
from freq.modules.users import _load_users, _save_users, _role_level, ROLE_HIERARCHY
from freq.modules.vault import vault_get, vault_set, vault_init, vault_list, vault_delete
from freq.jarvis.agent import TEMPLATES, _load_agents, _save_agents
from freq.jarvis.notify import notify as jarvis_notify
from freq.jarvis.risk import _load_risk_map, _load_kill_chain
import freq


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server — won't block on slow API calls."""
    daemon_threads = True


# ── CONSTANTS ────────────────────────────────────────────────────────────

BG_CACHE_REFRESH_INTERVAL = 60   # seconds between background cache refreshes
DASHBOARD_AUTO_REFRESH_MS = 30000  # milliseconds between frontend auto-refreshes
SESSION_TIMEOUT_HOURS = 8
_SERVER_START_TIME = time.monotonic()
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_HOURS * 3600
DEFAULT_LOG_LINES = 50

# ── BACKGROUND CACHE ENGINE ──────────────────────────────────────────────
# Probes run in a background thread on a loop. API endpoints always serve
# from memory cache (instant). On startup, stale data loads from disk so
# the very first request is never cold.

import threading

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
_bg_cache = {
    "infra_quick": None,
    "health": None,
    "update": None,
}
_bg_cache_ts = {
    "infra_quick": 0,
    "health": 0,
    "update": 0,
}
UPDATE_CHECK_INTERVAL = 6 * 3600  # 6 hours
_bg_lock = threading.Lock()


def _cache_path(name):
    return os.path.join(CACHE_DIR, f"{name}.json")


def _load_disk_cache():
    """Load cached probe data from disk — instant startup."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    for name in _bg_cache:
        p = _cache_path(name)
        if os.path.isfile(p):
            try:
                with open(p) as f:
                    data = json.load(f)
                with _bg_lock:
                    _bg_cache[name] = data.get("data")
                    _bg_cache_ts[name] = data.get("ts", 0)
            except (json.JSONDecodeError, OSError) as e:
                logger.warn(f"cache load failed: {name}: {e}")


def _save_disk_cache(name, data):
    """Persist to disk atomically so next server start is instant."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    target = _cache_path(name)
    try:
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"data": data, "ts": time.time()}, f)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        logger.warn(f"cache save failed: {name}: {e}")


def _bg_probe_infra():
    """Probe all physical infra devices — runs in background thread."""
    try:
        cfg = load_config()
    except Exception as e:
        logger.error(f"bg_probe_infra: failed to load config: {e}")
        return
    fb = cfg.fleet_boundaries
    start = time.monotonic()

    def _probe_device(key, dev):
        d = {"key": key, "label": dev.label, "type": dev.device_type,
             "ip": dev.ip, "reachable": False, "metrics": {}}
        dt = dev.device_type
        try:
            if dt == "pfsense":
                r = ssh_single(host=dev.ip,
                    command="echo \"$(sudo pfctl -ss 2>/dev/null | wc -l)|$(uptime)|$(ifconfig -l)\"",
                    key_path=cfg.ssh_key_path, connect_timeout=2, command_timeout=5,
                    htype="pfsense", use_sudo=False, cfg=cfg)
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    m = d["metrics"]
                    parts = r.stdout.strip().split("|", 2)
                    if parts[0].strip():
                        m["states"] = parts[0].strip()
                    if len(parts) > 1:
                        up_match = re.search(r'up\s+(.+?),\s*\d+ user', parts[1])
                        if up_match:
                            m["uptime"] = "up " + up_match.group(1).strip()
                    if len(parts) > 2:
                        ifaces = [i for i in parts[2].strip().split() if not i.startswith(("lo", "enc", "pflog", "pfsync"))]
                        m["interfaces"] = str(len(ifaces))
            elif dt == "truenas":
                # Two quick SSH calls: zpool for pool status, midclt for alert count
                r = ssh_single(host=dev.ip,
                    command="zpool list -o name,size,alloc,free,health -H 2>/dev/null",
                    key_path=cfg.ssh_key_path, connect_timeout=2, command_timeout=8,
                    htype="truenas", use_sudo=True, cfg=cfg)
                r2 = ssh_single(host=dev.ip,
                    command="midclt call alert.list",
                    key_path=cfg.ssh_key_path, connect_timeout=2, command_timeout=8,
                    htype="truenas", use_sudo=True, cfg=cfg)
                if r.returncode == 0:
                    d["reachable"] = True
                    m = d["metrics"]
                    if r.stdout.strip():
                        pools = []
                        for line in r.stdout.strip().split("\n"):
                            cols = line.split()
                            if len(cols) >= 5:
                                pools.append({"name": cols[0], "size": cols[1],
                                              "alloc": cols[2], "free": cols[3], "health": cols[4]})
                        m["pools"] = pools
                        healths = [p["health"] for p in pools]
                        m["pool_health"] = "DEGRADED" if "DEGRADED" in healths else "FAULTED" if "FAULTED" in healths else "ONLINE"
                        total_alloc = sum(float(p["alloc"].replace("T","").replace("G","")) * (1024 if "T" in p["alloc"] else 1) for p in pools)
                        total_size = sum(float(p["size"].replace("T","").replace("G","")) * (1024 if "T" in p["size"] else 1) for p in pools)
                        if total_size > 0:
                            m["capacity_pct"] = str(round(total_alloc / total_size * 100)) + "%"
                        m["total_size"] = pools[0]["size"] if len(pools) == 1 else str(round(total_size/1024, 1)) + "T"
                    # Parse alert count from raw JSON
                    try:
                        alerts = json.loads(r2.stdout) if r2.returncode == 0 else []
                        m["alerts"] = len(alerts) if isinstance(alerts, list) else 0
                    except (json.JSONDecodeError, ValueError):
                        m["alerts"] = 0
            elif dt == "switch":
                # Switch requires RSA key (no ed25519 support)
                sw_key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
                r = ssh_single(host=dev.ip, command="show version | include uptime",
                    key_path=sw_key, connect_timeout=2, command_timeout=5, htype="switch", use_sudo=False, cfg=cfg)
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    d["metrics"]["uptime"] = r.stdout.strip()
            elif dt == "idrac":
                # iDRAC requires RSA key (no ed25519 support)
                idrac_key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
                r = ssh_single(host=dev.ip, command="racadm getsysinfo -s",
                    key_path=idrac_key, connect_timeout=3, command_timeout=8, htype="idrac", use_sudo=False, cfg=cfg)
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    m = d["metrics"]
                    for line in r.stdout.strip().split("\n"):
                        low = line.lower()
                        if "power status" in low:
                            val = line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
                            m["power"] = "ON" if "on" in val.lower() else "OFF"
                        elif "inlet temp" in low:
                            m["inlet_temp"] = line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
                        elif "system model" in low:
                            m["model"] = line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
            else:
                pr = subprocess.run(["ping", "-c", "1", "-W", "1", dev.ip], capture_output=True, timeout=2)
                d["reachable"] = pr.returncode == 0
        except Exception as e:
            logger.warning(f"bg_probe_infra: probe failed for {key} ({dev.ip}): {e}")
        return d

    devices = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_probe_device, k, v): k for k, v in fb.physical.items()}
        for f in concurrent.futures.as_completed(futures):
            try:
                devices.append(f.result())
            except Exception as e:
                logger.warning(f"bg_probe_infra: future failed for {futures[f]}: {e}")

    result = {"devices": devices, "duration": round(time.monotonic() - start, 2), "probed_at": time.time()}
    with _bg_lock:
        _bg_cache["infra_quick"] = result
        _bg_cache_ts["infra_quick"] = time.time()
    _save_disk_cache("infra_quick", result)


def _bg_probe_health():
    """Probe all hosts for health — runs in background thread."""
    try:
        cfg = load_config()
    except Exception as e:
        logger.error(f"bg_probe_health: failed to load config: {e}")
        return
    start = time.monotonic()

    HEALTH_CMDS = {
        "linux": (
            'echo "$(hostname)|$(nproc)|'
            '$(free -m | awk \'/Mem:/ {printf "%d/%dMB", $3, $2}\')|'
            '$(df -h / | awk \'NR==2 {print $5}\')|'
            '$(cat /proc/loadavg | awk \'{print $1}\')|'
            '$(docker ps -q 2>/dev/null | wc -l)"'
        ),
        "pfsense": (
            'echo "$(hostname)|$(sysctl -n hw.ncpu)|'
            '$(sysctl -n hw.physmem hw.usermem 2>/dev/null | '
            'awk \'NR==1{t=$1} NR==2{u=$1} END{printf "%d/%dMB", (t-u)/1048576, t/1048576}\')|'
            '$(df -h / | awk \'NR==2 {print $5}\')|'
            '$(sysctl -n vm.loadavg | awk \'{print $2}\')|0"'
        ),
        "switch": 'show processes cpu | include CPU',
    }

    def _probe_host(h):
        htype = h.htype
        cmd = HEALTH_CMDS.get(htype, HEALTH_CMDS["linux"])
        use_sudo = htype not in ("switch", "idrac")
        probe_key = (cfg.ssh_rsa_key_path or cfg.ssh_key_path) if htype in ("idrac", "switch") else cfg.ssh_key_path
        r = ssh_single(host=h.ip, command=cmd, key_path=probe_key,
                        connect_timeout=cfg.ssh_connect_timeout, command_timeout=15,
                        htype=htype, use_sudo=use_sudo, cfg=cfg)
        _groups = getattr(h, "groups", "") or ""
        if r.returncode != 0 or not r.stdout.strip():
            return {"label": h.label, "ip": h.ip, "type": htype, "groups": _groups,
                    "status": "unreachable", "cores": "-", "ram": "-",
                    "disk": "-", "load": "-", "docker": "0"}
        if htype == "switch":
            m = re.search(r'one minute:\s*(\d+)%', r.stdout)
            cpu_pct = m.group(1) if m else "0"
            sw_key2 = cfg.ssh_rsa_key_path or cfg.ssh_key_path
            r2 = ssh_single(host=h.ip, command='show processes memory | include Processor',
                            key_path=sw_key2, connect_timeout=3,
                            command_timeout=10, htype="switch", use_sudo=False, cfg=cfg)
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
            return {"label": h.label, "ip": h.ip, "type": htype, "groups": _groups,
                    "status": "healthy", "cores": "1", "ram": ram,
                    "disk": "-", "load": load_val, "docker": "0"}
        parts = r.stdout.strip().split("|")
        return {
            "label": h.label, "ip": h.ip, "type": htype, "groups": _groups, "status": "healthy",
            "cores": parts[1] if len(parts) > 1 else "?",
            "ram": parts[2] if len(parts) > 2 else "?",
            "disk": parts[3] if len(parts) > 3 else "?",
            "load": parts[4] if len(parts) > 4 else "?",
            "docker": parts[5].strip() if len(parts) > 5 else "0",
        }

    probe_hosts = cfg.hosts

    host_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.ssh_max_parallel) as pool:
        futures = {pool.submit(_probe_host, h): h for h in probe_hosts}
        for f in concurrent.futures.as_completed(futures):
            try:
                host_data.append(f.result())
            except Exception as e:
                h = futures[f]
                logger.warn(f"health probe failed for {h.label}: {e}")
                host_data.append({"label": h.label, "ip": h.ip, "type": h.htype,
                                  "status": "unreachable", "cores": "-", "ram": "-",
                                  "disk": "-", "load": "-", "docker": "0"})

    # Aggregate container counts per PVE node.
    # Chain: container_vms (vm_id→IP) + WATCHDOG (vm_id→node) + health (IP→docker count)
    node_containers = {}
    try:
        # Build IP→docker count from health data
        ip_docker = {h["ip"]: int(h.get("docker", 0)) for h in host_data if h.get("type") == "docker"}
        # Build vm_id→IP from container_vms config
        vmid_to_ip = {vm.vm_id: vm.ip for vm in cfg.container_vms.values()}
        # Read WATCHDOG for vm_id→node mapping
        wd_path = "/var/lib/freq-watchdog/status.json"
        if os.path.isfile(wd_path):
            with open(wd_path) as f:
                wd_vms = json.load(f).get("watch", {}).get("vms", [])
            for wv in wd_vms:
                vmid = wv.get("vmid", 0)
                node = wv.get("node", "")
                ip = vmid_to_ip.get(vmid, "")
                if ip and ip in ip_docker and node:
                    node_containers[node] = node_containers.get(node, 0) + ip_docker[ip]
    except Exception as e:
        logger.warning(f"bg_probe_health: node_containers aggregation failed: {e}")

    result = {"duration": round(time.monotonic() - start, 1), "hosts": host_data,
              "probed_at": time.time(), "node_containers": node_containers}
    with _bg_lock:
        _bg_cache["health"] = result
        _bg_cache_ts["health"] = time.time()
    _save_disk_cache("health", result)

    # Evaluate alert rules against fresh health data
    _evaluate_alert_rules(cfg, result)

    # Save capacity snapshot if due (weekly)
    try:
        from freq.jarvis.capacity import should_snapshot, save_snapshot
        if should_snapshot(cfg.data_dir):
            save_snapshot(cfg.data_dir, result)
    except Exception as e:
        logger.warn(f"Capacity snapshot failed: {e}")


def _bg_check_update():
    """Check GitHub releases for newer version. Runs every 6 hours."""
    with _bg_lock:
        last_check = _bg_cache_ts.get("update", 0)
    if time.time() - last_check < UPDATE_CHECK_INTERVAL:
        return  # Not time yet

    from freq import __version__
    try:
        url = "https://api.github.com/repos/lowfreqlabs/pve-freq/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "PVE-FREQ-UpdateCheck"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        latest = data.get("tag_name", "").lstrip("v")
        update_available = latest and latest != __version__
        result = {
            "current": __version__,
            "latest": latest,
            "update_available": update_available,
            "release_url": data.get("html_url", ""),
            "checked_at": time.time(),
        }
    except Exception:
        # Air-gapped or rate-limited — gracefully degrade
        result = {
            "current": __version__,
            "latest": "",
            "update_available": False,
            "release_url": "",
            "checked_at": time.time(),
            "error": "Could not reach GitHub",
        }

    with _bg_lock:
        _bg_cache["update"] = result
        _bg_cache_ts["update"] = time.time()
    _save_disk_cache("update", result)


def _evaluate_alert_rules(cfg, health_data):
    """Evaluate alert rules and fire notifications for triggered alerts."""
    try:
        from freq.jarvis.rules import (
            load_rules, evaluate_rules, load_rule_state, save_rule_state,
            load_alert_history, save_alert_history, alert_to_dict,
        )
        rules = load_rules(cfg.conf_dir)
        state = load_rule_state(CACHE_DIR)
        alerts = evaluate_rules(health_data, rules, state)
        save_rule_state(CACHE_DIR, state)

        if alerts:
            history = load_alert_history(CACHE_DIR)
            for alert in alerts:
                # Fire notification
                try:
                    jarvis_notify(cfg, alert.message,
                                  title=f"FREQ Alert: {alert.rule_name}",
                                  severity=alert.severity)
                except Exception as e:
                    logger.warn(f"Alert notification failed: {e}")
                history.append(alert_to_dict(alert))
            save_alert_history(CACHE_DIR, history)
    except Exception as e:
        logger.warn(f"Alert rule evaluation failed: {e}")


def _bg_refresh_loop(interval=BG_CACHE_REFRESH_INTERVAL):
    """Continuous background refresh — runs forever as a daemon thread."""
    while True:
        try:
            _bg_probe_health()
        except Exception as e:
            logger.error(f"bg health probe failed: {e}")
        try:
            _bg_probe_infra()
        except Exception as e:
            logger.error(f"bg infra probe failed: {e}")
        try:
            _bg_check_update()
        except Exception as e:
            logger.error(f"bg update check failed: {e}")
        time.sleep(interval)


def start_background_cache():
    """Load disk cache, then start the background refresh loop."""
    _load_disk_cache()
    t = threading.Thread(target=_bg_refresh_loop, args=(BG_CACHE_REFRESH_INTERVAL,), daemon=True)
    t.start()


# --- Dashboard HTML ---

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE FREQ — Dashboard</title>
<style>
  :root {
    --purple: #7B2FBE;
    --purple-light: #9B4FDE;
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  .header {
    background: linear-gradient(135deg, var(--purple) 0%, #4a1a75 100%);
    padding: 24px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .header h1 { font-size: 24px; font-weight: 600; }
  .header .version { color: rgba(255,255,255,0.6); font-size: 14px; }
  .header .refresh { color: rgba(255,255,255,0.8); font-size: 12px; cursor: pointer; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
  }
  .stat-card .label { color: var(--text-dim); font-size: 13px; margin-bottom: 8px; }
  .stat-card .value { font-size: 28px; font-weight: 700; }
  .stat-card .value.green { color: var(--green); }
  .stat-card .value.yellow { color: var(--yellow); }
  .stat-card .value.red { color: var(--red); }
  .stat-card .value.purple { color: var(--purple-light); }
  .section { margin-bottom: 24px; }
  .section h2 {
    font-size: 16px;
    color: var(--purple-light);
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border-radius: 8px;
    overflow: hidden;
  }
  th {
    text-align: left;
    padding: 12px 16px;
    font-size: 12px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border);
  }
  td {
    padding: 10px 16px;
    font-size: 14px;
    border-bottom: 1px solid var(--border);
  }
  tr:last-child td { border-bottom: none; }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }
  .badge.up { background: rgba(63,185,80,0.15); color: var(--green); }
  .badge.down { background: rgba(248,81,73,0.15); color: var(--red); }
  .badge.warn { background: rgba(210,153,34,0.15); color: var(--yellow); }
  .footer {
    text-align: center;
    padding: 24px;
    color: var(--text-dim);
    font-size: 12px;
  }
  #loading { text-align: center; padding: 60px; color: var(--text-dim); }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab {
    padding: 8px 16px; border-radius: 6px; cursor: pointer;
    background: var(--card); border: 1px solid var(--border);
    color: var(--text-dim); font-size: 13px; font-weight: 500;
  }
  .tab.active { background: var(--purple); color: white; border-color: var(--purple); }
  .panel { display: none; }
  .panel.active { display: block; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
  .mini-card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 6px; padding: 12px 16px;
  }
  .mini-card .title { font-size: 12px; color: var(--text-dim); margin-bottom: 4px; }
  .mini-card .val { font-size: 18px; font-weight: 600; }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>PVE FREQ</h1>
    <span class="version">v""" + freq.__version__ + """ — PVE FREQ</span>
  </div>
  <span class="refresh" onclick="refresh()">Refresh</span>
</div>
<div class="container">
  <div id="loading">Loading fleet data...</div>
  <div id="content" style="display:none">
    <div class="stats">
      <div class="stat-card"><div class="label">Hosts</div><div class="value purple" id="s-hosts">-</div></div>
      <div class="stat-card"><div class="label">Online</div><div class="value green" id="s-up">-</div></div>
      <div class="stat-card"><div class="label">Down</div><div class="value red" id="s-down">-</div></div>
      <div class="stat-card"><div class="label">Response</div><div class="value" id="s-time">-</div></div>
    </div>
    <div class="tabs">
      <div class="tab active" onclick="showTab('fleet')">Fleet</div>
      <div class="tab" onclick="showTab('health')">Health</div>
      <div class="tab" onclick="showTab('info')">Info</div>
    </div>
    <div id="panel-fleet" class="panel active">
      <table>
        <thead><tr><th>Host</th><th>IP</th><th>Type</th><th>Status</th><th>Uptime</th></tr></thead>
        <tbody id="fleet-table"></tbody>
      </table>
    </div>
    <div id="panel-health" class="panel">
      <table>
        <thead><tr><th>Host</th><th>CPU</th><th>RAM</th><th>Disk</th><th>Load</th><th>Status</th></tr></thead>
        <tbody id="health-table"></tbody>
      </table>
    </div>
    <div id="panel-info" class="panel">
      <div class="two-col">
        <div class="mini-card"><div class="title">Version</div><div class="val" id="i-version">-</div></div>
        <div class="mini-card"><div class="title">Cluster</div><div class="val" id="i-cluster">-</div></div>
        <div class="mini-card"><div class="title">PVE Nodes</div><div class="val" id="i-pve">-</div></div>
        <div class="mini-card"><div class="title">Install Dir</div><div class="val" id="i-dir" style="font-size:13px">-</div></div>
      </div>
      <br>
      <h2 style="color:var(--purple-light);font-size:14px;margin-bottom:8px">Policies</h2>
      <table>
        <thead><tr><th>Policy</th><th>Scope</th><th>Description</th></tr></thead>
        <tbody id="policy-table"></tbody>
      </table>
    </div>
  </div>
</div>
<div class="footer">PVE FREQ — Datacenter management for homelabbers</div>
<script>
function refresh() {
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      document.getElementById('loading').style.display = 'none';
      document.getElementById('content').style.display = 'block';
      document.getElementById('s-hosts').textContent = data.total;
      document.getElementById('s-up').textContent = data.up;
      document.getElementById('s-down').textContent = data.down;
      document.getElementById('s-time').textContent = data.duration + 's';
      const tbody = document.getElementById('fleet-table');
      tbody.innerHTML = '';
      data.hosts.forEach(h => {
        const badge = h.status === 'up'
          ? '<span class="badge up">UP</span>'
          : '<span class="badge down">DOWN</span>';
        tbody.innerHTML += '<tr><td><strong>' + h.label + '</strong></td><td>' +
          h.ip + '</td><td>' + h.type + '</td><td>' + badge + '</td><td>' +
          (h.uptime || '-') + '</td></tr>';
      });
    })
    .catch(e => {
      document.getElementById('loading').textContent = 'Error loading data: ' + e;
    });
}
function showTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  event.target.classList.add('active');
  if (name === 'health') loadHealth();
  if (name === 'info') loadInfo();
}
function loadHealth() {
  fetch('/api/health').then(r=>r.json()).then(data => {
    var t = document.getElementById('health-table');
    t.innerHTML = '';
    data.hosts.forEach(h => {
      var diskNum = parseInt(h.disk);
      var diskColor = diskNum >= 90 ? 'red' : diskNum >= 75 ? 'yellow' : 'green';
      var badge = h.status === 'healthy'
        ? '<span class="badge up">OK</span>'
        : '<span class="badge down">DOWN</span>';
      t.innerHTML += '<tr><td><strong>'+h.label+'</strong></td><td>'+h.cores+'</td><td>'+h.ram+'</td><td style="color:var(--'+diskColor+')">'+h.disk+'</td><td>'+h.load+'</td><td>'+badge+'</td></tr>';
    });
  }).catch(()=>{});
}
function loadInfo() {
  fetch('/api/info').then(r=>r.json()).then(data => {
    document.getElementById('i-version').textContent = 'v' + data.version;
    document.getElementById('i-cluster').textContent = data.cluster;
    document.getElementById('i-pve').textContent = data.pve_nodes;
    document.getElementById('i-dir').textContent = data.install_dir;
  }).catch(()=>{});
  fetch('/api/policies').then(r=>r.json()).then(data => {
    var t = document.getElementById('policy-table');
    t.innerHTML = '';
    data.policies.forEach(p => {
      t.innerHTML += '<tr><td><strong>'+p.name+'</strong></td><td>'+p.scope.join(', ')+'</td><td>'+p.description+'</td></tr>';
    });
  }).catch(()=>{});
}
refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""


def _check_vm_permission(cfg, vmid, action):
    """Check if an action is allowed for a VMID. Returns (allowed, error_msg)."""
    fb = cfg.fleet_boundaries
    cat_name, tier = fb.categorize(vmid)
    if fb.can_action(vmid, action):
        return True, ""
    return False, f"Action '{action}' blocked on VMID {vmid} ({cat_name}/{tier})"


def _check_session_role(handler, min_role="operator"):
    """Check if the request has a valid session with sufficient role. Returns (role, error_msg).

    Role hierarchy: viewer < operator < admin.
    Returns (role_str, None) if ok, or (None, error_str) if blocked.
    """
    params = parse_qs(urlparse(handler.path).query)
    token = params.get("token", [""])[0]
    if not token:
        # No auth required if no token system active (backwards compat)
        return "admin", None
    session = FreqHandler._auth_tokens.get(token)
    if not session:
        return None, "Session expired or invalid"
    if time.time() - session["ts"] > SESSION_TIMEOUT_SECONDS:
        del FreqHandler._auth_tokens[token]
        return None, "Session expired"
    role_order = {"viewer": 0, "operator": 1, "admin": 2, "protected": 3}
    if role_order.get(session["role"], 0) < role_order.get(min_role, 1):
        return None, f"Requires {min_role} role (you are {session['role']})"
    return session["role"], None


def _find_reachable_pve_node(cfg):
    """Find the first reachable PVE node. Returns IP string or None."""
    for ip in cfg.pve_nodes:
        r = ssh_single(host=ip, command="sudo pvesh get /version --output-format json",
                       key_path=cfg.ssh_key_path, connect_timeout=3,
                       command_timeout=10, htype="pve", use_sudo=False)
        if r.returncode == 0:
            return ip
    return None


def _parse_query(handler):
    """Parse query parameters from the request path. Returns dict."""
    return parse_qs(urlparse(handler.path).query)


def _is_first_run():
    """Detect if this is the first run (no admin exists, no setup-complete marker).

    Returns True if:
      1. No data/setup-complete marker exists, AND
      2. No users exist in users.conf (or file doesn't exist)
    """
    # Check marker first (fast path — already set up)
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    if os.path.isfile(os.path.join(data_dir, "setup-complete")):
        return False

    # Check if any users exist
    try:
        cfg = load_config()
        users = _load_users(cfg)
        if users:
            return False
    except Exception:
        pass

    return True


def _get_fleet_vms(cfg):
    """Fetch VM list from PVE cluster, enriched with fleet boundary data.

    Shared by _serve_vms and _serve_fleet_overview to avoid duplication.
    Returns list of VM dicts.
    """
    fb = cfg.fleet_boundaries
    vm_list = []
    for node_ip in cfg.pve_nodes:
        r = ssh_single(
            host=node_ip,
            command="pvesh get /cluster/resources --type vm --output-format json",
            key_path=cfg.ssh_key_path,
            command_timeout=15,
            htype="pve", use_sudo=True, cfg=cfg,
        )
        if r.returncode == 0 and r.stdout:
            try:
                vms = json.loads(r.stdout)
                for v in vms:
                    vmid = v.get("vmid", 0)
                    cat_name, tier = fb.categorize(vmid)
                    vm_list.append({
                        "vmid": vmid,
                        "name": v.get("name", ""),
                        "node": v.get("node", ""),
                        "status": v.get("status", ""),
                        "cpu": v.get("maxcpu", 0),
                        "ram_mb": v.get("maxmem", 0) // (1024 * 1024) if v.get("maxmem") else 0,
                        "type": v.get("type", ""),
                        "category": cat_name,
                        "tier": tier,
                        "allowed_actions": fb.allowed_actions(vmid),
                        "is_prod": fb.is_prod(vmid),
                    })
            except json.JSONDecodeError:
                pass
        break  # Only need one node for cluster-wide view
    return vm_list


class FreqHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the FREQ dashboard."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    # Route dispatch table — path → method name (resolved at call time via getattr)
    _ROUTES = {
        "/": "_serve_app",
        "/dashboard": "_serve_app",
        "/old": "_serve_html",
        "/api/status": "_serve_status",
        "/api/health": "_serve_health_api",
        "/api/vms": "_serve_vms",
        "/api/fleet/overview": "_serve_fleet_overview",
        "/api/fleet/ntp": "_serve_fleet_ntp",
        "/api/fleet/updates": "_serve_fleet_updates",
        "/api/agents": "_serve_agents",
        "/api/policies": "_serve_policies",
        "/api/info": "_serve_info",
        "/api/exec": "_serve_exec",
        "/api/learn": "_serve_learn",
        "/api/risk": "_serve_risk",
        "/api/metrics": "_serve_metrics",
        "/api/vm/create": "_serve_vm_create",
        "/api/vm/destroy": "_serve_vm_destroy",
        "/api/vm/snapshot": "_serve_vm_snapshot",
        "/api/vm/resize": "_serve_vm_resize",
        "/api/vm/power": "_serve_vm_power",
        "/api/vm/template": "_serve_vm_template",
        "/api/vm/rename": "_serve_vm_rename",
        "/api/vm/snapshots": "_serve_vm_snapshots",
        "/api/vm/delete-snapshot": "_serve_vm_delete_snapshot",
        "/api/vm/change-id": "_serve_vm_change_id",
        "/api/vm/check-ip": "_serve_vm_check_ip",
        "/api/vm/add-nic": "_serve_vm_add_nic",
        "/api/vm/clear-nics": "_serve_vm_clear_nics",
        "/api/vm/change-ip": "_serve_vm_change_ip",
        "/api/vault": "_serve_vault",
        "/api/vault/set": "_serve_vault_set",
        "/api/vault/delete": "_serve_vault_delete",
        "/api/users": "_serve_users",
        "/api/users/create": "_serve_user_create",
        "/api/users/promote": "_serve_user_promote",
        "/api/users/demote": "_serve_user_demote",
        "/api/keys": "_serve_keys",
        "/api/journal": "_serve_journal",
        "/api/config": "_serve_config",
        "/api/distros": "_serve_distros",
        "/api/groups": "_serve_groups",
        "/api/harden": "_serve_harden",
        "/api/agent/create": "_serve_agent_create",
        "/api/agent/destroy": "_serve_agent_destroy",
        "/api/deploy-agent": "_serve_deploy_agent",
        "/api/switch": "_serve_switch",
        "/api/notify/test": "_serve_notify_test",
        "/api/infra/pfsense": "_serve_pfsense",
        "/api/infra/truenas": "_serve_truenas",
        "/api/infra/idrac": "_serve_idrac",
        "/api/infra/overview": "_serve_infra_overview",
        "/api/infra/quick": "_serve_infra_quick",
        "/api/media/status": "_serve_media_status",
        "/api/media/health": "_serve_media_health",
        "/api/media/downloads": "_serve_media_downloads",
        "/api/media/streams": "_serve_media_streams",
        "/api/media/dashboard": "_serve_media_dashboard",
        "/api/media/restart": "_serve_media_restart",
        "/api/media/logs": "_serve_media_logs",
        "/api/media/update": "_serve_media_update",
        "/api/pool": "_serve_pool",
        "/api/host/detail": "_serve_host_detail",
        "/api/lab/status": "_serve_lab_status",
        "/api/specialists": "_serve_specialists",
        "/api/lab-tool/proxy": "_serve_lab_tool_proxy",
        "/api/lab-tool/config": "_serve_lab_tool_config",
        "/api/lab-tool/save-config": "_serve_lab_tool_save_config",
        "/api/auth/login": "_serve_auth_login",
        "/api/auth/verify": "_serve_auth_verify",
        "/api/auth/change-password": "_serve_auth_change_password",
        "/api/admin/fleet-boundaries": "_serve_admin_fleet_boundaries",
        "/api/admin/fleet-boundaries/update": "_serve_admin_fleet_boundaries_update",
        "/api/admin/hosts/update": "_serve_admin_hosts_update",
        "/api/watchdog/health": "_proxy_watchdog",
        "/api/doctor": "_serve_doctor",
        "/api/diagnose": "_serve_diagnose",
        "/api/log": "_serve_log",
        "/api/policy/check": "_serve_policy_check",
        "/api/policy/fix": "_serve_policy_fix",
        "/api/policy/diff": "_serve_policy_diff",
        "/api/sweep": "_serve_sweep",
        "/api/patrol/status": "_serve_patrol_status",
        "/api/zfs": "_serve_zfs",
        "/api/backup": "_serve_backup",
        "/api/discover": "_serve_discover",
        "/api/gwipe": "_serve_gwipe",
        # Topology & Capacity
        "/api/topology": "_serve_topology",
        "/api/capacity": "_serve_capacity",
        "/api/capacity/snapshot": "_serve_capacity_snapshot",
        # Playbook runner
        "/api/playbooks": "_serve_playbooks",
        "/api/playbooks/run": "_serve_playbooks_run",
        "/api/playbooks/step": "_serve_playbooks_step",
        "/api/playbooks/create": "_serve_playbooks_create",
        # Documentation
        "/api/docs": "_serve_api_docs",
        "/api/openapi.json": "_serve_openapi_json",
        # Orchestration endpoints (no auth)
        "/healthz": "_serve_healthz",
        "/readyz": "_serve_readyz",
        "/api/metrics/prometheus": "_serve_metrics_prometheus",
        # Update check
        "/api/update/check": "_serve_update_check",
        # Alert rules
        "/api/rules": "_serve_rules",
        "/api/rules/create": "_serve_rules_create",
        "/api/rules/update": "_serve_rules_update",
        "/api/rules/delete": "_serve_rules_delete",
        "/api/rules/history": "_serve_rules_history",
        # Setup wizard (no auth — only works during first run)
        "/api/setup/status": "_serve_setup_status",
        "/api/setup/create-admin": "_serve_setup_create_admin",
        "/api/setup/configure": "_serve_setup_configure",
        "/api/setup/generate-key": "_serve_setup_generate_key",
        "/api/setup/complete": "_serve_setup_complete",
    }

    def do_GET(self):
        path = self.path.split("?")[0]
        method_name = self._ROUTES.get(path)
        if method_name:
            try:
                getattr(self, method_name)()
            except Exception as e:
                import traceback
                traceback.print_exc()
                try:
                    self._json_response({"error": str(e), "path": path}, 500)
                except Exception as e2:
                    import sys
                    print(f"[FREQ] Failed to send error response for {path}: {e2}", file=sys.stderr)
        elif path.startswith("/api/comms/") or path.startswith("/api/watch/"):
            self._proxy_watchdog()
        else:
            self.send_error(404)

    # ── Topology ─────────────────────────────────────────────────────────

    def _serve_topology(self):
        """Return network topology data for visualization (nodes, VMs, links)."""
        with _bg_lock:
            health = _bg_cache.get("health")
            fo_cached = _bg_cache.get("infra_quick")

        # Build health lookup
        health_map = {}
        if health and "hosts" in health:
            for h in health["hosts"]:
                health_map[h.get("label", "")] = h

        cfg = load_config()
        fb = cfg.fleet_boundaries
        nodes = []
        links = []

        # PVE nodes
        for pn in fb.pve_nodes.values():
            status = "healthy"
            h = health_map.get(pn.name, {})
            if h.get("status") == "unreachable":
                status = "unreachable"
            nodes.append({
                "id": f"pve:{pn.name}", "label": pn.name, "type": "pve",
                "ip": pn.ip, "status": status,
                "ram": h.get("ram", ""), "disk": h.get("disk", ""), "load": h.get("load", ""),
            })

        # VMs from fleet overview cache or live
        vm_list = _get_fleet_vms(cfg)
        for vm in vm_list:
            node_id = f"pve:{vm['node']}"
            vm_id = f"vm:{vm['vmid']}"
            status = "running" if vm.get("status") == "running" else "stopped"
            # Check if this VM is also a fleet host with health data
            h = health_map.get(vm.get("name", ""), {})
            if h.get("status") == "unreachable" and status == "running":
                status = "unreachable"
            nodes.append({
                "id": vm_id, "label": vm.get("name", str(vm["vmid"])),
                "type": "vm", "vmid": vm["vmid"], "status": status,
                "category": vm.get("category", ""), "node": vm["node"],
                "ram": h.get("ram", ""), "disk": h.get("disk", ""),
                "docker": h.get("docker", "0"),
            })
            links.append({"source": node_id, "target": vm_id})

        # Physical devices
        for dev in fb.physical.values():
            nodes.append({
                "id": f"dev:{dev.key}", "label": dev.label, "type": dev.device_type,
                "ip": dev.ip, "status": "healthy",
            })

        self._json_response({
            "nodes": nodes, "links": links,
            "pve_count": len(fb.pve_nodes),
            "vm_count": len(vm_list),
        })

    # ── Capacity Planner ─────────────────────────────────────────────────

    def _serve_capacity(self):
        """Return capacity projections and trend data."""
        from freq.jarvis.capacity import load_snapshots, compute_projections
        cfg = load_config()
        snapshots = load_snapshots(cfg.data_dir)
        projections = compute_projections(snapshots)
        self._json_response({
            "projections": projections,
            "snapshot_count": len(snapshots),
            "hosts": len(projections),
        })

    def _serve_capacity_snapshot(self):
        """Force a capacity snapshot now (admin only)."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.capacity import save_snapshot
        cfg = load_config()
        with _bg_lock:
            health = _bg_cache.get("health")
        if not health:
            self._json_response({"error": "No health data available yet"}, 503); return
        fname = save_snapshot(cfg.data_dir, health)
        if fname:
            self._json_response({"ok": True, "snapshot": fname})
        else:
            self._json_response({"error": "Failed to save snapshot"}, 500)

    # ── Playbook Runner ─────────────────────────────────────────────────

    def _serve_playbooks(self):
        """List all available playbooks."""
        from freq.jarvis.playbook import load_playbooks, playbooks_to_dicts
        cfg = load_config()
        playbooks = load_playbooks(cfg.conf_dir)
        self._json_response({"playbooks": playbooks_to_dicts(playbooks)})

    def _serve_playbooks_run(self):
        """Run all steps of a playbook (non-confirm steps only)."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        params = _parse_query(self.path)
        filename = params.get("filename", "")
        if not filename:
            self._json_response({"error": "Missing filename parameter"}); return

        from freq.jarvis.playbook import load_playbooks, run_step, result_to_dict
        from freq.core.ssh import run as ssh_run
        cfg = load_config()
        playbooks = load_playbooks(cfg.conf_dir)
        pb = next((p for p in playbooks if p.filename == filename), None)
        if not pb:
            self._json_response({"error": f"Playbook '{filename}' not found"}); return

        results = []
        for step in pb.steps:
            if step.confirm:
                results.append({
                    "step_name": step.name, "step_type": step.step_type,
                    "status": "pending_confirm", "output": "",
                    "error": "Requires confirmation", "duration": 0,
                })
                break
            r = run_step(step, ssh_run, cfg)
            results.append(result_to_dict(r))
            if r.status == "fail":
                break

        self._json_response({
            "playbook": pb.name,
            "filename": pb.filename,
            "results": results,
            "completed": len(results) == len(pb.steps) and all(
                r["status"] == "pass" for r in results
            ),
        })

    def _serve_playbooks_step(self):
        """Run a single step of a playbook by index."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        params = _parse_query(self.path)
        filename = params.get("filename", "")
        step_idx = params.get("step", "")
        if not filename or step_idx == "":
            self._json_response({"error": "Missing filename or step parameter"}); return

        try:
            step_idx = int(step_idx)
        except ValueError:
            self._json_response({"error": "step must be an integer"}); return

        from freq.jarvis.playbook import load_playbooks, run_step, result_to_dict
        from freq.core.ssh import run as ssh_run
        cfg = load_config()
        playbooks = load_playbooks(cfg.conf_dir)
        pb = next((p for p in playbooks if p.filename == filename), None)
        if not pb:
            self._json_response({"error": f"Playbook '{filename}' not found"}); return
        if step_idx < 0 or step_idx >= len(pb.steps):
            self._json_response({"error": f"Step index {step_idx} out of range"}); return

        r = run_step(pb.steps[step_idx], ssh_run, cfg)
        self._json_response({
            "playbook": pb.name,
            "step_index": step_idx,
            "total_steps": len(pb.steps),
            "result": result_to_dict(r),
        })

    def _serve_playbooks_create(self):
        """Create a new playbook from parameters."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        params = _parse_query(self.path)
        name = params.get("name", "").strip()
        if not name:
            self._json_response({"error": "Missing playbook name"}); return

        filename = re.sub(r'[^a-z0-9_-]', '-', name.lower()) + ".toml"
        cfg = load_config()
        pb_dir = os.path.join(cfg.conf_dir, "playbooks")
        os.makedirs(pb_dir, exist_ok=True)
        path = os.path.join(pb_dir, filename)
        if os.path.exists(path):
            self._json_response({"error": f"Playbook '{filename}' already exists"}); return

        description = params.get("description", "")
        trigger = params.get("trigger", "")
        content = f'[playbook]\nname = "{name}"\ndescription = "{description}"\ntrigger = "{trigger}"\n'
        try:
            with open(path, "w") as f:
                f.write(content)
            self._json_response({"ok": True, "filename": filename})
        except OSError as e:
            self._json_response({"error": str(e)}, 500)

    # ── API Documentation ────────────────────────────────────────────────

    def _serve_api_docs(self):
        """Self-contained API documentation page."""
        from freq import __version__
        routes = self._ROUTES
        # Group routes by category
        categories = {}
        for path, method_name in sorted(routes.items()):
            if path in ("/", "/dashboard", "/old", "/api/docs", "/api/openapi.json"):
                continue
            # Extract category from path
            parts = path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "api":
                cat = parts[1].capitalize()
            elif path.startswith("/"):
                cat = "System"
            else:
                cat = "Other"
            # Get docstring from handler
            handler = getattr(self, method_name, None)
            desc = (handler.__doc__ or "").strip().split("\n")[0] if handler else ""
            categories.setdefault(cat, []).append({"path": path, "description": desc})

        # Build HTML
        rows = []
        for cat in sorted(categories.keys()):
            rows.append(f'<tr><td colspan="2" style="background:rgba(123,47,190,0.1);font-weight:600;'
                        f'color:var(--purple-light);letter-spacing:1px;text-transform:uppercase;'
                        f'padding:10px 14px">{cat}</td></tr>')
            for ep in categories[cat]:
                rows.append(f'<tr><td><code>{ep["path"]}</code></td>'
                            f'<td>{ep["description"]}</td></tr>')

        table = "\n".join(rows)
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE FREQ — API Documentation</title>
<style>
:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--dim:#8b949e;--purple:#7B2FBE;--purple-light:#9B4FDE;--green:#3fb950}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',-apple-system,system-ui,sans-serif;background:var(--bg);color:var(--text);padding:32px;max-width:960px;margin:0 auto}}
h1{{font-size:24px;margin-bottom:8px;color:var(--purple-light)}}
.ver{{font-size:13px;color:var(--dim);margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:2px solid var(--border);border-radius:8px;overflow:hidden}}
th{{text-align:left;padding:10px 14px;font-size:11px;color:var(--text);text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid var(--border);background:rgba(0,0,0,0.3)}}
td{{padding:8px 14px;font-size:13px;border-bottom:1px solid var(--border)}}
tr:last-child td{{border-bottom:none}}
code{{background:var(--bg);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--green)}}
a{{color:var(--purple-light);text-decoration:none}}
a:hover{{text-decoration:underline}}
.links{{margin-bottom:24px;font-size:13px}}
</style>
</head><body>
<h1>PVE FREQ API</h1>
<div class="ver">v{__version__} &mdash; {len(routes)} endpoints</div>
<div class="links"><a href="/api/openapi.json">OpenAPI 3.0 Spec (JSON)</a> &middot; <a href="/">Dashboard</a></div>
<table>
<tr><th>Endpoint</th><th>Description</th></tr>
{table}
</table>
</body></html>"""
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_openapi_json(self):
        """OpenAPI 3.0 spec generated from route table."""
        from freq import __version__
        routes = self._ROUTES
        paths = {}
        for path, method_name in sorted(routes.items()):
            if path in ("/", "/dashboard", "/old", "/api/docs", "/api/openapi.json"):
                continue
            handler = getattr(self, method_name, None)
            desc = (handler.__doc__ or "").strip().split("\n")[0] if handler else ""
            paths[path] = {
                "get": {
                    "summary": desc or method_name,
                    "responses": {
                        "200": {"description": "Successful response", "content": {"application/json": {}}},
                    },
                }
            }

        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "PVE FREQ API",
                "version": __version__,
                "description": "Datacenter management API for PVE FREQ",
            },
            "servers": [{"url": "/"}],
            "paths": paths,
        }
        self._json_response(spec)

    # ── Orchestration Endpoints (no auth, lightweight) ──────────────────

    def _serve_healthz(self):
        """Liveness probe — confirms HTTP server is alive. <1ms, no backend work."""
        from freq import __version__
        self._json_response({"status": "ok", "version": __version__})

    def _serve_readyz(self):
        """Readiness probe — 200 if background cache has run, 503 if still warming up."""
        from freq import __version__
        with _bg_lock:
            health_ready = _bg_cache.get("health") is not None
        if health_ready:
            self._json_response({"status": "ready", "version": __version__})
        else:
            self._json_response({"status": "warming_up", "version": __version__}, 503)

    def _serve_metrics_prometheus(self):
        """Prometheus-format metrics from background health cache."""
        from freq import __version__
        uptime = round(time.monotonic() - _SERVER_START_TIME)
        lines = [
            "# HELP freq_info FREQ server info",
            "# TYPE freq_info gauge",
            f'freq_info{{version="{__version__}"}} 1',
            "# HELP freq_uptime_seconds Server uptime in seconds",
            "# TYPE freq_uptime_seconds gauge",
            f"freq_uptime_seconds {uptime}",
        ]
        with _bg_lock:
            health = _bg_cache.get("health")
        if health and "hosts" in health:
            hosts = health["hosts"]
            total = len(hosts)
            healthy = sum(1 for h in hosts if h.get("reachable"))
            unreachable = total - healthy
            total_vms = sum(h.get("vm_count", 0) for h in hosts if isinstance(h.get("vm_count"), int))
            lines.extend([
                "# HELP freq_hosts_total Total fleet hosts",
                "# TYPE freq_hosts_total gauge",
                f"freq_hosts_total {total}",
                "# HELP freq_hosts_healthy Reachable fleet hosts",
                "# TYPE freq_hosts_healthy gauge",
                f"freq_hosts_healthy {healthy}",
                "# HELP freq_hosts_unreachable Unreachable fleet hosts",
                "# TYPE freq_hosts_unreachable gauge",
                f"freq_hosts_unreachable {unreachable}",
                "# HELP freq_vms_total Total VMs across fleet",
                "# TYPE freq_vms_total gauge",
                f"freq_vms_total {total_vms}",
            ])
        body = "\n".join(lines) + "\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    # ── Update Check ─────────────────────────────────────────────────

    def _serve_update_check(self):
        """Return cached update check result."""
        from freq import __version__
        with _bg_lock:
            update = _bg_cache.get("update")
        if update:
            self._json_response(update)
        else:
            self._json_response({
                "current": __version__,
                "latest": "",
                "update_available": False,
                "checked_at": 0,
            })

    # ── Alert Rules Endpoints ──────────────────────────────────────────

    def _serve_rules(self):
        """List all alert rules and their current state."""
        from freq.jarvis.rules import load_rules, rules_to_dicts, load_rule_state
        cfg = load_config()
        rules = load_rules(cfg.conf_dir)
        state = load_rule_state(CACHE_DIR)
        rule_list = rules_to_dicts(rules)
        # Annotate with state info
        for rd in rule_list:
            active_hosts = [k.split(":", 1)[1] for k in state if k.startswith(f"{rd['name']}:")]
            rd["active_hosts"] = active_hosts
        self._json_response({"rules": rule_list, "count": len(rule_list)})

    def _serve_rules_create(self):
        """Create a new alert rule."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.rules import Rule, load_rules, save_rules
        cfg = load_config()
        params = _parse_query(self)
        name = params.get("name", [""])[0].strip()
        condition = params.get("condition", [""])[0].strip()
        if not name or not condition:
            self._json_response({"error": "name and condition required"}); return
        valid_conditions = ("host_unreachable", "cpu_above", "ram_above", "disk_above", "docker_down")
        if condition not in valid_conditions:
            self._json_response({"error": f"Invalid condition. Valid: {', '.join(valid_conditions)}"}); return
        rules = load_rules(cfg.conf_dir)
        if any(r.name == name for r in rules):
            self._json_response({"error": f"Rule '{name}' already exists"}); return
        rules.append(Rule(
            name=name,
            condition=condition,
            target=params.get("target", ["*"])[0].strip(),
            threshold=float(params.get("threshold", ["0"])[0]),
            duration=int(params.get("duration", ["0"])[0]),
            severity=params.get("severity", ["warning"])[0].strip(),
            cooldown=int(params.get("cooldown", ["300"])[0]),
            enabled=params.get("enabled", ["true"])[0].lower() == "true",
        ))
        if save_rules(cfg.conf_dir, rules):
            self._json_response({"ok": True, "name": name})
        else:
            self._json_response({"error": "Failed to save rules"}, 500)

    def _serve_rules_update(self):
        """Update an existing alert rule (enable/disable/modify)."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.rules import load_rules, save_rules
        cfg = load_config()
        params = _parse_query(self)
        name = params.get("name", [""])[0].strip()
        if not name:
            self._json_response({"error": "name required"}); return
        rules = load_rules(cfg.conf_dir)
        rule = next((r for r in rules if r.name == name), None)
        if not rule:
            self._json_response({"error": f"Rule '{name}' not found"}); return
        # Update fields if provided
        if "enabled" in params:
            rule.enabled = params["enabled"][0].lower() == "true"
        if "threshold" in params:
            rule.threshold = float(params["threshold"][0])
        if "duration" in params:
            rule.duration = int(params["duration"][0])
        if "cooldown" in params:
            rule.cooldown = int(params["cooldown"][0])
        if "severity" in params:
            rule.severity = params["severity"][0].strip()
        if "target" in params:
            rule.target = params["target"][0].strip()
        if save_rules(cfg.conf_dir, rules):
            self._json_response({"ok": True, "name": name})
        else:
            self._json_response({"error": "Failed to save rules"}, 500)

    def _serve_rules_delete(self):
        """Delete an alert rule."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.rules import load_rules, save_rules
        cfg = load_config()
        params = _parse_query(self)
        name = params.get("name", [""])[0].strip()
        if not name:
            self._json_response({"error": "name required"}); return
        rules = load_rules(cfg.conf_dir)
        before = len(rules)
        rules = [r for r in rules if r.name != name]
        if len(rules) == before:
            self._json_response({"error": f"Rule '{name}' not found"}); return
        if save_rules(cfg.conf_dir, rules):
            self._json_response({"ok": True, "deleted": name})
        else:
            self._json_response({"error": "Failed to save rules"}, 500)

    def _serve_rules_history(self):
        """Return recent alert history."""
        from freq.jarvis.rules import load_alert_history
        history = load_alert_history(CACHE_DIR)
        self._json_response({"alerts": history, "count": len(history)})

    # ── Setup Wizard Endpoints (no auth — gated by _is_first_run) ──────

    def _serve_setup_status(self):
        """Return current setup state including SSH key existence."""
        from freq import __version__
        cfg = load_config()
        ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
        self._json_response({
            "first_run": _is_first_run(),
            "version": __version__,
            "ssh_key_exists": os.path.isfile(ed_key),
            "ssh_key_path": ed_key,
        })

    def _serve_setup_create_admin(self):
        """Create admin account during first-run setup."""
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        params = _parse_query(self)
        username = params.get("username", [""])[0].strip().lower()
        password = params.get("password", [""])[0]

        if not username or not password:
            self._json_response({"error": "Username and password required"})
            return

        # Validate username
        if not re.match(r'^[a-z_][a-z0-9_-]{0,31}$', username):
            self._json_response({"error": "Invalid username (lowercase, 1-32 chars, alphanumeric/hyphens/underscores)"})
            return

        if len(password) < 8:
            self._json_response({"error": "Password must be at least 8 characters"})
            return

        cfg = load_config()

        # Create user in users.conf
        users = _load_users(cfg)
        if any(u["username"] == username for u in users):
            self._json_response({"error": f"User '{username}' already exists"})
            return

        users.append({"username": username, "role": "admin", "groups": ""})
        os.makedirs(cfg.conf_dir, exist_ok=True)
        if not _save_users(cfg, users):
            self._json_response({"error": "Failed to save user"}, 500)
            return

        # Store password hash in vault
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        try:
            if not os.path.exists(cfg.vault_file):
                vault_init(cfg)
            vault_set(cfg, "auth", f"password_{username}", pw_hash)
        except Exception as e:
            self._json_response({"error": f"Failed to store password: {e}"}, 500)
            return

        self._json_response({"ok": True, "user": username, "role": "admin"})

    def _serve_setup_configure(self):
        """Save cluster configuration during first-run setup."""
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        params = _parse_query(self)
        cluster_name = params.get("cluster_name", [""])[0].strip()
        timezone = params.get("timezone", ["UTC"])[0].strip()
        pve_nodes = params.get("pve_nodes", [""])[0].strip()

        cfg = load_config()

        # Write/update freq.toml
        toml_path = os.path.join(cfg.conf_dir, "freq.toml")
        os.makedirs(cfg.conf_dir, exist_ok=True)

        # Build config content
        lines = ['[freq]']
        if cluster_name:
            lines.append(f'cluster_name = "{cluster_name}"')
        lines.append(f'timezone = "{timezone}"')
        lines.append('')

        if pve_nodes:
            node_ips = [ip.strip() for ip in pve_nodes.split(",") if ip.strip()]
            if node_ips:
                lines.append('[pve]')
                lines.append(f'nodes = {json.dumps(node_ips)}')
                lines.append('')

        try:
            with open(toml_path, "w") as f:
                f.write("\n".join(lines) + "\n")
            self._json_response({"ok": True, "cluster_name": cluster_name, "timezone": timezone})
        except OSError as e:
            self._json_response({"error": f"Failed to write config: {e}"}, 500)

    def _serve_setup_generate_key(self):
        """Generate SSH keypair during first-run setup."""
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        cfg = load_config()
        key_dir = cfg.key_dir
        os.makedirs(key_dir, mode=0o700, exist_ok=True)

        hostname = os.uname().nodename
        ed_key = os.path.join(key_dir, "freq_id_ed25519")

        if os.path.isfile(ed_key):
            # Key already exists — read and return public key
            pub_path = f"{ed_key}.pub"
            pubkey = ""
            if os.path.isfile(pub_path):
                with open(pub_path) as f:
                    pubkey = f.read().strip()
            self._json_response({"ok": True, "exists": True, "pubkey": pubkey, "key_path": ed_key})
            return

        # Generate ed25519 keypair
        result = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-C", f"freq@{hostname}",
             "-f", ed_key, "-N", "", "-q"],
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode != 0:
            self._json_response({"error": f"Key generation failed: {result.stderr[:100]}"}, 500)
            return

        os.chmod(ed_key, 0o600)
        os.chmod(f"{ed_key}.pub", 0o644)

        # Also generate RSA key for legacy devices
        rsa_key = os.path.join(key_dir, "freq_id_rsa")
        if not os.path.isfile(rsa_key):
            subprocess.run(
                ["ssh-keygen", "-t", "rsa", "-b", "4096",
                 "-C", f"freq-legacy@{hostname}", "-f", rsa_key, "-N", "", "-q"],
                capture_output=True, text=True, timeout=30,
            )
            if os.path.isfile(rsa_key):
                os.chmod(rsa_key, 0o600)
                os.chmod(f"{rsa_key}.pub", 0o644)

        # Read public key
        pubkey = ""
        pub_path = f"{ed_key}.pub"
        if os.path.isfile(pub_path):
            with open(pub_path) as f:
                pubkey = f.read().strip()

        self._json_response({"ok": True, "exists": False, "pubkey": pubkey, "key_path": ed_key})

    def _serve_setup_complete(self):
        """Mark setup as complete — writes marker file."""
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)
        marker = os.path.join(data_dir, "setup-complete")

        try:
            with open(marker, "w") as f:
                f.write(f"Setup completed: {datetime.datetime.now().isoformat()}\n")
            self._json_response({"ok": True, "message": "Setup complete — redirecting to dashboard"})
        except OSError as e:
            self._json_response({"error": f"Failed to write setup marker: {e}"}, 500)

    # ── Legacy + Main HTML ───────────────────────────────────────────────

    def _serve_html(self):
        # Pre-fetch fleet data and embed it in HTML for instant load
        cfg = load_config()
        start = time.monotonic()
        results = ssh_run_many(
            hosts=cfg.hosts, command="uptime -p 2>/dev/null || uptime",
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=5, max_parallel=10, use_sudo=False, cfg=cfg,
        )
        duration = round(time.monotonic() - start, 1)

        host_data = []
        up = down = 0
        for h in cfg.hosts:
            r = results.get(h.label)
            if r and r.returncode == 0:
                up += 1
                host_data.append({"label": h.label, "ip": h.ip, "type": h.htype,
                                  "status": "up", "uptime": r.stdout.strip().replace("up ", "")[:40]})
            else:
                down += 1
                host_data.append({"label": h.label, "ip": h.ip, "type": h.htype,
                                  "status": "down", "uptime": ""})

        initial_data = json.dumps({"total": len(cfg.hosts), "up": up, "down": down,
                                   "duration": duration, "hosts": host_data})

        # Inject pre-fetched data into HTML
        html = DASHBOARD_HTML.replace(
            "refresh();",
            f"var INITIAL_DATA = {initial_data};\n"
            "function loadInitial(data) {\n"
            "  document.getElementById('loading').style.display = 'none';\n"
            "  document.getElementById('content').style.display = 'block';\n"
            "  document.getElementById('s-hosts').textContent = data.total;\n"
            "  document.getElementById('s-up').textContent = data.up;\n"
            "  document.getElementById('s-down').textContent = data.down;\n"
            "  document.getElementById('s-time').textContent = data.duration + 's';\n"
            "  var tbody = document.getElementById('fleet-table');\n"
            "  tbody.innerHTML = '';\n"
            "  data.hosts.forEach(function(h) {\n"
            "    var badge = h.status === 'up'\n"
            "      ? '<span class=\"badge up\">UP</span>'\n"
            "      : '<span class=\"badge down\">DOWN</span>';\n"
            "    tbody.innerHTML += '<tr><td><strong>' + h.label + '</strong></td><td>' +\n"
            "      h.ip + '</td><td>' + h.type + '</td><td>' + badge + '</td><td>' +\n"
            "      (h.uptime || '-') + '</td></tr>';\n"
            "  });\n"
            "}\n"
            "loadInitial(INITIAL_DATA);\n"
            "// Still auto-refresh via API\nsetInterval(refresh, 30000);\n"
            "// refresh();"
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode())))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_status(self):
        cfg = load_config()
        hosts = cfg.hosts
        start = time.monotonic()

        results = ssh_run_many(
            hosts=hosts,
            command="uptime -p 2>/dev/null || uptime",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,    # Fast timeout for web UI
            command_timeout=5,    # Don't let one slow host block the page
            max_parallel=10,      # All hosts at once
            use_sudo=False, cfg=cfg,
        )

        duration = round(time.monotonic() - start, 1)
        up = 0
        down = 0
        host_data = []

        for h in hosts:
            r = results.get(h.label)
            if r and r.returncode == 0:
                up += 1
                uptime = r.stdout.strip().replace("up ", "")[:40]
                host_data.append({
                    "label": h.label, "ip": h.ip, "type": h.htype,
                    "status": "up", "uptime": uptime,
                })
            else:
                down += 1
                host_data.append({
                    "label": h.label, "ip": h.ip, "type": h.htype,
                    "status": "down", "uptime": "",
                })

        response = json.dumps({
            "total": len(hosts), "up": up, "down": down,
            "duration": duration, "hosts": host_data,
        })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response.encode())

    def _serve_health_api(self):
        """Fleet health — served from background cache, always instant."""
        with _bg_lock:
            cached = _bg_cache.get("health")
        if cached:
            cached["cached"] = True
            cached["age"] = round(time.time() - _bg_cache_ts.get("health", 0), 1)
            self._json_response(cached)
            return
        # Fallback: no cache yet (first few seconds after cold start)
        cfg = load_config()
        start = time.monotonic()

        # Platform-specific health commands — all output: hostname|cores|used/totalMB|disk%|load|docker_count
        HEALTH_CMDS = {
            "linux": (
                'echo "$(hostname)|$(nproc)|'
                '$(free -m | awk \'/Mem:/ {printf "%d/%dMB", $3, $2}\')|'
                '$(df -h / | awk \'NR==2 {print $5}\')|'
                '$(cat /proc/loadavg | awk \'{print $1}\')|'
                '$(docker ps -q 2>/dev/null | wc -l)"'
            ),
            "pfsense": (
                'echo "$(hostname)|$(sysctl -n hw.ncpu)|'
                '$(sysctl -n hw.physmem hw.usermem 2>/dev/null | '
                'awk \'NR==1{t=$1} NR==2{u=$1} END{printf "%d/%dMB", (t-u)/1048576, t/1048576}\')|'
                '$(df -h / | awk \'NR==2 {print $5}\')|'
                '$(sysctl -n vm.loadavg | awk \'{print $2}\')|0"'
            ),
            "switch": 'show processes cpu | include CPU',
        }

        def _probe_host(h):
            htype = h.htype
            cmd = HEALTH_CMDS.get(htype, HEALTH_CMDS["linux"])
            use_sudo = htype not in ("switch", "idrac")
            # iDRAC/switch require RSA key (no ed25519 support)
            probe_key = (cfg.ssh_rsa_key_path or cfg.ssh_key_path) if htype in ("idrac", "switch") else cfg.ssh_key_path
            r = ssh_single(
                host=h.ip, command=cmd,
                key_path=probe_key,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=15,
                htype=htype, use_sudo=use_sudo, cfg=cfg,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return {"label": h.label, "ip": h.ip, "type": htype,
                        "groups": getattr(h, "groups", "") or "",
                        "status": "unreachable", "cores": "-", "ram": "-",
                        "disk": "-", "load": "-", "docker": "0"}

            if htype == "switch":
                # Parse: "CPU utilization for five seconds: 10%/0%; one minute: 8%; five minutes: 8%"
                m = re.search(r'one minute:\s*(\d+)%', r.stdout)
                cpu_pct = m.group(1) if m else "0"
                # Get memory in a second call
                r2 = ssh_single(host=h.ip, command='show processes memory | include Processor',
                                key_path=probe_key, connect_timeout=3,
                                command_timeout=10, htype="switch", use_sudo=False, cfg=cfg)
                ram = "-"
                if r2.returncode == 0 and r2.stdout:
                    parts = r2.stdout.split()
                    # "Processor Pool Total: 939790504 Used: 234591540 Free: 705198964"
                    try:
                        idx_t = parts.index("Total:") + 1
                        idx_u = parts.index("Used:") + 1
                        total_mb = int(parts[idx_t]) // 1048576
                        used_mb = int(parts[idx_u]) // 1048576
                        ram = f"{used_mb}/{total_mb}MB"
                    except (ValueError, IndexError):
                        pass
                # Convert CPU% to Unix-style load (load/cores*100 = pct in frontend)
                load_val = f"{float(cpu_pct) / 100:.2f}" if cpu_pct != "0" else "0.00"
                return {"label": h.label, "ip": h.ip, "type": htype,
                        "groups": getattr(h, "groups", "") or "",
                        "status": "healthy", "cores": "1", "ram": ram,
                        "disk": "-", "load": load_val, "docker": "0"}

            # Standard pipe-delimited output
            parts = r.stdout.strip().split("|")
            return {
                "label": h.label, "ip": h.ip, "type": htype,
                "groups": getattr(h, "groups", "") or "",
                "status": "healthy",
                "cores": parts[1] if len(parts) > 1 else "?",
                "ram": parts[2] if len(parts) > 2 else "?",
                "disk": parts[3] if len(parts) > 3 else "?",
                "load": parts[4] if len(parts) > 4 else "?",
                "docker": parts[5].strip() if len(parts) > 5 else "0",
            }

        # Run all probes in parallel
        host_data = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.ssh_max_parallel) as pool:
            futures = {pool.submit(_probe_host, h): h for h in cfg.hosts}
            for f in concurrent.futures.as_completed(futures):
                try:
                    host_data.append(f.result())
                except Exception as e:
                    h = futures[f]
                    logger.warn(f"health probe failed for {h.label}: {e}")
                    host_data.append({"label": h.label, "ip": h.ip, "type": h.htype,
                                      "groups": getattr(h, "groups", "") or "",
                                      "status": "unreachable", "cores": "-", "ram": "-",
                                      "disk": "-", "load": "-", "docker": "0"})

        duration = round(time.monotonic() - start, 1)
        result = {"duration": duration, "hosts": host_data}
        self._json_response(result)

    def _serve_vms(self):
        """VM inventory from PVE cluster — enriched with fleet boundaries."""
        cfg = load_config()
        vm_list = _get_fleet_vms(cfg)
        self._json_response({"vms": vm_list, "count": len(vm_list)})

    def _serve_fleet_overview(self):
        """Master endpoint — everything the frontend needs in one call."""
        cfg = load_config()
        fb = cfg.fleet_boundaries
        start = time.monotonic()

        vm_list = _get_fleet_vms(cfg)

        # Physical devices — ping each to check reachability
        physical = []
        for dev in fb.physical.values():
            reachable = False
            try:
                r = subprocess.run(
                    ["ping", "-c", "1", "-W", "1", dev.ip],
                    capture_output=True, timeout=2,
                )
                reachable = r.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                pass
            physical.append({
                "key": dev.key, "ip": dev.ip, "label": dev.label,
                "type": dev.device_type, "tier": dev.tier, "detail": dev.detail,
                "reachable": reachable,
            })

        # PVE nodes — enrich with live stats from PVE API
        node_stats = {}
        for node_ip in cfg.pve_nodes[:1]:  # query one node for cluster-wide data
            r = ssh_single(
                host=node_ip,
                command="pvesh get /cluster/resources --type node --output-format json",
                key_path=cfg.ssh_key_path,
                command_timeout=15,
                htype="pve", use_sudo=True, cfg=cfg,
            )
            if r.returncode == 0 and r.stdout:
                try:
                    for n in json.loads(r.stdout):
                        node_stats[n.get("node", "")] = {
                            "cores": n.get("maxcpu", 0),
                            "ram_gb": round(n.get("maxmem", 0) / (1024 ** 3)),
                        }
                except json.JSONDecodeError:
                    pass

        pve_nodes = []
        for node in fb.pve_nodes.values():
            entry = {"name": node.name, "ip": node.ip, "detail": node.detail}
            ns = node_stats.get(node.name, {})
            if ns:
                entry["cores"] = ns["cores"]
                entry["ram_gb"] = ns["ram_gb"]
            pve_nodes.append(entry)

        # Category summaries
        cat_summary = {}
        for cat_name, cat_info in fb.categories.items():
            running = sum(1 for v in vm_list if v["category"] == cat_name and v["status"] == "running")
            total = sum(1 for v in vm_list if v["category"] == cat_name)
            cat_summary[cat_name] = {
                "count": total,
                "running": running,
                "description": cat_info.get("description", ""),
                "tier": cat_info.get("tier", "probe"),
            }

        # Overall summary (exclude templates from main counts)
        non_template = [v for v in vm_list if v["category"] != "templates"]
        total_vms = len(non_template)
        running = sum(1 for v in non_template if v["status"] == "running")
        stopped = sum(1 for v in non_template if v["status"] == "stopped")
        prod_count = sum(1 for v in non_template if v["is_prod"])
        lab_count = sum(1 for v in non_template if v["category"] == "lab")
        template_count = sum(1 for v in vm_list if v["category"] == "templates")

        # VM NIC data — batch fetch per node, parse VLAN tags
        vlan_id_to_name = {v.id: v.name for v in cfg.vlans}
        # Tag 2550 is MGMT VLAN (untagged on some bridges as vmbr0v2550)
        if 2550 not in vlan_id_to_name:
            vlan_id_to_name[2550] = "MGMT"
        vm_nics = {}
        # Group VMs by node
        node_vmids = {}
        for v in vm_list:
            node_vmids.setdefault(v["node"], []).append(v["vmid"])
        node_ips = {n.name: n.ip for n in fb.pve_nodes.values()}
        for node_name, vmids in node_vmids.items():
            nip = node_ips.get(node_name)
            if not nip:
                continue
            # Batch: dump net* lines for all VMIDs on this node
            cmd_parts = []
            for vid in vmids:
                cmd_parts.append(f"echo VMID:{vid}; qm config {vid} 2>/dev/null | grep ^net")
            batch_cmd = "; ".join(cmd_parts)
            r = ssh_single(
                host=nip, command=batch_cmd,
                key_path=cfg.ssh_key_path,
                command_timeout=20,
                htype="pve", use_sudo=True, cfg=cfg,
            )
            if r.returncode == 0 and r.stdout:
                cur_vmid = None
                for line in r.stdout.strip().split("\n"):
                    if line.startswith("VMID:"):
                        cur_vmid = int(line[5:])
                        vm_nics[cur_vmid] = []
                    elif cur_vmid is not None and line.startswith("net"):
                        # Parse: net0: virtio=XX,bridge=vmbr0,tag=2550
                        nic_name = line.split(":")[0].strip()
                        tag_match = re.search(r'tag=(\d+)', line)
                        vlan_tag = int(tag_match.group(1)) if tag_match else 0
                        vlan_name = vlan_id_to_name.get(vlan_tag, f"VLAN {vlan_tag}" if vlan_tag else "UNTAGGED")
                        vm_nics[cur_vmid].append({
                            "nic": nic_name,
                            "tag": vlan_tag,
                            "vlan_name": vlan_name,
                        })

        duration = round(time.monotonic() - start, 2)
        self._json_response({
            "vms": vm_list,
            "vm_nics": {str(k): v for k, v in vm_nics.items()},
            "physical": physical,
            "pve_nodes": pve_nodes,
            "vlans": [{"id": v.id, "name": v.name, "prefix": v.prefix, "gateway": v.gateway,
                       "cidr": v.subnet.split("/")[1] if "/" in v.subnet else "24"}
                      for v in cfg.vlans],
            "nic_profiles": cfg.nic_profiles,
            "categories": cat_summary,
            "summary": {
                "total_vms": total_vms,
                "running": running,
                "stopped": stopped,
                "prod_count": prod_count,
                "lab_count": lab_count,
                "template_count": template_count,
            },
            "duration": duration,
        })

    def _serve_agents(self):
        """Agent registry."""
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
        self._json_response({"agents": agent_list, "count": len(agent_list)})

    def _serve_policies(self):
        """Available policies."""
        from freq.engine.policies import ALL_POLICIES
        policy_list = [
            {
                "name": p["name"],
                "description": p.get("description", ""),
                "scope": p.get("scope", []),
            }
            for p in ALL_POLICIES
        ]
        self._json_response({"policies": policy_list, "count": len(policy_list)})

    def _serve_info(self):
        """FREQ installation info."""
        cfg = load_config()
        from freq.core.personality import load_pack
        pack = load_pack(cfg.conf_dir, cfg.build)
        self._json_response({
            "version": freq.__version__,
            "brand": cfg.brand,
            "build": cfg.build,
            "hosts": len(cfg.hosts),
            "pve_nodes": len(cfg.pve_nodes),
            "cluster": cfg.cluster_name,
            "install_dir": cfg.install_dir,
            "subtitle": getattr(pack, "subtitle", cfg.brand) if pack else cfg.brand,
            "dashboard_header": getattr(pack, "dashboard_header", "PVE FREQ Dashboard") if pack else "PVE FREQ Dashboard",
        })

    def _serve_app(self):
        """Serve the full web UI, or setup wizard on first run."""
        if _is_first_run():
            from freq.modules.web_ui import SETUP_HTML
            body = SETUP_HTML.encode()
        else:
            from freq.modules.web_ui import APP_HTML
            body = APP_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _serve_exec(self):
        """Execute a command across fleet hosts via API."""

        params = _parse_query(self)
        target = params.get("target", ["all"])[0]
        cmd = params.get("cmd", [""])[0]

        if not cmd:
            self._json_response({"error": "No command specified"})
            return

        cfg = load_config()

        # Resolve targets
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
            self._json_response({"error": f"No hosts matched: {target}", "results": []})
            return

        results = ssh_run_many(
            hosts=hosts, command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=3, command_timeout=15,
            max_parallel=10, use_sudo=False,
        )

        result_list = []
        for h in hosts:
            r = results.get(h.label)
            if r and r.returncode == 0:
                result_list.append({"host": h.label, "ok": True, "output": r.stdout, "error": ""})
            else:
                result_list.append({"host": h.label, "ok": False, "output": "",
                                    "error": r.stderr[:100] if r else "no response"})

        self._json_response({"target": target, "command": cmd, "results": result_list})

    def _serve_learn(self):
        """Search the knowledge base via API."""


        params = _parse_query(self)
        query = params.get("q", [""])[0]

        if not query:
            self._json_response({"lessons": [], "gotchas": [], "query": ""})
            return

        cfg = load_config()
        from freq.jarvis.learn import _init_db, _seed_db, _search, _load_knowledge

        db_path = os.path.join(cfg.data_dir, "jarvis", "knowledge.db")
        conn = _init_db(db_path)
        lessons_data, gotchas_data = _load_knowledge(cfg)
        _seed_db(conn, lessons_data, gotchas_data)
        lessons, gotchas = _search(conn, query)
        conn.close()

        lesson_list = [
            {"number": l[0], "session": l[1], "platform": l[2], "severity": l[3],
             "title": l[4], "description": l[5], "commands": l[6]}
            for l in lessons
        ]
        gotcha_list = [
            {"platform": g[0], "trigger": g[1], "description": g[2], "fix": g[3]}
            for g in gotchas
        ]

        self._json_response({"query": query, "lessons": lesson_list, "gotchas": gotcha_list})

    def _serve_metrics(self):
        """Collect metrics from fleet agents or SSH fallback."""
        cfg = load_config()
        params = _parse_query(self)
        target = params.get("host", [None])[0]

        hosts = [h for h in cfg.hosts if h.label == target] if target else cfg.hosts
        results = []

        for h in hosts:
            # Try agent first (fast HTTP)
            try:
                url = f"http://{h.ip}:{cfg.agent_port}/metrics"
                resp = urllib.request.urlopen(url, timeout=2)
                data = json.loads(resp.read().decode())
                data["source"] = "agent"
                results.append(data)
                continue
            except (urllib.error.URLError, json.JSONDecodeError, OSError):
                pass

            # Fallback to SSH
            cmd = (
                "echo '{\"cpu\":{\"cores\":'$(nproc)',\"load_1m\":'$(awk '{print $1}' /proc/loadavg)'},"
                "\"memory\":{\"total_mb\":'$(free -m|awk '/Mem:/{print $2}')','\"used_mb\":'$(free -m|awk '/Mem:/{print $3}')','\"usage_pct\":'$(free|awk '/Mem:/{printf \"%.1f\",$3/$2*100}')'}',"
                "\"system\":{\"hostname\":\"'$(hostname)'\",\"uptime_human\":\"'$(uptime -p 2>/dev/null|sed 's/up //'||echo unknown)'\"},"
                "\"source\":\"ssh\"}'"
            )
            r = ssh_single(host=h.ip, command=cmd, key_path=cfg.ssh_key_path,
                           connect_timeout=3, command_timeout=5, htype=h.htype, use_sudo=False, cfg=cfg)
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout)
                    results.append(data)
                except json.JSONDecodeError:
                    results.append({"hostname": h.label, "source": "error"})
            else:
                results.append({"hostname": h.label, "source": "unreachable"})

        self._json_response({"hosts": results, "count": len(results)})

    def _serve_pfsense(self):
        """pfSense data via SSH."""


        cfg = load_config()
        params = _parse_query(self)
        action = params.get("action", ["status"])[0]

        pf_ip = cfg.pfsense_ip
        if not pf_ip:
            self._json_response({"error": "pfSense IP not configured", "data": {}})
            return

        actions = {
            "status": (
                "echo \"=== SYSTEM === \";uname -sr; uptime;"
                "echo \"=== PF STATUS === \";pfctl -s info 2>/dev/null | head -12;"
                "echo \"=== GATEWAY === \";netstat -rn | grep default | head -5"
            ),
            "rules": (
                "echo \"=== FILTER RULES === \";"
                "pfctl -sr 2>/dev/null | grep -v '^scrub' | grep -v '^anchor' | "
                "sed 's/ label \"[^\"]*\"//g; s/ ridentifier [0-9]*//g' | "
                "grep -v 'icmp6-type' | "
                "awk '{"
                "  action=$1; dir=$2; quick=\"\";"
                "  if($3==\"quick\"){quick=\" quick\"; iface=$5; rest=\"\";"
                "    for(i=6;i<=NF;i++) rest=rest\" \"$i}"
                "  else{iface=$4; rest=\"\";"
                "    for(i=5;i<=NF;i++) rest=rest\" \"$i}"
                "  gsub(/^ /,\"\",rest);"
                "  if(action==\"block\") color=\"BLOCK\";"
                "  else if(action==\"pass\") color=\"PASS\";"
                "  else color=action;"
                "  printf \"%-6s %-4s %-8s  %-18s  %s\\n\", toupper(color), dir, quick, iface, rest"
                "}' | head -40;"
                "echo \"\";"
                "echo \"=== SUMMARY === \";"
                "total=$(pfctl -sr 2>/dev/null | wc -l | tr -d ' ');"
                "blocks=$(pfctl -sr 2>/dev/null | grep -c '^block');"
                "passes=$(pfctl -sr 2>/dev/null | grep -c '^pass');"
                "scrubs=$(pfctl -sr 2>/dev/null | grep -c '^scrub');"
                "printf 'Total: %s  |  Pass: %s  |  Block: %s  |  Scrub: %s\\n' \"$total\" \"$passes\" \"$blocks\" \"$scrubs\""
            ),
            "nat": (
                "echo \"=== NAT RULES === \";"
                "pfctl -sn 2>/dev/null | grep -v '^no ' | grep -v '^rdr-anchor' | grep -v '^nat-anchor' | "
                "awk '{"
                "  type=$1;"
                "  if(type==\"nat\"){"
                "    iface=$3; proto=\"\"; src=\"\"; dst=\"\"; arrow=\"\"; target=\"\";"
                "    for(i=4;i<=NF;i++){"
                "      if($i==\"inet\"||$i==\"inet6\") proto=$i;"
                "      else if($i==\"from\"){src=$(i+1); i++}"
                "      else if($i==\"to\"){dst=$(i+1); i++}"
                "      else if($i==\"->\"){target=$(i+1); i++}"
                "    }"
                "    if(src==\"any\") src=\"*\";"
                "    if(dst==\"any\") dst=\"*\";"
                "    printf \"NAT  %-14s  %-6s  %-22s -> %-22s  => %s\\n\", iface, proto, src, dst, target"
                "  }"
                "  else if(type==\"rdr\"){"
                "    iface=$3; proto=\"\"; src=\"\"; port=\"\"; target=\"\"; tport=\"\";"
                "    for(i=4;i<=NF;i++){"
                "      if($i==\"proto\"){proto=$(i+1); i++}"
                "      else if($i==\"to\" && target==\"\"){dst=$(i+1); i++; if($(i+1)==\"port\"){port=$(i+2); i+=2}}"
                "      else if($i==\"->\"){target=$(i+1); i++; if($(i+1)==\"port\"){tport=$(i+2); i+=2}}"
                "    }"
                "    printf \"RDR  %-14s  %-6s  %-22s => %s:%s\\n\", iface, proto, dst\":\"port, target, tport"
                "  }"
                "}';"
                "echo \"\";"
                "echo \"=== PORT FORWARDS === \";"
                "pfctl -sn 2>/dev/null | grep '^rdr' | grep -v 'anchor' | "
                "sed 's/ ridentifier [0-9]*//g' | head -10;"
                "echo \"\";"
                "echo \"=== SUMMARY === \";"
                "nat_count=$(pfctl -sn 2>/dev/null | grep -c '^nat');"
                "rdr_count=$(pfctl -sn 2>/dev/null | grep -c '^rdr[^-]');"
                "printf 'NAT rules: %s  |  Port forwards: %s\\n' \"$nat_count\" \"$rdr_count\""
            ),
            "states": (
                "echo \"Active states: $(pfctl -ss 2>/dev/null | wc -l | tr -d ' ')\";"
                "echo \"\";echo \"=== TOP STATES (by source) === \";"
                "pfctl -ss 2>/dev/null | awk '{print $3}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -15"
            ),
            "interfaces": (
                "echo \"=== INTERFACES WITH IPs === \";"
                "ifconfig -a | grep -E '^[a-z]|inet ' | awk '/^[a-z]/{iface=$1} /inet /{print iface, $2}' | column -t; "
                "echo \"\";echo \"=== ALL INTERFACES === \";ifconfig -l | tr ' ' '\\n'"
            ),
            "gateways": (
                "echo \"=== ROUTING TABLE === \";netstat -rn | head -25;"
                "echo \"\";echo \"=== DEFAULT GATEWAYS === \";netstat -rn | grep default"
            ),
            "vpn": (
                "echo \"=== WIREGUARD TUNNELS === \";wg show 2>/dev/null || echo No_WireGuard_tunnels;"
                "echo \"\";echo \"=== IPSEC === \";ipsec statusall 2>/dev/null | head -10 || echo No_IPsec"
            ),
            "arp": (
                "echo \"=== ARP TABLE === \";"
                "echo \"\";"
                "printf '%-18s  %-20s  %-16s  %-8s\\n' 'IP ADDRESS' 'MAC ADDRESS' 'INTERFACE' 'TYPE';"
                "printf '%-18s  %-20s  %-16s  %-8s\\n' '──────────────────' '────────────────────' '────────────────' '────────';"
                "arp -an | sed 's/? (//;s/) at / /;s/ on / /;s/ permanent/PERM/;s/ expires in [0-9]* seconds//' | "
                "sed 's/\\[ethernet\\]//;s/\\[vlan\\]//' | "
                "awk '{printf \"%-18s  %-20s  %-16s  %-8s\\n\", $1, $2, $3, ($4==\"PERM\"?\"PERM\":\"DYN\")}' | "
                "sort -t. -k1,1n -k2,2n -k3,3n -k4,4n;"
                "echo \"\";"
                "echo \"=== SUMMARY === \";"
                "total=$(arp -an | wc -l | tr -d ' ');"
                "perm=$(arp -an | grep -c 'permanent');"
                "dyn=$((total - perm));"
                "printf 'Total: %s  |  Permanent: %s  |  Dynamic: %s\\n' \"$total\" \"$perm\" \"$dyn\";"
                "echo \"\";"
                "echo \"=== BY INTERFACE === \";"
                "arp -an | awk '{for(i=1;i<=NF;i++) if($i==\"on\") print $(i+1)}' | sort | uniq -c | sort -rn | "
                "awk '{printf \"  %-16s  %s entries\\n\", $2, $1}'"
            ),
            "services": (
                "echo \"=== RUNNING SERVICES === \";"
                "for svc in sshd unbound dhcpd ntpd dpinger filterdns syslogd; do "
                "  pid=$(pgrep -x $svc 2>/dev/null); "
                "  [ -n \"$pid\" ] && printf '  %-12s RUNNING (PID %s)\\n' \"$svc\" \"$pid\" || printf '  %-12s STOPPED\\n' \"$svc\"; "
                "done"
            ),
            "log": (
                "echo \"=== RECENT FIREWALL LOG (last 30) === \";"
                "tail -30 /var/log/filter.log 2>/dev/null || echo Log_unavailable"
            ),
            "dhcp": (
                "echo \"=== DHCP LEASES === \";"
                "cat /var/dhcpd/var/db/dhcpd.leases 2>/dev/null | grep -E 'lease|starts|ends|hardware|client-hostname' | head -60 || echo No_DHCP_leases"
            ),
            "gateway_monitor": (
                "echo \"=== GATEWAY STATUS === \";"
                "pfctl -s info 2>/dev/null | grep -i status | head -2; "
                "echo \"\";echo \"=== DPINGER (latency/loss) === \";"
                "cat /tmp/dpinger_*.sock 2>/dev/null || echo dpinger_unavailable; "
                "echo \"\";echo \"=== WAN INTERFACES === \";"
                "netstat -rn | grep default; "
                "echo \"\";echo \"=== PING TEST === \";"
                "ping -c 3 -t 3 1.1.1.1 2>/dev/null | tail -3 || echo Ping_failed"
            ),
            "dns": (
                "echo \"=== UNBOUND STATUS === \";"
                "unbound-control status 2>/dev/null | head -10 || echo Unbound_not_running; "
                "echo \"\";echo \"=== CACHE STATS === \";"
                "unbound-control stats_noreset 2>/dev/null | grep -E 'total.num|cache.count|num.query' | head -15 || echo Stats_unavailable; "
                "echo \"\";echo \"=== DNS TEST === \";"
                "drill google.com @127.0.0.1 2>/dev/null | grep -E 'rcode|ANSWER|Query time' | head -5 || "
                "host google.com 127.0.0.1 2>/dev/null | head -3 || echo DNS_test_failed"
            ),
            "traffic": (
                "echo \"=== INTERFACE TRAFFIC === \";"
                "netstat -ibnd | head -1; netstat -ibnd | grep -v lo0 | grep Link | head -20; "
                "echo \"\";echo \"=== TOP CONNECTIONS BY STATE === \";"
                "pfctl -ss 2>/dev/null | awk '{print $4}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -15; "
                "echo \"\";echo \"=== BANDWIDTH (bytes in/out per interface) === \";"
                "netstat -I lagg0 -bnd 2>/dev/null | tail -1; "
                "netstat -I lagg1 -bnd 2>/dev/null | tail -1"
            ),
            "syslog": (
                "echo \"=== SYSTEM LOG (last 40) === \";"
                "tail -40 /var/log/system.log 2>/dev/null || tail -40 /var/log/messages 2>/dev/null || echo Log_unavailable"
            ),
            "aliases": (
                "echo \"=== PF TABLES (aliases) === \";"
                "pfctl -s Tables 2>/dev/null; "
                "echo \"\";echo \"=== TABLE CONTENTS === \";"
                "for tbl in $(pfctl -s Tables 2>/dev/null); do "
                "  cnt=$(pfctl -t $tbl -T show 2>/dev/null | wc -l | tr -d ' '); "
                "  echo \"$tbl ($cnt entries)\"; "
                "  pfctl -t $tbl -T show 2>/dev/null | head -10; "
                "  echo \"\";"
                "done"
            ),
            "backup": (
                "echo \"=== CONFIG BACKUP === \";"
                "ls -la /cf/conf/backup/ 2>/dev/null | tail -10 || echo No_backups_found; "
                "echo \"\";echo \"=== CURRENT CONFIG === \";"
                "ls -la /cf/conf/config.xml 2>/dev/null; "
                "echo \"\";echo \"=== LAST MODIFIED === \";"
                "stat -f '%Sm' /cf/conf/config.xml 2>/dev/null || stat -c '%y' /cf/conf/config.xml 2>/dev/null || echo Unknown"
            ),
        }

        cmd = actions.get(action, actions["status"])
        r = ssh_single(host=pf_ip, command=cmd, key_path=cfg.ssh_key_path,
                        command_timeout=15,
                        htype="pfsense", use_sudo=False, cfg=cfg)

        self._json_response({
            "action": action,
            "host": pf_ip,
            "reachable": r.returncode == 0,
            "output": r.stdout if r.returncode == 0 else "",
            "error": r.stderr[:100] if r.returncode != 0 else "",
        })

    def _serve_truenas(self):
        """TrueNAS data via SSH/midclt.

        midclt returns JSON — we parse it HERE, not on the remote host.
        This avoids the quoting nightmare of inline Python through sudo sh -c.
        """

        cfg = load_config()
        params = _parse_query(self)
        action = params.get("action", ["status"])[0]

        tn_ip = cfg.truenas_ip
        if not tn_ip:
            self._json_response({"error": "TrueNAS IP not configured", "data": {}})
            return

        # Shell-only actions (no midclt piping, work fine through sudo sh -c)
        shell_actions = {
            "pools": (
                "echo \"=== ZFS POOLS === \";"
                "printf '%-14s  %8s  %8s  %8s  %5s  %5s  %-8s\\n' 'NAME' 'SIZE' 'ALLOC' 'FREE' 'FRAG' 'CAP' 'HEALTH';"
                "printf '%-14s  %8s  %8s  %8s  %5s  %5s  %-8s\\n' '──────────────' '────────' '────────' '────────' '─────' '─────' '────────';"
                "zpool list -o name,size,alloc,free,frag,cap,health -H 2>/dev/null | "
                "awk '{printf \"%-14s  %8s  %8s  %8s  %5s  %5s  %-8s\\n\", $1,$2,$3,$4,$5,$6,$7}';"
                "echo \"\";echo \"=== SUMMARY === \";"
                "total=$(zpool list -H -o name 2>/dev/null | wc -l | tr -d ' ');"
                "healthy=$(zpool list -H -o health 2>/dev/null | grep -c 'ONLINE');"
                "printf 'Pools: %s  |  Healthy: %s\\n' \"$total\" \"$healthy\""
            ),
            "health": (
                "echo \"=== POOL HEALTH === \";"
                "zpool status 2>/dev/null | awk '{"
                "  if(/pool:/){pool=$2}"
                "  if(/state:/){state=$2; printf \"%-14s  %s\\n\", pool, state}"
                "  if(/errors:/){print \"  \" $0}"
                "}';"
                "echo \"\";echo \"=== DETAILED STATUS === \";"
                "zpool status 2>/dev/null | grep -E 'pool:|state:|status:|action:|scan:|config:|errors:|NAME|ONLINE|DEGRADED|FAULTED|UNAVAIL|REMOVED' | head -40"
            ),
            "datasets": (
                "echo \"=== ZFS DATASETS === \";"
                "printf '%-40s  %8s  %8s  %8s  %s\\n' 'NAME' 'USED' 'AVAIL' 'REFER' 'MOUNTPOINT';"
                "printf '%-40s  %8s  %8s  %8s  %s\\n' '────────────────────────────────────────' '────────' '────────' '────────' '──────────';"
                "zfs list -o name,used,avail,refer,mountpoint 2>/dev/null | tail -n +2 | "
                "awk '{printf \"%-40s  %8s  %8s  %8s  %s\\n\", $1,$2,$3,$4,$5}' | head -30;"
                "echo \"\";echo \"=== SUMMARY === \";"
                "total=$(zfs list -H 2>/dev/null | wc -l | tr -d ' ');"
                "printf 'Total datasets: %s\\n' \"$total\""
            ),
            "snapshots": (
                "echo \"=== ZFS SNAPSHOTS (recent 30) === \";"
                "printf '%-50s  %8s  %s\\n' 'NAME' 'USED' 'CREATED';"
                "printf '%-50s  %8s  %s\\n' '──────────────────────────────────────────────────' '────────' '───────────────────';"
                "zfs list -t snapshot -o name,used,creation -s creation 2>/dev/null | tail -n +2 | tail -30 | "
                "awk '{printf \"%-50s  %8s  %s %s %s %s %s\\n\", $1,$2,$3,$4,$5,$6,$7}';"
                "echo \"\";echo \"=== SUMMARY === \";"
                "total=$(zfs list -t snapshot -H 2>/dev/null | wc -l | tr -d ' ');"
                "printf 'Total snapshots: %s\\n' \"$total\""
            ),
            "syslog": (
                "echo \"=== SYSTEM LOG (last 40) === \";"
                "tail -40 /var/log/messages 2>/dev/null | cut -c1-200 || journalctl --no-pager -n 40 2>/dev/null || echo Log_unavailable"
            ),
        }

        # midclt actions — get raw JSON, format locally
        midclt_actions = {
            "status": "midclt call system.info",
            "shares_smb": "midclt call sharing.smb.query '[]'",
            "shares_nfs": "midclt call sharing.nfs.query '[]'",
            "alerts": "midclt call alert.list",
            "smart": "midclt call disk.query '[]'",
            "replication": "midclt call replication.query '[]'",
            "services": "midclt call service.query '[]'",
            "network_ifaces": "midclt call interface.query '[]'",
        }

        # Handle shell-only actions directly
        if action in shell_actions:
            cmd = shell_actions[action]
            r = ssh_single(host=tn_ip, command=cmd, key_path=cfg.ssh_key_path,
                            command_timeout=30,
                            htype="truenas", use_sudo=True, cfg=cfg)
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r.returncode == 0,
                "output": r.stdout if r.returncode == 0 else "",
                "error": r.stderr[:100] if r.returncode != 0 else "",
            })
            return

        # Handle midclt actions — fetch raw JSON, format locally
        def _ssh(cmd):
            return ssh_single(host=tn_ip, command=cmd, key_path=cfg.ssh_key_path,
                              command_timeout=30,
                              htype="truenas", use_sudo=True, cfg=cfg)

        def _parse(raw):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return None

        if action == "status":
            # System info + uptime + memory
            r1 = _ssh("midclt call system.info; echo \"|||\"; uptime; echo \"|||\"; free -h | head -2")
            parts = r1.stdout.split("|||")
            lines = []
            lines.append("=== SYSTEM INFO ===")
            d = _parse(parts[0].strip()) if len(parts) > 0 else None
            if d and isinstance(d, dict):
                up_s = int(d.get("uptime_seconds", 0))
                # TrueNAS returns dates as {"$date": epoch_ms} or ISO strings
                def _fmt_date(val):
                    if isinstance(val, dict) and "$date" in val:
                        try:
                            return datetime.datetime.fromtimestamp(val["$date"] / 1000).strftime("%Y-%m-%d %H:%M")
                        except (OSError, ValueError):
                            return "?"
                    return str(val)[:19] if val else "?"
                fields = [
                    ("Hostname", d.get("hostname", "?")),
                    ("Version", d.get("version", "?")),
                    ("Build", _fmt_date(d.get("buildtime"))),
                    ("Uptime", f"{up_s // 86400}d {up_s % 86400 // 3600}h"),
                    ("Model", str(d.get("system_product", "?"))),
                    ("Serial", str(d.get("system_serial", "?"))),
                    ("CPU", str(d.get("cores", "?")) + " cores"),
                    ("RAM", f"{round(d.get('physmem', 0) / 1073741824, 1)}GB"),
                    ("Boot", _fmt_date(d.get("boottime"))),
                ]
                ml = max(len(k) for k, _ in fields)
                for k, v in fields:
                    lines.append(f"  {k:<{ml + 1}s} {v}")
            else:
                lines.append("  (midclt unavailable)")
            lines.append("")
            lines.append("=== LOAD ===")
            lines.append(parts[1].strip() if len(parts) > 1 else "unavailable")
            lines.append("")
            lines.append("=== MEMORY ===")
            lines.append(parts[2].strip() if len(parts) > 2 else "unavailable")
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r1.returncode == 0,
                "output": "\n".join(lines),
                "error": "",
            })

        elif action == "shares":
            r_smb = _ssh("midclt call sharing.smb.query '[]'")
            r_nfs = _ssh("midclt call sharing.nfs.query '[]'")
            lines = ["=== SMB SHARES ==="]
            smb = _parse(r_smb.stdout)
            if smb and isinstance(smb, list):
                lines.append(f"{'NAME':<20s}  {'PATH':<40s}  {'ENABLED':<8s}  COMMENT")
                lines.append("─" * 20 + "  " + "─" * 40 + "  " + "─" * 8 + "  " + "─" * 20)
                for s in smb:
                    en = "YES" if s.get("enabled") else "NO"
                    lines.append(f"{s.get('name', '?'):<20s}  {s.get('path', '?'):<40s}  {en:<8s}  {s.get('comment', '')}")
                lines.append(f"\n=== SUMMARY ===\nTotal: {len(smb)}  |  Enabled: {sum(1 for s in smb if s.get('enabled'))}")
            else:
                lines.append("  No SMB shares or midclt unavailable")
            lines.append("")
            lines.append("=== NFS SHARES ===")
            nfs = _parse(r_nfs.stdout)
            if nfs and isinstance(nfs, list):
                for s in nfs:
                    paths = ", ".join(s.get("paths", [])) or s.get("path", "?")
                    nets = ", ".join(s.get("networks", [])) or "*"
                    en = "YES" if s.get("enabled") else "NO"
                    lines.append(f"  {paths}  ({nets})  enabled={en}")
            else:
                lines.append("  No NFS shares or midclt unavailable")
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r_smb.returncode == 0 or r_nfs.returncode == 0,
                "output": "\n".join(lines),
                "error": "",
            })

        elif action == "alerts":
            r = _ssh("midclt call alert.list")
            lines = ["=== ACTIVE ALERTS ==="]
            alerts = _parse(r.stdout)
            if alerts is not None and isinstance(alerts, list):
                if not alerts:
                    lines.append("  No active alerts — all clear")
                else:
                    by_level = {}
                    for a in alerts:
                        lv = a.get("level", "UNKNOWN")
                        by_level[lv] = by_level.get(lv, 0) + 1
                    lines.append("\n=== SUMMARY ===")
                    parts = [f"{k}: {v}" for k, v in sorted(by_level.items())]
                    lines.append(f"Total: {len(alerts)}  |  {'  |  '.join(parts)}")
                    lines.append("\n=== DETAILS ===")
                    for a in alerts[:15]:
                        lv = a.get("level", "?")[:8]
                        cat = a.get("klass", "?").split(".")[-1][:20]
                        msg = (a.get("formatted") or str(a.get("args", "?")))[:80]
                        lines.append(f"  [{lv:<8s}] {cat:<20s}  {msg}")
            else:
                lines.append("  midclt unavailable")
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r.returncode == 0,
                "output": "\n".join(lines),
                "error": "",
            })

        elif action == "smart":
            r_disks = _ssh("midclt call disk.query '[]'")
            r_pool = _ssh("zpool status 2>/dev/null | grep -E 'NAME|ONLINE|DEGRADED|FAULTED|state:|errors:' | head -30")
            lines = ["=== DISK INVENTORY ==="]
            lines.append(f"{'DISK':<6s}  {'MODEL':<25s}  {'SERIAL':<14s}  {'SIZE':>7s}  TEMP")
            lines.append("─" * 6 + "  " + "─" * 25 + "  " + "─" * 14 + "  " + "─" * 7 + "  " + "─" * 4)
            disks = _parse(r_disks.stdout)
            if disks and isinstance(disks, list):
                for d in sorted(disks, key=lambda x: x.get("name", "")):
                    name = d.get("name", "?")
                    model = d.get("model", "?")[:25]
                    serial = d.get("serial", "?")[:14]
                    size = d.get("size", 0) // 1073741824
                    temp = f"{d.get('temperature', '?')}C" if d.get("temperature") else "-"
                    lines.append(f"{name:<6s}  {model:<25s}  {serial:<14s}  {size:>5d}GB  {temp}")
                total_tb = sum(d.get("size", 0) for d in disks) / 1099511627776
                lines.append(f"\n=== SUMMARY ===\nDisks: {len(disks)}  |  Raw capacity: {total_tb:.1f}TB")
            else:
                lines.append("  midclt unavailable")
            lines.append("\n=== POOL DISK STATUS ===")
            lines.append(r_pool.stdout if r_pool.returncode == 0 else "unavailable")
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r_disks.returncode == 0,
                "output": "\n".join(lines),
                "error": "",
            })

        elif action == "replication":
            r = _ssh("midclt call replication.query '[]'")
            lines = ["=== REPLICATION TASKS ==="]
            tasks = _parse(r.stdout)
            if tasks is not None and isinstance(tasks, list):
                if not tasks:
                    lines.append("  No replication tasks configured")
                for t in tasks:
                    name = t.get("name", "?")
                    src = t.get("source_datasets", ["?"])
                    dst = t.get("target_dataset", "?")
                    state = t.get("state", {}).get("state", "?") if isinstance(t.get("state"), dict) else "?"
                    enabled = "YES" if t.get("enabled") else "NO"
                    sched = t.get("auto", False)
                    lines.append(f"  {name}")
                    lines.append(f"    Source:  {', '.join(src) if isinstance(src, list) else src}")
                    lines.append(f"    Target:  {dst}")
                    lines.append(f"    State:   {state}  |  Enabled: {enabled}  |  Auto: {sched}")
                    lines.append("")
            else:
                lines.append("  midclt unavailable")
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r.returncode == 0,
                "output": "\n".join(lines),
                "error": "",
            })

        elif action == "services":
            r = _ssh("midclt call service.query '[]'")
            lines = ["=== TRUENAS SERVICES ==="]
            lines.append(f"{'SERVICE':<20s}  {'STATE':<10s}  {'ENABLED':<8s}")
            lines.append("─" * 20 + "  " + "─" * 10 + "  " + "─" * 8)
            svcs = _parse(r.stdout)
            if svcs and isinstance(svcs, list):
                svcs_sorted = sorted(svcs, key=lambda s: s.get("service", ""))
                run = stop = 0
                for s in svcs_sorted:
                    name = s.get("service", "?")
                    state = "RUNNING" if s.get("state") == "RUNNING" else "STOPPED"
                    enabled = "YES" if s.get("enable") else "NO"
                    if state == "RUNNING":
                        run += 1
                    else:
                        stop += 1
                    lines.append(f"{name:<20s}  {state:<10s}  {enabled:<8s}")
                lines.append(f"\n=== SUMMARY ===\nTotal: {len(svcs_sorted)}  |  Running: {run}  |  Stopped: {stop}")
            else:
                lines.append("  midclt unavailable")
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r.returncode == 0,
                "output": "\n".join(lines),
                "error": "",
            })

        elif action == "network":
            r_ifaces = _ssh("midclt call interface.query '[]'")
            r_routes = _ssh("netstat -rn 2>/dev/null | grep default | head -5 || ip route show default 2>/dev/null")
            lines = ["=== NETWORK INTERFACES ==="]
            lines.append(f"{'NAME':<12s}  {'TYPE':<10s}  {'STATE':<8s}  IP ADDRESSES")
            lines.append("─" * 12 + "  " + "─" * 10 + "  " + "─" * 8 + "  " + "─" * 20)
            ifaces = _parse(r_ifaces.stdout)
            if ifaces and isinstance(ifaces, list):
                for i in sorted(ifaces, key=lambda x: x.get("name", "")):
                    name = i.get("name", "?")
                    itype = i.get("type", "?")
                    state_obj = i.get("state", {})
                    state = "UP" if isinstance(state_obj, dict) and state_obj.get("link_state", "") == "LINK_STATE_UP" else "DOWN"
                    ips = ", ".join(
                        a["address"] + "/" + str(a.get("netmask", ""))
                        for a in i.get("aliases", [])
                        if a.get("type") == "INET"
                    ) or "-"
                    lines.append(f"{name:<12s}  {itype:<10s}  {state:<8s}  {ips}")
                up = sum(1 for i in ifaces if isinstance(i.get("state"), dict) and i["state"].get("link_state", "") == "LINK_STATE_UP")
                lines.append(f"\n=== SUMMARY ===\nInterfaces: {len(ifaces)}  |  Link up: {up}")
            else:
                lines.append("  midclt unavailable")
            lines.append("\n=== ROUTING ===")
            lines.append(r_routes.stdout if r_routes.returncode == 0 else "unavailable")
            self._json_response({
                "action": action, "host": tn_ip,
                "reachable": r_ifaces.returncode == 0,
                "output": "\n".join(lines),
                "error": "",
            })

        else:
            # Unknown action — try status
            self._serve_truenas()

    def _serve_idrac(self):
        """iDRAC data via SSH/racadm."""


        cfg = load_config()
        params = _parse_query(self)
        action = params.get("action", ["status"])[0]
        target = params.get("target", [""])[0]

        # Build iDRAC targets from fleet boundaries config
        fb = cfg.fleet_boundaries
        targets = {}
        for key, dev in fb.physical.items():
            if dev.device_type == "idrac":
                targets[dev.label] = dev.ip

        if target:
            # Match by label or key
            matched = {k: v for k, v in targets.items() if target.lower() in k.lower()}
            idrac_ips = matched if matched else targets
        else:
            idrac_ips = targets

        # iDRAC SSH gives a racadm console, NOT a shell.
        # No pipes, redirects, ||, or shell syntax — just bare racadm commands.
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

        self._json_response({"action": action, "targets": results})

    def _serve_infra_quick(self):
        """Infra device summary — served from background cache, always instant."""
        with _bg_lock:
            cached = _bg_cache.get("infra_quick")
        if cached:
            cached["cached"] = True
            cached["age"] = round(time.time() - _bg_cache_ts.get("infra_quick", 0), 1)
            self._json_response(cached)
            return
        # Fallback: no cache yet — return empty with flag
        self._json_response({"devices": [], "duration": 0, "warming": True})
        return

    def _serve_vm_create(self):

        cfg = load_config()
        params = _parse_query(self)
        name = params.get("name", [""])[0]
        cores = int(params.get("cores", ["2"])[0])
        ram = int(params.get("ram", ["2048"])[0])
        if not name:
            self._json_response({"error": "Name required"}); return
        if not valid_label(name):
            self._json_response({"error": "Invalid VM name (alphanumeric + hyphens only)"}); return
        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return
            stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
            if not ok:
                self._json_response({"error": "Cannot allocate VMID"}); return
            vmid = int(stdout.strip())
            lab_cat = cfg.fleet_boundaries.categories.get("lab", {})
            vmid_floor = lab_cat.get("range_start", 5000)
            if vmid < vmid_floor: vmid = vmid_floor
            cmd = f"qm create {vmid} --name {name} --cores {cores} --memory {ram} --cpu {cfg.vm_cpu} --machine {cfg.vm_machine} --net0 virtio,bridge={cfg.nic_bridge} --scsihw {cfg.vm_scsihw}"
            stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
            self._json_response({"ok": ok, "vmid": vmid, "name": name, "error": stdout if not ok else ""})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_destroy(self):

        cfg = load_config()
        params = _parse_query(self)
        vmid = int(params.get("vmid", ["0"])[0])
        # Fleet boundary check — only admin-tier VMs can be destroyed
        allowed, err = _check_vm_permission(cfg, vmid, "destroy")
        if not allowed:
            self._json_response({"error": err}); return
        if is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges):
            self._json_response({"error": f"VMID {vmid} is PROTECTED"}); return
        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return
            _pve_cmd(cfg, node_ip, f"qm stop {vmid} --skiplock", timeout=30)
            stdout, ok = _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=120)
            self._json_response({"ok": ok, "vmid": vmid, "error": stdout if not ok else ""})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_snapshot(self):

        cfg = load_config()
        params = _parse_query(self)
        vmid = int(params.get("vmid", ["0"])[0])
        snap_name = params.get("name", [f"freq-snap-{vmid}"])[0]
        if not valid_label(snap_name):
            self._json_response({"error": "Invalid snapshot name (alphanumeric + hyphens only)"}); return
        # Fleet boundary check
        allowed, err = _check_vm_permission(cfg, vmid, "snapshot")
        if not allowed:
            self._json_response({"error": err}); return
        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return
            stdout, ok = _pve_cmd(cfg, node_ip, f"qm snapshot {vmid} {snap_name}", timeout=120)
            self._json_response({"ok": ok, "vmid": vmid, "snapshot": snap_name, "error": stdout if not ok else ""})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_resize(self):

        cfg = load_config()
        params = _parse_query(self)
        vmid = int(params.get("vmid", ["0"])[0])
        cores = params.get("cores", [None])[0]
        ram = params.get("ram", [None])[0]
        # Fleet boundary check
        allowed, err = _check_vm_permission(cfg, vmid, "resize")
        if not allowed:
            self._json_response({"error": err}); return
        parts = []
        if cores:
            try: cores = int(cores)
            except ValueError:
                self._json_response({"error": "Invalid cores value"}); return
            parts.append(f"--cores {cores}")
        if ram:
            try: ram = int(ram)
            except ValueError:
                self._json_response({"error": "Invalid ram value"}); return
            parts.append(f"--memory {ram}")
        if not parts:
            self._json_response({"error": "Specify cores or ram"}); return
        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return
            stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} {' '.join(parts)}")
            self._json_response({"ok": ok, "vmid": vmid, "error": stdout if not ok else ""})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_power(self):

        cfg = load_config()
        params = _parse_query(self)
        vmid = int(params.get("vmid", ["0"])[0])
        action = params.get("action", ["status"])[0]
        # Fleet boundary check — power actions require start/stop permission
        if action in ("start", "stop", "reset"):
            perm_action = "start" if action == "start" else "stop"
            allowed, err = _check_vm_permission(cfg, vmid, perm_action)
            if not allowed:
                self._json_response({"error": err}); return
        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return
            cmds = {"start": f"qm start {vmid}", "stop": f"qm stop {vmid}", "reset": f"qm reset {vmid}",
                    "status": f"qm status {vmid}"}
            cmd = cmds.get(action, cmds["status"])
            stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=60)
            self._json_response({"ok": ok, "vmid": vmid, "action": action, "output": stdout, "error": "" if ok else stdout})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vault(self):
        cfg = load_config()
        if not os.path.exists(cfg.vault_file):
            self._json_response({"entries": [], "initialized": False}); return
        entries = vault_list(cfg)
        safe = [{"host": h, "key": k, "masked": "********" if any(w in k.lower() for w in ["pass","secret","token","key"]) else v[:20]}
                for h, k, v in entries]
        self._json_response({"entries": safe, "initialized": True, "count": len(entries)})

    def _serve_vault_set(self):

        cfg = load_config()
        params = _parse_query(self)
        key = params.get("key", [""])[0]
        value = params.get("value", [""])[0]
        host = params.get("host", ["DEFAULT"])[0]
        if not key or not value:
            self._json_response({"error": "Key and value required"}); return
        if not os.path.exists(cfg.vault_file):
            vault_init(cfg)
        ok = vault_set(cfg, host, key, value)
        self._json_response({"ok": ok, "key": key, "host": host})

    def _serve_vault_delete(self):

        cfg = load_config()
        params = _parse_query(self)
        key = params.get("key", [""])[0]
        host = params.get("host", ["DEFAULT"])[0]
        ok = vault_delete(cfg, host, key)
        self._json_response({"ok": ok, "key": key, "host": host})

    def _serve_users(self):
        cfg = load_config()
        users = _load_users(cfg)
        self._json_response({"users": users, "count": len(users), "roles": ROLE_HIERARCHY})

    def _serve_user_create(self):

        cfg = load_config()
        params = _parse_query(self)
        username = params.get("username", [""])[0]
        role = params.get("role", ["operator"])[0]
        if not username:
            self._json_response({"error": "Username required"}); return
        users = _load_users(cfg)
        if any(u["username"] == username for u in users):
            self._json_response({"error": f"User '{username}' already exists"}); return
        users.append({"username": username, "role": role, "groups": ""})
        ok = _save_users(cfg, users)
        self._json_response({"ok": ok, "username": username, "role": role})

    def _serve_user_promote(self):

        cfg = load_config()
        params = _parse_query(self)
        username = params.get("username", [""])[0]
        users = _load_users(cfg)
        user = next((u for u in users if u["username"] == username), None)
        if not user:
            self._json_response({"error": f"User not found: {username}"}); return
        lvl = _role_level(user["role"])
        if lvl >= _role_level("admin"):
            self._json_response({"error": "Already at max role"}); return
        old = user["role"]
        user["role"] = ROLE_HIERARCHY[lvl + 1]
        _save_users(cfg, users)
        self._json_response({"ok": True, "username": username, "old": old, "new": user["role"]})

    def _serve_user_demote(self):

        cfg = load_config()
        params = _parse_query(self)
        username = params.get("username", [""])[0]
        users = _load_users(cfg)
        user = next((u for u in users if u["username"] == username), None)
        if not user:
            self._json_response({"error": f"User not found: {username}"}); return
        lvl = _role_level(user["role"])
        if lvl <= 0:
            self._json_response({"error": "Already at min role"}); return
        old = user["role"]
        user["role"] = ROLE_HIERARCHY[lvl - 1]
        _save_users(cfg, users)
        self._json_response({"ok": True, "username": username, "old": old, "new": user["role"]})

    def _serve_keys(self):
        cfg = load_config()
        results = ssh_run_many(hosts=cfg.hosts, command="cat ~/.ssh/authorized_keys 2>/dev/null | wc -l",
                           key_path=cfg.ssh_key_path, connect_timeout=3, command_timeout=5,
                           max_parallel=10, use_sudo=False, cfg=cfg)
        keys = []
        for h in cfg.hosts:
            r = results.get(h.label)
            keys.append({"host": h.label, "ip": h.ip, "reachable": r is not None and r.returncode == 0,
                         "key_count": int(r.stdout.strip()) if r and r.returncode == 0 and r.stdout.strip().isdigit() else 0})
        self._json_response({"hosts": keys, "ssh_key": cfg.ssh_key_path})

    def _serve_journal(self):
        cfg = load_config()
        path = os.path.join(cfg.data_dir, "log", "journal.jsonl")
        entries = []
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    try: entries.append(json.loads(line.strip()))
                    except (json.JSONDecodeError, ValueError): pass
        self._json_response({"entries": entries[-50:], "count": len(entries)})

    def _serve_config(self):
        cfg = load_config()
        self._json_response({
            "version": cfg.version, "brand": cfg.brand, "build": cfg.build,
            "ssh_account": cfg.ssh_service_account, "ssh_timeout": cfg.ssh_connect_timeout,
            "ssh_parallel": cfg.ssh_max_parallel, "pve_nodes": cfg.pve_nodes,
            "cluster": cfg.cluster_name, "timezone": cfg.timezone,
            "truenas_ip": cfg.truenas_ip, "pfsense_ip": cfg.pfsense_ip,
            "install_dir": cfg.install_dir, "hosts_count": len(cfg.hosts),
            "vlans_count": len(cfg.vlans), "distros_count": len(cfg.distros),
            "protected_vmids": cfg.protected_vmids,
            "kill_chain": _load_kill_chain(cfg) or ["Operator", "VPN", "Firewall", "Switch", "Network", "Target"],
            # Notification provider status (booleans only — no secrets)
            "discord_webhook": bool(cfg.discord_webhook),
            "slack_webhook": bool(cfg.slack_webhook),
            "telegram_bot_token": bool(cfg.telegram_bot_token),
            "telegram_chat_id": bool(cfg.telegram_chat_id),
            "smtp_host": bool(cfg.smtp_host),
            "smtp_to": bool(cfg.smtp_to),
            "ntfy_url": bool(cfg.ntfy_url),
            "ntfy_topic": bool(cfg.ntfy_topic),
            "gotify_url": bool(cfg.gotify_url),
            "gotify_token": bool(cfg.gotify_token),
            "pushover_user": bool(cfg.pushover_user),
            "pushover_token": bool(cfg.pushover_token),
            "webhook_url": bool(cfg.webhook_url),
        })

    def _serve_distros(self):
        cfg = load_config()
        distros = [{"key": d.key, "name": d.name, "family": d.family, "tier": d.tier,
                     "url": d.url} for d in cfg.distros]
        self._json_response({"distros": distros, "count": len(distros)})

    def _serve_groups(self):
        cfg = load_config()
        groups = {g: [h.label for h in hosts] for g, hosts in res.all_groups(cfg.hosts).items()}
        self._json_response({"groups": groups})

    def _serve_harden(self):

        cfg = load_config()
        params = _parse_query(self)
        target = params.get("target", ["all"])[0]
        if target == "all":
            hosts = cfg.hosts
        else:
            h = res.by_target(cfg.hosts, target)
            hosts = [h] if h else []
        checks = [
            ("PasswordAuth", "grep -c '^PasswordAuthentication no' /etc/ssh/sshd_config 2>/dev/null || echo 0",
             "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config"),
            ("RootLogin", "grep -c '^PermitRootLogin prohibit-password' /etc/ssh/sshd_config 2>/dev/null || echo 0",
             "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config"),
            ("EmptyPasswd", "grep -c '^PermitEmptyPasswords no' /etc/ssh/sshd_config 2>/dev/null || echo 0",
             "sed -i 's/^#*PermitEmptyPasswords.*/PermitEmptyPasswords no/' /etc/ssh/sshd_config"),
        ]
        results = []
        for name, check_cmd, _ in checks:
            r = ssh_run_many(hosts=hosts, command=check_cmd, key_path=cfg.ssh_key_path,
                         connect_timeout=3, command_timeout=10, max_parallel=10, use_sudo=True)
            for h in hosts:
                res = r.get(h.label)
                ok = res and res.returncode == 0 and res.stdout.strip() != "0"
                results.append({"host": h.label, "check": name, "ok": ok})
        self._json_response({"results": results, "hosts": len(hosts)})

    def _serve_agent_create(self):

        cfg = load_config()
        params = _parse_query(self)
        template = params.get("template", ["blank"])[0]
        name = params.get("name", [template])[0]
        if not valid_label(name):
            self._json_response({"error": "Invalid agent name (alphanumeric + hyphens only)"}); return
        agents = _load_agents(cfg)
        if name in agents:
            self._json_response({"error": f"Agent '{name}' already exists"}); return
        tmpl = TEMPLATES.get(template, TEMPLATES.get("blank"))
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            self._json_response({"error": "No PVE node reachable"}); return
        stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
        if not ok:
            self._json_response({"error": "Cannot allocate VMID"}); return
        lab_cat = cfg.fleet_boundaries.categories.get("lab", {})
        vmid_floor = lab_cat.get("range_start", 5000)
        vmid = max(int(stdout.strip()), vmid_floor)
        cmd = f"qm create {vmid} --name {name} --cores {tmpl['cores']} --memory {tmpl['ram']} --cpu {cfg.vm_cpu} --machine {cfg.vm_machine} --net0 virtio,bridge={cfg.nic_bridge} --scsihw {cfg.vm_scsihw}"
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
        if not ok:
            self._json_response({"error": f"VM creation failed: {stdout[:60]}"}); return
        agents[name] = {"name": name, "template": template, "vmid": vmid, "node": node_ip,
                         "status": "created", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "cores": tmpl["cores"], "ram": tmpl["ram"], "disk": tmpl["disk"]}
        _save_agents(cfg, agents)
        md_dir = os.path.join(cfg.data_dir, "jarvis", "agents", name)
        os.makedirs(md_dir, exist_ok=True)
        with open(os.path.join(md_dir, "CLAUDE.md"), "w") as f:
            f.write(tmpl["claude_md"].format(name=name))
        self._json_response({"ok": True, "name": name, "vmid": vmid, "template": template})

    def _serve_agent_destroy(self):

        cfg = load_config()
        params = _parse_query(self)
        name = params.get("name", [""])[0]
        agents = _load_agents(cfg)
        if name not in agents:
            self._json_response({"error": f"Agent not found: {name}"}); return
        vmid = agents[name].get("vmid")
        if vmid:
            node_ip = _find_reachable_node(cfg)
            if node_ip:
                _pve_cmd(cfg, node_ip, f"qm stop {vmid} --skiplock", timeout=30)
                _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=120)
        del agents[name]
        _save_agents(cfg, agents)
        md_dir = os.path.join(cfg.data_dir, "jarvis", "agents", name)
        if os.path.isdir(md_dir): shutil.rmtree(md_dir)
        self._json_response({"ok": True, "name": name, "vmid": vmid})

    def _serve_deploy_agent(self):
        self._json_response({"message": "Run from CLI: freq deploy-agent <host|all>",
                              "note": "Requires sudo on target hosts"})

    def _serve_switch(self):

        cfg = load_config()
        params = _parse_query(self)
        action = params.get("action", ["status"])[0]
        switch_ip = cfg.switch_ip
        if not switch_ip:
            self._json_response({"error": "No switch_ip configured in freq.toml [infrastructure]"}, 400)
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
        self._json_response({"action": action, "host": switch_ip, "reachable": r.returncode == 0,
                              "output": r.stdout if r.returncode == 0 else "", "error": r.stderr[:100] if r.returncode != 0 else ""})

    def _serve_notify_test(self):
        cfg = load_config()
        results = jarvis_notify(cfg, "Test notification from FREQ Web UI", severity="info")
        self._json_response({"results": {k: v for k, v in results.items()},
                              "discord_configured": bool(cfg.discord_webhook),
                              "slack_configured": bool(cfg.slack_webhook)})

    def _serve_infra_overview(self):
        """Full infrastructure overview — physical → hypervisor → VM → OS → containers."""
        cfg = load_config()

        # Gather everything in parallel
        cmd = (
            "echo \"$(hostname)|$(cat /etc/os-release 2>/dev/null | grep -oP '(?<=PRETTY_NAME=\\\").*(?=\\\")' || echo unknown)|"
            "$(nproc)|$(free -m | awk '/Mem:/ {printf \\\"%d/%dMB\\\", $3, $2}')|"
            "$(df -h / | awk 'NR==2 {print $5}')|"
            "$(docker ps -q 2>/dev/null | wc -l)|"
            "$(systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l)\""
        )

        results = ssh_run_many(
            hosts=cfg.hosts, command=cmd, key_path=cfg.ssh_key_path,
            connect_timeout=3, command_timeout=10,
            max_parallel=10, use_sudo=False,
        )

        layers = []
        for h in cfg.hosts:
            r = results.get(h.label)
            if r and r.returncode == 0 and r.stdout:
                parts = r.stdout.split("|")
                layers.append({
                    "label": h.label, "ip": h.ip, "type": h.htype,
                    "status": "up",
                    "hostname": parts[0] if len(parts) > 0 else "?",
                    "os": parts[1] if len(parts) > 1 else "?",
                    "cores": parts[2] if len(parts) > 2 else "?",
                    "ram": parts[3] if len(parts) > 3 else "?",
                    "disk_pct": parts[4] if len(parts) > 4 else "?",
                    "containers": int(parts[5]) if len(parts) > 5 and parts[5].strip().isdigit() else 0,
                    "services": int(parts[6]) if len(parts) > 6 and parts[6].strip().isdigit() else 0,
                })
            else:
                layers.append({
                    "label": h.label, "ip": h.ip, "type": h.htype,
                    "status": "down",
                })

        # PVE cluster info
        pve_info = {"nodes": [], "vms": []}
        for node_ip in cfg.pve_nodes:
            r = ssh_single(host=node_ip,
                           command="pvesh get /cluster/resources --type vm --output-format json 2>/dev/null",
                           key_path=cfg.ssh_key_path, connect_timeout=3,
                           command_timeout=10, htype="pve", use_sudo=True)
            if r.returncode == 0 and r.stdout:
                try:
                    vms = json.loads(r.stdout)
                    for v in vms:
                        pve_info["vms"].append({
                            "vmid": v.get("vmid"), "name": v.get("name", ""),
                            "node": v.get("node", ""), "status": v.get("status", ""),
                            "cpu": v.get("maxcpu", 0),
                            "ram_mb": v.get("maxmem", 0) // (1024 * 1024) if v.get("maxmem") else 0,
                        })
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warn(f"infra overview VM parse failed: {e}")
                break

        # Infrastructure targets status — only include configured devices
        infra = {}
        if cfg.pfsense_ip:
            infra["pfsense"] = {"ip": cfg.pfsense_ip, "status": "unknown"}
        if cfg.truenas_ip:
            infra["truenas"] = {"ip": cfg.truenas_ip, "status": "unknown"}

        self._json_response({
            "hosts": layers,
            "pve": pve_info,
            "infra": infra,
            "cluster": cfg.cluster_name,
        })

    def _serve_risk(self):
        """Risk analysis data via API."""
        cfg = load_config()
        dependencies = _load_risk_map(cfg)
        chain = _load_kill_chain(cfg)
        targets = []
        for key, info in dependencies.items():
            targets.append({
                "name": key,
                "label": info["label"],
                "risk": info["risk"],
                "impact": info["impact"][0] if info["impact"] else "",
                "recovery": info["recovery"],
                "depends_on": info.get("depends_on", []),
                "depended_by": info.get("depended_by", []),
            })
        self._json_response({"targets": targets, "chain": chain})

    # --- Media API Endpoints ---

    def _serve_media_status(self):
        """All containers across all VMs."""
        cfg = load_config()
        containers = []
        for vm in sorted(cfg.container_vms.values(), key=lambda v: v.vm_id):
            r = ssh_single(
                host=vm.ip,
                command="docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null",
                key_path=cfg.ssh_key_path, connect_timeout=3,
                command_timeout=10, htype="docker", use_sudo=False,
            )
            running = {}
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.strip().split("\n"):
                    parts = line.split("|", 1)
                    if len(parts) == 2:
                        running[parts[0].strip()] = parts[1].strip()

            for cname, container in vm.containers.items():
                status = "not found"
                for rn, rs in running.items():
                    if cname.lower() in rn.lower():
                        status = rs
                        break
                containers.append({
                    "name": cname, "vm_id": vm.vm_id, "vm_label": vm.label,
                    "vm_ip": vm.ip, "port": container.port,
                    "status": "up" if "Up" in status else "down",
                    "detail": status,
                })
        self._json_response({"containers": containers, "count": len(containers)})

    def _serve_media_health(self):
        """API health for all media services."""
        cfg = load_config()
        results = []
        skipped = 0
        for vm in sorted(cfg.container_vms.values(), key=lambda v: v.vm_id):
            for cname, container in vm.containers.items():
                if not container.port or not container.api_path:
                    skipped += 1
                    continue
                r = ssh_single(
                    host=vm.ip,
                    command=f"curl -s -o /dev/null -w '%{{http_code}}' "
                            f"--connect-timeout 2 'http://localhost:{container.port}{container.api_path}' "
                            f"2>/dev/null || echo 000",
                    key_path=cfg.ssh_key_path, connect_timeout=3,
                    command_timeout=5, htype="docker", use_sudo=False, cfg=cfg,
                )
                code = r.stdout.strip()[-3:] if r.returncode == 0 else "000"
                healthy = code in ("200", "301", "302")
                results.append({
                    "name": cname, "vm_label": vm.label,
                    "status": "healthy" if healthy else "down",
                    "http_code": code, "port": container.port,
                })
        self._json_response({"services": results, "skipped": skipped})

    def _serve_media_downloads(self):
        """Active downloads from qBit + SABnzbd."""
        cfg = load_config()
        downloads = []
        for vm in cfg.container_vms.values():
            for cname, container in vm.containers.items():
                if "qbittorrent" in cname.lower():
                    # qBit needs session cookie auth — try login first
                    qb_user = vault_get(cfg, "DEFAULT", "qbittorrent_user") or "admin"
                    qb_pass = vault_get(cfg, "DEFAULT", "qbittorrent_password") or ""
                    if not qb_pass:
                        logger.warn("qBittorrent password not in vault — skipping download check")
                        continue
                    r = ssh_single(
                        host=vm.ip,
                        command=f"curl -s -c /tmp/qb.cookie --connect-timeout 3 "
                                f"'http://{vm.ip}:{container.port}/api/v2/auth/login' "
                                f"-d 'username={qb_user}&password={qb_pass}' && "
                                f"curl -s -b /tmp/qb.cookie --connect-timeout 3 "
                                f"'http://{vm.ip}:{container.port}/api/v2/torrents/info?filter=downloading'",
                        key_path=cfg.ssh_key_path, connect_timeout=3,
                        command_timeout=10, htype="docker", use_sudo=False,
                    )
                    if r.returncode == 0:
                        # Response may have "Ok.\n" or "Fails.\n" prefix from login
                        stdout = r.stdout
                        bracket = stdout.find("[")
                        if bracket >= 0:
                            stdout = stdout[bracket:]
                        try:
                            for t in json.loads(stdout):
                                downloads.append({
                                    "name": t.get("name", "?"),
                                    "size": t.get("size", 0),
                                    "progress": round(t.get("progress", 0) * 100),
                                    "speed": t.get("dlspeed", 0),
                                    "client": "qBittorrent",
                                    "vm": vm.label,
                                })
                        except (json.JSONDecodeError, TypeError):
                            pass
                elif "sabnzbd" in cname.lower() and container.port:
                    # SABnzbd uses API key auth
                    api_key = ""
                    try:
                        api_key = vault_get(cfg, "DEFAULT", container.vault_key) or ""
                    except Exception as e:
                        logger.warn(f"vault read failed for {cname}: {e}")
                    r = ssh_single(
                        host=vm.ip,
                        command=f"curl -s --connect-timeout 3 "
                                f"'http://{vm.ip}:{container.port}/api?mode=queue&apikey={api_key}&output=json'",
                        key_path=cfg.ssh_key_path, connect_timeout=3,
                        command_timeout=10, htype="docker", use_sudo=False,
                    )
                    if r.returncode == 0:
                        try:
                            data = json.loads(r.stdout)
                            for s in data.get("queue", {}).get("slots", []):
                                pct = int(float(s.get("percentage", 0)))
                                size_mb = float(s.get("mb", 0)) * 1048576
                                speed_str = data.get("queue", {}).get("speed", "0")
                                speed_val = float(speed_str.replace(" M", "").replace(" K", "").replace(" G", "") or 0)
                                if "M" in speed_str:
                                    speed_val *= 1048576
                                elif "K" in speed_str:
                                    speed_val *= 1024
                                elif "G" in speed_str:
                                    speed_val *= 1073741824
                                downloads.append({
                                    "name": s.get("filename", "?"),
                                    "size": int(size_mb),
                                    "progress": pct,
                                    "speed": int(speed_val),
                                    "client": "SABnzbd",
                                    "vm": vm.label,
                                })
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
        self._json_response({"downloads": downloads, "count": len(downloads)})

    def _serve_media_streams(self):
        """Active Plex streams via Tautulli."""
        cfg = load_config()

        container, vm = res.container_by_name(cfg.container_vms, "tautulli")
        sessions = []
        if container and vm:
            # Get API key from vault
            api_key = ""
            try:
                api_key = vault_get(cfg, "DEFAULT", container.vault_key) or ""
            except Exception as e:
                logger.warn(f"vault read failed for {container.vault_key}: {e}")
            r = ssh_single(
                host=vm.ip,
                command=f"curl -s --connect-timeout 3 "
                        f"'http://{vm.ip}:{container.port}/api/v2?apikey={api_key}&cmd=get_activity'",
                key_path=cfg.ssh_key_path, connect_timeout=3,
                command_timeout=10, htype="docker", use_sudo=False,
            )
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout)
                    for s in data.get("response", {}).get("data", {}).get("sessions", []):
                        sessions.append({
                            "user": s.get("friendly_name", "?"),
                            "title": s.get("full_title", s.get("title", "?")),
                            "type": s.get("media_type", "?"),
                            "quality": s.get("video_resolution", "?"),
                            "state": s.get("state", "?"),
                        })
                except (json.JSONDecodeError, TypeError):
                    pass
        self._json_response({"sessions": sessions, "count": len(sessions)})

    def _serve_media_dashboard(self):
        """Aggregate media dashboard data."""
        cfg = load_config()

        total = 0
        running = 0
        for vm in cfg.container_vms.values():
            r = ssh_single(
                host=vm.ip,
                command="docker ps --format '{{.Names}}' 2>/dev/null | wc -l",
                key_path=cfg.ssh_key_path, connect_timeout=3,
                command_timeout=10, htype="docker", use_sudo=False,
            )
            total += len(vm.containers)
            if r.returncode == 0:
                try:
                    running += int(r.stdout.strip())
                except ValueError:
                    pass

        self._json_response({
            "containers_total": total,
            "containers_running": running,
            "containers_down": total - running,
            "vm_count": len(cfg.container_vms),
        })

    def _serve_media_restart(self):
        """Restart a container (GET with ?name=xxx)."""
        cfg = load_config()


        query = _parse_query(self)
        name = query.get("name", [""])[0]
        if not name:
            self._json_response({"error": "name parameter required"})
            return

        container, vm = res.container_by_name(cfg.container_vms, name)
        if not container:
            self._json_response({"error": f"container not found: {name}"})
            return

        r = ssh_single(
            host=vm.ip, command=f"docker restart {container.name}",
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=60, htype="docker", use_sudo=False,
        )
        self._json_response({
            "ok": r.returncode == 0,
            "container": container.name,
            "vm": vm.label,
        })

    def _serve_media_logs(self):
        """Container logs (GET with ?name=xxx&lines=50)."""
        cfg = load_config()


        query = _parse_query(self)
        name = query.get("name", [""])[0]
        try: lines = int(query.get("lines", ["50"])[0])
        except ValueError: lines = 50

        if not name:
            self._json_response({"error": "name parameter required"})
            return

        container, vm = res.container_by_name(cfg.container_vms, name)
        if not container:
            self._json_response({"error": f"container not found: {name}"})
            return

        r = ssh_single(
            host=vm.ip, command=f"docker logs --tail {lines} {container.name} 2>&1",
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=15, htype="docker", use_sudo=False,
        )
        self._json_response({
            "container": container.name,
            "vm": vm.label,
            "logs": r.stdout if r.returncode == 0 else r.stderr,
        })

    def _serve_media_update(self):
        """Update a container (GET with ?name=xxx)."""
        cfg = load_config()


        query = _parse_query(self)
        name = query.get("name", [""])[0]

        if not name:
            self._json_response({"error": "name parameter required"})
            return

        container, vm = res.container_by_name(cfg.container_vms, name)
        if not container or not vm.compose_path:
            self._json_response({"error": f"container or compose not found: {name}"})
            return

        compose_dir = vm.compose_path.rsplit("/", 1)[0]
        r = ssh_single(
            host=vm.ip,
            command=f"cd {compose_dir} && docker compose pull {container.name} && "
                    f"docker compose up -d {container.name}",
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=120, htype="docker", use_sudo=False,
        )
        self._json_response({
            "ok": r.returncode == 0,
            "container": container.name,
            "vm": vm.label,
            "output": r.stdout[:500] if r.stdout else r.stderr[:500],
        })

    def _serve_vm_template(self):
        """Convert VM to template (GET with ?vmid=xxx)."""
        cfg = load_config()


        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        if not vmid:
            self._json_response({"error": "vmid parameter required"})
            return
        # Fleet boundary check
        allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
        if not allowed:
            self._json_response({"error": err})
            return

        try:
            node_ip = _find_reachable_pve_node(cfg)
            if not node_ip:
                self._json_response({"error": "no PVE node reachable"})
                return

            r = ssh_single(host=node_ip, command=f"sudo qm template {vmid}",
                            key_path=cfg.ssh_key_path, connect_timeout=3,
                            command_timeout=120, htype="pve", use_sudo=False)
            self._json_response({"ok": r.returncode == 0, "vmid": vmid})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_rename(self):
        """Rename VM (GET with ?vmid=xxx&name=xxx)."""
        cfg = load_config()


        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        name = query.get("name", [""])[0]
        if not vmid or not name:
            self._json_response({"error": "vmid and name parameters required"})
            return
        if not valid_label(name):
            self._json_response({"error": "Invalid VM name (alphanumeric + hyphens only)"}); return
        # Fleet boundary check
        allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
        if not allowed:
            self._json_response({"error": err})
            return

        try:
            node_ip = _find_reachable_pve_node(cfg)
            if not node_ip:
                self._json_response({"error": "no PVE node reachable"})
                return

            r = ssh_single(host=node_ip, command=f"sudo qm set {vmid} --name {name}",
                            key_path=cfg.ssh_key_path, connect_timeout=3,
                            command_timeout=30, htype="pve", use_sudo=False)
            self._json_response({"ok": r.returncode == 0, "vmid": vmid, "name": name})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_snapshots(self):
        """List snapshots for a VM."""
        cfg = load_config()

        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        if not vmid:
            self._json_response({"error": "vmid required"}); return
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            self._json_response({"error": "no PVE node reachable"}); return
        r = ssh_single(host=node_ip,
                        command=f"sudo qm listsnapshot {vmid}",
                        key_path=cfg.ssh_key_path, connect_timeout=3,
                        command_timeout=15, htype="pve", use_sudo=False)
        snaps = []
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if not line or "current" in line.lower() and "->" in line:
                    continue
                parts = line.split()
                if parts:
                    name = parts[0].replace("`-", "").replace("->", "").strip()
                    if name and name != "current":
                        snaps.append(name)
        self._json_response({"vmid": vmid, "snapshots": snaps, "count": len(snaps),
                              "live_migration": len(snaps) == 0})

    def _serve_vm_delete_snapshot(self):
        """Delete a snapshot from a VM."""
        cfg = load_config()

        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        snap = query.get("name", [""])[0]
        if not vmid or not snap:
            self._json_response({"error": "vmid and name required"}); return
        if not valid_label(snap):
            self._json_response({"error": "Invalid snapshot name (alphanumeric + hyphens only)"}); return
        allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
        if not allowed:
            self._json_response({"error": err}); return
        try:
            node_ip = _find_reachable_pve_node(cfg)
            if not node_ip:
                self._json_response({"error": "no PVE node reachable"}); return
            r = ssh_single(host=node_ip,
                            command=f"sudo qm delsnapshot {vmid} {snap}",
                            key_path=cfg.ssh_key_path, connect_timeout=3,
                            command_timeout=120, htype="pve", use_sudo=False)
            self._json_response({"ok": r.returncode == 0, "vmid": vmid, "snapshot": snap,
                                  "error": "" if r.returncode == 0 else (r.stderr or r.stdout)})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_change_id(self):
        """Change VMID (GET with ?vmid=xxx&newid=xxx). Requires VM to be stopped."""
        cfg = load_config()


        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        newid = query.get("newid", [""])[0]
        if not vmid or not newid:
            self._json_response({"error": "vmid and newid parameters required"})
            return
        # Fleet boundary check on BOTH old and new VMID
        allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
        if not allowed:
            self._json_response({"error": err})
            return
        allowed2, err2 = _check_vm_permission(cfg, int(newid), "configure")
        if not allowed2:
            self._json_response({"error": f"Target VMID blocked: {err2}"})
            return

        try:
            node_ip = _find_reachable_pve_node(cfg)
            if not node_ip:
                self._json_response({"error": "no PVE node reachable"})
                return

            # VM must be stopped first
            r = ssh_single(host=node_ip, command=f"sudo qm status {vmid}",
                            key_path=cfg.ssh_key_path, connect_timeout=3,
                            command_timeout=10, htype="pve", use_sudo=False)
            if "running" in (r.stdout or ""):
                self._json_response({"error": f"VM {vmid} must be stopped first"})
                return

            # Clone to new ID then destroy old
            r = ssh_single(host=node_ip,
                            command=f"sudo qm clone {vmid} {newid} --full",
                            key_path=cfg.ssh_key_path, connect_timeout=3,
                            command_timeout=300, htype="pve", use_sudo=False)
            if r.returncode != 0:
                self._json_response({"error": f"Clone failed: {r.stderr or r.stdout}"})
                return

            # Destroy old VM
            r2 = ssh_single(host=node_ip,
                             command=f"sudo qm destroy {vmid} --purge",
                             key_path=cfg.ssh_key_path, connect_timeout=3,
                             command_timeout=120, htype="pve", use_sudo=False)
            self._json_response({"ok": r2.returncode == 0, "old_vmid": vmid, "new_vmid": newid,
                                  "error": "" if r2.returncode == 0 else (r2.stderr or r2.stdout)})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_check_ip(self):
        """Check if an IP is available by pinging it (GET with ?ip=xxx)."""

        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query(self)
        ip = query.get("ip", [""])[0]
        if not ip:
            self._json_response({"error": "ip required"})
            return
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", ip],
                               capture_output=True, timeout=3)
            in_use = r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            in_use = False
        self._json_response({"ip": ip, "in_use": in_use, "available": not in_use})

    def _serve_vm_add_nic(self):
        """Add a single NIC to a VM without clearing existing ones (GET with ?vmid=xxx&ip=xxx&gw=xxx&vlan=xxx)."""
        cfg = load_config()


        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        new_ip = query.get("ip", [""])[0]
        gateway = query.get("gw", [""])[0]
        vlan_id = query.get("vlan", [""])[0]
        if not vmid or not new_ip:
            self._json_response({"error": "vmid and ip required"})
            return
        bare_ip = new_ip.split("/")[0] if "/" in new_ip else new_ip
        if not valid_ip(bare_ip):
            self._json_response({"error": "Invalid IP address"}); return
        if gateway and not valid_ip(gateway):
            self._json_response({"error": "Invalid gateway IP"}); return
        if vlan_id and not valid_vlan(vlan_id):
            self._json_response({"error": "Invalid VLAN ID"}); return
        allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
        if not allowed:
            self._json_response({"error": err})
            return

        try:
            node_ip = _find_reachable_pve_node(cfg)
            if not node_ip:
                self._json_response({"error": "no PVE node reachable"})
                return

            # Find the next available NIC index
            r = ssh_single(host=node_ip,
                            command=f"sudo qm config {vmid}",
                            key_path=cfg.ssh_key_path, connect_timeout=3,
                            command_timeout=15, htype="pve", use_sudo=False)
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
            tag_part = f",tag={vlan_id}" if vlan_id else ""

            # Create net entry
            r1 = ssh_single(host=node_ip,
                              command=f"sudo qm set {vmid} --net{next_nic} virtio,bridge={cfg.nic_bridge}{tag_part}",
                              key_path=cfg.ssh_key_path, connect_timeout=3,
                              command_timeout=30, htype="pve", use_sudo=False)
            # Set ipconfig
            r2 = ssh_single(host=node_ip,
                              command=f"sudo qm set {vmid} --ipconfig{next_nic} ip={cidr}{gw_part}",
                              key_path=cfg.ssh_key_path, connect_timeout=3,
                              command_timeout=30, htype="pve", use_sudo=False)
            ok = r1.returncode == 0 and r2.returncode == 0
            err = ""
            if r1.returncode != 0:
                err = f"NIC create failed: {r1.stderr or r1.stdout}"
            elif r2.returncode != 0:
                err = f"IP config failed: {r2.stderr or r2.stdout}"
            self._json_response({"ok": ok, "vmid": vmid, "nic": f"net{next_nic}",
                                  "ip": new_ip, "vlan": vlan_id, "error": err})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_clear_nics(self):
        """Clear all NICs and ipconfigs from a VM (GET with ?vmid=xxx)."""
        cfg = load_config()


        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        if not vmid:
            self._json_response({"error": "vmid required"})
            return
        allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
        if not allowed:
            self._json_response({"error": err})
            return

        try:
            node_ip = _find_reachable_pve_node(cfg)
            if not node_ip:
                self._json_response({"error": "no PVE node reachable"})
                return

            # Get current VM config to find existing NICs
            r = ssh_single(host=node_ip,
                            command=f"sudo qm config {vmid}",
                            key_path=cfg.ssh_key_path, connect_timeout=3,
                            command_timeout=15, htype="pve", use_sudo=False)

            deleted = []
            if r.returncode == 0:
                # Delete all net* (virtual NICs) and ipconfig* (cloud-init IPs)
                # New NICs will be re-created by the change-ip calls that follow
                for line in r.stdout.split("\n"):
                    line = line.strip()
                    if ":" not in line:
                        continue
                    key = line.split(":")[0].strip()
                    if key.startswith("ipconfig") or key.startswith("net"):
                        r2 = ssh_single(host=node_ip,
                                         command=f"sudo qm set {vmid} --delete {key}",
                                         key_path=cfg.ssh_key_path, connect_timeout=3,
                                         command_timeout=15, htype="pve", use_sudo=False)
                        if r2.returncode == 0:
                            deleted.append(key)

            self._json_response({"ok": True, "vmid": vmid, "cleared": deleted,
                                  "count": len(deleted)})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_change_ip(self):
        """Change VM IP via cloud-init or manual config (GET with ?vmid=xxx&ip=xxx&gw=xxx)."""
        cfg = load_config()


        query = _parse_query(self)
        vmid = query.get("vmid", [""])[0]
        new_ip = query.get("ip", [""])[0]
        gateway = query.get("gw", [""])[0]
        if not vmid or not new_ip:
            self._json_response({"error": "vmid and ip parameters required"})
            return
        bare_ip = new_ip.split("/")[0] if "/" in new_ip else new_ip
        if not valid_ip(bare_ip):
            self._json_response({"error": "Invalid IP address"}); return
        if gateway and not valid_ip(gateway):
            self._json_response({"error": "Invalid gateway IP"}); return
        # Fleet boundary check
        allowed, err = _check_vm_permission(cfg, int(vmid), "configure")
        if not allowed:
            self._json_response({"error": err})
            return

        # Create the virtual NIC (net*) with VLAN tag + set cloud-init IP (ipconfig*)
        try: nic_idx = int(query.get("nic", ["0"])[0])
        except ValueError:
            self._json_response({"error": "Invalid NIC index"}); return
        vlan_id = query.get("vlan", [""])[0]
        if vlan_id and not valid_vlan(vlan_id):
            self._json_response({"error": "Invalid VLAN ID"}); return
        try:
            node_ip = _find_reachable_pve_node(cfg)
            if not node_ip:
                self._json_response({"error": "no PVE node reachable"})
                return

            cidr = new_ip if "/" in new_ip else new_ip + "/24"
            gw_part = f",gw={gateway}" if gateway else ""

            # Create net entry — virtio on bridge with VLAN tag
            tag_part = f",tag={vlan_id}" if vlan_id else ""
            r1 = ssh_single(host=node_ip,
                              command=f"sudo qm set {vmid} --net{nic_idx} virtio,bridge={cfg.nic_bridge}{tag_part}",
                              key_path=cfg.ssh_key_path, connect_timeout=3,
                              command_timeout=30, htype="pve", use_sudo=False)
            # Set cloud-init ipconfig
            r2 = ssh_single(host=node_ip,
                              command=f"sudo qm set {vmid} --ipconfig{nic_idx} ip={cidr}{gw_part}",
                              key_path=cfg.ssh_key_path, connect_timeout=3,
                              command_timeout=30, htype="pve", use_sudo=False)
            ok = r1.returncode == 0 and r2.returncode == 0
            err = ""
            if r1.returncode != 0:
                err = f"NIC create failed: {r1.stderr or r1.stdout}"
            elif r2.returncode != 0:
                err = f"IP config failed: {r2.stderr or r2.stdout}"
            self._json_response({"ok": ok, "vmid": vmid, "ip": new_ip, "nic": nic_idx, "error": err})
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_pool(self):
        """List PVE pools."""
        cfg = load_config()
        pools = []
        for ip in cfg.pve_nodes:
            r = ssh_single(host=ip,
                           command="sudo pvesh get /pools --output-format json 2>/dev/null",
                           key_path=cfg.ssh_key_path, connect_timeout=3,
                           command_timeout=15, htype="pve", use_sudo=False)
            if r.returncode == 0:
                try:
                    pools = json.loads(r.stdout)
                except json.JSONDecodeError:
                    pass
                break
        self._json_response({"pools": pools})

    def _serve_fleet_ntp(self):
        """Fleet NTP status."""
        cfg = load_config()
        results_data = []
        results = ssh_run_many(
            hosts=cfg.hosts,
            command="timedatectl show --property=NTPSynchronized --value 2>/dev/null; date '+%H:%M:%S'",
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=10, max_parallel=10, use_sudo=False,
        )
        for h in cfg.hosts:
            r = results.get(h.label)
            if r and r.returncode == 0:
                lines = r.stdout.strip().split("\n")
                synced = lines[0].strip() == "yes" if lines else False
                time_str = lines[1].strip() if len(lines) > 1 else "?"
                results_data.append({
                    "label": h.label, "synced": synced, "time": time_str,
                })
            else:
                results_data.append({"label": h.label, "synced": False, "time": "unreachable"})
        self._json_response({"hosts": results_data})

    def _serve_fleet_updates(self):
        """Fleet update status."""
        cfg = load_config()
        results_data = []
        results = ssh_run_many(
            hosts=cfg.hosts,
            command="if command -v apt >/dev/null 2>&1; then "
                    "  apt list --upgradable 2>/dev/null | grep -c upgradable; echo apt; "
                    "else echo 0; echo unknown; fi",
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=30, max_parallel=10, use_sudo=False,
        )
        for h in cfg.hosts:
            r = results.get(h.label)
            if r and r.returncode == 0:
                lines = r.stdout.strip().split("\n")
                count = lines[0].strip() if lines else "0"
                pkg_mgr = lines[1].strip() if len(lines) > 1 else "?"
                try:
                    count_int = int(count)
                except ValueError:
                    count_int = 0
                results_data.append({
                    "label": h.label, "updates": count_int, "pkg_mgr": pkg_mgr,
                })
            else:
                results_data.append({"label": h.label, "updates": -1, "pkg_mgr": "?"})
        self._json_response({"hosts": results_data})

    def _serve_host_detail(self):
        """Deep detail for a single host — system, hardware, network, services, docker."""


        cfg = load_config()
        query = _parse_query(self)
        label = query.get("host", [""])[0]

        host = res.by_target(cfg.hosts, label)
        if not host:
            self._json_response({"error": f"Host not found: {label}"})
            return

        def _cmd(command, timeout=10):
            r = ssh_single(host=host.ip, command=command,
                           key_path=cfg.ssh_key_path, connect_timeout=3,
                           command_timeout=timeout, htype=host.htype, use_sudo=False)
            return r.stdout.strip() if r.returncode == 0 else ""

        detail = {
            "label": host.label, "ip": host.ip, "type": host.htype, "groups": host.groups,
            "hostname": _cmd("hostname -f 2>/dev/null || hostname"),
            "os": _cmd("cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'"),
            "kernel": _cmd("uname -r"),
            "uptime": _cmd("uptime -p 2>/dev/null || uptime"),
            "cpu_model": _cmd("grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs"),
            "cores": _cmd("nproc"),
            "ram": _cmd("free -m | awk '/Mem:/ {printf \"%d/%dMB (%d%%)\", $3, $2, $3/$2*100}'"),
            "load": _cmd("cat /proc/loadavg | awk '{print $1, $2, $3}'"),
            "disk": _cmd("df -h / | awk 'NR==2 {print $3\"/\"$2\" (\"$5\" used)\"}'"),
            "ips": _cmd("ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $NF\": \"$2}'"),
            "gateway": _cmd("ip route show default 2>/dev/null | awk '{print $3}' | head -1"),
            "dns": _cmd("grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | tr '\\n' ' '"),
            "listening_ports": _cmd("ss -tlnp 2>/dev/null | grep LISTEN | awk '{print $4}' | sed 's/.*://' | sort -un | tr '\\n' ' '"),
            "docker_count": _cmd("docker ps -q 2>/dev/null | wc -l"),
            "docker_containers": [],
            "failed_services": _cmd("systemctl --failed --no-legend 2>/dev/null | head -5 || echo none"),
            "running_services": _cmd("systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l"),
            "ssh_root_login": _cmd("grep -i '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'"),
            "ssh_password_auth": _cmd("grep -i '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'"),
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

        # Docker containers if any
        dc = _cmd("docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null")
        if dc:
            for line in dc.split("\n"):
                parts = line.split("|")
                if len(parts) >= 3:
                    detail["docker_containers"].append({
                        "name": parts[0], "status": parts[1], "image": parts[2]
                    })

        self._json_response(detail)

    def _serve_lab_status(self):
        """Lab fleet status."""
        cfg = load_config()

        lab_hosts = [h for h in cfg.hosts if "lab" in (h.groups or "").split(",")]

        hosts = []
        for h in lab_hosts:
            r = ssh_single(host=h.ip, command="uptime -p 2>/dev/null || echo unknown",
                           key_path=cfg.ssh_key_path, connect_timeout=3,
                           command_timeout=5, htype="linux", use_sudo=False, cfg=cfg)
            hosts.append({
                "label": h.label, "ip": h.ip, "role": h.htype,
                "status": "up" if r.returncode == 0 else "down",
                "uptime": r.stdout.strip().replace("up ", "")[:30] if r.returncode == 0 else "",
            })

        # Docker containers on docker-dev
        docker_containers = []
        docker_dev_ip = cfg.docker_dev_ip
        if not docker_dev_ip:
            self._json_response({"hosts": hosts, "docker": []})
            return
        r = ssh_single(host=docker_dev_ip,
                       command="docker ps --format '{{.Names}}|{{.Status}}' 2>/dev/null",
                       key_path=cfg.ssh_key_path, connect_timeout=3,
                       command_timeout=10, htype="docker", use_sudo=False)
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.strip().split("\n"):
                parts = line.split("|", 1)
                if len(parts) == 2:
                    docker_containers.append({
                        "name": parts[0].strip(),
                        "status": "up" if "Up" in parts[1] else "down",
                    })

        self._json_response({"hosts": hosts, "docker": docker_containers})

    def _serve_specialists(self):
        """Specialist / agent listing."""
        cfg = load_config()
        agents = []
        try:
            for name, a in _load_agents(cfg).items():
                agents.append({
                    "name": name,
                    "template": a.get("template", "?"),
                    "vmid": a.get("vmid"),
                    "status": a.get("status", "?"),
                })
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            logger.warn(f"agent list fetch failed: {e}")
        self._json_response({"agents": agents})

    # ── Lab Tool generic proxy ────────────────────────────────────────

    LAB_TOOL_REGISTRY = {
        "gwipe": {"default_port": 7980, "api_base": "/api/v1", "auth_header": "X-API-Key"},
    }

    def _lab_tool_request(self, tool_id, host, key, method, endpoint, body=None):
        """Make an HTTP request to a registered lab tool API."""
        tool = self.LAB_TOOL_REGISTRY.get(tool_id)
        if not tool:
            return {"error": f"Unknown lab tool: {tool_id}"}
        port = tool["default_port"]
        base = tool["api_base"].rstrip("/")
        url = f"http://{host}:{port}{base}/{endpoint}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header(tool["auth_header"], key)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode())
                return {"error": err_body.get("error", f"HTTP {e.code}")}
            except (json.JSONDecodeError, ValueError):
                return {"error": f"HTTP {e.code}"}
        except urllib.error.URLError as e:
            return {"error": f"Cannot reach {tool_id} at {host}:{port} — {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def _serve_lab_tool_proxy(self):
        """Generic proxy for lab tool API requests (GET or POST)."""

        params = _parse_query(self)
        tool = params.get("tool", [""])[0]
        host = params.get("host", [""])[0]
        key = params.get("key", [""])[0]
        method = params.get("method", ["GET"])[0].upper()
        endpoint = params.get("endpoint", [""])[0]
        confirm = params.get("confirm", [""])[0]

        if not tool or not host or not key or not endpoint:
            self._json_response({"error": "Missing parameters"})
            return

        body = {"confirm": "YES"} if confirm == "YES" else None
        result = self._lab_tool_request(tool, host, key, method, endpoint, body)
        self._json_response(result)

    def _serve_lab_tool_config(self):
        """Return saved connection config for a lab tool from vault."""

        params = _parse_query(self)
        tool = params.get("tool", [""])[0]
        if not tool:
            self._json_response({"error": "Missing tool parameter"})
            return
        cfg = load_config()
        host = ""
        key = ""
        try:
            host = vault_get(cfg, tool, f"{tool}_host") or ""
            key = vault_get(cfg, tool, f"{tool}_api_key") or ""
        except Exception as e:
            logger.warn(f"vault read failed for {tool}: {e}")
        self._json_response({"host": host, "key": key})

    def _serve_lab_tool_save_config(self):
        """Save lab tool connection config to vault."""

        params = _parse_query(self)
        tool = params.get("tool", [""])[0]
        host = params.get("host", [""])[0]
        key = params.get("key", [""])[0]

        if not tool or not host or not key:
            self._json_response({"error": "Missing parameters"})
            return

        cfg = load_config()
        try:
            if not os.path.exists(cfg.vault_file):
                vault_init(cfg)
            vault_set(cfg, tool, f"{tool}_host", host)
            vault_set(cfg, tool, f"{tool}_api_key", key)
            self._json_response({"ok": True})
        except Exception as e:
            self._json_response({"error": str(e)})

    # ── Auth ────────────────────────────────────────────────────────

    # Simple token store (in-memory, cleared on restart)
    _auth_tokens = {}  # token -> {user, role, ts}

    def _serve_auth_login(self):
        """Authenticate user against FREQ users list + vault password."""

        params = _parse_query(self)
        username = params.get("username", [""])[0].strip()
        password = params.get("password", [""])[0]

        if not username or not password:
            self._json_response({"error": "Username and password required"})
            return

        # Load FREQ users to verify the user exists and get role
        cfg = load_config()
        users = _load_users(cfg)
        user = next((u for u in users if u["username"] == username), None)
        if not user:
            self._json_response({"error": "Unknown user"})
            return

        # Verify password against vault-stored hash
        stored_hash = ""
        try:
            stored_hash = vault_get(cfg, "auth", f"password_{username}") or ""
        except Exception as e:
            logger.warn(f"vault read failed for auth: {e}")

        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        if stored_hash and stored_hash != pw_hash:
            self._json_response({"error": "Invalid password"})
            return

        # If no password stored yet, save this one (first login sets password)
        if not stored_hash:
            try:
                if not os.path.exists(cfg.vault_file):
                    vault_init(cfg)
                vault_set(cfg, "auth", f"password_{username}", pw_hash)
            except Exception as e:
                logger.warn(f"vault write failed for auth: {e}")

        # Generate session token
        token = hashlib.sha256(f"{username}{time.time()}{os.getpid()}".encode()).hexdigest()[:32]
        FreqHandler._auth_tokens[token] = {
            "user": username,
            "role": user["role"],
            "ts": time.time(),
        }
        self._json_response({
            "ok": True, "token": token,
            "user": username, "role": user["role"],
        })

    def _serve_auth_verify(self):
        """Verify a session token is still valid."""

        params = _parse_query(self)
        token = params.get("token", [""])[0]
        session = FreqHandler._auth_tokens.get(token)
        if not session:
            self._json_response({"valid": False})
            return
        # Sessions expire after 8 hours
        if time.time() - session["ts"] > SESSION_TIMEOUT_SECONDS:
            del FreqHandler._auth_tokens[token]
            self._json_response({"valid": False})
            return
        self._json_response({
            "valid": True, "user": session["user"], "role": session["role"],
        })

    def _serve_auth_change_password(self):
        """Change password for authenticated user."""

        params = _parse_query(self)
        token = params.get("token", [""])[0]
        new_password = params.get("password", [""])[0]

        session = FreqHandler._auth_tokens.get(token)
        if not session:
            self._json_response({"error": "Not authenticated"})
            return
        if not new_password or len(new_password) < 6:
            self._json_response({"error": "Password must be at least 6 characters"})
            return

        username = session["user"]
        cfg = load_config()
        pw_hash = hashlib.sha256(new_password.encode()).hexdigest()
        try:
            if not os.path.exists(cfg.vault_file):
                vault_init(cfg)
            vault_set(cfg, "auth", f"password_{username}", pw_hash)
            self._json_response({"ok": True, "user": username})
        except Exception as e:
            self._json_response({"error": f"Failed to update password: {e}"})

    def _proxy_watchdog(self):
        """Proxy requests to FREQ WATCHDOG daemon."""
        cfg = load_config()
        wd_port = cfg.watchdog_port
        parsed = urlparse(self.path)
        target_url = f"http://127.0.0.1:{wd_port}{parsed.path}"
        if parsed.query:
            target_url += f"?{parsed.query}"
        try:
            req = urllib.request.Request(target_url, method=self.command)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.URLError:
            self._json_response({"error": f"WATCHDOG daemon not reachable at localhost:{wd_port}", "watchdog_down": True})
        except Exception as e:
            self._json_response({"error": f"Proxy error: {e}"})

    # ── ADMIN API ENDPOINTS ──────────────────────────────────────────

    def _serve_admin_fleet_boundaries(self):
        """GET /api/admin/fleet-boundaries — return current fleet boundary config."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return
        cfg = load_config()
        fb = cfg.fleet_boundaries
        cats = {}
        for name, info in fb.categories.items():
            cats[name] = {
                "description": info.get("description", ""),
                "tier": info.get("tier", "probe"),
                "vmids": info.get("vmids", []),
            }
            if "range_start" in info:
                cats[name]["range_start"] = info["range_start"]
            if "range_end" in info:
                cats[name]["range_end"] = info["range_end"]
        self._json_response({
            "tiers": fb.tiers,
            "categories": cats,
            "physical": {k: {"ip": d.ip, "label": d.label, "type": d.device_type,
                             "tier": d.tier, "detail": d.detail}
                         for k, d in fb.physical.items()},
            "pve_nodes": {k: {"ip": n.ip, "detail": n.detail}
                          for k, n in fb.pve_nodes.items()},
            "hosts": [{"ip": h.ip, "label": h.label, "type": h.htype,
                       "groups": h.groups, "all_ips": h.all_ips}
                      for h in cfg.hosts],
        })

    def _serve_admin_fleet_boundaries_update(self):
        """GET /api/admin/fleet-boundaries/update — update fleet-boundaries.toml.

        Params: action=update_category|update_range|update_tier|add_vmid|remove_vmid
        """
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return

        params = _parse_query(self)
        action = params.get("action", [""])[0]
        cfg = load_config()
        fb_path = os.path.join(cfg.conf_dir, "fleet-boundaries.toml")

        if action == "update_category_tier":
            # Change which tier a category uses
            cat_name = params.get("category", [""])[0]
            new_tier = params.get("tier", [""])[0]
            if not cat_name or not new_tier:
                self._json_response({"error": "category and tier required"})
                return
            if cat_name not in cfg.fleet_boundaries.categories:
                self._json_response({"error": f"Unknown category: {cat_name}"})
                return
            if new_tier not in cfg.fleet_boundaries.tiers:
                self._json_response({"error": f"Unknown tier: {new_tier}"})
                return
            self._update_fb_toml(fb_path, "category_tier", cat_name=cat_name, tier=new_tier)
            self._json_response({"ok": True, "action": action})

        elif action == "add_vmid":
            cat_name = params.get("category", [""])[0]
            vmid_str = params.get("vmid", [""])[0]
            if not cat_name or not vmid_str:
                self._json_response({"error": "category and vmid required"})
                return
            try:
                vmid = int(vmid_str)
            except ValueError:
                self._json_response({"error": "vmid must be an integer"})
                return
            self._update_fb_toml(fb_path, "add_vmid", cat_name=cat_name, vmid=vmid)
            self._json_response({"ok": True, "action": action, "vmid": vmid})

        elif action == "remove_vmid":
            cat_name = params.get("category", [""])[0]
            vmid_str = params.get("vmid", [""])[0]
            if not cat_name or not vmid_str:
                self._json_response({"error": "category and vmid required"})
                return
            try:
                vmid = int(vmid_str)
            except ValueError:
                self._json_response({"error": "vmid must be an integer"})
                return
            self._update_fb_toml(fb_path, "remove_vmid", cat_name=cat_name, vmid=vmid)
            self._json_response({"ok": True, "action": action, "vmid": vmid})

        elif action == "update_range":
            cat_name = params.get("category", [""])[0]
            start_str = params.get("range_start", [""])[0]
            end_str = params.get("range_end", [""])[0]
            if not cat_name or not start_str or not end_str:
                self._json_response({"error": "category, range_start, range_end required"})
                return
            try:
                rs, re = int(start_str), int(end_str)
            except ValueError:
                self._json_response({"error": "range values must be integers"})
                return
            if rs >= re:
                self._json_response({"error": "range_start must be < range_end"})
                return
            self._update_fb_toml(fb_path, "update_range", cat_name=cat_name, range_start=rs, range_end=re)
            self._json_response({"ok": True, "action": action})

        elif action == "update_tier_actions":
            tier_name = params.get("tier", [""])[0]
            actions_str = params.get("actions", [""])[0]
            if not tier_name or not actions_str:
                self._json_response({"error": "tier and actions required"})
                return
            if tier_name not in cfg.fleet_boundaries.tiers:
                self._json_response({"error": f"Unknown tier: {tier_name}"})
                return
            actions_list = [a.strip() for a in actions_str.split(",") if a.strip()]
            valid_actions = {"view", "start", "stop", "restart", "snapshot", "destroy",
                            "clone", "resize", "migrate", "configure"}
            invalid = [a for a in actions_list if a not in valid_actions]
            if invalid:
                self._json_response({"error": f"Invalid actions: {', '.join(invalid)}"})
                return
            self._update_fb_toml(fb_path, "update_tier_actions", tier_name=tier_name, actions=actions_list)
            self._json_response({"ok": True, "action": action, "tier": tier_name, "actions": actions_list})

        else:
            self._json_response({"error": f"Unknown action: {action}"})

    def _update_fb_toml(self, path, op, **kw):
        """Read-modify-write fleet-boundaries.toml. Preserves comments and structure."""
        lines = []
        try:
            with open(path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            return

        if op == "category_tier":
            cat_name, tier = kw["cat_name"], kw["tier"]
            in_section = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == f"[categories.{cat_name}]":
                    in_section = True
                    continue
                if in_section and stripped.startswith("["):
                    break
                if in_section and stripped.startswith("tier"):
                    lines[i] = f'tier = "{tier}"\n'
                    break

        elif op == "add_vmid":
            cat_name, vmid = kw["cat_name"], kw["vmid"]
            in_section = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == f"[categories.{cat_name}]":
                    in_section = True
                    continue
                if in_section and stripped.startswith("["):
                    break
                if in_section and stripped.startswith("vmids"):
                    # Parse current vmids list, add new one
                    m = re.search(r'\[([^\]]*)\]', line)
                    if m:
                        current = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
                        if vmid not in current:
                            current.append(vmid)
                            current.sort()
                        lines[i] = f'vmids = [{", ".join(str(v) for v in current)}]\n'
                    break

        elif op == "remove_vmid":
            cat_name, vmid = kw["cat_name"], kw["vmid"]
            in_section = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == f"[categories.{cat_name}]":
                    in_section = True
                    continue
                if in_section and stripped.startswith("["):
                    break
                if in_section and stripped.startswith("vmids"):
                    m = re.search(r'\[([^\]]*)\]', line)
                    if m:
                        current = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
                        current = [v for v in current if v != vmid]
                        lines[i] = f'vmids = [{", ".join(str(v) for v in current)}]\n'
                    break

        elif op == "update_range":
            cat_name = kw["cat_name"]
            rs, re_val = kw["range_start"], kw["range_end"]
            in_section = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == f"[categories.{cat_name}]":
                    in_section = True
                    continue
                if in_section and stripped.startswith("[") and not stripped.startswith(f"[categories.{cat_name}"):
                    break
                if in_section and stripped.startswith("range_start"):
                    lines[i] = f'range_start = {rs}\n'
                if in_section and stripped.startswith("range_end"):
                    lines[i] = f'range_end = {re_val}\n'

        elif op == "update_tier_actions":
            tier_name, actions = kw["tier_name"], kw["actions"]
            in_tiers = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == "[tiers]":
                    in_tiers = True
                    continue
                if in_tiers and stripped.startswith("["):
                    break
                if in_tiers and stripped.startswith(f"{tier_name}"):
                    actions_str = ", ".join(f'"{a}"' for a in actions)
                    lines[i] = f'{tier_name:<9}= [{actions_str}]\n'
                    break

        try:
            with open(path, "w") as f:
                f.writelines(lines)
        except OSError as e:
            self._json_response({"error": f"Failed to write {path}: {e}"}, 500)
            return
        self._json_response({"ok": True})

    def _serve_admin_hosts_update(self):
        """GET /api/admin/hosts/update — update host type or groups in hosts.conf.

        Params: label, type (optional), groups (optional)
        """
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return

        params = _parse_query(self)
        label = params.get("label", [""])[0]
        new_type = params.get("type", [""])[0]
        new_groups = params.get("groups", [""])[0] if "groups" in params else None
        if not label:
            self._json_response({"error": "label required"})
            return

        cfg = load_config()
        hosts_path = cfg.hosts_file
        lines = []
        try:
            with open(hosts_path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            self._json_response({"error": "hosts.conf not found"})
            return

        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].lower() == label.lower():
                found = True
                ip = parts[0]
                htype = new_type if new_type else (parts[2] if len(parts) > 2 else "linux")
                groups = new_groups if new_groups is not None else (parts[3] if len(parts) > 3 else "")
                all_ips = parts[4] if len(parts) > 4 else ""
                new_parts = [f"{ip:<16}", f"{parts[1]:<15}", f"{htype:<10}"]
                if groups or all_ips:
                    new_parts.append(f"{groups:<20}" if all_ips else groups)
                if all_ips:
                    new_parts.append(all_ips)
                lines[i] = "  ".join(new_parts).rstrip() + "\n"
                break

        if not found:
            self._json_response({"error": f"Host '{label}' not found in hosts.conf"})
            return

        try:
            with open(hosts_path, "w") as f:
                f.writelines(lines)
        except OSError as e:
            self._json_response({"error": f"Failed to write hosts.conf: {e}"}, 500)
            return
        self._json_response({"ok": True, "label": label})

    # --- Phase 2: Feature parity endpoints ---

    def _serve_doctor(self):
        """Run FREQ self-diagnostic and return results as JSON."""
        try:
            from freq.core.doctor import run as doctor_run
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                from freq.core.config import load_config as _lc
                cfg = _lc()
                result = doctor_run(cfg)
            self._json_response({"ok": result == 0, "output": buf.getvalue(), "exit_code": result})
        except Exception as e:
            self._json_response({"error": f"Doctor failed: {e}"}, 500)

    def _serve_diagnose(self):
        """Run deep diagnostic for a specific host."""
        cfg = load_config()
        query = _parse_query(self)
        target = query.get("target", [""])[0]
        if not target:
            self._json_response({"error": "target parameter required"}); return
        try:
            host = res.by_target(cfg.hosts, target)
            if not host:
                self._json_response({"error": f"Unknown host: {target}"}); return
            # Gather diagnostic data via SSH
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
                r = ssh_single(host=host.ip, command=cmd,
                               key_path=cfg.ssh_key_path, connect_timeout=3,
                               command_timeout=15, htype=host.htype, use_sudo=False)
                checks[label] = r.stdout if r.returncode == 0 else f"ERROR: {r.stderr or r.stdout}"
            self._json_response({"host": target, "ip": host.ip, "checks": checks})
        except Exception as e:
            self._json_response({"error": f"Diagnose failed: {e}"}, 500)

    def _serve_log(self):
        """View remote host logs via SSH."""
        cfg = load_config()
        query = _parse_query(self)
        target = query.get("target", [""])[0]
        lines = int(query.get("lines", ["50"])[0])
        unit = query.get("unit", [""])[0]
        if not target:
            self._json_response({"error": "target parameter required"}); return
        try:
            host = res.by_target(cfg.hosts, target)
            if not host:
                self._json_response({"error": f"Unknown host: {target}"}); return
            cmd = f"journalctl --no-pager -n {min(lines, 500)}"
            if unit:
                cmd += f" -u {unit}"
            r = ssh_single(host=host.ip, command=cmd,
                           key_path=cfg.ssh_key_path, connect_timeout=3,
                           command_timeout=15, htype=host.htype, use_sudo=True)
            self._json_response({
                "host": target, "ip": host.ip, "lines": r.stdout.split("\n") if r.returncode == 0 else [],
                "error": "" if r.returncode == 0 else (r.stderr or r.stdout)
            })
        except Exception as e:
            self._json_response({"error": f"Log fetch failed: {e}"}, 500)

    def _serve_policy_check(self):
        """Run policy compliance check (dry run)."""
        cfg = load_config()
        query = _parse_query(self)
        policy = query.get("policy", [""])[0]
        hosts_param = query.get("hosts", [""])[0]
        try:
            import io, contextlib
            from freq.modules.engine_cmds import cmd_check
            # Build a mock args object
            class Args:
                pass
            args = Args()
            args.policy = policy or None
            args.hosts = hosts_param or None
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = cmd_check(cfg, None, args)
            self._json_response({"ok": result == 0, "output": buf.getvalue(), "policy": policy})
        except Exception as e:
            self._json_response({"error": f"Policy check failed: {e}"}, 500)

    def _serve_policy_fix(self):
        """Apply policy remediation."""
        cfg = load_config()
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query(self)
        policy = query.get("policy", [""])[0]
        hosts_param = query.get("hosts", [""])[0]
        try:
            import io, contextlib
            from freq.modules.engine_cmds import cmd_fix
            class Args:
                pass
            args = Args()
            args.policy = policy or None
            args.hosts = hosts_param or None
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = cmd_fix(cfg, None, args)
            self._json_response({"ok": result == 0, "output": buf.getvalue(), "policy": policy})
        except Exception as e:
            self._json_response({"error": f"Policy fix failed: {e}"}, 500)

    def _serve_policy_diff(self):
        """Show policy drift as git-style diff."""
        cfg = load_config()
        query = _parse_query(self)
        policy = query.get("policy", [""])[0]
        hosts_param = query.get("hosts", [""])[0]
        try:
            import io, contextlib
            from freq.modules.engine_cmds import cmd_diff
            class Args:
                pass
            args = Args()
            args.policy = policy or None
            args.hosts = hosts_param or None
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = cmd_diff(cfg, None, args)
            self._json_response({"ok": result == 0, "output": buf.getvalue(), "policy": policy})
        except Exception as e:
            self._json_response({"error": f"Policy diff failed: {e}"}, 500)

    def _serve_sweep(self):
        """Run full audit + policy sweep pipeline."""
        cfg = load_config()
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query(self)
        do_fix = query.get("fix", ["false"])[0].lower() == "true"
        try:
            import io, contextlib
            from freq.jarvis.sweep import cmd_sweep
            class Args:
                pass
            args = Args()
            args.fix = do_fix
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = cmd_sweep(cfg, None, args)
            self._json_response({"ok": result == 0, "output": buf.getvalue(), "fix_mode": do_fix})
        except Exception as e:
            self._json_response({"error": f"Sweep failed: {e}"}, 500)

    def _serve_patrol_status(self):
        """Get patrol (continuous monitoring) status."""
        cfg = load_config()
        try:
            import io, contextlib
            # Patrol is a long-running process — we return a one-shot status check
            from freq.modules.engine_cmds import cmd_check
            class Args:
                pass
            args = Args()
            args.policy = None
            args.hosts = None
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = cmd_check(cfg, None, args)
            self._json_response({"ok": result == 0, "output": buf.getvalue(),
                                  "note": "One-shot compliance check (patrol is a long-running CLI process)"})
        except Exception as e:
            self._json_response({"error": f"Patrol status failed: {e}"}, 500)

    def _serve_zfs(self):
        """ZFS pool status and operations."""
        cfg = load_config()
        query = _parse_query(self)
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
            self._json_response({"ok": result == 0, "output": buf.getvalue(), "action": action})
        except Exception as e:
            self._json_response({"error": f"ZFS operation failed: {e}"}, 500)

    def _serve_backup(self):
        """Backup management: list, create, status, prune."""
        cfg = load_config()
        query = _parse_query(self)
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
            self._json_response({"ok": result == 0, "output": buf.getvalue(), "action": action})
        except Exception as e:
            self._json_response({"error": f"Backup operation failed: {e}"}, 500)

    def _serve_discover(self):
        """Discover hosts on network."""
        cfg = load_config()
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query(self)
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
            self._json_response({"ok": result == 0, "output": buf.getvalue()})
        except Exception as e:
            self._json_response({"error": f"Discovery failed: {e}"}, 500)

    def _serve_gwipe(self):
        """FREQ WIPE station status and operations."""
        cfg = load_config()
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query(self)
        action = query.get("action", ["status"])[0]
        try:
            # GWipe talks to an external API — reuse the vault lookup pattern
            host = vault_get(cfg, "gwipe", "gwipe_host") or ""
            key = vault_get(cfg, "gwipe", "gwipe_api_key") or ""
            if not host or not key:
                self._json_response({"error": "GWIPE station not configured in vault"}); return
            import urllib.request, urllib.error
            url = f"http://{host}:7980/api/v1/{action}"
            req = urllib.request.Request(url)
            req.add_header("X-API-Key", key)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            self._json_response({"ok": True, "action": action, "data": data})
        except Exception as e:
            self._json_response({"error": f"GWIPE operation failed: {e}"}, 500)

    def _json_response(self, data, status=200):
        """Send a JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def cmd_serve(cfg, pack, args) -> int:
    """Start the FREQ web dashboard."""
    port = getattr(args, "port", None) or cfg.dashboard_port

    fmt.header("Web Dashboard")
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Starting dashboard on port {port}...{fmt.C.RESET}")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}Dashboard: http://localhost:{port}{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.GREEN}API:       http://localhost:{port}/api/status{fmt.C.RESET}")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Ctrl+C to stop{fmt.C.RESET}")
    fmt.blank()

    # Start background cache engine — disk cache loads instantly,
    # then background thread probes live data continuously
    start_background_cache()
    fmt.line(f"  {fmt.C.DIM}Background cache engine started{fmt.C.RESET}")
    fmt.blank()

    server = ThreadedHTTPServer(("0.0.0.0", port), FreqHandler)
    logger.info(f"web dashboard started on port {port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  {fmt.C.YELLOW}Dashboard stopped.{fmt.C.RESET}")
        server.server_close()

    return 0
