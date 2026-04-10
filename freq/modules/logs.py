"""Fleet-wide log aggregation and search for FREQ.

Domain: freq fleet <logs-tail|logs-search|logs-stats|logs-export>

Tail, search, and aggregate logs across every fleet host. No agents, no
ingestion fees, no separate infrastructure. SSH + journalctl + docker logs.
Search the entire fleet from one terminal.

Replaces: Splunk ($1M+/yr), ELK stack (resource monster), Papertrail ($230/mo)

Architecture:
    - Tail via SSH + journalctl --lines on each host (parallel)
    - Search via SSH + journalctl --grep across fleet
    - Docker logs via SSH + docker logs on container hosts
    - Stats aggregates error/warning counts per host

Design decisions:
    - No log shipping, no central store. Logs stay where they are; FREQ
      queries them on demand via SSH. Zero storage cost, zero ingestion lag.
"""

import json
import re

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many, result_for

LOGS_CMD_TIMEOUT = 15
LOGS_SEARCH_TIMEOUT = 30


def cmd_logs(cfg: FreqConfig, pack, args) -> int:
    """Fleet log management."""
    action = getattr(args, "action", None) or "tail"
    routes = {
        "tail": _cmd_tail,
        "search": _cmd_search,
        "stats": _cmd_stats,
        "export": _cmd_export,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown logs action: {action}")
    fmt.info("Available: tail, search, stats, export")
    return 1


def _cmd_tail(cfg: FreqConfig, args) -> int:
    """Tail recent logs from fleet hosts."""
    fmt.header("Fleet Logs — Tail")
    fmt.blank()

    target = getattr(args, "target_host", None)
    lines = getattr(args, "lines", 20) or 20
    unit = getattr(args, "unit", None)

    hosts = cfg.hosts
    if target:
        from freq.core.resolve import host as resolve_host

        h = resolve_host(hosts, target)
        if not h:
            fmt.error(f"Host not found: {target}")
            return 1
        hosts = [h]

    unit_filter = f"--unit {unit}" if unit else ""
    command = f"journalctl --no-pager -n {lines} {unit_filter} --output short-iso 2>/dev/null | tail -{lines}"

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=LOGS_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    reachable = 0
    unreachable = []
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0:
            unreachable.append(h.label)
            continue
        if not r.stdout.strip():
            reachable += 1
            continue

        reachable += 1
        fmt.divider(h.label)
        fmt.blank()
        for line in r.stdout.strip().split("\n")[-lines:]:
            # Color-code by severity
            if "error" in line.lower() or "fail" in line.lower() or "crit" in line.lower():
                fmt.line(f"  {fmt.C.RED}{line}{fmt.C.RESET}")
            elif "warn" in line.lower():
                fmt.line(f"  {fmt.C.YELLOW}{line}{fmt.C.RESET}")
            else:
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        fmt.blank()

    if unreachable:
        fmt.blank()
        fmt.line(f"  {fmt.C.RED}{len(unreachable)} host(s) unreachable:{fmt.C.RESET} {', '.join(unreachable)}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{reachable}/{len(hosts)} hosts returned logs{fmt.C.RESET}")
    fmt.footer()
    return 0


def _cmd_search(cfg: FreqConfig, args) -> int:
    """Search logs across fleet."""
    pattern = getattr(args, "pattern", None)
    if not pattern:
        fmt.error("Usage: freq logs search <pattern> [--since 1h] [--host <label>]")
        return 1

    fmt.header(f"Fleet Log Search: {pattern}")
    fmt.blank()

    since = getattr(args, "since", "1h") or "1h"
    target = getattr(args, "target_host", None)
    lines = getattr(args, "lines", 50) or 50

    hosts = cfg.hosts
    if target:
        from freq.core.resolve import host as resolve_host

        h = resolve_host(hosts, target)
        if not h:
            fmt.error(f"Host not found: {target}")
            return 1
        hosts = [h]

    # Sanitize pattern for shell
    safe_pattern = pattern.replace("'", "'\\''")

    command = (
        f"journalctl --no-pager --since '-{since}' --output short-iso 2>/dev/null | "
        f"grep -i '{safe_pattern}' | tail -{lines}; "
        f"docker logs --since {since} $(docker ps -q 2>/dev/null) 2>&1 | "
        f"grep -i '{safe_pattern}' | tail -10 || true"
    )

    fmt.step_start(f"Searching {len(hosts)} hosts (last {since})")
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=LOGS_SEARCH_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    reachable = 0
    unreachable = []
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0:
            unreachable.append(h.label)
        else:
            reachable += 1

    if unreachable:
        fmt.step_warn(f"Search done — {len(unreachable)} host(s) unreachable")
    else:
        fmt.step_ok(f"Search complete — {reachable} hosts checked")
    fmt.blank()

    total_matches = 0
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0 or not r.stdout.strip():
            continue

        match_lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
        if not match_lines:
            continue

        total_matches += len(match_lines)
        fmt.divider(f"{h.label} ({len(match_lines)} matches)")
        fmt.blank()

        for line in match_lines[:20]:
            # Highlight the search pattern
            highlighted = re.sub(
                f"({re.escape(pattern)})",
                f"{fmt.C.RED}\\1{fmt.C.RESET}",
                line,
                flags=re.IGNORECASE,
            )
            fmt.line(f"  {highlighted}")

        if len(match_lines) > 20:
            fmt.line(f"  {fmt.C.DIM}... +{len(match_lines) - 20} more{fmt.C.RESET}")
        fmt.blank()

    if unreachable:
        fmt.line(f"  {fmt.C.RED}Unreachable:{fmt.C.RESET} {', '.join(unreachable)}")

    if total_matches == 0:
        fmt.line(f"  {fmt.C.DIM}No matches for '{pattern}' in last {since}.{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}{total_matches}{fmt.C.RESET} matches across {reachable}/{len(hosts)} reachable hosts")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_stats(cfg: FreqConfig, args) -> int:
    """Show log statistics — top error patterns fleet-wide."""
    fmt.header("Fleet Log Statistics")
    fmt.blank()

    since = getattr(args, "since", "1h") or "1h"

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    command = (
        f"journalctl --no-pager --since '-{since}' --priority err --output cat 2>/dev/null | "
        "sort | uniq -c | sort -rn | head -15"
    )

    fmt.step_start(f"Analyzing errors across {len(hosts)} hosts (last {since})")
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=LOGS_SEARCH_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )
    fmt.step_ok("Analysis complete")
    fmt.blank()

    # Aggregate patterns across hosts
    pattern_counts = {}
    for h in hosts:
        r = result_for(results, h)
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
                    msg = parts[1][:80]
                    pattern_counts[msg] = pattern_counts.get(msg, 0) + count
                except ValueError:
                    pass

    if not pattern_counts:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} No errors in the last {since}.{fmt.C.RESET}")
    else:
        fmt.table_header(("COUNT", 8), ("ERROR PATTERN", 60))
        sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
        for msg, count in sorted_patterns[:15]:
            fmt.table_row(
                (f"{fmt.C.RED}{count}{fmt.C.RESET}", 8),
                (msg[:60], 60),
            )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Period: last {since} across {len(hosts)} hosts{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_export(cfg: FreqConfig, args) -> int:
    """Export logs in JSON format."""
    since = getattr(args, "since", "1h") or "1h"
    target = getattr(args, "target_host", None)

    hosts = cfg.hosts
    if target:
        from freq.core.resolve import host as resolve_host

        h = resolve_host(hosts, target)
        if not h:
            fmt.error(f"Host not found: {target}")
            return 1
        hosts = [h]

    command = f"journalctl --no-pager --since '-{since}' --output json 2>/dev/null | tail -100"

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=LOGS_SEARCH_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    export = {"period": since, "hosts": {}}
    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode == 0 and r.stdout.strip():
            entries = []
            for line in r.stdout.strip().split("\n"):
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            export["hosts"][h.label] = entries

    print(json.dumps(export, indent=2))
    return 0
