"""Fleet health monitoring for FREQ.

Commands: health

Comprehensive health check across the fleet:
- CPU load vs core count
- Memory pressure
- Disk space
- System uptime
- Service status (docker, ssh)

Color-coded thresholds: green (healthy), yellow (warning), red (critical).
"""
from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many


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
        "echo \"$("
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
        ")\""
    )

    fmt.line(f"{fmt.C.BOLD}Scanning {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    import time
    start = time.monotonic()
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
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

    healthy = 0
    degraded = 0
    critical = 0

    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            critical += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                ("—", 10),
                ("—", 14),
                ("—", 8),
                ("—", 8),
                (fmt.badge("down"), 8),
            )
            continue

        parts = r.stdout.split("|")
        if len(parts) < 7:
            critical += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                ("parse err", 10),
                ("—", 14),
                ("—", 8),
                ("—", 8),
                (fmt.badge("fail"), 8),
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
        except (ValueError, IndexError):
            critical += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                ("—", 10),
                ("—", 14),
                ("—", 8),
                ("—", 8),
                (fmt.badge("fail"), 8),
            )
            continue

        # Evaluate health
        host_health = "healthy"
        issues = 0

        # Load: warn if > cores, crit if > 2x cores
        load_ratio = load_1m / cores if cores > 0 else 0
        if load_ratio > 2.0:
            load_color = fmt.C.RED
            host_health = "critical"
            issues += 1
        elif load_ratio > 1.0:
            load_color = fmt.C.YELLOW
            if host_health != "critical":
                host_health = "degraded"
            issues += 1
        else:
            load_color = fmt.C.GREEN
        load_str = f"{load_color}{load_1m:.1f}/{cores}c{fmt.C.RESET}"

        # RAM: warn if > 80%, crit if > 95%
        ram_pct = (ram_used * 100 // ram_total) if ram_total > 0 else 0
        if ram_pct > 95:
            ram_color = fmt.C.RED
            host_health = "critical"
            issues += 1
        elif ram_pct > 80:
            ram_color = fmt.C.YELLOW
            if host_health != "critical":
                host_health = "degraded"
            issues += 1
        else:
            ram_color = fmt.C.GREEN
        ram_str = f"{ram_color}{ram_pct}%{fmt.C.RESET} {ram_used}M"

        # Disk: warn if > 75%, crit if > 90%
        if disk_pct > 90:
            disk_color = fmt.C.RED
            host_health = "critical"
            issues += 1
        elif disk_pct > 75:
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
    fmt.line(
        f"  {fmt.C.GREEN}{healthy}{fmt.C.RESET} healthy  "
        f"{fmt.C.YELLOW}{degraded}{fmt.C.RESET} degraded  "
        f"{fmt.C.RED}{critical}{fmt.C.RESET} critical  "
        f"({len(hosts)} hosts, {total_duration:.1f}s)"
    )
    fmt.blank()
    fmt.footer()

    return 1 if critical > 0 else 0
