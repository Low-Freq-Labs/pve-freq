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

def _get_cache_dir():
    """Resolve cache directory from config at runtime — not from __file__.
    Using __file__ breaks pip-installed packages where site-packages is read-only."""
    try:
        cfg = load_config()
        return os.path.join(cfg.data_dir, "cache")
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")


CACHE_DIR = None  # Set at runtime by _init_cache_dir()


def _init_cache_dir():
    global CACHE_DIR
    CACHE_DIR = _get_cache_dir()
_bg_cache = {
    "infra_quick": None,
    "health": None,
    "update": None,
    "fleet_overview": None,
    "hosts_sync": None,
    "pve_nodes": None,
    "vm_tags": None,
}
_bg_cache_ts = {
    "infra_quick": 0,
    "health": 0,
    "update": 0,
    "fleet_overview": 0,
    "hosts_sync": 0,
    "pve_nodes": 0,
    "vm_tags": 0,
}
UPDATE_CHECK_INTERVAL = 6 * 3600  # 6 hours
HOSTS_SYNC_INTERVAL = 3600        # 1 hour — keep hosts.conf in sync with PVE
NODE_DISCOVERY_INTERVAL = 300     # 5 min — discover PVE cluster nodes
VM_TAGS_INTERVAL = 300            # 5 min — refresh PVE VM tags
_bg_lock = threading.Lock()

# ── SSE EVENT BUS ────────────────────────────────────────────────────────
# Lightweight pub/sub: each connected EventSource client gets a Queue.
# Background probes broadcast events after cache updates.

import queue

_sse_clients: list = []          # list of queue.Queue, one per SSE client
_sse_lock = threading.Lock()     # guards _sse_clients list


def _sse_subscribe() -> queue.Queue:
    """Register a new SSE client. Returns a Queue to read events from."""
    q = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append(q)
    return q


def _sse_unsubscribe(q: queue.Queue):
    """Remove an SSE client queue."""
    with _sse_lock:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass


def _sse_broadcast(event_type: str, data: dict):
    """Push an event to all connected SSE clients.

    Drops clients whose queue is full (slow/dead connections).
    Must NOT be called while holding _bg_lock.
    """
    msg = {"type": event_type, "data": data}
    dead = []
    with _sse_lock:
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                _sse_clients.remove(q)
            except ValueError:
                pass


# ── ACTIVITY FEED ────────────────────────────────────────────────────────
# Ring buffer for recent system events — powers the dashboard activity widget.
# Max 200 events kept in memory, newest first.

import collections

_activity_feed: collections.deque = collections.deque(maxlen=200)
_activity_lock = threading.Lock()


def _activity_add(event_type: str, message: str, detail: str = "", severity: str = "info"):
    """Record an activity event."""
    entry = {
        "ts": time.time(),
        "type": event_type,
        "message": message,
        "detail": detail,
        "severity": severity,  # info, success, warning, error
    }
    with _activity_lock:
        _activity_feed.appendleft(entry)
    _sse_broadcast("activity", entry)


def _cache_path(name):
    global CACHE_DIR
    if CACHE_DIR is None:
        _init_cache_dir()
    return os.path.join(CACHE_DIR, f"{name}.json")


def _load_disk_cache():
    """Load cached probe data from disk — instant startup."""
    global CACHE_DIR
    if CACHE_DIR is None:
        _init_cache_dir()
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
                else:
                    pr = subprocess.run(["ping", "-c", "1", "-W", "1", dev.ip], capture_output=True, timeout=2)
                    d["reachable"] = pr.returncode == 0
                    if d["reachable"]:
                        d["metrics"]["note"] = "Reachable (no SSH)"
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
                    # SSH failed — fall back to ping so we don't mark a reachable iDRAC as offline
                    pr = subprocess.run(["ping", "-c", "1", "-W", "1", dev.ip], capture_output=True, timeout=2)
                    d["reachable"] = pr.returncode == 0
                    if d["reachable"]:
                        d["metrics"]["note"] = "Reachable (no SSH)"
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

    # SSE: broadcast infra cache update
    _sse_broadcast("cache_update", {"key": "infra_quick", "ts": time.time()})


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
            err = r.stderr.strip()[:120] if r.stderr else "no response"
            return {"label": h.label, "ip": h.ip, "type": htype, "groups": _groups,
                    "status": "unreachable", "cores": "-", "ram": "-",
                    "disk": "-", "load": "-", "docker": "0",
                    "last_error": err}
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
                                  "disk": "-", "load": "-", "docker": "0",
                                  "last_error": str(e)[:120]})

    # Aggregate container counts per PVE node.
    # Chain: container_vms (vm_id→IP) + WATCHDOG (vm_id→node) + health (IP→docker count)
    node_containers = {}
    try:
        # Build IP→docker count from health data
        ip_docker = {h["ip"]: int(h.get("docker", 0)) for h in host_data if h.get("type") == "docker"}
        # Build vm_id→IP from container_vms config (resolved from hosts.conf)
        vmid_to_ip = {vm.vm_id: _resolve_container_vm_ip(vm) for vm in cfg.container_vms.values()}
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
    # Snapshot old health for SSE diff
    with _bg_lock:
        old_health = _bg_cache.get("health")
        _bg_cache["health"] = result
        _bg_cache_ts["health"] = time.time()
    _save_disk_cache("health", result)

    # SSE: broadcast cache_update + per-host health_change events
    _sse_broadcast("cache_update", {"key": "health", "ts": time.time()})
    if old_health and isinstance(old_health, dict):
        old_status = {h["label"]: h["status"] for h in old_health.get("hosts", [])}
        for h in host_data:
            prev = old_status.get(h["label"])
            if prev and prev != h["status"]:
                _sse_broadcast("health_change", {
                    "host": h["label"], "old": prev, "new": h["status"]})
                severity = "success" if h["status"] == "healthy" else "error"
                _activity_add("health_change",
                              f"{h['label']} is now {h['status']}",
                              f"was {prev}", severity)

    # Evaluate alert rules against fresh health data
    _evaluate_alert_rules(cfg, result)

    # Save capacity snapshot if due (weekly)
    try:
        from freq.jarvis.capacity import should_snapshot, save_snapshot
        if should_snapshot(cfg.data_dir):
            save_snapshot(cfg.data_dir, result)
    except Exception as e:
        logger.warn(f"Capacity snapshot failed: {e}")


def _bg_probe_fleet_overview():
    """Build fleet overview in background — PVE API + pings + NIC data."""
    try:
        cfg = load_config()
    except Exception as e:
        logger.error(f"bg_probe_fleet_overview: config load failed: {e}")
        return
    fb = cfg.fleet_boundaries
    start = time.monotonic()

    vm_list = _get_fleet_vms(cfg)

    # Physical devices — ping in parallel
    physical = []
    def _ping_device(dev):
        reachable = False
        try:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", "1", dev.ip],
                capture_output=True, timeout=2,
            )
            reachable = r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            pass
        return {
            "key": dev.key, "ip": dev.ip, "label": dev.label,
            "type": dev.device_type, "tier": dev.tier, "detail": dev.detail,
            "reachable": reachable,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_ping_device, dev): dev for dev in fb.physical.values()}
        for f in concurrent.futures.as_completed(futures):
            try:
                physical.append(f.result())
            except Exception:
                dev = futures[f]
                physical.append({"key": dev.key, "ip": dev.ip, "label": dev.label,
                                 "type": dev.device_type, "tier": dev.tier, "detail": dev.detail,
                                 "reachable": False})

    # PVE nodes — use auto-discovered nodes, enrich with live stats + config detail
    discovered_nodes = _get_discovered_nodes()
    # Also keep fleet-boundaries detail strings for enrichment
    fb_detail = {n.name: n.detail for n in fb.pve_nodes.values()}

    pve_nodes = []
    for dn in discovered_nodes:
        entry = {
            "name": dn.get("name", ""),
            "ip": dn.get("ip", ""),
            "detail": fb_detail.get(dn.get("name", ""), dn.get("detail", "")),
        }
        if dn.get("cores"):
            entry["cores"] = dn["cores"]
        if dn.get("ram_gb"):
            entry["ram_gb"] = dn["ram_gb"]
        pve_nodes.append(entry)

    # Category summaries
    cat_summary = {}
    for cat_name, cat_info in fb.categories.items():
        running = sum(1 for v in vm_list if v["category"] == cat_name and v["status"] == "running")
        total = sum(1 for v in vm_list if v["category"] == cat_name)
        cat_summary[cat_name] = {
            "count": total, "running": running,
            "description": cat_info.get("description", ""),
            "tier": cat_info.get("tier", "probe"),
        }

    non_template = [v for v in vm_list if v["category"] != "templates"]
    total_vms = len(non_template)
    running = sum(1 for v in non_template if v["status"] == "running")
    stopped = sum(1 for v in non_template if v["status"] == "stopped")
    prod_count = sum(1 for v in non_template if v["is_prod"])
    lab_count = sum(1 for v in non_template if v["category"] == "lab")
    template_count = sum(1 for v in vm_list if v["category"] == "templates")

    # VM NIC data — batch per node
    vlan_id_to_name = {v.id: v.name for v in cfg.vlans}
    if 2550 not in vlan_id_to_name:
        vlan_id_to_name[2550] = "MGMT"
    vm_nics = {}
    node_vmids = {}
    for v in vm_list:
        node_vmids.setdefault(v["node"], []).append(v["vmid"])
    node_ips = {n["name"]: n["ip"] for n in discovered_nodes if n.get("name") and n.get("ip")}
    for node_name, vmids in node_vmids.items():
        nip = node_ips.get(node_name)
        if not nip:
            continue
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
                    nic_name = line.split(":")[0].strip()
                    tag_match = re.search(r'tag=(\d+)', line)
                    vlan_tag = int(tag_match.group(1)) if tag_match else 0
                    vlan_name = vlan_id_to_name.get(vlan_tag, f"VLAN {vlan_tag}" if vlan_tag else "UNTAGGED")
                    vm_nics[cur_vmid].append({
                        "nic": nic_name, "tag": vlan_tag, "vlan_name": vlan_name,
                    })

    duration = round(time.monotonic() - start, 2)
    result = {
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
            "total_vms": total_vms, "running": running, "stopped": stopped,
            "prod_count": prod_count, "lab_count": lab_count, "template_count": template_count,
        },
        "duration": duration,
    }

    # Snapshot old fleet for SSE diff
    with _bg_lock:
        old_fleet = _bg_cache.get("fleet_overview")
        _bg_cache["fleet_overview"] = result
        _bg_cache_ts["fleet_overview"] = time.time()
    _save_disk_cache("fleet_overview", result)

    # SSE: broadcast cache_update + per-VM vm_state events
    _sse_broadcast("cache_update", {"key": "fleet_overview", "ts": time.time()})
    if old_fleet and isinstance(old_fleet, dict):
        old_vm_status = {v["vmid"]: v["status"] for v in old_fleet.get("vms", [])}
        for v in vm_list:
            prev = old_vm_status.get(v["vmid"])
            if prev and prev != v["status"]:
                _sse_broadcast("vm_state", {
                    "vmid": v["vmid"], "name": v.get("name", ""),
                    "old": prev, "new": v["status"]})
                vm_label = v.get("name") or f"VM {v['vmid']}"
                _activity_add("vm_state", f"{vm_label}: {prev} \u2192 {v['status']}",
                              f"VMID {v['vmid']}", "info")


def _bg_discover_pve_nodes():
    """Discover PVE cluster nodes from API + corosync config.

    Queries any reachable seed node (from freq.toml) for:
    - /cluster/resources --type node → node names, status, hardware stats
    - /etc/pve/corosync.conf → node name ↔ IP mapping

    Results cached in _bg_cache["pve_nodes"] for 5 minutes.
    Falls back to freq.toml static list if discovery fails.
    """
    with _bg_lock:
        last = _bg_cache_ts.get("pve_nodes", 0)
    if time.time() - last < NODE_DISCOVERY_INTERVAL:
        return

    try:
        cfg = load_config()
        # Find first reachable seed node
        seed_ip = None
        for ip in cfg.pve_nodes:
            r = ssh_single(host=ip, command="echo ok",
                           key_path=cfg.ssh_key_path, connect_timeout=3,
                           command_timeout=5, htype="pve", use_sudo=False)
            if r.returncode == 0:
                seed_ip = ip
                break

        if not seed_ip:
            logger.warn("PVE node discovery: no reachable seed node")
            with _bg_lock:
                _bg_cache_ts["pve_nodes"] = time.time()
            return

        # Get node names + stats from cluster API
        r = ssh_single(
            host=seed_ip,
            command="pvesh get /cluster/resources --type node --output-format json",
            key_path=cfg.ssh_key_path, command_timeout=15,
            htype="pve", use_sudo=True, cfg=cfg,
        )

        node_stats = {}
        if r.returncode == 0 and r.stdout:
            try:
                for n in json.loads(r.stdout):
                    name = n.get("node", "")
                    if name:
                        node_stats[name] = {
                            "status": "online" if n.get("status") == "online" else "offline",
                            "cores": n.get("maxcpu", 0),
                            "ram_gb": round(n.get("maxmem", 0) / (1024 ** 3)),
                        }
            except json.JSONDecodeError:
                pass

        # Get IPs from corosync config
        r2 = ssh_single(
            host=seed_ip,
            command="cat /etc/pve/corosync.conf 2>/dev/null",
            key_path=cfg.ssh_key_path, command_timeout=10,
            htype="pve", use_sudo=True, cfg=cfg,
        )

        node_ips = {}
        if r2.returncode == 0 and r2.stdout:
            current_name = None
            for line in r2.stdout.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    current_name = line.split(":", 1)[1].strip()
                elif line.startswith("ring0_addr:") and current_name:
                    node_ips[current_name] = line.split(":", 1)[1].strip()
                    current_name = None

        # Build discovered nodes
        discovered = []
        for name, stats in node_stats.items():
            discovered.append({
                "name": name,
                "ip": node_ips.get(name, ""),
                "status": stats["status"],
                "cores": stats["cores"],
                "ram_gb": stats["ram_gb"],
            })

        result = {"nodes": discovered, "discovered_at": time.time()} if discovered else None
    except Exception as e:
        logger.error(f"PVE node discovery failed: {e}")
        result = None

    with _bg_lock:
        _bg_cache["pve_nodes"] = result
        _bg_cache_ts["pve_nodes"] = time.time()


def _get_discovered_node_ips():
    """Get PVE node IPs — prefers auto-discovered, falls back to freq.toml."""
    with _bg_lock:
        discovered = _bg_cache.get("pve_nodes")
    if discovered and discovered.get("nodes"):
        ips = [n["ip"] for n in discovered["nodes"] if n.get("ip")]
        if ips:
            return ips
    cfg = load_config()
    return list(cfg.pve_nodes)


def _get_discovered_nodes():
    """Get PVE nodes as list of dicts with name/ip/stats.

    Prefers auto-discovered nodes, falls back to fleet-boundaries config.
    """
    with _bg_lock:
        discovered = _bg_cache.get("pve_nodes")
    if discovered and discovered.get("nodes"):
        return discovered["nodes"]
    cfg = load_config()
    fb = cfg.fleet_boundaries
    return [{"name": n.name, "ip": n.ip, "detail": getattr(n, "detail", "")}
            for n in fb.pve_nodes.values()]


def _bg_fetch_vm_tags():
    """Fetch PVE tags for all VMs via batch SSH.

    Queries each PVE node for VM configs, extracts tags.
    Result: {vmid: ["tag1", "tag2", ...]}
    Used for tag-based protection (prod) and categorization (lab, core, etc).
    """
    with _bg_lock:
        last = _bg_cache_ts.get("vm_tags", 0)
    if time.time() - last < VM_TAGS_INTERVAL:
        return

    try:
        cfg = load_config()
        node_ips = _get_discovered_node_ips()
        if not node_ips:
            return

        # Get VM list from cluster resources (one node is enough)
        seed_ip = node_ips[0]
        r = ssh_single(
            host=seed_ip,
            command="pvesh get /cluster/resources --type vm --output-format json",
            key_path=cfg.ssh_key_path, command_timeout=15,
            htype="pve", use_sudo=True, cfg=cfg,
        )
        if r.returncode != 0 or not r.stdout:
            return

        vms = json.loads(r.stdout)
        # Group VMIDs by node
        node_vmids = {}
        for v in vms:
            if v.get("type") == "qemu":
                node_vmids.setdefault(v.get("node", ""), []).append(v.get("vmid", 0))

        # Build node name → IP mapping
        node_ip_map = {n["name"]: n["ip"] for n in _get_discovered_nodes()
                       if n.get("name") and n.get("ip")}

        # Batch query tags per node
        all_tags = {}
        for node_name, vmids in node_vmids.items():
            nip = node_ip_map.get(node_name)
            if not nip:
                continue
            # Build batch command: for each VMID, print "VMID:<id>" then grep tags
            cmd_parts = []
            for vid in vmids:
                cmd_parts.append(f"echo VMID:{vid}; qm config {vid} 2>/dev/null | grep ^tags || true")
            batch_cmd = "; ".join(cmd_parts)
            r = ssh_single(
                host=nip, command=batch_cmd,
                key_path=cfg.ssh_key_path, command_timeout=30,
                htype="pve", use_sudo=True, cfg=cfg,
            )
            if r.returncode == 0 and r.stdout:
                cur_vmid = None
                for line in r.stdout.strip().split("\n"):
                    if line.startswith("VMID:"):
                        cur_vmid = int(line[5:])
                    elif cur_vmid is not None and line.startswith("tags:"):
                        raw = line.split(":", 1)[1].strip()
                        # PVE tags are semicolon-separated
                        tags = [t.strip() for t in raw.replace(",", ";").split(";") if t.strip()]
                        all_tags[cur_vmid] = tags

        result = {"tags": all_tags, "fetched_at": time.time()}
    except Exception as e:
        logger.error(f"VM tag fetch failed: {e}")
        result = None

    with _bg_lock:
        _bg_cache["vm_tags"] = result
        _bg_cache_ts["vm_tags"] = time.time()


def get_vm_tags(vmid: int) -> list:
    """Get cached PVE tags for a VMID. Returns list of tag strings."""
    with _bg_lock:
        cache = _bg_cache.get("vm_tags")
    if cache and cache.get("tags"):
        return cache["tags"].get(vmid, [])
    return []


def is_vm_tagged(vmid: int, tag: str) -> bool:
    """Check if a VM has a specific PVE tag (from cache)."""
    return tag in get_vm_tags(vmid)


def _bg_sync_hosts():
    """Auto-sync hosts.conf from PVE every hour.

    Keeps hosts.conf labels in sync with PVE VM names so the dashboard,
    SSH keys, and fleet data all use the same names. Users never need to
    run 'freq hosts sync' manually.
    """
    with _bg_lock:
        last_sync = _bg_cache_ts.get("hosts_sync", 0)
    if time.time() - last_sync < HOSTS_SYNC_INTERVAL:
        return  # Not time yet

    try:
        import io, sys
        from freq.modules.hosts import _hosts_sync
        cfg = load_config()
        # Suppress fmt output — hosts_sync prints to stdout
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _hosts_sync(cfg, dry_run=False)
        finally:
            sys.stdout = old_stdout
        result = {"synced_at": time.time(), "ok": True}
    except Exception as e:
        logger.error(f"bg hosts sync failed: {e}")
        result = {"synced_at": time.time(), "ok": False, "error": str(e)}

    with _bg_lock:
        _bg_cache["hosts_sync"] = result
        _bg_cache_ts["hosts_sync"] = time.time()


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
                # SSE: broadcast alert event
                _sse_broadcast("alert", {
                    "rule": alert.rule_name, "message": alert.message,
                    "severity": alert.severity})
            save_alert_history(CACHE_DIR, history)
    except Exception as e:
        logger.warn(f"Alert rule evaluation failed: {e}")


def _bg_refresh_loop(interval=BG_CACHE_REFRESH_INTERVAL):
    """Continuous background refresh — runs forever as a daemon thread."""
    while True:
        try:
            _bg_discover_pve_nodes()
        except Exception as e:
            logger.error(f"bg node discovery failed: {e}")
        try:
            _bg_fetch_vm_tags()
        except Exception as e:
            logger.error(f"bg tag fetch failed: {e}")
        try:
            _bg_probe_health()
        except Exception as e:
            logger.error(f"bg health probe failed: {e}")
        try:
            _bg_probe_infra()
        except Exception as e:
            logger.error(f"bg infra probe failed: {e}")
        try:
            _bg_probe_fleet_overview()
        except Exception as e:
            logger.error(f"bg fleet overview probe failed: {e}")
        try:
            _bg_check_update()
        except Exception as e:
            logger.error(f"bg update check failed: {e}")
        try:
            _bg_sync_hosts()
        except Exception as e:
            logger.error(f"bg hosts sync failed: {e}")
        time.sleep(interval)


def start_background_cache():
    """Load disk cache, then start the background refresh loop."""
    _init_cache_dir()
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
    """Find the first reachable PVE node. Returns IP string or None.

    Prefers auto-discovered nodes, falls back to freq.toml static list.
    """
    node_ips = _get_discovered_node_ips()
    for ip in node_ips:
        r = ssh_single(host=ip, command="sudo pvesh get /version --output-format json",
                       key_path=cfg.ssh_key_path, connect_timeout=3,
                       command_timeout=10, htype="pve", use_sudo=False)
        if r.returncode == 0:
            return ip
    return None


def _parse_query(handler):
    """Parse query parameters from the request path. Returns dict of lists."""
    return parse_qs(urlparse(handler.path).query)


def _parse_pct(value: str) -> float:
    """Parse a percentage string like '45%' or RAM string '4096/8192MB' into float."""
    if not value:
        return 0.0
    import re as _re
    # Try percentage: "45%"
    m = _re.match(r'(\d+)%', value)
    if m:
        return float(m.group(1))
    # Try fraction: "4096/8192"
    m = _re.match(r'(\d+)/(\d+)', value)
    if m:
        used, total = float(m.group(1)), float(m.group(2))
        return round(used / total * 100, 1) if total > 0 else 0.0
    return 0.0


def _parse_query_flat(path_str):
    """Parse query params from a URL path string. Returns {key: str}."""
    raw = parse_qs(urlparse(path_str).query)
    return {k: v[0] if v else "" for k, v in raw.items()}


def _resolve_container_vm_ip(vm) -> str:
    """Resolve container VM IP from hosts.conf by label, falling back to hardcoded IP.

    This eliminates hardcoded IPs in containers.toml — if the VM gets re-IPed,
    the hourly hosts.conf sync picks up the new IP, and container probes
    automatically use it.
    """
    if vm.label:
        try:
            from freq.modules.hosts import resolve_host_ip
            cfg = load_config()
            resolved = resolve_host_ip(cfg, vm.label)
            if resolved:
                return resolved
        except Exception as e:
            logger.warning(f"_resolve_container_vm_ip: failed to resolve '{vm.label}': {e}")
    return vm.ip


def _write_containers_toml(path: str, container_vms: dict):
    """Write container registry back to containers.toml."""
    lines = ["# FREQ Container Registry\n"]
    for vm_id in sorted(container_vms.keys()):
        vm = container_vms[vm_id]
        lines.append(f"\n[vm.{vm_id}]")
        if vm.ip:
            lines.append(f'ip = "{vm.ip}"')
        if vm.label:
            lines.append(f'label = "{vm.label}"')
        if vm.compose_path:
            lines.append(f'compose_path = "{vm.compose_path}"')
        for cname, c in sorted(vm.containers.items()):
            lines.append(f"\n[vm.{vm_id}.containers.{cname}]")
            if c.port:
                lines.append(f"port = {c.port}")
            if c.api_path:
                lines.append(f'api_path = "{c.api_path}"')
            if c.auth_type:
                lines.append(f'auth_type = "{c.auth_type}"')
            if c.auth_header:
                lines.append(f'auth_header = "{c.auth_header}"')
            if c.vault_key:
                lines.append(f'vault_key = "{c.vault_key}"')
    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def _is_first_run():
    """Detect if this is the first run (no admin exists, no setup markers).

    Returns True if:
      1. No data/setup-complete marker exists (Web UI), AND
      2. No conf/.initialized marker exists (CLI init), AND
      3. No users exist in users.conf (or file doesn't exist)
    """
    cfg = load_config()

    # Check Web UI marker (fast path)
    if os.path.isfile(os.path.join(cfg.data_dir, "setup-complete")):
        return False

    # Check CLI init marker (so CLI-initialized systems skip the wizard)
    if os.path.isfile(os.path.join(cfg.conf_dir, ".initialized")):
        return False

    # Check if any users exist
    try:
        users = _load_users(cfg)
        if users:
            return False
    except Exception as e:
        logger.warning(f"_is_first_run: failed to check users: {e}")

    return True


def _get_fleet_vms(cfg):
    """Fetch VM list from PVE cluster, enriched with fleet boundary data.

    Shared by _serve_vms and _serve_fleet_overview to avoid duplication.
    Tries PVE REST API first, falls back to SSH.
    Returns list of VM dicts.
    """
    fb = cfg.fleet_boundaries
    vm_list = []
    for node_ip in _get_discovered_node_ips():
        # Try API first, fall back to SSH
        from freq.modules.pve import _pve_call
        result, ok = _pve_call(cfg, node_ip,
                               api_endpoint="/cluster/resources?type=vm",
                               ssh_command="pvesh get /cluster/resources --type vm --output-format json",
                               timeout=15)
        if ok and result:
            try:
                vms = result if isinstance(result, list) else json.loads(result)
                for v in vms:
                    vmid = v.get("vmid", 0)
                    cat_name, tier = fb.categorize(vmid)
                    tags = get_vm_tags(vmid)
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
                        "tags": tags,
                        "allowed_actions": fb.allowed_actions(vmid),
                        "is_prod": fb.is_prod(vmid) or "prod" in tags,
                    })
            except (json.JSONDecodeError, TypeError):
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
        "/api/vm/push-key": "_serve_vm_push_key",
        "/api/vm/add-disk": "_serve_vm_add_disk",
        "/api/vm/tag": "_serve_vm_tag",
        "/api/vm/clone": "_serve_vm_clone",
        "/api/vm/migrate": "_serve_vm_migrate",
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
        "/api/containers/registry": "_serve_containers_registry",
        "/api/containers/rescan": "_serve_containers_rescan",
        "/api/containers/delete": "_serve_containers_delete",
        "/api/containers/add": "_serve_containers_add",
        "/api/containers/edit": "_serve_containers_edit",
        "/api/containers/compose-up": "_serve_containers_compose_up",
        "/api/containers/compose-down": "_serve_containers_compose_down",
        "/api/containers/compose-view": "_serve_containers_compose_view",
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
        "/api/backup/list": "_serve_backup_list",
        "/api/backup/create": "_serve_backup_create",
        "/api/backup/restore": "_serve_backup_restore",
        "/api/discover": "_serve_discover",
        "/api/gwipe": "_serve_gwipe",
        # Topology & Capacity
        "/api/topology": "_serve_topology",
        "/api/capacity": "_serve_capacity",
        "/api/capacity/snapshot": "_serve_capacity_snapshot",
        "/api/capacity/recommend": "_serve_capacity_recommend",
        # Chaos engineering
        "/api/chaos/types": "_serve_chaos_types",
        "/api/chaos/run": "_serve_chaos_run",
        "/api/chaos/log": "_serve_chaos_log",
        # Federation
        "/api/federation/status": "_serve_federation_status",
        "/api/federation/register": "_serve_federation_register",
        "/api/federation/unregister": "_serve_federation_unregister",
        "/api/federation/poll": "_serve_federation_poll",
        "/api/federation/toggle": "_serve_federation_toggle",
        # Cost tracking
        "/api/cost": "_serve_cost",
        "/api/cost/config": "_serve_cost_config",
        # GitOps config sync
        "/api/gitops/status": "_serve_gitops_status",
        "/api/gitops/sync": "_serve_gitops_sync",
        "/api/gitops/apply": "_serve_gitops_apply",
        "/api/gitops/diff": "_serve_gitops_diff",
        "/api/gitops/log": "_serve_gitops_log",
        "/api/gitops/rollback": "_serve_gitops_rollback",
        "/api/gitops/init": "_serve_gitops_init",
        # Playbook runner
        "/api/playbooks": "_serve_playbooks",
        "/api/playbooks/run": "_serve_playbooks_run",
        "/api/playbooks/step": "_serve_playbooks_step",
        "/api/playbooks/create": "_serve_playbooks_create",
        # Fleet Intelligence
        "/api/fleet/health-score": "_serve_fleet_health_score",
        "/api/fleet/topology-enhanced": "_serve_topology_enhanced",
        "/api/fleet/heatmap": "_serve_fleet_heatmap",
        "/api/snapshots/stale": "_serve_snapshots_stale",
        # Storage & Media Extended
        "/api/storage/health": "_serve_storage_health",
        "/api/media/tdarr": "_serve_media_tdarr",
        "/api/media/downloads/detail": "_serve_media_downloads_detail",
        # Config & Deploy
        "/api/config/view": "_serve_config_view",
        "/api/deploy/log": "_serve_deploy_log",
        "/api/vm/wizard-defaults": "_serve_vm_wizard_defaults",
        # Activity Feed
        "/api/activity": "_serve_activity",
        # HTTP Monitors
        "/api/monitors": "_serve_monitors",
        "/api/monitors/check": "_serve_monitors_check",
        # Docker Fleet
        "/api/docker-fleet": "_serve_docker_fleet",
        # Documentation
        "/api/docs": "_serve_api_docs",
        "/api/openapi.json": "_serve_openapi_json",
        # Server-Sent Events (no auth — dashboard live updates)
        "/api/events": "_serve_events",
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
        # Alerting & Intelligence (Phase 1)
        "/api/alert/rules": "_serve_alert_rules",
        "/api/alert/history": "_serve_alert_history",
        "/api/alert/check": "_serve_alert_check",
        "/api/alert/silences": "_serve_alert_silences",
        "/api/inventory": "_serve_inventory",
        "/api/inventory/hosts": "_serve_inventory_hosts",
        "/api/inventory/vms": "_serve_inventory_vms",
        "/api/inventory/containers": "_serve_inventory_containers",
        "/api/compare": "_serve_compare",
        "/api/baseline/list": "_serve_baseline_list",
        "/api/rollback": "_serve_rollback",
        # Phase 2: Fleet Intelligence
        "/api/report": "_serve_report",
        "/api/trend/data": "_serve_trend_data",
        "/api/trend/snapshot": "_serve_trend_snapshot",
        "/api/sla": "_serve_sla",
        "/api/sla/check": "_serve_sla_check",
        "/api/cert/inventory": "_serve_cert_inventory",
        "/api/dns/inventory": "_serve_dns_inventory",
        # Setup wizard (no auth — only works during first run)
        "/api/setup/status": "_serve_setup_status",
        "/api/setup/create-admin": "_serve_setup_create_admin",
        "/api/setup/configure": "_serve_setup_configure",
        "/api/setup/generate-key": "_serve_setup_generate_key",
        "/api/setup/complete": "_serve_setup_complete",
        "/api/setup/test-ssh": "_serve_setup_test_ssh",
        "/api/setup/reset": "_serve_setup_reset",
    }

    def _dispatch(self):
        """Route request to handler method by path."""
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
        elif path.startswith("/static/"):
            self._serve_static(path)
        elif path.startswith("/api/comms/") or path.startswith("/api/watch/"):
            self._proxy_watchdog()
        else:
            self.send_error(404)

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    # ── Server-Sent Events ────────────────────────────────────────────────

    def _serve_events(self):
        """SSE endpoint — streams live updates to the dashboard.

        Keeps the connection open and pushes events as they arrive from
        background cache probes. Each client gets its own Queue via the
        SSE event bus. Sends keepalive comments every 15s.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = _sse_subscribe()
        try:
            # Initial keepalive so the client knows we're alive
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()

            while True:
                try:
                    event = q.get(timeout=15)
                    line = f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                    self.wfile.write(line.encode())
                    self.wfile.flush()
                except queue.Empty:
                    # Keepalive — prevents proxies/browsers from closing idle connections
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client disconnected
        finally:
            _sse_unsubscribe(q)

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

        # PVE nodes — auto-discovered with fallback to fleet-boundaries
        for pn in _get_discovered_nodes():
            pn_name = pn.get("name", "") if isinstance(pn, dict) else pn.name
            pn_ip = pn.get("ip", "") if isinstance(pn, dict) else pn.ip
            status = "healthy"
            h = health_map.get(pn_name, {})
            if h.get("status") == "unreachable":
                status = "unreachable"
            nodes.append({
                "id": f"pve:{pn_name}", "label": pn_name, "type": "pve",
                "ip": pn_ip, "status": status,
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
            "pve_count": len(_get_discovered_nodes()),
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

    def _serve_capacity_recommend(self):
        """GET /api/capacity/recommend — migration + optimization suggestions."""
        from freq.jarvis.capacity import load_snapshots, compute_projections, recommend_migrations
        cfg = load_config()
        snapshots = load_snapshots(cfg.data_dir)
        projections = compute_projections(snapshots)

        # Get cost data if available
        costs = []
        try:
            from freq.jarvis.cost import load_cost_config, compute_costs
            cost_cfg = load_cost_config(cfg.conf_dir)
            with _bg_lock:
                health = _bg_cache.get("health")
            if health:
                costs = compute_costs(health, {}, cost_cfg)
        except Exception:
            pass

        recs = recommend_migrations(projections, costs)
        self._json_response({
            "recommendations": recs,
            "count": len(recs),
            "critical": sum(1 for r in recs if r["urgency"] == "critical"),
            "warning": sum(1 for r in recs if r["urgency"] == "warning"),
        })

    # ── Chaos Engineering ─────────────────────────────────────────────────

    def _serve_chaos_types(self):
        """List available chaos experiment types."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.chaos import list_experiment_types
        self._json_response({"types": list_experiment_types()})

    def _serve_chaos_run(self):
        """Run a chaos experiment (admin only)."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.chaos import Experiment, run_experiment, result_to_dict
        from freq.core.ssh import run as ssh_run
        cfg = load_config()
        params = _parse_query_flat(self.path)
        name = params.get("name", "").strip()
        exp_type = params.get("type", "").strip()
        target = params.get("target", "").strip()
        service = params.get("service", "")
        try:
            duration = int(params.get("duration", "60"))
        except (ValueError, TypeError):
            self._json_response({"error": "duration must be an integer"}); return

        if not name or not exp_type or not target:
            self._json_response({"error": "Missing name, type, or target parameter"}); return

        exp = Experiment(
            name=name, experiment_type=exp_type, target_host=target,
            target_service=service, duration=duration,
        )
        result = run_experiment(exp, ssh_run, cfg)
        self._json_response({"result": result_to_dict(result)})

    def _serve_chaos_log(self):
        """Return recent chaos experiment log."""
        from freq.jarvis.chaos import load_experiment_log
        cfg = load_config()
        params = _parse_query_flat(self.path)
        try:
            count = min(int(params.get("count", "20")), 50)
        except (ValueError, TypeError):
            count = 20
        log = load_experiment_log(cfg.data_dir, count)
        self._json_response({"experiments": log})

    # ── Federation ────────────────────────────────────────────────────────

    def _serve_federation_status(self):
        """Return federation status and registered sites."""
        from freq.jarvis.federation import load_sites, sites_to_dicts, federation_summary
        cfg = load_config()
        sites = load_sites(cfg.data_dir)
        self._json_response({
            "sites": sites_to_dicts(sites),
            "summary": federation_summary(sites),
        })

    def _serve_federation_register(self):
        """Register a new remote FREQ site."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.federation import register_site
        cfg = load_config()
        params = _parse_query_flat(self.path)
        name = params.get("name", "").strip()
        url = params.get("url", "").strip()
        secret = params.get("secret", "")
        if not name or not url:
            self._json_response({"error": "Missing name or url parameter"}); return
        ok, msg = register_site(cfg.data_dir, name, url, secret)
        self._json_response({"ok": ok, "message": msg})

    def _serve_federation_unregister(self):
        """Remove a registered remote site."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.federation import unregister_site
        cfg = load_config()
        params = _parse_query_flat(self.path)
        name = params.get("name", "").strip()
        if not name:
            self._json_response({"error": "Missing name parameter"}); return
        ok, msg = unregister_site(cfg.data_dir, name)
        self._json_response({"ok": ok, "message": msg})

    def _serve_federation_poll(self):
        """Trigger a poll of all remote sites."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.federation import poll_all_sites, sites_to_dicts, federation_summary
        cfg = load_config()
        sites = poll_all_sites(cfg.data_dir)
        self._json_response({
            "ok": True,
            "sites": sites_to_dicts(sites),
            "summary": federation_summary(sites),
        })

    def _serve_federation_toggle(self):
        """Enable or disable a registered site."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.federation import load_sites, save_sites
        cfg = load_config()
        params = _parse_query_flat(self.path)
        name = params.get("name", "").strip()
        if not name:
            self._json_response({"error": "Missing name parameter"}); return
        sites = load_sites(cfg.data_dir)
        found = False
        for s in sites:
            if s.name == name:
                s.enabled = not s.enabled
                found = True
                break
        if not found:
            self._json_response({"error": f"Site '{name}' not found"}); return
        save_sites(cfg.data_dir, sites)
        self._json_response({"ok": True, "enabled": s.enabled})

    # ── Cost Tracking ────────────────────────────────────────────────────

    def _serve_cost(self):
        """Return fleet cost estimates per host."""
        from freq.jarvis.cost import load_cost_config, compute_costs, costs_to_dicts, fleet_summary
        cfg = load_config()
        cost_cfg = load_cost_config(cfg.conf_dir)
        with _bg_lock:
            health = _bg_cache.get("health")
        if not health:
            self._json_response({"error": "No health data available yet"}, 503); return

        # Try to get iDRAC power data from infra cache
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
        self._json_response({
            "hosts": costs_to_dicts(costs),
            "summary": summary,
        })

    def _serve_cost_config(self):
        """Return current cost configuration."""
        from freq.jarvis.cost import load_cost_config
        cfg = load_config()
        cost_cfg = load_cost_config(cfg.conf_dir)
        self._json_response({
            "rate_per_kwh": cost_cfg.rate_per_kwh,
            "currency": cost_cfg.currency,
            "pue": cost_cfg.pue,
        })

    # ── GitOps Config Sync ──────────────────────────────────────────────

    def _serve_gitops_status(self):
        """Return GitOps sync status and configuration."""
        from freq.jarvis.gitops import load_gitops_config, load_state, state_to_dict
        cfg = load_config()
        go_cfg = load_gitops_config(cfg.conf_dir)
        state = load_state(cfg.data_dir)
        self._json_response({
            "enabled": go_cfg.enabled,
            "repo_url": go_cfg.repo_url,
            "branch": go_cfg.branch,
            "sync_interval": go_cfg.sync_interval,
            "auto_apply": go_cfg.auto_apply,
            "state": state_to_dict(state),
        })

    def _serve_gitops_sync(self):
        """Trigger a sync (fetch) from remote."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.gitops import load_gitops_config, sync, state_to_dict
        cfg = load_config()
        go_cfg = load_gitops_config(cfg.conf_dir)
        if not go_cfg.enabled:
            self._json_response({"error": "GitOps not configured — set repo_url in freq.toml [gitops]"}); return
        state = sync(cfg.data_dir, go_cfg.branch)
        self._json_response({"ok": True, "state": state_to_dict(state)})

    def _serve_gitops_apply(self):
        """Apply pending changes (pull)."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.gitops import load_gitops_config, apply_changes, load_state, state_to_dict
        cfg = load_config()
        go_cfg = load_gitops_config(cfg.conf_dir)
        if not go_cfg.enabled:
            self._json_response({"error": "GitOps not configured"}); return
        ok, msg = apply_changes(cfg.data_dir, go_cfg.branch)
        state = load_state(cfg.data_dir)
        self._json_response({"ok": ok, "message": msg, "state": state_to_dict(state)})

    def _serve_gitops_diff(self):
        """Show diff between local and remote."""
        from freq.jarvis.gitops import load_gitops_config, get_diff, get_diff_full
        cfg = load_config()
        go_cfg = load_gitops_config(cfg.conf_dir)
        params = _parse_query_flat(self.path)
        full = params.get("full", "") == "1"
        if full:
            diff = get_diff_full(cfg.data_dir, go_cfg.branch)
        else:
            diff = get_diff(cfg.data_dir, go_cfg.branch)
        self._json_response({"diff": diff})

    def _serve_gitops_log(self):
        """Return recent commit history."""
        from freq.jarvis.gitops import get_log
        cfg = load_config()
        params = _parse_query_flat(self.path)
        try:
            count = min(int(params.get("count", "20")), 50)
        except (ValueError, TypeError):
            count = 20
        commits = get_log(cfg.data_dir, count)
        self._json_response({"commits": commits})

    def _serve_gitops_rollback(self):
        """Rollback config to a specific commit."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.gitops import rollback
        cfg = load_config()
        params = _parse_query_flat(self.path)
        commit = params.get("commit", "").strip()
        if not commit:
            self._json_response({"error": "Missing commit parameter"}); return
        ok, msg = rollback(cfg.data_dir, commit)
        self._json_response({"ok": ok, "message": msg})

    def _serve_gitops_init(self):
        """Initialize the gitops repo clone."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        from freq.jarvis.gitops import load_gitops_config, init_repo
        cfg = load_config()
        go_cfg = load_gitops_config(cfg.conf_dir)
        if not go_cfg.repo_url:
            self._json_response({"error": "No repo_url configured in freq.toml [gitops]"}); return
        ok, msg = init_repo(cfg.data_dir, go_cfg.repo_url, go_cfg.branch)
        self._json_response({"ok": ok, "message": msg})

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
        params = _parse_query_flat(self.path)
        filename = params.get("filename", "")
        if not filename or '/' in filename or '\\' in filename or '..' in filename:
            self._json_response({"error": "Invalid or missing filename"}); return

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
        params = _parse_query_flat(self.path)
        filename = params.get("filename", "")
        step_idx = params.get("step", "")
        if not filename or '/' in filename or '\\' in filename or '..' in filename:
            self._json_response({"error": "Invalid or missing filename"}); return
        if step_idx == "":
            self._json_response({"error": "Missing step parameter"}); return

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
        params = _parse_query_flat(self.path)
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
        _te = lambda s: s.replace('\\', '\\\\').replace('"', '\\"')
        content = f'[playbook]\nname = "{_te(name)}"\ndescription = "{_te(description)}"\ntrigger = "{_te(trigger)}"\n'
        try:
            with open(path, "w") as f:
                f.write(content)
            self._json_response({"ok": True, "filename": filename})
        except OSError as e:
            self._json_response({"error": str(e)}, 500)

    # ── Fleet Intelligence ──────────────────────────────────────────────

    def _serve_fleet_health_score(self):
        """GET /api/fleet/health-score — composite fleet health score 0-100."""
        with _bg_lock:
            health = _bg_cache.get("health")
            fleet = _bg_cache.get("fleet_overview")

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
                    factors.append({"factor": "hosts_down", "penalty": penalty,
                                    "detail": f"{unhealthy}/{total} hosts unhealthy"})

                # Check resource pressure
                high_ram = sum(1 for h in hosts if _parse_pct(h.get("ram", "")) > 80)
                high_disk = sum(1 for h in hosts if _parse_pct(h.get("disk", "")) > 80)
                if high_ram > 0:
                    penalty = min(15, high_ram * 5)
                    score -= penalty
                    factors.append({"factor": "ram_pressure", "penalty": penalty,
                                    "detail": f"{high_ram} host(s) >80% RAM"})
                if high_disk > 0:
                    penalty = min(15, high_disk * 5)
                    score -= penalty
                    factors.append({"factor": "disk_pressure", "penalty": penalty,
                                    "detail": f"{high_disk} host(s) >80% disk"})

        if fleet and isinstance(fleet, dict):
            vms = fleet.get("vms", [])
            stopped = sum(1 for v in vms if v.get("status") == "stopped")
            total_vms = len(vms)
            if total_vms > 0 and stopped > total_vms * 0.3:
                penalty = min(10, stopped)
                score -= penalty
                factors.append({"factor": "vms_stopped", "penalty": penalty,
                                "detail": f"{stopped}/{total_vms} VMs stopped"})

        score = max(0, min(100, score))
        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

        self._json_response({
            "score": score,
            "grade": grade,
            "factors": factors,
            "max_score": 100,
        })

    def _serve_topology_enhanced(self):
        """GET /api/fleet/topology-enhanced — topology with VLAN grouping."""
        cfg = load_config()
        with _bg_lock:
            fleet = _bg_cache.get("fleet_overview")
            health = _bg_cache.get("health")

        # Build VLAN groups
        vlan_groups = {}
        for vlan in cfg.vlans:
            vlan_groups[vlan.name] = {
                "id": vlan.id,
                "name": vlan.name,
                "subnet": vlan.subnet,
                "gateway": vlan.gateway,
                "hosts": [],
            }

        # Map hosts to VLANs by IP prefix
        health_hosts = health.get("hosts", []) if health and isinstance(health, dict) else []
        for h in health_hosts:
            ip = h.get("ip", "")
            matched = False
            for vlan in cfg.vlans:
                if vlan.prefix and ip.startswith(vlan.prefix):
                    vlan_groups[vlan.name]["hosts"].append({
                        "label": h.get("label", ""),
                        "ip": ip,
                        "type": h.get("type", ""),
                        "status": h.get("status", ""),
                    })
                    matched = True
                    break
            if not matched and "untagged" not in vlan_groups:
                if "untagged" not in vlan_groups:
                    vlan_groups["untagged"] = {
                        "id": 0, "name": "Untagged", "subnet": "",
                        "gateway": "", "hosts": [],
                    }
                vlan_groups["untagged"]["hosts"].append({
                    "label": h.get("label", ""),
                    "ip": ip,
                    "type": h.get("type", ""),
                    "status": h.get("status", ""),
                })

        # PVE nodes and VMs per node
        nodes = {}
        if fleet and isinstance(fleet, dict):
            for vm in fleet.get("vms", []):
                node = vm.get("node", "unknown")
                if node not in nodes:
                    nodes[node] = {"name": node, "vms": 0, "running": 0}
                nodes[node]["vms"] += 1
                if vm.get("status") == "running":
                    nodes[node]["running"] += 1

        self._json_response({
            "vlans": list(vlan_groups.values()),
            "nodes": list(nodes.values()),
            "total_hosts": len(health_hosts),
            "total_vlans": len(cfg.vlans),
        })

    def _serve_fleet_heatmap(self):
        """GET /api/fleet/heatmap — resource usage per host for heatmap viz."""
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
                heatmap.append({
                    "label": h.get("label", ""),
                    "type": h.get("type", ""),
                    "ram_pct": round(ram_pct, 1),
                    "disk_pct": round(disk_pct, 1),
                    "load": round(load, 2),
                    "containers": int(h.get("docker", "0") or 0),
                })

        self._json_response({"hosts": heatmap, "count": len(heatmap)})

    def _serve_snapshots_stale(self):
        """GET /api/snapshots/stale — find VM snapshots older than threshold."""
        cfg = load_config()
        from freq.core.ssh import run as ssh_fn

        params = _parse_query_flat(self.path)
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
                htype="pve", use_sudo=False,
            )
            if r.returncode != 0:
                continue

            for line in r.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) < 2:
                    continue
                vmid = parts[0]
                vm_name = parts[1]

                # Get snapshots for this VM
                sr = ssh_fn(
                    host=node_ip,
                    command=f"sudo qm listsnapshot {vmid} 2>/dev/null | grep -v current | grep -v '^$'",
                    key_path=cfg.ssh_key_path,
                    connect_timeout=cfg.ssh_connect_timeout,
                    command_timeout=15,
                    htype="pve", use_sudo=False,
                )
                if sr.returncode != 0 or not sr.stdout.strip():
                    continue

                for sline in sr.stdout.strip().split("\n"):
                    sline = sline.strip()
                    if not sline or sline.startswith("`") or "current" in sline.lower():
                        continue
                    # Parse snapshot line: "  `->` snapname       timestamp     description"
                    sparts = sline.replace("`->", "").strip().split()
                    if len(sparts) >= 1:
                        snap_name = sparts[0]
                        # Try to extract date
                        snap_date = " ".join(sparts[1:3]) if len(sparts) >= 3 else ""
                        stale.append({
                            "vmid": int(vmid),
                            "vm_name": vm_name,
                            "snapshot": snap_name,
                            "date": snap_date,
                            "node": node_name,
                        })

        self._json_response({
            "stale": stale,
            "count": len(stale),
            "threshold_days": days,
        })

    # ── Storage & Media Extended ────────────────────────────────────────

    def _serve_storage_health(self):
        """GET /api/storage/health — storage pool status across PVE + TrueNAS."""
        cfg = load_config()
        from freq.core.ssh import run as ssh_run_fn

        pools = []
        # PVE storage pools
        for i, node_ip in enumerate(cfg.pve_nodes):
            node_name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"node{i}"
            r = ssh_run_fn(
                host=node_ip,
                command="sudo pvesm status 2>/dev/null | tail -n +2",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=15,
                htype="pve", use_sudo=False,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n"):
                    parts = line.split()
                    if len(parts) >= 7:
                        total_bytes = int(parts[3]) if parts[3].isdigit() else 0
                        used_bytes = int(parts[4]) if parts[4].isdigit() else 0
                        avail_bytes = int(parts[5]) if parts[5].isdigit() else 0
                        pct = round(used_bytes / total_bytes * 100, 1) if total_bytes > 0 else 0
                        pools.append({
                            "name": parts[0],
                            "type": parts[1],
                            "status": parts[2],
                            "total_gb": round(total_bytes / (1024**3), 1),
                            "used_gb": round(used_bytes / (1024**3), 1),
                            "avail_gb": round(avail_bytes / (1024**3), 1),
                            "used_pct": pct,
                            "node": node_name,
                            "source": "pve",
                        })

        # TrueNAS pools (if configured)
        if cfg.truenas_ip:
            r = ssh_run_fn(
                host=cfg.truenas_ip,
                command="zpool list -Hp 2>/dev/null | head -10",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=15,
                htype="truenas", use_sudo=False,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n"):
                    parts = line.split("\t")
                    if len(parts) >= 4:
                        try:
                            total = int(parts[1])
                            used = int(parts[2])
                            pools.append({
                                "name": parts[0],
                                "type": "zfs",
                                "status": parts[9] if len(parts) > 9 else "unknown",
                                "total_gb": round(total / (1024**3), 1),
                                "used_gb": round(used / (1024**3), 1),
                                "avail_gb": round((total - used) / (1024**3), 1),
                                "used_pct": round(used / total * 100, 1) if total > 0 else 0,
                                "node": "truenas",
                                "source": "truenas",
                            })
                        except (ValueError, IndexError):
                            pass

        self._json_response({
            "pools": pools,
            "count": len(pools),
            "total_tb": round(sum(p["total_gb"] for p in pools) / 1024, 2),
            "used_tb": round(sum(p["used_gb"] for p in pools) / 1024, 2),
        })

    def _serve_media_tdarr(self):
        """GET /api/media/tdarr — Tdarr transcoding status."""
        cfg = load_config()
        # Tdarr is typically on a docker host — query via container exec or API
        tdarr_data = {"status": "not_configured", "queue": 0, "processed": 0, "errors": 0}

        # Check if any container named tdarr exists
        with _bg_lock:
            health = _bg_cache.get("health")
        if health:
            for h in health.get("hosts", []):
                if h.get("status") != "healthy":
                    continue
                from freq.core.ssh import run as ssh_fn
                r = ssh_fn(
                    host=h.get("ip", ""),
                    command="docker inspect tdarr 2>/dev/null | grep -c '\"Running\": true'",
                    key_path=cfg.ssh_key_path,
                    connect_timeout=3,
                    command_timeout=10,
                    htype=h.get("type", "linux"), use_sudo=False,
                )
                if r.returncode == 0 and r.stdout.strip() == "1":
                    tdarr_data["status"] = "running"
                    tdarr_data["host"] = h.get("label", "")
                    break

        self._json_response(tdarr_data)

    def _serve_media_downloads_detail(self):
        """GET /api/media/downloads/detail — enhanced download queue info."""
        cfg = load_config()
        # Re-use existing media downloads but add more detail
        with _bg_lock:
            health = _bg_cache.get("health")

        downloads = {"active": [], "queued": [], "history": [], "total": 0}

        if health:
            from freq.core.ssh import run as ssh_fn
            for h in health.get("hosts", []):
                if h.get("type") != "docker" or h.get("status") != "healthy":
                    continue
                # Check SABnzbd or NZBGet queue
                r = ssh_fn(
                    host=h.get("ip", ""),
                    command="docker logs --tail 5 sabnzbd 2>/dev/null || docker logs --tail 5 nzbget 2>/dev/null || echo 'no-dl-client'",
                    key_path=cfg.ssh_key_path,
                    connect_timeout=3,
                    command_timeout=10,
                    htype="docker", use_sudo=False,
                )
                if r.returncode == 0 and "no-dl-client" not in r.stdout:
                    downloads["total"] = len([l for l in r.stdout.split("\n") if l.strip()])
                break

        self._json_response(downloads)

    # ── Config & Deploy ────────────────────────────────────────────────

    def _serve_config_view(self):
        """GET /api/config/view — read-only view of freq.toml settings."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return
        cfg = load_config()
        # Return safe config values (no secrets)
        safe_config = {
            "version": cfg.version,
            "brand": cfg.brand,
            "build": cfg.build,
            "debug": cfg.debug,
            "ssh_service_account": cfg.ssh_service_account,
            "ssh_connect_timeout": cfg.ssh_connect_timeout,
            "ssh_max_parallel": cfg.ssh_max_parallel,
            "ssh_mode": getattr(cfg, "ssh_mode", "sudo"),
            "pve_nodes": cfg.pve_node_names,
            "vm_defaults": {
                "cores": cfg.vm_default_cores,
                "ram": cfg.vm_default_ram,
                "disk": cfg.vm_default_disk,
                "cpu": cfg.vm_cpu,
                "machine": cfg.vm_machine,
            },
            "cluster_name": cfg.cluster_name,
            "timezone": cfg.timezone,
            "dashboard_port": cfg.dashboard_port,
            "nic_bridge": cfg.nic_bridge,
            "hosts_count": len(cfg.hosts),
            "vlans_count": len(cfg.vlans),
            "monitors_count": len(cfg.monitors),
        }
        self._json_response({"config": safe_config})

    def _serve_deploy_log(self):
        """GET /api/deploy/log — recent git commits from the install dir."""
        cfg = load_config()
        import subprocess
        try:
            r = subprocess.run(
                ["git", "log", "--oneline", "-20", "--format=%H|%s|%ar"],
                cwd=cfg.install_dir,
                capture_output=True, text=True, timeout=10,
            )
            commits = []
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n"):
                    parts = line.split("|", 2)
                    if len(parts) >= 3:
                        commits.append({
                            "hash": parts[0][:8],
                            "message": parts[1],
                            "ago": parts[2],
                        })
            self._json_response({"commits": commits, "count": len(commits)})
        except Exception as e:
            self._json_response({"commits": [], "count": 0, "error": str(e)})

    def _serve_vm_wizard_defaults(self):
        """GET /api/vm/wizard-defaults — defaults for VM creation wizard."""
        cfg = load_config()
        profiles = getattr(cfg, "template_profiles", {})
        self._json_response({
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
        })

    # ── Activity Feed ──────────────────────────────────────────────────

    def _serve_activity(self):
        """GET /api/activity — recent system events."""
        params = _parse_query_flat(self.path)
        try:
            limit = min(int(params.get("limit", "50")), 200)
        except (ValueError, TypeError):
            limit = 50
        with _activity_lock:
            events = list(_activity_feed)[:limit]
        self._json_response({"events": events, "count": len(events)})

    # ── HTTP Monitors ────────────────────────────────────────────────────

    def _serve_monitors(self):
        """GET /api/monitors — list configured HTTP monitors."""
        cfg = load_config()
        monitors = []
        for m in cfg.monitors:
            monitors.append({
                "name": m.name,
                "url": m.url,
                "interval": m.interval,
                "timeout": m.timeout,
                "expected_status": m.expected_status,
                "method": m.method,
            })
        self._json_response({"monitors": monitors, "count": len(monitors)})

    def _serve_monitors_check(self):
        """GET /api/monitors/check — run all HTTP checks now."""
        cfg = load_config()
        if not cfg.monitors:
            self._json_response({"results": [], "count": 0})
            return
        from freq.jarvis.patrol import check_http_monitors
        results = check_http_monitors(cfg.monitors)
        ok = sum(1 for r in results if r["ok"])
        self._json_response({
            "results": results,
            "count": len(results),
            "healthy": ok,
            "unhealthy": len(results) - ok,
        })

    # ── Docker Fleet ────────────────────────────────────────────────────

    def _serve_docker_fleet(self):
        """GET /api/docker-fleet — fleet-wide container inventory."""
        cfg = load_config()
        from freq.core.resolve import by_type
        from freq.core.ssh import run_many as ssh_run_many_fn

        docker_hosts = by_type(cfg.hosts, "docker")
        if not docker_hosts:
            self._json_response({"hosts": [], "total_containers": 0})
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
            r = results.get(host.label)
            containers = []
            if r and r.returncode == 0 and r.stdout.strip():
                for line in r.stdout.strip().split("\n"):
                    parts = line.split("|")
                    containers.append({
                        "name": parts[0] if len(parts) > 0 else "?",
                        "image": parts[1] if len(parts) > 1 else "",
                        "status": parts[2] if len(parts) > 2 else "",
                    })
                total += len(containers)
            hosts_data.append({
                "label": host.label,
                "ip": host.ip,
                "containers": containers,
                "count": len(containers),
                "reachable": r is not None and r.returncode == 0 if r else False,
            })

        self._json_response({
            "hosts": hosts_data,
            "total_containers": total,
            "total_hosts": len(docker_hosts),
        })

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
            "pve_nodes_configured": bool(cfg.pve_nodes),
        })

    def _serve_setup_create_admin(self):
        """Create admin account during first-run setup.

        Accepts POST with JSON body (preferred) or GET with query params (legacy).
        POST body: {"username": "...", "password": "..."}
        """
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        # Prefer POST body (credentials should not be in URLs)
        username = ""
        password = ""
        if self.command == "POST":
            try:
                body = self._request_body()
                username = body.get("username", "").strip().lower()
                password = body.get("password", "")
            except Exception:
                pass
        if not username or not password:
            # Fall back to query params for legacy compatibility
            params = _parse_query(self)
            username = username or params.get("username", [""])[0].strip().lower()
            password = password or params.get("password", [""])[0]

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
        """Save cluster configuration during first-run setup.

        Updates freq.toml in-place, preserving existing config sections.
        Only modifies cluster_name, timezone, and pve.nodes.
        """
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        params = _parse_query(self)
        cluster_name = params.get("cluster_name", [""])[0].strip()
        timezone = params.get("timezone", ["UTC"])[0].strip()
        pve_nodes = params.get("pve_nodes", [""])[0].strip()

        cfg = load_config()

        toml_path = os.path.join(cfg.conf_dir, "freq.toml")
        os.makedirs(cfg.conf_dir, exist_ok=True)

        # Read existing config to preserve all sections
        from freq.modules.init_cmd import _update_toml_value
        try:
            content = ""
            if os.path.isfile(toml_path):
                with open(toml_path, "r") as f:
                    content = f.read()

            # If empty/missing, seed from template
            if not content.strip():
                template = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "data", "conf-templates", "freq.toml.example",
                )
                if os.path.isfile(template):
                    with open(template, "r") as f:
                        content = f.read()
                else:
                    content = "[freq]\n\n[pve]\nnodes = []\n"

            # Update only the targeted keys (preserves everything else)
            if cluster_name:
                content = _update_toml_value(content, "cluster_name", cluster_name)
            content = _update_toml_value(content, "timezone", timezone)

            if pve_nodes:
                node_ips = [ip.strip() for ip in pve_nodes.split(",") if ip.strip()]
                if node_ips:
                    content = _update_toml_value(content, "nodes", node_ips)

            with open(toml_path, "w") as f:
                f.write(content)

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

        cfg = load_config()
        data_dir = cfg.data_dir
        os.makedirs(data_dir, exist_ok=True)
        marker = os.path.join(data_dir, "setup-complete")

        try:
            with open(marker, "w") as f:
                f.write(f"Setup completed: {datetime.datetime.now().isoformat()}\n")

            # Also write CLI-compatible .initialized marker so freq init --check passes
            try:
                os.makedirs(cfg.conf_dir, exist_ok=True)
                init_marker = os.path.join(cfg.conf_dir, ".initialized")
                if not os.path.isfile(init_marker):
                    from freq import __version__
                    with open(init_marker, "w") as f:
                        f.write(f"PVE FREQ {__version__} — web setup {datetime.datetime.now().isoformat()}\n")
            except OSError:
                pass  # Non-fatal — web marker is primary

            # Auto-trigger hosts sync so fleet populates immediately
            try:
                threading.Thread(target=_bg_sync_hosts, daemon=True).start()
            except Exception as e:
                logger.warning(f"Post-setup hosts sync failed to start: {e}")

            self._json_response({"ok": True, "message": "Setup complete — redirecting to dashboard"})
        except OSError as e:
            self._json_response({"error": f"Failed to write setup marker: {e}"}, 500)

    def _serve_setup_test_ssh(self):
        """Test SSH connectivity to a PVE node during setup."""
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        params = _parse_query(self)
        host = params.get("host", [""])[0].strip()

        if not host:
            self._json_response({"error": "host parameter required"})
            return

        # Basic IP/hostname validation
        from freq.core import validate as _val
        if not (_val.ip(host) or _val.hostname(host)):
            self._json_response({"error": f"Invalid host: {host}"})
            return

        cfg = load_config()
        key_path = cfg.ssh_key_path
        user = cfg.ssh_service_account

        try:
            r = ssh_single(
                host=host, command="pvesh get /version --output-format json",
                key_path=key_path, connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=10, htype="pve", use_sudo=True, cfg=cfg,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    version_info = json.loads(r.stdout)
                    pve_version = version_info.get("version", "unknown")
                except json.JSONDecodeError:
                    pve_version = "unknown"
                self._json_response({
                    "ok": True, "host": host, "user": user,
                    "pve_version": pve_version,
                })
            else:
                err = r.stderr.strip()[:200] if r.stderr else "Connection failed"
                self._json_response({
                    "ok": False, "host": host, "user": user, "error": err,
                })
        except Exception as e:
            self._json_response({"ok": False, "host": host, "error": str(e)[:200]})

    def _serve_setup_reset(self):
        """Reset setup wizard — admin only. Deletes setup-complete marker."""
        cfg = load_config()

        # This endpoint requires admin auth (NOT gated by _is_first_run)
        role, err = _check_session_role(self, min_role="admin")
        if err:
            self._json_response({"error": err}, 403)
            return

        data_dir = cfg.data_dir
        marker = os.path.join(data_dir, "setup-complete")

        try:
            if os.path.isfile(marker):
                os.remove(marker)
            self._json_response({"ok": True, "message": "Setup wizard re-enabled"})
        except OSError as e:
            self._json_response({"error": f"Failed to reset setup: {e}"}, 500)

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
        """Master endpoint — serves from background cache (instant)."""
        with _bg_lock:
            cached = _bg_cache.get("fleet_overview")
        if cached:
            self._json_response(cached)
        else:
            # First request before background probe completes — return skeleton
            self._json_response({
                "vms": [], "vm_nics": {}, "physical": [], "pve_nodes": [],
                "vlans": [], "nic_profiles": {}, "categories": {},
                "summary": {"total_vms": 0, "running": 0, "stopped": 0,
                             "prod_count": 0, "lab_count": 0, "template_count": 0},
                "duration": 0, "_loading": True,
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
            "pve_nodes": len(_get_discovered_nodes()),
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
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    # ── Static assets ─────────────────────────────────────────────────

    _STATIC_TYPES = {
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }

    def _serve_static(self, path: str):
        """Serve static web assets from freq/data/web/."""
        # /static/css/app.css → css/app.css
        rel = path[len("/static/"):]
        # Block path traversal
        if ".." in rel or rel.startswith("/"):
            self.send_error(403)
            return
        try:
            from freq.modules.web_ui import _read_asset
            body = _read_asset(rel).encode("utf-8")
        except (FileNotFoundError, TypeError):
            self.send_error(404)
            return
        ext = os.path.splitext(rel)[1].lower()
        content_type = self._STATIC_TYPES.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
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
        if is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges,
                             vm_tags=get_vm_tags(vmid)):
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
            ssh_cmds = {"start": f"qm start {vmid}", "stop": f"qm stop {vmid}",
                        "reset": f"qm reset {vmid}", "status": f"qm status {vmid}"}
            api_actions = {"start": ("start", "POST"), "stop": ("stop", "POST"),
                          "reset": ("reset", "POST"), "status": ("current", "GET")}
            ssh_cmd = ssh_cmds.get(action, ssh_cmds["status"])
            api_action, api_method = api_actions.get(action, api_actions["status"])

            # Try API first: resolve node name for this VM
            from freq.modules.pve import _pve_api_call
            ok = False
            result = ""
            if getattr(cfg, "pve_api_token_id", "") and getattr(cfg, "pve_api_token_secret", ""):
                res_data, res_ok = _pve_api_call(cfg, node_ip,
                                                 "/cluster/resources?type=vm",
                                                 timeout=10)
                if res_ok and isinstance(res_data, list):
                    vm_entry = next((v for v in res_data if v.get("vmid") == vmid), None)
                    if vm_entry and vm_entry.get("node"):
                        result, ok = _pve_api_call(
                            cfg, node_ip,
                            f"/nodes/{vm_entry['node']}/qemu/{vmid}/status/{api_action}",
                            method=api_method, timeout=60)
            if not ok:
                result, ok = _pve_cmd(cfg, node_ip, ssh_cmd, timeout=60)
            output = result if isinstance(result, str) else json.dumps(result) if result else ""
            self._json_response({"ok": ok, "vmid": vmid, "action": action,
                                "output": output, "error": "" if ok else output})
        except Exception as e:
            self._json_response({"error": f"PVE operation failed: {e}"})

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
            # Host is DOWN only if truly unreachable (timeout, refused, no route)
            err = r.stderr or "" if r else ""
            down = r is None or r.returncode == 124 or "Connection timed out" in err or "Connection refused" in err or "No route to host" in err
            reachable = not down
            keys.append({"host": h.label, "ip": h.ip, "reachable": reachable,
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
            "pve_nodes_discovered": [n.get("name", "") for n in _get_discovered_nodes()],
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
        for node_ip in _get_discovered_node_ips():
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
            resolved_ip = _resolve_container_vm_ip(vm)
            r = ssh_single(
                host=resolved_ip,
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
                    "vm_ip": resolved_ip, "port": container.port,
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
            resolved_ip = _resolve_container_vm_ip(vm)
            for cname, container in vm.containers.items():
                if not container.port or not container.api_path:
                    skipped += 1
                    continue
                r = ssh_single(
                    host=resolved_ip,
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
            resolved_ip = _resolve_container_vm_ip(vm)
            for cname, container in vm.containers.items():
                if "qbittorrent" in cname.lower():
                    # qBit needs session cookie auth — try login first
                    qb_user = vault_get(cfg, "DEFAULT", "qbittorrent_user") or "admin"
                    qb_pass = vault_get(cfg, "DEFAULT", "qbittorrent_password") or ""
                    if not qb_pass:
                        logger.warn("qBittorrent password not in vault — skipping download check")
                        continue
                    r = ssh_single(
                        host=resolved_ip,
                        command=f"curl -s -c /tmp/qb.cookie --connect-timeout 3 "
                                f"'http://localhost:{container.port}/api/v2/auth/login' "
                                f"-d 'username={qb_user}&password={qb_pass}' && "
                                f"curl -s -b /tmp/qb.cookie --connect-timeout 3 "
                                f"'http://localhost:{container.port}/api/v2/torrents/info?filter=downloading'",
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
                        host=resolved_ip,
                        command=f"curl -s --connect-timeout 3 "
                                f"'http://localhost:{container.port}/api?mode=queue&apikey={api_key}&output=json'",
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
                host=_resolve_container_vm_ip(vm),
                command=f"curl -s --connect-timeout 3 "
                        f"'http://localhost:{container.port}/api/v2?apikey={api_key}&cmd=get_activity'",
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
        """Aggregate media dashboard data — from health cache (instant)."""
        cfg = load_config()

        # Derive from health cache — already has docker counts per host
        with _bg_lock:
            health = _bg_cache.get("health")

        total = sum(len(vm.containers) for vm in cfg.container_vms.values())
        running = 0
        if health and "hosts" in health:
            docker_ips = {_resolve_container_vm_ip(vm) for vm in cfg.container_vms.values()}
            for h in health["hosts"]:
                if h.get("ip") in docker_ips and h.get("status") != "unreachable":
                    try:
                        running += int(h.get("docker", "0"))
                    except (ValueError, TypeError):
                        pass
        elif not health:
            # No cache yet — do a quick live count as fallback
            for vm in cfg.container_vms.values():
                r = ssh_single(
                    host=_resolve_container_vm_ip(vm),
                    command="docker ps --format '{{.Names}}' 2>/dev/null | wc -l",
                    key_path=cfg.ssh_key_path, connect_timeout=3,
                    command_timeout=10, htype="docker", use_sudo=False,
                )
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
            host=_resolve_container_vm_ip(vm), command=f"docker restart {container.name}",
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
            host=_resolve_container_vm_ip(vm), command=f"docker logs --tail {lines} {container.name} 2>&1",
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
            host=_resolve_container_vm_ip(vm),
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

    # ── Container Registry Management ──────────────────────────────────

    def _serve_containers_registry(self):
        """List all registered containers from containers.toml."""
        cfg = load_config()
        entries = []
        for vm in sorted(cfg.container_vms.values(), key=lambda v: v.vm_id):
            for cname, c in vm.containers.items():
                entries.append({
                    "name": cname, "vm_id": vm.vm_id, "vm_label": vm.label,
                    "vm_ip": vm.ip, "port": c.port, "api_path": c.api_path,
                })
        self._json_response({"containers": entries})

    def _serve_containers_rescan(self):
        """SSH into all docker VMs, discover running containers, update registry."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        cfg = load_config()
        discovered = {}  # vm_id -> list of container names
        for vm in cfg.container_vms.values():
            r = ssh_single(
                host=_resolve_container_vm_ip(vm),
                command="docker ps -a --format '{{.Names}}' 2>/dev/null",
                key_path=cfg.ssh_key_path, connect_timeout=3,
                command_timeout=10, htype="docker", use_sudo=False,
            )
            names = []
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.strip().split("\n"):
                    n = line.strip()
                    if n:
                        names.append(n)
            discovered[vm.vm_id] = names

        # Compare: find stale (registered but not on any VM) and new (on VM but not registered)
        registered = {}
        for vm in cfg.container_vms.values():
            for cname in vm.containers:
                registered[f"{vm.vm_id}:{cname}"] = {"name": cname, "vm_id": vm.vm_id, "vm_label": vm.label}

        stale = []
        for key, info in registered.items():
            vm_id = info["vm_id"]
            cname = info["name"]
            vm_containers = discovered.get(vm_id, [])
            # Check if container exists (case-insensitive partial match)
            found = any(cname.lower() in dc.lower() or dc.lower() in cname.lower() for dc in vm_containers)
            if not found:
                stale.append(info)

        new_found = []
        for vm_id, names in discovered.items():
            vm = cfg.container_vms.get(vm_id)
            if not vm:
                continue
            for dc in names:
                # Check if already registered
                already = any(dc.lower() in cname.lower() or cname.lower() in dc.lower()
                              for cname in vm.containers)
                if not already:
                    new_found.append({"name": dc, "vm_id": vm_id, "vm_label": vm.label})

        self._json_response({
            "discovered": {str(k): v for k, v in discovered.items()},
            "stale": stale,
            "new": new_found,
            "vm_count": len(cfg.container_vms),
        })

    def _serve_containers_delete(self):
        """Remove a container from the registry (containers.toml)."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query_flat(self.path)
        name = query.get("name", "")
        try:
            vm_id = int(query.get("vm_id", "0"))
        except (ValueError, TypeError):
            self._json_response({"error": "Invalid vm_id"}); return
        if not name or not vm_id:
            self._json_response({"error": "name and vm_id required"}); return

        cfg = load_config()
        toml_path = os.path.join(cfg.conf_dir, "containers.toml")
        vm = cfg.container_vms.get(vm_id)
        if not vm:
            self._json_response({"error": f"VM {vm_id} not in registry"}); return
        if name not in vm.containers:
            self._json_response({"error": f"Container {name} not found on VM {vm_id}"}); return

        del vm.containers[name]
        _write_containers_toml(toml_path, cfg.container_vms)
        self._json_response({"ok": True, "deleted": name, "vm_id": vm_id})

    def _serve_containers_add(self):
        """Add a container to the registry."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query_flat(self.path)
        name = query.get("name", "").strip()
        try:
            vm_id = int(query.get("vm_id", "0"))
        except (ValueError, TypeError):
            self._json_response({"error": "Invalid vm_id"}); return
        try:
            port = int(query.get("port", "0"))
        except (ValueError, TypeError):
            port = 0
        if not name or not vm_id:
            self._json_response({"error": "name and vm_id required"}); return

        cfg = load_config()
        toml_path = os.path.join(cfg.conf_dir, "containers.toml")
        vm = cfg.container_vms.get(vm_id)
        if not vm:
            self._json_response({"error": f"VM {vm_id} not in registry"}); return
        if name in vm.containers:
            self._json_response({"error": f"Container {name} already registered on VM {vm_id}"}); return

        from freq.core.config import Container
        vm.containers[name] = Container(name=name, vm_id=vm_id, port=port)
        _write_containers_toml(toml_path, cfg.container_vms)
        self._json_response({"ok": True, "added": name, "vm_id": vm_id})

    def _serve_containers_edit(self):
        """Edit a container in the registry (move VM, change port/api_path)."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        query = _parse_query_flat(self.path)
        name = query.get("name", "").strip()
        try:
            old_vm_id = int(query.get("old_vm_id", "0"))
        except (ValueError, TypeError):
            self._json_response({"error": "Invalid old_vm_id"}); return
        try:
            new_vm_id = int(query.get("new_vm_id", "0"))
        except (ValueError, TypeError):
            self._json_response({"error": "Invalid new_vm_id"}); return
        try:
            port = int(query.get("port", "0"))
        except (ValueError, TypeError):
            port = 0
        api_path = query.get("api_path", "")
        if not name or not old_vm_id or not new_vm_id:
            self._json_response({"error": "name, old_vm_id, new_vm_id required"}); return

        cfg = load_config()
        toml_path = os.path.join(cfg.conf_dir, "containers.toml")
        old_vm = cfg.container_vms.get(old_vm_id)
        if not old_vm or name not in old_vm.containers:
            self._json_response({"error": f"Container {name} not found on VM {old_vm_id}"}); return

        if old_vm_id == new_vm_id:
            # Same VM — just update fields
            c = old_vm.containers[name]
            c.port = port
            c.api_path = api_path
        else:
            # Moving to a different VM
            new_vm = cfg.container_vms.get(new_vm_id)
            if not new_vm:
                self._json_response({"error": f"VM {new_vm_id} not in registry"}); return
            if name in new_vm.containers:
                self._json_response({"error": f"Container {name} already exists on VM {new_vm_id}"}); return
            from freq.core.config import Container
            new_vm.containers[name] = Container(
                name=name, vm_id=new_vm_id, port=port, api_path=api_path,
            )
            del old_vm.containers[name]

        _write_containers_toml(toml_path, cfg.container_vms)
        self._json_response({"ok": True, "name": name, "vm_id": new_vm_id})

    def _serve_containers_compose_up(self):
        """Start a Docker Compose stack on a container VM."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        cfg = load_config()
        query = _parse_query_flat(self.path)
        vm_id = int(query.get("vm_id", "0"))

        vm = cfg.container_vms.get(vm_id)
        if not vm:
            self._json_response({"error": f"VM {vm_id} not in container registry"}); return

        compose_path = vm.compose_path or f"{cfg.docker_config_base}/{vm.label}"
        host_ip = _resolve_container_vm_ip(vm)
        cmd = f"cd {compose_path} && docker compose up -d"
        r = ssh_single(
            host=host_ip, command=cmd,
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=120, htype="docker", use_sudo=False,
        )
        self._json_response({
            "ok": r.returncode == 0, "vm_id": vm_id, "vm": vm.label,
            "output": (r.stdout or "")[:1000],
            "error": (r.stderr or "")[:500] if r.returncode != 0 else "",
        })

    def _serve_containers_compose_down(self):
        """Stop a Docker Compose stack on a container VM."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        cfg = load_config()
        query = _parse_query_flat(self.path)
        vm_id = int(query.get("vm_id", "0"))

        vm = cfg.container_vms.get(vm_id)
        if not vm:
            self._json_response({"error": f"VM {vm_id} not in container registry"}); return

        compose_path = vm.compose_path or f"{cfg.docker_config_base}/{vm.label}"
        host_ip = _resolve_container_vm_ip(vm)
        cmd = f"cd {compose_path} && docker compose down"
        r = ssh_single(
            host=host_ip, command=cmd,
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=120, htype="docker", use_sudo=False,
        )
        self._json_response({
            "ok": r.returncode == 0, "vm_id": vm_id, "vm": vm.label,
            "output": (r.stdout or "")[:1000],
            "error": (r.stderr or "")[:500] if r.returncode != 0 else "",
        })

    def _serve_containers_compose_view(self):
        """Read and return the docker-compose.yml for a container VM."""
        cfg = load_config()
        query = _parse_query_flat(self.path)
        vm_id = int(query.get("vm_id", "0"))

        vm = cfg.container_vms.get(vm_id)
        if not vm:
            self._json_response({"error": f"VM {vm_id} not in container registry"}); return

        compose_path = vm.compose_path or f"{cfg.docker_config_base}/{vm.label}"
        host_ip = _resolve_container_vm_ip(vm)
        cmd = f"cat {compose_path}/docker-compose.yml 2>/dev/null || cat {compose_path}/compose.yml 2>/dev/null"
        r = ssh_single(
            host=host_ip, command=cmd,
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=10, htype="docker", use_sudo=False,
        )
        if r.returncode == 0 and r.stdout:
            self._json_response({
                "ok": True, "vm_id": vm_id, "vm": vm.label,
                "content": r.stdout[:10000],
            })
        else:
            self._json_response({
                "ok": False, "vm_id": vm_id,
                "error": "Compose file not found or not readable",
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

    def _serve_vm_push_key(self):
        """Push the freq SSH key to a target VM's freq-admin authorized_keys."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return
        cfg = load_config()
        query = _parse_query_flat(self.path)
        target_ip = query.get("ip", "")
        if not target_ip or not valid_ip(target_ip):
            self._json_response({"error": "Valid IP required"}); return

        # Read the public key
        pub_path = cfg.ssh_key_path + ".pub"
        if not os.path.isfile(pub_path):
            self._json_response({"error": f"Public key not found: {pub_path}"}); return
        with open(pub_path) as f:
            pubkey = f.read().strip()
        if not pubkey:
            self._json_response({"error": "Public key file is empty"}); return

        # SSH as service account (who has sudo) to write the key
        svc_account = self.cfg.ssh_service_account
        escaped_key = pubkey.replace('"', '\\"')
        cmd = (
            f'sudo mkdir -p /home/{svc_account}/.ssh && '
            f'echo "{escaped_key}" | sudo tee /home/{svc_account}/.ssh/authorized_keys > /dev/null && '
            f'sudo chown -R {svc_account}:{svc_account} /home/{svc_account}/.ssh && '
            f'sudo chmod 700 /home/{svc_account}/.ssh && '
            f'sudo chmod 600 /home/{svc_account}/.ssh/authorized_keys'
        )
        r = ssh_single(
            host=target_ip, command=cmd,
            user=svc_account, key_path=self.cfg.ssh_key_path,
            connect_timeout=5, command_timeout=15, htype="linux", use_sudo=False,
        )
        if r.returncode != 0:
            self._json_response({"error": f"Key push failed: {r.stderr or r.stdout}"}); return

        # Verify: try connecting as freq-admin with the freq key
        r2 = ssh_single(
            host=target_ip, command="echo ok",
            key_path=cfg.ssh_key_path, connect_timeout=3,
            command_timeout=5, htype="docker", use_sudo=False,
        )
        verified = r2.returncode == 0 and "ok" in (r2.stdout or "")
        self._json_response({"ok": True, "verified": verified, "ip": target_ip})

    def _serve_vm_add_disk(self):
        """Add a disk to a VM."""
        cfg = load_config()
        params = _parse_query(self)
        vmid = int(params.get("vmid", ["0"])[0])
        size = params.get("size", [""])[0]  # e.g. "32G"
        storage = params.get("storage", [""])[0]

        if not vmid or not size:
            self._json_response({"error": "vmid and size required"}); return

        allowed, err = _check_vm_permission(cfg, vmid, "configure")
        if not allowed:
            self._json_response({"error": err}); return

        # Validate size format
        import re as _re
        if not _re.match(r'^\d+[GMTgmt]?$', size):
            self._json_response({"error": "Invalid size (e.g. '32G', '100')"}); return

        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return

            # Find next available scsi slot
            stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
            if not ok:
                self._json_response({"error": f"Cannot read VM config: {stdout}"}); return

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
            self._json_response({
                "ok": ok, "vmid": vmid, "disk": f"scsi{next_idx}",
                "size": size, "storage": storage_target,
                "error": stdout if not ok else "",
            })
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_tag(self):
        """Set PVE tags on a VM."""
        cfg = load_config()
        params = _parse_query(self)
        vmid = int(params.get("vmid", ["0"])[0])
        tags = params.get("tags", [""])[0]  # comma-separated

        if not vmid:
            self._json_response({"error": "vmid required"}); return

        allowed, err = _check_vm_permission(cfg, vmid, "configure")
        if not allowed:
            self._json_response({"error": err}); return

        # Validate tag names
        import re as _re
        if tags:
            for tag in tags.split(","):
                tag = tag.strip()
                if tag and not _re.match(r'^[a-zA-Z0-9_-]+$', tag):
                    self._json_response({"error": f"Invalid tag name: {tag}"}); return

        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return

            # PVE uses semicolon-separated tags
            pve_tags = ";".join(t.strip() for t in tags.split(",") if t.strip()) if tags else ""
            cmd = f'qm set {vmid} --tags "{pve_tags}"'
            stdout, ok = _pve_cmd(cfg, node_ip, cmd)
            self._json_response({
                "ok": ok, "vmid": vmid, "tags": tags,
                "error": stdout if not ok else "",
            })
        except Exception as e:
            self._json_response({"error": f"SSH operation failed: {e}"})

    def _serve_vm_clone(self):
        """Clone a VM. Dedicated endpoint replacing /api/vm/create?clone workaround."""
        cfg = load_config()
        params = _parse_query(self)
        source_vmid = int(params.get("vmid", ["0"])[0])
        name = params.get("name", [""])[0]
        target_node = params.get("target_node", [""])[0]
        full = params.get("full", ["1"])[0] == "1"

        if not source_vmid:
            self._json_response({"error": "vmid (source) required"}); return

        allowed, err = _check_vm_permission(cfg, source_vmid, "view")
        if not allowed:
            self._json_response({"error": err}); return

        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return

            # Get next available VMID
            stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
            if not ok:
                self._json_response({"error": "Cannot get next VMID"}); return
            new_vmid = stdout.strip()

            parts = [f"qm clone {source_vmid} {new_vmid}"]
            if name:
                from freq.core.validate import shell_safe_name
                if not shell_safe_name(name):
                    self._json_response({"error": f"Invalid VM name: {name}"}); return
                parts.append(f"--name {name}")
            if target_node:
                parts.append(f"--target {target_node}")
            if full:
                parts.append("--full")

            cmd = " ".join(parts)
            stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=300)
            self._json_response({
                "ok": ok, "source_vmid": source_vmid, "new_vmid": int(new_vmid),
                "name": name, "full_clone": full,
                "error": stdout if not ok else "",
            })
        except Exception as e:
            self._json_response({"error": f"Clone failed: {e}"})

    def _serve_vm_migrate(self):
        """Migrate a VM to another node."""
        cfg = load_config()
        params = _parse_query(self)
        vmid = int(params.get("vmid", ["0"])[0])
        target_node = params.get("target_node", [""])[0]
        online = params.get("online", ["0"])[0] == "1"

        if not vmid or not target_node:
            self._json_response({"error": "vmid and target_node required"}); return

        allowed, err = _check_vm_permission(cfg, vmid, "migrate")
        if not allowed:
            self._json_response({"error": err}); return

        import re as _re
        if not _re.match(r'^[a-zA-Z0-9_-]+$', target_node):
            self._json_response({"error": f"Invalid node name: {target_node}"}); return

        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return

            parts = [f"qm migrate {vmid} {target_node}"]
            if online:
                parts.append("--online")
            cmd = " ".join(parts)
            stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=600)
            self._json_response({
                "ok": ok, "vmid": vmid, "target_node": target_node,
                "online": online, "error": stdout if not ok else "",
            })
        except Exception as e:
            self._json_response({"error": f"Migration failed: {e}"})

    def _serve_pool(self):
        """List PVE pools."""
        cfg = load_config()
        pools = []
        for ip in _get_discovered_node_ips():
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

    def _serve_backup_list(self):
        """List all VM snapshots and config exports as structured JSON."""
        cfg = load_config()
        result = {"snapshots": [], "exports": []}

        try:
            node_ip = _find_reachable_node(cfg)
            if node_ip:
                stdout, ok = _pve_cmd(cfg, node_ip,
                                      "pvesh get /cluster/resources --type vm --output-format json")
                if ok and stdout:
                    try:
                        vms = json.loads(stdout)
                        for vm in vms:
                            vmid = vm.get("vmid", 0)
                            name = vm.get("name", "?")
                            snap_out, snap_ok = _pve_cmd(cfg, node_ip,
                                                          f"qm listsnapshot {vmid} 2>/dev/null")
                            if snap_ok and snap_out.strip():
                                for line in snap_out.strip().split("\n"):
                                    line = line.strip()
                                    if not line or "current" in line.lower():
                                        continue
                                    parts = line.split()
                                    snap_name = parts[0].replace("`-", "").replace("->", "").strip()
                                    if snap_name:
                                        result["snapshots"].append({
                                            "vmid": vmid, "vm_name": name,
                                            "snapshot": snap_name,
                                        })
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.warning(f"backup list: failed to get snapshots: {e}")

        # Config exports
        export_dir = os.path.join(cfg.data_dir, "backups")
        if os.path.isdir(export_dir):
            for f in sorted(os.listdir(export_dir), reverse=True)[:20]:
                fpath = os.path.join(export_dir, f)
                result["exports"].append({
                    "filename": f,
                    "size_kb": os.path.getsize(fpath) // 1024 if os.path.isfile(fpath) else 0,
                })

        self._json_response(result)

    def _serve_backup_create(self):
        """Create a VM snapshot."""
        cfg = load_config()
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}); return

        query = _parse_query_flat(self.path)
        vmid = int(query.get("vmid", "0"))
        snap_name = query.get("name", f"freq-snap-{vmid}")

        if not vmid:
            self._json_response({"error": "vmid required"}); return

        allowed, err_msg = _check_vm_permission(cfg, vmid, "snapshot")
        if not allowed:
            self._json_response({"error": err_msg}); return

        import re as _re
        if not _re.match(r'^[a-zA-Z0-9_-]+$', snap_name):
            self._json_response({"error": f"Invalid snapshot name: {snap_name}"}); return

        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return
            cmd = f"qm snapshot {vmid} {snap_name} --description 'Created by FREQ dashboard'"
            stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
            self._json_response({
                "ok": ok, "vmid": vmid, "snapshot": snap_name,
                "error": stdout if not ok else "",
            })
        except Exception as e:
            self._json_response({"error": f"Snapshot failed: {e}"})

    def _serve_backup_restore(self):
        """Rollback a VM to a snapshot."""
        cfg = load_config()
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}); return

        query = _parse_query_flat(self.path)
        vmid = int(query.get("vmid", "0"))
        snap_name = query.get("name", "")

        if not vmid or not snap_name:
            self._json_response({"error": "vmid and name required"}); return

        allowed, err_msg = _check_vm_permission(cfg, vmid, "configure")
        if not allowed:
            self._json_response({"error": err_msg}); return

        import re as _re
        if not _re.match(r'^[a-zA-Z0-9_-]+$', snap_name):
            self._json_response({"error": f"Invalid snapshot name: {snap_name}"}); return

        try:
            node_ip = _find_reachable_node(cfg)
            if not node_ip:
                self._json_response({"error": "No PVE node reachable"}); return
            cmd = f"qm rollback {vmid} {snap_name}"
            stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=300)
            self._json_response({
                "ok": ok, "vmid": vmid, "snapshot": snap_name,
                "error": stdout if not ok else "",
            })
        except Exception as e:
            self._json_response({"error": f"Restore failed: {e}"})

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

    # --- Phase 1: Alerting & Intelligence API Handlers ---

    def _serve_alert_rules(self):
        """List alert rules."""
        from freq.modules.alert import _load_rules, _load_silences
        cfg = load_config()
        rules = _load_rules(cfg)
        silences = [s for s in _load_silences(cfg) if s.get("expires", 0) > time.time()]
        self._json_response({"rules": rules, "count": len(rules), "silences": silences})

    def _serve_alert_history(self):
        """Get alert history."""
        from freq.modules.alert import _load_history
        cfg = load_config()
        history = _load_history(cfg)
        params = _parse_query(self)
        limit = int(params.get("limit", ["50"])[0])
        self._json_response({"history": history[-limit:], "total": len(history)})

    def _serve_alert_check(self):
        """Evaluate alert rules against current fleet state."""
        from freq.modules.alert import _load_rules, _evaluate_fleet
        cfg = load_config()
        rules = [r for r in _load_rules(cfg) if r.get("enabled", True)]
        triggered = _evaluate_fleet(cfg, rules)
        alerts = []
        for a in triggered:
            alerts.append({
                "rule": a["rule"]["name"],
                "host": a["host"],
                "value": a["value"],
                "message": a["message"],
                "severity": a["rule"].get("severity", "warning"),
            })
        self._json_response({"alerts": alerts, "count": len(alerts), "rules_checked": len(rules)})

    def _serve_alert_silences(self):
        """List active silences."""
        from freq.modules.alert import _load_silences
        cfg = load_config()
        silences = [s for s in _load_silences(cfg) if s.get("expires", 0) > time.time()]
        self._json_response({"silences": silences, "count": len(silences)})

    def _serve_inventory(self):
        """Full fleet inventory."""
        from freq.modules.inventory import _gather_hosts, _gather_vms, _gather_containers
        cfg = load_config()
        hosts = _gather_hosts(cfg)
        vms = _gather_vms(cfg)
        containers = _gather_containers(cfg)
        self._json_response({
            "hosts": hosts, "vms": vms, "containers": containers,
            "meta": {"host_count": len(hosts), "vm_count": len(vms), "container_count": len(containers)},
        })

    def _serve_inventory_hosts(self):
        """Host inventory only."""
        from freq.modules.inventory import _gather_hosts
        cfg = load_config()
        hosts = _gather_hosts(cfg)
        self._json_response({"hosts": hosts, "count": len(hosts)})

    def _serve_inventory_vms(self):
        """VM inventory only."""
        from freq.modules.inventory import _gather_vms
        cfg = load_config()
        vms = _gather_vms(cfg)
        self._json_response({"vms": vms, "count": len(vms)})

    def _serve_inventory_containers(self):
        """Container inventory only."""
        from freq.modules.inventory import _gather_containers
        cfg = load_config()
        containers = _gather_containers(cfg)
        self._json_response({"containers": containers, "count": len(containers)})

    def _serve_compare(self):
        """Compare two hosts."""
        from freq.modules.compare import _gather_host_info
        from freq.core.resolve import host as resolve_host
        cfg = load_config()
        params = _parse_query(self)
        a = params.get("a", [""])[0].strip()
        b = params.get("b", [""])[0].strip()
        if not a or not b:
            self._json_response({"error": "Parameters 'a' and 'b' required"}, 400); return
        host_a = resolve_host(cfg.hosts, a)
        host_b = resolve_host(cfg.hosts, b)
        if not host_a or not host_b:
            self._json_response({"error": "Host not found"}, 404); return
        info_a = _gather_host_info(cfg, host_a)
        info_b = _gather_host_info(cfg, host_b)
        self._json_response({"host_a": info_a, "host_b": info_b})

    def _serve_baseline_list(self):
        """List saved baselines."""
        from freq.modules.baseline import _list_baselines
        cfg = load_config()
        baselines = _list_baselines(cfg)
        self._json_response({"baselines": baselines, "count": len(baselines)})

    def _serve_rollback(self):
        """Rollback endpoint info (actual rollback requires CLI for safety)."""
        self._json_response({
            "info": "VM rollback must be performed via CLI for safety",
            "usage": "freq rollback <vmid> [--name <snapshot>]",
        })

    # --- Phase 2: Fleet Intelligence API Handlers ---

    def _serve_report(self):
        """Generate fleet report."""
        from freq.modules.report import _generate_report
        cfg = load_config()
        report = _generate_report(cfg)
        self._json_response(report)

    def _serve_trend_data(self):
        """Get trend data."""
        from freq.modules.trend import _load_trend_data
        cfg = load_config()
        data = _load_trend_data(cfg)
        params = _parse_query(self)
        limit = int(params.get("limit", ["100"])[0])
        self._json_response({"snapshots": data[-limit:], "total": len(data)})

    def _serve_trend_snapshot(self):
        """Take a trend snapshot."""
        from freq.modules.trend import _take_snapshot, _load_trend_data, _save_trend_data
        cfg = load_config()
        snapshot = _take_snapshot(cfg)
        if snapshot:
            data = _load_trend_data(cfg)
            data.append(snapshot)
            _save_trend_data(cfg, data)
        self._json_response({"ok": bool(snapshot), "snapshot": snapshot})

    def _serve_sla(self):
        """Get SLA data."""
        from freq.modules.sla import _load_sla_data, _calculate_sla
        cfg = load_config()
        data = _load_sla_data(cfg)
        params = _parse_query(self)
        days = int(params.get("days", ["30"])[0])
        all_hosts = set()
        for c in data.get("checks", []):
            all_hosts.update(c.get("results", {}).keys())
        sla_results = {}
        for label in sorted(all_hosts):
            sla_results[label] = {
                "7d": _calculate_sla(data, label, 7),
                "30d": _calculate_sla(data, label, 30),
                "90d": _calculate_sla(data, label, 90),
            }
        self._json_response({"hosts": sla_results, "total_checks": len(data.get("checks", []))})

    def _serve_sla_check(self):
        """Record an SLA check."""
        from freq.modules.sla import _record_check
        cfg = load_config()
        _record_check(cfg)
        self._json_response({"ok": True})

    def _serve_cert_inventory(self):
        """Get cert inventory."""
        from freq.modules.cert import _load_cert_data
        cfg = load_config()
        data = _load_cert_data(cfg)
        self._json_response(data)

    def _serve_dns_inventory(self):
        """Get DNS inventory."""
        from freq.modules.dns import _load_dns_data
        cfg = load_config()
        data = _load_dns_data(cfg)
        self._json_response(data)


def cmd_serve(cfg, pack, args) -> int:
    """Start the FREQ web dashboard."""
    port = getattr(args, "port", None) or cfg.dashboard_port

    # Ensure data directories exist — pip installs don't create /opt/pve-freq
    for d in (cfg.install_dir, cfg.conf_dir, cfg.data_dir,
              os.path.join(cfg.data_dir, "log"),
              os.path.join(cfg.data_dir, "cache")):
        try:
            os.makedirs(d, exist_ok=True)
        except PermissionError:
            fmt.error(f"Cannot create {d} — run with sudo or set FREQ_DIR to a writable path")
            return 1

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
