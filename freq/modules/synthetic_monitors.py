"""Synthetic monitoring for FREQ — HTTP, TCP, DNS, SSL endpoint checks.

Domain: freq observe monitor <action>
What: Schedule and run synthetic checks against endpoints. Track uptime,
      response times, SSL expiry. Alert on failures.
Replaces: UptimeRobot, Pingdom, StatusCake, Uptime Kuma
Architecture:
    - Checks defined in conf/monitors/checks.json
    - Results stored in conf/monitors/results.json
    - Uses urllib.request for HTTP, socket for TCP/DNS, ssl for TLS
Design decisions:
    - All stdlib. urllib for HTTP, socket for TCP, ssl for TLS.
    - Checks are pull-based — run freq observe monitor run or schedule via cron.
    - Results append-only with rotation (last 1000 per check).
"""
import json
import os
import socket
import ssl
import time
import urllib.request
import urllib.error

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


MONITORS_DIR = "monitors"


def _monitors_dir(cfg):
    path = os.path.join(cfg.conf_dir, MONITORS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_checks(cfg):
    filepath = os.path.join(_monitors_dir(cfg), "checks.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return {"checks": []}


def _save_checks(cfg, data):
    filepath = os.path.join(_monitors_dir(cfg), "checks.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _save_result(cfg, check_name, result):
    filepath = os.path.join(_monitors_dir(cfg), f"results-{check_name}.json")
    existing = []
    if os.path.exists(filepath):
        with open(filepath) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []
    existing.append(result)
    existing = existing[-1000:]
    with open(filepath, "w") as f:
        json.dump(existing, f)


# ---------------------------------------------------------------------------
# Check Implementations
# ---------------------------------------------------------------------------

def _check_http(url, timeout=10):
    """HTTP GET check. Returns (ok, response_ms, status_code, error)."""
    start = time.time()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = int((time.time() - start) * 1000)
            return True, elapsed, resp.status, ""
    except urllib.error.HTTPError as e:
        elapsed = int((time.time() - start) * 1000)
        return e.code < 500, elapsed, e.code, str(e)
    except (urllib.error.URLError, OSError) as e:
        elapsed = int((time.time() - start) * 1000)
        return False, elapsed, 0, str(e)


def _check_tcp(host, port, timeout=5):
    """TCP connect check. Returns (ok, response_ms, error)."""
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = int((time.time() - start) * 1000)
            return True, elapsed, ""
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        elapsed = int((time.time() - start) * 1000)
        return False, elapsed, str(e)


def _check_dns(hostname, timeout=5):
    """DNS resolution check. Returns (ok, response_ms, resolved_ip, error)."""
    start = time.time()
    try:
        socket.setdefaulttimeout(timeout)
        ip = socket.gethostbyname(hostname)
        elapsed = int((time.time() - start) * 1000)
        return True, elapsed, ip, ""
    except socket.gaierror as e:
        elapsed = int((time.time() - start) * 1000)
        return False, elapsed, "", str(e)


def _check_ssl(host, port=443, timeout=5):
    """SSL certificate check. Returns (ok, days_left, cn, error)."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert(binary_form=False)
                if cert:
                    not_after = cert.get("notAfter", "")
                    from datetime import datetime
                    expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                    days_left = (expiry - datetime.utcnow()).days
                    subject = dict(x[0] for x in cert.get("subject", []))
                    return True, days_left, subject.get("commonName", "?"), ""
                return True, -1, "?", "no cert data"
    except Exception as e:
        return False, 0, "", str(e)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_monitor_list(cfg: FreqConfig, pack, args) -> int:
    """List configured monitors."""
    data = _load_checks(cfg)
    checks = data.get("checks", [])

    fmt.header("Monitors", breadcrumb="FREQ > Observe > Monitor")
    fmt.blank()

    if not checks:
        fmt.info("No monitors configured")
        fmt.info("Add: freq observe monitor add --name prod --type http --target https://example.com")
        fmt.footer()
        return 0

    fmt.table_header(("Name", 16), ("Type", 6), ("Target", 36), ("Interval", 10))
    for c in checks:
        fmt.table_row(
            (c.get("name", ""), 16),
            (c.get("type", ""), 6),
            (c.get("target", ""), 36),
            (c.get("interval", "5m"), 10),
        )

    fmt.blank()
    fmt.info(f"{len(checks)} monitor(s)")
    fmt.footer()
    return 0


def cmd_monitor_add(cfg: FreqConfig, pack, args) -> int:
    """Add a monitor check."""
    name = getattr(args, "name", None)
    check_type = getattr(args, "type", None)
    target = getattr(args, "target", None)

    if not name or not check_type or not target:
        fmt.error("Usage: freq observe monitor add --name <name> --type http|tcp|dns|ssl --target <url-or-host>")
        return 1

    data = _load_checks(cfg)
    checks = data.get("checks", [])

    if any(c["name"] == name for c in checks):
        fmt.error(f"Monitor '{name}' already exists")
        return 1

    checks.append({
        "name": name,
        "type": check_type,
        "target": target,
        "interval": getattr(args, "interval", "5m"),
        "created": time.strftime("%Y-%m-%d"),
    })
    data["checks"] = checks
    _save_checks(cfg, data)

    fmt.success(f"Monitor '{name}' added ({check_type}: {target})")
    return 0


def cmd_monitor_run(cfg: FreqConfig, pack, args) -> int:
    """Execute all monitor checks."""
    data = _load_checks(cfg)
    checks = data.get("checks", [])

    if not checks:
        fmt.warn("No monitors configured")
        return 0

    fmt.header("Monitor Run", breadcrumb="FREQ > Observe > Monitor")
    fmt.blank()

    for c in checks:
        name = c.get("name", "?")
        ctype = c.get("type", "")
        target = c.get("target", "")

        if ctype == "http":
            ok, ms, status, err = _check_http(target)
            result = {"ok": ok, "ms": ms, "status": status, "error": err}
            if ok:
                fmt.step_ok(f"{name}: {status} in {ms}ms")
            else:
                fmt.step_fail(f"{name}: {err[:60]}")
        elif ctype == "tcp":
            host, _, port = target.rpartition(":")
            ok, ms, err = _check_tcp(host, int(port))
            result = {"ok": ok, "ms": ms, "error": err}
            if ok:
                fmt.step_ok(f"{name}: connected in {ms}ms")
            else:
                fmt.step_fail(f"{name}: {err[:60]}")
        elif ctype == "dns":
            ok, ms, ip, err = _check_dns(target)
            result = {"ok": ok, "ms": ms, "ip": ip, "error": err}
            if ok:
                fmt.step_ok(f"{name}: {ip} in {ms}ms")
            else:
                fmt.step_fail(f"{name}: {err[:60]}")
        elif ctype == "ssl":
            host = target.split(":")[0] if ":" in target else target
            ok, days, cn, err = _check_ssl(host)
            result = {"ok": ok, "days_left": days, "cn": cn, "error": err}
            if ok and days > 30:
                fmt.step_ok(f"{name}: {cn} — {days} days left")
            elif ok:
                fmt.step_warn(f"{name}: {cn} — {days} days left!")
            else:
                fmt.step_fail(f"{name}: {err[:60]}")
        else:
            result = {"ok": False, "error": f"Unknown type: {ctype}"}
            fmt.step_warn(f"{name}: unknown check type '{ctype}'")

        result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        result["name"] = name
        _save_result(cfg, name, result)

    fmt.blank()
    logger.info("monitor_run", checks=len(checks))
    fmt.footer()
    return 0


def cmd_monitor_remove(cfg: FreqConfig, pack, args) -> int:
    """Remove a monitor."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq observe monitor remove --name <name>")
        return 1

    data = _load_checks(cfg)
    before = len(data.get("checks", []))
    data["checks"] = [c for c in data.get("checks", []) if c.get("name") != name]

    if len(data["checks"]) == before:
        fmt.error(f"Monitor '{name}' not found")
        return 1

    _save_checks(cfg, data)
    fmt.success(f"Monitor '{name}' removed")
    return 0
