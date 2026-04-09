"""FREQ Web Dashboard — fleet management in a browser.

Domain: freq serve [--port N]

Starts a local HTTP server with a full fleet dashboard: live host health,
VM inventory, container status, VLAN topology, capacity trends, NTP sync,
storage health, media stack, alerting, and 100+ REST API endpoints. Pure
Python stdlib (http.server + json + threading), zero external dependencies.

Replaces: Grafana dashboards ($0 but requires Prometheus + exporters),
          Proxmox web UI (limited to PVE, no fleet view), Netbox ($0 but
          heavy setup), custom Flask/Django dashboards

Architecture:
    - http.server.HTTPServer with threaded request handler
    - Background cache probes (ThreadPoolExecutor) refresh fleet data
    - Server-Sent Events (SSE) for real-time dashboard updates
    - Static file serving for embedded SPA (web_ui.py)
    - Route table (_ROUTES dict) maps paths to handler methods
    - v1 API routes delegated to freq/api/ domain modules

Design decisions:
    - stdlib http.server, not Flask. Zero dependencies is sacred.
    - Background probes, not on-demand. Dashboard loads instantly.
    - SSE, not WebSocket. Simpler, no upgrade handshake, works through proxies.
    - Auth via session cookies + RBAC. Setup wizard creates first admin.
"""

import concurrent.futures
import datetime
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

from freq.core import log as logger
from freq.core import resolve as res
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single, run_many as ssh_run_many
from freq.core.validate import (
    label as valid_label,
)
from freq.modules.pve import _find_reachable_node, _pve_cmd
from freq.modules.users import _load_users, _save_users
from freq.modules.vault import vault_get, vault_set, vault_init
from freq.jarvis.agent import TEMPLATES, _load_agents, _save_agents
from freq.jarvis.notify import notify as jarvis_notify
from freq.jarvis.risk import _load_kill_chain


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server — won't block on slow API calls."""

    daemon_threads = True


# ── CONSTANTS ────────────────────────────────────────────────────────────

BG_CACHE_REFRESH_INTERVAL = 15  # seconds between background cache refreshes
DASHBOARD_AUTO_REFRESH_MS = 30000  # milliseconds between frontend auto-refreshes

# ── CIRCUIT BREAKER — prevent sshguard blocking from aggressive probes ───
LEGACY_HTYPES = {"idrac", "switch"}
LEGACY_PROBE_INTERVAL = 60       # seconds between probes for iDRAC/switch
CIRCUIT_BREAKER_THRESHOLD = 3    # consecutive failures before backoff
CIRCUIT_BREAKER_BACKOFF = 300    # 5 minutes backoff after threshold
_host_fail_count = {}            # ip -> consecutive failure count
_host_backoff_until = {}         # ip -> monotonic timestamp when backoff expires
_last_legacy_probe = 0.0         # monotonic timestamp of last legacy probe
_SERVER_START_TIME = time.monotonic()
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
HOSTS_SYNC_INTERVAL = 3600  # 1 hour — keep hosts.conf in sync with PVE
NODE_DISCOVERY_INTERVAL = 300  # 5 min — discover PVE cluster nodes
VM_TAGS_INTERVAL = 300  # 5 min — refresh PVE VM tags
_bg_lock = threading.Lock()
_setup_lock = threading.Lock()

# ── SSE EVENT BUS ────────────────────────────────────────────────────────
# Lightweight pub/sub: each connected EventSource client gets a Queue.
# Background probes broadcast events after cache updates.

import queue

_sse_clients: list = []  # list of queue.Queue, one per SSE client
_sse_lock = threading.Lock()  # guards _sse_clients list


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
    global CACHE_DIR
    if CACHE_DIR is None:
        _init_cache_dir()
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

    def _ping_check(ip):
        """Quick ping fallback for devices where SSH isn't available."""
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, timeout=2)
            return r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    # Infrastructure devices often need different credentials than the service account.
    # Try: 1) fleet/bootstrap key with freq-ops, 2) service account key
    fleet_key = os.path.join(cfg.key_dir, "fleet_key")
    if not os.path.isfile(fleet_key):
        fleet_key = cfg.ssh_key_path  # fallback to service account key
    bootstrap_user = os.environ.get("SUDO_USER") or cfg.ssh_service_account or "freq-admin"

    def _probe_device(key, dev):
        d = {"key": key, "label": dev.label, "type": dev.device_type, "ip": dev.ip, "reachable": False, "metrics": {}}
        dt = dev.device_type
        try:
            if dt == "pfsense":
                r = ssh_single(
                    host=dev.ip,
                    command='echo "$(sudo pfctl -ss 2>/dev/null | wc -l)|$(uptime)|$(ifconfig -l)"',
                    key_path=fleet_key,
                    user=bootstrap_user,
                    connect_timeout=2,
                    command_timeout=5,
                    htype="pfsense",
                    use_sudo=False,
                    cfg=cfg,
                )
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    m = d["metrics"]
                    parts = r.stdout.strip().split("|", 2)
                    if parts[0].strip():
                        m["states"] = parts[0].strip()
                    if len(parts) > 1:
                        up_match = re.search(r"up\s+(.+?),\s*\d+ user", parts[1])
                        if up_match:
                            m["uptime"] = "up " + up_match.group(1).strip()
                    if len(parts) > 2:
                        ifaces = [
                            i for i in parts[2].strip().split() if not i.startswith(("lo", "enc", "pflog", "pfsync"))
                        ]
                        m["interfaces"] = str(len(ifaces))
                else:
                    d["reachable"] = _ping_check(dev.ip)
            elif dt == "truenas":
                # Two quick SSH calls: zpool for pool status, midclt for alert count
                r = ssh_single(
                    host=dev.ip,
                    command="zpool list -o name,size,alloc,free,health -H 2>/dev/null",
                    key_path=fleet_key,
                    user=bootstrap_user,
                    connect_timeout=2,
                    command_timeout=8,
                    htype="truenas",
                    use_sudo=True,
                    cfg=cfg,
                )
                r2 = ssh_single(
                    host=dev.ip,
                    command="midclt call alert.list",
                    key_path=fleet_key,
                    user=bootstrap_user,
                    connect_timeout=2,
                    command_timeout=8,
                    htype="truenas",
                    use_sudo=True,
                    cfg=cfg,
                )
                if r.returncode == 0:
                    d["reachable"] = True
                    m = d["metrics"]
                    if r.stdout.strip():
                        pools = []
                        for line in r.stdout.strip().split("\n"):
                            cols = line.split()
                            if len(cols) >= 5:
                                pools.append(
                                    {
                                        "name": cols[0],
                                        "size": cols[1],
                                        "alloc": cols[2],
                                        "free": cols[3],
                                        "health": cols[4],
                                    }
                                )
                        m["pools"] = pools
                        healths = [p["health"] for p in pools]
                        m["pool_health"] = (
                            "DEGRADED" if "DEGRADED" in healths else "FAULTED" if "FAULTED" in healths else "ONLINE"
                        )
                        total_alloc = sum(
                            float(p["alloc"].replace("T", "").replace("G", "")) * (1024 if "T" in p["alloc"] else 1)
                            for p in pools
                        )
                        total_size = sum(
                            float(p["size"].replace("T", "").replace("G", "")) * (1024 if "T" in p["size"] else 1)
                            for p in pools
                        )
                        if total_size > 0:
                            m["capacity_pct"] = str(round(total_alloc / total_size * 100)) + "%"
                        m["total_size"] = (
                            pools[0]["size"] if len(pools) == 1 else str(round(total_size / 1024, 1)) + "T"
                        )
                    # Parse alert count from raw JSON
                    try:
                        alerts = json.loads(r2.stdout) if r2.returncode == 0 else []
                        m["alerts"] = len(alerts) if isinstance(alerts, list) else 0
                    except (json.JSONDecodeError, ValueError):
                        m["alerts"] = 0
                else:
                    d["reachable"] = _ping_check(dev.ip)
            elif dt == "switch":
                # Switch: password auth via sshpass (Cisco IOS needs legacy ciphers)
                sw_pass_file = os.path.join(os.path.dirname(cfg.conf_dir), "credentials", "switch-password")
                if os.path.isfile(sw_pass_file):
                    sw_cmd = [
                        "sshpass", "-f", sw_pass_file, "ssh", "-n",
                        "-o", "ConnectTimeout=3",
                        "-o", "StrictHostKeyChecking=accept-new",
                        "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
                        "-o", "HostKeyAlgorithms=+ssh-rsa",
                        f"{bootstrap_user}@{dev.ip}",
                        "show version | include uptime",
                    ]
                    proc = subprocess.run(sw_cmd, capture_output=True, text=True, timeout=10)
                    r = type("R", (), {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})()
                else:
                    r = ssh_single(
                        host=dev.ip,
                        command="show version | include uptime",
                        key_path=fleet_key,
                        connect_timeout=2,
                        command_timeout=5,
                        htype="switch",
                        use_sudo=False,
                        cfg=cfg,
                    )
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    d["metrics"]["uptime"] = r.stdout.strip()
                else:
                    pr = subprocess.run(["ping", "-c", "1", "-W", "1", dev.ip], capture_output=True, timeout=2)
                    d["reachable"] = pr.returncode == 0
                    if d["reachable"]:
                        d["metrics"]["note"] = "Reachable (no SSH)"
            elif dt == "idrac":
                # iDRAC: password auth via sshpass (same cred file as switch)
                idrac_pass_file = os.path.join(os.path.dirname(cfg.conf_dir), "credentials", "switch-password")
                if os.path.isfile(idrac_pass_file):
                    idrac_cmd = [
                        "sshpass", "-f", idrac_pass_file, "ssh", "-n",
                        "-o", "ConnectTimeout=3",
                        "-o", "StrictHostKeyChecking=accept-new",
                        "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
                        "-o", "HostKeyAlgorithms=+ssh-rsa",
                        "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
                        f"{bootstrap_user}@{dev.ip}",
                        "racadm getsysinfo -s",
                    ]
                    proc = subprocess.run(idrac_cmd, capture_output=True, text=True, timeout=15)
                    r = type("R", (), {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})()
                else:
                    # Fallback: try RSA key
                    idrac_key = cfg.ssh_rsa_key_path or fleet_key
                    r = ssh_single(
                        host=dev.ip,
                        command="racadm getsysinfo -s",
                        key_path=idrac_key,
                        user="root",
                        connect_timeout=3,
                        command_timeout=8,
                        htype="idrac",
                        use_sudo=False,
                        cfg=cfg,
                    )
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    m = d["metrics"]
                    for line in r.stdout.strip().split("\n"):
                        low = line.lower()
                        if "power status" in low:
                            val = line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
                            m["power"] = "ON" if "on" in val.lower() else "OFF"
                        elif "inlet temp" in low:
                            m["inlet_temp"] = (
                                line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
                            )
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
    logger.debug("health_probe_start", host_count=len(cfg.hosts))
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
        _groups = getattr(h, "groups", "") or ""
        if r.returncode != 0 or not r.stdout.strip():
            err = r.stderr.strip()[:120] if r.stderr else "no response"
            return {
                "label": h.label,
                "ip": h.ip,
                "type": htype,
                "groups": _groups,
                "status": "unreachable",
                "cores": "-",
                "ram": "-",
                "disk": "-",
                "load": "-",
                "docker": "0",
                "last_error": err,
            }
        if htype == "switch":
            m = re.search(r"one minute:\s*(\d+)%", r.stdout)
            cpu_pct = m.group(1) if m else "0"
            sw_key2 = cfg.ssh_rsa_key_path or cfg.ssh_key_path
            r2 = ssh_single(
                host=h.ip,
                command="show processes memory | include Processor",
                key_path=sw_key2,
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
                "groups": _groups,
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
            "groups": _groups,
            "status": "healthy",
            "cores": parts[1] if len(parts) > 1 else "?",
            "ram": parts[2] if len(parts) > 2 else "?",
            "disk": parts[3] if len(parts) > 3 else "?",
            "load": parts[4] if len(parts) > 4 else "?",
            "docker": parts[5].strip() if len(parts) > 5 else "0",
        }

    # ── Circuit breaker: skip hosts in backoff or legacy hosts probed recently ──
    global _last_legacy_probe
    now = time.monotonic()
    probe_legacy = (now - _last_legacy_probe) >= LEGACY_PROBE_INTERVAL

    active_hosts = []
    skipped_hosts = []
    for h in cfg.hosts:
        # Skip hosts in circuit-breaker backoff
        if _host_backoff_until.get(h.ip, 0) > now:
            skipped_hosts.append(h)
            continue
        # Rate-limit legacy device probes
        if h.htype in LEGACY_HTYPES and not probe_legacy:
            skipped_hosts.append(h)
            continue
        active_hosts.append(h)

    if probe_legacy and any(h.htype in LEGACY_HTYPES for h in active_hosts):
        _last_legacy_probe = now

    # Reuse cached data for skipped hosts
    host_data = []
    if skipped_hosts:
        with _bg_lock:
            cached = _bg_cache.get("health")
        cached_by_ip = {}
        if cached and isinstance(cached, dict):
            cached_by_ip = {h["ip"]: h for h in cached.get("hosts", [])}
        for h in skipped_hosts:
            prev = cached_by_ip.get(h.ip)
            if prev:
                host_data.append(prev)
            else:
                host_data.append({
                    "label": h.label, "ip": h.ip, "type": h.htype,
                    "status": "unreachable", "cores": "-", "ram": "-",
                    "disk": "-", "load": "-", "docker": "0",
                    "last_error": "circuit breaker / rate limited",
                })

    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.ssh_max_parallel) as pool:
        futures = {pool.submit(_probe_host, h): h for h in active_hosts}
        for f in concurrent.futures.as_completed(futures):
            h = futures[f]
            try:
                result_entry = f.result()
                host_data.append(result_entry)
                # Circuit breaker: track success/failure
                if result_entry.get("status") == "healthy":
                    was_in_backoff = h.ip in _host_backoff_until
                    _host_fail_count.pop(h.ip, None)
                    _host_backoff_until.pop(h.ip, None)
                    if was_in_backoff:
                        logger.info("circuit_breaker_reset", host=h.ip)
                else:
                    count = _host_fail_count.get(h.ip, 0) + 1
                    _host_fail_count[h.ip] = count
                    if count >= CIRCUIT_BREAKER_THRESHOLD:
                        _host_backoff_until[h.ip] = now + CIRCUIT_BREAKER_BACKOFF
                        logger.warning(
                            f"circuit breaker: {h.label} ({h.ip}) failed {count}x, "
                            f"backing off {CIRCUIT_BREAKER_BACKOFF}s"
                        )
            except Exception as e:
                logger.warn(f"health probe failed for {h.label}: {e}")
                host_data.append(
                    {
                        "label": h.label,
                        "ip": h.ip,
                        "type": h.htype,
                        "status": "unreachable",
                        "cores": "-",
                        "ram": "-",
                        "disk": "-",
                        "load": "-",
                        "docker": "0",
                        "last_error": str(e)[:120],
                    }
                )
                count = _host_fail_count.get(h.ip, 0) + 1
                _host_fail_count[h.ip] = count
                if count >= CIRCUIT_BREAKER_THRESHOLD:
                    _host_backoff_until[h.ip] = now + CIRCUIT_BREAKER_BACKOFF

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

    result = {
        "duration": round(time.monotonic() - start, 1),
        "hosts": host_data,
        "probed_at": time.time(),
        "node_containers": node_containers,
    }
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
                _sse_broadcast("health_change", {"host": h["label"], "old": prev, "new": h["status"]})
                severity = "success" if h["status"] == "healthy" else "error"
                _activity_add("health_change", f"{h['label']} is now {h['status']}", f"was {prev}", severity)

    # Evaluate alert rules against fresh health data
    _evaluate_alert_rules(cfg, result)

    # Log probe completion
    duration = round(time.monotonic() - start, 1)
    healthy_count = sum(1 for h in host_data if h.get("status") == "healthy")
    unreachable_count = sum(1 for h in host_data if h.get("status") != "healthy")
    logger.info("health_probe_complete", duration=duration, total=len(host_data), healthy=healthy_count, unreachable=unreachable_count)
    logger.perf("health_probe", duration, hosts_total=len(host_data), hosts_healthy=healthy_count)

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
                capture_output=True,
                timeout=2,
            )
            reachable = r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            pass
        return {
            "key": dev.key,
            "ip": dev.ip,
            "label": dev.label,
            "type": dev.device_type,
            "tier": dev.tier,
            "detail": dev.detail,
            "reachable": reachable,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_ping_device, dev): dev for dev in fb.physical.values()}
        for f in concurrent.futures.as_completed(futures):
            try:
                physical.append(f.result())
            except Exception:
                dev = futures[f]
                physical.append(
                    {
                        "key": dev.key,
                        "ip": dev.ip,
                        "label": dev.label,
                        "type": dev.device_type,
                        "tier": dev.tier,
                        "detail": dev.detail,
                        "reachable": False,
                    }
                )

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
            "online": dn.get("online", False),
        }
        if dn.get("cores"):
            entry["cores"] = dn["cores"]
        if dn.get("ram_gb"):
            entry["ram_gb"] = dn["ram_gb"]
        # Check PVE API reachability if not already set
        if not entry["online"]:
            from freq.modules.pve import _pve_api_call
            _, ok = _pve_api_call(cfg, entry["ip"], f"/nodes/{entry['name']}/status", timeout=3)
            entry["online"] = ok
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
            host=nip,
            command=batch_cmd,
            key_path=cfg.ssh_key_path,
            command_timeout=20,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
        )
        if r.returncode == 0 and r.stdout:
            cur_vmid = None
            for line in r.stdout.strip().split("\n"):
                if line.startswith("VMID:"):
                    cur_vmid = int(line[5:])
                    vm_nics[cur_vmid] = []
                elif cur_vmid is not None and line.startswith("net"):
                    nic_name = line.split(":")[0].strip()
                    tag_match = re.search(r"tag=(\d+)", line)
                    vlan_tag = int(tag_match.group(1)) if tag_match else 0
                    vlan_name = vlan_id_to_name.get(vlan_tag, f"VLAN {vlan_tag}" if vlan_tag else "UNTAGGED")
                    vm_nics[cur_vmid].append(
                        {
                            "nic": nic_name,
                            "tag": vlan_tag,
                            "vlan_name": vlan_name,
                        }
                    )

    duration = round(time.monotonic() - start, 2)
    result = {
        "vms": vm_list,
        "vm_nics": {str(k): v for k, v in vm_nics.items()},
        "physical": physical,
        "pve_nodes": pve_nodes,
        "vlans": [
            {
                "id": v.id,
                "name": v.name,
                "prefix": v.prefix,
                "gateway": v.gateway,
                "cidr": v.subnet.split("/")[1] if "/" in v.subnet else "24",
            }
            for v in cfg.vlans
        ],
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
                _sse_broadcast(
                    "vm_state", {"vmid": v["vmid"], "name": v.get("name", ""), "old": prev, "new": v["status"]}
                )
                vm_label = v.get("name") or f"VM {v['vmid']}"
                _activity_add("vm_state", f"{vm_label}: {prev} \u2192 {v['status']}", f"VMID {v['vmid']}", "info")


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
            r = ssh_single(
                host=ip,
                command="echo ok",
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=5,
                htype="pve",
                use_sudo=False,
            )
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
            key_path=cfg.ssh_key_path,
            command_timeout=15,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
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
                            "ram_gb": round(n.get("maxmem", 0) / (1024**3)),
                        }
            except json.JSONDecodeError:
                pass

        # Get IPs from corosync config
        r2 = ssh_single(
            host=seed_ip,
            command="cat /etc/pve/corosync.conf 2>/dev/null",
            key_path=cfg.ssh_key_path,
            command_timeout=10,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
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
            discovered.append(
                {
                    "name": name,
                    "ip": node_ips.get(name, ""),
                    "status": stats["status"],
                    "cores": stats["cores"],
                    "ram_gb": stats["ram_gb"],
                }
            )

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
    return [{"name": n.name, "ip": n.ip, "detail": getattr(n, "detail", "")} for n in fb.pve_nodes.values()]


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
            key_path=cfg.ssh_key_path,
            command_timeout=15,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
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
        node_ip_map = {n["name"]: n["ip"] for n in _get_discovered_nodes() if n.get("name") and n.get("ip")}

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
                host=nip,
                command=batch_cmd,
                key_path=cfg.ssh_key_path,
                command_timeout=30,
                htype="pve",
                use_sudo=True,
                cfg=cfg,
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
            load_rules,
            evaluate_rules,
            load_rule_state,
            save_rule_state,
            load_alert_history,
            save_alert_history,
            alert_to_dict,
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
                    jarvis_notify(cfg, alert.message, title=f"FREQ Alert: {alert.rule_name}", severity=alert.severity)
                except Exception as e:
                    logger.warn(f"Alert notification failed: {e}")
                history.append(alert_to_dict(alert))
                # SSE: broadcast alert event
                _sse_broadcast("alert", {"rule": alert.rule_name, "message": alert.message, "severity": alert.severity})
            save_alert_history(CACHE_DIR, history)
    except Exception as e:
        logger.warn(f"Alert rule evaluation failed: {e}")


def _bg_health_loop():
    """Fast health-only loop — runs every 15s for live dashboard bars."""
    while True:
        logger.debug("bg_loop_cycle", loop="health")
        try:
            _bg_probe_health()
        except Exception as e:
            logger.error(f"bg health probe failed: {e}")
        time.sleep(BG_CACHE_REFRESH_INTERVAL)


def _bg_slow_loop():
    """Slower loop for fleet overview, infra, tags, updates — runs every 60s."""
    while True:
        logger.debug("bg_loop_cycle", loop="slow")
        for fn, label in [
            (_bg_discover_pve_nodes, "node discovery"),
            (_bg_fetch_vm_tags, "tag fetch"),
            (_bg_probe_infra, "infra probe"),
            (_bg_probe_fleet_overview, "fleet overview"),
            (_bg_check_update, "update check"),
            (_bg_sync_hosts, "hosts sync"),
        ]:
            try:
                fn()
            except Exception as e:
                logger.error(f"bg {label} failed: {e}")
        time.sleep(60)


def _bg_initial_probe():
    """Run critical probes immediately on startup so first page load has data."""
    for fn, label in [
        (_bg_discover_pve_nodes, "node discovery"),
        (_bg_probe_fleet_overview, "fleet overview"),
        (_bg_fetch_vm_tags, "tag fetch"),
    ]:
        try:
            fn()
        except Exception as e:
            logger.error(f"bg initial {label} failed: {e}")


def start_background_cache():
    """Load disk cache, then start background refresh threads."""
    _init_cache_dir()
    _load_disk_cache()
    # Kick off critical probes immediately so first page load has data
    t0 = threading.Thread(target=_bg_initial_probe, daemon=True, name="freq-init-probe")
    t1 = threading.Thread(target=_bg_health_loop, daemon=True, name="freq-health")
    t2 = threading.Thread(target=_bg_slow_loop, daemon=True, name="freq-slow")
    t0.start()
    t1.start()
    t2.start()


# Legacy DASHBOARD_HTML removed — 240 lines of dead embedded HTML
# Modern dashboard served from freq/data/web/app.html via _serve_static


def _parse_pct(value: str) -> float:
    """Parse a percentage string like '45%' or RAM string '4096/8192MB' into float."""
    if not value:
        return 0.0
    import re as _re

    m = _re.match(r"(\d+)%", value)
    if m:
        return float(m.group(1))
    m = _re.match(r"(\d+)/(\d+)", value)
    if m:
        used, total = float(m.group(1)), float(m.group(2))
        return round(used / total * 100, 1) if total > 0 else 0.0
    return 0.0


def _parse_query_flat(path_str):
    """Parse query params from a URL path string. Returns {key: str}."""
    raw = parse_qs(urlparse(path_str).query)
    return {k: v[0] if v else "" for k, v in raw.items()}


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



def _check_vm_permission(cfg, vmid, action):
    """Check if an action is allowed for a VMID. Returns (allowed, error_msg)."""
    fb = cfg.fleet_boundaries
    cat_name, tier = fb.categorize(vmid)
    if fb.can_action(vmid, action):
        return True, ""
    return False, f"Action '{action}' blocked on VMID {vmid} ({cat_name}/{tier})"


# Auth functions delegated to freq.api.auth
from freq.api.auth import (
    hash_password as _hash_password,
    check_session_role as _check_session_role,
    handle_auth_login,
    handle_auth_verify,
    handle_auth_change_password,
)


def _find_reachable_pve_node(cfg):
    """Find the first reachable PVE node. Returns IP string or None.

    Prefers auto-discovered nodes, falls back to freq.toml static list.
    """
    node_ips = _get_discovered_node_ips()
    for ip in node_ips:
        r = ssh_single(
            host=ip,
            command="sudo pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode == 0:
            return ip
    return None


def _parse_query(handler):
    """Parse query parameters from the request path. Returns dict of lists."""
    return parse_qs(urlparse(handler.path).query)


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

        result, ok = _pve_call(
            cfg,
            node_ip,
            api_endpoint="/cluster/resources?type=vm",
            ssh_command="pvesh get /cluster/resources --type vm --output-format json",
            timeout=15,
        )
        if ok and result:
            try:
                vms = result if isinstance(result, list) else json.loads(result)
                for v in vms:
                    vmid = v.get("vmid", 0)
                    cat_name, tier = fb.categorize(vmid)
                    tags = get_vm_tags(vmid)
                    # cpu field: real utilization (0.0-1.0), maxcpu: allocated cores
                    # mem field: real used bytes, maxmem: allocated bytes
                    cpu_real = v.get("cpu", 0)
                    cpu_pct = round(cpu_real * 100, 1) if isinstance(cpu_real, (int, float)) else 0
                    mem_used = v.get("mem", 0) or 0
                    mem_max = v.get("maxmem", 0) or 0
                    vm_list.append(
                        {
                            "vmid": vmid,
                            "name": v.get("name", ""),
                            "node": v.get("node", ""),
                            "status": v.get("status", ""),
                            "cpu": v.get("maxcpu", 0),
                            "cpu_pct": cpu_pct,
                            "ram_mb": mem_max // (1024 * 1024) if mem_max else 0,
                            "ram_used_mb": mem_used // (1024 * 1024) if mem_used else 0,
                            "ram_pct": min(round(mem_used / mem_max * 100, 1), 100.0) if mem_max else 0,
                            "type": v.get("type", ""),
                            "category": cat_name,
                            "tier": tier,
                            "tags": tags,
                            "allowed_actions": fb.allowed_actions(vmid),
                            "is_prod": fb.is_prod(vmid) or "prod" in tags,
                        }
                    )
            except (json.JSONDecodeError, TypeError):
                pass
        break  # Only need one node for cluster-wide view
    return vm_list


class FreqHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the FREQ dashboard."""

    # HTTP/1.1 required for WebSocket upgrade (RFC 6455) and SSE keep-alive
    protocol_version = "HTTP/1.1"

    # Class-level caches for PVE metrics polling
    _pve_metrics_cache = None
    _pve_metrics_ts = 0

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    # Route dispatch table — path → method name (resolved at call time via getattr)
    _ROUTES = {
        # ── Infrastructure routes (stay in serve.py) ──────────────────
        "/": "_serve_app",
        "/dashboard": "_serve_app",
        # ── Auth (stays in serve.py) ──────────────────────────────────
        "/api/pve/metrics": "_serve_pve_metrics",
        "/api/pve/rrd": "_serve_pve_rrd",
        "/api/auth/login": "_serve_auth_login",
        "/api/auth/verify": "_serve_auth_verify",
        "/api/auth/change-password": "_serve_auth_change_password",
        # ── Admin (stays in serve.py) ─────────────────────────────────
        "/api/admin/fleet-boundaries": "_serve_admin_fleet_boundaries",
        "/api/admin/fleet-boundaries/update": "_serve_admin_fleet_boundaries_update",
        "/api/admin/hosts/update": "_serve_admin_hosts_update",
        # ── Setup wizard (stays in serve.py) ──────────────────────────
        "/api/setup/status": "_serve_setup_status",
        "/api/setup/create-admin": "_serve_setup_create_admin",
        "/api/setup/configure": "_serve_setup_configure",
        "/api/setup/generate-key": "_serve_setup_generate_key",
        "/api/setup/complete": "_serve_setup_complete",
        "/api/setup/test-ssh": "_serve_setup_test_ssh",
        "/api/setup/reset": "_serve_setup_reset",
        # ── SSE / orchestration (stays in serve.py) ───────────────────
        "/api/events": "_serve_events",
        "/healthz": "_serve_healthz",
        "/readyz": "_serve_readyz",
        # ── Docs (stays in serve.py) ──────────────────────────────────
        "/api/docs": "_serve_api_docs",
        "/api/openapi.json": "_serve_openapi_json",
        "/api/docs/generate": "_serve_docs_generate",
        "/api/docs/runbooks": "_serve_docs_runbooks",
        # ── Config & misc (stays in serve.py) ─────────────────────────
        "/api/config": "_serve_config",
        "/api/config/view": "_serve_config_view",
        "/api/update/check": "_serve_update_check",
        "/api/learn": "_serve_learn",
        "/api/distros": "_serve_distros",
        "/api/notify/test": "_serve_notify_test",
        "/api/doctor": "_serve_doctor",
        "/api/deploy/log": "_serve_deploy_log",
        "/api/watch/start": "_serve_watch_start",
        "/api/watch/stop": "_serve_watch_stop",
        "/api/dns/lookup": "_serve_dns_lookup",
        "/api/net/portscan": "_serve_portscan",
        "/api/backup/schedules": "_serve_backup_schedules",
        "/api/containers/action": "_serve_container_action",
        "/api/containers/logs": "_serve_container_logs",
        "/api/fleet/connectivity": "_serve_fleet_connectivity",
        "/api/host/diagnostic": "_serve_host_diagnostic",
        # ── Agent lifecycle (stays in serve.py) ───────────────────────
        "/api/agent/create": "_serve_agent_create",
        "/api/agent/destroy": "_serve_agent_destroy",
        # ── Lab / specialist (stays in serve.py) ──────────────────────
        "/api/lab/status": "_serve_lab_status",
        "/api/specialists": "_serve_specialists",
        "/api/lab-tool/proxy": "_serve_lab_tool_proxy",
        "/api/lab-tool/config": "_serve_lab_tool_config",
        "/api/lab-tool/save-config": "_serve_lab_tool_save_config",
        # ── Media (stays in serve.py — complex container proxy) ───────
        "/api/media/status": "_serve_media_status",
        "/api/media/health": "_serve_media_health",
        "/api/media/downloads": "_serve_media_downloads",
        "/api/media/streams": "_serve_media_streams",
        "/api/media/dashboard": "_serve_media_dashboard",
        "/api/media/restart": "_serve_media_restart",
        "/api/media/logs": "_serve_media_logs",
        "/api/media/update": "_serve_media_update",
        "/api/media/tdarr": "_serve_media_tdarr",
        "/api/media/tags": "_serve_media_tags",
        "/api/media/downloads/detail": "_serve_media_downloads_detail",
        # ── Infrastructure device (stays — pfsense goes to fw later) ──
        "/api/infra/pfsense": "_serve_pfsense",
        #
    }

    # v1 API routes from freq/api/ domain modules (built once, cached)
    _V1_ROUTES = None

    @classmethod
    def _load_v1_routes(cls):
        """Load domain API routes from freq/api/ modules (once at first request)."""
        if cls._V1_ROUTES is None:
            try:
                from freq.api import build_routes

                cls._V1_ROUTES = build_routes()
                logger.info(f"v1 API routes loaded: {len(cls._V1_ROUTES)} endpoints")
            except Exception as e:
                import traceback

                logger.error(f"build_routes failed: {e}\n{traceback.format_exc()}")
                cls._V1_ROUTES = {}  # Fallback — traceback logged for debugging

    # Paths that don't require authentication
    _AUTH_WHITELIST = frozenset({
        "/api/auth/login",
        "/api/auth/verify",
        "/api/setup/status",
        "/api/setup/complete",
        "/healthz",
        "/readyz",
        "/api/openapi.json",
    })
    # Path prefixes that don't require authentication
    _AUTH_WHITELIST_PREFIXES = ("/static/", "/dashboard", "/api/watch/", "/api/comms/")

    def _dispatch(self):
        """Route request to handler method or callable by path.

        Legacy routes use string method names (getattr dispatch).
        v1 domain routes use callables: function(handler) from freq/api/.
        """
        path = self.path.split("?")[0]

        # Global auth check — all /api/ endpoints require at least viewer role
        # unless explicitly whitelisted. Non-API paths (SPA, static) are public.
        if path.startswith("/api/") and path not in self._AUTH_WHITELIST \
                and not any(path.startswith(p) for p in self._AUTH_WHITELIST_PREFIXES):
            role, err = _check_session_role(self, "viewer")
            if err:
                self._json_response({"error": "Authentication required"}, 403)
                return

        # Check legacy routes first, then v1 domain routes
        handler_ref = self._ROUTES.get(path)
        if not handler_ref:
            self._load_v1_routes()
            handler_ref = self._V1_ROUTES.get(path)
        if handler_ref:
            try:
                if callable(handler_ref):
                    handler_ref(self)
                else:
                    getattr(self, handler_ref)()
            except Exception as e:
                import traceback

                traceback.print_exc()
                try:
                    logger.error("api_error", method=getattr(self, "command", "?"), path=path, status=500)
                    logger.error(f"handler error: {path}: {e}")
                    self._json_response({"error": "Internal server error", "path": path}, 500)
                except Exception as e2:
                    import sys

                    print(f"[FREQ] Failed to send error response for {path}: {e2}", file=sys.stderr)
        elif path.startswith("/static/"):
            self._serve_static(path)
        elif path.startswith("/api/comms/") or path.startswith("/api/watch/"):
            self._proxy_watchdog()
        elif path.startswith("/api/"):
            logger.error("api_error", method=getattr(self, "command", "?"), path=path, status=404)
            self._json_response({"error": "not found", "path": path}, 404)
        else:
            self._serve_app()

    def do_GET(self):
        logger.debug("api_request", method=getattr(self, "command", "GET"), path=self.path)
        self._dispatch()

    def do_POST(self):
        logger.debug("api_request", method=getattr(self, "command", "POST"), path=self.path)
        self._dispatch()

    # ── Server-Sent Events ────────────────────────────────────────────────

    def _serve_events(self):
        """SSE endpoint — streams live updates to the dashboard.

        Keeps the connection open and pushes events as they arrive from
        background cache probes. Each client gets its own Queue via the
        SSE event bus. Sends keepalive comments every 15s.
        """
        # Auth: EventSource can't send headers, so token is in query string
        # _check_session_role already reads query string tokens (auth.py:91-92)
        role, err = _check_session_role(self, "viewer")
        if err:
            self.send_response(403)
            self.end_headers()
            return
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

    def _serve_media_tags(self):
        """GET/POST /api/media/tags — persist media container tags server-side."""
        cfg = load_config()
        tags_file = os.path.join(cfg.data_dir, "cache", "media_tags.json")
        if self.command == "POST":
            body = self._request_body()
            if body and "tags" in body:
                try:
                    with open(tags_file, "w") as f:
                        json.dump(body["tags"], f)
                    self._json_response({"ok": True, "tags": body["tags"]})
                except OSError as e:
                    self._json_response({"error": str(e)}, 500)
            else:
                self._json_response({"error": "tags array required"}, 400)
        else:
            try:
                with open(tags_file) as f:
                    tags = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                tags = []
            self._json_response({"tags": tags})

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
                    htype=h.get("type", "linux"),
                    use_sudo=False,
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
                    htype="docker",
                    use_sudo=False,
                )
                if r.returncode == 0 and "no-dl-client" not in r.stdout:
                    lines = [l for l in r.stdout.split("\n") if l.strip()]
                    downloads["total"] += len(lines)
                    for line in lines:
                        downloads["active"].append({"host": h.get("label", ""), "detail": line})

        self._json_response(downloads)

    # ── Config & Deploy ────────────────────────────────────────────────

    def _serve_config_view(self):
        """GET /api/config/view — read-only view of freq.toml settings."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return
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
                capture_output=True,
                text=True,
                timeout=10,
            )
            commits = []
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n"):
                    parts = line.split("|", 2)
                    if len(parts) >= 3:
                        commits.append(
                            {
                                "hash": parts[0][:8],
                                "message": parts[1],
                                "ago": parts[2],
                            }
                        )
            self._json_response({"commits": commits, "count": len(commits)})
        except Exception as e:
            self._json_response({"commits": [], "count": 0, "error": str(e)})

    def _documented_routes(self):
        """Return combined legacy and v1 route tables for docs/spec generation."""
        routes = dict(self._ROUTES)
        self._load_v1_routes()
        routes.update(self._V1_ROUTES or {})
        return routes

    def _serve_api_docs(self):
        """Self-contained API documentation page."""
        from freq import __version__

        routes = self._documented_routes()
        # Group routes by category
        categories = {}
        for path, method_name in sorted(routes.items()):
            if path in ("/", "/dashboard", "/api/docs", "/api/openapi.json"):
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
            rows.append(
                f'<tr><td colspan="2" style="background:rgba(123,47,190,0.1);font-weight:600;'
                f"color:var(--purple-light);letter-spacing:1px;text-transform:uppercase;"
                f'padding:10px 14px">{cat}</td></tr>'
            )
            for ep in categories[cat]:
                rows.append(f"<tr><td><code>{ep['path']}</code></td><td>{ep['description']}</td></tr>")

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

        routes = self._documented_routes()
        paths = {}
        for path, method_name in sorted(routes.items()):
            if path in ("/", "/dashboard", "/api/docs", "/api/openapi.json"):
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

    def _serve_update_check(self):
        """Return cached update check result."""
        from freq import __version__

        with _bg_lock:
            update = _bg_cache.get("update")
        if update:
            self._json_response(update)
        else:
            self._json_response(
                {
                    "current": __version__,
                    "latest": "",
                    "update_available": False,
                    "checked_at": 0,
                }
            )

    # ── Alert Rules Endpoints ──────────────────────────────────────────

    def _serve_setup_status(self):
        """Return current setup state including SSH key existence."""
        from freq import __version__

        cfg = load_config()
        ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
        self._json_response(
            {
                "first_run": _is_first_run(),
                "version": __version__,
                "ssh_key_exists": os.path.isfile(ed_key),
                "ssh_key_path": ed_key,
                "pve_nodes_configured": bool(cfg.pve_nodes),
            }
        )

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
            self._json_response({"error": "Username and password required"}, 400)
            return

        # Validate username
        if not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", username):
            self._json_response(
                {"error": "Invalid username (lowercase, 1-32 chars, alphanumeric/hyphens/underscores)"},
                400,
            )
            return

        if len(password) < 8:
            self._json_response({"error": "Password must be at least 8 characters"}, 400)
            return

        cfg = load_config()

        # Create user in users.conf
        users = _load_users(cfg)
        if any(u["username"] == username for u in users):
            self._json_response({"error": f"User '{username}' already exists"}, 409)
            return

        users.append({"username": username, "role": "admin", "groups": ""})
        os.makedirs(cfg.conf_dir, exist_ok=True)
        if not _save_users(cfg, users):
            self._json_response({"error": "Failed to save user"}, 500)
            return

        # Store password hash in vault
        pw_hash = _hash_password(password)
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

        body = self._request_body() if self.command == "POST" else {}
        params = _parse_query(self)
        cluster_name = str(body.get("cluster_name", params.get("cluster_name", [""])[0])).strip()
        timezone = str(body.get("timezone", params.get("timezone", ["UTC"])[0])).strip()
        pve_nodes_value = body.get("pve_nodes", params.get("pve_nodes", [""])[0])
        if isinstance(pve_nodes_value, list):
            node_ips = [str(ip).strip() for ip in pve_nodes_value if str(ip).strip()]
        else:
            pve_nodes = str(pve_nodes_value).strip()
            node_ips = [ip.strip() for ip in pve_nodes.split(",") if ip.strip()] if pve_nodes else []

        if not cluster_name:
            self._json_response({"error": "cluster_name is required"}, 400)
            return
        if not node_ips:
            self._json_response({"error": "At least one PVE node IP is required"}, 400)
            return

        try:
            import zoneinfo

            zoneinfo.ZoneInfo(timezone or "UTC")
        except Exception:
            self._json_response({"error": f"Invalid timezone: {timezone}"}, 400)
            return

        from freq.core import validate as _val

        invalid_nodes = [ip for ip in node_ips if not _val.ip(ip)]
        if invalid_nodes:
            self._json_response({"error": f"Invalid PVE node IP(s): {', '.join(invalid_nodes)}"}, 400)
            return
        if len(set(node_ips)) != len(node_ips):
            self._json_response({"error": "Duplicate PVE node IPs are not allowed"}, 400)
            return

        node_names = [f"pve{i + 1:02d}" for i in range(len(node_ips))]

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
                    "data",
                    "conf-templates",
                    "freq.toml.example",
                )
                if os.path.isfile(template):
                    with open(template, "r") as f:
                        content = f.read()
                else:
                    content = "[freq]\n\n[pve]\nnodes = []\n"

            # Update only the targeted keys (preserves everything else)
            content = _update_toml_value(content, "cluster_name", cluster_name)
            content = _update_toml_value(content, "timezone", timezone)
            content = _update_toml_value(content, "nodes", node_ips)
            content = _update_toml_value(content, "node_names", node_names)

            with open(toml_path, "w") as f:
                f.write(content)

            self._json_response(
                {
                    "ok": True,
                    "cluster_name": cluster_name,
                    "timezone": timezone,
                    "pve_nodes": node_ips,
                    "pve_node_names": node_names,
                }
            )
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
            ["ssh-keygen", "-t", "ed25519", "-C", f"freq@{hostname}", "-f", ed_key, "-N", "", "-q"],
            capture_output=True,
            text=True,
            timeout=30,
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
                [
                    "ssh-keygen",
                    "-t",
                    "rsa",
                    "-b",
                    "4096",
                    "-C",
                    f"freq-legacy@{hostname}",
                    "-f",
                    rsa_key,
                    "-N",
                    "",
                    "-q",
                ],
                capture_output=True,
                text=True,
                timeout=30,
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

        if not _setup_lock.acquire(blocking=False):
            self._json_response({"error": "Setup already in progress"}, 409)
            return

        try:
            # Re-check after acquiring lock (another request may have completed setup)
            if not _is_first_run():
                self._json_response({"error": "Setup already complete"}, 403)
                return

            cfg = load_config()
            data_dir = cfg.data_dir
            os.makedirs(data_dir, exist_ok=True)
            marker = os.path.join(data_dir, "setup-complete")

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
        finally:
            _setup_lock.release()

    def _serve_setup_test_ssh(self):
        """Test SSH connectivity to a PVE node during setup."""
        if not _is_first_run():
            self._json_response({"error": "Setup already complete"}, 403)
            return

        params = _parse_query(self)
        host = params.get("host", [""])[0].strip()

        if not host:
            self._json_response({"error": "host parameter required"}, 400)
            return

        # Basic IP/hostname validation
        from freq.core import validate as _val

        if not (_val.ip(host) or _val.hostname(host)):
            self._json_response({"error": f"Invalid host: {host}"}, 400)
            return

        cfg = load_config()
        key_path = cfg.ssh_key_path
        user = cfg.ssh_service_account

        try:
            r = ssh_single(
                host=host,
                command="pvesh get /version --output-format json",
                key_path=key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=10,
                htype="pve",
                use_sudo=True,
                cfg=cfg,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    version_info = json.loads(r.stdout)
                    pve_version = version_info.get("version", "unknown")
                except json.JSONDecodeError:
                    pve_version = "unknown"
                self._json_response(
                    {
                        "ok": True,
                        "host": host,
                        "user": user,
                        "pve_version": pve_version,
                    }
                )
            else:
                err = r.stderr.strip()[:200] if r.stderr else "Connection failed"
                self._json_response(
                    {
                        "ok": False,
                        "host": host,
                        "user": user,
                        "error": err,
                    },
                    502,
                )
        except Exception as e:
            self._json_response({"ok": False, "host": host, "error": str(e)[:200]}, 502)

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

    def _serve_pve_metrics(self):
        """Real-time PVE node metrics via PVE API.

        Cached for 4 seconds to prevent hammering PVE when multiple
        JS poll calls arrive near-simultaneously (login burst).
        """
        now = time.time()
        if FreqHandler._pve_metrics_cache and (now - FreqHandler._pve_metrics_ts) < 4:
            self._json_response(FreqHandler._pve_metrics_cache)
            return
        cfg = load_config()
        nodes = []
        for i, ip in enumerate(cfg.pve_nodes):
            name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"pve{i + 1:02d}"
            from freq.modules.pve import _pve_api_call

            data, ok = _pve_api_call(cfg, ip, f"/nodes/{name}/status", timeout=5)
            if ok and isinstance(data, dict):
                cpu_pct = round((data.get("cpu", 0)) * 100, 1)
                mem = data.get("memory", {})
                mem_used = mem.get("used", 0)
                mem_total = mem.get("total", 1)
                mem_pct = round(mem_used / mem_total * 100, 1) if mem_total else 0
                root = data.get("rootfs", {})
                disk_used = root.get("used", 0)
                disk_total = root.get("total", 1)
                disk_pct = round(disk_used / disk_total * 100, 1) if disk_total else 0
                cpuinfo = data.get("cpuinfo", {})
                load = data.get("loadavg", ["0", "0", "0"])
                # Storage pools — query per-node storage for the real disk picture
                storage_pools = []
                st_data, st_ok = _pve_api_call(cfg, ip, f"/nodes/{name}/storage", timeout=3)
                if st_ok and isinstance(st_data, list):
                    for pool in st_data:
                        if not pool.get("active"):
                            continue
                        p_total = pool.get("total", 0)
                        p_used = pool.get("used", 0)
                        p_pct = round(p_used / p_total * 100, 1) if p_total else 0
                        storage_pools.append(
                            {
                                "name": pool.get("storage", ""),
                                "type": pool.get("type", ""),
                                "used_gb": round(p_used / 1024**3, 1),
                                "total_gb": round(p_total / 1024**3, 1),
                                "pct": p_pct,
                            }
                        )

                iowait = round(data.get("wait", 0) * 100, 1)

                nodes.append(
                    {
                        "name": name,
                        "ip": ip,
                        "online": True,
                        "cpu_pct": cpu_pct,
                        "cores": cpuinfo.get("cpus", 0),
                        "model": cpuinfo.get("model", ""),
                        "ram_used_gb": round(mem_used / 1024**3, 1),
                        "ram_total_gb": round(mem_total / 1024**3, 1),
                        "ram_pct": mem_pct,
                        "iowait": iowait,
                        "disk_pct": disk_pct,
                        "disk_used_gb": round(disk_used / 1024**3, 1),
                        "disk_total_gb": round(disk_total / 1024**3, 1),
                        "uptime": data.get("uptime", 0),
                        "load": load,
                        "storage": storage_pools,
                    }
                )
            else:
                nodes.append({"name": name, "ip": ip, "online": False})
        result = {"nodes": nodes, "ts": time.time()}
        FreqHandler._pve_metrics_cache = result
        FreqHandler._pve_metrics_ts = time.time()
        self._json_response(result)

    _pve_rrd_cache = None
    _pve_rrd_ts = 0

    def _serve_pve_rrd(self):
        """PVE RRD time-series data for sparkline charts.

        Returns 1 hour of data (~60 points) per node: CPU%, RAM%, IO wait.
        Cached for 60 seconds — sparklines don't need real-time updates.
        """
        now = time.time()
        if FreqHandler._pve_rrd_cache and (now - FreqHandler._pve_rrd_ts) < 60:
            self._json_response(FreqHandler._pve_rrd_cache)
            return
        cfg = load_config()
        nodes = []
        for i, ip in enumerate(cfg.pve_nodes):
            name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"pve{i + 1:02d}"
            from freq.modules.pve import _pve_api_call

            data, ok = _pve_api_call(cfg, ip, f"/nodes/{name}/rrddata?timeframe=hour", timeout=5)
            if ok and isinstance(data, list):
                cpu = []
                ram = []
                iowait = []
                for pt in data:
                    if not isinstance(pt, dict):
                        continue
                    t = pt.get("time", 0)
                    c = pt.get("cpu")
                    m_used = pt.get("memused")
                    m_total = pt.get("memtotal")
                    io = pt.get("iowait")
                    if c is not None:
                        cpu.append({"t": t, "v": round(c * 100, 1)})
                    if m_used is not None and m_total and m_total > 0:
                        ram.append({"t": t, "v": round(m_used / m_total * 100, 1)})
                    if io is not None:
                        iowait.append({"t": t, "v": round(io * 100, 1)})
                nodes.append(
                    {
                        "name": name,
                        "cpu": cpu[-70:],  # Last ~70 points (just over 1 hour)
                        "ram": ram[-70:],
                        "iowait": iowait[-70:],
                    }
                )
            else:
                nodes.append({"name": name, "cpu": [], "ram": [], "iowait": []})
        result = {"nodes": nodes, "ts": time.time()}
        FreqHandler._pve_rrd_cache = result
        FreqHandler._pve_rrd_ts = time.time()
        self._json_response(result)

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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
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
        rel = path[len("/static/") :]
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
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

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
            {
                "number": l[0],
                "session": l[1],
                "platform": l[2],
                "severity": l[3],
                "title": l[4],
                "description": l[5],
                "commands": l[6],
            }
            for l in lessons
        ]
        gotcha_list = [{"platform": g[0], "trigger": g[1], "description": g[2], "fix": g[3]} for g in gotchas]

        self._json_response({"query": query, "lessons": lesson_list, "gotchas": gotcha_list})

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
                'echo "=== SYSTEM === ";uname -sr; uptime;'
                'echo "=== PF STATUS === ";pfctl -s info 2>/dev/null | head -12;'
                'echo "=== GATEWAY === ";netstat -rn | grep default | head -5'
            ),
            "rules": (
                'echo "=== FILTER RULES === ";'
                "pfctl -sr 2>/dev/null | grep -v '^scrub' | grep -v '^anchor' | "
                'sed \'s/ label "[^"]*"//g; s/ ridentifier [0-9]*//g\' | '
                "grep -v 'icmp6-type' | "
                "awk '{"
                '  action=$1; dir=$2; quick="";'
                '  if($3=="quick"){quick=" quick"; iface=$5; rest="";'
                '    for(i=6;i<=NF;i++) rest=rest" "$i}'
                '  else{iface=$4; rest="";'
                '    for(i=5;i<=NF;i++) rest=rest" "$i}'
                '  gsub(/^ /,"",rest);'
                '  if(action=="block") color="BLOCK";'
                '  else if(action=="pass") color="PASS";'
                "  else color=action;"
                '  printf "%-6s %-4s %-8s  %-18s  %s\\n", toupper(color), dir, quick, iface, rest'
                "}' | head -40;"
                'echo "";'
                'echo "=== SUMMARY === ";'
                "total=$(pfctl -sr 2>/dev/null | wc -l | tr -d ' ');"
                "blocks=$(pfctl -sr 2>/dev/null | grep -c '^block');"
                "passes=$(pfctl -sr 2>/dev/null | grep -c '^pass');"
                "scrubs=$(pfctl -sr 2>/dev/null | grep -c '^scrub');"
                'printf \'Total: %s  |  Pass: %s  |  Block: %s  |  Scrub: %s\\n\' "$total" "$passes" "$blocks" "$scrubs"'
            ),
            "nat": (
                'echo "=== NAT RULES === ";'
                "pfctl -sn 2>/dev/null | grep -v '^no ' | grep -v '^rdr-anchor' | grep -v '^nat-anchor' | "
                "awk '{"
                "  type=$1;"
                '  if(type=="nat"){'
                '    iface=$3; proto=""; src=""; dst=""; arrow=""; target="";'
                "    for(i=4;i<=NF;i++){"
                '      if($i=="inet"||$i=="inet6") proto=$i;'
                '      else if($i=="from"){src=$(i+1); i++}'
                '      else if($i=="to"){dst=$(i+1); i++}'
                '      else if($i=="->"){target=$(i+1); i++}'
                "    }"
                '    if(src=="any") src="*";'
                '    if(dst=="any") dst="*";'
                '    printf "NAT  %-14s  %-6s  %-22s -> %-22s  => %s\\n", iface, proto, src, dst, target'
                "  }"
                '  else if(type=="rdr"){'
                '    iface=$3; proto=""; src=""; port=""; target=""; tport="";'
                "    for(i=4;i<=NF;i++){"
                '      if($i=="proto"){proto=$(i+1); i++}'
                '      else if($i=="to" && target==""){dst=$(i+1); i++; if($(i+1)=="port"){port=$(i+2); i+=2}}'
                '      else if($i=="->"){target=$(i+1); i++; if($(i+1)=="port"){tport=$(i+2); i+=2}}'
                "    }"
                '    printf "RDR  %-14s  %-6s  %-22s => %s:%s\\n", iface, proto, dst":"port, target, tport'
                "  }"
                "}';"
                'echo "";'
                'echo "=== PORT FORWARDS === ";'
                "pfctl -sn 2>/dev/null | grep '^rdr' | grep -v 'anchor' | "
                "sed 's/ ridentifier [0-9]*//g' | head -10;"
                'echo "";'
                'echo "=== SUMMARY === ";'
                "nat_count=$(pfctl -sn 2>/dev/null | grep -c '^nat');"
                "rdr_count=$(pfctl -sn 2>/dev/null | grep -c '^rdr[^-]');"
                'printf \'NAT rules: %s  |  Port forwards: %s\\n\' "$nat_count" "$rdr_count"'
            ),
            "states": (
                "echo \"Active states: $(pfctl -ss 2>/dev/null | wc -l | tr -d ' ')\";"
                'echo "";echo "=== TOP STATES (by source) === ";'
                "pfctl -ss 2>/dev/null | awk '{print $3}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -15"
            ),
            "interfaces": (
                'echo "=== INTERFACES WITH IPs === ";'
                "ifconfig -a | grep -E '^[a-z]|inet ' | awk '/^[a-z]/{iface=$1} /inet /{print iface, $2}' | column -t; "
                "echo \"\";echo \"=== ALL INTERFACES === \";ifconfig -l | tr ' ' '\\n'"
            ),
            "gateways": (
                'echo "=== ROUTING TABLE === ";netstat -rn | head -25;'
                'echo "";echo "=== DEFAULT GATEWAYS === ";netstat -rn | grep default'
            ),
            "vpn": (
                'echo "=== WIREGUARD TUNNELS === ";wg show 2>/dev/null || echo No_WireGuard_tunnels;'
                'echo "";echo "=== IPSEC === ";ipsec statusall 2>/dev/null | head -10 || echo No_IPsec'
            ),
            "arp": (
                'echo "=== ARP TABLE === ";'
                'echo "";'
                "printf '%-18s  %-20s  %-16s  %-8s\\n' 'IP ADDRESS' 'MAC ADDRESS' 'INTERFACE' 'TYPE';"
                "printf '%-18s  %-20s  %-16s  %-8s\\n' '──────────────────' '────────────────────' '────────────────' '────────';"
                "arp -an | sed 's/? (//;s/) at / /;s/ on / /;s/ permanent/PERM/;s/ expires in [0-9]* seconds//' | "
                "sed 's/\\[ethernet\\]//;s/\\[vlan\\]//' | "
                'awk \'{printf "%-18s  %-20s  %-16s  %-8s\\n", $1, $2, $3, ($4=="PERM"?"PERM":"DYN")}\' | '
                "sort -t. -k1,1n -k2,2n -k3,3n -k4,4n;"
                'echo "";'
                'echo "=== SUMMARY === ";'
                "total=$(arp -an | wc -l | tr -d ' ');"
                "perm=$(arp -an | grep -c 'permanent');"
                "dyn=$((total - perm));"
                'printf \'Total: %s  |  Permanent: %s  |  Dynamic: %s\\n\' "$total" "$perm" "$dyn";'
                'echo "";'
                'echo "=== BY INTERFACE === ";'
                "arp -an | awk '{for(i=1;i<=NF;i++) if($i==\"on\") print $(i+1)}' | sort | uniq -c | sort -rn | "
                "awk '{printf \"  %-16s  %s entries\\n\", $2, $1}'"
            ),
            "services": (
                'echo "=== RUNNING SERVICES === ";'
                "for svc in sshd unbound dhcpd ntpd dpinger filterdns syslogd; do "
                "  pid=$(pgrep -x $svc 2>/dev/null); "
                '  [ -n "$pid" ] && printf \'  %-12s RUNNING (PID %s)\\n\' "$svc" "$pid" || printf \'  %-12s STOPPED\\n\' "$svc"; '
                "done"
            ),
            "log": (
                'echo "=== RECENT FIREWALL LOG (last 30) === ";'
                "tail -30 /var/log/filter.log 2>/dev/null || echo Log_unavailable"
            ),
            "dhcp": (
                'echo "=== DHCP LEASES === ";'
                "cat /var/dhcpd/var/db/dhcpd.leases 2>/dev/null | grep -E 'lease|starts|ends|hardware|client-hostname' | head -60 || echo No_DHCP_leases"
            ),
            "gateway_monitor": (
                'echo "=== GATEWAY STATUS === ";'
                "pfctl -s info 2>/dev/null | grep -i status | head -2; "
                'echo "";echo "=== DPINGER (latency/loss) === ";'
                "cat /tmp/dpinger_*.sock 2>/dev/null || echo dpinger_unavailable; "
                'echo "";echo "=== WAN INTERFACES === ";'
                "netstat -rn | grep default; "
                'echo "";echo "=== PING TEST === ";'
                "ping -c 3 -t 3 1.1.1.1 2>/dev/null | tail -3 || echo Ping_failed"
            ),
            "dns": (
                'echo "=== UNBOUND STATUS === ";'
                "unbound-control status 2>/dev/null | head -10 || echo Unbound_not_running; "
                'echo "";echo "=== CACHE STATS === ";'
                "unbound-control stats_noreset 2>/dev/null | grep -E 'total.num|cache.count|num.query' | head -15 || echo Stats_unavailable; "
                'echo "";echo "=== DNS TEST === ";'
                "drill google.com @127.0.0.1 2>/dev/null | grep -E 'rcode|ANSWER|Query time' | head -5 || "
                "host google.com 127.0.0.1 2>/dev/null | head -3 || echo DNS_test_failed"
            ),
            "traffic": (
                'echo "=== INTERFACE TRAFFIC === ";'
                "netstat -ibnd | head -1; netstat -ibnd | grep -v lo0 | grep Link | head -20; "
                'echo "";echo "=== TOP CONNECTIONS BY STATE === ";'
                "pfctl -ss 2>/dev/null | awk '{print $4}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -15; "
                'echo "";echo "=== BANDWIDTH (bytes in/out per interface) === ";'
                "netstat -I lagg0 -bnd 2>/dev/null | tail -1; "
                "netstat -I lagg1 -bnd 2>/dev/null | tail -1"
            ),
            "syslog": (
                'echo "=== SYSTEM LOG (last 40) === ";'
                "tail -40 /var/log/system.log 2>/dev/null || tail -40 /var/log/messages 2>/dev/null || echo Log_unavailable"
            ),
            "aliases": (
                'echo "=== PF TABLES (aliases) === ";'
                "pfctl -s Tables 2>/dev/null; "
                'echo "";echo "=== TABLE CONTENTS === ";'
                "for tbl in $(pfctl -s Tables 2>/dev/null); do "
                "  cnt=$(pfctl -t $tbl -T show 2>/dev/null | wc -l | tr -d ' '); "
                '  echo "$tbl ($cnt entries)"; '
                "  pfctl -t $tbl -T show 2>/dev/null | head -10; "
                '  echo "";'
                "done"
            ),
            "backup": (
                'echo "=== CONFIG BACKUP === ";'
                "ls -la /cf/conf/backup/ 2>/dev/null | tail -10 || echo No_backups_found; "
                'echo "";echo "=== CURRENT CONFIG === ";'
                "ls -la /cf/conf/config.xml 2>/dev/null; "
                'echo "";echo "=== LAST MODIFIED === ";'
                "stat -f '%Sm' /cf/conf/config.xml 2>/dev/null || stat -c '%y' /cf/conf/config.xml 2>/dev/null || echo Unknown"
            ),
        }

        cmd = actions.get(action, actions["status"])
        r = ssh_single(
            host=pf_ip,
            command=cmd,
            key_path=cfg.ssh_key_path,
            command_timeout=15,
            htype="pfsense",
            use_sudo=False,
            cfg=cfg,
        )

        self._json_response(
            {
                "action": action,
                "host": pf_ip,
                "reachable": r.returncode == 0,
                "output": r.stdout if r.returncode == 0 else "",
                "error": r.stderr[:100] if r.returncode != 0 else "",
            }
        )

    def _serve_config(self):
        cfg = load_config()
        self._json_response(
            {
                "version": cfg.version,
                "brand": cfg.brand,
                "build": cfg.build,
                "ssh_account": cfg.ssh_service_account,
                "ssh_timeout": cfg.ssh_connect_timeout,
                "ssh_parallel": cfg.ssh_max_parallel,
                "pve_nodes": cfg.pve_nodes,
                "cluster": cfg.cluster_name,
                "timezone": cfg.timezone,
                "truenas_ip": cfg.truenas_ip,
                "pfsense_ip": cfg.pfsense_ip,
                "install_dir": cfg.install_dir,
                "hosts_count": len(cfg.hosts),
                "vlans_count": len(cfg.vlans),
                "distros_count": len(cfg.distros),
                "protected_vmids": cfg.protected_vmids,
                "pve_nodes_discovered": [n.get("name", "") for n in _get_discovered_nodes()],
                "kill_chain": _load_kill_chain(cfg) or ["Operator", "VPN", "Firewall", "Switch", "Network", "Target"],
            }
        )

    def _serve_distros(self):
        cfg = load_config()
        distros = [
            {"key": d.key, "name": d.name, "family": d.family, "tier": d.tier, "url": d.url} for d in cfg.distros
        ]
        self._json_response({"distros": distros, "count": len(distros)})

    def _serve_agent_create(self):
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return
        cfg = load_config()
        params = _parse_query(self)
        template = params.get("template", ["blank"])[0]
        name = params.get("name", [template])[0]
        if not valid_label(name):
            self._json_response({"error": "Invalid agent name (alphanumeric + hyphens only)"})
            return
        agents = _load_agents(cfg)
        if name in agents:
            self._json_response({"error": f"Agent '{name}' already exists"})
            return
        tmpl = TEMPLATES.get(template, TEMPLATES.get("blank"))
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            self._json_response({"error": "No PVE node reachable"})
            return
        stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
        if not ok:
            self._json_response({"error": "Cannot allocate VMID"})
            return
        lab_cat = cfg.fleet_boundaries.categories.get("lab", {})
        vmid_floor = lab_cat.get("range_start", 5000)
        vmid = max(int(stdout.strip()), vmid_floor)
        cmd = f"qm create {vmid} --name {name} --cores {tmpl['cores']} --memory {tmpl['ram']} --cpu {cfg.vm_cpu} --machine {cfg.vm_machine} --net0 virtio,bridge={cfg.nic_bridge} --scsihw {cfg.vm_scsihw}"
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
        if not ok:
            self._json_response({"error": f"VM creation failed: {stdout[:60]}"})
            return
        agents[name] = {
            "name": name,
            "template": template,
            "vmid": vmid,
            "node": node_ip,
            "status": "created",
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cores": tmpl["cores"],
            "ram": tmpl["ram"],
            "disk": tmpl["disk"],
        }
        _save_agents(cfg, agents)
        md_dir = os.path.join(cfg.data_dir, "jarvis", "agents", name)
        os.makedirs(md_dir, exist_ok=True)
        with open(os.path.join(md_dir, "CLAUDE.md"), "w") as f:
            f.write(tmpl["claude_md"].format(name=name))
        self._json_response({"ok": True, "name": name, "vmid": vmid, "template": template})

    def _serve_agent_destroy(self):
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return
        cfg = load_config()
        params = _parse_query(self)
        name = params.get("name", [""])[0]
        agents = _load_agents(cfg)
        if name not in agents:
            self._json_response({"error": f"Agent not found: {name}"})
            return
        vmid = agents[name].get("vmid")
        if vmid:
            node_ip = _find_reachable_node(cfg)
            if node_ip:
                _pve_cmd(cfg, node_ip, f"qm stop {vmid} --skiplock", timeout=30)
                _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=120)
        del agents[name]
        _save_agents(cfg, agents)
        md_dir = os.path.join(cfg.data_dir, "jarvis", "agents", name)
        if os.path.isdir(md_dir):
            shutil.rmtree(md_dir)
        self._json_response({"ok": True, "name": name, "vmid": vmid})

    def _serve_notify_test(self):
        cfg = load_config()
        results = jarvis_notify(cfg, "Test notification from FREQ Web UI", severity="info")
        self._json_response(
            {
                "results": {k: v for k, v in results.items()},
                "discord_configured": bool(cfg.discord_webhook),
                "slack_configured": bool(cfg.slack_webhook),
            }
        )

    def _serve_media_status(self):
        """All containers across all VMs."""
        cfg = load_config()
        containers = []
        for vm in sorted(cfg.container_vms.values(), key=lambda v: v.vm_id):
            resolved_ip = _resolve_container_vm_ip(vm)
            r = ssh_single(
                host=resolved_ip,
                command="docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null",
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=10,
                htype="docker",
                use_sudo=False,
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
                containers.append(
                    {
                        "name": cname,
                        "vm_id": vm.vm_id,
                        "vm_label": vm.label,
                        "vm_ip": resolved_ip,
                        "port": container.port,
                        "status": "up" if "Up" in status else "down",
                        "detail": status,
                    }
                )
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
                    key_path=cfg.ssh_key_path,
                    connect_timeout=3,
                    command_timeout=5,
                    htype="docker",
                    use_sudo=False,
                    cfg=cfg,
                )
                code = r.stdout.strip()[-3:] if r.returncode == 0 else "000"
                healthy = code in ("200", "301", "302")
                results.append(
                    {
                        "name": cname,
                        "vm_label": vm.label,
                        "status": "healthy" if healthy else "down",
                        "http_code": code,
                        "port": container.port,
                    }
                )
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
                        key_path=cfg.ssh_key_path,
                        connect_timeout=3,
                        command_timeout=10,
                        htype="docker",
                        use_sudo=False,
                    )
                    if r.returncode == 0:
                        # Response may have "Ok.\n" or "Fails.\n" prefix from login
                        stdout = r.stdout
                        bracket = stdout.find("[")
                        if bracket >= 0:
                            stdout = stdout[bracket:]
                        try:
                            for t in json.loads(stdout):
                                downloads.append(
                                    {
                                        "name": t.get("name", "?"),
                                        "size": t.get("size", 0),
                                        "progress": round(t.get("progress", 0) * 100),
                                        "speed": t.get("dlspeed", 0),
                                        "client": "qBittorrent",
                                        "vm": vm.label,
                                    }
                                )
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
                        key_path=cfg.ssh_key_path,
                        connect_timeout=3,
                        command_timeout=10,
                        htype="docker",
                        use_sudo=False,
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
                                downloads.append(
                                    {
                                        "name": s.get("filename", "?"),
                                        "size": int(size_mb),
                                        "progress": pct,
                                        "speed": int(speed_val),
                                        "client": "SABnzbd",
                                        "vm": vm.label,
                                    }
                                )
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
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=10,
                htype="docker",
                use_sudo=False,
            )
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout)
                    for s in data.get("response", {}).get("data", {}).get("sessions", []):
                        sessions.append(
                            {
                                "user": s.get("friendly_name", "?"),
                                "title": s.get("full_title", s.get("title", "?")),
                                "type": s.get("media_type", "?"),
                                "quality": s.get("video_resolution", "?"),
                                "state": s.get("state", "?"),
                            }
                        )
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
                    key_path=cfg.ssh_key_path,
                    connect_timeout=3,
                    command_timeout=10,
                    htype="docker",
                    use_sudo=False,
                )
                if r.returncode == 0:
                    try:
                        running += int(r.stdout.strip())
                    except ValueError:
                        pass

        self._json_response(
            {
                "containers_total": total,
                "containers_running": running,
                "containers_down": total - running,
                "vm_count": len(cfg.container_vms),
            }
        )

    def _serve_media_restart(self):
        """Restart a container (GET with ?name=xxx)."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err})
            return
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
            host=_resolve_container_vm_ip(vm),
            command=f"docker restart {container.name}",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=60,
            htype="docker",
            use_sudo=False,
        )
        self._json_response(
            {
                "ok": r.returncode == 0,
                "container": container.name,
                "vm": vm.label,
            }
        )

    def _serve_media_logs(self):
        """Container logs (GET with ?name=xxx&lines=50)."""
        cfg = load_config()

        query = _parse_query(self)
        name = query.get("name", [""])[0]
        try:
            lines = int(query.get("lines", ["50"])[0])
        except ValueError:
            lines = 50

        if not name:
            self._json_response({"error": "name parameter required"})
            return

        container, vm = res.container_by_name(cfg.container_vms, name)
        if not container:
            self._json_response({"error": f"container not found: {name}"})
            return

        r = ssh_single(
            host=_resolve_container_vm_ip(vm),
            command=f"docker logs --tail {lines} {container.name} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=15,
            htype="docker",
            use_sudo=False,
        )
        self._json_response(
            {
                "container": container.name,
                "vm": vm.label,
                "logs": r.stdout if r.returncode == 0 else r.stderr,
            }
        )

    def _serve_media_update(self):
        """Update a container (GET with ?name=xxx)."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return
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
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=120,
            htype="docker",
            use_sudo=False,
        )
        self._json_response(
            {
                "ok": r.returncode == 0,
                "container": container.name,
                "vm": vm.label,
                "output": r.stdout[:500] if r.stdout else r.stderr[:500],
            }
        )

    # ── Container Registry Management ──────────────────────────────────

    def _serve_lab_status(self):
        """Lab fleet status."""
        cfg = load_config()

        lab_hosts = [h for h in cfg.hosts if "lab" in (h.groups or "").split(",")]

        hosts = []
        for h in lab_hosts:
            r = ssh_single(
                host=h.ip,
                command="uptime -p 2>/dev/null || echo unknown",
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=5,
                htype="linux",
                use_sudo=False,
                cfg=cfg,
            )
            hosts.append(
                {
                    "label": h.label,
                    "ip": h.ip,
                    "role": h.htype,
                    "status": "up" if r.returncode == 0 else "down",
                    "uptime": r.stdout.strip().replace("up ", "")[:30] if r.returncode == 0 else "",
                }
            )

        # Docker containers on docker-dev
        docker_containers = []
        docker_dev_ip = cfg.docker_dev_ip
        if not docker_dev_ip:
            self._json_response({"hosts": hosts, "docker": []})
            return
        r = ssh_single(
            host=docker_dev_ip,
            command="docker ps --format '{{.Names}}|{{.Status}}' 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="docker",
            use_sudo=False,
        )
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.strip().split("\n"):
                parts = line.split("|", 1)
                if len(parts) == 2:
                    docker_containers.append(
                        {
                            "name": parts[0].strip(),
                            "status": "up" if "Up" in parts[1] else "down",
                        }
                    )

        self._json_response({"hosts": hosts, "docker": docker_containers})

    def _serve_specialists(self):
        """Specialist / agent listing."""
        cfg = load_config()
        agents = []
        try:
            for name, a in _load_agents(cfg).items():
                agents.append(
                    {
                        "name": name,
                        "template": a.get("template", "?"),
                        "vmid": a.get("vmid"),
                        "status": a.get("status", "?"),
                    }
                )
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
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err})
            return
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
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err})
            return
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
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err})
            return
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

    # ── Auth (delegated to freq.api.auth) ────────────────────────────

    def _serve_auth_login(self):
        handle_auth_login(self)

    def _serve_auth_verify(self):
        handle_auth_verify(self)

    def _serve_auth_change_password(self):
        handle_auth_change_password(self)

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
                data = json.loads(resp.read().decode())
                self._json_response(data, resp.status)
        except urllib.error.URLError:
            self._json_response(
                {"error": f"WATCHDOG daemon not reachable at localhost:{wd_port}", "watchdog_down": True}
            )
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
        self._json_response(
            {
                "tiers": fb.tiers,
                "categories": cats,
                "physical": {
                    k: {"ip": d.ip, "label": d.label, "type": d.device_type, "tier": d.tier, "detail": d.detail}
                    for k, d in fb.physical.items()
                },
                "pve_nodes": {k: {"ip": n.ip, "detail": n.detail} for k, n in fb.pve_nodes.items()},
                "hosts": [
                    {"ip": h.ip, "label": h.label, "type": h.htype, "groups": h.groups, "all_ips": h.all_ips}
                    for h in cfg.hosts
                ],
            }
        )

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
            valid_actions = {
                "view",
                "start",
                "stop",
                "restart",
                "snapshot",
                "destroy",
                "clone",
                "resize",
                "migrate",
                "configure",
            }
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
                    m = re.search(r"\[([^\]]*)\]", line)
                    if m:
                        current = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
                        if vmid not in current:
                            current.append(vmid)
                            current.sort()
                        lines[i] = f"vmids = [{', '.join(str(v) for v in current)}]\n"
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
                    m = re.search(r"\[([^\]]*)\]", line)
                    if m:
                        current = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
                        current = [v for v in current if v != vmid]
                        lines[i] = f"vmids = [{', '.join(str(v) for v in current)}]\n"
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
                    lines[i] = f"range_start = {rs}\n"
                if in_section and stripped.startswith("range_end"):
                    lines[i] = f"range_end = {re_val}\n"

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
                    lines[i] = f"{tier_name:<9}= [{actions_str}]\n"
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

    def _serve_watch_start(self):
        """Start the FREQ watch daemon."""
        try:
            rc, out, _ = subprocess.Popen(
                ["freq", "watch", "start"], capture_output=True, text=True, timeout=10
            ).communicate()
            self._json_response({"ok": True, "output": out})
        except Exception as e:
            self._json_response({"error": str(e)})

    def _serve_watch_stop(self):
        """Stop the FREQ watch daemon."""
        try:
            rc, out, _ = subprocess.Popen(
                ["freq", "watch", "stop"], capture_output=True, text=True, timeout=10
            ).communicate()
            self._json_response({"ok": True, "output": out})
        except Exception as e:
            self._json_response({"error": str(e)})

    def _serve_dns_lookup(self):
        """Resolve a hostname."""
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        if not host:
            self._json_response({"error": "host required"})
            return
        import re as _re

        if not _re.match(r"^[a-zA-Z0-9._-]+$", host):
            self._json_response({"error": "Invalid hostname"})
            return
        try:
            import socket

            results = socket.getaddrinfo(host, None)
            ips = sorted(set(r[4][0] for r in results))
            self._json_response({"host": host, "ips": ips, "count": len(ips)})
        except socket.gaierror:
            self._json_response({"host": host, "ips": [], "error": "DNS resolution failed"})

    def _serve_portscan(self):
        """Scan ports on a host."""
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        ports_str = query.get("ports", [""])[0]
        if not host or not ports_str:
            self._json_response({"error": "host and ports required"})
            return
        import re as _re, socket

        if not _re.match(r"^[a-zA-Z0-9._-]+$", host):
            self._json_response({"error": "Invalid hostname"})
            return
        results = []
        for p in ports_str.split(","):
            try:
                port = int(p.strip())
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                ok = s.connect_ex((host, port)) == 0
                s.close()
                results.append({"port": port, "open": ok})
            except (ValueError, OSError):
                results.append({"port": p.strip(), "open": False, "error": "invalid"})
        self._json_response({"host": host, "results": results})

    def _serve_backup_schedules(self):
        """List PVE backup schedules from cluster jobs config."""
        cfg = load_config()
        node_ip = _find_reachable_pve_node(cfg)
        if not node_ip:
            self._json_response({"schedules": [], "error": "No PVE node reachable"})
            return
        from freq.core.ssh import run as ssh_single

        r = ssh_single(
            host=node_ip,
            command="cat /etc/pve/jobs.cfg 2>/dev/null || echo ''",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
        )
        self._json_response(
            {"raw": r.stdout if r and r.returncode == 0 else "", "ok": r is not None and r.returncode == 0}
        )

    def _serve_container_action(self):
        """Restart/stop/start a container on a Docker host."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err})
            return
        cfg = load_config()
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        name = query.get("name", [""])[0]
        action = query.get("action", ["restart"])[0]
        if not host or not name:
            self._json_response({"error": "host and name required"})
            return
        if action not in ("restart", "stop", "start"):
            self._json_response({"error": "action must be restart, stop, or start"})
            return
        import re as _re

        if not _re.match(r"^[a-zA-Z0-9._-]+$", name):
            self._json_response({"error": "Invalid container name"})
            return
        from freq.core.ssh import run as ssh_single
        from freq.core.resolve import by_target

        h = by_target(cfg.hosts, host)
        if not h:
            self._json_response({"error": f"Host not found: {host}"})
            return
        r = ssh_single(
            host=h.ip,
            command=f"docker {action} {name} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=5,
            command_timeout=30,
            htype=h.htype,
            use_sudo=False,
            cfg=cfg,
        )
        self._json_response(
            {
                "ok": r.returncode == 0,
                "output": r.stdout.strip() if r else "",
                "action": action,
                "container": name,
                "host": host,
            }
        )

    def _serve_container_logs(self):
        """Get logs from a container on a Docker host."""
        cfg = load_config()
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        name = query.get("name", [""])[0]
        lines = min(int(query.get("lines", ["50"])[0]), 200)
        if not host or not name:
            self._json_response({"error": "host and name required"})
            return
        import re as _re

        if not _re.match(r"^[a-zA-Z0-9._-]+$", name):
            self._json_response({"error": "Invalid container name"})
            return
        from freq.core.ssh import run as ssh_single
        from freq.core.resolve import by_target

        h = by_target(cfg.hosts, host)
        if not h:
            self._json_response({"error": f"Host not found: {host}"})
            return
        r = ssh_single(
            host=h.ip,
            command=f"docker logs --tail {lines} {name} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=5,
            command_timeout=15,
            htype=h.htype,
            use_sudo=False,
            cfg=cfg,
        )
        self._json_response({"output": r.stdout if r else "", "container": name, "host": host, "lines": lines})

    def _serve_fleet_connectivity(self):
        """Check SSH connectivity to all fleet hosts.

        Uses per-host SSH config: legacy devices (iDRAC, switch) get RSA key
        + legacy KexAlgorithms; modern hosts get ed25519.
        """
        cfg = load_config()
        from freq.core.ssh import run as ssh_single, PLATFORM_SSH

        hosts = []
        for h in cfg.hosts:
            # Select key and command based on device type
            htype = getattr(h, "htype", "linux")
            legacy_types = {"idrac", "switch"}
            if htype in legacy_types:
                key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
            else:
                key = cfg.ssh_key_path

            try:
                r = ssh_single(
                    host=h.ip,
                    command="whoami" if htype not in legacy_types else "racadm getversion" if htype == "idrac" else "show version | include uptime",
                    key_path=key,
                    user=cfg.ssh_service_account if htype not in legacy_types else "",
                    connect_timeout=3,
                    command_timeout=5,
                    htype=htype,
                    cfg=cfg,
                )
                reachable = r.returncode == 0
                user = r.stdout.strip() if reachable else ""
            except Exception:
                reachable = False
                user = ""

            hosts.append(
                {
                    "label": h.label,
                    "ip": h.ip,
                    "type": htype,
                    "reachable": reachable,
                    "user": user,
                }
            )
        self._json_response({"hosts": hosts, "total": len(hosts), "reachable": sum(1 for h in hosts if h["reachable"])})

    def _serve_host_diagnostic(self):
        """Full system diagnostic for a single host."""
        cfg = load_config()
        query = _parse_query(self)
        target = query.get("target", [""])[0]
        if not target:
            self._json_response({"error": "target required"})
            return
        from freq.core.ssh import run as ssh_single
        from freq.core.resolve import by_target

        h = by_target(cfg.hosts, target)
        if not h:
            self._json_response({"error": f"Host not found: {target}"})
            return
        cmd = (
            'echo "=== SYSTEM ===" && hostname -f && cat /etc/os-release 2>/dev/null | grep PRETTY && uname -r '
            '&& echo "=== RESOURCES ===" && nproc && free -h | head -2 && df -h / && cat /proc/loadavg '
            '&& echo "=== NETWORK ===" && ip -4 addr show | grep inet | grep -v 127 && ip route show default '
            '&& echo "=== DOCKER ===" && docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "not installed" '
            '&& echo "=== SECURITY ===" && systemctl --failed --no-legend 2>/dev/null | head -5 || echo "ok" '
            '&& echo "=== LISTENING ===" && ss -tlnp 2>/dev/null | grep LISTEN | head -10'
        )
        r = ssh_single(
            host=h.ip,
            command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=5,
            command_timeout=15,
            htype=h.htype,
            use_sudo=True,
            cfg=cfg,
        )
        self._json_response(
            {"host": target, "output": r.stdout if r else "", "ok": r is not None and r.returncode == 0}
        )

    def _request_body(self):
        """Read and parse JSON request body."""
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        if length > 1_000_000:  # 1MB limit
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}

    def _json_response(self, data, status=200):
        """Send a JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    # --- Phase 1: Alerting & Intelligence API Handlers ---

    def _serve_docs_generate(self):
        """Generate docs data."""
        from freq.modules.docs import _gather_fleet_data

        cfg = load_config()
        data = _gather_fleet_data(cfg)
        self._json_response(data)

    def _serve_docs_runbooks(self):
        """List runbooks."""
        from freq.modules.docs import _runbook_dir

        cfg = load_config()
        import os as os_mod

        rdir = _runbook_dir(cfg)
        runbooks = [f.replace(".json", "") for f in os_mod.listdir(rdir) if f.endswith(".json")]
        self._json_response({"runbooks": runbooks, "count": len(runbooks)})

    # --- Phase 5: Medium Kills API Handlers ---


def cmd_serve(cfg, pack, args) -> int:
    """Start the FREQ web dashboard."""
    port = getattr(args, "port", None) or cfg.dashboard_port or 8888
    print(f"\n  \033[38;5;93mPVE FREQ → Dashboard\033[0m")
    print(f"  Starting on port {port}...\n")
    start_background_cache()

    httpd = ThreadedHTTPServer(("0.0.0.0", port), FreqHandler)

    # Wrap in TLS if certs exist
    use_tls = False
    if cfg.tls_cert and cfg.tls_key and os.path.isfile(cfg.tls_cert) and os.path.isfile(cfg.tls_key):
        import ssl

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ssl_ctx.load_cert_chain(cfg.tls_cert, cfg.tls_key)
            httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)
            use_tls = True
        except Exception as e:
            logger.warning(f"dashboard_tls_failed: {e} — falling back to HTTP")

    proto = "https" if use_tls else "http"
    logger.info("dashboard_start", port=port, host="0.0.0.0", tls=use_tls)
    print(f"  \033[38;5;82m✔\033[0m Dashboard running at {proto}://0.0.0.0:{port}")
    print(f"  \033[38;5;245mPress Ctrl+C to stop\033[0m\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  \033[38;5;220mDashboard stopped.\033[0m")
    finally:
        httpd.server_close()
    return 0
