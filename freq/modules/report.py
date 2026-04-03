"""Fleet report generator for FREQ.

Domain: freq observe <report-generate|report-schedule|report-list>

Auto-generated fleet digest. Aggregates health, alerts, capacity, and
changes into a single report. Terminal, JSON, or Markdown output for
Discord, email, or Obsidian. Cron it and forget it.

Replaces: Datadog reports ($15/host/mo), New Relic digest emails,
          hand-written weekly status updates

Architecture:
    - Health metrics gathered via parallel SSH across fleet
    - PVE cluster data via pvesh for VM counts and resource totals
    - Alert and change data pulled from freq journal and alert history
    - Reports persisted in conf/reports/ as timestamped JSON/Markdown

Design decisions:
    - Reports are snapshots, not live dashboards. Generated once, stored,
      and shareable. Designed for async consumption (Discord, email).
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many

# Report storage
REPORT_DIR = "reports"
REPORT_CMD_TIMEOUT = 15
REPORT_PVE_TIMEOUT = 30


def _report_dir(cfg: FreqConfig) -> str:
    """Get or create reports directory."""
    path = os.path.join(cfg.conf_dir, REPORT_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _gather_fleet_health(cfg: FreqConfig) -> dict:
    """Gather fleet health metrics."""
    hosts = cfg.hosts
    if not hosts:
        return {"hosts": [], "up": 0, "down": 0, "total": 0}

    command = (
        'echo "$('
        "nproc"
        ")|$("
        "cat /proc/loadavg | awk '{print $1}'"
        ")|$("
        "free -m | awk '/Mem:/ {printf \"%d|%d\", $3, $2}'"
        ")|$("
        "df -h / | awk 'NR==2 {print $5}' | tr -d '%'"
        ")|$("
        "cat /proc/uptime | awk '{d=int($1/86400); printf \"%d\", d}'"
        ")|$("
        "docker ps -q 2>/dev/null | wc -l || echo 0"
        ')"'
    )

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=REPORT_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    host_data = []
    up = 0
    down = 0
    total_cores = 0
    total_ram = 0
    total_containers = 0

    for h in hosts:
        r = results.get(h.label)
        entry = {"label": h.label, "ip": h.ip, "type": h.htype, "status": "down"}

        if r and r.returncode == 0:
            entry["status"] = "up"
            up += 1
            parts = r.stdout.strip().split("|")
            if len(parts) >= 6:
                try:
                    entry["cores"] = int(parts[0])
                    entry["load"] = float(parts[1])
                    entry["ram_used"] = int(parts[2])
                    entry["ram_total"] = int(parts[3])
                    entry["ram_pct"] = round(entry["ram_used"] / max(entry["ram_total"], 1) * 100, 1)
                    entry["disk_pct"] = int(parts[4])
                    entry["uptime_days"] = int(parts[5])
                    entry["containers"] = int(parts[6]) if len(parts) > 6 else 0
                    total_cores += entry["cores"]
                    total_ram += entry["ram_total"]
                    total_containers += entry.get("containers", 0)
                except (ValueError, IndexError):
                    pass
        else:
            down += 1

        host_data.append(entry)

    return {
        "hosts": host_data,
        "up": up,
        "down": down,
        "total": len(hosts),
        "total_cores": total_cores,
        "total_ram_mb": total_ram,
        "total_containers": total_containers,
    }


def _gather_vm_summary(cfg: FreqConfig) -> dict:
    """Gather VM summary from PVE."""
    if not cfg.pve_nodes:
        return {"total": 0, "running": 0, "stopped": 0}

    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip,
            command="pvesh get /cluster/resources --type vm --output-format json 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=REPORT_PVE_TIMEOUT,
            htype="pve",
            use_sudo=True,
        )
        if r.returncode == 0:
            try:
                vms = json.loads(r.stdout)
                running = sum(1 for v in vms if v.get("status") == "running")
                stopped = len(vms) - running
                return {"total": len(vms), "running": running, "stopped": stopped}
            except json.JSONDecodeError:
                pass

    return {"total": 0, "running": 0, "stopped": 0}


def _gather_alert_summary(cfg: FreqConfig) -> dict:
    """Gather alert history summary."""
    try:
        from freq.modules.alert import _load_history, _load_rules

        history = _load_history(cfg)
        rules = _load_rules(cfg)

        # Count alerts in last 24h
        cutoff = time.time() - 86400
        recent = [e for e in history if e.get("epoch", 0) > cutoff and e.get("fired")]
        by_severity = {"critical": 0, "warning": 0, "info": 0}
        for e in recent:
            sev = e.get("severity", "info")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return {
            "rules_total": len(rules),
            "rules_active": sum(1 for r in rules if r.get("enabled", True)),
            "alerts_24h": len(recent),
            "by_severity": by_severity,
        }
    except ImportError:
        return {"rules_total": 0, "rules_active": 0, "alerts_24h": 0, "by_severity": {}}


def _find_issues(health: dict) -> list:
    """Identify issues from health data."""
    issues = []
    for h in health.get("hosts", []):
        if h["status"] == "down":
            issues.append({"host": h["label"], "type": "critical", "message": "Host DOWN"})
            continue
        if h.get("disk_pct", 0) >= 90:
            issues.append({"host": h["label"], "type": "critical", "message": f"Disk at {h['disk_pct']}%"})
        elif h.get("disk_pct", 0) >= 80:
            issues.append({"host": h["label"], "type": "warning", "message": f"Disk at {h['disk_pct']}%"})
        if h.get("ram_pct", 0) >= 95:
            issues.append({"host": h["label"], "type": "critical", "message": f"RAM at {h['ram_pct']}%"})
        elif h.get("ram_pct", 0) >= 85:
            issues.append({"host": h["label"], "type": "warning", "message": f"RAM at {h['ram_pct']}%"})
        cores = h.get("cores", 1)
        load = h.get("load", 0)
        if cores and load > cores * 2:
            issues.append(
                {"host": h["label"], "type": "warning", "message": f"Load {load:.1f} ({load / cores:.1f}x cores)"}
            )
    return issues


def _generate_report(cfg: FreqConfig) -> dict:
    """Generate a complete fleet report."""
    health = _gather_fleet_health(cfg)
    vms = _gather_vm_summary(cfg)
    alerts = _gather_alert_summary(cfg)
    issues = _find_issues(health)

    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "period": "snapshot",
        "health": health,
        "vms": vms,
        "alerts": alerts,
        "issues": issues,
        "issue_count": len(issues),
        "critical_count": sum(1 for i in issues if i["type"] == "critical"),
    }


def _report_to_markdown(report: dict) -> str:
    """Convert report to markdown format."""
    ts = report.get("timestamp", "")[:19]
    h = report.get("health", {})
    v = report.get("vms", {})
    a = report.get("alerts", {})
    issues = report.get("issues", [])

    lines = [
        f"# FREQ Fleet Report",
        f"**Generated:** {ts}",
        "",
        "## Fleet Status",
        f"- **Hosts:** {h.get('up', 0)}/{h.get('total', 0)} up",
        f"- **Total Cores:** {h.get('total_cores', 0)}",
        f"- **Total RAM:** {h.get('total_ram_mb', 0)} MB",
        f"- **Containers:** {h.get('total_containers', 0)}",
        "",
        "## Virtual Machines",
        f"- **Total:** {v.get('total', 0)}",
        f"- **Running:** {v.get('running', 0)}",
        f"- **Stopped:** {v.get('stopped', 0)}",
        "",
        "## Alerts (24h)",
        f"- **Fired:** {a.get('alerts_24h', 0)}",
        f"- **Rules:** {a.get('rules_active', 0)} active / {a.get('rules_total', 0)} total",
    ]

    if issues:
        lines.extend(["", "## Issues"])
        for issue in issues:
            icon = "🔴" if issue["type"] == "critical" else "🟡"
            lines.append(f"- {icon} **{issue['host']}:** {issue['message']}")
    else:
        lines.extend(["", "## Issues", "✅ No issues detected."])

    return "\n".join(lines)


def cmd_report(cfg: FreqConfig, pack, args) -> int:
    """Generate fleet report."""
    action = getattr(args, "action", None) or "generate"
    output_format = "json" if getattr(args, "json", False) else "table"
    if getattr(args, "markdown", False):
        output_format = "markdown"

    if action == "generate":
        return _cmd_generate(cfg, args, output_format)

    fmt.error(f"Unknown report action: {action}")
    return 1


def _cmd_generate(cfg: FreqConfig, args, output_format: str) -> int:
    """Generate and display a fleet report."""
    fmt.header("Fleet Report")
    fmt.blank()

    fmt.step_start("Gathering fleet data")
    report = _generate_report(cfg)
    fmt.step_ok("Data collected")
    fmt.blank()

    # Save report
    report_path = os.path.join(_report_dir(cfg), f"report-{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    if output_format == "json":
        print(json.dumps(report, indent=2))
        return 0

    if output_format == "markdown":
        print(_report_to_markdown(report))
        return 0

    # Table output
    h = report["health"]
    v = report["vms"]
    a = report["alerts"]
    issues = report["issues"]

    # Fleet overview
    fmt.divider("Fleet Overview")
    fmt.blank()
    up_color = fmt.C.GREEN if h["down"] == 0 else fmt.C.YELLOW
    fmt.line(f"  Hosts:      {up_color}{h['up']}/{h['total']} up{fmt.C.RESET}")
    fmt.line(f"  Cores:      {h['total_cores']}")
    fmt.line(f"  RAM:        {h['total_ram_mb']} MB")
    fmt.line(f"  Containers: {h['total_containers']}")
    fmt.blank()

    # VMs
    fmt.divider("Virtual Machines")
    fmt.blank()
    fmt.line(f"  Total:   {v['total']}")
    fmt.line(f"  Running: {fmt.C.GREEN}{v['running']}{fmt.C.RESET}")
    fmt.line(f"  Stopped: {fmt.C.RED}{v['stopped']}{fmt.C.RESET}")
    fmt.blank()

    # Alerts
    fmt.divider("Alerts (24h)")
    fmt.blank()
    if a["alerts_24h"] > 0:
        fmt.line(f"  {fmt.C.RED}{fmt.S.WARN} {a['alerts_24h']} alert(s) fired{fmt.C.RESET}")
        by_sev = a.get("by_severity", {})
        if by_sev.get("critical"):
            fmt.line(f"    {fmt.C.RED}Critical: {by_sev['critical']}{fmt.C.RESET}")
        if by_sev.get("warning"):
            fmt.line(f"    {fmt.C.YELLOW}Warning:  {by_sev['warning']}{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} No alerts in the last 24 hours{fmt.C.RESET}")
    fmt.line(f"  Rules: {a['rules_active']} active / {a['rules_total']} total")
    fmt.blank()

    # Host details
    fmt.divider("Host Health")
    fmt.blank()
    fmt.table_header(
        ("HOST", 14),
        ("STATUS", 8),
        ("LOAD", 8),
        ("RAM", 8),
        ("DISK", 8),
        ("UPTIME", 10),
        ("DOCKER", 8),
    )
    for host in h["hosts"]:
        if host["status"] == "down":
            fmt.table_row(
                (f"{fmt.C.BOLD}{host['label']}{fmt.C.RESET}", 14),
                (fmt.badge("down"), 8),
                ("-", 8),
                ("-", 8),
                ("-", 8),
                ("-", 10),
                ("-", 8),
            )
            continue

        load = host.get("load", 0)
        cores = host.get("cores", 1)
        load_color = fmt.C.RED if load > cores * 2 else (fmt.C.YELLOW if load > cores else "")
        ram_pct = host.get("ram_pct", 0)
        ram_color = fmt.C.RED if ram_pct > 95 else (fmt.C.YELLOW if ram_pct > 80 else "")
        disk_pct = host.get("disk_pct", 0)
        disk_color = fmt.C.RED if disk_pct > 90 else (fmt.C.YELLOW if disk_pct > 75 else "")

        fmt.table_row(
            (f"{fmt.C.BOLD}{host['label']}{fmt.C.RESET}", 14),
            (fmt.badge("up"), 8),
            (f"{load_color}{load:.1f}{fmt.C.RESET}" if load_color else f"{load:.1f}", 8),
            (f"{ram_color}{ram_pct:.0f}%{fmt.C.RESET}" if ram_color else f"{ram_pct:.0f}%", 8),
            (f"{disk_color}{disk_pct}%{fmt.C.RESET}" if disk_color else f"{disk_pct}%", 8),
            (f"{host.get('uptime_days', '?')}d", 10),
            (str(host.get("containers", 0)), 8),
        )
    fmt.blank()

    # Issues
    if issues:
        fmt.divider(f"Issues ({len(issues)})")
        fmt.blank()
        for issue in issues:
            icon = f"{fmt.C.RED}{fmt.S.CROSS}" if issue["type"] == "critical" else f"{fmt.C.YELLOW}{fmt.S.WARN}"
            fmt.line(f"  {icon}{fmt.C.RESET} {issue['host']}: {issue['message']}")
        fmt.blank()
    else:
        fmt.divider("Issues")
        fmt.blank()
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} No issues detected.{fmt.C.RESET}")
        fmt.blank()

    fmt.line(f"  {fmt.C.DIM}Report saved: {report_path}{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}Markdown:     freq report --markdown{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}JSON:         freq report --json{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
