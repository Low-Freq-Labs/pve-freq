"""Log aggregation API handlers -- fleet-wide log search and analysis.

Who:   New module for centralized log querying.
What:  REST endpoints for fleet-wide journalctl queries via parallel SSH.
Why:   Fleet-wide log search from the dashboard is a killer feature.
Where: Routes registered at /api/logs/*.
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

from freq.api.helpers import json_response, get_param, get_param_int
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single, run_many as ssh_run_many


# -- Helpers -----------------------------------------------------------------

def _log_query(cfg, command, target=None, max_hosts=50):
    """Run a log query across fleet hosts. Returns list of {host, output, ok}."""
    hosts = cfg.hosts
    if not hosts:
        return []

    if target:
        hosts = [h for h in hosts if target.lower() in h.label.lower()]

    results_raw = ssh_run_many(
        hosts=hosts[:max_hosts],
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    results = []
    for h in hosts[:max_hosts]:
        r = results_raw.get(h.label)
        if not r:
            continue
        output = r.stdout.strip() if r.returncode == 0 else ""
        if output:
            results.append({
                "host": h.label,
                "ip": h.ip,
                "output": output[:4000],
                "lines": len(output.splitlines()),
            })

    return results


# -- Handlers ----------------------------------------------------------------


def handle_logs_fleet(handler):
    """GET /api/logs/fleet -- recent errors across fleet.

    Params: ?since=1h&priority=err&target=host-label&limit=30
    """
    cfg = load_config()
    since = get_param(handler, "since", "1 hour ago")
    priority = get_param(handler, "priority", "err")
    target = get_param(handler, "target", "")
    limit = get_param_int(handler, "limit", 30, min_val=5, max_val=100)

    if priority not in ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"):
        priority = "err"

    cmd = f'journalctl --since "{since}" -p {priority} --no-pager -q 2>/dev/null | tail -{limit}'
    results = _log_query(cfg, cmd, target or None)

    total_lines = sum(r["lines"] for r in results)
    json_response(handler, {
        "ok": True,
        "hosts_with_errors": len(results),
        "total_lines": total_lines,
        "since": since,
        "priority": priority,
        "results": results,
    })


def handle_logs_search(handler):
    """GET /api/logs/search -- search logs fleet-wide by pattern.

    Params: ?pattern=error_text&since=24h&target=host-label&limit=20
    """
    cfg = load_config()
    pattern = get_param(handler, "pattern", "")
    since = get_param(handler, "since", "24 hours ago")
    target = get_param(handler, "target", "")
    limit = get_param_int(handler, "limit", 20, min_val=5, max_val=50)

    if not pattern:
        json_response(handler, {"error": "pattern parameter required"}, 400)
        return

    # Sanitize pattern for shell safety
    safe_pattern = pattern.replace("'", "").replace('"', '').replace(";", "").replace("|", "")[:100]

    cmd = f"journalctl --since \"{since}\" --no-pager -q 2>/dev/null | grep -i '{safe_pattern}' | tail -{limit}"
    results = _log_query(cfg, cmd, target or None)

    json_response(handler, {
        "ok": True,
        "pattern": pattern,
        "hosts_matched": len(results),
        "results": results,
    })


def handle_logs_oom(handler):
    """GET /api/logs/oom -- OOM kill events across fleet.

    Params: ?since=24h&target=host-label
    """
    cfg = load_config()
    since = get_param(handler, "since", "24 hours ago")
    target = get_param(handler, "target", "")

    cmd = (
        f'journalctl -k --since "{since}" --no-pager 2>/dev/null | '
        f'grep -iE "oom|out of memory|killed process|invoked oom" | tail -20'
    )
    results = _log_query(cfg, cmd, target or None)

    json_response(handler, {
        "ok": True,
        "hosts_with_oom": len(results),
        "since": since,
        "results": results,
    })


def handle_logs_auth(handler):
    """GET /api/logs/auth -- authentication failures across fleet.

    Params: ?since=24h&target=host-label
    """
    cfg = load_config()
    since = get_param(handler, "since", "24 hours ago")
    target = get_param(handler, "target", "")

    cmd = (
        f'journalctl _SYSTEMD_UNIT=sshd.service --since "{since}" --no-pager 2>/dev/null | '
        f'grep -iE "failed|invalid|refused|denied" | tail -30'
    )
    results = _log_query(cfg, cmd, target or None)

    json_response(handler, {
        "ok": True,
        "hosts_with_failures": len(results),
        "since": since,
        "results": results,
    })


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register log aggregation API routes."""
    routes["/api/logs/fleet"] = handle_logs_fleet
    routes["/api/logs/search"] = handle_logs_search
    routes["/api/logs/oom"] = handle_logs_oom
    routes["/api/logs/auth"] = handle_logs_auth
