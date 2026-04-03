"""Built-in job scheduler for FREQ.

Domain: freq auto <schedule-list|schedule-create|schedule-delete|schedule-run|schedule-enable|schedule-disable>

"Snapshot prod VMs at 2am." "Run patrol every 6 hours." "Trend snapshot
every 2 hours." Define recurring freq commands as scheduled jobs. No more
hand-writing systemd timers or crontabs.

Replaces: Crontab management ($0 but fragile), Ansible Tower scheduling ($$$),
          systemd timer units (verbose)

Architecture:
    - Jobs stored as JSON in conf/schedules/jobs.json
    - Each job: name, freq command, cron expression, enabled flag
    - Execution log stored separately with timestamps and exit codes
    - Run triggers invoke the freq command via subprocess

Design decisions:
    - JSON config, not crontab. Jobs are version-controllable, inspectable,
      and portable. The scheduler reads JSON, not /var/spool/cron.
"""

import json
import os
import re
import subprocess
import time

from freq.core import fmt
from freq.core.config import FreqConfig

# Storage
SCHEDULE_DIR = "schedules"
SCHEDULE_FILE = "jobs.json"
SCHEDULE_LOG = "schedule-log.json"
MAX_LOG_ENTRIES = 200


def _schedule_dir(cfg: FreqConfig) -> str:
    """Get or create schedule directory."""
    path = os.path.join(cfg.conf_dir, SCHEDULE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_jobs(cfg: FreqConfig) -> list:
    """Load scheduled jobs from disk."""
    filepath = os.path.join(_schedule_dir(cfg), SCHEDULE_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_jobs(cfg: FreqConfig, jobs: list):
    """Save scheduled jobs to disk."""
    filepath = os.path.join(_schedule_dir(cfg), SCHEDULE_FILE)
    with open(filepath, "w") as f:
        json.dump(jobs, f, indent=2)


def _load_log(cfg: FreqConfig) -> list:
    """Load schedule execution log."""
    filepath = os.path.join(_schedule_dir(cfg), SCHEDULE_LOG)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_log(cfg: FreqConfig, log_entries: list):
    """Save schedule execution log."""
    filepath = os.path.join(_schedule_dir(cfg), SCHEDULE_LOG)
    with open(filepath, "w") as f:
        json.dump(log_entries[-MAX_LOG_ENTRIES:], f, indent=2)


def _parse_interval(interval_str: str) -> int:
    """Parse an interval string like '2h', '30m', '1d' into seconds."""
    match = re.match(r"^(\d+)([smhd])$", interval_str.strip().lower())
    if not match:
        return 0
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers.get(unit, 0)


# Pre-defined job templates
JOB_TEMPLATES = {
    "trend-snapshot": {
        "command": "freq trend snapshot",
        "interval": "2h",
        "description": "Record capacity data point every 2 hours",
    },
    "sla-check": {
        "command": "freq sla check",
        "interval": "5m",
        "description": "Record SLA connectivity check every 5 minutes",
    },
    "alert-check": {
        "command": "freq alert check",
        "interval": "5m",
        "description": "Evaluate alert rules every 5 minutes",
    },
    "patrol-run": {
        "command": "freq patrol --interval 0",
        "interval": "30m",
        "description": "Run patrol sweep every 30 minutes",
    },
    "report-daily": {"command": "freq report --json", "interval": "24h", "description": "Generate daily fleet report"},
}


def cmd_schedule(cfg: FreqConfig, pack, args) -> int:
    """Schedule management dispatch."""
    action = getattr(args, "action", None) or "list"

    routes = {
        "list": _cmd_list,
        "create": _cmd_create,
        "delete": _cmd_delete,
        "run": _cmd_run,
        "enable": _cmd_enable,
        "disable": _cmd_disable,
        "log": _cmd_log,
        "templates": _cmd_templates,
        "install": _cmd_install,
    }

    handler = routes.get(action)
    if handler:
        return handler(cfg, args)

    fmt.error(f"Unknown schedule action: {action}")
    fmt.info("Available: list, create, delete, run, enable, disable, log, templates, install")
    return 1


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List all scheduled jobs."""
    fmt.header("Scheduled Jobs")
    fmt.blank()

    jobs = _load_jobs(cfg)
    if not jobs:
        fmt.line(f"  {fmt.C.DIM}No scheduled jobs.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Create one:{fmt.C.RESET}")
        fmt.line(
            f"  {fmt.C.DIM}  freq schedule create my-job --command 'freq trend snapshot' --interval 2h{fmt.C.RESET}"
        )
        fmt.line(f"  {fmt.C.DIM}  freq schedule templates   (see pre-built jobs){fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("NAME", 18),
        ("COMMAND", 28),
        ("INTERVAL", 10),
        ("STATUS", 8),
        ("LAST RUN", 20),
    )

    for job in jobs:
        enabled = job.get("enabled", True)
        status = fmt.badge("on") if enabled else f"{fmt.C.RED}OFF{fmt.C.RESET}"
        last_run = job.get("last_run", "never")
        if last_run != "never":
            last_run = last_run[:19]

        fmt.table_row(
            (f"{fmt.C.BOLD}{job['name']}{fmt.C.RESET}", 18),
            (job.get("command", "")[:28], 28),
            (job.get("interval", ""), 10),
            (status, 8),
            (last_run, 20),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(jobs)} job(s){fmt.C.RESET}")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Install as system cron: freq schedule install{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_create(cfg: FreqConfig, args) -> int:
    """Create a new scheduled job."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq schedule create <name> --command '<cmd>' --interval <interval>")
        fmt.info("Interval: 5m, 2h, 1d, etc.")
        return 1

    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        fmt.error("Job name must be alphanumeric with hyphens/underscores.")
        return 1

    command = getattr(args, "command", None)
    interval = getattr(args, "interval", None)

    # Check if it's a template
    if name in JOB_TEMPLATES and not command:
        template = JOB_TEMPLATES[name]
        command = template["command"]
        interval = interval or template["interval"]

    if not command:
        fmt.error("--command is required (or use a template name)")
        return 1
    if not interval:
        fmt.error("--interval is required (e.g., 5m, 2h, 1d)")
        return 1

    interval_secs = _parse_interval(interval)
    if interval_secs <= 0:
        fmt.error(f"Invalid interval: {interval} (use format: 5m, 2h, 1d)")
        return 1

    jobs = _load_jobs(cfg)
    if any(j["name"] == name for j in jobs):
        fmt.error(f"Job '{name}' already exists. Delete it first.")
        return 1

    job = {
        "name": name,
        "command": command,
        "interval": interval,
        "interval_secs": interval_secs,
        "enabled": True,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "last_run": "never",
    }

    jobs.append(job)
    _save_jobs(cfg, jobs)

    fmt.header("Job Created")
    fmt.blank()
    fmt.step_ok(f"Job: {name}")
    fmt.line(f"  Command:  {command}")
    fmt.line(f"  Interval: {interval} ({interval_secs}s)")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Run manually: freq schedule run {name}{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}Install cron: freq schedule install{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_delete(cfg: FreqConfig, args) -> int:
    """Delete a scheduled job."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq schedule delete <name>")
        return 1

    jobs = _load_jobs(cfg)
    original = len(jobs)
    jobs = [j for j in jobs if j["name"] != name]

    if len(jobs) == original:
        fmt.error(f"No job named '{name}'")
        return 1

    _save_jobs(cfg, jobs)
    fmt.header("Job Deleted")
    fmt.blank()
    fmt.step_ok(f"Deleted: {name}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_run(cfg: FreqConfig, args) -> int:
    """Run a scheduled job immediately."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq schedule run <name>")
        return 1

    jobs = _load_jobs(cfg)
    job = next((j for j in jobs if j["name"] == name), None)
    if not job:
        fmt.error(f"No job named '{name}'")
        return 1

    fmt.header(f"Running: {name}")
    fmt.blank()

    command = job["command"]
    fmt.step_start(f"Executing: {command}")

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        exit_code = result.returncode
        if exit_code == 0:
            fmt.step_ok(f"Completed (exit {exit_code})")
        else:
            fmt.step_fail(f"Failed (exit {exit_code})")
            if result.stderr:
                fmt.line(f"  {fmt.C.DIM}{result.stderr[:200]}{fmt.C.RESET}")
    except subprocess.TimeoutExpired:
        fmt.step_fail("Timed out after 300s")
        exit_code = 1
    except Exception as e:
        fmt.step_fail(f"Error: {e}")
        exit_code = 1

    # Update last_run
    job["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save_jobs(cfg, jobs)

    # Log execution
    log_entries = _load_log(cfg)
    log_entries.append(
        {
            "job": name,
            "command": command,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "exit_code": exit_code,
        }
    )
    _save_log(cfg, log_entries)

    fmt.blank()
    fmt.footer()
    return exit_code


def _cmd_enable(cfg: FreqConfig, args) -> int:
    """Enable a scheduled job."""
    return _toggle_job(cfg, args, True)


def _cmd_disable(cfg: FreqConfig, args) -> int:
    """Disable a scheduled job."""
    return _toggle_job(cfg, args, False)


def _toggle_job(cfg: FreqConfig, args, enabled: bool) -> int:
    """Toggle a job's enabled state."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error(f"Usage: freq schedule {'enable' if enabled else 'disable'} <name>")
        return 1

    jobs = _load_jobs(cfg)
    job = next((j for j in jobs if j["name"] == name), None)
    if not job:
        fmt.error(f"No job named '{name}'")
        return 1

    job["enabled"] = enabled
    _save_jobs(cfg, jobs)
    state = "enabled" if enabled else "disabled"
    fmt.step_ok(f"Job '{name}' {state}")
    return 0


def _cmd_log(cfg: FreqConfig, args) -> int:
    """Show schedule execution log."""
    fmt.header("Schedule Log")
    fmt.blank()

    log_entries = _load_log(cfg)
    if not log_entries:
        fmt.line(f"  {fmt.C.DIM}No executions recorded.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    lines = getattr(args, "lines", 20) or 20
    recent = log_entries[-lines:]

    fmt.table_header(("TIME", 20), ("JOB", 18), ("EXIT", 6))

    for entry in reversed(recent):
        ts = entry.get("timestamp", "")[:19]
        ec = entry.get("exit_code", -1)
        ec_str = f"{fmt.C.GREEN}0{fmt.C.RESET}" if ec == 0 else f"{fmt.C.RED}{ec}{fmt.C.RESET}"
        fmt.table_row((ts, 20), (entry.get("job", ""), 18), (ec_str, 6))

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(log_entries)} total executions ({len(recent)} shown){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_templates(cfg: FreqConfig, args) -> int:
    """Show available job templates."""
    fmt.header("Job Templates")
    fmt.blank()

    fmt.table_header(("NAME", 18), ("COMMAND", 30), ("INTERVAL", 10))

    for name, tmpl in JOB_TEMPLATES.items():
        fmt.table_row(
            (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 18),
            (tmpl["command"], 30),
            (tmpl["interval"], 10),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Create from template: freq schedule create <template-name>{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_install(cfg: FreqConfig, args) -> int:
    """Install enabled jobs as system cron entries."""
    jobs = _load_jobs(cfg)
    active = [j for j in jobs if j.get("enabled", True)]

    if not active:
        fmt.error("No enabled jobs to install.")
        return 1

    fmt.header("Install Schedule to Cron")
    fmt.blank()

    # Generate crontab lines
    cron_lines = [
        "# FREQ scheduled jobs (managed by freq schedule install)",
    ]

    for job in active:
        secs = job.get("interval_secs", 0)
        cmd = job["command"]

        # Convert interval to closest cron expression
        if secs < 60:
            cron_expr = "* * * * *"  # Every minute
        elif secs < 3600:
            mins = max(1, secs // 60)
            cron_expr = f"*/{mins} * * * *"
        elif secs < 86400:
            hours = max(1, secs // 3600)
            cron_expr = f"0 */{hours} * * *"
        else:
            days = max(1, secs // 86400)
            cron_expr = f"0 0 */{days} * *"

        cron_lines.append(f"{cron_expr} {cmd} >> /var/log/freq-schedule.log 2>&1  # {job['name']}")

    fmt.line(f"  {fmt.C.DIM}Generated crontab entries:{fmt.C.RESET}")
    fmt.blank()
    for line in cron_lines:
        fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Add to crontab: crontab -e{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
