"""Local FREQ watchdog daemon.

The watchdog is a local truth-auditor for pve-freq itself. It is deliberately
cache-first and read-only: it reads local config, cache files, and local service
state, then writes a compact status document for the dashboard to display.
It must not become a second fleet scanner.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from freq.core import fmt
from freq.core.config import FreqConfig, load_config


STATUS_DIR = "/var/lib/freq-watchdog"
STATUS_FILE = os.path.join(STATUS_DIR, "status.json")
STATE_FILE = os.path.join(STATUS_DIR, "state.json")
MAX_STATE_CHECKS = 64
DEFAULT_INTERVAL_SECONDS = 15
DEFAULT_CACHE_MAX_AGE_SECONDS = 360
DEFAULT_CONSECUTIVE_THRESHOLD = 2
DEFAULT_STATUS_MAX_AGE_SECONDS = 60

GOOD_STATES = {"live", "healthy", "recovering"}
GOOD_STATUSES = {"healthy", "ok", "up"}
OPERATOR_AUTO_EXCLUDE_LABELS = {"nexus", "pve-freq"}


@dataclass
class Check:
    name: str
    status: str
    summary: str
    evidence: dict[str, Any] | None = None


def _now() -> float:
    return time.time()


def _read_json(path: str) -> tuple[Any, str]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), ""
    except FileNotFoundError:
        return None, "missing"
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"
    except OSError as e:
        return None, f"read failed: {e}"


def _unwrap_cache(data: Any) -> tuple[Any, float]:
    if isinstance(data, dict) and "data" in data:
        return data.get("data"), float(data.get("ts") or 0)
    return data, 0.0


def _age_for_path(path: str, ts: float = 0.0) -> tuple[float | None, str]:
    if ts:
        return _now() - ts, "cache_ts"
    try:
        return _now() - os.path.getmtime(path), "mtime"
    except OSError:
        return None, "missing"


def _atomic_write_json(path: str, data: Any, mode: int = 0o640) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_state(path: str = STATE_FILE) -> dict[str, Any]:
    data, err = _read_json(path)
    if err or not isinstance(data, dict):
        return {"checks": {}}
    if not isinstance(data.get("checks"), dict):
        data["checks"] = {}
    return data


def _save_state(state: dict[str, Any], path: str = STATE_FILE) -> None:
    checks = state.get("checks")
    if isinstance(checks, dict) and len(checks) > MAX_STATE_CHECKS:
        state["checks"] = dict(list(checks.items())[-MAX_STATE_CHECKS:])
    state["updated_at"] = _now()
    _atomic_write_json(path, state)


def _cache_file(cfg: FreqConfig, name: str) -> str:
    return os.path.join(cfg.data_dir, "cache", f"{name}.json")


def _label_key(value: str) -> str:
    return str(value or "").strip().lower()


def _host_indexes(cfg: FreqConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    by_label: dict[str, Any] = {}
    by_ip: dict[str, Any] = {}
    for host in getattr(cfg, "hosts", []) or []:
        label = _label_key(getattr(host, "label", ""))
        ip = str(getattr(host, "ip", "") or "").strip()
        if label:
            by_label[label] = host
        if ip:
            by_ip[ip] = host
    return by_label, by_ip


def _cache_item_in_watchdog_contract(cfg: FreqConfig, item: dict[str, Any], by_label: dict[str, Any], by_ip: dict[str, Any]) -> bool:
    """True when a cached health/infra item belongs in watchdog's hard red count."""
    label = _label_key(item.get("label") or item.get("key") or item.get("name"))
    if label in OPERATOR_AUTO_EXCLUDE_LABELS:
        return False

    ip = str(item.get("ip", "") or "").strip()
    host = by_label.get(label) or by_ip.get(ip)
    if host is None:
        return True
    if not getattr(host, "managed", True):
        return False
    if _label_key(getattr(host, "label", "")) in OPERATOR_AUTO_EXCLUDE_LABELS:
        return False

    vmid = int(getattr(host, "vmid", 0) or 0)
    boundaries = getattr(cfg, "fleet_boundaries", None)
    if vmid and boundaries and hasattr(boundaries, "categorize"):
        try:
            category, _tier = boundaries.categorize(vmid)
        except Exception:
            category = ""
        if category in {"out_of_contract", "templates"}:
            return False

    pve_node_ips = set(getattr(cfg, "pve_nodes", []) or [])
    if getattr(host, "htype", "") == "pve" and getattr(host, "ip", "") not in pve_node_ips:
        return False
    return True


def _check_initialized(cfg: FreqConfig) -> Check:
    marker = os.path.join(cfg.conf_dir, ".initialized")
    if os.path.isfile(marker):
        return Check("initialized_marker", "pass", ".initialized marker present", {"path": marker})
    return Check("initialized_marker", "warn", ".initialized marker missing", {"path": marker})


def _is_container_runtime() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    path = Path("/proc/1/cgroup")
    if not path.is_file():
        return False
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return False
    return any(token in text for token in ("docker", "kubepods", "containerd"))


def _check_freq_serve_systemd() -> Check:
    if _is_container_runtime():
        return Check(
            "freq_serve_runtime",
            "pass",
            "container runtime supervises freq serve",
            {"runtime": "container"},
        )
    if not shutil.which("systemctl"):
        return Check("freq_serve_systemd", "warn", "systemctl unavailable; cannot verify freq-serve")
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "freq-serve.service"],
            text=True,
            capture_output=True,
            timeout=1.5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Check("freq_serve_systemd", "warn", "systemctl is-active timed out")
    except OSError as e:
        return Check("freq_serve_systemd", "warn", f"systemctl check failed: {e}")
    state = (r.stdout or r.stderr or "").strip()
    if r.returncode == 0 and state == "active":
        return Check("freq_serve_systemd", "pass", "freq-serve.service active", {"systemd_state": state})
    return Check("freq_serve_systemd", "fail", "freq-serve.service is not active", {"systemd_state": state or "unknown"})


def _check_dashboard_port(cfg: FreqConfig) -> Check:
    port = int(getattr(cfg, "dashboard_port", 8888) or 8888)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.35)
    try:
        rc = sock.connect_ex(("127.0.0.1", port))
    finally:
        sock.close()
    if rc == 0:
        return Check("dashboard_port", "pass", f"dashboard port {port} listening", {"host": "127.0.0.1", "port": port})
    return Check("dashboard_port", "fail", f"dashboard port {port} not listening", {"host": "127.0.0.1", "port": port, "connect_ex": rc})


def _check_health_cache(cfg: FreqConfig, max_age: int) -> tuple[Check, dict[str, Any]]:
    path = _cache_file(cfg, "health")
    raw, err = _read_json(path)
    if err:
        return Check("health_cache", "warn", f"health cache {err}", {"path": path}), {}
    data, ts = _unwrap_cache(raw)
    if not isinstance(data, dict):
        return Check("health_cache", "fail", "health cache shape invalid", {"path": path}), {}

    hosts = data.get("hosts") or []
    age = _now() - ts if ts else None
    bad_hosts = []
    by_label, by_ip = _host_indexes(cfg)
    for host in hosts:
        if not isinstance(host, dict):
            continue
        if not _cache_item_in_watchdog_contract(cfg, host, by_label, by_ip):
            continue
        state = str(host.get("state") or "").lower()
        status = str(host.get("status") or "").lower()
        if (state and state not in GOOD_STATES) or (status and status not in GOOD_STATUSES):
            bad_hosts.append(
                {
                    "label": host.get("label", ""),
                    "state": host.get("state", ""),
                    "status": host.get("status", ""),
                    "reason": host.get("reason", ""),
                }
            )

    if age is not None and age > max_age:
        return Check("health_cache", "fail", f"health cache stale ({int(age)}s old)", {"path": path, "age_seconds": round(age, 1), "hosts": len(hosts)}), data
    if bad_hosts:
        return Check("health_cache", "fail", f"{len(bad_hosts)} host health issue(s)", {"path": path, "hosts": len(hosts), "bad_hosts": bad_hosts[:10]}), data
    return Check("health_cache", "pass", f"health cache fresh with {len(hosts)} host(s)", {"path": path, "age_seconds": round(age or 0, 1), "hosts": len(hosts)}), data


def _check_infra_quick(cfg: FreqConfig, max_age: int) -> Check:
    path = _cache_file(cfg, "infra_quick")
    raw, err = _read_json(path)
    if err:
        return Check("infra_quick", "warn", f"infra quick cache {err}", {"path": path})
    data, ts = _unwrap_cache(raw)
    if not isinstance(data, dict):
        return Check("infra_quick", "fail", "infra quick cache shape invalid", {"path": path})
    age, age_source = _age_for_path(path, ts)
    devices = data.get("devices") or []
    core = data.get("core_devices") or []
    by_label, by_ip = _host_indexes(cfg)
    leaked_lab = [
        d.get("label") or d.get("key")
        for d in core
        if isinstance(d, dict)
        and _cache_item_in_watchdog_contract(cfg, d, by_label, by_ip)
        and (str(d.get("scope") or "").lower() == "lab" or str(d.get("groups") or "").lower() == "lab")
    ]
    bad = [
        d.get("label") or d.get("key")
        for d in devices
        if isinstance(d, dict)
        and _cache_item_in_watchdog_contract(cfg, d, by_label, by_ip)
        and (d.get("auth_failed") or d.get("reachable") is False)
    ]
    evidence = {
        "path": path,
        "age_seconds": round(age, 1) if age is not None else None,
        "age_source": age_source,
        "max_age_seconds": max_age,
        "devices": len(devices),
        "core_devices": len(core),
    }
    if age is not None and age > max_age:
        return Check("infra_quick", "fail", f"infra quick cache stale ({int(age)}s old)", evidence)
    if leaked_lab:
        evidence["lab_in_core"] = leaked_lab[:10]
        return Check("infra_quick", "fail", f"{len(leaked_lab)} lab device(s) leaked into core infra", evidence)
    if bad:
        evidence["bad_devices"] = bad[:10]
        return Check("infra_quick", "fail", f"{len(bad)} infra device issue(s)", evidence)
    return Check("infra_quick", "pass", f"infra quick clean ({len(core)} core / {len(devices)} total)", evidence)


def _check_alert_contract(cfg: FreqConfig, health_data: dict[str, Any]) -> Check:
    cache_dir = os.path.join(cfg.data_dir, "cache")
    history_path = os.path.join(cache_dir, "alert_history.json")
    state_path = os.path.join(cache_dir, "rule_state.json")
    history, hist_err = _read_json(history_path)
    state, state_err = _read_json(state_path)
    hist_age, hist_age_source = _age_for_path(history_path)
    state_age, state_age_source = _age_for_path(state_path)
    false_ram = []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            rule = item.get("rule_name") or item.get("rule") or ""
            host = item.get("host") or ""
            msg = item.get("message") or ""
            if rule == "ram-pressure" and (host in {"truenas", "truenas-lab"} or "**truenas**" in msg or "**truenas-lab**" in msg):
                false_ram.append(host or msg[:80])
    false_state = []
    if isinstance(state, dict):
        false_state = [k for k in state if k in {"ram-pressure:truenas", "ram-pressure:truenas-lab"}]

    try:
        from freq.jarvis.rules import evaluate_rules, load_rules

        would_fire = evaluate_rules(health_data or {"hosts": []}, load_rules(cfg.conf_dir), {})
    except Exception as e:
        return Check("alert_contract", "warn", f"could not evaluate alert rules: {e}")

    evidence = {
        "history_error": hist_err,
        "state_error": state_err,
        "history_age_seconds": round(hist_age, 1) if hist_age is not None else None,
        "history_age_source": hist_age_source,
        "state_age_seconds": round(state_age, 1) if state_age is not None else None,
        "state_age_source": state_age_source,
        "history_entries": len(history) if isinstance(history, list) else 0,
        "would_fire": len(would_fire),
    }
    if false_ram or false_state:
        evidence["false_ram_history"] = false_ram[:10]
        evidence["false_ram_state"] = false_state[:10]
        return Check("alert_contract", "fail", "stale false TrueNAS/lab RAM alert state present", evidence)
    if would_fire:
        evidence["alerts"] = [{"rule": a.rule_name, "host": a.host, "message": a.message} for a in would_fire[:10]]
        return Check("alert_contract", "warn", f"{len(would_fire)} alert rule(s) would fire", evidence)
    return Check("alert_contract", "pass", "alert contract clean", evidence)


def _apply_transient_dampening(checks: list[Check], state: dict[str, Any], threshold: int) -> list[dict[str, Any]]:
    check_state = state.setdefault("checks", {})
    rendered = []
    seen = set()
    for check in checks:
        seen.add(check.name)
        entry = check_state.setdefault(check.name, {"consecutive": 0, "last_status": "pass"})
        if check.status == "pass":
            entry["consecutive"] = 0
            entry["last_status"] = "pass"
            status = "pass"
        else:
            entry["consecutive"] = int(entry.get("consecutive") or 0) + 1
            entry["last_status"] = check.status
            status = check.status if entry["consecutive"] >= threshold else "pending"
        entry["summary"] = check.summary
        entry["updated_at"] = _now()
        rendered.append(
            {
                "name": check.name,
                "status": status,
                "raw_status": check.status,
                "consecutive": entry["consecutive"],
                "summary": check.summary,
                "evidence": check.evidence or {},
            }
        )

    for key in list(check_state.keys()):
        if key not in seen:
            del check_state[key]
    return rendered


def _freshen_status_for_read(data: dict[str, Any], max_age: int = DEFAULT_STATUS_MAX_AGE_SECONDS) -> dict[str, Any]:
    rendered = dict(data)
    checked_at = rendered.get("checked_at")
    if checked_at:
        try:
            age = _now() - float(checked_at)
        except (TypeError, ValueError):
            age = None
        if age is not None:
            rendered["age_seconds"] = round(age, 1)
            if age > max_age:
                rendered["ok"] = False
                rendered["status"] = "stale"
                rendered["errors"] = max(1, int(rendered.get("errors") or 0))
                rendered.setdefault("failures", [])
                if "watchdog status stale" not in rendered["failures"]:
                    rendered["failures"].append(f"watchdog status stale ({int(age)}s old)")
    return rendered


def evaluate(cfg: FreqConfig, *, state: dict[str, Any] | None = None, max_age: int = DEFAULT_CACHE_MAX_AGE_SECONDS, threshold: int = DEFAULT_CONSECUTIVE_THRESHOLD) -> dict[str, Any]:
    """Run one local watchdog evaluation. No fleet network probes are performed."""
    started = time.monotonic()
    if state is None:
        state = {"checks": {}}

    checks: list[Check] = [
        _check_initialized(cfg),
        _check_freq_serve_systemd(),
        _check_dashboard_port(cfg),
    ]
    health_check, health_data = _check_health_cache(cfg, max_age)
    checks.append(health_check)
    checks.append(_check_infra_quick(cfg, max_age))
    checks.append(_check_alert_contract(cfg, health_data))

    rendered = _apply_transient_dampening(checks, state, threshold)
    failures = [c for c in rendered if c["status"] == "fail"]
    warnings = [c for c in rendered if c["status"] == "warn"]
    pending = [c for c in rendered if c["status"] == "pending"]
    health_hosts = 0
    if isinstance(health_data, dict):
        health_hosts = len(health_data.get("hosts") or [])

    if failures:
        status = "failing"
    elif warnings:
        status = "degraded"
    elif pending:
        status = "pending"
    else:
        status = "healthy"

    return {
        "ok": not failures,
        "watchdog_installed": True,
        "status": status,
        "checked_at": _now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "hosts": health_hosts,
        "errors": len(failures) + len(warnings),
        "pending_count": len(pending),
        "warnings": [c["summary"] for c in warnings],
        "failures": [c["summary"] for c in failures],
        "pending": [c["summary"] for c in pending],
        "checks": rendered,
    }


class _WatchdogHandler(BaseHTTPRequestHandler):
    server_version = "freq-watchdog"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/", "/healthz", "/api/watchdog/health"}:
            self._json({"error": "not found"}, 404)
            return
        status = getattr(self.server, "latest_status", None) or {"ok": False, "status": "starting", "watchdog_installed": True}
        status = _freshen_status_for_read(status)
        self._json(status, 200 if status.get("ok", False) else 200)

    def log_message(self, _fmt, *_args):
        return

    def _json(self, data: dict[str, Any], code: int = 200):
        body = json.dumps(data, sort_keys=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve_http(port: int, stop: threading.Event, latest: dict[str, Any]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), _WatchdogHandler)
    server.latest_status = latest

    def run():
        while not stop.is_set():
            server.handle_request()

    thread = threading.Thread(target=run, daemon=True, name="freq-watchdog-http")
    thread.start()
    return server


def run_daemon(cfg: FreqConfig, *, interval: int = DEFAULT_INTERVAL_SECONDS, status_file: str = STATUS_FILE, state_file: str = STATE_FILE, once: bool = False) -> dict[str, Any]:
    state = _load_state(state_file)
    latest: dict[str, Any] = {"ok": False, "status": "starting", "watchdog_installed": True}
    stop = threading.Event()
    server = None
    if not once:
        server = _serve_http(int(getattr(cfg, "watchdog_port", 9900) or 9900), stop, latest)
    try:
        while True:
            status = evaluate(cfg, state=state)
            latest.clear()
            latest.update(status)
            _save_state(state, state_file)
            _atomic_write_json(status_file, status, mode=0o644)
            if once:
                return status
            time.sleep(max(5, int(interval)))
    finally:
        stop.set()
        if server is not None:
            try:
                # Unblock handle_request without depending on external traffic.
                with socket.create_connection(("127.0.0.1", int(getattr(cfg, "watchdog_port", 9900) or 9900)), timeout=0.2):
                    pass
            except OSError:
                pass
            server.server_close()


def load_status(path: str = STATUS_FILE) -> dict[str, Any]:
    data, err = _read_json(path)
    if err or not isinstance(data, dict):
        return {"ok": False, "watchdog_installed": False, "status": "not_installed", "error": err or "invalid status"}
    return _freshen_status_for_read(data)


def _print_status(data: dict[str, Any]) -> None:
    status = data.get("status", "unknown")
    color = fmt.C.GREEN if status == "healthy" else fmt.C.YELLOW if status in {"degraded", "pending"} else fmt.C.RED
    fmt.header("FREQ Watchdog")
    fmt.blank()
    fmt.line(f"  Status: {color}{status}{fmt.C.RESET}")
    fmt.line(f"  Hosts observed from cache: {data.get('hosts', 0)}")
    if data.get("age_seconds") is not None:
        fmt.line(f"  Status age: {data.get('age_seconds')}s")
    fmt.blank()
    for check in data.get("checks", []) or []:
        mark = fmt.S.TICK if check.get("status") == "pass" else fmt.S.WARN if check.get("status") in {"warn", "pending"} else fmt.S.CROSS
        fmt.line(f"  {mark} {check.get('name')}: {check.get('status')} — {check.get('summary')}")
    fmt.blank()
    fmt.footer()


def cmd_watchdog(cfg: FreqConfig, _pack, args: argparse.Namespace) -> int:
    action = getattr(args, "action", None) or "status"
    status_file = getattr(args, "status_file", None) or STATUS_FILE
    state_file = getattr(args, "state_file", None) or STATE_FILE

    if action == "status":
        _print_status(load_status(status_file))
        return 0
    if action == "once":
        data = run_daemon(cfg, status_file=status_file, state_file=state_file, once=True)
        _print_status(data)
        return 0 if data.get("ok") else 1
    if action == "run":
        interval = getattr(args, "interval", None) or DEFAULT_INTERVAL_SECONDS
        run_daemon(cfg, interval=interval, status_file=status_file, state_file=state_file)
        return 0
    raise SystemExit(f"unknown watchdog action: {action}")


def cmd_watch(cfg: FreqConfig, pack, args: argparse.Namespace) -> int:
    """Backward-compatible observe watch entry point."""
    return cmd_watchdog(cfg, pack, args)
