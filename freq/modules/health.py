"""Fleet-wide health monitoring for FREQ.

Domain: freq fleet <health>

Comprehensive health check across every fleet host. Measures CPU load ratio,
memory pressure, disk usage, uptime, and key service status (docker, sshd).
Color-coded output: green healthy, yellow warning, red critical.

Replaces: Nagios ($2K+), Zabbix (complex setup), Datadog ($15/host/mo)

Architecture:
    - Single compound SSH command gathers all metrics in one round-trip
    - Parallel execution via ssh_run_many across entire fleet
    - Threshold-based grading: load ratio, RAM %, disk % with configurable limits
    - Output via freq/core/fmt.py with color-coded status indicators

Design decisions:
    - One SSH call per host, not five. All health metrics gathered in a
      single command to minimize latency on large fleets.
"""

import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.health_state import (
    STATE_AUTH_FAILED,
    STATE_DEGRADED,
    STATE_UNREACHABLE,
    classify_probe_failure,
)
from freq.core.ssh import run_many as ssh_run_many, result_for

# Health check thresholds
HEALTH_CMD_TIMEOUT = 15
LOAD_RATIO_CRITICAL = 2.0
LOAD_RATIO_WARNING = 1.0
RAM_PCT_CRITICAL = 95
RAM_PCT_WARNING = 80
DISK_PCT_CRITICAL = 90
DISK_PCT_WARNING = 75


def cmd_health(cfg: FreqConfig, pack, args) -> int:
    """Comprehensive fleet health check."""
    fmt.header("Fleet Health")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"{fmt.C.YELLOW}No hosts registered.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Gather health metrics from all hosts
    # Single compound command to minimize SSH round trips
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
        "uptime -p 2>/dev/null | sed 's/up //' || echo '?'"
        ")|$("
        "systemctl is-active sshd 2>/dev/null || echo '?'"
        ")|$("
        "docker ps -q 2>/dev/null | wc -l || echo '0'"
        ')"'
    )

    fmt.line(f"{fmt.C.BOLD}Scanning {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    start = time.monotonic()
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=HEALTH_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )
    total_duration = time.monotonic() - start

    # Parse and display
    fmt.table_header(
        ("HOST", 14),
        ("LOAD", 10),
        ("RAM", 14),
        ("DISK", 8),
        ("DOCKER", 8),
        ("HEALTH", 8),
    )

    # failure paths route through the
    # shared classifier so the fleet health table names the failure
    # class (auth_failed / unreachable / degraded) alongside the
    # metric-based grading. Metric axis (load/ram/disk → healthy/
    # degraded/critical) is the load dimension — a different axis than
    # probe outcome — and stays as-is. But a 'down' host whose probe
    # never reached the kernel must NOT be collapsed to 'critical'
    # silently: operators need to know whether to look at uptime graphs
    # or ssh keys.
    healthy = 0
    degraded = 0
    critical = 0
    auth_failed_n = 0
    unreachable_n = 0
    # Stash reason strings per non-live host so the summary line can
    # name what tripped.
    probe_reasons: dict[str, tuple[str, str]] = {}

    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0:
            rc = r.returncode if r else 1
            stderr = (r.stderr or "") if r else "no response"
            stdout = (r.stdout or "") if r else ""
            state, reason = classify_probe_failure(rc, stderr, stdout)
            probe_reasons[h.label] = (state, reason)
            if state == STATE_AUTH_FAILED:
                auth_failed_n += 1
                badge = (f"{fmt.C.RED}auth{fmt.C.RESET}", 8)
            elif state == STATE_UNREACHABLE:
                unreachable_n += 1
                badge = (fmt.badge("down"), 8)
            else:
                critical += 1
                badge = (fmt.badge("fail"), 8)
            # Dim detail — reason in the LOAD column since there are
            # no metrics to show anyway. Truncated to the column width.
            detail = reason[:10] if reason else "no data"
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                (f"{fmt.C.DIM}{detail}{fmt.C.RESET}", 10),
                ("—", 14),
                ("—", 8),
                ("—", 8),
                badge,
            )
            continue

        parts = r.stdout.split("|")
        if len(parts) < 7:
            # Probe ran (ssh connected) but payload is broken. Degraded,
            # not critical — the host is alive, just returning garbage.
            probe_reasons[h.label] = (
                STATE_DEGRADED,
                f"probe returned malformed payload ({len(parts)} fields, expected >=7)",
            )
            degraded += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                (f"{fmt.C.YELLOW}parse err{fmt.C.RESET}", 10),
                ("—", 14),
                ("—", 8),
                ("—", 8),
                (f"{fmt.C.YELLOW}degraded{fmt.C.RESET}", 8),
            )
            continue

        try:
            cores = int(parts[0])
            load_1m = float(parts[1])
            ram_used = int(parts[2])
            ram_total = int(parts[3])
            disk_pct = int(parts[4])
            uptime_str = parts[5]
            sshd_status = parts[6] if len(parts) > 6 else "?"
            docker_count = parts[7].strip() if len(parts) > 7 else "0"
        except (ValueError, IndexError) as _e:
            # Probe ran but the values aren't numeric. Same class as
            # above — degraded, not critical.
            probe_reasons[h.label] = (
                STATE_DEGRADED,
                f"probe value parse error: {str(_e)[:60]}",
            )
            degraded += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                (f"{fmt.C.YELLOW}parse err{fmt.C.RESET}", 10),
                ("—", 14),
                ("—", 8),
                ("—", 8),
                (f"{fmt.C.YELLOW}degraded{fmt.C.RESET}", 8),
            )
            continue

        # Evaluate health
        host_health = "healthy"
        issues = 0

        # Load: warn if > cores, crit if > 2x cores
        load_ratio = load_1m / cores if cores > 0 else 0
        if load_ratio > LOAD_RATIO_CRITICAL:
            load_color = fmt.C.RED
            host_health = "critical"
            issues += 1
        elif load_ratio > LOAD_RATIO_WARNING:
            load_color = fmt.C.YELLOW
            if host_health != "critical":
                host_health = "degraded"
            issues += 1
        else:
            load_color = fmt.C.GREEN
        load_str = f"{load_color}{load_1m:.1f}/{cores}c{fmt.C.RESET}"

        # RAM: warn if > 80%, crit if > 95%
        ram_pct = (ram_used * 100 // ram_total) if ram_total > 0 else 0
        if ram_pct > RAM_PCT_CRITICAL:
            ram_color = fmt.C.RED
            host_health = "critical"
            issues += 1
        elif ram_pct > RAM_PCT_WARNING:
            ram_color = fmt.C.YELLOW
            if host_health != "critical":
                host_health = "degraded"
            issues += 1
        else:
            ram_color = fmt.C.GREEN
        ram_str = f"{ram_color}{ram_pct}%{fmt.C.RESET} {ram_used}M"

        # Disk: warn if > 75%, crit if > 90%
        if disk_pct > DISK_PCT_CRITICAL:
            disk_color = fmt.C.RED
            host_health = "critical"
            issues += 1
        elif disk_pct > DISK_PCT_WARNING:
            disk_color = fmt.C.YELLOW
            if host_health != "critical":
                host_health = "degraded"
            issues += 1
        else:
            disk_color = fmt.C.GREEN
        disk_str = f"{disk_color}{disk_pct}%{fmt.C.RESET}"

        # Docker
        docker_str = docker_count if docker_count != "0" else f"{fmt.C.DIM}—{fmt.C.RESET}"

        # Health badge
        if host_health == "critical":
            critical += 1
            health_badge = fmt.badge("critical")
        elif host_health == "degraded":
            degraded += 1
            health_badge = fmt.badge("warn")
        else:
            healthy += 1
            health_badge = fmt.badge("healthy")

        fmt.table_row(
            (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
            (load_str, 10),
            (ram_str, 14),
            (disk_str, 8),
            (docker_str, 8),
            (health_badge, 8),
        )

    # Summary
    fmt.blank()
    fmt.divider("Health Summary")
    fmt.blank()
    summary = (
        f"  {fmt.C.GREEN}{healthy}{fmt.C.RESET} healthy  "
        f"{fmt.C.YELLOW}{degraded}{fmt.C.RESET} degraded  "
        f"{fmt.C.RED}{critical}{fmt.C.RESET} critical"
    )
    # probe-failure classes are a
    # different axis than load grading but must still be named so an
    # operator knows whether a red host is overloaded or unreachable.
    if auth_failed_n:
        summary += f"  {fmt.C.RED}{auth_failed_n}{fmt.C.RESET} auth_failed"
    if unreachable_n:
        summary += f"  {fmt.C.RED}{unreachable_n}{fmt.C.RESET} unreachable"
    summary += f"  ({len(hosts)} hosts, {total_duration:.1f}s)"
    fmt.line(summary)
    # Name the worst probe failure so the operator knows which host to
    # look at first.
    if probe_reasons:
        worst = next(
            iter([(lbl, s, r) for lbl, (s, r) in probe_reasons.items()
                  if s == STATE_AUTH_FAILED]),
            None,
        ) or next(
            iter([(lbl, s, r) for lbl, (s, r) in probe_reasons.items()
                  if s == STATE_UNREACHABLE]),
            None,
        ) or next(
            iter([(lbl, s, r) for lbl, (s, r) in probe_reasons.items()]),
            None,
        )
        if worst:
            fmt.line(
                f"  {fmt.C.DIM}worst probe:{fmt.C.RESET} "
                f"{fmt.C.BOLD}{worst[0]}{fmt.C.RESET} "
                f"{fmt.C.DIM}— {worst[1]}: {worst[2][:80]}{fmt.C.RESET}"
            )
    fmt.blank()
    fmt.footer()

    # Return non-zero on probe failures OR critical metric states.
    return 1 if (critical > 0 or auth_failed_n > 0 or unreachable_n > 0) else 0
