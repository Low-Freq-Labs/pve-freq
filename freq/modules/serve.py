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
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from freq.core import audit
from freq.core import log as logger
from freq.core import resolve as res
from freq.core.config import load_config, load_toml
from freq.core.health_state import (
    STATE_LIVE,
    STATE_STALE,
    STATE_DEGRADED,
    STATE_AUTH_FAILED,
    STATE_UNREACHABLE,
    STATE_RECOVERING,
    aggregate_probe_state,
    classify_probe_failure,
    entry_base,
    legacy_status_for,
    mark_stale,
)
from freq.core.ssh import run as ssh_single, run_many as ssh_run_many
from freq.core import truenas_api
from freq.core.device_credentials import resolve_device_ssh_auth, resolve_staged_device_ssh_auth
from freq.core.validate import (
    label as valid_label,
)
from freq.modules.pve import _find_reachable_node, _pve_cmd
from freq.modules.users import _load_users, _save_users, _save_users_error
from freq.modules.vault import vault_get, vault_set, vault_init
from freq.jarvis.agent import TEMPLATES, _load_agents, _save_agents
from freq.jarvis.notify import notify as jarvis_notify
from freq.jarvis.risk import _load_kill_chain


IDRAC_READ_CONNECT_TIMEOUT = 10
IDRAC_READ_COMMAND_TIMEOUT = 30
IDRAC_SESSION_LOCK = threading.Lock()
IDRAC_SESSION_GAP_SECONDS = 2.0
_idrac_last_session_at = 0.0


def _redact_device_command_output(output: str) -> str:
    """Strip secrets from raw device CLI output before it reaches the UI."""
    text = str(output or "")
    text = re.sub(
        r"(?im)^(\s*(?:private key|preshared key)\s*:\s*).*$",
        r"\1[redacted]",
        text,
    )
    return text


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server — won't block on slow API calls."""

    daemon_threads = True
    allow_reuse_address = True
    allow_reuse_port = False

    def handle_error(self, request, client_address):
        """Keep benign TLS disconnects from looking like app crashes."""
        import sys

        exc = sys.exc_info()[1]
        if isinstance(exc, ssl.SSLError) and "UNEXPECTED_EOF_WHILE_READING" in str(exc):
            logger.info("tls_client_disconnect", client=f"{client_address[0]}:{client_address[1]}")
            return
        super().handle_error(request, client_address)


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

# six-state health contract state-tracking.
# These track per-host evidence across probe cycles so we can emit
# reason + last_success_at + a one-cycle 'recovering' marker after a
# circuit-breaker backoff resets. Keyed by host IP.
_host_last_success_at = {}       # ip -> unix ts of last 'live' probe
_host_last_error = {}            # ip -> {"state","reason","at"} last failure
_host_backoff_started_at = {}    # ip -> unix ts when current backoff began
_host_recovering = set()         # ip -> just came back, hold 'recovering' one cycle
_SERVER_START_TIME = time.monotonic()
DEFAULT_LOG_LINES = 50


def _run_idrac_subprocess(cmd, timeout):
    """Serialize iDRAC SSH reads to avoid exhausting legacy BMC sessions."""
    global _idrac_last_session_at
    with IDRAC_SESSION_LOCK:
        since = time.monotonic() - _idrac_last_session_at
        if since < IDRAC_SESSION_GAP_SECONDS:
            time.sleep(IDRAC_SESSION_GAP_SECONDS - since)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        _idrac_last_session_at = time.monotonic()
        return proc

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
_bg_cache_errors = {}  # key -> {"error": str, "failed_at": float, "consecutive": int}
_bg_cache_from_disk = set()  # keys loaded from disk (not yet re-probed this instance)
UPDATE_CHECK_INTERVAL = 6 * 3600  # 6 hours
HOSTS_SYNC_INTERVAL = 3600  # 1 hour — keep hosts.toml in sync with PVE
NODE_DISCOVERY_INTERVAL = 300  # 5 min — discover PVE cluster nodes
VM_TAGS_INTERVAL = 300  # 5 min — refresh PVE VM tags
_bg_lock = threading.Lock()
_setup_lock = threading.Lock()
_setup_init_lock = threading.Lock()
_setup_init_job = None
_shutdown_flag = threading.Event()  # Set on SIGTERM to stop background loops

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


def _is_routine_legacy_health_change(
    prev_state: str,
    prev_reason: str,
    cur_state: str,
    cur_reason: str,
    htype: str = "",
) -> bool:
    """Return True for expected legacy-device rate-limit churn.

    Switches and BMCs are intentionally probed less often than normal Linux
    hosts. Between real probes the cache may mark them stale for freshness,
    then live again on the next scheduled probe. That transition is useful
    metadata, not an operator event, and must not create recurring toasts.
    """
    prev_reason = (prev_reason or "").lower()
    cur_reason = (cur_reason or "").lower()
    htype = (htype or "").lower()
    rate_limited = "legacy-device rate limit" in prev_reason or "legacy-device rate limit" in cur_reason
    metrics_probe_noise = (
        "legacy device reachable; metrics probe failed" in prev_reason
        or "legacy device reachable; metrics probe failed" in cur_reason
        or "probe command timed out" in cur_reason
        or "probe parse error" in cur_reason
    )
    if htype in LEGACY_HTYPES and (rate_limited or metrics_probe_noise):
        if cur_state in (STATE_STALE, STATE_DEGRADED, STATE_UNREACHABLE):
            return True
        if prev_state in (STATE_STALE, STATE_DEGRADED, STATE_UNREACHABLE) and cur_state in (
            STATE_LIVE,
            STATE_RECOVERING,
        ):
            return True
    if not rate_limited:
        return False
    return (
        (prev_state == STATE_LIVE and cur_state == STATE_STALE)
        or (prev_state == STATE_STALE and cur_state in (STATE_LIVE, STATE_RECOVERING))
    )


def _reuse_skipped_health(prev: dict, now_wall: float, skip_reason: str) -> dict:
    """Return honest cached health for a skipped probe cycle.

    Circuit-breaker skips are stale because the host is intentionally not being
    retried after failures. Routine legacy-device rate limiting is different:
    the previous real probe is still the newest truth, so preserve its state and
    mark only the freshness metadata.
    """
    if "legacy-device rate limit" in (skip_reason or ""):
        reused = dict(prev)
        reused["freshness"] = "rate_limited"
        reused["freshness_reason"] = skip_reason
        reused["skip_reason"] = skip_reason
        try:
            probed_at = float(prev.get("probed_at") or now_wall)
        except (TypeError, ValueError):
            probed_at = now_wall
        reused["age_seconds"] = max(0, round(now_wall - probed_at, 1))
        return reused
    return mark_stale(prev, now_wall, skip_reason)


def _reuse_recent_legacy_success(prev: dict, now_wall: float, failure_reason: str):
    """Reuse a recent successful legacy-controller probe after transient noise.

    iDRAC and older switches have tiny SSH session pools and occasionally
    reject or stall a read while remaining reachable. If the previous real
    probe was green and still inside the legacy freshness window, preserve that
    truth and annotate the transient failure instead of turning the dashboard
    red for a session-limit/timeout blip.
    """
    if not isinstance(prev, dict):
        return None
    state = str(prev.get("state") or prev.get("status") or "").lower()
    if state not in {STATE_LIVE, STATE_RECOVERING}:
        return None
    try:
        probed_at = float(prev.get("probed_at") or prev.get("last_success_at") or 0)
    except (TypeError, ValueError):
        probed_at = 0
    if not probed_at:
        return None
    age = now_wall - probed_at
    if age < 0 or age > (LEGACY_PROBE_INTERVAL * 6):
        return None
    reused = dict(prev)
    reused["freshness"] = "recent_success_reused"
    reused["freshness_reason"] = f"transient legacy probe failure: {failure_reason}"
    reused["last_transient_error"] = failure_reason
    reused["age_seconds"] = round(age, 1)
    return reused


def _reuse_recent_infra_device_success(prev: dict, now_wall: float, failure_reason: str):
    """Reuse recent green infra truth for slow legacy management devices.

    The health probe already preserves recent green iDRAC/switch evidence after
    transient session-limit or timeout noise. The infra_quick probe needs the
    same behavior because watchdog treats core infra_quick failures as hard
    health failures.
    """
    if not isinstance(prev, dict):
        return None
    if prev.get("reachable") is not True or prev.get("auth_failed"):
        return None
    try:
        probed_at = float(prev.get("probed_at") or 0)
    except (TypeError, ValueError):
        probed_at = 0
    if not probed_at:
        return None
    age = now_wall - probed_at
    if age < 0 or age > (LEGACY_PROBE_INTERVAL * 6):
        return None
    reused = dict(prev)
    metrics = dict(reused.get("metrics") or {})
    metrics["note"] = f"Recent green reused after transient legacy probe failure: {failure_reason}"
    reused["metrics"] = metrics
    reused["probe_method"] = "recent_success_reused"
    reused["freshness"] = "recent_success_reused"
    reused["freshness_reason"] = failure_reason
    reused["age_seconds"] = round(age, 1)
    reused["reachable"] = True
    reused["auth_failed"] = False
    return reused


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
    """Load cached probe data from disk — instant startup.

    Marks all loaded entries in _bg_cache_from_disk so API consumers
    know the data is from a previous server instance and may reflect
    a different probe configuration (e.g., different SSH user).
    """
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
                    _bg_cache_from_disk.add(name)
            except (json.JSONDecodeError, OSError) as e:
                logger.warn(f"cache load failed: {name}: {e}")


def _save_disk_cache(name, data):
    """Persist to disk atomically so next server start is instant.

    Cache files are chmod 644 so operator CLI commands (running as a
    non-service-account user) can read them. The cache contains host
    health/metrics data — no secrets — so world-readable is safe.
    """
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
            os.chmod(tmp, 0o644)
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
        return  # Config load failure should not crash background probes
    fb = cfg.fleet_boundaries
    start = time.monotonic()
    now_wall = time.time()
    previous_devices = {}
    try:
        with _bg_lock:
            previous = _bg_cache.get("infra_quick")
        if isinstance(previous, dict):
            previous_probed_at = previous.get("probed_at")
            for item in previous.get("devices", []) or []:
                if isinstance(item, dict):
                    item = dict(item)
                    item.setdefault("probed_at", previous_probed_at)
                    token = item.get("key") or item.get("label") or item.get("ip")
                    if token:
                        previous_devices[str(token)] = item
    except Exception:
        previous_devices = {}

    def _ping_check(ip):
        """Quick ICMP fallback for devices where SSH/API isn't available."""
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, timeout=2)
            return r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _tcp_check(ip, ports, timeout=1.0):
        for port in ports:
            try:
                with socket.create_connection((ip, port), timeout=timeout):
                    return True
            except OSError:
                continue
        return False

    def _network_reachable(dev):
        dt = dev.device_type
        if dt in ("pfsense", "opnsense"):
            return _tcp_check(dev.ip, (443, 80, 22)) or _ping_check(dev.ip)
        if dt in ("truenas", "synology", "unraid"):
            return _tcp_check(dev.ip, (443, 80)) or _ping_check(dev.ip)
        if dt in ("switch", "idrac", "ilo", "ipmi"):
            return _tcp_check(dev.ip, (22,)) or _ping_check(dev.ip)
        return _ping_check(dev.ip)

    # Runtime probes must use the same managed service-account identity that
    # init verifies. Bootstrap/operator keys are for deployment only; using
    # them here lets init drift hide behind stale "network reachable" UI.
    svc_user = cfg.ssh_service_account
    svc_key = cfg.ssh_key_path
    legacy_key = cfg.ssh_rsa_key_path or svc_key
    pfsense_auth = resolve_staged_device_ssh_auth(cfg, "pfsense")

    def _is_auth_failure(stderr):
        """Detect SSH permission denied in stderr.

        Credential failure is not network failure. The dashboard must keep
        the device reachable and show auth/metrics unavailable separately.
        """
        if not stderr:
            return False
        s = stderr.lower()
        return "permission denied" in s or "publickey" in s

    def _probe_device(key, dev):
        d = {
            "key": key,
            "label": dev.label,
            "type": dev.device_type,
            "ip": dev.ip,
            "groups": dev.groups,
            "scope": dev.scope,
            "reachable": False,
            "auth_failed": False,
            "probe_method": "none",
            "metrics": {},
            "probed_at": now_wall,
        }
        prev_device = (
            previous_devices.get(str(key))
            or previous_devices.get(str(dev.label))
            or previous_devices.get(str(dev.ip))
        )
        dt = dev.device_type
        def _reuse_recent_device(reason):
            if dt not in LEGACY_HTYPES:
                return None
            reused = _reuse_recent_infra_device_success(prev_device, now_wall, reason)
            if reused is not None:
                logger.info(
                    "infra_quick_reused_recent_legacy_success",
                    device=dev.label,
                    reason=reason,
                    age_seconds=reused.get("age_seconds"),
                )
            return reused
        try:
            if dt == "pfsense":
                r = ssh_single(
                    host=dev.ip,
                    command='echo "$(sudo pfctl -ss 2>/dev/null | wc -l)|$(uptime)|$(ifconfig -l)"',
                    key_path=pfsense_auth["key_path"],
                    user=pfsense_auth["user"],
                    local_user=pfsense_auth.get("local_user"),
                    password_file=pfsense_auth.get("password_file") or None,
                    sudo_password_file=pfsense_auth.get("sudo_password_file", False),
                    connect_timeout=2,
                    command_timeout=5,
                    htype="pfsense",
                    use_sudo=False,
                    cfg=cfg,
                    failure_log_level="warn",
                )
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    d["probe_method"] = "ssh"
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
                elif _is_auth_failure(r.stderr):
                    # Auth failure is not network failure. Keep the device
                    # reachable when TCP/ICMP says it is there, but make the
                    # metrics credential problem explicit.
                    d["reachable"] = _network_reachable(dev)
                    d["auth_failed"] = True
                    d["probe_method"] = "ssh_auth_failed"
                    d["metrics"]["note"] = "SSH auth failed — credentials rejected"
                else:
                    d["reachable"] = _network_reachable(dev)
                    d["probe_method"] = "network" if d["reachable"] else "none"
            elif dt == "truenas":
                api_settings = truenas_api.settings(cfg, dev)
                pool_data, pool_err = truenas_api.request(api_settings, "pools", timeout=6)
                if not pool_err:
                    d["reachable"] = True
                    d["api_available"] = True
                    d["probe_method"] = "truenas_api_key"
                    d["metrics"].update(truenas_api.pool_metrics(pool_data))
                    alerts, alert_err = truenas_api.request(api_settings, "alerts", timeout=6)
                    if not alert_err and isinstance(alerts, list):
                        d["metrics"]["alerts"] = len(alerts)
                else:
                    auth = resolve_staged_device_ssh_auth(cfg, "truenas")
                    r = ssh_single(
                        host=dev.ip,
                        command=(
                            "hostname && uptime && "
                            "zpool list -o name,size,alloc,free,health -H 2>/dev/null"
                        ),
                        user=auth.get("user") or cfg.ssh_service_account,
                        key_path=auth.get("key_path") or svc_key,
                        local_user=auth.get("local_user") or None,
                        password_file=auth.get("password_file") or None,
                        sudo_password_file=auth.get("sudo_password_file", False),
                        connect_timeout=5,
                        command_timeout=10,
                        htype="truenas",
                        use_sudo=False,
                        cfg=cfg,
                        failure_log_level="warn",
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        d["api_available"] = False
                        d["ssh_available"] = True
                        d["reachable"] = True
                        d["probe_method"] = "ssh"
                        lines = [line.strip() for line in r.stdout.splitlines() if line.strip()]
                        if len(lines) > 1:
                            d["metrics"]["uptime"] = lines[1][:120]
                        pools = []
                        for line in lines[2:]:
                            parts = re.split(r"\s+", line)
                            if len(parts) >= 5:
                                pools.append({
                                    "name": parts[0],
                                    "size": parts[1],
                                    "alloc": parts[2],
                                    "free": parts[3],
                                    "health": parts[4],
                                })
                        if pools:
                            d["metrics"]["pools"] = pools
                            d["metrics"]["pool_health"] = pools[0].get("health", "")
                    else:
                        d["api_available"] = False
                        d["reachable"] = _ping_check(dev.ip)
                        d["probe_method"] = "truenas_api_unreachable" if not d["reachable"] else "network"
                        if d["reachable"]:
                            d["metrics"]["note"] = "Network reachable, no TrueNAS API or SSH metrics"
                        else:
                            d["metrics"]["note"] = f"Network unreachable; {pool_err['error']}"
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
                        f"{svc_user}@{dev.ip}",
                        "show version | include uptime",
                    ]
                    proc = subprocess.run(sw_cmd, capture_output=True, text=True, timeout=10)
                    r = type("R", (), {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})()
                else:
                    r = ssh_single(
                        host=dev.ip,
                        command="show version | include uptime",
                        user=svc_user,
                        key_path=legacy_key,
                        connect_timeout=2,
                        command_timeout=5,
                        htype="switch",
                        use_sudo=False,
                        cfg=cfg,
                        failure_log_level="warn",
                    )
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    d["probe_method"] = "ssh"
                    d["metrics"]["uptime"] = r.stdout.strip()
                elif _is_auth_failure(r.stderr):
                    d["reachable"] = _network_reachable(dev)
                    d["auth_failed"] = True
                    d["probe_method"] = "ssh_auth_failed"
                    d["metrics"]["note"] = "SSH auth failed — credentials rejected"
                else:
                    d["reachable"] = _network_reachable(dev)
                    d["probe_method"] = "network" if d["reachable"] else "none"
                    if d["reachable"]:
                        d["metrics"]["note"] = "Network reachable, no SSH metrics"
            elif dt == "idrac":
                # iDRAC probe MUST match init's verify path for parity with
                # `freq init --check` and `freq fleet status`. Init verifies
                # BMCs as the deployed service account via the RSA key
                # with iDRAC cipher options, falling back to sshpass with
                # cfg.legacy_password_file only if key auth fails. The old
                # code did the opposite — sshpass first with SUDO_USER (the
                # calling operator, not the BMC account) then root@ via key
                # — which left /api/infra/quick reporting auth_failed on
                # BMCs that the CLI had verified green.
                from freq.core.ssh import PLATFORM_SSH as _PLATFORM_SSH_LOCAL
                idrac_user = cfg.ssh_service_account
                idrac_key = legacy_key
                idrac_opts = _PLATFORM_SSH_LOCAL.get("idrac", {}).get("extra_opts", [])
                idrac_cmd = [
                    "ssh", "-n",
                    "-o", f"ConnectTimeout={IDRAC_READ_CONNECT_TIMEOUT}",
                    "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-i", idrac_key,
                ] + idrac_opts + [
                    f"{idrac_user}@{dev.ip}",
                    "racadm getsysinfo -s",
                ]
                proc = _run_idrac_subprocess(idrac_cmd, IDRAC_READ_COMMAND_TIMEOUT)
                r = type("R", (), {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})()

                # Fallback: if key auth hit a permission-denied, try sshpass
                # with cfg.legacy_password_file (still as svc_user). Matches
                # init._verify_host's two-stage verification order.
                if r.returncode != 0 and _is_auth_failure(r.stderr):
                    pw_file = getattr(cfg, "legacy_password_file", "") or ""
                    if pw_file and os.path.isfile(pw_file):
                        sshpass_cmd = [
                            "sshpass", "-f", pw_file, "ssh", "-n",
                            "-o", f"ConnectTimeout={IDRAC_READ_CONNECT_TIMEOUT}",
                            "-o", "StrictHostKeyChecking=accept-new",
                        ] + idrac_opts + [
                            f"{idrac_user}@{dev.ip}",
                            "racadm getsysinfo -s",
                        ]
                        proc2 = _run_idrac_subprocess(sshpass_cmd, IDRAC_READ_COMMAND_TIMEOUT)
                        r = type("R", (), {"returncode": proc2.returncode, "stdout": proc2.stdout, "stderr": proc2.stderr})()
                if r.returncode == 0 and r.stdout.strip():
                    d["reachable"] = True
                    d["probe_method"] = "ssh"
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
                elif _is_auth_failure(r.stderr):
                    d["reachable"] = _network_reachable(dev)
                    d["auth_failed"] = True
                    d["probe_method"] = "ssh_auth_failed"
                    d["metrics"]["note"] = "SSH auth failed — credentials rejected"
                else:
                    d["reachable"] = _network_reachable(dev)
                    d["probe_method"] = "network" if d["reachable"] else "none"
                    if d["reachable"]:
                        reused = _reuse_recent_device((r.stderr or r.stdout or "no SSH metrics").strip()[:200])
                        if reused is not None:
                            return reused
                        d["metrics"]["note"] = "Network reachable, no SSH metrics"
            else:
                # Unknown device type — ping-only probe. The health probe
                # may have more authoritative data if this device is also
                # in cfg.hosts; operators should check both surfaces.
                d["reachable"] = _network_reachable(dev)
                d["probe_method"] = "network" if d["reachable"] else "none"
                if d["reachable"]:
                    d["metrics"]["note"] = "Network reachable — see /api/health for SSH probe state"
        except subprocess.TimeoutExpired as e:
            reused = _reuse_recent_device(f"timeout after {getattr(e, 'timeout', 'unknown')}s")
            if reused is not None:
                return reused
            d["reachable"] = _network_reachable(dev)
            d["probe_method"] = "network" if d["reachable"] else "none"
            d["metrics"]["note"] = f"Legacy probe timed out after {getattr(e, 'timeout', 'unknown')}s"
            logger.warning(f"bg_probe_infra: probe timed out for {key} ({dev.ip}): {e}")
        except Exception as e:
            reused = _reuse_recent_device(str(e)[:200])
            if reused is not None:
                return reused
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

    core_devices = [d for d in devices if d.get("scope", "core") != "lab"]
    lab_devices = [d for d in devices if d.get("scope", "core") == "lab"]
    result = {
        "devices": devices,
        "core_devices": core_devices,
        "lab_devices": lab_devices,
        "duration": round(time.monotonic() - start, 2),
        "probed_at": time.time(),
    }
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
        return  # Config load failure should not crash background probes
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
        # R-RESILIENCE-INIT-RECOVERY-20260413S: iDRAC was previously absent
        # from this map, so the dict-lookup fell back to HEALTH_CMDS["linux"]
        # and the health probe tried to run a POSIX `echo "$(hostname)|..."`
        # against a Dell racadm shell. Every probe failed → the fleet view
        # flipped iDRAC hosts to "unreachable" minutes after each green init.
        # Use `racadm getsysinfo -s` (read-only, fast, no side effects) for
        # reachability — output parsing is optional since iDRACs don't have
        # meaningful cores/ram/disk values in the fleet columns.
        "idrac": "racadm getsysinfo -s",
    }

    def _legacy_network_reachable(h):
        """Return whether a legacy management endpoint is still on-network.

        Legacy device command probes can hang even when the management
        controller itself is reachable. Separate "device is down" from
        "metrics command is stuck" so the dashboard does not lie red.
        """
        try:
            with socket.create_connection((h.ip, 22), timeout=1.0):
                return True
        except OSError:
            pass
        try:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", "1", h.ip],
                capture_output=True,
                timeout=2,
            )
            return r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _probe_host(h):
        """Probe one host and return a six-state entry with full evidence.

        every return path carries a canonical
        `state` token (live/stale/degraded/auth_failed/unreachable/recovering)
        plus `reason`, `probed_at`, `last_success_at`, `failure_count`.
        The legacy `status` field is still set via legacy_status_for() for
        older callers, but the dashboard reads `state` through classifier
        helpers so stale, auth_failed, degraded, and unreachable stay
        distinct.
        """
        htype = h.htype
        cmd = HEALTH_CMDS.get(htype, HEALTH_CMDS["linux"])
        use_sudo = False
        probe_key = (cfg.ssh_rsa_key_path or cfg.ssh_key_path) if htype in ("idrac", "switch") else cfg.ssh_key_path
        probe_user = None
        probe_local_user = None
        probe_password_file = None
        probe_sudo_password_file = False
        if htype in ("pfsense", "idrac", "switch", "truenas"):
            auth = resolve_staged_device_ssh_auth(cfg, htype)
            probe_key = auth.get("key_path") or probe_key
            probe_user = auth.get("user") or None
            probe_local_user = auth.get("local_user") or None
            probe_password_file = auth.get("password_file") or None
            probe_sudo_password_file = auth.get("sudo_password_file", False)
        now = time.time()
        _groups = getattr(h, "groups", "") or ""
        prev_failures = _host_fail_count.get(h.ip, 0)
        last_success_at = _host_last_success_at.get(h.ip)

        if htype == "idrac":
            global _idrac_last_session_at
            with IDRAC_SESSION_LOCK:
                since = time.monotonic() - _idrac_last_session_at
                if since < IDRAC_SESSION_GAP_SECONDS:
                    time.sleep(IDRAC_SESSION_GAP_SECONDS - since)
                r = ssh_single(
                    host=h.ip,
                    command=cmd,
                    key_path=probe_key,
                    user=probe_user,
                    local_user=probe_local_user,
                    password_file=probe_password_file,
                    sudo_password_file=probe_sudo_password_file,
                    connect_timeout=cfg.ssh_connect_timeout,
                    command_timeout=15,
                    htype=htype,
                    use_sudo=use_sudo,
                    cfg=cfg,
                )
                _idrac_last_session_at = time.monotonic()
        else:
            r = ssh_single(
                host=h.ip,
                command=cmd,
                key_path=probe_key,
                user=probe_user,
                local_user=probe_local_user,
                password_file=probe_password_file,
                sudo_password_file=probe_sudo_password_file,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=15,
                htype=htype,
                use_sudo=use_sudo,
                cfg=cfg,
            )

        # ── Failure path ────────────────────────────────────────────
        if r.returncode != 0 or not r.stdout.strip():
            state, reason = classify_probe_failure(
                r.returncode, r.stderr or "", r.stdout or ""
            )
            if htype in LEGACY_HTYPES and state == STATE_UNREACHABLE and _legacy_network_reachable(h):
                prev = None
                with _bg_lock:
                    cached = _bg_cache.get("health")
                    if isinstance(cached, dict):
                        for cached_host in cached.get("hosts", []) or []:
                            if isinstance(cached_host, dict) and cached_host.get("ip") == h.ip:
                                prev = cached_host
                                break
                reused = _reuse_recent_legacy_success(prev, now, reason)
                if reused is not None:
                    return reused
                state = STATE_DEGRADED
                reason = f"legacy device reachable; metrics probe failed: {reason}"
            entry = entry_base(
                h,
                state=state,
                reason=reason,
                probed_at=now,
                last_success_at=last_success_at,
                failure_count=prev_failures + 1,
                groups=_groups,
            )
            entry.update({
                "cores": "-", "ram": "-", "disk": "-",
                "load": "-", "docker": "0",
                # Keep legacy field for any reader that still grep's it.
                "last_error": reason,
            })
            return entry

        # ── Success paths ───────────────────────────────────────────
        # One-cycle 'recovering' marker: if this host was just cleared
        # out of backoff in _host_recovering, flag it so the operator
        # sees 'just healed' instead of a silent green return to normal.
        success_state = (
            STATE_RECOVERING if h.ip in _host_recovering else STATE_LIVE
        )
        success_reason = (
            f"recovered from backoff (was failing for {prev_failures}x)"
            if success_state == STATE_RECOVERING
            else "probe OK"
        )

        if htype == "idrac":
            # iDRAC reachability = "racadm getsysinfo -s returned something".
            # BMCs are management controllers, not compute hosts. CPU/RAM/disk
            # resource columns are not applicable and must be flagged as such
            # so renderers do not coerce "-" into fake numeric metrics.
            bmc_metrics = {}
            for line in r.stdout.strip().split("\n"):
                low = line.lower()
                if "power status" in low:
                    val = line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
                    bmc_metrics["power"] = "ON" if "on" in val.lower() else "OFF"
                elif "inlet temp" in low:
                    bmc_metrics["inlet_temp"] = (
                        line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
                    )
                elif "system model" in low:
                    bmc_metrics["model"] = line.split("=")[-1].strip() if "=" in line else line.split(":")[-1].strip()
            entry = entry_base(
                h,
                state=success_state,
                reason=(success_reason if success_state == STATE_RECOVERING
                        else "racadm getsysinfo -s returned OK"),
                probed_at=now,
                last_success_at=now,
                failure_count=0,
                groups=_groups,
            )
            entry.update({
                "cores": None, "ram": None, "disk": None,
                "load": "-", "docker": "0",
                "resource_metrics_supported": False,
                "unsupported_metrics": ["cpu", "ram", "disk", "load"],
                "management_metrics": bmc_metrics,
            })
            entry.update(bmc_metrics)
            return entry

        if htype == "switch":
            m = re.search(r"one minute:\s*(\d+)%", r.stdout)
            cpu_pct = m.group(1) if m else "0"
            sw_key2 = cfg.ssh_rsa_key_path or cfg.ssh_key_path
            r2 = ssh_single(
                host=h.ip,
                command="show processes memory | include Processor",
                key_path=sw_key2,
                user=probe_user,
                local_user=probe_local_user,
                password_file=probe_password_file,
                sudo_password_file=probe_sudo_password_file,
                connect_timeout=3,
                command_timeout=10,
                htype="switch",
                use_sudo=False,
                cfg=cfg,
            )
            ram = "-"
            ram_parsed = False
            if r2.returncode == 0 and r2.stdout:
                parts = r2.stdout.split()
                try:
                    idx_t = parts.index("Total:") + 1
                    idx_u = parts.index("Used:") + 1
                    total_mb = int(parts[idx_t]) // 1048576
                    used_mb = int(parts[idx_u]) // 1048576
                    ram = f"{used_mb}/{total_mb}MB"
                    ram_parsed = True
                except (ValueError, IndexError):
                    pass
            load_val = f"{float(cpu_pct) / 100:.2f}" if cpu_pct != "0" else "0.00"
            # Primary probe succeeded; if the RAM secondary couldn't be
            # parsed, surface as degraded — partial success is not full
            # success under the product law.
            if not ram_parsed:
                sw_state = STATE_DEGRADED
                sw_reason = "switch CPU probe OK, RAM secondary probe missing/unparsable"
            else:
                sw_state = success_state
                sw_reason = success_reason if success_state == STATE_RECOVERING else "switch CPU+RAM probes OK"
            entry = entry_base(
                h,
                state=sw_state,
                reason=sw_reason,
                probed_at=now,
                last_success_at=now if sw_state != STATE_DEGRADED else last_success_at,
                failure_count=0 if sw_state != STATE_DEGRADED else prev_failures + 1,
                groups=_groups,
            )
            entry.update({
                "cores": "1", "ram": ram, "disk": "-",
                "load": load_val, "docker": "0",
            })
            return entry

        # Linux / PVE / docker / truenas / pfsense — pipe-delimited parse.
        parts = r.stdout.strip().split("|")
        # A too-short output string means the remote shell produced
        # something but the metrics payload is broken. Partial success
        # → degraded, not fake green.
        if len(parts) < 5:
            return entry_base(
                h,
                state=STATE_DEGRADED,
                reason=f"probe returned malformed payload ({len(parts)} fields, expected >=5)",
                probed_at=now,
                last_success_at=last_success_at,
                failure_count=prev_failures + 1,
                groups=_groups,
            ) | {
                "cores": "-", "ram": "-", "disk": "-",
                "load": "-", "docker": "0",
            }
        entry = entry_base(
            h,
            state=success_state,
            reason=success_reason,
            probed_at=now,
            last_success_at=now,
            failure_count=0,
            groups=_groups,
        )
        entry.update({
            "cores": parts[1] if len(parts) > 1 else "?",
            "ram": parts[2] if len(parts) > 2 else "?",
            "disk": parts[3] if len(parts) > 3 else "?",
            "load": parts[4] if len(parts) > 4 else "?",
            "docker": parts[5].strip() if len(parts) > 5 else "0",
        })
        return entry

    # ── Circuit breaker: skip hosts in backoff or legacy hosts probed recently ──
    global _last_legacy_probe
    now = time.monotonic()
    probe_legacy = (now - _last_legacy_probe) >= LEGACY_PROBE_INTERVAL

    active_hosts = []
    skipped_hosts = []     # (host, reason) — reason is an operator-readable string
    for h in cfg.hosts:
        # Skip unmanaged hosts (discovered but not deployed to)
        if not getattr(h, "managed", True):
            continue
        # Skip hosts in circuit-breaker backoff
        if _host_backoff_until.get(h.ip, 0) > now:
            remain = int(_host_backoff_until[h.ip] - now)
            skipped_hosts.append((h, f"circuit breaker backoff ({remain}s remaining)"))
            continue
        # Rate-limit legacy device probes
        if h.htype in LEGACY_HTYPES and not probe_legacy:
            since = int(now - _last_legacy_probe)
            skipped_hosts.append((h, f"legacy-device rate limit (last probe {since}s ago, interval {LEGACY_PROBE_INTERVAL}s)"))
            continue
        active_hosts.append(h)

    if probe_legacy and any(h.htype in LEGACY_HTYPES for h in active_hosts):
        _last_legacy_probe = now

    # log what we skipped this cycle.
    # Previously the probe loop silently dropped backoff/rate-limited
    # hosts into a local variable with no audit trail — operators had
    # no way to reason about why a host card was stale.
    if skipped_hosts:
        logger.info(
            "health_probe_skipped",
            count=len(skipped_hosts),
            hosts=",".join(f"{h.label}:{r}" for h, r in skipped_hosts[:8]),
        )

    # Reuse cached data for skipped hosts. Circuit-breaker skips go stale;
    # routine legacy-device rate-limit skips keep the last real state and only
    # annotate freshness, avoiding false unreachable churn in the dashboard.
    now_wall = time.time()
    host_data = []
    if skipped_hosts:
        with _bg_lock:
            cached = _bg_cache.get("health")
        cached_by_ip = {}
        if cached and isinstance(cached, dict):
            cached_by_ip = {h_e["ip"]: h_e for h_e in cached.get("hosts", [])}
        for h, skip_reason in skipped_hosts:
            prev = cached_by_ip.get(h.ip)
            if prev:
                host_data.append(_reuse_skipped_health(prev, now_wall, skip_reason))
            else:
                # No prior cache for this host — we genuinely have no
                # evidence. Honest state: unreachable, not stale.
                entry = entry_base(
                    h,
                    state=STATE_UNREACHABLE,
                    reason=f"no prior probe result ({skip_reason})",
                    probed_at=now_wall,
                    last_success_at=_host_last_success_at.get(h.ip),
                    failure_count=_host_fail_count.get(h.ip, 0),
                    groups=getattr(h, "groups", "") or "",
                )
                entry.update({
                    "cores": "-", "ram": "-", "disk": "-",
                    "load": "-", "docker": "0",
                    "last_error": skip_reason,
                })
                host_data.append(entry)

    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.ssh_max_parallel) as pool:
        futures = {pool.submit(_probe_host, h): h for h in active_hosts}
        for f in concurrent.futures.as_completed(futures):
            h = futures[f]
            try:
                result_entry = f.result()
                host_data.append(result_entry)
                entry_state = result_entry.get("state", STATE_UNREACHABLE)

                # ── Circuit breaker: success/failure tracking with evidence ──
                # previously circuit-breaker
                # engage and reset logged only a stderr warning. An
                # operator reviewing audit.jsonl found nothing about the
                # system's self-protective backoffs. Both engage and
                # reset now emit audit events with the error class,
                # failure count, and — on reset — the duration of the
                # backoff episode so SLA correlation is possible.
                if entry_state in (STATE_LIVE, STATE_RECOVERING):
                    was_in_backoff = h.ip in _host_backoff_until
                    old_fail_count = _host_fail_count.get(h.ip, 0)
                    backoff_started = _host_backoff_started_at.get(h.ip)
                    _host_fail_count.pop(h.ip, None)
                    _host_backoff_until.pop(h.ip, None)
                    _host_backoff_started_at.pop(h.ip, None)
                    _host_last_error.pop(h.ip, None)
                    _host_last_success_at[h.ip] = now_wall
                    if was_in_backoff:
                        duration = int(now_wall - backoff_started) if backoff_started else None
                        logger.info(
                            "circuit_breaker_reset",
                            host=h.ip,
                            label=h.label,
                            prior_failure_count=old_fail_count,
                            backoff_duration_s=duration,
                        )
                        audit.record(
                            "circuit_breaker_reset",
                            h.ip,
                            "recovered",
                            label=h.label,
                            prior_failure_count=old_fail_count,
                            backoff_duration_s=duration,
                            healed_with=result_entry.get("reason", ""),
                        )
                        _host_recovering.add(h.ip)
                    else:
                        # Clear any lingering recovering marker from the
                        # prior cycle — we've had one cycle of LIVE now.
                        _host_recovering.discard(h.ip)
                else:
                    # Probe failed (classified into one of the non-live
                    # states by _probe_host). Track the error class and
                    # bump the counter.
                    count = _host_fail_count.get(h.ip, 0) + 1
                    _host_fail_count[h.ip] = count
                    _host_last_error[h.ip] = {
                        "state": entry_state,
                        "reason": result_entry.get("reason", ""),
                        "at": now_wall,
                    }
                    if count >= CIRCUIT_BREAKER_THRESHOLD and h.ip not in _host_backoff_until:
                        _host_backoff_until[h.ip] = now + CIRCUIT_BREAKER_BACKOFF
                        _host_backoff_started_at[h.ip] = now_wall
                        logger.warning(
                            f"circuit breaker: {h.label} ({h.ip}) failed {count}x, "
                            f"backing off {CIRCUIT_BREAKER_BACKOFF}s "
                            f"(last error: {result_entry.get('reason', '')[:100]})"
                        )
                        audit.record(
                            "circuit_breaker_engage",
                            h.ip,
                            "engaged",
                            label=h.label,
                            failure_count=count,
                            error_state=entry_state,
                            last_error=result_entry.get("reason", "")[:200],
                            backoff_seconds=CIRCUIT_BREAKER_BACKOFF,
                        )
            except Exception as e:
                logger.warn(f"health probe failed for {h.label}: {e}")
                # Unplanned exception path — classify as degraded so
                # the operator knows the probe itself is broken (not
                # the host).
                err_entry = entry_base(
                    h,
                    state=STATE_DEGRADED,
                    reason=f"probe exception: {str(e)[:120]}",
                    probed_at=now_wall,
                    last_success_at=_host_last_success_at.get(h.ip),
                    failure_count=_host_fail_count.get(h.ip, 0) + 1,
                    groups=getattr(h, "groups", "") or "",
                )
                err_entry.update({
                    "cores": "-", "ram": "-", "disk": "-",
                    "load": "-", "docker": "0",
                    "last_error": str(e)[:120],
                })
                host_data.append(err_entry)
                count = _host_fail_count.get(h.ip, 0) + 1
                _host_fail_count[h.ip] = count
                _host_last_error[h.ip] = {
                    "state": STATE_DEGRADED,
                    "reason": f"probe exception: {str(e)[:120]}",
                    "at": now_wall,
                }
                if count >= CIRCUIT_BREAKER_THRESHOLD and h.ip not in _host_backoff_until:
                    _host_backoff_until[h.ip] = now + CIRCUIT_BREAKER_BACKOFF
                    _host_backoff_started_at[h.ip] = now_wall
                    audit.record(
                        "circuit_breaker_engage",
                        h.ip,
                        "engaged",
                        label=h.label,
                        failure_count=count,
                        error_state=STATE_DEGRADED,
                        last_error=f"probe exception: {str(e)[:200]}",
                        backoff_seconds=CIRCUIT_BREAKER_BACKOFF,
                    )

    # Aggregate container counts per PVE node.
    # Chain: container_vms (vm_id→IP) + WATCHDOG (vm_id→node) + health (IP→docker count)
    node_containers = {}
    try:
        # Build IP→docker count from health data
        ip_docker = {h["ip"]: int(h.get("docker", 0)) for h in host_data if h.get("type") == "docker"}
        # Build vm_id→IP from container_vms config (resolved from hosts.toml)
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

    # aggregate a top-level probe_state so
    # Morty's silent-refresh banner does not have to re-derive fleet
    # health by inspecting every host entry with possibly-undefined
    # fields. Worst state wins (auth_failed > unreachable > degraded
    # > stale > recovering > live).
    probe_state, probe_reason = aggregate_probe_state(host_data)
    result = {
        "duration": round(time.monotonic() - start, 1),
        "hosts": host_data,
        "probed_at": time.time(),
        "node_containers": node_containers,
        "probe_state": probe_state,
        "probe_reason": probe_reason,
    }
    # Snapshot old health for SSE diff
    with _bg_lock:
        old_health = _bg_cache.get("health")
        _bg_cache["health"] = result
        _bg_cache_ts["health"] = time.time()
        _bg_cache_from_disk.discard("health")  # Fresh probe replaces stale disk data
    _save_disk_cache("health", result)

    # SSE: broadcast cache_update + per-host health_change events.
    # Use the new canonical `state` field when present, falling back to
    # legacy `status` so old cache shape still fires events during upgrade.
    _sse_broadcast("cache_update", {"key": "health", "ts": time.time()})
    if old_health and isinstance(old_health, dict):
        old_state = {
            h_e["label"]: h_e.get("state") or h_e.get("status")
            for h_e in old_health.get("hosts", [])
        }
        old_reason = {
            h_e["label"]: h_e.get("reason", "")
            for h_e in old_health.get("hosts", [])
        }
        for h_e in host_data:
            prev = old_state.get(h_e["label"])
            cur = h_e.get("state") or h_e.get("status")
            if prev and prev != cur:
                reason = h_e.get("reason", "")
                if _is_routine_legacy_health_change(
                    prev,
                    old_reason.get(h_e["label"], ""),
                    cur,
                    reason,
                    h_e.get("type", ""),
                ):
                    logger.info(
                        "health_change_suppressed",
                        host=h_e["label"],
                        old=prev,
                        new=cur,
                        reason=reason,
                    )
                    continue
                _sse_broadcast("health_change", {
                    "host": h_e["label"],
                    "old": prev,
                    "new": cur,
                    "reason": reason,
                })
                cur_state = h_e.get("state") or h_e.get("status")
                severity = (
                    "success"
                    if cur_state in (STATE_LIVE, STATE_RECOVERING)
                    else "warn"
                    if cur_state in (STATE_STALE, STATE_DEGRADED)
                    else "error"
                )
                _activity_add("health_change", f"{h_e['label']} is now {cur_state}", f"was {prev}", severity)

    # Evaluate alert rules against fresh health data
    _evaluate_alert_rules(cfg, result)

    # Log probe completion
    duration = round(time.monotonic() - start, 1)
    state_counts = {
        state: sum(1 for h in host_data if (h.get("state") or h.get("status")) == state)
        for state in (
            STATE_LIVE,
            STATE_RECOVERING,
            STATE_STALE,
            STATE_DEGRADED,
            STATE_AUTH_FAILED,
            STATE_UNREACHABLE,
        )
    }
    liveish_count = state_counts[STATE_LIVE] + state_counts[STATE_RECOVERING]
    logger.info(
        "health_probe_complete",
        duration=duration,
        total=len(host_data),
        live=state_counts[STATE_LIVE],
        recovering=state_counts[STATE_RECOVERING],
        stale=state_counts[STATE_STALE],
        degraded=state_counts[STATE_DEGRADED],
        auth_failed=state_counts[STATE_AUTH_FAILED],
        unreachable=state_counts[STATE_UNREACHABLE],
    )
    logger.perf("health_probe", duration, hosts_total=len(host_data), hosts_healthy=liveish_count)

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
        return  # Config load failure should not crash background probes
    fb = cfg.fleet_boundaries
    start = time.monotonic()

    vm_list = _get_fleet_vms(cfg)

    def _tcp_check(ip, ports, timeout=1.0):
        """Return True when any TCP port accepts a connection.

        Some infrastructure devices intentionally block ICMP while still
        serving their management plane. The fleet overview card must not
        render those as unreachable just because ping is disabled.
        """
        for port in ports:
            try:
                with socket.create_connection((ip, int(port)), timeout=timeout):
                    return True
            except OSError:
                continue
        return False

    def _icmp_check(ip):
        try:
            r = subprocess.run(
                ["ping", "-c", "1", "-W", "1", ip],
                capture_output=True,
                timeout=2,
            )
            return r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _physical_reachable(dev):
        dtype = (getattr(dev, "device_type", "") or "").lower()
        if dtype in {"pfsense", "opnsense"}:
            return _tcp_check(dev.ip, (443, 80, 22)) or _icmp_check(dev.ip)
        if dtype == "truenas":
            return _tcp_check(dev.ip, (443, 80)) or _icmp_check(dev.ip)
        if dtype in {"switch", "idrac", "ilo", "ipmi"}:
            return _tcp_check(dev.ip, (22,)) or _icmp_check(dev.ip)
        return _icmp_check(dev.ip)

    # Physical devices — device-appropriate reachability in parallel.
    physical = []

    def _ping_device(dev):
        reachable = _physical_reachable(dev)
        return {
            "key": dev.key,
            "ip": dev.ip,
            "label": dev.label,
            "type": dev.device_type,
            "tier": dev.tier,
            "detail": dev.detail,
            "groups": dev.groups,
            "scope": dev.scope,
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
                        "groups": dev.groups,
                        "scope": dev.scope,
                        "reachable": False,
                    }
                )

    # PVE nodes — use auto-discovered nodes, enrich with live stats + config detail
    discovered_nodes = _get_discovered_nodes()
    # Also keep fleet-boundaries detail strings for enrichment
    fb_detail = {n.name: n.detail for n in fb.pve_nodes.values()}

    pve_nodes = []
    _now_wall = time.time()
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
        # attach six-state + reason +
        # last_seen_ts per node. Shares the same _pve_last_seen_ts
        # dict the live-metrics endpoint maintains, so 'STALE 47s'
        # is consistent across /api/fleet/overview and /api/pve/metrics.
        last_seen = FreqHandler._pve_last_seen_ts.get(entry["ip"])
        if entry["online"]:
            FreqHandler._pve_last_seen_ts[entry["ip"]] = _now_wall
            entry["state"] = "live"
            entry["reason"] = "PVE API responded"
            entry["last_seen_ts"] = _now_wall
        else:
            age = round(_now_wall - last_seen, 1) if last_seen else None
            entry["state"] = "unreachable" if last_seen is None else "stale"
            entry["reason"] = (
                "PVE API did not respond — node never seen alive"
                if last_seen is None
                else f"PVE API did not respond; last seen {age}s ago"
            )
            entry["last_seen_ts"] = last_seen
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
    resource_count = len(vm_list)
    real_vm_count = len(non_template)
    total_vms = real_vm_count  # Backward-compatible alias: templates are not real VMs.
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
            cmd_parts.append(
                f"echo VMID:{vid}; "
                f"grep '^net' /etc/pve/qemu-server/{int(vid)}.conf 2>/dev/null || true"
            )
        batch_cmd = "; ".join(cmd_parts)
        r = ssh_single(
            host=nip,
            command=batch_cmd,
            key_path=cfg.ssh_key_path,
            command_timeout=20,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
            failure_log_level="warn",
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
    # aggregate top-level fleet_state so
    # the dashboard banner can stop guessing whether the fleet is OK
    # from an empty vms list + all-offline pve_nodes + undefined
    # probe_status. Worst PVE-node state wins for the overview.
    _pve_states = [n.get("state", "unreachable") for n in pve_nodes] or ["degraded"]
    if "unreachable" in _pve_states and all(s == "unreachable" for s in _pve_states):
        _fleet_state = "unreachable"
        _fleet_reason = "all PVE nodes unreachable"
    elif "unreachable" in _pve_states:
        n_bad = sum(1 for s in _pve_states if s == "unreachable")
        _fleet_state = "degraded"
        _fleet_reason = f"{n_bad}/{len(_pve_states)} PVE nodes unreachable"
    elif "stale" in _pve_states:
        n_stale = sum(1 for s in _pve_states if s == "stale")
        _fleet_state = "stale"
        _fleet_reason = f"{n_stale}/{len(_pve_states)} PVE nodes stale (not responding, prior evidence)"
    else:
        _fleet_state = "live"
        _fleet_reason = (
            f"all {len(_pve_states)} PVE nodes live; "
            f"{real_vm_count} real VMs + {template_count} templates tracked"
        )
    core_physical = [p for p in physical if p.get("scope", "core") != "lab"]
    lab_physical = [p for p in physical if p.get("scope", "core") == "lab"]

    result = {
        "vms": vm_list,
        "vm_nics": {str(k): v for k, v in vm_nics.items()},
        "physical": core_physical,
        "core_physical": core_physical,
        "lab_physical": lab_physical,
        "all_physical": physical,
        "pve_nodes": pve_nodes,
        "fleet_state": _fleet_state,
        "fleet_reason": _fleet_reason,
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
            "resource_count": resource_count,
            "real_vm_count": real_vm_count,
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
                cfg=cfg,
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
            # Build batch command: for each VMID, print "VMID:<id>" then grep tags.
            # Reading PVE's config file is much faster than repeated CLI config
            # calls and avoids timeout noise on nodes with many VMs.
            cmd_parts = []
            for vid in vmids:
                cmd_parts.append(
                    f"echo VMID:{vid}; "
                    f"grep '^tags' /etc/pve/qemu-server/{int(vid)}.conf 2>/dev/null || true"
                )
            batch_cmd = "; ".join(cmd_parts)
            r = ssh_single(
                host=nip,
                command=batch_cmd,
                key_path=cfg.ssh_key_path,
                command_timeout=30,
                htype="pve",
                use_sudo=True,
                cfg=cfg,
                failure_log_level="warn",
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
    """Auto-sync hosts.toml from PVE every hour.

    Keeps hosts.toml labels in sync with PVE VM names so the dashboard,
    SSH keys, and fleet data all use the same names. Users never need to
    run 'freq host sync' manually.
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


def _record_probe_error(cache_key, error):
    """Record a probe failure so API responses can report stale/error state."""
    with _bg_lock:
        prev = _bg_cache_errors.get(cache_key, {})
        _bg_cache_errors[cache_key] = {
            "error": str(error)[:200],
            "failed_at": time.time(),
            "consecutive": prev.get("consecutive", 0) + 1,
        }
    _sse_broadcast("probe_error", {
        "key": cache_key,
        "error": str(error)[:200],
        "consecutive": prev.get("consecutive", 0) + 1,
        "ts": time.time(),
    })


def _clear_probe_error(cache_key):
    """Clear probe error on successful run."""
    with _bg_lock:
        _bg_cache_errors.pop(cache_key, None)


def _bg_health_loop():
    """Fast health-only loop — runs every 15s for live dashboard bars."""
    while not _shutdown_flag.is_set():
        logger.debug("bg_loop_cycle", loop="health")
        try:
            _bg_probe_health()
            _clear_probe_error("health")
        except Exception as e:
            logger.error(f"bg health probe failed: {e}")
            _record_probe_error("health", e)
        _shutdown_flag.wait(BG_CACHE_REFRESH_INTERVAL)


# Cache key mapping for slow loop probes
_SLOW_PROBE_CACHE_KEYS = {
    "node discovery": "pve_nodes",
    "tag fetch": "vm_tags",
    "infra probe": "infra_quick",
    "fleet overview": "fleet_overview",
    "update check": "update",
    "hosts sync": "hosts_sync",
}


def _bg_slow_loop():
    """Slower loop for fleet overview, infra, tags, updates — runs every 60s."""
    while not _shutdown_flag.is_set():
        logger.debug("bg_loop_cycle", loop="slow")
        for fn, label in [
            (_bg_discover_pve_nodes, "node discovery"),
            (_bg_fetch_vm_tags, "tag fetch"),
            (_bg_probe_infra, "infra probe"),
            (_bg_probe_fleet_overview, "fleet overview"),
            (_bg_check_update, "update check"),
            (_bg_sync_hosts, "hosts sync"),
        ]:
            if _shutdown_flag.is_set():
                break
            try:
                fn()
                cache_key = _SLOW_PROBE_CACHE_KEYS.get(label)
                if cache_key:
                    _clear_probe_error(cache_key)
            except Exception as e:
                logger.error(f"bg {label} failed: {e}")
                cache_key = _SLOW_PROBE_CACHE_KEYS.get(label)
                if cache_key:
                    _record_probe_error(cache_key, e)
        _shutdown_flag.wait(60)


def _bg_initial_probe():
    """Run critical probes immediately on startup so first page load has data."""
    for fn, label in [
        (_bg_discover_pve_nodes, "node discovery"),
        (_bg_probe_fleet_overview, "fleet overview"),
        (_bg_fetch_vm_tags, "tag fetch"),
    ]:
        try:
            fn()
            cache_key = _SLOW_PROBE_CACHE_KEYS.get(label)
            if cache_key:
                _clear_probe_error(cache_key)
        except Exception as e:
            logger.error(f"bg initial {label} failed: {e}")
            cache_key = _SLOW_PROBE_CACHE_KEYS.get(label)
            if cache_key:
                _record_probe_error(cache_key, e)


def start_background_cache():
    """Load disk cache, then start background refresh threads."""
    _install_runtime_exception_hooks()
    _init_cache_dir()
    _load_disk_cache()
    # Kick off critical probes immediately so first page load has data
    t0 = threading.Thread(target=_bg_initial_probe, daemon=True, name="freq-init-probe")
    t1 = threading.Thread(target=_bg_health_loop, daemon=True, name="freq-health")
    t2 = threading.Thread(target=_bg_slow_loop, daemon=True, name="freq-slow")
    t0.start()
    t1.start()
    t2.start()


_RUNTIME_EXCEPTION_HOOKS_INSTALLED = False


def _install_runtime_exception_hooks():
    """Log uncaught process/thread exceptions as structured runtime events."""
    global _RUNTIME_EXCEPTION_HOOKS_INSTALLED
    if _RUNTIME_EXCEPTION_HOOKS_INSTALLED:
        return
    _RUNTIME_EXCEPTION_HOOKS_INSTALLED = True

    import sys
    import traceback as _traceback

    previous_excepthook = sys.excepthook
    previous_thread_hook = getattr(threading, "excepthook", None)

    def _excepthook(exc_type, exc, tb):
        logger.error(
            "runtime_uncaught_exception",
            error=repr(exc),
            exception_type=getattr(exc_type, "__name__", str(exc_type)),
            traceback="".join(_traceback.format_exception(exc_type, exc, tb)),
        )
        previous_excepthook(exc_type, exc, tb)

    def _thread_excepthook(args):
        logger.error(
            "runtime_thread_exception",
            thread=getattr(args.thread, "name", ""),
            error=repr(args.exc_value),
            exception_type=getattr(args.exc_type, "__name__", str(args.exc_type)),
            traceback="".join(_traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )
        if previous_thread_hook:
            previous_thread_hook(args)

    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook


def _cleanup_ssh_mux(cfg):
    """Kill SSH ControlMaster mux sockets on shutdown.

    Background probes use SSH with ControlMaster=auto and ControlPersist=300.
    These mux master processes outlive the daemon threads and prevent
    systemd from cleanly stopping the service (they're children of the
    main process). Closing them ensures clean shutdown.

    R-RESILIENCE-INIT-RECOVERY-20260413S: previously this ran `ssh -O exit`
    serially per socket (~3s each) which meant a 20-host fleet took up to
    60s to cool down — combined with mid-probe SSH calls still in flight
    this reliably breached systemd's default TimeoutStopSec=90s and forced
    SIGKILL. Parallelize via ThreadPoolExecutor, cap at a hard 8s total
    wall-clock budget, and spawn every child with start_new_session=True so
    if `ssh -O exit` itself hangs we pgid-kill the tree instead of leaking.
    """
    import glob
    svc_name = cfg.ssh_service_account
    mux_dir = os.path.expanduser(f"~{svc_name}/.ssh/freq-mux")
    if not os.path.isdir(mux_dir):
        return
    mux_sockets = glob.glob(os.path.join(mux_dir, "*"))
    if not mux_sockets:
        return

    def _exit_one(sock):
        try:
            proc = subprocess.Popen(
                ["ssh", "-O", "exit", "-o", f"ControlPath={sock}", "dummy"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    import signal as _signal
                    os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    proc.communicate(timeout=1)
                except Exception:
                    pass
        except Exception:
            pass  # Best effort — systemd SIGKILL handles stragglers

    import concurrent.futures
    budget = 8
    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(mux_sockets))) as pool:
            futures = [pool.submit(_exit_one, sock) for sock in mux_sockets]
            for f in concurrent.futures.as_completed(futures, timeout=budget):
                try:
                    f.result(timeout=0.1)
                except Exception:
                    pass
    except concurrent.futures.TimeoutError:
        logger.warning(
            f"ssh_mux cleanup exceeded {budget}s budget — leaving stragglers to systemd",
            elapsed=round(time.monotonic() - started, 1),
            sockets=len(mux_sockets),
        )


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
    """Write container registry back to containers.toml.

    Preserves the canonical format based on key type:
    - String keys → [host.<label>] format (init-generated)
    - Int keys → [vm.<id>] format (legacy/dashboard-created)
    """
    lines = ["# FREQ Container Registry\n"]

    def _write_container_fields(c):
        if c.name:
            lines.append(f'name = "{c.name}"')
        if getattr(c, "image", ""):
            lines.append(f'image = "{c.image}"')
        if getattr(c, "status", ""):
            lines.append(f'status = "{c.status}"')
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

    for key in sorted(container_vms.keys(), key=str):
        vm = container_vms[key]
        if isinstance(key, str):
            # Host-format (init-generated): [host.<label>]
            lines.append(f"\n[host.{key}]")
            if vm.ip:
                lines.append(f'ip = "{vm.ip}"')
            if vm.label and vm.label != key:
                lines.append(f'label = "{vm.label}"')
            if vm.compose_path:
                lines.append(f'compose_path = "{vm.compose_path}"')
            for cname, c in sorted(vm.containers.items()):
                lines.append(f"\n[host.{key}.containers.{cname}]")
                _write_container_fields(c)
        else:
            # Legacy format: [vm.<id>]
            lines.append(f"\n[vm.{key}]")
            if vm.ip:
                lines.append(f'ip = "{vm.ip}"')
            if vm.label:
                lines.append(f'label = "{vm.label}"')
            if vm.compose_path:
                lines.append(f'compose_path = "{vm.compose_path}"')
            for cname, c in sorted(vm.containers.items()):
                lines.append(f"\n[vm.{key}.containers.{cname}]")
                _write_container_fields(c)

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
    verify_password as _verify_password,
    check_session_role as _check_session_role,
    _request_has_query_token,
    handle_auth_login,
    handle_auth_logout,
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
            cfg=cfg,
        )
        if r.returncode == 0:
            return ip
    return None


def _parse_query(handler):
    """Parse query parameters from the request path. Returns dict of lists."""
    return parse_qs(urlparse(handler.path).query)


def _resolve_container_vm_ip(vm) -> str:
    """Resolve container VM IP from hosts.toml by label, falling back to hardcoded IP.

    This eliminates hardcoded IPs in containers.toml — if the VM gets re-IPed,
    the hourly hosts.toml sync picks up the new IP, and container probes
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


def _container_vm_host(cfg, target: str):
    """Resolve a Docker host target from host label/IP or container VM label."""
    from freq.core.resolve import by_target
    from freq.core.types import Host

    h = by_target(cfg.hosts, target)
    if h:
        return h
    target_l = str(target or "").strip().lower()
    for vm in cfg.container_vms.values():
        vmid = int(getattr(vm, "vm_id", 0) or 0)
        candidates = {
            str(getattr(vm, "label", "") or "").lower(),
            str(getattr(vm, "ip", "") or "").lower(),
        }
        if vmid:
            candidates.update({str(vmid), f"vm:{vmid}"})
        if target_l in candidates:
            return Host(
                ip=_resolve_container_vm_ip(vm),
                label=vm.label,
                htype="docker",
                groups="docker",
                vmid=vmid,
            )
    return None


_MEDIA_DEFAULT_PORTS = {
    "tautulli": 8181,
    "sabnzbd": 8080,
    "qbittorrent": 8080,
    "qbit": 8080,
    "plex": 32400,
}


def _media_default_port(name: str) -> int:
    lname = (name or "").lower()
    for key, port in _MEDIA_DEFAULT_PORTS.items():
        if key in lname:
            return port
    return 0


def _media_container_port(container) -> int:
    return int(getattr(container, "port", 0) or _media_default_port(getattr(container, "name", "")) or 0)


def _media_ssh_user_from_key(cfg) -> str:
    key_path = getattr(cfg, "ssh_key_path", "") or ""
    parts = key_path.split(os.sep)
    if len(parts) >= 3 and parts[-2] == ".ssh" and parts[-3]:
        return parts[-3]
    return ""


def _media_ssh_single(cfg, vm, command: str, timeout: int = 10):
    def _run(**overrides):
        merged = dict(kwargs)
        merged.update(overrides)
        return ssh_single(**merged)

    kwargs = {
        "host": _resolve_container_vm_ip(vm),
        "command": command,
        "key_path": cfg.ssh_key_path,
        "connect_timeout": 3,
        "command_timeout": timeout,
        "htype": "docker",
        "use_sudo": False,
        "cfg": cfg,
    }
    r = _run()
    if r.returncode == 255 and "Permission denied" in (r.stderr or ""):
        key_user = _media_ssh_user_from_key(cfg)
        if key_user and key_user != getattr(cfg, "ssh_service_account", ""):
            r = _run(user=key_user)
    if r.returncode != 0 and "docker.sock" in (r.stderr or "") and "permission denied" in (r.stderr or "").lower():
        retry = {"use_sudo": True}
        key_user = _media_ssh_user_from_key(cfg)
        if key_user and key_user != getattr(cfg, "ssh_service_account", ""):
            retry["user"] = key_user
        r = _run(**retry)
    return r


def _docker_exec_json(cfg, vm, container_name: str, script: str, timeout: int = 10):
    r = _media_ssh_single(
        cfg,
        vm,
        f"docker exec {shlex.quote(container_name)} sh -lc {shlex.quote(script)}",
        timeout=timeout,
    )
    if r.returncode != 0:
        return None, r
    try:
        return json.loads(r.stdout), r
    except (json.JSONDecodeError, TypeError):
        return None, r


def _parse_sab_downloads(data, vm_label: str) -> list:
    downloads = []
    queue = data.get("queue", {}) if isinstance(data, dict) else {}
    speed_str = str(queue.get("speed", "0"))
    speed_val = float(speed_str.replace(" M", "").replace(" K", "").replace(" G", "") or 0)
    if "M" in speed_str:
        speed_val *= 1048576
    elif "K" in speed_str:
        speed_val *= 1024
    elif "G" in speed_str:
        speed_val *= 1073741824
    for s in queue.get("slots", []):
        pct = int(float(s.get("percentage", 0)))
        size_mb = float(s.get("mb", 0)) * 1048576
        downloads.append(
            {
                "name": s.get("filename", "?"),
                "size": int(size_mb),
                "progress": pct,
                "speed": int(speed_val),
                "client": "SABnzbd",
                "vm": vm_label,
            }
        )
    return downloads


def _parse_qbit_downloads(data, vm_label: str) -> list:
    downloads = []
    if not isinstance(data, list):
        return downloads
    for t in data:
        downloads.append(
            {
                "name": t.get("name", "?"),
                "size": t.get("size", 0),
                "progress": round(t.get("progress", 0) * 100),
                "speed": t.get("dlspeed", 0),
                "client": "qBittorrent",
                "vm": vm_label,
            }
        )
    return downloads


_INLINE_STYLE_CSP_HASHES: list[str] = []
_INLINE_STYLE_CSP_LOCK = threading.Lock()


def _inline_style_csp_hashes() -> list[str]:
    """Return the cached list of CSP `'sha256-…'` tokens for every
    bespoke inline style="…" attribute that ships in app.html.

    The cache is built lazily on first call and reused for the lifetime
    of the process. App.html is loaded via web_ui._read_asset so the
    same template the server actually serves is the one we hash. The
    SHA256 is computed over the raw attribute value (the bytes between
    the quotes, no surrounding `style="…"` wrapper) — that's what the
    CSP spec matches against under `'unsafe-hashes'`.

    R-WEB-INLINE-STYLE-CSP-SWEEP-20260413Q hybrid finish per Finn's
    design call: token Q's utility-class sweep extracted the high-
    frequency patterns (264 → N), and the remaining N bespoke styles
    are allowed via per-style hash instead of a blanket
    `'unsafe-inline'`. The hashes are computed once at first request,
    not per-request — the inline-style set is fixed in the static
    asset bundle and only changes when the dashboard is re-deployed.
    """
    global _INLINE_STYLE_CSP_HASHES
    with _INLINE_STYLE_CSP_LOCK:
        if _INLINE_STYLE_CSP_HASHES:
            return _INLINE_STYLE_CSP_HASHES
        try:
            from freq.modules.web_ui import _read_asset
            html = _read_asset("app.html")
        except Exception as e:
            logger.error(f"inline_style_csp_hashes: failed to read app.html: {e}")
            return []
        import hashlib
        import base64
        seen: set[str] = set()
        tokens: list[str] = []
        # Match every style="…" attribute. Use a non-greedy capture
        # bounded by the next " — same regex shape as the test suite
        # uses for counting.
        for m in re.finditer(r' style="([^"]*)"', html):
            value = m.group(1)
            if value in seen:
                continue
            seen.add(value)
            digest = hashlib.sha256(value.encode("utf-8")).digest()
            b64 = base64.b64encode(digest).decode("ascii")
            tokens.append(f"'sha256-{b64}'")
        _INLINE_STYLE_CSP_HASHES = tokens
        logger.info(
            f"inline_style_csp_hashes: cached {len(tokens)} unique inline style hashes for CSP"
        )
        return _INLINE_STYLE_CSP_HASHES


_DNS_LOOKUP_LOG: dict = {}  # {ip: [(ts), ...]}
_DNS_LOOKUP_LOCK = threading.Lock()
_DNS_LOOKUP_WINDOW = 300   # 5 minutes
_DNS_LOOKUP_MAX = 30       # per window per source IP


def _dns_lookup_rate_limit(client_ip: str) -> bool:
    """Return True if a DNS lookup from client_ip is allowed.

    F17 of R-SECURITY-TRUST-AUDIT-20260413P. Caps the per-source
    DNS lookup volume so an authenticated viewer can't use the
    dashboard's resolver as a covert exfiltration channel
    (encoding payload bytes as subdomains of an attacker-controlled
    nameserver). 30 lookups per 5 minutes is enough for legitimate
    operator use of the DNS lookup tile while making any meaningful
    exfil throughput impractical.
    """
    now = time.time()
    with _DNS_LOOKUP_LOCK:
        bucket = _DNS_LOOKUP_LOG.get(client_ip, [])
        bucket = [t for t in bucket if now - t < _DNS_LOOKUP_WINDOW]
        if len(bucket) >= _DNS_LOOKUP_MAX:
            _DNS_LOOKUP_LOG[client_ip] = bucket
            return False
        bucket.append(now)
        _DNS_LOOKUP_LOG[client_ip] = bucket
        return True


def _is_first_run():
    """Detect if this is the first run or if setup is incomplete.

    Returns True if no users exist — even if init markers are present.
    An init without dashboard users is incomplete: the operator cannot
    log in and would be stranded between "setup complete" and
    "invalid credentials". The setup wizard must remain available
    until at least one user exists.

    F9 of R-SECURITY-TRUST-AUDIT-20260413P: this function now fails
    CLOSED on exception. Pre-fix it returned True if _load_users
    raised, on the reasoning "safer to show setup wizard". That was
    wrong — fail-open meant a transient users.conf permission/IO
    error reopened the entire setup wizard surface to unauth callers,
    which combined with F2 (test-ssh SSRF) gave a real attack window.
    Fail-closed on read error is the safer posture: the setup wizard
    stays gated, the operator sees the failure via /api/setup/status
    or freq.log, and unsticks the wizard explicitly via
    /api/setup/reset (admin auth) once the underlying read is fixed.
    """
    cfg = load_config()

    # Users are the ultimate gate — no users means setup is incomplete
    # regardless of markers. This prevents the post-init dead-end where
    # .initialized exists but users.conf is empty.
    try:
        users = _load_users(cfg)
        if not users:
            return True
    except Exception as e:
        logger.error(
            f"_is_first_run: failed to check users — failing CLOSED to keep "
            f"setup endpoints gated: {e}"
        )
        return False  # Fail closed (F9): never re-open the wizard on a read error

    # If users exist, check markers to determine if setup completed
    if os.path.isfile(os.path.join(cfg.data_dir, "setup-complete")):
        return False
    if os.path.isfile(os.path.join(cfg.conf_dir, ".initialized")):
        return False
    if os.path.isfile(os.path.join(cfg.conf_dir, ".web-setup-complete")):
        return False

    # Users exist but no markers — treat as configured (user added manually)
    return False


def _setup_marker_exists(cfg):
    """True when setup or init has already crossed a completion boundary."""
    return any(
        os.path.isfile(path)
        for path in (
            os.path.join(cfg.data_dir, "setup-complete"),
            os.path.join(cfg.conf_dir, ".initialized"),
            os.path.join(cfg.conf_dir, ".web-setup-complete"),
        )
    )


def _allow_setup_admin_window(handler):
    """Allow setup continuation after first admin creation, before markers.

    The first setup call creates users.conf, which intentionally makes
    _is_first_run() false. Continuing setup after that point must be
    authenticated as the freshly-created admin, and only while no setup/init
    marker exists.
    """
    cfg = load_config()
    if _setup_marker_exists(cfg):
        handler._json_response({"error": "Setup wizard already used — run freq init to complete fleet deployment"}, 403)
        return False
    role, err = _check_session_role(handler, "admin")
    if err:
        handler._json_response({"error": err}, 403)
        return False
    return True


def _setup_init_snapshot():
    with _setup_init_lock:
        if not _setup_init_job:
            return {"running": False, "job": None}
        job = dict(_setup_init_job)
        job["lines"] = list(_setup_init_job.get("lines", []))[-300:]
        return {"running": job.get("state") == "running", "job": job}


def _setup_secret_dir(cfg, job_id):
    path = os.path.join(cfg.data_dir, "secrets", "setup-init", job_id)
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _write_setup_secret(secret_dir, name, value):
    if not value:
        return ""
    path = os.path.join(secret_dir, name)
    with open(path, "w") as f:
        f.write(str(value))
        if not str(value).endswith("\n"):
            f.write("\n")
    os.chmod(path, 0o600)
    return path


def _setup_existing_secret_file(value, label):
    path = os.path.expanduser(str(value or "").strip())
    if not path:
        return ""
    def _sudo_file_exists(candidate):
        try:
            return subprocess.run(
                ["sudo", "-n", "test", "-f", candidate],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    if not os.path.isfile(path):
        prefix = "/root/freq-init-inputs/"
        if path.startswith(prefix):
            alias = os.path.join("/freq-init-inputs", path[len(prefix):])
            if os.path.isfile(alias) or _sudo_file_exists(alias):
                path = alias
    if not os.path.isfile(path) and not _sudo_file_exists(path):
        raise ValueError(f"{label} file not found: {path}")
    return path


def _read_setup_secret_file(value, label):
    path = _setup_existing_secret_file(value, label)
    if not path:
        return ""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except PermissionError:
        result = subprocess.run(
            ["sudo", "-n", "cat", path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise PermissionError(f"{label} file is not readable: {path}")
        return result.stdout.strip()


def _toml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_scalar(v) for v in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_setup_device_credentials(secret_dir, device_credentials):
    if not isinstance(device_credentials, dict) or not device_credentials:
        return ""
    lines = []
    type_sections = {
        "pfsense": "pfsense",
        "truenas": "truenas",
        "switch": "switch",
        "bmc": "idrac",
        "idrac": "idrac",
    }
    for section, raw in device_credentials.items():
        if not isinstance(raw, dict):
            continue
        row_type = str(raw.get("type") or "").strip().lower()
        section_name = type_sections.get(row_type) or str(section).strip()
        safe_section = re.sub(r"[^A-Za-z0-9_.:-]", "", section_name)
        if not safe_section:
            continue
        lines.append(f"[{safe_section}]")
        normalized = dict(raw)
        if normalized.get("username") and not normalized.get("user"):
            normalized["user"] = normalized.get("username")
        if normalized.get("secret") and not normalized.get("password"):
            normalized["password"] = normalized.get("secret")
        if normalized.get("target"):
            target = str(normalized.get("target") or "").strip()
            if target:
                if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target) and not normalized.get("host"):
                    normalized["host"] = target
                elif not normalized.get("label"):
                    normalized["label"] = target
        for key, value in normalized.items():
            if value in (None, ""):
                continue
            if key == "password":
                pw_path = _write_setup_secret(secret_dir, f"{safe_section}-password", value)
                lines.append(f"password_file = {_toml_scalar(pw_path)}")
            elif key == "api_key":
                api_path = _write_setup_secret(secret_dir, f"{safe_section}-api-key", value)
                lines.append(f"api_key_file = {_toml_scalar(api_path)}")
            elif key in {
                "user",
                "host",
                "hosts",
                "label",
                "url",
                "ssh_key_file",
                "api_key_file",
                "password_file",
                "scope",
                "api_key_only",
                "sudo_password_file",
            }:
                lines.append(f"{key} = {_toml_scalar(value)}")
        lines.append("")
    if not lines:
        return ""
    path = os.path.join(secret_dir, "device-credentials.toml")
    with open(path, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    os.chmod(path, 0o600)
    return path


def _list_value(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in re.split(r"[,\s]+", str(value or "")) if v.strip()]


def _setup_init_command(cfg, body, job_id):
    secret_dir = _setup_secret_dir(cfg, job_id)
    service_password = str(body.get("service_account_password") or body.get("password") or "").strip()
    dashboard_password = str(body.get("dashboard_password") or "").strip()
    bootstrap_password = str(body.get("bootstrap_password") or "").strip()
    pdm_password = str(body.get("pdm_password") or "").strip()
    service_password_file = _setup_existing_secret_file(
        body.get("service_account_password_file") or body.get("password_file"),
        "service_account_password",
    )
    dashboard_password_file = _setup_existing_secret_file(body.get("dashboard_password_file"), "dashboard_password")
    bootstrap_password_file = _setup_existing_secret_file(body.get("bootstrap_password_file"), "bootstrap_password")
    bootstrap_key_path = _setup_existing_secret_file(
        body.get("bootstrap_key_path") or body.get("bootstrap_key_file"),
        "bootstrap_key",
    )
    vm_contract_file = _setup_existing_secret_file(body.get("vm_contract"), "vm_contract")
    device_credentials_file = _setup_existing_secret_file(
        body.get("device_credentials_file"),
        "device_credentials",
    )
    if not service_password_file:
        if len(service_password) < 8:
            raise ValueError("service_account_password is required and must be at least 8 characters")
        service_password_file = _write_setup_secret(secret_dir, "service-account-password", service_password)
    if body.get("dashboard_user") and not dashboard_password_file:
        if len(dashboard_password) < 8:
            raise ValueError("dashboard_password is required when dashboard_user is set")
        dashboard_password_file = _write_setup_secret(secret_dir, "dashboard-password", dashboard_password)
    if bootstrap_password and not bootstrap_password_file:
        bootstrap_password_file = _write_setup_secret(secret_dir, "bootstrap-password", bootstrap_password)
    pdm_password_file = _write_setup_secret(secret_dir, "pdm-password", pdm_password)
    if not device_credentials_file:
        device_credentials_file = _write_setup_device_credentials(secret_dir, body.get("device_credentials") or {})

    code = "import sys; from freq.cli import main; raise SystemExit(main(sys.argv[1:]))"
    cmd = [sys.executable, "-c", code, "--yes", "init", "--headless", "--password-file", service_password_file]
    if body.get("bootstrap_user"):
        cmd.extend(["--bootstrap-user", str(body.get("bootstrap_user")).strip()])
    if bootstrap_password_file:
        cmd.extend(["--bootstrap-password-file", bootstrap_password_file])
    elif bootstrap_key_path:
        cmd.extend(["--bootstrap-key", bootstrap_key_path])
    elif body.get("bootstrap_key"):
        cmd.extend(["--bootstrap-key", os.path.expanduser(str(body.get("bootstrap_key")).strip())])
    if body.get("service_account"):
        cmd.extend(["--service-account", str(body.get("service_account")).strip()])
    if body.get("dashboard_user"):
        cmd.extend(["--dashboard-user", str(body.get("dashboard_user")).strip()])
    if dashboard_password_file:
        cmd.extend(["--dashboard-password-file", dashboard_password_file])
    pve_nodes = _list_value(body.get("pve_nodes")) or list(getattr(cfg, "pve_nodes", []) or [])
    if pve_nodes:
        cmd.extend(["--pve-nodes", ",".join(pve_nodes)])
    pve_names = _list_value(body.get("pve_node_names")) or list(getattr(cfg, "pve_node_names", []) or [])
    if pve_names:
        cmd.extend(["--pve-node-names", ",".join(pve_names)])
    for field, flag in (
        ("gateway", "--gateway"),
        ("nameserver", "--nameserver"),
        ("cluster_name", "--cluster-name"),
        ("ssh_mode", "--ssh-mode"),
        ("hosts_file", "--hosts-file"),
        ("owned_vmids", "--owned-vmids"),
        ("template_vmids", "--template-vmids"),
        ("acknowledged_out_of_contract_vmids", "--acknowledged-out-of-contract-vmids"),
        ("core_devices", "--core-devices"),
        ("lab_devices", "--lab-devices"),
        ("pdm_remote_name", "--pdm-remote-name"),
    ):
        if body.get(field):
            cmd.extend([flag, str(body.get(field)).strip()])
    if vm_contract_file:
        cmd.extend(["--vm-contract", vm_contract_file])
    if device_credentials_file:
        cmd.extend(["--device-credentials", device_credentials_file])
    if body.get("install_pdm"):
        cmd.append("--install-pdm")
    if body.get("skip_pdm"):
        cmd.append("--skip-pdm")
    if pdm_password_file:
        cmd.extend(["--pdm-pass", pdm_password_file])

    env = os.environ.copy()
    env["FREQ_DIR"] = cfg.install_dir
    env["FREQ_WEB_INIT"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", "env", f"FREQ_DIR={cfg.install_dir}", "FREQ_WEB_INIT=1", "PYTHONUNBUFFERED=1"] + cmd
    return cmd, env, secret_dir


def _redact_setup_init_line(line, secret_dir):
    text = str(line or "").rstrip()
    if secret_dir:
        text = text.replace(secret_dir, "[setup-secret-dir]")
    return text


def _schedule_setup_runtime_handoff(cfg):
    """Move Web Init from the bootstrap listener to the managed service.

    Web-launched init runs inside a temporary setup listener so the browser can
    stream progress before the managed service account exists. Once init has
    created freq-serve.service, that bootstrap process must get out of the way
    or it will keep old config cached and compete with the real dashboard.
    """
    try:
        has_service = subprocess.run(
            ["systemctl", "cat", "freq-serve.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        has_service = False
    if not has_service:
        return False

    current_pid = os.getpid()
    current_user = ""
    try:
        import pwd

        current_user = pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        current_user = ""
    if current_user and current_user == getattr(cfg, "ssh_service_account", ""):
        return False

    prefix = []
    if os.geteuid() != 0:
        prefix = ["sudo", "-n"]
    script = (
        " ".join(shlex.quote(part) for part in prefix + ["systemctl", "stop", "pve-freq-setup.service"])
        + " >/dev/null 2>&1 || true; "
        + f"kill -TERM {current_pid} >/dev/null 2>&1 || true; "
        + "sleep 2; "
        + " ".join(shlex.quote(part) for part in prefix + ["systemctl", "restart", "freq-serve.service"])
        + " >/dev/null 2>&1 || "
        + " ".join(shlex.quote(part) for part in prefix + ["systemctl", "start", "freq-serve.service"])
        + " >/dev/null 2>&1 || true"
    )
    run_cmd = prefix + [
        "systemd-run",
        "--quiet",
        "--collect",
        "--unit=pve-freq-web-init-handoff",
        "--on-active=5",
        "/bin/sh",
        "-c",
        script,
    ]
    try:
        scheduled = subprocess.run(
            run_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).returncode == 0
        if scheduled:
            logger.info("setup_runtime_handoff_scheduled", pid=current_pid, method="systemd-run")
            return True
    except (OSError, subprocess.SubprocessError):
        pass

    fallback_script = (
        "sleep 5; "
        + f"kill -TERM {current_pid} >/dev/null 2>&1 || true; "
        + "sleep 2; "
        + " ".join(shlex.quote(part) for part in prefix + ["systemctl", "restart", "freq-serve.service"])
        + " >/dev/null 2>&1 || "
        + " ".join(shlex.quote(part) for part in prefix + ["systemctl", "start", "freq-serve.service"])
        + " >/dev/null 2>&1 || true"
    )
    try:
        subprocess.Popen(
            ["/bin/sh", "-c", fallback_script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("setup_runtime_handoff_scheduled", pid=current_pid, method="detached-shell")
        return True
    except OSError as e:
        logger.warn(f"setup runtime handoff scheduling failed: {e}")
        return False


def _run_setup_init_job(job_id, cmd, env, secret_dir):
    proc = None
    handoff_cfg = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=env.get("FREQ_DIR") or None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        with _setup_init_lock:
            if _setup_init_job and _setup_init_job.get("id") == job_id:
                _setup_init_job["pid"] = proc.pid
        for line in proc.stdout or []:
            with _setup_init_lock:
                if _setup_init_job and _setup_init_job.get("id") == job_id:
                    _setup_init_job.setdefault("lines", []).append(_redact_setup_init_line(line, secret_dir))
                    _setup_init_job["updated_at"] = time.time()
                    _setup_init_job["lines"] = _setup_init_job["lines"][-1000:]
        rc = proc.wait()
        cfg = load_config(force=True)
        handoff_cfg = cfg
        initialized = os.path.isfile(os.path.join(cfg.conf_dir, ".initialized"))
        with _setup_init_lock:
            if _setup_init_job and _setup_init_job.get("id") == job_id:
                _setup_init_job["state"] = "succeeded" if rc == 0 and initialized else "failed"
                _setup_init_job["returncode"] = rc
                _setup_init_job["initialized"] = initialized
                _setup_init_job["finished_at"] = time.time()
                _setup_init_job["updated_at"] = time.time()
    except Exception as exc:
        with _setup_init_lock:
            if _setup_init_job and _setup_init_job.get("id") == job_id:
                _setup_init_job["state"] = "failed"
                _setup_init_job["error"] = str(exc)
                _setup_init_job["finished_at"] = time.time()
                _setup_init_job["updated_at"] = time.time()
    finally:
        if env.get("FREQ_WEB_INIT") == "1" and handoff_cfg is not None:
            if _schedule_setup_runtime_handoff(handoff_cfg):
                with _setup_init_lock:
                    if _setup_init_job and _setup_init_job.get("id") == job_id:
                        _setup_init_job.setdefault("lines", []).append(
                            "scheduled dashboard handoff to freq-serve.service"
                        )
                        _setup_init_job["updated_at"] = time.time()
        try:
            shutil.rmtree(secret_dir)
        except Exception:
            pass


def _init_blocker_from_artifacts(cfg):
    """Return a truthful not-initialized reason from generated init artifacts."""
    status_path = os.path.join(cfg.conf_dir, "init-status.json")
    try:
        with open(status_path) as f:
            status = json.load(f)
    except (OSError, ValueError, TypeError):
        status = {}
    if isinstance(status, dict) and status:
        if status.get("initialized") is True:
            return ""
        unexpected = []
        for vmid in status.get("unexpected_out_of_contract_vmids", []) or []:
            try:
                unexpected.append(int(vmid))
            except (TypeError, ValueError):
                continue
        if unexpected:
            formatted = ", ".join(str(vmid) for vmid in sorted(set(unexpected)))
            return (
                f"freq init ran and is blocked by operator VM contract: "
                f"{len(set(unexpected))} unexpected out-of-contract PVE VM(s) discovered ({formatted})"
            )
        failed_checks = [
            str(item).strip()
            for item in status.get("failed_checks", []) or []
            if str(item).strip()
        ]
        if failed_checks:
            return f"freq init ran and failed verification: {failed_checks[0]}"
        reason = str(status.get("reason") or "").strip()
        if reason:
            return f"freq init ran and failed verification: {reason}"

    fb_path = os.path.join(cfg.conf_dir, "fleet-boundaries.toml")
    inv_path = os.path.join(cfg.conf_dir, "pve-inventory.toml")
    fb_data = load_toml(fb_path)
    inv_data = load_toml(inv_path)
    if not fb_data and not inv_data:
        return ""

    categories = fb_data.get("categories", {}) if isinstance(fb_data, dict) else {}
    out_cat = categories.get("out_of_contract", {}) if isinstance(categories, dict) else {}
    out_vmids = []
    if isinstance(out_cat, dict):
        for vmid in out_cat.get("vmids", []) or []:
            try:
                out_vmids.append(int(vmid))
            except (TypeError, ValueError):
                continue
    if inv_data:
        return "freq init ran but did not mark initialized; run freq init --check for the failing check"
    return ""


def _get_fleet_vms(cfg):
    """Fetch VM list from PVE cluster, enriched with fleet boundary data.

    Shared by _serve_vms and _serve_fleet_overview to avoid duplication.
    Tries PVE REST API first, falls back to SSH.
    Returns list of VM dicts.
    """
    fb = cfg.fleet_boundaries
    dashboard_scope = _dashboard_vm_scope(cfg)
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
                    template_flag = v.get("template", 0)
                    is_template = bool(template_flag) or 9000 <= int(vmid or 0) < 10000
                    if not is_template and not _dashboard_vm_visible(v, dashboard_scope):
                        continue
                    if is_template:
                        cat_name, tier = "templates", "protected"
                    else:
                        cat_name, tier = fb.categorize(vmid)
                    tags = get_vm_tags(vmid)
                    vm_name = str(v.get("name", "") or "").strip()
                    if not vm_name and vmid and v.get("node"):
                        cfg_result, cfg_ok = _pve_call(
                            cfg,
                            node_ip,
                            api_endpoint=f"/nodes/{v.get('node')}/qemu/{vmid}/config",
                            ssh_command=(
                                f"pvesh get /nodes/{v.get('node')}/qemu/{vmid}/config "
                                "--output-format json"
                            ),
                            timeout=10,
                        )
                        if cfg_ok and cfg_result:
                            try:
                                vm_config = cfg_result if isinstance(cfg_result, dict) else json.loads(cfg_result)
                                vm_name = str(vm_config.get("name", "") or "").strip()
                            except (json.JSONDecodeError, TypeError, AttributeError):
                                vm_name = ""
                    if not vm_name:
                        vm_name = f"vm-{vmid}"
                    # cpu field: real utilization (0.0-1.0), maxcpu: allocated cores
                    # mem field: real used bytes, maxmem: allocated bytes
                    cpu_real = v.get("cpu", 0)
                    cpu_pct = round(cpu_real * 100, 1) if isinstance(cpu_real, (int, float)) else 0
                    mem_used = v.get("mem", 0) or 0
                    mem_max = v.get("maxmem", 0) or 0
                    vm_list.append(
                        {
                            "vmid": vmid,
                            "name": vm_name,
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


def _label_key(value):
    return str(value or "").strip().lower().replace("_", "-")


def _managed_dashboard_vm_identities(cfg):
    """Return managed VM identities allowed to appear in dashboard VM lists."""
    labels = set()
    vmids = set()
    for h in getattr(cfg, "hosts", []) or []:
        if not getattr(h, "managed", True):
            continue
        if getattr(h, "htype", "") == "pve":
            continue
        label = _label_key(getattr(h, "label", ""))
        if label:
            labels.add(label)
        try:
            vmid = int(getattr(h, "vmid", 0) or 0)
        except (TypeError, ValueError):
            vmid = 0
        if vmid:
            vmids.add(vmid)
    return labels, vmids


def _category_vmids(cat):
    vmids = set()
    for vmid in cat.get("vmids", []) or []:
        try:
            vmids.add(int(vmid))
        except (TypeError, ValueError):
            continue
    try:
        start = int(cat.get("range_start"))
        end = int(cat.get("range_end"))
    except (TypeError, ValueError):
        return vmids
    if start > end:
        start, end = end, start
    vmids.update(range(start, end + 1))
    return vmids


def _dashboard_vm_scope(cfg):
    """Return explicit dashboard VM visibility contract."""
    visible_vmids = set()
    hidden_vmids = set()
    fb = getattr(cfg, "fleet_boundaries", None)
    categories = getattr(fb, "categories", {}) or {}
    hidden_categories = {
        "out_of_contract",
        "discovered_unowned",
        "inventory_only",
        "unowned",
    }
    visible_categories = {
        "production",
        "lab",
        "infrastructure",
        "prod_media",
        "prod_other",
        "personal",
    }
    for name, cat in categories.items():
        cat_vmids = _category_vmids(cat)
        if name in hidden_categories:
            hidden_vmids.update(cat_vmids)
            continue
        if name == "templates":
            continue
        if name in visible_categories or str(cat.get("tier", "")) in {"operator", "admin"}:
            visible_vmids.update(cat_vmids)

    managed_labels, managed_vmids = _managed_dashboard_vm_identities(cfg)
    return {
        "visible_vmids": visible_vmids,
        "hidden_vmids": hidden_vmids,
        "managed_labels": managed_labels,
        "managed_vmids": managed_vmids,
        "has_boundary_contract": bool(visible_vmids or hidden_vmids),
    }


def _dashboard_vm_visible(vm, scope):
    """Dashboard VM cards are for operator-owned guests, not raw PVE inventory."""
    try:
        vmid = int((vm or {}).get("vmid", 0) or 0)
    except (TypeError, ValueError):
        vmid = 0
    if vmid and vmid in scope["hidden_vmids"]:
        return False
    if vmid and vmid in scope["visible_vmids"]:
        return True
    if scope["has_boundary_contract"]:
        return False
    if vmid and vmid in scope["managed_vmids"]:
        return True
    name = _label_key((vm or {}).get("name", ""))
    return bool(name and name in scope["managed_labels"])


class FreqHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the FREQ dashboard."""

    # HTTP/1.1 required for WebSocket upgrade (RFC 6455) and SSE keep-alive
    protocol_version = "HTTP/1.1"

    # Class-level caches for PVE metrics polling
    _pve_metrics_cache = None
    _pve_metrics_ts = 0
    _doctor_cache = None
    _doctor_cache_ts = 0
    _doctor_lock = threading.Lock()
    _doctor_cache_ttl = 15
    # per-node last-seen tracking so the
    # dashboard can render 'STALE 47s' instead of a bare 'offline' chip.
    _pve_last_seen_ts: dict = {}

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def send_response(self, code, message=None):
        self._response_status = int(code)
        super().send_response(code, message)

    def send_header(self, keyword, value):
        if keyword.lower() == "content-length":
            try:
                self._response_bytes = int(value)
            except (TypeError, ValueError):
                self._response_bytes = None
        super().send_header(keyword, value)

    def end_headers(self):
        request_id = getattr(self, "_request_id", "")
        if request_id and not getattr(self, "_request_id_header_sent", False):
            self.send_header("X-Request-ID", request_id)
            self._request_id_header_sent = True
        super().end_headers()

    def _begin_request(self):
        self._request_id = uuid.uuid4().hex[:12]
        self._request_started = time.monotonic()
        self._response_status = None
        self._response_bytes = None
        self._request_path = self.path.split("?")[0]
        self._request_user = ""
        self._request_role = ""
        logger.info(
            "http_request_start",
            request_id=self._request_id,
            method=getattr(self, "command", "?"),
            path=self._request_path,
            client=getattr(self, "client_address", ("?", 0))[0],
        )

    def _finish_request(self):
        started = getattr(self, "_request_started", None)
        duration_ms = round((time.monotonic() - started) * 1000, 1) if started else None
        status = getattr(self, "_response_status", None)
        user = getattr(self, "_request_user", "") or getattr(self, "_session_user", "")
        role = getattr(self, "_request_role", "") or getattr(self, "_session_role", "")
        logger.info(
            "http_request_end",
            request_id=getattr(self, "_request_id", ""),
            method=getattr(self, "command", "?"),
            path=getattr(self, "_request_path", self.path.split("?")[0]),
            status=status if status is not None else "unknown",
            duration_ms=duration_ms,
            bytes=getattr(self, "_response_bytes", None),
            user=user,
            role=role,
        )

    # Route dispatch table — path → method name (resolved at call time via getattr)
    _ROUTES = {
        # ── Infrastructure routes (stay in serve.py) ──────────────────
        "/": "_serve_app",
        "/dashboard": "_serve_app",
        "/setup": "_serve_setup_page",
        "/setup.html": "_serve_setup_page",
        # ── Auth (stays in serve.py) ──────────────────────────────────
        "/api/pve/metrics": "_serve_pve_metrics",
        "/api/pve/rrd": "_serve_pve_rrd",
        "/api/auth/login": "_serve_auth_login",
        "/api/auth/logout": "_serve_auth_logout",
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
        "/api/setup/init/start": "_serve_setup_init_start",
        "/api/setup/init/status": "_serve_setup_init_status",
        "/api/setup/init/logs": "_serve_setup_init_logs",
        "/api/setup/reset": "_serve_setup_reset",
        # ── SSE / orchestration (stays in serve.py) ───────────────────
        "/api/events": "_serve_events",
        "/api/ui/event": "_serve_ui_event",
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
    # F2 of R-SECURITY-TRUST-AUDIT-20260413P removed /api/setup/test-ssh
    # from this set: it now requires either the first-run window AND
    # admin (post-create-admin) OR an existing admin session, scoped
    # to the configured PVE nodes only.
    _AUTH_WHITELIST = frozenset({
        "/api/auth/login",
        "/api/auth/verify",
        "/api/setup/status",
        "/api/setup/create-admin",
        "/api/setup/configure",
        "/api/setup/generate-key",
        "/api/setup/complete",
        "/api/docs",
        "/healthz",
        "/readyz",
        "/api/openapi.json",
    })
    # Path prefixes that don't require authentication
    _AUTH_WHITELIST_PREFIXES = ("/static/", "/dashboard")

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
                logger.warn(
                    "http_auth_rejected",
                    request_id=getattr(self, "_request_id", ""),
                    method=getattr(self, "command", "?"),
                    path=path,
                    reason=err,
                )
                #  task 1: when the caller
                # passed ?token= in the query string but no cookie or
                # Authorization header, surface the truthful migration
                # reason so the operator can see that query-string auth
                # was removed (R-SECURITY-TRUST-AUDIT-20260413P F7)
                # instead of a generic "Authentication required". The
                # token value is not trusted or parsed — only its
                # presence in the URL is used to select the message.
                if _request_has_query_token(self):
                    self._json_response({
                        "error": (
                            "Query-string auth removed. Use the freq_session "
                            "cookie (same-origin EventSource sends it "
                            "automatically) or an Authorization: Bearer "
                            "header. See R-SECURITY-TRUST-AUDIT-20260413P F7."
                        ),
                        "reason": "query_token_removed",
                        "migration": "R-SECURITY-TRUST-AUDIT-20260413P-F7",
                    }, 403)
                else:
                    self._json_response({"error": err}, 403)
                return
            self._request_role = role or ""
            self._request_user = getattr(self, "_session_user", "")

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

                try:
                    logger.error(
                        "http_handler_exception",
                        request_id=getattr(self, "_request_id", ""),
                        method=getattr(self, "command", "?"),
                        path=path,
                        status=500,
                        error=repr(e),
                        traceback=traceback.format_exc(),
                    )
                    self._json_response({
                        "error": "Internal server error",
                        "path": path,
                        "request_id": getattr(self, "_request_id", ""),
                    }, 500)
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
        self._begin_request()
        try:
            self._dispatch()
        finally:
            self._finish_request()

    def do_POST(self):
        self._begin_request()
        try:
            self._dispatch()
        finally:
            self._finish_request()

    # ── Server-Sent Events ────────────────────────────────────────────────

    def _serve_events(self):
        """SSE endpoint — streams live updates to the dashboard.

        Keeps the connection open and pushes events as they arrive from
        background cache probes. Each client gets its own Queue via the
        SSE event bus. Sends keepalive comments every 15s.
        """
        # Auth: same-origin EventSource sends the freq_session cookie.
        # Query-string token auth was removed because it leaks into URLs/logs.
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
        self._send_security_headers()
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

    def _serve_ui_event(self):
        """POST /api/ui/event — log browser-visible UI events.

        This is intentionally small and non-authoritative. It lets server
        logs show the same toast/card state the operator saw in the browser,
        without depending on screenshots to reconstruct frontend behavior.
        """
        role, err = _check_session_role(self, "viewer")
        if err:
            self._json_response({"error": err}, 403)
            return
        if self.command != "POST":
            self._json_response({"error": "UI event logging requires POST"}, 405)
            return
        body = self._request_body()
        event_type = str(body.get("event", "ui_event"))[:64]
        level = str(body.get("level", body.get("type", "info")))[:24]
        message = str(body.get("message", ""))[:500]
        source = str(body.get("source", ""))[:120]
        view = str(body.get("view", ""))[:80]
        logger.info(
            "ui_event",
            event=event_type,
            ui_level=level,
            source=source,
            view=view,
            message=message,
        )
        self._json_response({"ok": True})

    # ── Topology ─────────────────────────────────────────────────────────

    def _serve_media_tags(self):
        """GET/POST /api/media/tags — persist media container tags server-side."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}, 403)
            return
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
        tdarr_data = {"status": "unknown", "queue": 0, "processed": 0, "errors": 0}

        with _bg_lock:
            health = _bg_cache.get("health")
        if not health:
            tdarr_data["status"] = "unknown"
        else:
            healthy_hosts = [h for h in health.get("hosts", []) if h.get("status") == "healthy"]
            if not healthy_hosts:
                tdarr_data["status"] = "unavailable"
            else:
                tdarr_data["status"] = "not_found"
                from freq.core.ssh import run as ssh_fn

                for h in healthy_hosts:
                    r = ssh_fn(
                        host=h.get("ip", ""),
                        command="docker inspect tdarr 2>/dev/null | grep -c '\"Running\": true'",
                        key_path=cfg.ssh_key_path,
                        connect_timeout=3,
                        command_timeout=10,
                        htype=h.get("type", "linux"),
                        use_sudo=False,
                        cfg=cfg,
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
                    cfg=cfg,
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
            self._json_response({"error": err}, 403)
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
            # Get docstring from handler (method name or callable)
            if callable(method_name):
                desc = (method_name.__doc__ or "").strip().split("\n")[0]
            else:
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
        # Add proxy routes not in static tables
        routes["/api/comms/{path}"] = "_proxy_watchdog"
        routes["/api/watch/{path}"] = "_proxy_watchdog"

        _POST_KEYWORDS = ("create", "update", "delete", "reset", "login", "logout",
                          "change", "complete", "generate", "deploy",
                          "rollback", "power", "boot", "clear", "wol",
                          "bench", "reboot", "add", "remove")
        # Paths that contain POST keywords but are actually GET (read-only)
        _GET_OVERRIDES = {"/api/fleet/updates", "/api/redfish/power-usage"}

        paths = {}
        for path, handler_ref in sorted(routes.items()):
            if path in ("/", "/dashboard", "/api/docs", "/api/openapi.json"):
                continue
            # Resolve description from method or callable
            if callable(handler_ref):
                desc = (handler_ref.__doc__ or "").strip().split("\n")[0]
            else:
                handler = getattr(self, handler_ref, None)
                desc = (handler.__doc__ or "").strip().split("\n")[0] if handler else ""

            # Detect HTTP method from path name or docstring
            path_tail = path.rsplit("/", 1)[-1]
            doc_lower = desc.lower()
            if path in _GET_OVERRIDES:
                method = "get"
            elif any(kw in path_tail for kw in _POST_KEYWORDS) or doc_lower.startswith("post "):
                method = "post"
            else:
                method = "get"

            responses = {
                "200": {"description": "Successful response", "content": {"application/json": {}}},
            }
            if method == "post":
                responses["400"] = {"description": "Validation error"}
                responses["403"] = {"description": "Insufficient permissions"}
            responses["500"] = {"description": "Internal server error"}

            # Clean up summary — don't expose internal method names
            summary = desc
            if not summary or summary.startswith("_serve_"):
                # Derive a readable summary from the path
                parts = path.strip("/").split("/")
                summary = " ".join(parts[1:]).replace("-", " ").replace("_", " ").title()

            paths[path] = {
                method: {
                    "summary": summary,
                    "responses": responses,
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
            "components": {
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "description": "Session token from POST /api/auth/login",
                    },
                    "cookieAuth": {
                        "type": "apiKey",
                        "in": "cookie",
                        "name": "freq_session",
                        "description": "HttpOnly session cookie set on login",
                    },
                },
            },
            "security": [{"bearerAuth": []}, {"cookieAuth": []}],
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
        """Return cached update check result with staleness metadata."""
        from freq import __version__

        with _bg_lock:
            update = _bg_cache.get("update")
            update_ts = _bg_cache_ts.get("update", 0)
            update_err = _bg_cache_errors.get("update")
        if update:
            response = dict(update)
            age = round(time.time() - update_ts, 1) if update_ts else None
            response["cached"] = True
            response["age_seconds"] = age
            response["stale"] = age is not None and age > UPDATE_CHECK_INTERVAL + 600
            if update_err:
                response["probe_status"] = "error"
                response["probe_error"] = update_err["error"]
            elif response.get("error"):
                # Probe ran but GitHub was unreachable — error is in the
                # cached result, not in _bg_cache_errors (graceful degradation)
                response["probe_status"] = "error"
                response["probe_error"] = response["error"]
            else:
                response["probe_status"] = "ok"
            self._json_response(response)
        else:
            self._json_response(
                {
                    "current": __version__,
                    "latest": "",
                    "update_available": False,
                    "checked_at": 0,
                    "cached": False,
                    "stale": True,
                    "probe_status": "pending",
                }
            )

    # ── Alert Rules Endpoints ──────────────────────────────────────────

    def _serve_setup_status(self):
        """Return current setup state including SSH key existence."""
        from freq import __version__

        cfg = load_config()
        # Use the actual resolved key path — re-detect on each call so we
        # catch keys created after serve started (e.g., init runs post-serve)
        key_path = cfg.ssh_key_path
        if not key_path:
            # Re-detect only when no configured key path exists. If config names
            # a key path, setup status should report that path's disk state
            # instead of finding an unrelated fallback key elsewhere.
            from freq.core.config import _detect_ssh_key
            key_path = _detect_ssh_key(cfg) or key_path
        key_exists = bool(key_path and os.path.isfile(key_path))
        key_readable = key_exists and os.access(key_path, os.R_OK)
        has_hosts = bool(cfg.hosts)
        has_nodes = bool(cfg.pve_nodes)
        # Check markers — .initialized is ONLY written by freq init (CLI).
        # .web-setup-complete is written by the web setup wizard.
        # The two are distinct: web setup alone does NOT mean init ran.
        initialized_marker = os.path.join(cfg.conf_dir, ".initialized")
        is_initialized = os.path.isfile(initialized_marker)
        web_setup_marker = os.path.join(cfg.conf_dir, ".web-setup-complete")
        is_web_setup_complete = os.path.isfile(web_setup_marker)

        running_job = None
        try:
            snap = _setup_init_snapshot()
            running_job = snap.get("job") if snap else None
        except Exception:
            running_job = None
        init_is_running = bool(running_job and running_job.get("state") == "running")

        # Honest health — five tiers:
        # "configured" = freq init completed (.initialized) + config items
        # "init-running" = web-launched init is still running
        # "web-setup-only" = web wizard done but freq init not yet run
        # "partial" = config items exist but neither marker
        # "unconfigured" = nothing configured yet
        init_blocker = "" if is_initialized or init_is_running else _init_blocker_from_artifacts(cfg)
        missing = []
        if not is_initialized:
            missing.append(init_blocker or "freq init not yet run (no .initialized marker)")
        if not key_readable:
            missing.append("ssh key missing or unreadable")
        if not has_nodes:
            missing.append("no PVE nodes configured")
        if not has_hosts:
            missing.append("no fleet hosts configured")
        if is_initialized and key_readable and has_hosts and has_nodes:
            setup_health = "configured"
            setup_reason = "freq init completed, key readable, hosts + nodes configured"
        elif init_is_running:
            setup_health = "init-running"
            setup_reason = "freq init is running"
        elif init_blocker:
            setup_health = "init-failed"
            setup_reason = init_blocker
        elif is_web_setup_complete and not is_initialized:
            setup_health = "web-setup-only"
            setup_reason = "web setup complete — run freq init to deploy fleet service account"
        elif key_exists or has_hosts or has_nodes:
            setup_health = "partial"
            setup_reason = "partial setup: " + "; ".join(missing)
        else:
            setup_health = "unconfigured"
            setup_reason = "no setup performed"

        dashboard_users = []
        dashboard_accounts_configured = False
        dashboard_passwords_configured = False
        try:
            dashboard_users = _load_users(cfg)
            dashboard_accounts_configured = bool(dashboard_users)
            dashboard_passwords_configured = any(
                bool(vault_get(cfg, "auth", f"password_{u.get('username', '')}"))
                for u in dashboard_users
                if u.get("username")
            )
        except Exception as e:
            logger.warn(f"setup_status_dashboard_user_health_failed: {e}")

        # F11 of R-SECURITY-TRUST-AUDIT-20260413P: this endpoint is in the
        # AUTH_WHITELIST so an unauth caller hits it during setup wizard
        # bootstrap. Don't leak the absolute SSH key filesystem path —
        # ssh_key_exists / ssh_key_readable carry the same UI information
        # without naming the on-disk location an attacker would target if
        # they later got a foothold. Same reason version + host_count are
        # gated to authenticated responses below.
        is_authed = False
        try:
            authed_role, authed_err = _check_session_role(self, "viewer")
            is_authed = authed_err is None
        except Exception:
            is_authed = False
        payload = {
            "first_run": _is_first_run(),
            "ssh_key_exists": key_exists,
            "ssh_key_readable": key_readable,
            "pve_nodes_configured": has_nodes,
            "hosts_configured": has_hosts,
            "setup_health": setup_health,
            "setup_reason": setup_reason,
            "initialized": is_initialized,
            "web_setup_complete": is_web_setup_complete,
            "dashboard_accounts_configured": dashboard_accounts_configured,
            "dashboard_passwords_configured": dashboard_passwords_configured,
            "checked_at": time.time(),
        }
        if is_authed:
            payload["version"] = __version__
            payload["ssh_key_path"] = key_path or ""
            payload["host_count"] = len(cfg.hosts)
            payload["dashboard_users"] = [
                {
                    "username": u.get("username", ""),
                    "role": u.get("role", ""),
                    "has_password": bool(vault_get(cfg, "auth", f"password_{u.get('username', '')}")),
                }
                for u in dashboard_users
                if u.get("username")
            ]
        self._json_response(payload)

    def _serve_setup_create_admin(self):
        """Create admin account during first-run setup.

        Accepts POST with JSON body only. Credentials must not be in URLs.
        POST body: {"username": "...", "password": "..."} or
        {"username": "...", "password_file": "/path/to/operator-password"}.

        T-8 of R-SECURITY-ARCH-DEBT-20260413U: wrapped in _setup_lock
        with a double-checked _is_first_run() inside the lock. Pre-fix
        two concurrent requests could both pass the first _is_first_run
        check, both reach users.conf, and land two admin accounts in a
        single first-run window. The window is narrow (first-run only)
        but an operator running `curl &` twice during bootstrap, or an
        attacker racing the legitimate operator, could trip it. Now:
          - Fast-path reject before attempting the lock.
          - Non-blocking lock acquire → 409 if another setup mutation
            is already in flight (parity with _serve_setup_complete).
          - Re-check _is_first_run INSIDE the lock so a racing
            complete/create-admin can't slip through.
        """
        if self.command != "POST":
            self._json_response({"error": "Use POST with JSON body"}, 405)
            return

        username = ""
        password = ""
        try:
            body = self._request_body()
            username = body.get("username", "").strip().lower()
            if body.get("password_file"):
                password = _read_setup_secret_file(body.get("password_file"), "operator password")
            else:
                password = body.get("password", "")
        except Exception:
            pass

        first_run = _is_first_run()
        cfg = load_config()
        if not first_run:
            if _setup_marker_exists(cfg):
                self._json_response({"error": "Setup wizard already used — run freq init to complete fleet deployment"}, 403)
                return
            if not username or not password:
                self._json_response({"error": "Setup admin session resume failed"}, 403)
                return
            if not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", username) or len(password) < 8:
                self._json_response({"error": "Setup admin session resume failed"}, 403)
                return
            users = _load_users(cfg)
            user = next((u for u in users if u.get("username") == username), None)
            stored_hash = vault_get(cfg, "auth", f"password_{username}") if user else ""
            if not user or user.get("role") != "admin" or not stored_hash or not _verify_password(password, stored_hash):
                self._json_response({"error": "Setup admin session resume failed"}, 403)
                return
            try:
                from freq.api.auth import establish_session

                establish_session(self, username, "admin")
            except Exception as e:
                logger.warn(f"setup_create_admin_resume_session_failed: {e}")
            self._json_response({"ok": True, "user": username, "role": "admin", "session_started": True, "resumed": True})
            return

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

        # T-8: serialize setup mutations. Non-blocking acquire — a
        # concurrent create-admin/configure/complete returns 409.
        if not _setup_lock.acquire(blocking=False):
            self._json_response({"error": "Setup already in progress"}, 409)
            return
        try:
            # Double-checked locking: another request may have completed
            # setup between our first _is_first_run() check above and the
            # lock acquire.
            if not _is_first_run():
                self._json_response({"error": "Setup wizard already used — run freq init to complete fleet deployment"}, 403)
                return

            # Create user in users.conf
            users = _load_users(cfg)
            if any(u["username"] == username for u in users):
                self._json_response({"error": f"User '{username}' already exists"}, 409)
                return

            users.append({"username": username, "role": "admin", "groups": ""})
            os.makedirs(cfg.conf_dir, exist_ok=True)
            save_error = _save_users_error(cfg, users)
            if save_error:
                self._json_response({"error": f"Failed to save user: {save_error}"}, 500)
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

            try:
                from freq.api.auth import establish_session

                establish_session(self, username, "admin")
            except Exception as e:
                logger.warn(f"setup_create_admin_session_failed: {e}")
            self._json_response({"ok": True, "user": username, "role": "admin", "session_started": True})
        finally:
            _setup_lock.release()

    def _serve_setup_configure(self):
        """Save cluster configuration during first-run setup.

        POST body: {"cluster_name": "...", "timezone": "...", "pve_nodes": [...]}
        """
        if not _is_first_run() and not _allow_setup_admin_window(self):
            return

        if self.command != "POST":
            self._json_response({"error": "Use POST with JSON body"}, 405)
            return

        body = self._request_body()
        cluster_name = str(body.get("cluster_name", "")).strip()
        timezone = str(body.get("timezone", "UTC")).strip()
        pve_nodes_value = body.get("pve_nodes", [])
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
        """Generate SSH keypair during first-run setup. POST only."""
        if not _is_first_run() and not _allow_setup_admin_window(self):
            return

        if self.command != "POST":
            self._json_response({"error": "Use POST to generate keys"}, 405)
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
        if not _is_first_run() and not _allow_setup_admin_window(self):
            return

        if self.command != "POST":
            self._json_response({"error": "Use POST to complete setup"}, 405)
            return

        if not _setup_lock.acquire(blocking=False):
            self._json_response({"error": "Setup already in progress"}, 409)
            return

        try:
            # Re-check after acquiring lock (another request may have completed setup)
            if not _is_first_run() and not _allow_setup_admin_window(self):
                return

            cfg = load_config()
            data_dir = cfg.data_dir
            os.makedirs(data_dir, exist_ok=True)
            marker = os.path.join(data_dir, "setup-complete")

            with open(marker, "w") as f:
                f.write(f"Setup completed: {datetime.datetime.now().isoformat()}\n")

            # Write .web-setup-complete marker — distinct from .initialized
            # which is ONLY written by freq init after a successful fleet
            # deploy. The web wizard completing does NOT mean init ran.
            try:
                os.makedirs(cfg.conf_dir, exist_ok=True)
                web_marker = os.path.join(cfg.conf_dir, ".web-setup-complete")
                if not os.path.isfile(web_marker):
                    from freq import __version__

                    with open(web_marker, "w") as f:
                        f.write(f"PVE FREQ {__version__} — web setup {datetime.datetime.now().isoformat()}\n")
            except OSError:
                pass  # Non-fatal — setup-complete marker is primary

            # Auto-trigger hosts sync so fleet populates immediately
            try:
                threading.Thread(target=_bg_sync_hosts, daemon=True).start()
            except Exception as e:
                logger.warning(f"Post-setup hosts sync failed to start: {e}")

            self._json_response({"ok": True, "message": "Web setup complete — run freq init to deploy the fleet service account"})
        except OSError as e:
            self._json_response({"error": f"Failed to write setup marker: {e}"}, 500)
        finally:
            _setup_lock.release()

    def _serve_setup_test_ssh(self):
        """Test SSH connectivity to a PVE node during setup.

        F2 of R-SECURITY-TRUST-AUDIT-20260413P:
        - Removed from _AUTH_WHITELIST (no longer unauth).
        - Requires admin role from the global auth gate (the dispatch
          gate already enforces viewer; here we tighten to admin).
        - Validates the requested host against cfg.pve_nodes (the
          targets the in-progress setup wizard has already declared
          via /api/setup/configure). Hosts not in that list are
          refused so an attacker with admin creds still cannot use
          this endpoint as a generic SSRF.
        Pre-fix this was an unauth IP-format-validated SSH probe
        gateway during the first-run window, which combined with F9's
        fail-open _is_first_run gave a real attack path.
        """
        # Admin role required even during first-run. The dispatch gate
        # would already 403 unauth callers because the route is no
        # longer whitelisted, but we tighten further to admin here.
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return

        # T-4 of R-REDTEAM-SECURITY-ASSAULT-20260413T: setup-wizard
        # endpoints must not stay callable after setup completes.
        # `freq doctor`, `freq host test`, and the dashboard health
        # panel cover the post-init SSH-probe need — keeping
        # test-ssh alive is unnecessary admin-only surface.
        if not _is_first_run():
            self._json_response(
                {"error": "Setup wizard already used — use freq doctor or /api/host/test"},
                403,
            )
            return

        cfg = load_config()
        params = _parse_query(self)
        host = params.get("host", [""])[0].strip()

        if not host:
            self._json_response({"error": "host parameter required"}, 400)
            return

        # Basic IP/hostname validation (pre-existing).
        from freq.core import validate as _val

        if not (_val.ip(host) or _val.hostname(host)):
            self._json_response({"error": f"Invalid host: {host}"}, 400)
            return

        # F2: scope to configured PVE nodes only. The setup wizard
        # collects PVE node IPs via /api/setup/configure before the
        # operator hits /api/setup/test-ssh; an admin who tries to
        # probe an arbitrary host is refused here even though they
        # have admin role.
        configured_targets = set(cfg.pve_nodes or [])
        if host not in configured_targets:
            self._json_response(
                {
                    "error": (
                        f"Host {host} is not in the configured PVE node list; "
                        f"add it via /api/setup/configure first. test-ssh is "
                        f"scoped to setup-declared targets."
                    ),
                },
                403,
            )
            return

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
        """POST /api/setup/reset — reset setup wizard. Admin only. Deletes setup-complete marker."""
        if self.command != "POST":
            self._json_response({"error": "Setup reset requires POST"}, 405)
            return
        cfg = load_config()

        # This endpoint requires admin auth (NOT gated by _is_first_run)
        role, err = _check_session_role(self, min_role="admin")
        if err:
            self._json_response({"error": err}, 403)
            return

        data_dir = cfg.data_dir
        marker = os.path.join(data_dir, "setup-complete")
        web_marker = os.path.join(cfg.conf_dir, ".web-setup-complete")

        try:
            for m in (marker, web_marker):
                if os.path.isfile(m):
                    os.remove(m)
            self._json_response({"ok": True, "message": "Setup wizard re-enabled (note: freq init state is unchanged — re-run freq init if needed)"})
        except OSError as e:
            self._json_response({"error": f"Failed to reset setup: {e}"}, 500)

    def _serve_setup_init_start(self):
        """POST /api/setup/init/start — run full headless init from web setup."""
        global _setup_init_job
        if self.command != "POST":
            self._json_response({"error": "Setup init start requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        cfg = load_config()
        if os.path.isfile(os.path.join(cfg.conf_dir, ".initialized")):
            self._json_response({"error": "freq init is already complete"}, 409)
            return
        with _setup_init_lock:
            if _setup_init_job and _setup_init_job.get("state") == "running":
                self._json_response({"error": "setup init already running", "job": dict(_setup_init_job)}, 409)
                return
        try:
            body = self._request_body()
            job_id = uuid.uuid4().hex[:12]
            cmd, env, secret_dir = _setup_init_command(cfg, body, job_id)
        except ValueError as exc:
            self._json_response({"error": str(exc)}, 400)
            return
        except Exception as exc:
            self._json_response({"error": f"could not prepare setup init: {exc}"}, 500)
            return

        now = time.time()
        with _setup_init_lock:
            _setup_init_job = {
                "id": job_id,
                "state": "running",
                "pid": None,
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
                "returncode": None,
                "initialized": False,
                "lines": ["starting web-launched freq init --headless"],
            }
        threading.Thread(
            target=_run_setup_init_job,
            args=(job_id, cmd, env, secret_dir),
            daemon=True,
            name=f"freq-setup-init-{job_id}",
        ).start()
        self._json_response({"ok": True, "job": _setup_init_snapshot()["job"]})

    def _serve_setup_init_status(self):
        """GET /api/setup/init/status — return current web-launched init job."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        snap = _setup_init_snapshot()
        job = snap.get("job") or {}
        lines = list(job.get("lines") or [])
        state = job.get("state") or ("running" if snap.get("running") else "idle")
        payload = {"ok": True, **snap, "state": state, "log_tail": lines}
        if lines:
            payload["phase"] = lines[-1]
        if state == "succeeded":
            payload["state"] = "complete"
        if state == "failed":
            payload["blocker"] = job.get("error") or (lines[-1] if lines else "setup init failed")
        self._json_response(payload)

    def _serve_setup_init_logs(self):
        """GET /api/setup/init/logs — return current web-launched init log tail."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        snap = _setup_init_snapshot()
        job = snap.get("job") or {}
        lines = list(job.get("lines") or [])
        self._json_response(
            {
                "ok": True,
                "running": snap.get("running", False),
                "state": "complete" if job.get("state") == "succeeded" else job.get("state", "idle"),
                "job_id": job.get("id"),
                "lines": lines,
                "log_tail": lines,
                "returncode": job.get("returncode"),
                "initialized": job.get("initialized", False),
            }
        )

    # ── Legacy + Main HTML ───────────────────────────────────────────────

    def _serve_setup_page(self):
        """Serve the setup wizard while setup/init has not completed."""
        cfg = load_config()
        if os.path.isfile(os.path.join(cfg.conf_dir, ".initialized")) and _setup_marker_exists(cfg):
            self._serve_app()
            return
        from freq.modules.web_ui import SETUP_HTML

        body = SETUP_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

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

                # record last-seen so a
                # subsequent offline probe can show 'STALE Ns' instead
                # of bare offline. Stored keyed by IP so node rename
                # doesn't lose history.
                now_wall = time.time()
                FreqHandler._pve_last_seen_ts[ip] = now_wall
                nodes.append(
                    {
                        "name": name,
                        "ip": ip,
                        "online": True,
                        "state": "live",
                        "reason": "PVE API responded",
                        "last_seen_ts": now_wall,
                        "age_seconds": 0,
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
                last_seen = FreqHandler._pve_last_seen_ts.get(ip)
                age = round(time.time() - last_seen, 1) if last_seen else None
                nodes.append({
                    "name": name,
                    "ip": ip,
                    "online": False,
                    # Distinguish 'never seen alive' (unreachable) from
                    # 'was alive, now not responding' (stale). Both render
                    # as down but the operator sees which one it is.
                    "state": "unreachable" if last_seen is None else "stale",
                    "reason": (
                        "PVE API did not respond — node never seen alive"
                        if last_seen is None
                        else f"PVE API did not respond; last seen {age}s ago"
                    ),
                    "last_seen_ts": last_seen,
                    "age_seconds": age,
                })
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
        self._send_security_headers()
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
        self.send_header("X-Content-Type-Options", "nosniff")
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
        import sqlite3

        db_path = os.path.join(cfg.data_dir, "jarvis", "knowledge.db")
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            conn = _init_db(db_path)
        except (OSError, sqlite3.OperationalError):
            fallback = os.path.join(os.path.expanduser("~"), ".freq", "knowledge.db")
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
            conn = _init_db(fallback)
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
            self._json_response({"error": "pfSense IP not configured", "data": {}}, 400)
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
                'echo "=== INTERFACES === ";'
                "printf '%-18s  %s\\n' 'INTERFACE' 'IP ADDRESS';"
                "printf '%-18s  %s\\n' '──────────────────' '────────────────────────';"
                "for iface in $(ifconfig -l); do "
                '  ips=$(ifconfig "$iface" 2>/dev/null | awk \'/ inet /{print $2}\' | tr \'\\n\' \',\' | sed \'s/,$//\'); '
                '  [ -n "$ips" ] || ips="no IP assigned"; '
                '  printf "%-18s  %s\\n" "$iface" "$ips"; '
                "done"
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
        pf_auth = resolve_staged_device_ssh_auth(cfg, "pfsense")
        r = ssh_single(
            host=pf_ip,
            command=cmd,
            key_path=pf_auth["key_path"],
            user=pf_auth["user"],
            local_user=pf_auth.get("local_user"),
            password_file=pf_auth.get("password_file") or None,
            sudo_password_file=pf_auth.get("sudo_password_file", False),
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=15,
            htype="pfsense",
            use_sudo=False,
            cfg=cfg,
            failure_log_level="warn",
        )

        auth_failed = "permission denied" in (r.stderr or "").lower() or "publickey" in (r.stderr or "").lower()

        self._json_response(
            {
                "action": action,
                "host": pf_ip,
                "reachable": r.returncode == 0,
                "auth_failed": auth_failed,
                "probe_method": "ssh_auth_failed" if auth_failed else ("ssh" if r.returncode == 0 else "ssh_failed"),
                "output": _redact_device_command_output(r.stdout) if r.returncode == 0 else "",
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
        """POST /api/agent/create — create a new agent VM."""
        if self.command != "POST":
            self._json_response({"error": "Agent create requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        cfg = load_config()
        params = _parse_query(self)
        template = params.get("template", ["blank"])[0]
        name = params.get("name", [template])[0]
        if not valid_label(name):
            self._json_response({"error": "Invalid agent name (alphanumeric + hyphens only)"}, 400)
            return
        agents = _load_agents(cfg)
        if name in agents:
            self._json_response({"error": f"Agent '{name}' already exists"}, 409)
            return
        tmpl = TEMPLATES.get(template, TEMPLATES.get("blank"))
        node_ip = _find_reachable_node(cfg)
        if not node_ip:
            self._json_response({"error": "No PVE node reachable"}, 502)
            return
        stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
        if not ok:
            self._json_response({"error": "Cannot allocate VMID"}, 502)
            return
        lab_cat = cfg.fleet_boundaries.categories.get("lab", {})
        vmid_floor = lab_cat.get("range_start", 5000)
        vmid = max(int(stdout.strip()), vmid_floor)
        cmd = f"qm create {vmid} --name {name} --cores {tmpl['cores']} --memory {tmpl['ram']} --cpu {cfg.vm_cpu} --machine {cfg.vm_machine} --net0 virtio,bridge={cfg.nic_bridge} --scsihw {cfg.vm_scsihw}"
        stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=120)
        if not ok:
            self._json_response({"error": f"VM creation failed: {stdout[:60]}"}, 500)
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
        """POST /api/agent/destroy — destroy an agent VM."""
        if self.command != "POST":
            self._json_response({"error": "Agent destroy requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        cfg = load_config()
        params = _parse_query(self)
        name = params.get("name", [""])[0]
        agents = _load_agents(cfg)
        if name not in agents:
            self._json_response({"error": f"Agent not found: {name}"}, 404)
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
        """POST /api/notify/test — send a test notification to configured channels."""
        if self.command != "POST":
            self._json_response({"error": "Notify test requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
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
        registry_configured = bool(cfg.container_vms)
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
                cfg=cfg,
            )
            running = {}
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.strip().split("\n"):
                    parts = line.split("|", 1)
                    if len(parts) == 2:
                        running[parts[0].strip()] = parts[1].strip()

            for cname, container in vm.containers.items():
                status = "not found"
                # Normalize hyphens/underscores for matching — init may discover
                # "tdarr_node" but Docker names it "tdarr-node"
                cn = cname.lower().replace("-", "_").replace(" ", "_")
                for rn, rs in running.items():
                    rn_norm = rn.lower().replace("-", "_").replace(" ", "_")
                    if cn in rn_norm or rn_norm in cn:
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
        self._json_response({
            "containers": containers,
            "count": len(containers),
            "registry_configured": registry_configured,
        })

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
        self._json_response({
            "services": results,
            "skipped": skipped,
            "registry_configured": bool(cfg.container_vms),
        })

    def _serve_media_downloads(self):
        """Active downloads from qBit + SABnzbd."""
        cfg = load_config()
        downloads = []
        warnings = []
        sources = []
        for vm in cfg.container_vms.values():
            for cname, container in vm.containers.items():
                port = _media_container_port(container)
                if "qbittorrent" in cname.lower():
                    data, r = _docker_exec_json(
                        cfg,
                        vm,
                        container.name,
                        f'curl -s --connect-timeout 3 "http://localhost:{port}/api/v2/torrents/info?filter=downloading"',
                    )
                    if isinstance(data, list):
                        downloads.extend(_parse_qbit_downloads(data, vm.label))
                        sources.append({"client": "qBittorrent", "vm": vm.label, "source": "container-local"})
                        continue

                    # qBit needs session cookie auth — try login first
                    qb_user = vault_get(cfg, "DEFAULT", "qbittorrent_user") or "admin"
                    qb_pass = vault_get(cfg, "DEFAULT", "qbittorrent_password") or ""
                    if not qb_pass:
                        warnings.append({
                            "client": "qBittorrent",
                            "vm": vm.label,
                            "reason": "auth_required",
                        })
                        logger.warn("qBittorrent password not in vault and container-local query was not authorized")
                        continue
                    r = _media_ssh_single(
                        cfg,
                        vm,
                        f"curl -s -c /tmp/qb.cookie --connect-timeout 3 "
                        f"'http://localhost:{port}/api/v2/auth/login' "
                        f"-d 'username={qb_user}&password={qb_pass}' && "
                        f"curl -s -b /tmp/qb.cookie --connect-timeout 3 "
                        f"'http://localhost:{port}/api/v2/torrents/info?filter=downloading'",
                        timeout=10,
                    )
                    if r.returncode == 0:
                        # Response may have "Ok.\n" or "Fails.\n" prefix from login
                        stdout = r.stdout
                        bracket = stdout.find("[")
                        if bracket >= 0:
                            stdout = stdout[bracket:]
                        try:
                            downloads.extend(_parse_qbit_downloads(json.loads(stdout), vm.label))
                            sources.append({"client": "qBittorrent", "vm": vm.label, "source": "vault-auth"})
                        except (json.JSONDecodeError, TypeError):
                            warnings.append({"client": "qBittorrent", "vm": vm.label, "reason": "bad_json"})
                    else:
                        warnings.append({"client": "qBittorrent", "vm": vm.label, "reason": "query_failed"})
                elif "sabnzbd" in cname.lower() and port:
                    # SABnzbd uses API key auth
                    api_key = ""
                    if container.vault_key:
                        try:
                            api_key = vault_get(cfg, "DEFAULT", container.vault_key) or ""
                        except Exception as e:
                            logger.warn(f"vault read failed for {cname}: {e}")
                    if api_key:
                        r = _media_ssh_single(
                            cfg,
                            vm,
                            f"curl -s --connect-timeout 3 "
                            f"'http://localhost:{port}/api?mode=queue&apikey={api_key}&output=json'",
                            timeout=10,
                        )
                        if r.returncode == 0:
                            try:
                                downloads.extend(_parse_sab_downloads(json.loads(r.stdout), vm.label))
                                sources.append({"client": "SABnzbd", "vm": vm.label, "source": "vault-auth"})
                                continue
                            except (json.JSONDecodeError, TypeError, ValueError):
                                warnings.append({"client": "SABnzbd", "vm": vm.label, "reason": "bad_json"})

                    data, r = _docker_exec_json(
                        cfg,
                        vm,
                        container.name,
                        "key=$(grep -Ei '^api_key[[:space:]]*=' /config/sabnzbd.ini | head -1 | "
                        "cut -d= -f2- | tr -d '[:space:]'); "
                        '[ -n "$key" ] || exit 42; '
                        f'curl -s --connect-timeout 3 "http://localhost:{port}/api?mode=queue&apikey=$key&output=json"',
                    )
                    if isinstance(data, dict):
                        try:
                            downloads.extend(_parse_sab_downloads(data, vm.label))
                            sources.append({"client": "SABnzbd", "vm": vm.label, "source": "container-config"})
                        except (TypeError, ValueError):
                            warnings.append({"client": "SABnzbd", "vm": vm.label, "reason": "bad_json"})
                    else:
                        warnings.append({"client": "SABnzbd", "vm": vm.label, "reason": "query_failed"})
        self._json_response({
            "downloads": downloads,
            "count": len(downloads),
            "warnings": warnings,
            "sources": sources,
        })

    def _serve_media_streams(self):
        """Active Plex streams via Tautulli."""
        cfg = load_config()

        container, vm = res.container_by_name(cfg.container_vms, "tautulli")
        sessions = []
        warnings = []
        sources = []
        if container and vm:
            port = _media_container_port(container)
            # Get API key from vault
            api_key = ""
            if container.vault_key:
                try:
                    api_key = vault_get(cfg, "DEFAULT", container.vault_key) or ""
                except Exception as e:
                    logger.warn(f"vault read failed for {container.vault_key}: {e}")
            if api_key:
                r = _media_ssh_single(
                    cfg,
                    vm,
                    f"curl -s --connect-timeout 3 "
                    f"'http://localhost:{port}/api/v2?apikey={api_key}&cmd=get_activity'",
                    timeout=10,
                )
                if r.returncode == 0:
                    try:
                        data = json.loads(r.stdout)
                        sources.append({"client": "Tautulli", "vm": vm.label, "source": "vault-auth"})
                    except (json.JSONDecodeError, TypeError):
                        data = None
                        warnings.append({"client": "Tautulli", "vm": vm.label, "reason": "bad_json"})
                else:
                    data = None
                    warnings.append({"client": "Tautulli", "vm": vm.label, "reason": "query_failed"})
            else:
                data, r = _docker_exec_json(
                    cfg,
                    vm,
                    container.name,
                    "key=$(grep -Ei '^api_key[[:space:]]*=' /config/config.ini | head -1 | "
                    "cut -d= -f2- | tr -d '[:space:]'); "
                    '[ -n "$key" ] || exit 42; '
                    f'curl -s --connect-timeout 3 "http://localhost:{port}/api/v2?apikey=$key&cmd=get_activity"',
                )
                if isinstance(data, dict):
                    sources.append({"client": "Tautulli", "vm": vm.label, "source": "container-config"})
                else:
                    warnings.append({"client": "Tautulli", "vm": vm.label, "reason": "query_failed"})
            if isinstance(data, dict):
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
        else:
            warnings.append({"client": "Tautulli", "reason": "not_configured"})
        self._json_response({
            "sessions": sessions,
            "count": len(sessions),
            "warnings": warnings,
            "sources": sources,
        })

    def _serve_media_dashboard(self):
        """Aggregate media dashboard data — from health cache (instant)."""
        cfg = load_config()

        # Derive from health cache — already has docker counts per host
        with _bg_lock:
            health = _bg_cache.get("health")
            _health_ts = _bg_cache_ts.get("health", 0)

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
                    cfg=cfg,
                )
                if r.returncode == 0:
                    try:
                        running += int(r.stdout.strip())
                    except ValueError:
                        pass

        age = round(time.time() - _health_ts, 1) if health else None
        registry_configured = bool(cfg.container_vms)
        self._json_response(
            {
                "containers_total": total,
                "containers_running": running,
                "containers_down": total - running,
                "vm_count": len(cfg.container_vms),
                "registry_configured": registry_configured,
                "cached": health is not None,
                "age_seconds": age,
                "source": "health_cache" if health else "live_probe",
            }
        )

    def _serve_media_restart(self):
        """POST /api/media/restart — restart a container."""
        if self.command != "POST":
            self._json_response({"error": "Container restart requires POST"}, 405)
            return
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}, 403)
            return
        cfg = load_config()

        query = _parse_query(self)
        name = query.get("name", [""])[0]
        if not name:
            self._json_response({"error": "name parameter required"}, 400)
            return

        container, vm = res.container_by_name(cfg.container_vms, name)
        if not container:
            self._json_response({"error": f"container not found: {name}"}, 404)
            return

        safe_name = shlex.quote(container.name)
        r = ssh_single(
            host=_resolve_container_vm_ip(vm),
            command=f"docker restart {safe_name} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=60,
            htype="docker",
            use_sudo=False,
            cfg=cfg,
        )
        self._json_response(
            {
                "ok": r.returncode == 0,
                "container": container.name,
                "vm": vm.label,
                "returncode": r.returncode,
                "output": r.stdout.strip() if r.stdout else "",
                "error": r.stderr.strip() if r.returncode != 0 else "",
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
            self._json_response({"error": "name parameter required"}, 400)
            return

        container, vm = res.container_by_name(cfg.container_vms, name)
        if not container:
            self._json_response({"error": f"container not found: {name}"}, 404)
            return

        safe_name = shlex.quote(container.name)
        r = ssh_single(
            host=_resolve_container_vm_ip(vm),
            command=f"docker logs --tail {lines} {safe_name} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=15,
            htype="docker",
            use_sudo=False,
            cfg=cfg,
        )
        self._json_response(
            {
                "ok": r.returncode == 0,
                "container": container.name,
                "vm": vm.label,
                "returncode": r.returncode,
                "logs": r.stdout if r.returncode == 0 else "",
                "error": r.stderr.strip() if r.returncode != 0 else "",
            }
        )

    def _serve_media_update(self):
        """POST /api/media/update — pull latest image for a container."""
        if self.command != "POST":
            self._json_response({"error": "Media update requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        cfg = load_config()

        query = _parse_query(self)
        name = query.get("name", [""])[0]

        if not name:
            self._json_response({"error": "name parameter required"}, 400)
            return

        container, vm = res.container_by_name(cfg.container_vms, name)
        if not container or not vm.compose_path:
            self._json_response({"error": f"container or compose not found: {name}"}, 404)
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
            cfg=cfg,
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

        def _is_lab_host(h):
            """Identify lab hosts by group, label, or fleet-boundaries VMID range."""
            # Explicit group assignment (manual or VLAN-scan)
            if "lab" in (h.groups or "").split(","):
                return True
            # Label contains "lab" (init-discovered: lab-pve1, pfsense-lab, etc.)
            if "lab" in h.label.lower():
                return True
            # VMID falls in fleet-boundaries lab category range
            if getattr(h, "vmid", 0):
                cat, _ = cfg.fleet_boundaries.categorize(h.vmid)
                if cat == "lab":
                    return True
            return False

        lab_hosts = [h for h in cfg.hosts if _is_lab_host(h)]

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
            cfg=cfg,
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

    # Per-tool config + endpoint allow-list. F3 of
    # R-SECURITY-TRUST-AUDIT-20260413P. The registry now carries an
    # explicit `endpoints` allow-list — the proxy refuses any endpoint
    # path not in this list. Pre-fix the proxy was a generic
    # operator-authenticated outbound HTTP gateway that took the
    # destination host AND the path AND the HTTP method as
    # query parameters, which made it a textbook SSRF.
    LAB_TOOL_REGISTRY = {
        "gwipe": {
            "default_port": 7980,
            "api_base": "/api/v1",
            "auth_header": "X-API-Key",
            "endpoints": frozenset({
                "status",
                "drives",
                "drives/list",
                "jobs",
                "jobs/list",
            }),
        },
    }

    def _lab_tool_request(self, tool_id, host, key, endpoint):
        """Make an HTTP GET request to a registered lab tool API.

        F3 of R-SECURITY-TRUST-AUDIT-20260413P:
        - host and key are vault-supplied by the caller; never user-
          supplied (the proxy reads them from vault before calling
          this helper).
        - method is GET-only by contract (no `method` param taken
          from the caller).
        - endpoint must be in the per-tool allow-list (the caller
          has already validated this; we re-validate here as
          defense-in-depth).
        """
        tool = self.LAB_TOOL_REGISTRY.get(tool_id)
        if not tool:
            return {"error": f"Unknown lab tool: {tool_id}"}
        if endpoint not in tool["endpoints"]:
            return {"error": f"Endpoint {endpoint!r} not allowed for {tool_id}"}
        port = tool["default_port"]
        base = tool["api_base"].rstrip("/")
        url = f"http://{host}:{port}{base}/{endpoint}"
        req = urllib.request.Request(url, method="GET")
        req.add_header(tool["auth_header"], key)
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
        """Read-only proxy for lab tool API requests.

        F3 of R-SECURITY-TRUST-AUDIT-20260413P:
        - GET-only (no method=POST/PUT/DELETE override).
        - host and key read from vault, NOT from query params.
        - endpoint must be in the per-tool LAB_TOOL_REGISTRY allow-list.
        Pre-fix this was a generic SSRF: operator-controlled host +
        operator-controlled endpoint + operator-controlled method.
        Now operator can only hit configured-tool endpoints that the
        registry knows about, only via GET, only against the host
        the admin pre-saved via /api/lab-tool/save-config.
        """
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}, 403)
            return
        params = _parse_query(self)
        tool = params.get("tool", [""])[0]
        endpoint = params.get("endpoint", [""])[0]

        if not tool or not endpoint:
            self._json_response({"error": "Missing tool or endpoint parameter"}, 400)
            return

        tool_def = self.LAB_TOOL_REGISTRY.get(tool)
        if not tool_def:
            self._json_response({"error": f"Unknown lab tool: {tool}"}, 404)
            return

        if endpoint not in tool_def["endpoints"]:
            self._json_response(
                {
                    "error": (
                        f"Endpoint {endpoint!r} is not in the allow-list for "
                        f"tool {tool!r}. Allowed: "
                        f"{sorted(tool_def['endpoints'])}"
                    ),
                },
                403,
            )
            return

        cfg = load_config()
        host = ""
        key = ""
        try:
            host = vault_get(cfg, tool, f"{tool}_host") or ""
            key = vault_get(cfg, tool, f"{tool}_api_key") or ""
        except Exception as e:
            logger.warn(f"vault read failed for {tool}: {e}")

        if not host or not key:
            self._json_response(
                {
                    "error": (
                        f"Tool {tool!r} has no saved host/key — admin must "
                        f"call /api/lab-tool/save-config first."
                    ),
                },
                503,
            )
            return

        result = self._lab_tool_request(tool, host, key, endpoint)
        self._json_response(result)

    def _serve_lab_tool_config(self):
        """Return saved connection config for a lab tool from vault."""
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}, 403)
            return
        params = _parse_query(self)
        tool = params.get("tool", [""])[0]
        if not tool:
            self._json_response({"error": "Missing tool parameter"}, 400)
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
        """Save lab tool connection config to vault.

        R-REDTEAM-SECURITY-ASSAULT-20260413T T-3: payload must come
        from the POST JSON body, not the URL query string. Pre-fix
        the handler read `tool`, `host`, `key` from query params —
        the API key landed in browser history, proxy access logs,
        Referer headers on dashboard navigation, and devtools HAR
        exports. Symmetric fix with F5 (ct/create) and F6
        (federation/register) from the P security audit.
        """
        if self.command != "POST":
            self._json_response({"error": "Use POST to save config"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        try:
            body = self._request_body()
            tool = (body.get("tool", "") or "").strip()
            host = (body.get("host", "") or "").strip()
            key = body.get("key", "") or ""
        except Exception as e:
            self._json_response({"error": f"Invalid request body: {e}"}, 400)
            return

        if not tool or not host or not key:
            self._json_response(
                {"error": "tool, host, and key required in POST JSON body"}, 400
            )
            return

        cfg = load_config()
        try:
            if not os.path.exists(cfg.vault_file):
                vault_init(cfg)
            vault_set(cfg, tool, f"{tool}_host", host)
            vault_set(cfg, tool, f"{tool}_api_key", key)
            self._json_response({"ok": True})
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    # ── Auth (delegated to freq.api.auth) ────────────────────────────

    def _serve_auth_login(self):
        handle_auth_login(self)

    def _serve_auth_logout(self):
        handle_auth_logout(self)

    def _serve_auth_verify(self):
        handle_auth_verify(self)

    def _serve_auth_change_password(self):
        handle_auth_change_password(self)

    def _proxy_watchdog(self):
        """Proxy requests to FREQ WATCHDOG daemon.

        Watchdog is an optional add-on. If not enabled in config, returns a
        normal 200 state object. The dashboard polls this endpoint
        automatically, so default optional absence must not look like a failed
        resource in browser tooling.
        """
        cfg = load_config()
        if not getattr(cfg, "watchdog_enabled", False):
            self._json_response(
                {"ok": True, "watchdog_installed": False, "status": "not_installed"},
                200,
            )
            return
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
                {"error": f"WATCHDOG daemon not reachable at localhost:{wd_port}", "watchdog_down": True}, 503
            )
        except Exception as e:
            self._json_response({"error": f"Proxy error: {e}"}, 502)

    # ── ADMIN API ENDPOINTS ──────────────────────────────────────────

    def _serve_admin_fleet_boundaries(self):
        """GET /api/admin/fleet-boundaries — return current fleet boundary config."""
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
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
                    k: {
                        "ip": d.ip,
                        "label": d.label,
                        "type": d.device_type,
                        "tier": d.tier,
                        "detail": d.detail,
                        "groups": d.groups,
                        "scope": d.scope,
                    }
                    for k, d in fb.physical.items()
                },
                "core_physical": {
                    k: {"ip": d.ip, "label": d.label, "type": d.device_type, "tier": d.tier, "detail": d.detail, "groups": d.groups, "scope": d.scope}
                    for k, d in fb.physical.items()
                    if d.scope != "lab"
                },
                "lab_physical": {
                    k: {"ip": d.ip, "label": d.label, "type": d.device_type, "tier": d.tier, "detail": d.detail, "groups": d.groups, "scope": d.scope}
                    for k, d in fb.physical.items()
                    if d.scope == "lab"
                },
                "pve_nodes": {k: {"ip": n.ip, "detail": n.detail} for k, n in fb.pve_nodes.items()},
                "hosts": [
                    {"ip": h.ip, "label": h.label, "type": h.htype, "groups": h.groups, "all_ips": h.all_ips}
                    for h in cfg.hosts
                ],
            }
        )

    def _serve_admin_fleet_boundaries_update(self):
        """POST /api/admin/fleet-boundaries/update — update fleet-boundaries.toml.

        Params: action=update_category|update_range|update_tier|add_vmid|remove_vmid
        """
        if self.command != "POST":
            self._json_response({"error": "fleet-boundaries update requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
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
                self._json_response({"error": "category and tier required"}, 400)
                return
            if cat_name not in cfg.fleet_boundaries.categories:
                self._json_response({"error": f"Unknown category: {cat_name}"}, 404)
                return
            if new_tier not in cfg.fleet_boundaries.tiers:
                self._json_response({"error": f"Unknown tier: {new_tier}"}, 404)
                return
            self._update_fb_toml(fb_path, "category_tier", cat_name=cat_name, tier=new_tier)
            self._json_response({"ok": True, "action": action})

        elif action == "add_vmid":
            cat_name = params.get("category", [""])[0]
            vmid_str = params.get("vmid", [""])[0]
            if not cat_name or not vmid_str:
                self._json_response({"error": "category and vmid required"}, 400)
                return
            try:
                vmid = int(vmid_str)
            except ValueError:
                self._json_response({"error": "vmid must be an integer"}, 400)
                return
            self._update_fb_toml(fb_path, "add_vmid", cat_name=cat_name, vmid=vmid)
            self._json_response({"ok": True, "action": action, "vmid": vmid})

        elif action == "remove_vmid":
            cat_name = params.get("category", [""])[0]
            vmid_str = params.get("vmid", [""])[0]
            if not cat_name or not vmid_str:
                self._json_response({"error": "category and vmid required"}, 400)
                return
            try:
                vmid = int(vmid_str)
            except ValueError:
                self._json_response({"error": "vmid must be an integer"}, 400)
                return
            self._update_fb_toml(fb_path, "remove_vmid", cat_name=cat_name, vmid=vmid)
            self._json_response({"ok": True, "action": action, "vmid": vmid})

        elif action == "update_range":
            cat_name = params.get("category", [""])[0]
            start_str = params.get("range_start", [""])[0]
            end_str = params.get("range_end", [""])[0]
            if not cat_name or not start_str or not end_str:
                self._json_response({"error": "category, range_start, range_end required"}, 400)
                return
            try:
                rs, re = int(start_str), int(end_str)
            except ValueError:
                self._json_response({"error": "range values must be integers"}, 400)
                return
            if rs >= re:
                self._json_response({"error": "range_start must be < range_end"}, 400)
                return
            self._update_fb_toml(fb_path, "update_range", cat_name=cat_name, range_start=rs, range_end=re)
            self._json_response({"ok": True, "action": action})

        elif action == "update_physical_scope":
            device_key = params.get("device", [""])[0]
            scope = params.get("scope", [""])[0].lower()
            if not device_key or scope not in {"core", "lab"}:
                self._json_response({"error": "device and scope=core|lab required"}, 400)
                return
            if device_key not in cfg.fleet_boundaries.physical:
                self._json_response({"error": f"Unknown physical device: {device_key}"}, 404)
                return
            self._update_fb_toml(fb_path, "update_physical_scope", device_key=device_key, scope=scope)
            self._json_response({"ok": True, "action": action, "device": device_key, "scope": scope})

        elif action == "update_tier_actions":
            tier_name = params.get("tier", [""])[0]
            actions_str = params.get("actions", [""])[0]
            if not tier_name or not actions_str:
                self._json_response({"error": "tier and actions required"}, 400)
                return
            if tier_name not in cfg.fleet_boundaries.tiers:
                self._json_response({"error": f"Unknown tier: {tier_name}"}, 404)
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
                self._json_response({"error": f"Invalid actions: {', '.join(invalid)}"}, 400)
                return
            self._update_fb_toml(fb_path, "update_tier_actions", tier_name=tier_name, actions=actions_list)
            self._json_response({"ok": True, "action": action, "tier": tier_name, "actions": actions_list})

        else:
            self._json_response({"error": f"Unknown action: {action}"}, 400)

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
            saw_start = False
            saw_end = False
            insert_at = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == f"[categories.{cat_name}]":
                    in_section = True
                    insert_at = i + 1
                    continue
                if in_section and stripped.startswith("[") and not stripped.startswith(f"[categories.{cat_name}"):
                    insert_at = i
                    break
                if in_section and stripped.startswith("range_start"):
                    lines[i] = f"range_start = {rs}\n"
                    saw_start = True
                if in_section and stripped.startswith("range_end"):
                    lines[i] = f"range_end = {re_val}\n"
                    saw_end = True
                if in_section and stripped:
                    insert_at = i + 1
            if in_section and (not saw_start or not saw_end):
                additions = []
                if not saw_start:
                    additions.append(f"range_start = {rs}\n")
                if not saw_end:
                    additions.append(f"range_end = {re_val}\n")
                lines[insert_at or len(lines):insert_at or len(lines)] = additions

        elif op == "update_physical_scope":
            device_key, scope = kw["device_key"], kw["scope"]
            in_physical = False
            inline_pat = re.compile(rf"^(\s*{re.escape(device_key)}\s*=\s*\{{)(.*)(\}}\s*)$")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == "[physical]":
                    in_physical = True
                    continue
                if in_physical and stripped.startswith("["):
                    break
                if not in_physical:
                    continue
                m = inline_pat.match(line.rstrip("\n"))
                if not m:
                    continue
                body = m.group(2)
                if re.search(r"\bscope\s*=", body):
                    body = re.sub(r'\bscope\s*=\s*"[^"]*"', f'scope = "{scope}"', body)
                else:
                    body = body.rstrip()
                    if body and not body.endswith(","):
                        body += ","
                    body += f' scope = "{scope}"'
                lines[i] = f"{m.group(1)}{body}{m.group(3)}\n"
                break

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
        """POST /api/admin/hosts/update — update host type or groups in hosts.toml.

        Params: label, type (optional), groups (optional)
        """
        if self.command != "POST":
            self._json_response({"error": "hosts update requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return

        params = _parse_query(self)
        label = params.get("label", [""])[0]
        new_type = params.get("type", [""])[0]
        new_groups = params.get("groups", [""])[0] if "groups" in params else None
        if not label:
            self._json_response({"error": "label required"}, 400)
            return

        cfg = load_config()
        hosts_path = cfg.hosts_file
        lines = []
        try:
            with open(hosts_path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            self._json_response({"error": "hosts.toml not found"}, 404)
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
            self._json_response({"error": f"Host '{label}' not found in hosts.toml"}, 404)
            return

        try:
            with open(hosts_path, "w") as f:
                f.writelines(lines)
        except OSError as e:
            self._json_response({"error": f"Failed to write hosts.toml: {e}"}, 500)
            return
        self._json_response({"ok": True, "label": label})

    # --- Phase 2: Feature parity endpoints ---

    def _serve_doctor(self):
        """Run FREQ self-diagnostic and return results as JSON."""
        try:
            now = time.monotonic()
            cached = FreqHandler._doctor_cache
            if cached is not None and now - FreqHandler._doctor_cache_ts < FreqHandler._doctor_cache_ttl:
                self._json_response(cached)
                return

            from freq.core.doctor import run as doctor_run
            import io, contextlib, json as _json

            with FreqHandler._doctor_lock:
                now = time.monotonic()
                cached = FreqHandler._doctor_cache
                if cached is not None and now - FreqHandler._doctor_cache_ts < FreqHandler._doctor_cache_ttl:
                    self._json_response(cached)
                    return

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    from freq.core.config import load_config as _lc

                    cfg = _lc()
                    result = doctor_run(cfg, json_output=True)
                # doctor_run with json_output prints JSON to stdout
                try:
                    data = _json.loads(buf.getvalue())
                except (ValueError, _json.JSONDecodeError):
                    data = {"ok": result == 0, "output": buf.getvalue(), "exit_code": result}
                FreqHandler._doctor_cache = data
                FreqHandler._doctor_cache_ts = time.monotonic()
            self._json_response(data)
        except Exception as e:
            self._json_response({"error": f"Doctor failed: {e}"}, 500)

    def _serve_watch_start(self):
        """POST /api/watch/start — start the FREQ watch daemon."""
        if self.command != "POST":
            self._json_response({"error": "Watch start requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        try:
            r = subprocess.run(
                ["freq", "watch", "start"], capture_output=True, text=True, timeout=10
            )
            self._json_response({"ok": r.returncode == 0, "output": r.stdout})
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _serve_watch_stop(self):
        """POST /api/watch/stop — stop the FREQ watch daemon."""
        if self.command != "POST":
            self._json_response({"error": "Watch stop requires POST"}, 405)
            return
        role, err = _check_session_role(self, "admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        try:
            r = subprocess.run(
                ["freq", "watch", "stop"], capture_output=True, text=True, timeout=10
            )
            self._json_response({"ok": r.returncode == 0, "output": r.stdout})
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _serve_dns_lookup(self):
        """Resolve a hostname.

        F17 of R-SECURITY-TRUST-AUDIT-20260413P: tightened from
        viewer to operator role and rate-limited per source IP.
        Pre-fix any logged-in viewer could submit any hostname and
        the dashboard would issue a DNS query for it via the host's
        resolver — a low-bandwidth covert exfiltration channel for
        an attacker with viewer credentials. The IP-based rate
        limit caps lookups at 30 per 5 minutes per source.
        """
        # Operator-only — viewer-role accounts must not trigger
        # outbound DNS queries through the dashboard.
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}, 403)
            return
        # Rate limit per source IP (best-effort in-process tracker).
        client_ip = self.client_address[0] if self.client_address else "unknown"
        if not _dns_lookup_rate_limit(client_ip):
            self._json_response(
                {"error": "Too many DNS lookups. Try again in 5 minutes."},
                429,
            )
            return
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        if not host:
            self._json_response({"error": "host required"}, 400)
            return
        if len(host) > 253:
            self._json_response({"error": "Hostname too long"}, 400)
            return
        import re as _re

        if not _re.match(r"^[a-zA-Z0-9._-]+$", host):
            self._json_response({"error": "Invalid hostname"}, 400)
            return
        try:
            import socket

            results = socket.getaddrinfo(host, None)
            ips = sorted(set(r[4][0] for r in results))
            self._json_response({"host": host, "ips": ips, "count": len(ips)})
        except socket.gaierror:
            self._json_response({"host": host, "ips": [], "error": "DNS resolution failed"}, 400)

    def _serve_portscan(self):
        """POST /api/net/portscan — scan ports on a host."""
        if self.command != "POST":
            self._json_response({"error": "Port scan requires POST"}, 405)
            return
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}, 403)
            return
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        ports_str = query.get("ports", [""])[0]
        if not host or not ports_str:
            self._json_response({"error": "host and ports required"}, 400)
            return
        import re as _re, socket

        if not _re.match(r"^[a-zA-Z0-9._-]+$", host):
            self._json_response({"error": "Invalid hostname"}, 400)
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
        if self.command != "POST":
            self._json_response({"error": "Container action requires POST"}, 405)
            return
        role, err = _check_session_role(self, "operator")
        if err:
            self._json_response({"error": err}, 403)
            return
        cfg = load_config()
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        name = query.get("name", [""])[0]
        action = query.get("action", ["restart"])[0]
        if not host or not name:
            self._json_response({"error": "host and name required"}, 400)
            return
        if action not in ("restart", "stop", "start"):
            self._json_response({"error": "action must be restart, stop, or start"}, 400)
            return
        import re as _re

        if not _re.match(r"^[a-zA-Z0-9._-]+$", name):
            self._json_response({"error": "Invalid container name"}, 400)
            return
        h = _container_vm_host(cfg, host)
        if not h:
            self._json_response({"error": f"Host not found: {host}"}, 404)
            return
        safe_name = shlex.quote(name)
        r = ssh_single(
            host=h.ip,
            command=f"docker {action} {safe_name} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=5,
            command_timeout=30,
            htype=h.htype or "docker",
            use_sudo=False,
            cfg=cfg,
        )
        self._json_response(
            {
                "ok": r.returncode == 0,
                "output": r.stdout.strip() if r and r.stdout else "",
                "error": r.stderr.strip() if r and r.returncode != 0 else "",
                "returncode": r.returncode if r else 1,
                "action": action,
                "container": name,
                "host": host,
                "resolved_host": h.label,
                "ip": h.ip,
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
            self._json_response({"error": "host and name required"}, 400)
            return
        import re as _re

        if not _re.match(r"^[a-zA-Z0-9._-]+$", name):
            self._json_response({"error": "Invalid container name"}, 400)
            return
        h = _container_vm_host(cfg, host)
        if not h:
            self._json_response({"error": f"Host not found: {host}"}, 404)
            return
        safe_name = shlex.quote(name)
        r = ssh_single(
            host=h.ip,
            command=f"docker logs --tail {lines} {safe_name} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=5,
            command_timeout=15,
            htype=h.htype or "docker",
            use_sudo=False,
            cfg=cfg,
        )
        self._json_response(
            {
                "ok": r.returncode == 0,
                "output": r.stdout if r and r.returncode == 0 else "",
                "error": r.stderr.strip() if r and r.returncode != 0 else "",
                "returncode": r.returncode if r else 1,
                "container": name,
                "host": host,
                "resolved_host": h.label,
                "ip": h.ip,
                "lines": lines,
            }
        )

    def _serve_fleet_connectivity(self):
        """Check SSH connectivity to all fleet hosts.

        Uses the dashboard health cache when available so connectivity matches
        the main fleet view and device-specific auth model. Falls back to a
        live device-aware probe only before the first health cache exists.
        """
        cfg = load_config()
        from freq.core.ssh import run as ssh_single

        with _bg_lock:
            health = _bg_cache.get("health")
        health_by_ip = {}
        if isinstance(health, dict):
            for row in health.get("hosts", []) or []:
                if isinstance(row, dict) and row.get("ip"):
                    health_by_ip[row["ip"]] = row

        hosts = []
        for h in cfg.hosts:
            htype = getattr(h, "htype", "linux")
            cached = health_by_ip.get(h.ip)
            if cached:
                state = cached.get("state") or cached.get("status")
                reachable = state not in {STATE_AUTH_FAILED, STATE_UNREACHABLE}
                hosts.append(
                    {
                        "label": h.label,
                        "ip": h.ip,
                        "type": htype,
                        "reachable": reachable,
                        "user": cached.get("state") or cached.get("status") or "",
                        "state": state,
                        "reason": cached.get("reason", ""),
                        "source": "health_cache",
                    }
                )
                continue

            legacy_types = {"idrac", "switch"}
            cmd = "whoami"
            key = cfg.ssh_key_path
            user = cfg.ssh_service_account
            local_user = None
            password_file = None
            sudo_password_file = False
            if htype in ("pfsense", "idrac", "switch", "truenas"):
                auth = resolve_staged_device_ssh_auth(cfg, htype)
                key = auth.get("key_path") or ((cfg.ssh_rsa_key_path or cfg.ssh_key_path) if htype in legacy_types else cfg.ssh_key_path)
                user = auth.get("user") or None
                local_user = auth.get("local_user") or None
                password_file = auth.get("password_file") or None
                sudo_password_file = auth.get("sudo_password_file", False)
                if htype == "pfsense":
                    cmd = "echo OK"
                elif htype == "idrac":
                    cmd = "racadm getversion"
                elif htype == "switch":
                    cmd = "show version | include uptime"

            try:
                r = ssh_single(
                    host=h.ip,
                    command=cmd,
                    key_path=key,
                    user=user,
                    local_user=local_user,
                    password_file=password_file,
                    sudo_password_file=sudo_password_file,
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
            self._json_response({"error": "target required"}, 400)
            return
        from freq.core.ssh import run as ssh_single
        from freq.core.resolve import by_target
        from freq.core.types import Host

        h = by_target(cfg.hosts, target)
        vm_match = re.match(r"^vm:(\d+)$", str(target or "").strip(), re.I)
        if not h and vm_match:
            vmid = int(vm_match.group(1))
            for known in cfg.hosts:
                if int(getattr(known, "vmid", 0) or 0) == vmid:
                    h = known
                    break
            if not h:
                try:
                    from freq.api.terminal import (
                        _find_live_vm_node_ip,
                        _guest_agent_network_json,
                        _extract_guest_ipv4,
                    )

                    node_ip, node_name = _find_live_vm_node_ip(cfg, vmid, "")
                    if node_ip:
                        raw, ok, _method = _guest_agent_network_json(cfg, vmid, node_ip, node_name)
                        if ok:
                            guest_ip = _extract_guest_ipv4(raw)
                            if guest_ip:
                                h = Host(ip=guest_ip, label=f"vm-{vmid}", htype="linux", groups="ad-hoc-vm", vmid=vmid)
                except Exception as e:
                    logger.warn(f"host diagnostic VM target resolve failed for VMID {vmid}: {e}")
        if not h and re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", target):
            h = Host(ip=target, label=target, htype="linux", groups="ad-hoc-vm")
        if not h:
            self._json_response({"error": f"Host not found: {target}"}, 404)
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

    def _send_security_headers(self):
        """Centralized security headers for all response types."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        # M-BLUETEAM-SECURITY-HARDENING-20260413AJ: lock down the
        # remaining browser capability surface.
        # Permissions-Policy: explicitly deny all browser features the
        # dashboard never uses. Kills camera/mic/geoloc/usb surface so
        # an XSS landing can't pivot to hardware access.
        self.send_header("Permissions-Policy",
                         "geolocation=(), microphone=(), camera=(), "
                         "usb=(), payment=(), accelerometer=(), "
                         "gyroscope=(), magnetometer=(), interest-cohort=()")
        # HSTS: only send when the current request arrived over TLS.
        # Setting HSTS on a plain-http response is a spec violation and
        # browsers ignore it; sending it unconditionally would also trap
        # HTTP-only deploys in an unrecoverable redirect loop via
        # browser pre-load. Short max-age (1 year) without preload.
        try:
            import ssl as _ssl
            if isinstance(getattr(self, "request", None), _ssl.SSLSocket):
                self.send_header("Strict-Transport-Security",
                                 "max-age=31536000; includeSubDomains")
        except Exception:
            pass
        # Web UI is self-contained: xterm is vendored under /static/vendor/xterm,
        # fonts use platform stacks only, no public CDN or font host references.
        #
        # Honest limits on 'unsafe-inline' and the remaining inline
        # execution/style paths:
        #   script-src: ZERO inline event handlers, ZERO inline <script> blocks,
        #     ZERO javascript: URLs (closed by R-WEB-INLINE-CSP-CLEANUP-20260413O).
        #     'unsafe-inline' is dropped from script-src.
        #   style-src: the shipped dashboard still uses runtime
        #     element.style writes and generated style="..." fragments
        #     across progress bars, modals, health colors, terminal layout,
        #     operator cards, and the 44 remaining inline style attributes
        #     in app.html. A previous contract tried to keep
        #     style-src hash-only and rely on style-src-attr for runtime
        #     property writes. Chromium browser smoke proved that was false:
        #     those runtime writes are enforced against style-src and are
        #     blocked unless style-src itself allows inline styles. Until
        #     the UI is fully migrated to classes/CSS variables, the truthful
        #     policy is style-src 'self' 'unsafe-inline'. Script execution
        #     remains locked down separately under script-src 'self'.
        #
        # No host names appear below. An air-gapped dashboard MUST NOT fetch any
        # asset off-box — that's what R-WEB-EXTERNAL-ASSET-CONTRACT-20260413L
        # closed. This CSP is the policy enforcement.
        style_src = "style-src 'self' 'unsafe-inline'"
        # M-BLUETEAM-SECURITY-HARDENING-20260413AJ:
        #   frame-ancestors 'none' — clickjacking defense-in-depth. The
        #     legacy X-Frame-Options: DENY header above covers older
        #     browsers; frame-ancestors is the CSP-level equivalent and
        #     is the spec-preferred directive for modern UAs.
        #   base-uri 'none' — prevent an XSS from injecting a <base>
        #     tag that rewrites all relative URLs to an attacker origin.
        #   form-action 'self' — POST form submissions can only target
        #     the dashboard's own origin, even though every real form
        #     uses fetch(). Belt on braces.
        #   object-src 'none' — no Flash/Silverlight/ActiveX/plugins.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; "
                         "script-src 'self'; "
                         f"{style_src}; "
                         "img-src 'self' data:; "
                         "connect-src 'self'; "
                         "font-src 'self'; "
                         "frame-ancestors 'none'; "
                         "base-uri 'none'; "
                         "form-action 'self'; "
                         "object-src 'none'")

    def _json_response(self, data, status=200):
        """Send a JSON response."""
        if isinstance(data, dict) and "error" in data and "request_id" not in data:
            data = dict(data)
            data["request_id"] = getattr(self, "_request_id", "")
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        try:
            from freq.api.auth import maybe_send_session_refresh_cookie

            maybe_send_session_refresh_cookie(self)
        except Exception:
            pass
        # M-BLUETEAM-SECURITY-HARDENING-20260413AJ: reflected-origin
        # Access-Control-Allow-Origin removed. The dashboard is same-
        # origin by design — no cross-origin caller should be able to
        # read these responses. Echoing the Origin header back was a
        # classic CORS-misconfiguration antipattern that let any
        # attacker page enumerate fleet state cross-origin (credentials
        # were never forwarded because Allow-Credentials wasn't set,
        # but the data read was still exposed). Same-origin requests
        # don't need ACAO at all, so the header is dropped entirely.
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
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


def _is_container_runtime() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8", errors="ignore") as f:
            return any(token in f.read() for token in ("docker", "kubepods", "containerd"))
    except OSError:
        return False


def _port_is_listening(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        sock.close()


def _start_embedded_watchdog_if_needed(cfg) -> None:
    if not getattr(cfg, "watchdog_enabled", False):
        return
    if not _is_container_runtime() and os.path.isdir("/run/systemd/system"):
        return
    wd_port = int(getattr(cfg, "watchdog_port", 9900) or 9900)
    if _port_is_listening(wd_port):
        return

    def _run_watchdog():
        try:
            from freq.modules.watchdog import run_daemon

            status_dir = os.path.join(cfg.data_dir, "watchdog")
            run_daemon(
                cfg,
                interval=15,
                status_file=os.path.join(status_dir, "status.json"),
                state_file=os.path.join(status_dir, "state.json"),
            )
        except Exception as e:
            logger.warning(f"embedded_watchdog_stopped: {e}")

    threading.Thread(target=_run_watchdog, daemon=True, name="freq-embedded-watchdog").start()
    logger.info("embedded_watchdog_started", port=wd_port)


def cmd_serve(cfg, pack, args) -> int:
    """Start the FREQ web dashboard."""
    import signal

    port = getattr(args, "port", None) or cfg.dashboard_port or 8888
    print(f"\n  \033[38;5;93mPVE FREQ → Dashboard\033[0m")
    print(f"  Starting on port {port}...\n")
    start_background_cache()
    _start_embedded_watchdog_if_needed(cfg)

    httpd = ThreadedHTTPServer(("0.0.0.0", port), FreqHandler)

    # SIGTERM handler — systemctl restart sends SIGTERM, not SIGINT.
    # Without this, serve_forever() is killed abruptly and the socket
    # can linger in a broken state, causing ConnectionResetError on the
    # next process's requests.
    # Note: shutdown() blocks waiting for serve_forever() to acknowledge,
    # but serve_forever() is paused while the signal handler runs.
    # Use a thread to avoid deadlock.
    def _sigterm_handler(signum, frame):
        logger.info("dashboard_stop", reason="SIGTERM")
        _shutdown_flag.set()  # Signal background loops to stop
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _sigterm_handler)

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
    # Users-without-dashboard-password hint.
    # R-SECURITY-TRUST-AUDIT-20260413P F1 removed the trust-on-first-use
    # silent-seed path from /api/auth/login, so a user listed in users.conf
    # with no vault entry can NO LONGER set their password by simply logging
    # in. The pre-F1 banner line that claimed login would seed the password
    # was a lie after F1 landed — the auth handler now returns 401 for
    # empty stored hashes. Point operators at the break-glass recovery
    # CLI that actually works:
    #   sudo freq user dashboard-passwd <user>            (interactive)
    #   sudo freq user dashboard-passwd <user> --file PW  (non-interactive)
    # Landed under R-RESILIENCE-INIT-RECOVERY-20260413S.
    try:
        from freq.modules.users import _load_users
        users = _load_users(cfg)
        if users:
            from freq.modules.vault import vault_get
            no_pw = [u["username"] for u in users if not vault_get(cfg, "auth", f"password_{u['username']}")]
            if no_pw:
                print(
                    f"  \033[38;5;220m⚠\033[0m Users without dashboard password: "
                    f"{', '.join(no_pw)}"
                )
                print(
                    f"    \033[38;5;245mRecover with: "
                    f"sudo freq user dashboard-passwd <user> [--file PATH]\033[0m"
                )
    except Exception:
        pass
    print(f"  \033[38;5;245mPress Ctrl+C to stop\033[0m\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  \033[38;5;220mDashboard stopped.\033[0m")
    finally:
        httpd.server_close()
        # Kill SSH ControlMaster mux sockets left by background probes.
        # These are forked processes that outlive daemon threads and prevent
        # systemd from cleanly stopping the service.
        _cleanup_ssh_mux(cfg)
        logger.info("dashboard_stopped")
    return 0
