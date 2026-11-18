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
import queue
import re
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import uuid
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from freq.api import standard_observe as _standard_observe_http
from freq.core import audit, host_identity, truenas_api
from freq.core import http_query as _http_query
from freq.core import log as logger
from freq.core import resolve as res
from freq.core.config import (
    _resolve_container_vm_ip,
    _write_containers_toml,  # noqa: F401 - retained compatibility re-export
    load_config,
    load_toml,
    save_hosts_toml,
)
from freq.core.device_credentials import resolve_staged_device_ssh_auth
from freq.core.first_admin_claim import (
    ClaimStateError,
    locked_first_admin_claim,
    prepare_first_admin_claim,
)
from freq.core.health_state import (
    STATE_AUTH_FAILED,
    STATE_DEGRADED,
    STATE_LIVE,
    STATE_RECOVERING,
    STATE_STALE,
    STATE_UNREACHABLE,
    aggregate_probe_state,
    classify_probe_failure,
    entry_base,
    mark_stale,
    parse_metric_percentage,
)
from freq.core.host_scope import managed_probe_hosts
from freq.core.setup_contract import (
    SetupContractError,
    build_setup_contract,
    clear_setup_contract,
    contract_credential_keys,
    contract_payload,
    credential_presence,
    credential_storage_value,
    credential_vault_key,
    load_setup_contract,
    record_credential_request,
    save_setup_contract,
    validate_credential_request,
)
from freq.core.setup_discovery import (
    DiscoveryInputError,
    run_setup_discovery,
    validate_discovery_request,
)
from freq.core.setup_state import (
    SCHEMA as ZERO_STATE_WEB_SCHEMA,
)
from freq.core.setup_state import (
    _project_init_status,
    clear_setup_state,
    ensure_setup_state,
    load_setup_state,
    setup_state_path,  # noqa: F401 - retained compatibility re-export
    touch_setup_state,
    update_setup_state,
)
from freq.core.ssh import run as ssh_single
from freq.core.validate import (
    label as valid_label,
)
from freq.jarvis.notify import _notification_test_results
from freq.jarvis.notify import notify as jarvis_notify
from freq.jarvis.risk import _load_kill_chain
from freq.modules import pve as _pve_module
from freq.modules.pve import _find_reachable_node, _pve_cmd
from freq.modules.users import _load_users, _save_users_error
from freq.modules.vault import vault_delete, vault_get, vault_init, vault_list, vault_set, vault_update
from freq.services import container_action as _container_action
from freq.services import container_logs as _container_logs
from freq.services import dashboard_doctor as _dashboard_doctor
from freq.services import dashboard_events as _dashboard_events
from freq.services import dashboard_state as _dashboard_state
from freq.services import deployment_history as _deployment_history
from freq.services import device_command as _device_command
from freq.services import dns_lookup as _dns_lookup
from freq.services import fleet_connectivity as _fleet_connectivity
from freq.services import host_diagnostic as _host_diagnostic
from freq.services import idrac_session as _idrac_session
from freq.services import lab_tool_proxy as _lab_tool_proxy
from freq.services import media_activity as _media_activity
from freq.services import portscan as _portscan
from freq.services import pve_discovery as _pve_discovery
from freq.services import pve_inventory as _pve_inventory
from freq.services import pve_tags as _pve_tags
from freq.services import pve_transport as _pve_transport
from freq.services import release_update as _release_update
from freq.services import setup_handoff as _setup_handoff
from freq.services import setup_health as _setup_health
from freq.services import setup_inputs as _setup_inputs
from freq.services import setup_keys as _setup_keys
from freq.services import setup_progress as _setup_progress
from freq.services import ssh_mux_cleanup as _ssh_mux_cleanup
from freq.services import standard_qemu_asset_policy as _standard_asset_policy
from freq.services import standard_qemu_assets as _standard_assets
from freq.services import vm_visibility as _vm_visibility
from freq.services import watch_control as _watch_control
from freq.services.cert_renewal import (
    start_cert_renewal_scheduler_if_needed as _start_cert_renewal_scheduler_if_needed,
)


def _load_users(cfg):
    """Resolve the user-registry reader at call time for startup truth."""
    from freq.modules import users as users_module

    return users_module._load_users(cfg)

_SERVER_START_TIME = _dashboard_state.server_start_time
_parse_query = _http_query.parse_query
_parse_query_flat = _http_query.parse_query_flat
_parse_pct = parse_metric_percentage
_activity_feed = _dashboard_state.activity_feed
_activity_lock = _dashboard_state.activity_lock
_bg_cache = _dashboard_state.background_cache
_bg_cache_errors = _dashboard_state.background_cache_errors
_bg_cache_from_disk = _dashboard_state.background_cache_from_disk
_bg_cache_ts = _dashboard_state.background_cache_timestamps
_bg_lock = _dashboard_state.background_cache_lock
_sse_clients = _dashboard_events._sse_clients
_sse_lock = _dashboard_events._sse_lock
_sse_subscribe = _dashboard_events._sse_subscribe
_sse_unsubscribe = _dashboard_events._sse_unsubscribe
_sse_broadcast = _dashboard_events._sse_broadcast
_activity_add = _dashboard_events._activity_add
IDRAC_SESSION_LOCK = _idrac_session.IDRAC_SESSION_LOCK
IDRAC_SESSION_GAP_SECONDS = _idrac_session.IDRAC_SESSION_GAP_SECONDS
_run_idrac_session = _idrac_session._run_idrac_session
_run_idrac_subprocess = _idrac_session._run_idrac_subprocess
_redact_device_command_output = _device_command.redact_device_command_output
_pfsense_execution_runtime = _device_command.PfSenseExecutionRuntime(
    resolve_auth=lambda cfg, device_type: resolve_staged_device_ssh_auth(cfg, device_type),
    ssh_single=lambda **kwargs: ssh_single(cfg=kwargs.pop("cfg"), **kwargs),
    redact_output=lambda output: _redact_device_command_output(output),
)
_resolve_pfsense_execution = partial(
    _device_command.resolve_pfsense_execution,
    runtime=_pfsense_execution_runtime,
)
_operator_physical_display_label = host_identity.operator_physical_display_label
_media_default_port = _media_activity.media_default_port
_media_container_port = _media_activity.media_container_port
_parse_sab_downloads = _media_activity.parse_sab_downloads
_parse_qbit_downloads = _media_activity.parse_qbit_downloads
_media_ssh_user_from_key = _media_activity.media_ssh_user_from_key
_media_ssh_single = _media_activity.media_ssh_single
_docker_exec_json = _media_activity.docker_exec_json
_container_vm_host = res.container_vm_host

_pve_metrics_runtime = _pve_transport.PveMetricsRuntime(
    load_config=lambda: load_config(),
    pve_api_call=lambda *args, **kwargs: _pve_module._pve_api_call(*args, **kwargs),
    now=lambda: time.time(),
)
_resolve_pve_metrics = partial(
    _pve_transport.resolve_pve_metrics,
    runtime=_pve_metrics_runtime,
)

_pve_rrd_runtime = _pve_transport.PveRrdRuntime(
    load_config=lambda: load_config(),
    pve_api_call=lambda *args, **kwargs: _pve_module._pve_api_call(*args, **kwargs),
    now=lambda: time.time(),
)
_resolve_pve_rrd = partial(
    _pve_transport.resolve_pve_rrd,
    runtime=_pve_rrd_runtime,
)

IDRAC_READ_CONNECT_TIMEOUT = 10
IDRAC_READ_COMMAND_TIMEOUT = 30


def _resolve_pfsense_target(cfg, target=""):
    """Resolve a pfSense/opnsense target by label/key/IP.

    Default remains the core firewall. Lab firewalls must be selected
    explicitly so a lab card never queries production by accident.
    """
    from freq.core.types import PhysicalDevice

    def _first_description_ip(text):
        for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", str(text or "")):
            parts = ip.split(".")
            try:
                if all(0 <= int(part) <= 255 for part in parts):
                    return ip
            except ValueError:
                continue
        return ""

    def _inventory_target():
        if not target_l:
            return None
        inv_path = os.path.join(getattr(cfg, "conf_dir", ""), "pve-inventory.toml")
        inv = load_toml(inv_path)
        resources = inv.get("resource", []) if isinstance(inv, dict) else []
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            name = str(resource.get("name") or "")
            vmid = str(resource.get("vmid") or "")
            node = str(resource.get("node") or "")
            tags = str(resource.get("tags") or "")
            identity = " ".join((name, vmid, node, tags)).lower()
            if "pfsense" not in identity and "opnsense" not in identity:
                continue
            description = str(resource.get("description") or "")
            fb = getattr(cfg, "fleet_boundaries", None)
            node_info = getattr(fb, "pve_nodes", {}).get(node) if fb else None
            node_ip = getattr(node_info, "ip", "") if node_info else ""
            if node_ip and vmid:
                try:
                    from freq.modules.pve import _pve_call

                    vm_cfg, ok = _pve_call(
                        cfg,
                        node_ip,
                        api_endpoint=f"/nodes/{node}/qemu/{vmid}/config",
                        ssh_command=f"pvesh get /nodes/{node}/qemu/{vmid}/config --output-format json",
                        timeout=10,
                    )
                    if ok and isinstance(vm_cfg, dict):
                        description = str(vm_cfg.get("description") or description)
                except Exception:
                    pass
            ip = _first_description_ip(description)
            if not ip:
                continue
            if target_l not in " ".join((identity, description.lower(), ip)):
                continue
            return PhysicalDevice(
                key=name or f"vm-{vmid}",
                ip=ip,
                label=name or f"vm-{vmid}",
                device_type="opnsense" if "opnsense" in identity else "pfsense",
                tier="probe",
                detail="Firewall",
                groups="lab" if "lab" in identity else "",
                scope="lab" if "lab" in identity else "core",
            )
        return None

    target_l = str(target or "").strip().lower()
    devices = []
    for key, dev in getattr(getattr(cfg, "fleet_boundaries", None), "physical", {}).items():
        if getattr(dev, "device_type", "") in ("pfsense", "opnsense"):
            if not getattr(dev, "key", ""):
                dev.key = key
            devices.append(dev)

    for host in getattr(cfg, "hosts", []):
        host_type = (getattr(host, "htype", "") or getattr(host, "type", "") or "").lower()
        label = getattr(host, "label", "") or getattr(host, "hostname", "")
        identity = " ".join(
            str(x or "")
            for x in (
                label,
                getattr(host, "display_name", ""),
                getattr(host, "hostname", ""),
                getattr(host, "ip", ""),
                getattr(host, "vmid", ""),
                getattr(host, "groups", ""),
                " ".join(getattr(host, "all_ips", []) or []),
            )
        ).lower()
        is_firewall = host_type in ("pfsense", "opnsense") or "pfsense" in identity or "opnsense" in identity
        if not is_firewall or not getattr(host, "ip", ""):
            continue
        devices.append(
            PhysicalDevice(
                key=label or getattr(host, "ip", ""),
                ip=getattr(host, "ip", ""),
                label=getattr(host, "display_name", "") or label or getattr(host, "ip", ""),
                device_type="opnsense" if "opnsense" in identity else "pfsense",
                tier="probe",
                detail="Firewall",
                groups=getattr(host, "groups", ""),
                scope="lab" if "lab" in identity else "core",
                hostname=getattr(host, "hostname", ""),
                display_name=getattr(host, "display_name", ""),
            )
        )

    if target_l:
        for dev in devices:
            hay = " ".join(
                str(x or "")
                for x in (
                    getattr(dev, "key", ""),
                    getattr(dev, "label", ""),
                    getattr(dev, "ip", ""),
                    getattr(dev, "display_name", ""),
                )
            ).lower()
            if target_l in hay:
                return dev
        inv_target = _inventory_target()
        if inv_target:
            return inv_target
        return None
    core = [dev for dev in devices if getattr(dev, "scope", "core") != "lab"]
    if core:
        return core[0]
    if getattr(cfg, "pfsense_ip", ""):
        return PhysicalDevice(
            key="pfsense",
            ip=cfg.pfsense_ip,
            label="firewall",
            device_type="pfsense",
            scope="core",
        )
    return None


def _http_cleanup_first(first, later):
    """Select actual Control, then Memory, then ordinary failure after cleanup.

    This original-module function has no lazy helper import or callback. Keep
    independent native close attempts ahead of failure classification.
    """
    if later is None:
        return first
    if first is None or issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception)
            or not issubclass(type(first), MemoryError)
            and issubclass(type(later), MemoryError)):
        return later
    return first


_STANDARD_STATIC_PATHS = tuple(
    row[0].split("?", 1)[0] for row in _standard_asset_policy._ASSETS[1:]
)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server — won't block on slow API calls."""

    daemon_threads = True
    allow_reuse_address = True
    allow_reuse_port = False

    def close_request(self, request):
        """Independently close the original transport, then record its outcome."""
        # The module is bound before any server construction. Live close must
        # not import helpers. Lookup/publication failure cannot skip close.
        entry, should_close, prior = None, True, None
        begin_failure = close_failure = None
        try:
            entry, should_close = _standard_observe_http._begin_http_close(self, request)
            if entry is not None:
                prior = entry.failure
        except BaseException as failure:
            begin_failure = failure
        if not should_close:
            return
        try:
            super().close_request(request)
        except BaseException as failure:
            close_failure = failure
        # Both raw failures are saved before classification or publication.
        first = _http_cleanup_first(begin_failure, close_failure)
        if first is not None:
            first = _http_cleanup_first(prior, first)
        try:
            first = _standard_observe_http._end_http_close(entry, first)
        except BaseException as failure:
            first = _http_cleanup_first(_http_cleanup_first(prior, first), failure)
        if first is not None:
            raise first from None

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
SNMP_IDENTITY_CACHE_TTL = 300
_snmp_identity_cache = {}
_snmp_identity_cache_ts = {}
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
DEFAULT_LOG_LINES = 50


# ── BACKGROUND CACHE ENGINE ──────────────────────────────────────────────
# Probes run in a background thread on a loop. API endpoints always serve
# from memory cache (instant). On startup, stale data loads from disk so
# the very first request is never cold.

def _get_cache_dir():
    """Resolve cache directory from config at runtime — not from __file__.
    Using __file__ breaks pip-installed packages where site-packages is read-only."""
    try:
        cfg = load_config()
        return os.path.join(cfg.data_dir, "cache")
    except MemoryError:
        raise
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")


CACHE_DIR = None  # Set at runtime by _init_cache_dir()


def _init_cache_dir():
    global CACHE_DIR
    CACHE_DIR = _get_cache_dir()


UPDATE_CHECK_INTERVAL = 6 * 3600  # 6 hours
HOSTS_SYNC_INTERVAL = 3600  # 1 hour — keep hosts.toml in sync with PVE
NODE_DISCOVERY_INTERVAL = _pve_discovery.NODE_DISCOVERY_INTERVAL
VM_TAGS_INTERVAL = _pve_tags.VM_TAGS_INTERVAL
_setup_lock = threading.Lock()
_setup_discovery_lock = threading.Lock()
_setup_discovery_job = None
_setup_init_lock = threading.Lock()
_setup_init_job = None
_shutdown_flag = threading.Event()  # Set on SIGTERM to stop background loops


class _UnsupportedJSONMediaType(ValueError):
    pass


def _require_json_media_type(handler) -> None:
    raw = str(handler.headers.get("Content-Type", "") or "")
    media_type = raw.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise _UnsupportedJSONMediaType("Content-Type must be application/json")


class _FirstAdminClaimRateLimiter:
    """Volatile invalid-claim buckets; durable attacker state is forbidden."""

    _WINDOW_SECONDS = 300.0
    _CLIENT_LIMIT = 5
    _GLOBAL_LIMIT = 50

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._clients = {}
        self._global = []

    def _prune_locked(self, now):
        cutoff = now - self._WINDOW_SECONDS
        self._global = [stamp for stamp in self._global if stamp > cutoff]
        for client in list(self._clients):
            kept = [stamp for stamp in self._clients[client] if stamp > cutoff]
            if kept:
                self._clients[client] = kept
            else:
                del self._clients[client]

    def record_invalid(self, client):
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            self._clients.setdefault(client, []).append(now)
            self._global.append(now)

    def client_allowed(self, client):
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            return len(self._clients.get(client, ())) < self._CLIENT_LIMIT

    def global_limited(self):
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            return len(self._global) >= self._GLOBAL_LIMIT

    def should_compare(self, client):
        return self.client_allowed(client)

    def failure_status(self, _client):
        return 429 if (not self.client_allowed(_client) or self.global_limited()) else 403

    def clear_client(self, client):
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            self._clients.pop(client, None)


_first_admin_claim_limiter = _FirstAdminClaimRateLimiter()


def _create_admin_error_template(status, code, message, *, field="", retryable=False):
    return (status, code, message, field, bool(retryable))


_CREATE_ADMIN_ERROR_TEMPLATES = {
    "method_not_allowed": _create_admin_error_template(405, "method_not_allowed", "Use POST with a JSON body."),
    "https_required": _create_admin_error_template(
        403,
        "https_required",
        "First-operator setup requires the bootstrap HTTPS listener.",
    ),
    "unsupported_media_type": _create_admin_error_template(
        400,
        "unsupported_media_type",
        "Send Content-Type: application/json.",
    ),
    "claim_secret_required": _create_admin_error_template(
        400,
        "claim_secret_required",
        "The first-boot claim is required.",
        field="claim_secret",
    ),
    "required_field:schema": _create_admin_error_template(
        400, "required_field", "Required setup field is missing: schema.", field="schema"
    ),
    "required_field:username": _create_admin_error_template(
        400, "required_field", "Required setup field is missing: username.", field="username"
    ),
    "required_field:password": _create_admin_error_template(
        400, "required_field", "Required setup field is missing: password.", field="password"
    ),
    "required_field:client_request_id": _create_admin_error_template(
        400,
        "required_field",
        "Required setup field is missing: client_request_id.",
        field="client_request_id",
    ),
    "manual_contract_not_allowed": _create_admin_error_template(
        400,
        "manual_contract_not_allowed",
        "Server-side paths and manual contracts are not accepted by browser setup.",
    ),
    "path_input_not_allowed": _create_admin_error_template(
        400,
        "path_input_not_allowed",
        "Server-side paths and manual contracts are not accepted by browser setup.",
    ),
    "unsupported_field": _create_admin_error_template(
        400, "unsupported_field", "Unsupported setup field."
    ),
    "invalid_field:schema": _create_admin_error_template(
        400, "invalid_field", "Setup field must be a string: schema.", field="schema"
    ),
    "invalid_field:username": _create_admin_error_template(
        400, "invalid_field", "Setup field must be a string: username.", field="username"
    ),
    "invalid_field:password": _create_admin_error_template(
        400, "invalid_field", "Setup field must be a string: password.", field="password"
    ),
    "invalid_field:client_request_id": _create_admin_error_template(
        400,
        "invalid_field",
        "Setup field must be a string: client_request_id.",
        field="client_request_id",
    ),
    "unsupported_schema": _create_admin_error_template(
        400, "unsupported_schema", "Unsupported setup schema.", field="schema"
    ),
    "invalid_json": _create_admin_error_template(400, "invalid_json", "Invalid setup admin request."),
    "claim_rate_limited": _create_admin_error_template(
        429,
        "claim_rate_limited",
        "Wait for the current rate window, then retry.",
        retryable=True,
    ),
    "setup_busy": _create_admin_error_template(
        409, "setup_busy", "Another setup mutation is in progress.", retryable=True
    ),
    "claim_state_unavailable": _create_admin_error_template(
        503,
        "claim_state_unavailable",
        "First-admin setup is temporarily unavailable; retry.",
        retryable=True,
    ),
    "setup_closed": _create_admin_error_template(403, "setup_closed", "Setup is complete; sign in to resume."),
    "operator_exists": _create_admin_error_template(
        409,
        "operator_exists",
        "The first operator already exists; sign in to resume setup.",
    ),
    "claim_consumed": _create_admin_error_template(
        409,
        "claim_consumed",
        "Follow the local first-admin claim reset procedure in the zero-state runbook.",
    ),
    "claim_secret_invalid": _create_admin_error_template(
        403,
        "claim_secret_invalid",
        "Use the newest claim for the current service; if it was lost, follow the local first-admin claim reset procedure in the zero-state runbook.",
        field="claim_secret",
        retryable=True,
    ),
    "invalid_username": _create_admin_error_template(
        400,
        "invalid_username",
        "Username must be lowercase and contain only letters, digits, hyphens, or underscores.",
        field="username",
    ),
    "invalid_password": _create_admin_error_template(
        400, "invalid_password", "Password must be at least 8 characters.", field="password"
    ),
    "operator_password_store_failed": _create_admin_error_template(
        500, "operator_password_store_failed", "Failed to store password."
    ),
    "setup_state_write_failed": _create_admin_error_template(
        500, "setup_state_write_failed", "Failed to create setup state."
    ),
    "operator_write_failed": _create_admin_error_template(
        500, "operator_write_failed", "Failed to save user."
    ),
    "session_create_failed": _create_admin_error_template(
        500, "session_create_failed", "Setup admin session creation failed."
    ),
}


def _create_admin_error(handler, template_id):
    """Project one allowlisted create-admin error without caller-derived data."""
    template = _CREATE_ADMIN_ERROR_TEMPLATES.get(template_id)
    if template is None:
        logger.critical("first_admin_claim_response_projection_blocked")
        template = (
            500,
            "response_projection_blocked",
            "The setup response could not be projected safely.",
            "",
            True,
        )
    status, code, message, field, retryable = template
    error = {"code": code, "message": message, "retryable": retryable}
    if field:
        error["field"] = field
    handler._json_response(
        {"ok": False, "schema": ZERO_STATE_WEB_SCHEMA, "error": error},
        status,
    )

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
    """Persist through a temporary file and replacement for the next start.

    The existing file mode 0644 remains for operator CLI compatibility.
    This source boundary does not qualify cache payload privacy.
    """
    global CACHE_DIR
    from freq.core.read_source_epoch import retire_process_reads, _first

    retire_process_reads()
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
        except BaseException as error:
            failure = error
            try:
                os.unlink(tmp)
            except OSError:
                pass
            except BaseException as cleanup_error:
                if (not issubclass(type(error), Exception)
                        or issubclass(type(error), MemoryError)
                        or not issubclass(type(cleanup_error), Exception)
                        or issubclass(type(cleanup_error), MemoryError)):
                    failure = _first(error, cleanup_error)
                else:
                    # Preserve ordinary non-OSError cleanup replacement.
                    failure = cleanup_error
            raise failure from None
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
    except MemoryError:
        raise
    except Exception as e:
        logger.error(f"bg_probe_health: failed to load config: {e}")
        raise  # Preserve failure for the health loop; it records and contains it.
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
            def _run_idrac_health_probe():
                return ssh_single(
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

            r = _run_idrac_session(_run_idrac_health_probe)
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
    for h in managed_probe_hosts(cfg):
        # Skip hosts in circuit-breaker backoff
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
        from freq.jarvis.capacity import save_snapshot, should_snapshot

        if should_snapshot(cfg.data_dir):
            save_snapshot(cfg.data_dir, result)
    except MemoryError:
        raise
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

    def _generic_physical_label(label, dtype):
        label = str(label or "").strip().lower()
        dtype = str(dtype or "").strip().lower()
        if not label:
            return True
        if label == dtype:
            return True
        if re.match(r"^(bmc|idrac|ilo|ipmi)[-_]?\d+$", label):
            return True
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", label):
            return True
        return False

    def _identity_label(identity, dtype):
        raw = (
            identity.get("sys_name")
            or identity.get("physical_name")
            or identity.get("serial")
            or ""
        )
        raw = str(raw).strip()
        if not raw:
            return ""
        label = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-_.").lower()
        if not label:
            return ""
        if dtype in {"idrac", "bmc", "ilo", "ipmi"} and not label.startswith(("idrac", "ilo", "bmc", "ipmi")):
            label = f"{dtype}-{label}"
        return label[:64]

    def _snmp_identity_for_physical(dev, reachable):
        if not reachable:
            return {}
        dtype = (getattr(dev, "device_type", "") or "").lower()
        try:
            from freq.modules.snmp import _get_community, _get_snmp_auth, get_snmp_identity

            auth = _get_snmp_auth(cfg, include_secret=True)
            # Without configured SNMPv3 credentials, only try BMC-style
            # v2c adoption probes. Broad public-community probing against
            # every physical device would slow the fleet overview and create
            # misleading "not configured" noise.
            if not auth.get("user") and dtype not in {"idrac", "bmc", "ilo", "ipmi"}:
                return {}
            cache_key = f"{dev.ip}|{bool(auth.get('user'))}"
            now = time.monotonic()
            cached = _snmp_identity_cache.get(cache_key)
            if cached is not None and now - _snmp_identity_cache_ts.get(cache_key, 0) < SNMP_IDENTITY_CACHE_TTL:
                return cached
            ident = get_snmp_identity(
                dev.ip,
                community=_get_community(cfg),
                auth=auth if auth.get("user") else {},
                timeout=2,
            )
            if not ident.get("reachable"):
                ident = {}
            _snmp_identity_cache[cache_key] = ident
            _snmp_identity_cache_ts[cache_key] = now
            return ident
        except Exception as e:
            logger.warn(f"snmp identity probe failed for {getattr(dev, 'label', dev.ip)}: {e}")
            return {}

    # Physical devices — device-appropriate reachability in parallel.
    physical = []

    def _ping_device(dev):
        reachable = _physical_reachable(dev)
        identity = _snmp_identity_for_physical(dev, reachable)
        dtype = getattr(dev, "device_type", "")
        display_name = getattr(dev, "display_name", "") or ""
        identity_label = _identity_label(identity, dtype)
        display_label = _operator_physical_display_label(cfg, dev, identity_label)
        item = {
            "key": dev.key,
            "ip": dev.ip,
            "label": dev.label,
            "raw_label": dev.label,
            "display_name": display_name,
            "display_label": display_label,
            "identity_label": identity_label,
            "type": dev.device_type,
            "tier": dev.tier,
            "detail": dev.detail,
            "groups": dev.groups,
            "scope": dev.scope,
            "reachable": reachable,
        }
        if identity:
            item["snmp_identity"] = identity
            item["identity_source"] = "snmp"
            item["snmp_sys_name"] = identity.get("sys_name", "")
            item["model"] = identity.get("model", "")
            item["service_tag"] = identity.get("serial", "")
        return item

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_ping_device, dev): dev for dev in fb.physical.values()}
        for f in concurrent.futures.as_completed(futures):
            try:
                physical.append(f.result())
            except Exception:
                dev = futures[f]
                display_name = getattr(dev, "display_name", "") or ""
                physical.append(
                    {
                        "key": dev.key,
                        "ip": dev.ip,
                        "label": dev.label,
                        "raw_label": dev.label,
                        "display_name": display_name,
                        "display_label": _operator_physical_display_label(cfg, dev),
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


_bg_discover_pve_nodes = _pve_discovery._bg_discover_pve_nodes
_get_discovered_node_ips = _pve_discovery._get_discovered_node_ips
_get_discovered_nodes = _pve_discovery._get_discovered_nodes
_find_reachable_pve_node = _pve_discovery.find_reachable_pve_node


_bg_fetch_vm_tags = _pve_tags._bg_fetch_vm_tags
get_vm_tags = _pve_tags.get_vm_tags
is_vm_tagged = _pve_tags.is_vm_tagged

_label_key = _vm_visibility._label_key
_managed_dashboard_vm_identities = _vm_visibility._managed_dashboard_vm_identities
_category_vmids = _vm_visibility._category_vmids
_dashboard_vm_scope = _vm_visibility._dashboard_vm_scope
_dashboard_vm_visible = _vm_visibility._dashboard_vm_visible
_get_fleet_vms = _pve_inventory._get_fleet_vms


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
        import io
        import sys

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

    result = _release_update.query_latest_release(__version__, time.time())

    with _bg_lock:
        _bg_cache["update"] = result
        _bg_cache_ts["update"] = time.time()
    _save_disk_cache("update", result)


def _evaluate_alert_rules(cfg, health_data):
    """Evaluate alert rules and fire notifications for triggered alerts."""
    try:
        from freq.jarvis.rules import (
            alert_to_dict,
            evaluate_rules,
            load_alert_history,
            load_rule_state,
            load_rules,
            save_alert_history,
            save_rule_state,
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
                except MemoryError:
                    raise
                except Exception as e:
                    logger.warn(f"Alert notification failed: {e}")
                history.append(alert_to_dict(alert))
                # SSE: broadcast alert event
                _sse_broadcast("alert", {"rule": alert.rule_name, "message": alert.message, "severity": alert.severity})
            save_alert_history(CACHE_DIR, history)
    except MemoryError:
        raise
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
        except MemoryError:
            raise
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
            (_bg_cleanup_expired_setup, "setup expiry cleanup"),
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


_cleanup_ssh_mux = _ssh_mux_cleanup.cleanup_ssh_mux


# Legacy DASHBOARD_HTML removed — 240 lines of dead embedded HTML
# Modern dashboard served from freq/data/web/app.html via _serve_static


# These imports intentionally follow the helpers they replace so serve.py can
# finish defining its compatibility surface before loading the auth module.
from freq.api.auth import (  # noqa: E402, F401
    _bg_cleanup_expired_setup,
    _cleanup_expired_setup,
    _clear_setup_contract_credentials,
    _delete_setup_vault_namespace,
    _observe_setup_state,
    _request_has_query_token,
    _retire_setup_contract,
    _setup_contract_getter,
    _setup_store_admin_password,
    _setup_vault_host,
    handle_auth_change_password,
    handle_auth_login,
    handle_auth_logout,
    handle_auth_verify,
    resolve_client_ip,
)
from freq.api.auth import (  # noqa: E402
    allow_setup_admin_window as _allow_setup_admin_window,
)
from freq.api.auth import (  # noqa: E402
    check_csrf as _check_csrf,
)
from freq.api.auth import (  # noqa: E402
    check_session_role as _check_session_role,
)
from freq.api.auth import (  # noqa: E402
    is_first_run as _is_first_run,
)
from freq.api.auth import (  # noqa: E402
    request_is_https as _request_is_https,
)
from freq.api.auth import (  # noqa: E402
    send_security_headers as _send_response_security_headers,
)
from freq.api.auth import (  # noqa: E402
    setup_init_command_from_contract as _setup_init_command_from_contract,
)
from freq.api.auth import (  # noqa: E402
    setup_session_payload as _setup_session_payload,
)
from freq.api.auth import (  # noqa: E402, F401
    write_setup_contract_credentials as _write_setup_contract_credentials,
)
from freq.api.helpers import setup_error as _setup_error  # noqa: E402

_setup_marker_exists = _setup_health.setup_marker_exists
_zero_state_setup_complete = _setup_health.zero_state_setup_complete


_write_web_setup_markers = _setup_health.write_web_setup_markers


_setup_forbidden_browser_input = _setup_inputs.forbidden_browser_input


_setup_init_snapshot = partial(
    _setup_progress.snapshot_live_init_job,
    current_lock=lambda: _setup_init_lock,
    current_job=lambda: _setup_init_job,
)


_SETUP_INIT_CANCEL_REQUESTED = _setup_progress.SETUP_INIT_CANCEL_REQUESTED
_SETUP_INIT_CANCEL_NOT_FOUND = _setup_progress.SETUP_INIT_CANCEL_NOT_FOUND
_SETUP_INIT_CANCEL_NOT_RUNNING = _setup_progress.SETUP_INIT_CANCEL_NOT_RUNNING


_setup_init_cancellation_runtime = _setup_progress.SetupInitCancellationRuntime(
    current_lock=lambda: _setup_init_lock,
    current_job=lambda: _setup_init_job,
)
_deliver_setup_init_cancel = partial(
    _setup_progress.deliver_setup_init_cancel,
    runtime=_setup_init_cancellation_runtime,
)
_publish_setup_init_process = partial(
    _setup_progress.publish_setup_init_process,
    runtime=_setup_init_cancellation_runtime,
)
_request_setup_init_cancel = partial(
    _setup_progress.request_setup_init_cancel,
    runtime=_setup_init_cancellation_runtime,
)
_setup_init_cancel_admission_runtime = _setup_progress.SetupInitCancelAdmissionRuntime(
    request_cancel=lambda job_id, owner: _request_setup_init_cancel(job_id, owner),
)
_cancel_setup_init = partial(
    _setup_progress.cancel_setup_init,
    runtime=_setup_init_cancel_admission_runtime,
)


_setup_discovery_snapshot = partial(
    _setup_progress.snapshot_live_discovery_job,
    current_lock=lambda: _setup_discovery_lock,
    current_job=lambda: _setup_discovery_job,
)

_setup_discovery_progress = partial(
    _setup_progress.update_discovery_progress,
    current_lock=lambda: _setup_discovery_lock,
    current_job=lambda: _setup_discovery_job,
)


_setup_discovery_admission_runtime = _setup_progress.SetupDiscoveryAdmissionRuntime(
    current_lock=lambda: _setup_discovery_lock,
    current_job=lambda: _setup_discovery_job,
    publish_job=lambda job: globals().__setitem__("_setup_discovery_job", job),
)
_admit_setup_discovery_job = partial(
    _setup_progress.admit_setup_discovery_job,
    runtime=_setup_discovery_admission_runtime,
)


_setup_discovery_secret_runtime = _setup_progress.SetupDiscoverySecretRuntime(
    setup_lock=lambda: _setup_lock,
    current_lock=lambda: _setup_discovery_lock,
    current_job=lambda: _setup_discovery_job,
    clear_job=lambda: globals().__setitem__("_setup_discovery_job", None),
    vault_init=lambda *args, **kwargs: vault_init(*args, **kwargs),
    vault_set=lambda *args, **kwargs: vault_set(*args, **kwargs),
    vault_get=lambda *args, **kwargs: vault_get(*args, **kwargs),
)
_store_setup_discovery_bootstrap_secret = partial(
    _setup_progress.store_setup_discovery_bootstrap_secret,
    runtime=_setup_discovery_secret_runtime,
)


_setup_discovery_state_runtime = _setup_progress.SetupDiscoveryStateRuntime(
    current_lock=lambda: _setup_discovery_lock,
    current_job=lambda: _setup_discovery_job,
    clear_job=lambda: globals().__setitem__("_setup_discovery_job", None),
    vault_delete=lambda *args, **kwargs: vault_delete(*args, **kwargs),
    update_state=lambda *args, **kwargs: update_setup_state(*args, **kwargs),
)
_persist_setup_discovery_state = partial(
    _setup_progress.persist_setup_discovery_state,
    runtime=_setup_discovery_state_runtime,
)


_setup_discovery_worker_runtime = _setup_progress.SetupDiscoveryWorkerRuntime(
    current_lock=lambda: _setup_discovery_lock,
    setup_lock=lambda: _setup_lock,
    current_job=lambda: _setup_discovery_job,
    vault_get=lambda *args, **kwargs: vault_get(*args, **kwargs),
    run_discovery=lambda *args, **kwargs: run_setup_discovery(*args, **kwargs),
    update_progress=lambda *args, **kwargs: _setup_discovery_progress(*args, **kwargs),
    load_contract=lambda *args, **kwargs: load_setup_contract(*args, **kwargs),
    retire_contract=lambda *args, **kwargs: _retire_setup_contract(*args, **kwargs),
    update_state=lambda *args, **kwargs: update_setup_state(*args, **kwargs),
)
_run_setup_discovery_job = partial(
    _setup_progress.run_setup_discovery_job,
    runtime=_setup_discovery_worker_runtime,
)


_setup_discovery_launch_runtime = _setup_progress.SetupDiscoveryLaunchRuntime(
    current_lock=lambda: _setup_discovery_lock,
    current_job=lambda: _setup_discovery_job,
    clear_job=lambda: globals().__setitem__("_setup_discovery_job", None),
    worker_target=_run_setup_discovery_job,
    thread_factory=lambda **kwargs: threading.Thread(**kwargs),
    vault_delete=lambda *args, **kwargs: vault_delete(*args, **kwargs),
    update_state=lambda *args, **kwargs: update_setup_state(*args, **kwargs),
)
_launch_setup_discovery_worker = partial(
    _setup_progress.launch_setup_discovery_worker,
    runtime=_setup_discovery_launch_runtime,
)


_setup_existing_secret_file = _setup_inputs.resolve_existing_secret_file
_read_setup_secret_file = _setup_inputs.read_existing_secret_file
_setup_secret_dir = _setup_inputs.setup_secret_dir
_write_setup_secret = _setup_inputs.write_setup_secret
_toml_scalar = _setup_inputs.toml_scalar
_write_setup_device_credentials = _setup_inputs.write_setup_device_credentials
_list_value = _setup_inputs.list_value
_setup_init_command = _setup_inputs.setup_init_command
_setup_init_request = _setup_inputs.validate_init_request
_write_setup_vm_contract = _setup_inputs.write_vm_contract
_schedule_setup_runtime_handoff = _setup_handoff.schedule_setup_runtime_handoff
_redact_setup_init_line = _setup_progress.redact_init_line
_setup_init_progress = _setup_progress.parse_init_progress
_setup_init_public_job = _setup_progress.project_init_job
_setup_discovery_payload = _setup_progress.project_discovery_job
_resolve_setup_discovery_status = _setup_progress.resolve_setup_discovery_status
_resolve_setup_contract_get = _setup_progress.resolve_setup_contract_get


_setup_init_status_runtime = _setup_progress.SetupInitStatusRuntime(
    snapshot_job=lambda: _setup_init_snapshot(),
    observe_state=lambda cfg: _observe_setup_state(cfg),
)
_resolve_setup_init_status = partial(
    _setup_progress.resolve_setup_init_status,
    runtime=_setup_init_status_runtime,
)


_setup_init_logs_runtime = _setup_progress.SetupInitLogsRuntime(
    snapshot_job=lambda: _setup_init_snapshot(),
)
_resolve_setup_init_logs = partial(
    _setup_progress.resolve_setup_init_logs,
    runtime=_setup_init_logs_runtime,
)


_setup_contract_admission_runtime = _setup_progress.SetupContractAdmissionRuntime(
    setup_lock=lambda: _setup_lock,
    observe_state=lambda *args, **kwargs: _observe_setup_state(*args, **kwargs),
    snapshot_discovery=lambda: _setup_discovery_snapshot(),
    load_contract=lambda *args, **kwargs: load_setup_contract(*args, **kwargs),
    retire_contract=lambda *args, **kwargs: _retire_setup_contract(*args, **kwargs),
    build_contract=lambda *args, **kwargs: build_setup_contract(*args, **kwargs),
    credential_keys=lambda contract: contract_credential_keys(contract),
    vault_host=lambda setup_id: _setup_vault_host(setup_id),
    vault_list=lambda *args, **kwargs: vault_list(*args, **kwargs),
    vault_update=lambda *args, **kwargs: vault_update(*args, **kwargs),
    save_contract=lambda *args, **kwargs: save_setup_contract(*args, **kwargs),
    clear_contract=lambda cfg: clear_setup_contract(cfg),
    build_getter=lambda *args, **kwargs: _setup_contract_getter(*args, **kwargs),
    project_contract=lambda *args, **kwargs: contract_payload(*args, **kwargs),
    update_state=lambda *args, **kwargs: update_setup_state(*args, **kwargs),
)
_admit_setup_contract = partial(
    _setup_progress.admit_setup_contract,
    runtime=_setup_contract_admission_runtime,
)


_setup_device_credential_admission_runtime = (
    _setup_progress.SetupDeviceCredentialAdmissionRuntime(
        setup_lock=lambda: _setup_lock,
        load_state=lambda *args, **kwargs: load_setup_state(*args, **kwargs),
        load_contract=lambda *args, **kwargs: load_setup_contract(*args, **kwargs),
        validate_request=lambda *args, **kwargs: validate_credential_request(
            *args, **kwargs
        ),
        vault_exists=lambda path: os.path.exists(path),
        vault_init=lambda *args, **kwargs: vault_init(*args, **kwargs),
        vault_host=lambda setup_id: _setup_vault_host(setup_id),
        vault_list=lambda *args, **kwargs: vault_list(*args, **kwargs),
        vault_update=lambda *args, **kwargs: vault_update(*args, **kwargs),
        credential_key=lambda *args, **kwargs: credential_vault_key(*args, **kwargs),
        storage_value=lambda *args, **kwargs: credential_storage_value(*args, **kwargs),
        record_request=lambda *args, **kwargs: record_credential_request(
            *args, **kwargs
        ),
        save_contract=lambda *args, **kwargs: save_setup_contract(*args, **kwargs),
        build_getter=lambda *args, **kwargs: _setup_contract_getter(*args, **kwargs),
        project_presence=lambda *args, **kwargs: credential_presence(*args, **kwargs),
        update_state=lambda *args, **kwargs: update_setup_state(*args, **kwargs),
    )
)
_admit_setup_device_credentials = partial(
    _setup_progress.admit_setup_device_credentials,
    runtime=_setup_device_credential_admission_runtime,
)


_init_blocker_from_artifacts = _setup_health.init_blocker_from_artifacts


_setup_init_worker_runtime = _setup_progress.SetupInitWorkerRuntime(
    init_lock=_setup_init_lock,
    setup_lock=_setup_lock,
    current_job=lambda: _setup_init_job,
    popen=lambda *args, **kwargs: subprocess.Popen(*args, **kwargs),
    publish_process=lambda job_id, process: _publish_setup_init_process(job_id, process),
    load_config=lambda **kwargs: load_config(**kwargs),
    write_web_setup_markers=lambda cfg: _write_web_setup_markers(cfg),
    delete_setup_vault_namespace=lambda cfg, setup_id: _delete_setup_vault_namespace(
        cfg, setup_id
    ),
    clear_setup_contract=lambda cfg: clear_setup_contract(cfg),
    clear_setup_state=lambda cfg: clear_setup_state(cfg),
    update_setup_state=lambda cfg, **kwargs: update_setup_state(cfg, **kwargs),
    schedule_runtime_handoff=lambda cfg: _schedule_setup_runtime_handoff(cfg),
    redact_line=lambda line, secret_dir: _redact_setup_init_line(line, secret_dir),
    parse_progress=lambda line: _setup_init_progress(line),
    now=lambda: time.time(),
    remove_tree=lambda path: shutil.rmtree(path),
)
_run_setup_init_job = partial(
    _setup_progress.run_setup_init_job,
    runtime=_setup_init_worker_runtime,
)


_settle_setup_init_launch = partial(
    _setup_progress.settle_setup_init_launch,
    runtime=_setup_init_cancellation_runtime,
)


_setup_init_start_runtime = _setup_progress.SetupInitStartRuntime(
    setup_lock=lambda: _setup_lock,
    observe_state=lambda *args, **kwargs: _observe_setup_state(*args, **kwargs),
    load_contract=lambda *args, **kwargs: load_setup_contract(*args, **kwargs),
    snapshot_discovery=lambda: _setup_discovery_snapshot(),
    contract_ready=lambda cfg, setup_id, contract: contract_payload(
        contract,
        _setup_contract_getter(cfg, setup_id),
    )["ready"],
    validate_request=lambda *args, **kwargs: _setup_init_request(*args, **kwargs),
    init_lock=lambda: _setup_init_lock,
    current_job=lambda: _setup_init_job,
    publish_job=lambda job: globals().__setitem__("_setup_init_job", job),
    new_job_id=lambda: uuid.uuid4().hex,
    build_command=lambda *args, **kwargs: _setup_init_command_from_contract(
        *args, **kwargs
    ),
    now=lambda: time.time(),
    update_state=lambda *args, **kwargs: update_setup_state(*args, **kwargs),
    worker_factory=lambda **kwargs: threading.Thread(**kwargs),
    worker_target=_run_setup_init_job,
    remove_tree=lambda *args, **kwargs: shutil.rmtree(*args, **kwargs),
    settle_launch=lambda: _settle_setup_init_launch(),
)
_start_setup_init = partial(
    _setup_progress.start_setup_init,
    runtime=_setup_init_start_runtime,
)


class FreqHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the FREQ dashboard."""

    # HTTP/1.1 required for WebSocket upgrade (RFC 6455) and SSE keep-alive
    protocol_version = "HTTP/1.1"

    # Class-level caches for PVE metrics polling
    _pve_metrics_cache = None
    _pve_metrics_ts = 0
    # per-node last-seen tracking so the
    # dashboard can render 'STALE 47s' instead of a bare 'offline' chip.
    _pve_last_seen_ts: dict = {}

    def finish(self):
        """Close both retained original streams before classifying failures."""
        entry = getattr(self, '_standard_observe_entry', None)
        if (entry is None or entry.handler is not self
                or entry.retention_stage == 'unreserved'):
            return super().finish()
        # No dynamic helper lookup/import on this cleanup path. Fixed original
        # stream/error holders exist before auth/body/response. No uncertain
        # close is retried; the retained slot cannot settle from socket alone.
        failed = False
        if entry.stream_stages[0] == 'owned':
            try:
                if not entry.streams[0].closed:
                    entry.streams[0].flush()
            except BaseException as failure:
                entry.stream_failures[0] = failure
                failed = True
        for index in (0, 1):
            if entry.stream_stages[index] != 'owned':
                continue
            entry.stream_stages[index] = 'close-pending'
            try:
                entry.streams[index].close()
            except BaseException as failure:
                entry.stream_stages[index] = 'close-uncertain'
                entry.stream_failures[index + 1] = failure
                failed = True
            else:
                entry.stream_stages[index] = 'closed'
        if failed:
            # Independent closes above precede all failure classification.
            first = entry.failure
            for failure in entry.stream_failures:
                first = _http_cleanup_first(first, failure)
            entry.failure = first
            raise first from None

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
        self._request_id_header_sent = False
        self._lab_response_consumed = False
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
        "/api/setup/discovery/start": "_serve_setup_discovery_start",
        "/api/setup/discovery/status": "_serve_setup_discovery_status",
        "/api/setup/contract": "_serve_setup_contract",
        "/api/setup/device-credentials": "_serve_setup_device_credentials",
        "/api/setup/init/start": "_serve_setup_init_start",
        "/api/setup/init/cancel": "_serve_setup_init_cancel",
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
        # ── Lab tooling (stays in serve.py) ───────────────────────────
        "/api/lab/status": "_serve_lab_status",
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

    # One complete local + domain registry, built atomically before serving.
    _ROUTE_REGISTRY = None
    _ROUTE_REGISTRY_LOCK = threading.Lock()

    @classmethod
    def _load_routes(cls):
        """Build and cache the complete registry, or raise without partial state."""
        if cls._ROUTE_REGISTRY is None:
            with cls._ROUTE_REGISTRY_LOCK:
                if cls._ROUTE_REGISTRY is None:
                    from freq.api import build_route_registry

                    registry = build_route_registry(cls._ROUTES)
                    cls._ROUTE_REGISTRY = registry
                    logger.info(f"API route registry loaded: {len(registry)} endpoints")
        return cls._ROUTE_REGISTRY

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
        "/api/docs",
        "/healthz",
        "/readyz",
        "/api/openapi.json",
    })
    # Path prefixes that don't require authentication
    _AUTH_WHITELIST_PREFIXES = ("/static/", "/dashboard")
    _CSRF_EXEMPT = frozenset({
        "/api/auth/login",
        "/api/auth/logout",
        "/api/setup/status",
        "/api/setup/create-admin",
    })
    _JSON_BODY_ROUTES = frozenset({
        "/api/auth/login",
        "/api/auth/change-password",
        "/api/ui/event",
        "/api/media/tags",
        "/api/setup/create-admin",
        "/api/setup/configure",
        "/api/setup/discovery/start",
        "/api/setup/contract",
        "/api/setup/device-credentials",
        "/api/setup/init/start",
        "/api/setup/init/cancel",
        "/api/lab-tool/save-config",
    })

    def _requires_csrf(self, path: str) -> bool:
        if self.command not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        if not path.startswith("/api/"):
            return False
        if path in self._CSRF_EXEMPT:
            return False
        return True

    def _dispatch(self):
        """Route request to handler method or callable by path.

        Transport-local routes use string method names (getattr dispatch).
        Domain routes use callables: function(handler) from freq/api/.
        """
        path = self.path.split("?")[0]

        if path == "/api/auth/logout":
            self.close_connection = True

        # This mode is selected by the actual server, never by request input.
        # Gate before special reads, auth wrappers or endpoint dispatch. Allowed
        # entries still pass their original authentication, CSRF and claim checks.
        lab_cockpit = getattr(getattr(self, "server", None), "freq_lab_cockpit", False) is True
        from freq.api.lab_guest import operation_path
        lab_path = path in ("/api/lab/guest", "/api/lab/power", "/api/lab/window") or operation_path(path)
        if lab_path and self.command == "POST":
            self.close_connection = True
        if lab_path and not lab_cockpit:
            self.close_connection = True
            self._json_response({"error": "not_found"}, 404)
            return
        if lab_cockpit or getattr(getattr(self, "server", None), "freq_read_only", False) is True:
            allowed_lab = lab_cockpit and (
                (self.command, path) in (("GET", "/api/lab/guest"), ("POST", "/api/lab/power"),
                                        ("GET", "/api/lab/window"), ("POST", "/api/lab/window"))
                or self.command == "GET" and operation_path(path)
            )
            allowed_api = (self.command, path) in _READ_ONLY_API_ROUTES or allowed_lab
            allowed_asset = self.command == "GET" and (
                path in ("/", "/dashboard", "/setup", "/setup.html")
                or path.startswith("/dashboard/")
                or path.startswith("/static/")
            )
            if not (allowed_api or allowed_asset):
                # A refused POST body must not become another request on this
                # connection. Do not resolve an endpoint or consume its input.
                self.close_connection = True
                self._json_response({
                    "error": "Route unavailable in read-only mode",
                    "reason": "read_only_mode",
                }, 403)
                return

        # Standard QEMU reads have an exact schema3 refusal and original
        # session/CSRF entry. Keep them outside legacy auth/error wrappers.
        if path.startswith("/api/observe/v1/"):
            from freq.api.standard_observe import handle

            handle(self)
            return

        if self.command == "POST" and path in self._JSON_BODY_ROUTES:
            try:
                _require_json_media_type(self)
            except _UnsupportedJSONMediaType:
                _setup_error(
                    self,
                    400,
                    "unsupported_media_type",
                    "Send Content-Type: application/json.",
                )
                return

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
            if self._requires_csrf(path):
                ok, csrf_err = _check_csrf(self)
                if not ok:
                    logger.warn(
                        "http_csrf_rejected",
                        request_id=getattr(self, "_request_id", ""),
                        method=getattr(self, "command", "?"),
                        path=path,
                        reason=csrf_err,
                    )
                    self._json_response({"error": csrf_err}, 403)
                    return

        from freq.api.lab_guest import handle as handle_lab, operation_path
        handler_ref = handle_lab if operation_path(path) else self._load_routes().get(path)
        if handler_ref:
            try:
                if callable(handler_ref):
                    handler_ref(self)
                else:
                    getattr(self, handler_ref)()
            except MemoryError:
                # Preserve the original allocation failure without repr/log/JSON.
                # The original request wrapper still attempts finish once.
                raise
            except Exception as e:
                # Dedicated structured reads consume publication before headers.
                # Never append generic error JSON after their write attempt.
                if (getattr(self, "_standard_frontend_response_started", False)
                        or getattr(self, "_lab_response_consumed", False)):
                    self.close_connection = True
                    if issubclass(type(e), MemoryError):
                        raise
                    return
                if (getattr(self, "_cluster_response_consumed", False)
                        or getattr(self, "_cluster_publication_admitted", False)):
                    self.close_connection = True
                    return
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
                except MemoryError:
                    raise
                except Exception as e2:
                    import sys

                    print(f"[FREQ] Failed to send error response for {path}: {e2}", file=sys.stderr)
        elif path.startswith("/static/"):
            self._serve_static(path)
        elif path.startswith("/api/"):
            logger.error("api_error", method=getattr(self, "command", "?"), path=path, status=404)
            self._json_response({"error": "not found", "path": path}, 404)
        else:
            self._serve_app()

    def _dispatch_and_finish(self):
        """Keep raw dispatch failure while independently finishing once."""
        first = None
        try:
            self._dispatch()
        except BaseException as failure:
            first = failure
        try:
            self._finish_request()
        except BaseException as failure:
            if (first is None or issubclass(type(first), Exception) and (
                    not issubclass(type(failure), Exception)
                    or not issubclass(type(first), MemoryError)
                    and issubclass(type(failure), MemoryError))):
                first = failure
        if first is not None:
            raise first from None

    def do_GET(self):
        self._begin_request()
        self._dispatch_and_finish()

    def do_POST(self):
        self._begin_request()
        self._dispatch_and_finish()

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
                    lines = [line for line in r.stdout.split("\n") if line.strip()]
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
        self._json_response(
            _deployment_history.read_deploy_log(load_config().install_dir)
        )

    def _documented_routes(self):
        """Return the same complete registry used by request dispatch."""
        return dict(self._load_routes())

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
        _POST_KEYWORDS = ("create", "update", "delete", "reset", "login", "logout",
                          "change", "complete", "generate", "deploy",
                          "rollback", "power", "boot", "clear", "wol",
                          "bench", "reboot", "add", "remove")
        # Paths that contain POST keywords but are actually GET (read-only)
        _GET_OVERRIDES = {"/api/fleet/updates", "/api/redfish/power-usage"}
        # Product settings endpoints that intentionally expose read+write on
        # one resource path: GET returns current shape, POST applies changes.
        _DUAL_METHOD_ROUTES = {
            "/api/opnsense/enrollment",
            "/api/vm/network-profiles",
        }

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
            if path in self._JSON_BODY_ROUTES:
                methods = ["post"]
            elif path in _GET_OVERRIDES:
                methods = ["get"]
            elif path in _DUAL_METHOD_ROUTES:
                methods = ["get", "post"]
            elif any(kw in path_tail for kw in _POST_KEYWORDS) or doc_lower.startswith("post "):
                methods = ["post"]
            else:
                methods = ["get"]

            responses = {
                "200": {"description": "Successful response", "content": {"application/json": {}}},
            }
            if "post" in methods:
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
                for method in methods
            }

        generic_json_body = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                }
            },
        }
        for path in self._JSON_BODY_ROUTES:
            operation = paths.get(path, {}).get("post")
            if operation is not None:
                operation["requestBody"] = generic_json_body

        origin_parameter = {
            "name": "Origin",
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "Exact HTTPS origin matching the request Host authority.",
        }
        for path in ("/api/auth/login", "/api/auth/logout"):
            operation = paths.get(path, {}).get("post")
            if operation is not None:
                operation["parameters"] = [dict(origin_parameter)]

        create_operation = paths.get("/api/setup/create-admin", {}).get("post")
        if create_operation is not None:
            create_operation["security"] = []
            create_operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "schema",
                                "username",
                                "password",
                                "claim_secret",
                                "client_request_id",
                            ],
                            "properties": {
                                "schema": {"type": "string", "const": ZERO_STATE_WEB_SCHEMA},
                                "username": {"type": "string"},
                                "password": {"type": "string", "format": "password", "writeOnly": True},
                                "claim_secret": {
                                    "type": "string",
                                    "format": "password",
                                    "writeOnly": True,
                                    "minLength": 1,
                                    "maxLength": 256,
                                },
                                "client_request_id": {"type": "string"},
                            },
                        }
                    }
                },
            }

            failure_contract = (
                ("400", "unsupported_media_type", False, None),
                ("403", "https_required", False, None),
                ("400", "claim_secret_required", False, "claim_secret"),
                ("403", "claim_secret_invalid", True, "claim_secret"),
                ("403", "setup_closed", False, None),
                ("409", "claim_consumed", False, None),
                ("409", "operator_exists", False, None),
                ("409", "setup_busy", True, None),
                ("429", "claim_rate_limited", True, None),
                ("503", "claim_state_unavailable", True, None),
            )

            def failure_branch(code, retryable, field):
                error_properties = {
                    "code": {"type": "string", "const": code},
                    "message": {"type": "string"},
                    "retryable": {"type": "boolean", "const": retryable},
                }
                if field is not None:
                    error_properties["field"] = {"type": "string", "const": field}
                error_required = list(error_properties)
                return {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ok", "schema", "error", "request_id"],
                    "properties": {
                        "ok": {"type": "boolean", "const": False},
                        "schema": {"type": "string", "const": ZERO_STATE_WEB_SCHEMA},
                        "error": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": error_required,
                            "properties": error_properties,
                        },
                        "request_id": {
                            "type": "string",
                            "minLength": 12,
                            "maxLength": 12,
                            "pattern": "^[0-9a-f]{12}$",
                        },
                    },
                }

            by_status = {}
            for status, code, retryable, field in failure_contract:
                by_status.setdefault(status, []).append(failure_branch(code, retryable, field))
            for status, branches in by_status.items():
                create_operation["responses"][status] = {
                    "description": "Stable first-admin setup failure",
                    "content": {
                        "application/json": {
                            "schema": {"oneOf": branches},
                        }
                    },
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
        setup_state_unreadable = False
        try:
            setup_record = _observe_setup_state(cfg)
        except (OSError, ValueError, TypeError) as exc:
            logger.warn(f"setup_status_state_unreadable: {exc}")
            setup_record = {}
            setup_state_unreadable = True
        if dashboard_accounts_configured and is_authed and not (is_initialized and is_web_setup_complete):
            setup_user = getattr(self, "_session_user", "") or (
                dashboard_users[0].get("username", "") if dashboard_users else ""
            )
            if setup_user:
                try:
                    setup_record = ensure_setup_state(cfg, setup_user)
                    setup_record = touch_setup_state(cfg)
                except (OSError, ValueError) as exc:
                    logger.warn(f"setup_status_state_refresh_failed: {exc}")

        job_state = (running_job or {}).get("state", "")
        if is_initialized and is_web_setup_complete:
            zero_state = "complete"
        elif job_state == "running":
            zero_state = "initializing"
        elif setup_state_unreadable:
            zero_state = "blocked"
        elif job_state == "failed" or is_initialized or is_web_setup_complete:
            zero_state = "blocked"
        elif not dashboard_accounts_configured:
            zero_state = "needs_operator"
        else:
            candidate = setup_record.get("phase", "collecting") if setup_record else "collecting"
            zero_state = candidate if candidate in {
                "collecting", "discovering", "selecting", "credentials", "ready", "blocked"
            } else "collecting"
        next_actions = {
            "needs_operator": "create_operator",
            "collecting": "start_discovery",
            "discovering": "poll_discovery",
            "selecting": "build_contract",
            "credentials": "store_device_credentials",
            "ready": "start_init",
            "initializing": "poll_init",
            "blocked": "review_blocker",
            "complete": "open_dashboard",
        }
        payload = {
            "ok": True,
            "schema": ZERO_STATE_WEB_SCHEMA,
            "state": zero_state,
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
            "setup_id": setup_record.get("setup_id") if is_authed and setup_record else None,
            "active_discovery_id": (
                setup_record.get("active_discovery_id") if is_authed and setup_record else None
            ),
            "active_contract_id": (
                setup_record.get("active_contract_id") if is_authed and setup_record else None
            ),
            "active_init_job_id": (
                (
                    (running_job or {}).get("id")
                    or (setup_record.get("active_init_job_id") if setup_record else None)
                )
                if is_authed
                else None
            ),
            "next": next_actions[zero_state],
            "checked_at": time.time(),
        }
        if setup_state_unreadable:
            payload["blocker"] = {
                "code": "setup_state_unreadable",
                "message": "Setup state is temporarily unreadable.",
                "retryable": True,
            }
        if is_authed:
            payload["version"] = __version__
            payload["ssh_key_path"] = key_path or ""
            payload["host_count"] = len(cfg.hosts)
            payload["init_status"] = _project_init_status(cfg)
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
        """Create the one first-run admin from a write-only password value."""
        def reject(handler, _status, code, _message, **options):
            field = options.get("field", "")
            template_id = f"{code}:{field}" if code in {"required_field", "invalid_field"} else code
            _create_admin_error(handler, template_id)

        _setup_error = reject

        if self.command != "POST":
            _setup_error(self, 405, "method_not_allowed", "Use POST with a JSON body.")
            return
        if not _request_is_https(self):
            _setup_error(
                self,
                403,
                "https_required",
                "First-operator setup requires the bootstrap HTTPS listener.",
            )
            return

        try:
            _require_json_media_type(self)
        except _UnsupportedJSONMediaType:
            _setup_error(
                self,
                400,
                "unsupported_media_type",
                "Send Content-Type: application/json.",
            )
            return

        try:
            body = self._request_body()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            required = {"schema", "username", "password", "claim_secret", "client_request_id"}
            missing = sorted(required - set(body))
            if missing:
                field = missing[0]
                if field == "claim_secret":
                    _setup_error(
                        self,
                        400,
                        "claim_secret_required",
                        "The first-boot claim is required.",
                        field="claim_secret",
                    )
                else:
                    _setup_error(
                        self,
                        400,
                        "required_field",
                        "A required setup field is missing.",
                        field=field,
                    )
                return
            field, code = _setup_forbidden_browser_input(body)
            if field:
                _setup_error(
                    self,
                    400,
                    code,
                    "Server-side paths and manual contracts are not accepted by browser setup.",
                )
                return
            unknown = sorted(set(body) - required)
            if unknown:
                _setup_error(
                    self,
                    400,
                    "unsupported_field",
                    "Unsupported setup field.",
                )
                return
            typed_fields = ("schema", "username", "password", "claim_secret", "client_request_id")
            invalid_type = next((name for name in typed_fields if not isinstance(body.get(name), str)), "")
            if invalid_type:
                code = "claim_secret_required" if invalid_type == "claim_secret" else "invalid_field"
                _setup_error(
                    self,
                    400,
                    code,
                    f"Setup field must be a string: {invalid_type}.",
                    field=invalid_type,
                )
                return
            schema = body["schema"]
            if schema != ZERO_STATE_WEB_SCHEMA:
                _setup_error(
                    self,
                    400,
                    "unsupported_schema",
                    "Unsupported setup schema.",
                    field="schema",
                )
                return
            claim_secret = body["claim_secret"]
            if not claim_secret or len(claim_secret) > 256:
                _setup_error(
                    self,
                    400,
                    "claim_secret_required",
                    "The first-boot claim is required.",
                    field="claim_secret",
                )
                return
            username = body["username"].strip().lower()
            password = body["password"]
        except MemoryError:
            raise
        except Exception:
            _setup_error(self, 400, "invalid_json", "Invalid setup admin request.")
            return
        client_ip = resolve_client_ip(self)
        if not _first_admin_claim_limiter.should_compare(client_ip):
            _setup_error(
                self,
                429,
                "claim_rate_limited",
                "Wait for the current rate window, then retry.",
                retryable=True,
            )
            return
        cfg = load_config()
        from freq.core.read_source_epoch import _first

        # Login deliberately excludes the runtime SSH service account. Do not
        # consume the first-admin claim to create an operator who cannot sign in.
        service_account = getattr(cfg, "ssh_service_account", "")
        if service_account and username == service_account.lower():
            _setup_error(
                self, 400, "invalid_field",
                "Setup field must be a string: username.", field="username",
            )
            return

        if not _setup_lock.acquire(blocking=False):
            _setup_error(self, 409, "setup_busy", "Another setup mutation is in progress.", retryable=True)
            return
        body_failure = None
        try:
            try:
                claim_context = locked_first_admin_claim(cfg)
                with claim_context as claim_transaction:
                    try:
                        marker_exists = _setup_marker_exists(cfg)
                        users = _load_users(cfg)
                    except MemoryError:
                        raise
                    except Exception:
                        _setup_error(
                            self,
                            503,
                            "claim_state_unavailable",
                            "First-admin setup is temporarily unavailable; retry.",
                            retryable=True,
                        )
                        return
                    if marker_exists or _zero_state_setup_complete(cfg):
                        _setup_error(self, 403, "setup_closed", "Setup is complete; sign in to resume.")
                        return
                    if users:
                        _setup_error(
                            self,
                            409,
                            "operator_exists",
                            "The first operator already exists; sign in to resume setup.",
                        )
                        return
                    if claim_transaction.state_name == "consumed":
                        _setup_error(
                            self,
                            409,
                            "claim_consumed",
                            "Follow the local first-admin claim reset procedure in the zero-state runbook.",
                        )
                        return
                    if claim_transaction.state_name != "available":
                        raise ClaimStateError("claim is not available")
                    if not claim_transaction.matches(claim_secret):
                        _first_admin_claim_limiter.record_invalid(client_ip)
                        status = _first_admin_claim_limiter.failure_status(client_ip)
                        if status == 429:
                            _setup_error(
                                self,
                                429,
                                "claim_rate_limited",
                                "Wait for the current rate window, then retry.",
                                retryable=True,
                            )
                        else:
                            _setup_error(
                                self,
                                403,
                                "claim_secret_invalid",
                                "Use the newest claim for the current service; if it was lost, follow the local first-admin claim reset procedure in the zero-state runbook.",
                                field="claim_secret",
                                retryable=True,
                            )
                        return

                    if not username or not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", username):
                        _setup_error(
                            self,
                            400,
                            "invalid_username",
                            "Username must be lowercase and contain only letters, digits, hyphens, or underscores.",
                            field="username",
                        )
                        return
                    if len(password) < 8:
                        _setup_error(
                            self,
                            400,
                            "invalid_password",
                            "Password must be at least 8 characters.",
                            field="password",
                        )
                        return

                    store_error = _setup_store_admin_password(cfg, username, password)
                    if store_error:
                        _setup_error(
                            self,
                            500,
                            "operator_password_store_failed",
                            "Failed to store password.",
                        )
                        return

                    clear_setup_state(cfg)
                    try:
                        setup_record = ensure_setup_state(cfg, username)
                    except (OSError, ValueError):
                        _setup_error(self, 500, "setup_state_write_failed", "Failed to create setup state.")
                        return
                    users.append({"username": username, "role": "admin", "groups": ""})
                    os.makedirs(cfg.conf_dir, exist_ok=True)
                    save_error = _save_users_error(cfg, users)
                    if save_error:
                        clear_setup_state(cfg)
                        _setup_error(self, 500, "operator_write_failed", "Failed to save user.")
                        return

                    try:
                        claim_transaction.consume()
                    except ClaimStateError:
                        logger.critical(
                            "first_admin_claim_terminalization_failed_after_user_commit",
                            claim_id=claim_transaction.claim_id,
                        )
                    _first_admin_claim_limiter.clear_client(client_ip)

                    try:
                        self._json_response(
                            _setup_session_payload(
                                self,
                                username,
                                "admin",
                                schema=ZERO_STATE_WEB_SCHEMA,
                                setup_id=setup_record["setup_id"],
                                state="collecting",
                            )
                        )
                    except MemoryError:
                        raise
                    except Exception as exc:
                        logger.warn(f"setup_create_admin_session_failed: {exc}")
                        _setup_error(self, 500, "session_create_failed", "Setup admin session creation failed.")
            except ClaimStateError:
                _setup_error(
                    self,
                    503,
                    "claim_state_unavailable",
                    "First-admin setup is temporarily unavailable; retry.",
                    retryable=True,
                )
                return
        except BaseException as error:
            body_failure = error
            raise
        finally:
            try:
                _setup_lock.release()
            except BaseException as cleanup_error:
                if body_failure is not None and (
                        not issubclass(type(body_failure), Exception)
                        or issubclass(type(body_failure), MemoryError)
                        or not issubclass(type(cleanup_error), Exception)
                        or issubclass(type(cleanup_error), MemoryError)):
                    raise _first(body_failure, cleanup_error) from None
                raise

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
        timezone = str(body.get("timezone") or "UTC").strip() or "UTC"
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

        # UTC is built into Python's datetime model and must work on minimal
        # images that do not install the optional system tzdata database.
        if timezone not in {"UTC", "Etc/UTC", "GMT"}:
            try:
                import zoneinfo

                zoneinfo.ZoneInfo(timezone)
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

        from freq.core.read_source_epoch import SourceWriteUnavailable, source_write
        from freq.modules.init_cmd import _update_toml_value

        try:
            with source_write():
                cfg = load_config()
                toml_path = os.path.join(cfg.conf_dir, "freq.toml")
                os.makedirs(cfg.conf_dir, exist_ok=True)

                # Read and modify only while participating source writers are excluded.
                content = ""
                if os.path.isfile(toml_path):
                    with open(toml_path, "r") as f:
                        content = f.read()

                # If empty/missing, seed from template.
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

                content = _update_toml_value(content, "cluster_name", cluster_name)
                content = _update_toml_value(content, "timezone", timezone)
                content = _update_toml_value(content, "nodes", node_ips)
                content = _update_toml_value(content, "node_names", node_names)
                with open(toml_path, "w") as f:
                    f.write(content)
        except SourceWriteUnavailable:
            self._json_response({"error": "Configuration update unavailable"}, 500)
            return
        except OSError as e:
            self._json_response({"error": f"Failed to write config: {e}"}, 500)
            return

        # Response I/O is outside the writer transaction and its error handler.
        self._json_response(
            {
                "ok": True,
                "cluster_name": cluster_name,
                "timezone": timezone,
                "pve_nodes": node_ips,
                "pve_node_names": node_names,
            }
        )

    def _serve_setup_generate_key(self):
        """Generate SSH keypair during first-run setup. POST only."""
        if not _is_first_run() and not _allow_setup_admin_window(self):
            return

        if self.command != "POST":
            self._json_response({"error": "Use POST to generate keys"}, 405)
            return

        payload, status = _setup_keys.generate_setup_keys(load_config().key_dir)
        self._json_response(payload, status)

    def _serve_setup_complete(self):
        """Legacy endpoint; completion belongs exclusively to successful init."""
        if self.command != "POST":
            _setup_error(self, 405, "method_not_allowed", "Use POST with a JSON body.")
            return
        _setup_error(
            self,
            409,
            "legacy_endpoint_disabled",
            "Browser setup completes only after web-launched init succeeds.",
        )

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
        global _setup_discovery_job
        if self.command != "POST":
            self._json_response({"error": "Setup reset requires POST"}, 405)
            return
        cfg = load_config()

        # This endpoint requires admin auth (NOT gated by _is_first_run)
        role, err = _check_session_role(self, min_role="admin")
        if err:
            self._json_response({"error": err}, 403)
            return
        _settle_setup_init_launch()
        if _setup_init_snapshot().get("running"):
            _setup_error(self, 409, "init_running", "Setup cannot reset while init is running.")
            return

        data_dir = cfg.data_dir
        marker = os.path.join(data_dir, "setup-complete")
        web_marker = os.path.join(cfg.conf_dir, ".web-setup-complete")

        from freq.core.read_source_epoch import source_write, SourceWriteUnavailable

        try:
            with source_write(), _setup_lock:
                # The earlier snapshot can only fast-refuse. Recheck live
                # occupancy while setup admission is serialized, before effects.
                if _setup_init_snapshot().get("running"):
                    raise _setup_progress.SetupInitResetBusy()
                state = load_setup_state(cfg)
                contract = load_setup_contract(cfg)
                _retire_setup_contract(cfg, contract)
                if state:
                    host = _setup_vault_host(state.get("setup_id", ""))
                    exact_keys = {key for entry_host, key, _value in vault_list(cfg) if entry_host == host}
                    if "bootstrap_password" in exact_keys:
                        if not vault_update(cfg, host, {"bootstrap_password": None}):
                            raise OSError("setup bootstrap cleanup failed")
                        remaining = {key for entry_host, key, _value in vault_list(cfg) if entry_host == host}
                        if "bootstrap_password" in remaining:
                            raise OSError("setup bootstrap cleanup failed")
                clear_setup_state(cfg)
                with _setup_discovery_lock:
                    _setup_discovery_job = None
                for m in (marker, web_marker):
                    if os.path.isfile(m):
                        os.remove(m)
            self._json_response({"ok": True, "message": "Setup wizard re-enabled (note: freq init state is unchanged — re-run freq init if needed)"})
        except _setup_progress.SetupInitResetBusy:
            _setup_error(self, 409, "init_running", "Setup cannot reset while init is running.")
        except SourceWriteUnavailable:
            self._json_response({"error": "Setup reset unavailable"}, 503)
        except OSError as e:
            self._json_response({"error": f"Failed to reset setup: {e}"}, 500)

    def _serve_setup_discovery_start(self):
        """Start bounded PVE and derived-network discovery."""
        if self.command != "POST":
            _setup_error(self, 405, "method_not_allowed", "Discovery start requires POST.")
            return
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        cfg = load_config()
        if _zero_state_setup_complete(cfg):
            _setup_error(self, 403, "setup_closed", "Browser setup is already complete.")
            return
        try:
            body = self._request_body()
            field, code = _setup_forbidden_browser_input(body)
            if field:
                _setup_error(
                    self,
                    400,
                    code,
                    "Server-side paths, manual contracts, and caller scan scopes are not accepted.",
                    field=field,
                )
                return
            request = validate_discovery_request(body, ZERO_STATE_WEB_SCHEMA)
        except DiscoveryInputError as exc:
            _setup_error(self, exc.status, exc.code, str(exc), field=exc.field)
            return
        except Exception:
            _setup_error(self, 400, "invalid_json", "Invalid discovery request.")
            return

        state = _observe_setup_state(cfg)
        if not state:
            _setup_error(self, 410, "setup_expired", "The setup window expired; reload setup status.")
            return
        if request["setup_id"] != state.get("setup_id"):
            _setup_error(self, 410, "setup_expired", "The setup identity is stale; reload setup status.")
            return
        session_user = getattr(self, "_session_user", "")
        if state.get("username") != session_user:
            _setup_error(self, 403, "setup_owner_mismatch", "Setup belongs to another operator.")
            return

        job_id = uuid.uuid4().hex
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job = {
            "id": job_id,
            "setup_id": state["setup_id"],
            "client_request_id": request.get("client_request_id", ""),
            "state": "queued",
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "poll_after_ms": 1000,
            "progress": {
                "phase": "queued",
                "current": 0,
                "total": len(request["cluster"]["nodes"]),
                "message": "Discovery queued.",
            },
            "cluster": request["cluster"],
            "bootstrap_username": request["bootstrap"]["username"],
            "results": None,
            "error": None,
        }
        admission = _admit_setup_discovery_job(job)
        existing = admission.existing
        replay = admission.replay
        conflict = admission.conflict
        if replay:
            self._json_response(
                {
                    "ok": True,
                    "schema": ZERO_STATE_WEB_SCHEMA,
                    "setup_id": state["setup_id"],
                    "discovery": _setup_discovery_payload(existing),
                },
                202,
            )
            return
        if conflict:
            _setup_error(self, 409, "discovery_running", "A discovery job is already running.", retryable=True)
            return

        password = request["bootstrap"].pop("password")
        try:
            setup_vault_host = _store_setup_discovery_bootstrap_secret(
                cfg,
                state["setup_id"],
                job_id,
                password,
            )
        finally:
            password = ""
        if not setup_vault_host:
            _setup_error(self, 500, "bootstrap_secret_store_failed", "Bootstrap secret storage failed.")
            return

        if not _persist_setup_discovery_state(cfg, job_id, setup_vault_host):
            _setup_error(self, 500, "setup_state_write_failed", "Discovery state could not be persisted.")
            return
        if not _launch_setup_discovery_worker(cfg, job_id, setup_vault_host):
            _setup_error(self, 500, "discovery_start_failed", "Discovery worker could not start.")
            return
        self._json_response(
            {
                "ok": True,
                "schema": ZERO_STATE_WEB_SCHEMA,
                "setup_id": state["setup_id"],
                "discovery": _setup_discovery_payload(_setup_discovery_snapshot()),
            },
            202,
        )

    def _serve_setup_discovery_status(self):
        """Return one setup-bound discovery job without secret material."""
        if self.command != "GET":
            _setup_error(self, 405, "method_not_allowed", "Discovery status requires GET.")
            return
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        cfg = load_config()
        if _zero_state_setup_complete(cfg):
            _setup_error(self, 403, "setup_closed", "Browser setup is already complete.")
            return
        state = _observe_setup_state(cfg)
        if not state:
            _setup_error(self, 410, "setup_expired", "The setup window expired.")
            return
        if state.get("username") != getattr(self, "_session_user", ""):
            _setup_error(self, 403, "setup_owner_mismatch", "Setup belongs to another operator.")
            return
        query = _parse_query(self)
        job_id = str((query.get("id") or [""])[0]).strip()
        if not job_id:
            _setup_error(self, 400, "required_field", "Discovery id is required.", field="id")
            return
        resolution = _resolve_setup_discovery_status(
            state,
            job_id,
            _setup_discovery_snapshot(),
        )
        if resolution.kind == "expired":
            _setup_error(self, 410, "discovery_expired", "Discovery state was lost; start discovery again.")
            return
        if resolution.kind == "absent":
            _setup_error(self, 404, "discovery_not_found", "Discovery job was not found.")
            return
        if resolution.kind == "not_found":
            _setup_error(self, 404, "discovery_not_found", "Discovery job was not found.")
            return
        self._json_response(
            {
                "ok": True,
                "schema": ZERO_STATE_WEB_SCHEMA,
                "discovery": _setup_discovery_payload(resolution.job),
            }
        )

    def _serve_setup_contract(self):
        """Create or return the durable normalized discovery contract."""
        if self.command not in {"GET", "POST"}:
            _setup_error(self, 405, "method_not_allowed", "Contract supports GET or POST.")
            return
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        cfg = load_config()
        if _zero_state_setup_complete(cfg):
            _setup_error(self, 403, "setup_closed", "Browser setup is already complete.")
            return
        state = load_setup_state(cfg)
        if not state:
            _setup_error(self, 410, "setup_expired", "The setup window expired.")
            return
        if state.get("username") != getattr(self, "_session_user", ""):
            _setup_error(self, 403, "setup_owner_mismatch", "Setup belongs to another operator.")
            return

        if self.command == "GET":
            resolution = _resolve_setup_contract_get(
                cfg,
                state,
                load_contract=load_setup_contract,
                build_getter=_setup_contract_getter,
            )
            if resolution.kind == "not_found":
                _setup_error(self, 404, "contract_not_found", "No current setup contract exists.")
                return
            self._json_response(
                {
                    "ok": True,
                    "schema": ZERO_STATE_WEB_SCHEMA,
                    "contract": contract_payload(resolution.contract, resolution.getter),
                }
            )
            return

        try:
            body = self._request_body()
            field, code = _setup_forbidden_browser_input(body)
            if field:
                _setup_error(
                    self,
                    400,
                    code,
                    "Server-side paths and manual contracts are not accepted.",
                    field=field,
                )
                return
            if not isinstance(body, dict):
                raise SetupContractError("invalid_json", "JSON object required.")
        except SetupContractError as exc:
            _setup_error(self, exc.status, exc.code, str(exc), field=exc.field, details=exc.details)
            return
        except Exception:
            _setup_error(self, 400, "invalid_json", "Invalid selection contract request.")
            return

        try:
            admission = _admit_setup_contract(
                cfg,
                body,
                getattr(self, "_session_user", ""),
            )
            payload = admission.payload
        except SetupContractError as exc:
            _setup_error(self, exc.status, exc.code, str(exc), field=exc.field, details=exc.details)
            return
        except Exception:
            _setup_error(self, 500, "contract_write_failed", "The setup contract could not be persisted.")
            return
        self._json_response(
            {
                "ok": True,
                "schema": ZERO_STATE_WEB_SCHEMA,
                "contract": payload,
            }
        )

    def _serve_setup_device_credentials(self):
        """Store write-only owned-device values in the setup vault."""
        if self.command != "POST":
            _setup_error(self, 405, "method_not_allowed", "Device credentials require POST.")
            return
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        cfg = load_config()
        if _zero_state_setup_complete(cfg):
            _setup_error(self, 403, "setup_closed", "Browser setup is already complete.")
            return
        state = _observe_setup_state(cfg)
        if not state:
            _setup_error(self, 410, "setup_expired", "The setup window expired.")
            return
        if state.get("username") != getattr(self, "_session_user", ""):
            _setup_error(self, 403, "setup_owner_mismatch", "Setup belongs to another operator.")
            return
        try:
            body = self._request_body()
            field, code = _setup_forbidden_browser_input(body)
            if field:
                _setup_error(
                    self,
                    400,
                    code,
                    "Server-side paths and manual credential inputs are not accepted.",
                    field=field,
                )
                return
        except Exception:
            _setup_error(self, 400, "invalid_json", "Invalid device credential request.")
            return

        try:
            admission = _admit_setup_device_credentials(
                cfg,
                body,
                getattr(self, "_session_user", ""),
            )
            contract = admission.contract
            presence = admission.presence
            ready = admission.ready
        except SetupContractError as exc:
            _setup_error(self, exc.status, exc.code, str(exc), field=exc.field, details=exc.details)
            return
        except Exception:
            _setup_error(self, 500, "credential_store_failed", "Device credentials could not be stored.")
            return
        self._json_response(
            {
                "ok": True,
                "schema": ZERO_STATE_WEB_SCHEMA,
                "contract_id": contract["contract_id"],
                "credentials": [
                    {
                        "resource_id": row["resource_id"],
                        "stored_fields": row["stored_fields"],
                        "complete": row["complete"],
                    }
                    for row in presence
                ],
                "ready": ready,
            }
        )

    def _serve_setup_init_start(self):
        """Start headless init from frozen, value-only zero-state objects."""
        if self.command != "POST":
            _setup_error(self, 405, "method_not_allowed", "Setup init start requires POST.")
            return
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        cfg = load_config()
        if _zero_state_setup_complete(cfg):
            _setup_error(self, 409, "setup_closed", "Browser setup is already complete.")
            return
        state = _observe_setup_state(cfg)
        if not state:
            _setup_error(self, 410, "setup_expired", "The setup window expired.")
            return
        if state.get("username") != getattr(self, "_session_user", ""):
            _setup_error(self, 403, "setup_owner_mismatch", "Setup belongs to another operator.")
            return
        try:
            body = self._request_body()
            field, code = _setup_forbidden_browser_input(body)
            if field:
                _setup_error(
                    self, 400, code,
                    "Server-side paths and manual contracts are not accepted.", field=field,
                )
                return
        except Exception:
            _setup_error(self, 400, "invalid_json", "Invalid setup init request.")
            return

        try:
            admission = _start_setup_init(
                cfg,
                body,
                getattr(self, "_session_user", ""),
            )
        except SetupContractError as exc:
            if exc.code == "init_prepare_failed":
                _setup_error(
                    self,
                    500,
                    "init_prepare_failed",
                    "Setup init could not be prepared.",
                )
                return
            if exc.code == "init_start_failed":
                _setup_error(
                    self,
                    500,
                    "init_start_failed",
                    "Setup init worker could not start.",
                )
                return
            _setup_error(self, exc.status, exc.code, str(exc), field=exc.field, details=exc.details)
            return

        if admission.replay:
            existing = admission.job
            self._json_response(
                {
                    "ok": True,
                    "schema": ZERO_STATE_WEB_SCHEMA,
                    "job": _setup_init_public_job(existing, log_limit=0),
                },
                202,
            )
            return
        job_id = admission.job["id"]
        self._json_response(
            {
                "ok": True,
                "schema": ZERO_STATE_WEB_SCHEMA,
                "job": {"id": job_id, "state": "queued", "poll_after_ms": 1000},
            },
            202,
        )

    def _serve_setup_init_cancel(self):
        """POST /api/setup/init/cancel — request cancellation of one owned init job."""
        if self.command != "POST":
            _setup_error(self, 405, "method_not_allowed", "Setup init cancellation requires POST.")
            return
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        try:
            body = self._request_body()
        except MemoryError:
            raise
        except Exception:
            _setup_error(self, 400, "invalid_json", "Invalid setup init cancellation request.")
            return
        try:
            result = _cancel_setup_init(
                body,
                getattr(self, "_session_user", ""),
            )
        except OSError:
            _setup_error(
                self,
                503,
                "init_cancel_delivery_unknown",
                "Init cancellation outcome is unknown.",
                retryable=False,
            )
            return
        except SetupContractError as exc:
            if exc.code == "init_cancel_delivery_unknown":
                _setup_error(
                    self, 503, "init_cancel_delivery_unknown",
                    "Init cancellation outcome is unknown.", retryable=False,
                )
                return
            if exc.code == "invalid_json":
                _setup_error(self, 400, "invalid_json", "Invalid setup init cancellation request.")
                return
            if exc.code == "unknown_field":
                _setup_error(
                    self,
                    400,
                    "unknown_field",
                    "Setup init cancellation accepts only the init job id.",
                    field=exc.field,
                )
                return
            if exc.code == "required_field":
                _setup_error(self, 400, "required_field", "Init job id is required.", field="id")
                return
            if exc.code == "init_not_found" and exc.field == "id":
                _setup_error(self, 404, "init_not_found", "Init job was not found.")
                return
            if exc.code == "init_not_found":
                _setup_error(self, 404, "init_not_found", "Init job was not found.")
                return
            if exc.code == "init_not_running":
                _setup_error(self, 409, "init_not_running", "Init job is not running.")
                return
            if exc.code == "init_cancel_failed":
                _setup_error(
                    self,
                    500,
                    "init_cancel_failed",
                    "Init cancellation returned an invalid outcome.",
                )
                return
            raise
        job_id = result.job_id
        self._json_response(
            {
                "ok": True,
                "schema": ZERO_STATE_WEB_SCHEMA,
                "cancellation": {
                    "job_id": job_id,
                    "state": _SETUP_INIT_CANCEL_REQUESTED,
                    "poll_after_ms": 250,
                },
            },
            202,
        )

    def _serve_setup_init_status(self):
        """Return one setup-bound init job with bounded redacted output."""
        if self.command != "GET":
            _setup_error(self, 405, "method_not_allowed", "Setup init status requires GET.")
            return
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        cfg = load_config()
        query = _parse_query(self)
        job_id = str((query.get("id") or [""])[0]).strip()
        if not job_id:
            _setup_error(self, 400, "required_field", "Init job id is required.", field="id")
            return
        resolution = _resolve_setup_init_status(
            cfg,
            job_id,
            getattr(self, "_session_user", ""),
        )
        if resolution.kind == "expired":
            _setup_error(self, 410, "init_expired", "Init job state was lost.")
            return
        if resolution.kind == "absent":
            _setup_error(self, 404, "init_not_found", "Init job was not found.")
            return
        if resolution.kind == "not_found":
            _setup_error(self, 404, "init_not_found", "Init job was not found.")
            return
        job = resolution.job
        self._json_response(
            {"ok": True, "schema": ZERO_STATE_WEB_SCHEMA, "job": _setup_init_public_job(job)}
        )

    def _serve_setup_init_logs(self):
        """GET /api/setup/init/logs — return current web-launched init log tail."""
        role, err = _check_session_role(self, "admin")
        if err:
            _setup_error(self, 403, "admin_required", err)
            return
        query = _parse_query(self)
        job_id = str((query.get("id") or [""])[0]).strip()
        if not job_id:
            _setup_error(self, 400, "required_field", "Init job id is required.", field="id")
            return
        resolution = _resolve_setup_init_logs(
            job_id,
            getattr(self, "_session_user", ""),
        )
        if resolution.kind == "not_found":
            _setup_error(self, 404, "init_not_found", "Init job was not found.")
            return
        job = resolution.job
        self._json_response(
            {"ok": True, "schema": ZERO_STATE_WEB_SCHEMA, "job": _setup_init_public_job(job, log_limit=300)}
        )

    # ── Legacy + Main HTML ───────────────────────────────────────────────

    def _serve_setup_page(self):
        """Serve the setup wizard while setup/init has not completed."""
        cfg = load_config()
        if (
            os.path.isfile(os.path.join(cfg.conf_dir, ".initialized"))
            and os.path.isfile(os.path.join(cfg.conf_dir, ".web-setup-complete"))
        ):
            self._serve_app()
            return
        from freq.modules.web_ui import load_setup_html

        body = load_setup_html().encode()
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
        resolution = _resolve_pve_metrics(
            FreqHandler._pve_metrics_cache,
            FreqHandler._pve_metrics_ts,
            FreqHandler._pve_last_seen_ts,
        )
        if resolution.cache_hit:
            self._json_response(FreqHandler._pve_metrics_cache)
            return
        result = resolution.payload
        FreqHandler._pve_metrics_cache = result
        FreqHandler._pve_metrics_ts = resolution.cache_timestamp
        self._json_response(result)

    _pve_rrd_cache = None
    _pve_rrd_ts = 0

    def _serve_pve_rrd(self):
        """PVE RRD time-series data for sparkline charts.

        Returns 1 hour of data (~60 points) per node: CPU%, RAM%, IO wait.
        Cached for 60 seconds — sparklines don't need real-time updates.
        """
        resolution = _resolve_pve_rrd(
            FreqHandler._pve_rrd_cache,
            FreqHandler._pve_rrd_ts,
        )
        if resolution.cache_hit:
            self._json_response(FreqHandler._pve_rrd_cache)
            return
        result = resolution.payload
        FreqHandler._pve_rrd_cache = result
        FreqHandler._pve_rrd_ts = resolution.cache_timestamp
        self._json_response(result)

    def _serve_app(self):
        """Serve the full web UI, or setup wizard on first run."""
        if not _is_first_run():
            self._serve_standard_frontend(app=True)
            return
        from freq.modules.web_ui import load_setup_html

        body = load_setup_html().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_standard_frontend(self, *, app):
        """Publish at most one response from the complete fixed package cohort."""
        self.close_connection = True
        if getattr(self, '_standard_frontend_response_started', False):
            return
        self._standard_frontend_response_started = True
        raw_target = self.path
        if app and raw_target.split('?', 1)[0] not in _standard_asset_policy._APP_TARGETS:
            # Preserve original unrelated SPA reloads with the server-selected
            # app representation from the SAME cohort. This is no standard
            # read endpoint, policy alias, source/ref or admission authority.
            raw_target = '/'
        status, mime, body = 404, 'text/plain; charset=utf-8', b'Frontend unavailable'
        try:
            asset = _standard_assets.get_asset(self.command, raw_target)
        except _standard_assets.AssetUnavailable:
            status = 503
        else:
            if asset is not None:
                selected_mime, body, _ = asset
                status, mime = 200, selected_mime + '; charset=utf-8'
        # No generic JSON/error/legacy loader follows this consumed attempt.
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Connection', 'close')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    # ── Static assets ─────────────────────────────────────────────────

    _STATIC_TYPES = {
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }

    def _serve_static(self, path: str):
        """Serve static web assets from freq/data/web/."""
        # Reject aliases before either fixed selection or legacy package IO.
        # Package paths collapse dot/empty components; none may bypass the
        # cohort policy by reaching its file through the unrelated loader.
        rel = path[len("/static/") :]
        if ".." in rel or any(part in ("", ".") for part in rel.split("/")):
            self.send_error(403)
            return
        if path in _STANDARD_STATIC_PATHS:
            # Detection uses the existing base path; selection keeps the FULL
            # original raw URL. No stale/missing/extra revision normalization.
            self._serve_standard_frontend(app=False)
            return
        try:
            from freq.modules.web_ui import read_asset

            body = read_asset(rel).encode("utf-8")
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

    def _serve_pfsense(self):
        """pfSense data via SSH."""

        cfg = load_config()
        params = _parse_query(self)
        action = params.get("action", ["status"])[0]
        target_name = params.get("target", [""])[0]

        target = _resolve_pfsense_target(cfg, target_name)
        if not target:
            self._json_response({"error": "pfSense target not configured", "data": {}, "target": target_name}, 400)
            return
        resolution = _resolve_pfsense_execution(cfg, action, target)
        pf_ip = resolution.ip
        pf_label = resolution.label
        auth_failed = resolution.auth_failed
        r = resolution
        _redact_device_command_output = str
        self._json_response(
            {
                "action": action,
                "target": pf_label,
                "label": pf_label,
                "host": pf_ip,
                "ip": pf_ip,
                "reachable": r.returncode == 0,
                "auth_failed": auth_failed,
                "probe_method": "ssh_auth_failed"
                if auth_failed
                else ("ssh" if r.returncode == 0 else "ssh_failed"),
                "output": _redact_device_command_output(r.stdout) if r.returncode == 0 else "",
                "error": r.stderr[:100] if r.returncode != 0 else "",
            }
        )

    def _serve_config(self):
        cfg = load_config()
        self._json_response(
            _dashboard_state.build_config_projection(
                cfg,
                _get_discovered_nodes(),
                _load_kill_chain(cfg),
            )
        )

    def _serve_distros(self):
        cfg = load_config()
        distros = _dashboard_state.build_distro_catalog(cfg.distros)
        self._json_response({"distros": distros, "count": len(distros)})

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
        results = _notification_test_results(cfg, jarvis_notify)
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
        containers, registry_configured = _media_activity.media_status_projection(
            cfg, _resolve_container_vm_ip, ssh_single
        )
        self._json_response({
            "containers": containers,
            "count": len(containers),
            "registry_configured": registry_configured,
        })

    def _serve_media_health(self):
        """API health for all media services."""
        cfg = load_config()
        results, skipped = _media_activity.media_health_projection(
            cfg, _resolve_container_vm_ip, ssh_single
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
                    local_downloads, local_source, local_success = (
                        _media_activity.qbit_container_local_downloads(
                            cfg, vm, container, port, _docker_exec_json, _parse_qbit_downloads
                        )
                    )
                    if local_success:
                        downloads.extend(local_downloads)
                        sources.append(local_source)
                        continue

                    vault_downloads, vault_source, vault_warning = (
                        _media_activity.qbit_vault_auth_downloads(
                            cfg,
                            vm,
                            port,
                            vault_get,
                            _media_ssh_single,
                            _parse_qbit_downloads,
                        )
                    )
                    downloads.extend(vault_downloads)
                    if vault_source is not None:
                        sources.append(vault_source)
                    if vault_warning is not None:
                        warnings.append(vault_warning)
                    if (
                        vault_warning is not None
                        and vault_warning["reason"] == "auth_required"
                    ):
                        logger.warn("qBittorrent password not in vault and container-local query was not authorized")
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

        total, running = _media_activity.media_dashboard_counts(
            cfg, health, _resolve_container_vm_ip, ssh_single
        )

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

    # ── Lab Tool generic proxy ────────────────────────────────────────

    LAB_TOOL_REGISTRY = _lab_tool_proxy.LAB_TOOL_REGISTRY
    _lab_tool_request = staticmethod(_lab_tool_proxy.lab_tool_request)

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
        """Return non-secret connection state for a lab tool from vault."""
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
        key_set = False
        try:
            host = vault_get(cfg, tool, f"{tool}_host") or ""
            key_set = bool(vault_get(cfg, tool, f"{tool}_api_key"))
        except Exception as e:
            logger.warn(f"vault read failed for {tool}: {e}")
        self._json_response({"host": host, "key_set": key_set})

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
        except MemoryError:
            raise
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
        except MemoryError:
            raise
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

        def _physical_admin_payload(d):
            display_name = getattr(d, "display_name", "") or ""
            return {
                "ip": d.ip,
                "label": d.label,
                "raw_label": d.label,
                "display_name": display_name,
                "display_label": _operator_physical_display_label(cfg, d),
                "type": d.device_type,
                "tier": d.tier,
                "detail": d.detail,
                "groups": d.groups,
                "scope": d.scope,
            }

        self._json_response(
            {
                "tiers": fb.tiers,
                "categories": cats,
                "physical": {k: _physical_admin_payload(d) for k, d in fb.physical.items()},
                "core_physical": {k: _physical_admin_payload(d) for k, d in fb.physical.items() if d.scope != "lab"},
                "lab_physical": {k: _physical_admin_payload(d) for k, d in fb.physical.items() if d.scope == "lab"},
                "pve_nodes": {k: {"ip": n.ip, "detail": n.detail} for k, n in fb.pve_nodes.items()},
                "hosts": [
                    {
                        "ip": h.ip,
                        "label": h.label,
                        "raw_label": h.label,
                        "display_name": getattr(h, "display_name", "") or "",
                        "display_label": getattr(h, "display_name", "") or h.label,
                        "type": h.htype,
                        "groups": h.groups,
                        "vmid": getattr(h, "vmid", 0),
                        "managed": bool(getattr(h, "managed", True)),
                        "all_ips": h.all_ips,
                    }
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
            if not self._update_fb_toml(fb_path, "category_tier", cat_name=cat_name, tier=new_tier):
                self._json_response({"error": "Fleet configuration update unavailable"}, 500)
                return
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
            if not self._update_fb_toml(fb_path, "add_vmid", cat_name=cat_name, vmid=vmid):
                self._json_response({"error": "Fleet configuration update unavailable"}, 500)
                return
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
            if not self._update_fb_toml(fb_path, "remove_vmid", cat_name=cat_name, vmid=vmid):
                self._json_response({"error": "Fleet configuration update unavailable"}, 500)
                return
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
            if not self._update_fb_toml(fb_path, "update_range", cat_name=cat_name, range_start=rs, range_end=re):
                self._json_response({"error": "Fleet configuration update unavailable"}, 500)
                return
            self._json_response({"ok": True, "action": action})

        elif action == "update_physical_identity":
            device_key = params.get("device", [""])[0]
            if not device_key:
                self._json_response({"error": "device required"}, 400)
                return
            if device_key not in cfg.fleet_boundaries.physical:
                self._json_response({"error": f"Unknown physical device: {device_key}"}, 404)
                return
            updates = {}
            for key in ("display_name", "detail", "groups", "type", "scope"):
                if key in params:
                    updates[key] = params.get(key, [""])[0].strip()
            if "scope" in updates and updates["scope"].lower() not in {"core", "lab"}:
                self._json_response({"error": "scope must be core or lab"}, 400)
                return
            if not updates:
                self._json_response({"error": "at least one identity field required"}, 400)
                return
            if not self._update_fb_toml(fb_path, "update_physical_identity", device_key=device_key, updates=updates):
                self._json_response({"error": "Fleet configuration update unavailable"}, 500)
                return
            self._json_response({"ok": True, "action": action, "device": device_key, "updates": updates})

        elif action == "update_physical_scope":
            device_key = params.get("device", [""])[0]
            scope = params.get("scope", [""])[0].lower()
            if not device_key or scope not in {"core", "lab"}:
                self._json_response({"error": "device and scope=core|lab required"}, 400)
                return
            if device_key not in cfg.fleet_boundaries.physical:
                self._json_response({"error": f"Unknown physical device: {device_key}"}, 404)
                return
            if not self._update_fb_toml(fb_path, "update_physical_scope", device_key=device_key, scope=scope):
                self._json_response({"error": "Fleet configuration update unavailable"}, 500)
                return
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
            if not self._update_fb_toml(fb_path, "update_tier_actions", tier_name=tier_name, actions=actions_list):
                self._json_response({"error": "Fleet configuration update unavailable"}, 500)
                return
            self._json_response({"ok": True, "action": action, "tier": tier_name, "actions": actions_list})

        else:
            self._json_response({"error": f"Unknown action: {action}"}, 400)

    def _update_fb_toml(self, path, op, **kw):
        """One local source transaction outcome; the caller owns HTTP output."""
        from freq.core.read_source_epoch import source_write, SourceWriteUnavailable

        def write_local():
            lines = []
            try:
                with open(path) as f:
                    lines = f.readlines()
            except FileNotFoundError:
                return False

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

            elif op in {"update_physical_scope", "update_physical_identity"}:
                device_key = kw["device_key"]
                updates = dict(kw.get("updates", {}))
                if op == "update_physical_scope":
                    updates = {"scope": kw["scope"]}
                in_physical = False
                inline_pat = re.compile(rf"^(\s*{re.escape(device_key)}\s*=\s*\{{)(.*)(\}}\s*)$")
                key_map = {"type": "type", "display_name": "display_name", "detail": "detail", "groups": "groups", "scope": "scope"}

                def toml_value(value):
                    text = str(value or "")
                    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

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
                    for update_key, value in updates.items():
                        toml_key = key_map.get(update_key)
                        if not toml_key:
                            continue
                        if re.search(rf"\b{re.escape(toml_key)}\s*=", body):
                            body = re.sub(rf'\b{re.escape(toml_key)}\s*=\s*"[^"]*"', f"{toml_key} = {toml_value(value)}", body)
                        else:
                            body = body.rstrip()
                            if body and not body.endswith(","):
                                body += ","
                            body += f" {toml_key} = {toml_value(value)}"
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
            except OSError:
                return False
            return True

        try:
            with source_write():
                return write_local()
        except (OSError, SourceWriteUnavailable):
            return False

    def _serve_admin_hosts_update(self):
        """POST /api/admin/hosts/update — update host fields in hosts.toml.

        Params: label, type (optional), groups (optional), managed (optional)
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
        new_display_name = params.get("display_name", [""])[0] if "display_name" in params else None
        new_managed = params.get("managed", [None])[0] if "managed" in params else None
        if not label:
            self._json_response({"error": "label required"}, 400)
            return

        cfg = load_config()
        host = next((h for h in cfg.hosts if h.label.lower() == label.lower()), None)
        if not host:
            self._json_response({"error": f"Host '{label}' not found in hosts.toml"}, 404)
            return
        if new_type:
            host.htype = new_type
        if new_groups is not None:
            host.groups = new_groups
        if new_display_name is not None:
            host.display_name = new_display_name.strip()
        if new_managed is not None:
            host.managed = str(new_managed).strip().lower() in {"1", "true", "yes", "on", "managed"}

        try:
            save_hosts_toml(cfg.hosts_file, cfg.hosts)
        except OSError as e:
            self._json_response({"error": f"Failed to write hosts.toml: {e}"}, 500)
            return
        with _bg_lock:
            _bg_cache["health"] = None
            _bg_cache_ts["health"] = 0
            _bg_cache_errors.pop("health", None)
        self._json_response(
            {
                "ok": True,
                "label": host.label,
                "raw_label": host.label,
                "display_name": getattr(host, "display_name", "") or "",
                "display_label": getattr(host, "display_name", "") or host.label,
                "type": host.htype,
                "groups": host.groups,
                "managed": bool(host.managed),
            }
        )

    # --- Phase 2: Feature parity endpoints ---

    def _serve_doctor(self):
        """Run FREQ self-diagnostic and return results as JSON."""
        try:
            self._json_response(_dashboard_doctor.run_dashboard_doctor())
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
            self._json_response(_watch_control.run_watch_action("start"))
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
            self._json_response(_watch_control.run_watch_action("stop"))
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
        if not _dns_lookup.allow_lookup(client_ip):
            self._json_response(
                {"error": "Too many DNS lookups. Try again in 5 minutes."},
                429,
            )
            return
        query = _parse_query(self)
        host = query.get("host", [""])[0]
        outcome, ips = _dns_lookup.resolve_hostname(host)
        if outcome == "host_required":
            self._json_response({"error": "host required"}, 400)
            return
        if outcome == "hostname_too_long":
            self._json_response({"error": "Hostname too long"}, 400)
            return
        if outcome == "invalid_hostname":
            self._json_response({"error": "Invalid hostname"}, 400)
            return
        if outcome == "resolution_failed":
            self._json_response(
                {"host": host, "ips": [], "error": "DNS resolution failed"},
                400,
            )
            return
        self._json_response({"host": host, "ips": ips, "count": len(ips)})

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
        response, status = _portscan.scan_ports(
            query.get("host", [""])[0],
            query.get("ports", [""])[0],
        )
        if status is None:
            self._json_response(response)
        else:
            self._json_response(response, status)

    def _serve_backup_schedules(self):
        """List PVE backup schedules from cluster jobs config."""
        self._json_response(_pve_discovery.read_backup_schedules(load_config()))

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
        response, status = _container_action.run_container_action(cfg, host, name, action)
        self._json_response(response, status)

    def _serve_container_logs(self):
        """Get logs from a container on a Docker host."""
        cfg = load_config()
        query = _parse_query(self)
        response, status = _container_logs.read_container_logs(
            cfg,
            query.get("host", [""])[0],
            query.get("name", [""])[0],
            query.get("lines", ["50"])[0],
        )
        self._json_response(response, status)

    def _serve_fleet_connectivity(self):
        """Check SSH connectivity to all fleet hosts.

        Uses the dashboard health cache when available so connectivity matches
        the main fleet view and device-specific auth model. Falls back to a
        live device-aware probe only before the first health cache exists.
        """
        cfg = load_config()
        with _bg_lock:
            health = _bg_cache.get("health")
        response = _fleet_connectivity.probe_fleet_connectivity(cfg, health)
        self._json_response(response)

    def _serve_host_diagnostic(self):
        """Full system diagnostic for a single host."""
        cfg = load_config()
        query = _parse_query(self)
        target = query.get("target", [""])[0]
        from freq.api import terminal as terminal_api

        response, status = _host_diagnostic.run_host_diagnostic(
            cfg,
            target,
            find_live_vm_node_ip=terminal_api._find_live_vm_node_ip,
            guest_agent_network_json=terminal_api._guest_agent_network_json,
            extract_guest_ipv4=terminal_api._extract_guest_ipv4,
        )
        if status is None:
            self._json_response(response)
        else:
            self._json_response(response, status)

    def _request_body(self):
        """Read and parse JSON request body."""
        _require_json_media_type(self)
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        if length > 1_000_000:  # 1MB limit
            raise ValueError("JSON request body exceeds the 1MB limit")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("Invalid JSON request body") from exc

    def _send_security_headers(self):
        """Send the shared application security-header policy."""
        _send_response_security_headers(self)

    def _json_response(self, data, status=200):
        """Send a JSON response."""
        if isinstance(data, dict) and "error" in data and "request_id" not in data:
            data = dict(data)
            data["request_id"] = getattr(self, "_request_id", "")
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
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
        try:
            entries = os_mod.listdir(rdir)
        except FileNotFoundError:
            entries = []
        runbooks = [f.replace(".json", "") for f in entries if f.endswith(".json")]
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
        except MemoryError:
            raise
        except Exception as e:
            logger.warning(f"embedded_watchdog_stopped: {e}")

    threading.Thread(target=_run_watchdog, daemon=True, name="freq-embedded-watchdog").start()
    logger.info("embedded_watchdog_started", port=wd_port)


_READ_ONLY_API_ROUTES = frozenset({
    ("GET", "/api/pve/inventory"),
    ("GET", "/api/pve/endpoints"),
    ("POST", "/api/pve/endpoints"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/verify"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/setup/status"),
    ("POST", "/api/setup/create-admin"),
})


def cmd_serve(cfg, pack, args) -> int:
    """Start the FREQ web dashboard."""
    import signal

    try:
        FreqHandler._load_routes()
    except MemoryError:
        raise
    except Exception as e:
        logger.error("api_route_registry_failed", error=repr(e))
        print(f"FREQ dashboard startup blocked: route registry failed: {e}", file=sys.stderr)
        return 1

    read_only = getattr(args, "read_only", False) is True
    lab_cockpit = getattr(args, "lab_cockpit", False) is True
    if read_only and lab_cockpit:
        return 1
    restricted = read_only or lab_cockpit
    bind = getattr(args, "bind", None) or ("127.0.0.1" if restricted else "0.0.0.0")
    read_only_tls = None
    if restricted:
        # Preflight the actual certificate/key before first-admin delivery or
        # constructing a listening socket. This mode never falls back to HTTP.
        try:
            if not cfg.tls_cert or not cfg.tls_key:
                raise ValueError("TLS certificate and key are required")
            read_only_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            read_only_tls.load_cert_chain(cfg.tls_cert, cfg.tls_key)
        except MemoryError:
            raise
        except Exception:
            print("FREQ restricted startup blocked: valid TLS certificate and key are required.", file=sys.stderr)
            return 1

    try:
        startup_users = _load_users(cfg)
        startup_setup_complete = _setup_marker_exists(cfg)
    except MemoryError:
        raise
    except Exception as exc:
        logger.error("first_admin_observation_failed", error=repr(exc))
        print("FREQ dashboard startup blocked: first-admin state observation failed.", file=sys.stderr)
        return 1

    def _deliver_first_admin_claim(claim_id, raw_claim, generated_at):
        print(
            "  FIRST-ADMIN CLAIM "
            f"generation timestamp={generated_at} claim-id={claim_id} claim={raw_claim}",
            flush=True,
        )

    def _warn_first_admin_claim(message):
        logger.warning("first_admin_claim_reconciliation_warning", message=message)

    try:
        claim_metadata = prepare_first_admin_claim(
            cfg,
            users_present=bool(startup_users),
            setup_complete=bool(startup_setup_complete),
            deliver=_deliver_first_admin_claim,
            warn=_warn_first_admin_claim,
        )
    except ClaimStateError as exc:
        logger.error("first_admin_claim_prepare_failed", error=repr(exc))
        print("FREQ dashboard startup blocked: first-admin claim state is unavailable.", file=sys.stderr)
        return 1

    port = getattr(args, "port", None) or cfg.dashboard_port or 8888
    print("\n  \033[38;5;93mPVE FREQ → Dashboard\033[0m")
    print(f"  Starting on port {port}...\n")
    if not restricted:
        start_background_cache()
        _start_embedded_watchdog_if_needed(cfg)
        _start_cert_renewal_scheduler_if_needed(cfg, _shutdown_flag)

    httpd = ThreadedHTTPServer((bind, port), FreqHandler)
    httpd.freq_read_only = read_only
    httpd.freq_lab_cockpit = lab_cockpit

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

    if not restricted:
        signal.signal(signal.SIGTERM, _sigterm_handler)

    # Wrap in TLS if certs exist
    use_tls = False
    if restricted:
        try:
            httpd.socket = read_only_tls.wrap_socket(httpd.socket, server_side=True)
            use_tls = True
        except BaseException as exc:
            httpd.server_close()
            if not isinstance(exc, Exception) or isinstance(exc, MemoryError):
                raise
            print("FREQ restricted startup blocked: TLS listener could not be initialized.", file=sys.stderr)
            return 1
    elif cfg.tls_cert and cfg.tls_key and os.path.isfile(cfg.tls_cert) and os.path.isfile(cfg.tls_key):
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ssl_ctx.load_cert_chain(cfg.tls_cert, cfg.tls_key)
            httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)
            use_tls = True
        except Exception as e:
            logger.warning(f"dashboard_tls_failed: {e} — falling back to HTTP")

    if restricted:
        signal.signal(signal.SIGTERM, _sigterm_handler)

    proto = "https" if use_tls else "http"
    logger.info("dashboard_start", port=port, host=bind, tls=use_tls)
    claim_id = claim_metadata.get("claim_id", "")
    readiness_claim = f" — first-admin claim-id={claim_id}" if claim_id else ""
    print(f"  \033[38;5;82m✔\033[0m Dashboard running at {proto}://{bind}:{port}{readiness_claim}")
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
        from freq.modules.users import _load_users as _load_users_for_banner
        users = _load_users_for_banner(cfg)
        if users:
            from freq.modules.vault import vault_get
            no_pw = [u["username"] for u in users if not vault_get(cfg, "auth", f"password_{u['username']}")]
            if no_pw:
                print(
                    f"  \033[38;5;220m⚠\033[0m Users without dashboard password: "
                    f"{', '.join(no_pw)}"
                )
                print(
                    "    \033[38;5;245mRecover with: "
                    "sudo freq user dashboard-passwd <user> [--file PATH]\033[0m"
                )
    except Exception:
        pass
    print("  \033[38;5;245mPress Ctrl+C to stop\033[0m\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  \033[38;5;220mDashboard stopped.\033[0m")
    finally:
        httpd.server_close()
        # Kill SSH ControlMaster mux sockets left by background probes.
        # These are forked processes that outlive daemon threads and prevent
        # systemd from cleanly stopping the service.
        if not restricted:
            _cleanup_ssh_mux(cfg)
        logger.info("dashboard_stopped")
    return 0
