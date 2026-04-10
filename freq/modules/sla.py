"""Uptime SLA tracking for FREQ.

Domain: freq observe <sla-show|sla-check|sla-reset>

Real SLA numbers from real data. Tracks uptime per host over 7, 30, and 90
day windows. Every health check records whether each host was reachable.
No guessing, no estimates — hard numbers from actual probe results.

Replaces: Enterprise monitoring SLA dashboards ($$$), uptime robot ($7+/mo),
          manual uptime spreadsheets

Architecture:
    - SLA data stored in conf/sla/sla-data.json (check history per host)
    - Each check records epoch timestamp + reachability boolean per host
    - Uptime percentage calculated from check pass/fail ratio per window
    - Auto-prune: checks older than 90 days are dropped on save

Design decisions:
    - SLA is calculated from actual check results, not inferred from logs.
      If FREQ could not reach the host, it was down. Period.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many, result_for

# Storage
SLA_DIR = "sla"
SLA_FILE = "sla-data.json"
SLA_CMD_TIMEOUT = 10


def _sla_dir(cfg: FreqConfig) -> str:
    """Get or create SLA directory."""
    path = os.path.join(cfg.conf_dir, SLA_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_sla_data(cfg: FreqConfig) -> dict:
    """Load SLA check data from disk."""
    filepath = os.path.join(_sla_dir(cfg), SLA_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"checks": [], "hosts": {}}


def _save_sla_data(cfg: FreqConfig, data: dict):
    """Save SLA data. Prune checks older than 90 days."""
    cutoff = time.time() - (90 * 86400)
    data["checks"] = [c for c in data.get("checks", []) if c.get("epoch", 0) > cutoff]
    filepath = os.path.join(_sla_dir(cfg), SLA_FILE)
    with open(filepath, "w") as f:
        json.dump(data, f)


def _record_check(cfg: FreqConfig):
    """Perform a connectivity check and record results."""
    hosts = cfg.hosts
    if not hosts:
        return

    results = ssh_run_many(
        hosts=hosts,
        command="echo ok",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=SLA_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    check = {
        "epoch": int(time.time()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": {},
    }

    for h in hosts:
        r = result_for(results, h)
        check["results"][h.label] = 1 if (r and r.returncode == 0) else 0

    data = _load_sla_data(cfg)
    data["checks"].append(check)
    _save_sla_data(cfg, data)


def _calculate_sla(data: dict, host_label: str, days: int) -> dict:
    """Calculate SLA for a specific host over N days."""
    cutoff = time.time() - (days * 86400)
    checks = [c for c in data.get("checks", []) if c.get("epoch", 0) > cutoff]

    if not checks:
        return {"checks": 0, "up": 0, "down": 0, "pct": 0.0, "grade": "N/A"}

    up = sum(1 for c in checks if c.get("results", {}).get(host_label, 0) == 1)
    total = len(checks)
    down = total - up
    pct = round(up / total * 100, 3) if total > 0 else 0

    # Letter grade
    if pct >= 99.99:
        grade = "A+"
    elif pct >= 99.9:
        grade = "A"
    elif pct >= 99.5:
        grade = "A-"
    elif pct >= 99.0:
        grade = "B"
    elif pct >= 98.0:
        grade = "B-"
    elif pct >= 95.0:
        grade = "C"
    elif pct >= 90.0:
        grade = "D"
    else:
        grade = "F"

    return {"checks": total, "up": up, "down": down, "pct": pct, "grade": grade}


def cmd_sla(cfg: FreqConfig, pack, args) -> int:
    """SLA tracking dispatch."""
    action = getattr(args, "action", None) or "show"

    if action == "show":
        return _cmd_show(cfg, args)
    elif action == "check":
        return _cmd_check(cfg, args)
    elif action == "reset":
        return _cmd_reset(cfg, args)

    fmt.error(f"Unknown sla action: {action}")
    fmt.info("Available: show, check, reset")
    return 1


def _cmd_check(cfg: FreqConfig, args) -> int:
    """Record a connectivity check for SLA tracking."""
    fmt.header("SLA Check")
    fmt.blank()

    fmt.step_start("Recording connectivity check")
    _record_check(cfg)
    fmt.step_ok("Check recorded")

    data = _load_sla_data(cfg)
    fmt.line(f"  Total data points: {len(data.get('checks', []))}")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Run this regularly (cron) for accurate SLA data.{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}View results: freq sla show{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_show(cfg: FreqConfig, args) -> int:
    """Show SLA report for all hosts."""
    days = getattr(args, "days", 30) or 30

    fmt.header(f"Fleet SLA — {days} Days")
    fmt.blank()

    data = _load_sla_data(cfg)
    checks = data.get("checks", [])

    if not checks:
        fmt.line(f"  {fmt.C.YELLOW}No SLA data collected yet.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Start tracking: freq sla check{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}For accurate data, add to cron:{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}  */5 * * * * freq sla check{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Get all host labels from checks
    all_hosts = set()
    for c in checks:
        all_hosts.update(c.get("results", {}).keys())

    if not all_hosts:
        fmt.line(f"  {fmt.C.YELLOW}No host data in SLA checks.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Calculate SLA for each host
    fmt.table_header(
        ("HOST", 16),
        ("7-DAY", 10),
        ("30-DAY", 10),
        ("90-DAY", 10),
        ("GRADE", 8),
        ("CHECKS", 8),
        ("DOWN", 6),
    )

    for label in sorted(all_hosts):
        sla_7 = _calculate_sla(data, label, 7)
        sla_30 = _calculate_sla(data, label, 30)
        sla_90 = _calculate_sla(data, label, 90)

        # Use the requested period for the grade
        primary = _calculate_sla(data, label, days)
        grade = primary["grade"]
        grade_color = fmt.C.GREEN if grade.startswith("A") else fmt.C.YELLOW if grade.startswith("B") else fmt.C.RED

        def _pct_str(sla):
            if sla["checks"] == 0:
                return f"{fmt.C.DIM}N/A{fmt.C.RESET}"
            pct = sla["pct"]
            color = fmt.C.GREEN if pct >= 99.5 else (fmt.C.YELLOW if pct >= 95 else fmt.C.RED)
            return f"{color}{pct:.2f}%{fmt.C.RESET}"

        fmt.table_row(
            (f"{fmt.C.BOLD}{label}{fmt.C.RESET}", 16),
            (_pct_str(sla_7), 10),
            (_pct_str(sla_30), 10),
            (_pct_str(sla_90), 10),
            (f"{grade_color}{grade}{fmt.C.RESET}", 8),
            (str(primary["checks"]), 8),
            (str(primary["down"]), 6),
        )

    fmt.blank()

    # Fleet average
    fleet_slas = [_calculate_sla(data, label, days) for label in all_hosts]
    valid = [s for s in fleet_slas if s["checks"] > 0]
    if valid:
        fleet_avg = sum(s["pct"] for s in valid) / len(valid)
        fleet_color = fmt.C.GREEN if fleet_avg >= 99.5 else (fmt.C.YELLOW if fleet_avg >= 95 else fmt.C.RED)
        fmt.divider("Fleet Average")
        fmt.blank()
        fmt.line(
            f"  {fleet_color}{fleet_avg:.3f}%{fmt.C.RESET} across {len(valid)} hosts "
            f"({sum(s['checks'] for s in valid)} total checks)"
        )

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_reset(cfg: FreqConfig, args) -> int:
    """Reset SLA data."""
    if not getattr(args, "yes", False):
        fmt.line(f"  {fmt.C.YELLOW}This will delete all SLA tracking data.{fmt.C.RESET}")
        try:
            confirm = input(f"  {fmt.C.YELLOW}Confirm [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    filepath = os.path.join(_sla_dir(cfg), SLA_FILE)
    if os.path.exists(filepath):
        os.remove(filepath)

    fmt.header("SLA Data Reset")
    fmt.blank()
    fmt.step_ok("SLA data cleared")
    fmt.blank()
    fmt.footer()
    return 0
