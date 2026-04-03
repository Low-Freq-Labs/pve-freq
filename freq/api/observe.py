"""Observe domain API handlers — /api/observe/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for observability: alerts, trends, SLA, capacity,
       monitors, metrics, DB status, and log stats.
Why:   Decouples observability logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.

Maps to monitoring/observability CLI domains. Each handler is a standalone
function that receives the HTTP handler as its first argument.
"""

import time

from freq.api.helpers import json_response, get_params
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.modules.serve import (
    _bg_cache,
    _bg_lock,
    _check_session_role,
    _SERVER_START_TIME,
)


# ── Handlers ────────────────────────────────────────────────────────────


def handle_alert_rules(handler):
    """GET /api/alert/rules — list alert rules and active silences."""
    from freq.modules.alert import _load_rules, _load_silences
    cfg = load_config()
    rules = _load_rules(cfg)
    silences = [s for s in _load_silences(cfg) if s.get("expires", 0) > time.time()]
    json_response(handler, {"rules": rules, "count": len(rules), "silences": silences})


def handle_alert_history(handler):
    """GET /api/alert/history — get alert history."""
    from freq.modules.alert import _load_history
    cfg = load_config()
    history = _load_history(cfg)
    params = get_params(handler)
    limit = int(params.get("limit", ["50"])[0])
    json_response(handler, {"history": history[-limit:], "total": len(history)})


def handle_alert_check(handler):
    """GET /api/alert/check — evaluate alert rules against current fleet state."""
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
    json_response(handler, {"alerts": alerts, "count": len(alerts), "rules_checked": len(rules)})


def handle_alert_silences(handler):
    """GET /api/alert/silences — list active silences."""
    from freq.modules.alert import _load_silences
    cfg = load_config()
    silences = [s for s in _load_silences(cfg) if s.get("expires", 0) > time.time()]
    json_response(handler, {"silences": silences, "count": len(silences)})


def handle_trend_data(handler):
    """GET /api/trend/data — get trend data."""
    from freq.modules.trend import _load_trend_data
    cfg = load_config()
    data = _load_trend_data(cfg)
    params = get_params(handler)
    limit = int(params.get("limit", ["100"])[0])
    json_response(handler, {"snapshots": data[-limit:], "total": len(data)})


def handle_trend_snapshot(handler):
    """GET /api/trend/snapshot — take a trend snapshot."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403); return
    from freq.modules.trend import _take_snapshot, _load_trend_data, _save_trend_data
    cfg = load_config()
    snapshot = _take_snapshot(cfg)
    if snapshot:
        data = _load_trend_data(cfg)
        data.append(snapshot)
        _save_trend_data(cfg, data)
    json_response(handler, {"ok": bool(snapshot), "snapshot": snapshot})


def handle_sla(handler):
    """GET /api/sla — get SLA data."""
    from freq.modules.sla import _load_sla_data, _calculate_sla
    cfg = load_config()
    data = _load_sla_data(cfg)
    params = get_params(handler)
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
    json_response(handler, {"hosts": sla_results, "total_checks": len(data.get("checks", []))})


def handle_sla_check(handler):
    """GET /api/sla/check — record an SLA check."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403); return
    from freq.modules.sla import _record_check
    cfg = load_config()
    _record_check(cfg)
    json_response(handler, {"ok": True})


def handle_capacity(handler):
    """GET /api/capacity — return capacity projections and trend data."""
    from freq.jarvis.capacity import load_snapshots, compute_projections
    cfg = load_config()
    snapshots = load_snapshots(cfg.data_dir)
    projections = compute_projections(snapshots)
    json_response(handler, {
        "projections": projections,
        "snapshot_count": len(snapshots),
        "hosts": len(projections),
    })


def handle_capacity_snapshot(handler):
    """GET /api/capacity/snapshot — force a capacity snapshot now (admin only)."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}); return
    from freq.jarvis.capacity import save_snapshot
    cfg = load_config()
    with _bg_lock:
        health = _bg_cache.get("health")
    if not health:
        json_response(handler, {"error": "No health data available yet"}, 503); return
    fname = save_snapshot(cfg.data_dir, health)
    if fname:
        json_response(handler, {"ok": True, "snapshot": fname})
    else:
        json_response(handler, {"error": "Failed to save snapshot"}, 500)


def handle_capacity_recommend(handler):
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
    json_response(handler, {
        "recommendations": recs,
        "count": len(recs),
        "critical": sum(1 for r in recs if r["urgency"] == "critical"),
        "warning": sum(1 for r in recs if r["urgency"] == "warning"),
    })


def handle_monitors(handler):
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
    json_response(handler, {"monitors": monitors, "count": len(monitors)})


def handle_monitors_check(handler):
    """GET /api/monitors/check — run all HTTP checks now."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403); return
    cfg = load_config()
    if not cfg.monitors:
        json_response(handler, {"results": [], "count": 0})
        return
    from freq.jarvis.patrol import check_http_monitors
    results = check_http_monitors(cfg.monitors)
    ok = sum(1 for r in results if r["ok"])
    json_response(handler, {
        "results": results,
        "count": len(results),
        "healthy": ok,
        "unhealthy": len(results) - ok,
    })


def handle_metrics_prometheus(handler):
    """GET /api/metrics/prometheus — Prometheus-format metrics from background health cache."""
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
    handler.send_response(200)
    handler.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body.encode())


def handle_db_status(handler):
    """GET /api/db/status — live database detection across fleet."""
    cfg = load_config()
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"databases": [], "total": 0})
        return

    command = (
        'PG="no"; MY="no"; CONNS=0; SIZE=0; '
        'if systemctl is-active postgresql >/dev/null 2>&1; then PG="system"; '
        '  CONNS=$(sudo -u postgres psql -t -c "SELECT count(*) FROM pg_stat_activity" 2>/dev/null || echo 0); '
        '  SIZE=$(sudo -u postgres psql -t -c "SELECT pg_database_size(current_database())" 2>/dev/null || echo 0); '
        'elif docker ps --format "{{.Names}}" 2>/dev/null | grep -qi postgres; then PG="docker"; fi; '
        'if systemctl is-active mysql >/dev/null 2>&1 || systemctl is-active mariadb >/dev/null 2>&1; then MY="system"; '
        'elif docker ps --format "{{.Names}}" 2>/dev/null | grep -qi -e mysql -e mariadb; then MY="docker"; fi; '
        'echo "${PG}|${MY}|${CONNS}|${SIZE}"'
    )
    from freq.core.ssh import run_many as ssh_run_many
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    databases = []
    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            continue
        parts = r.stdout.strip().split("|")
        if len(parts) < 4:
            continue
        pg, my = parts[0].strip(), parts[1].strip()
        if pg == "no" and my == "no":
            continue
        try:
            conns = int(parts[2].strip())
        except ValueError:
            conns = 0
        try:
            size = int(parts[3].strip())
        except ValueError:
            size = 0
        databases.append({
            "host": h.label, "postgres": pg, "mysql": my,
            "active_connections": conns, "db_size_bytes": size,
            "db_size_mb": round(size / 1048576, 1) if size > 0 else 0,
        })

    json_response(handler, {"databases": databases, "total": len(databases)})


def handle_logs_stats(handler):
    """GET /api/logs/stats — fleet-wide error pattern analysis."""
    cfg = load_config()
    params = get_params(handler)
    since = params.get("since", ["1h"])[0]
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"patterns": [], "total_errors": 0})
        return

    command = (
        f"journalctl --no-pager --since '-{since}' --priority err --output cat 2>/dev/null | "
        "sort | uniq -c | sort -rn | head -15"
    )
    from freq.core.ssh import run_many as ssh_run_many
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=20,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    pattern_counts = {}
    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0 or not r.stdout.strip():
            continue
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                try:
                    count = int(parts[0])
                    msg = parts[1][:120]
                    pattern_counts[msg] = pattern_counts.get(msg, 0) + count
                except ValueError:
                    pass

    sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
    patterns = [{"pattern": msg, "count": count} for msg, count in sorted_patterns[:20]]
    total = sum(count for _, count in sorted_patterns)

    json_response(handler, {
        "patterns": patterns, "total_errors": total,
        "period": since, "hosts_scanned": len(hosts),
    })


def handle_metrics(handler):
    """GET /api/metrics — collect metrics from fleet agents or SSH fallback."""
    import json
    import urllib.error
    import urllib.request

    cfg = load_config()
    params = get_params(handler)
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

    json_response(handler, {"hosts": results, "count": len(results)})


# ── Route Registration ──────────────────────────────────────────────────


def register(routes: dict):
    """Register observe API routes into the master route table.

    These routes use the same /api/ paths as the legacy serve.py handlers.
    The dispatch in serve.py checks _ROUTES first, then _V1_ROUTES. By
    removing these paths from _ROUTES, dispatch falls through to here.
    """
    routes["/api/alert/rules"] = handle_alert_rules
    routes["/api/alert/history"] = handle_alert_history
    routes["/api/alert/check"] = handle_alert_check
    routes["/api/alert/silences"] = handle_alert_silences
    routes["/api/trend/data"] = handle_trend_data
    routes["/api/trend/snapshot"] = handle_trend_snapshot
    routes["/api/sla"] = handle_sla
    routes["/api/sla/check"] = handle_sla_check
    routes["/api/capacity"] = handle_capacity
    routes["/api/capacity/snapshot"] = handle_capacity_snapshot
    routes["/api/capacity/recommend"] = handle_capacity_recommend
    routes["/api/monitors"] = handle_monitors
    routes["/api/monitors/check"] = handle_monitors_check
    routes["/api/metrics/prometheus"] = handle_metrics_prometheus
    routes["/api/db/status"] = handle_db_status
    routes["/api/logs/stats"] = handle_logs_stats
    routes["/api/metrics"] = handle_metrics
