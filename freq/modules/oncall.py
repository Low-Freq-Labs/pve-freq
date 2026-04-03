"""On-call rotation and incident management for FREQ.

Domain: freq ops <oncall-schedule|oncall-whoami|oncall-ack|oncall-escalate|oncall-resolve|oncall-history>

On-call rotation with weekly/biweekly schedules, incident tracking with
acknowledgment and escalation, and a full incident history. A JSON config
file replaces $41/user/month SaaS pricing.

Replaces: PagerDuty ($21-41/user/mo), OpsGenie (sunsetting April 2027)

Architecture:
    - Schedule and incidents stored as JSON in conf/oncall/
    - Rotation calculated from start date + user list + rotation period
    - Escalation timer triggers if incident is not acknowledged
    - Incident history capped at 500 entries with automatic pruning

Design decisions:
    - File-based, not a service. On-call schedule is a config file you
      version control. No SaaS dependency for knowing who is on call.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig

ONCALL_DIR = "oncall"
ONCALL_SCHEDULE = "schedule.json"
ONCALL_INCIDENTS = "incidents.json"
MAX_INCIDENTS = 500


def _oncall_dir(cfg: FreqConfig) -> str:
    path = os.path.join(cfg.conf_dir, ONCALL_DIR)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def _load_schedule(cfg: FreqConfig) -> dict:
    filepath = os.path.join(_oncall_dir(cfg), ONCALL_SCHEDULE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"users": [], "rotation": "weekly", "start_date": "", "escalation_mins": 15}


def _save_schedule(cfg: FreqConfig, schedule: dict):
    filepath = os.path.join(_oncall_dir(cfg), ONCALL_SCHEDULE)
    with open(filepath, "w") as f:
        json.dump(schedule, f, indent=2)


def _load_incidents(cfg: FreqConfig) -> list:
    filepath = os.path.join(_oncall_dir(cfg), ONCALL_INCIDENTS)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_incidents(cfg: FreqConfig, incidents: list):
    filepath = os.path.join(_oncall_dir(cfg), ONCALL_INCIDENTS)
    with open(filepath, "w") as f:
        json.dump(incidents[-MAX_INCIDENTS:], f, indent=2)


def _get_current_oncall(schedule: dict) -> str:
    """Determine who is currently on call based on rotation."""
    users = schedule.get("users", [])
    if not users:
        return ""

    rotation = schedule.get("rotation", "weekly")
    start_date = schedule.get("start_date", "")

    if not start_date:
        return users[0]  # Default to first user

    try:
        import datetime

        start = datetime.datetime.fromisoformat(start_date)
        now = datetime.datetime.now()
        delta = (now - start).days

        if rotation == "daily":
            index = delta % len(users)
        elif rotation == "weekly":
            index = (delta // 7) % len(users)
        elif rotation == "biweekly":
            index = (delta // 14) % len(users)
        else:
            index = (delta // 7) % len(users)

        return users[index]
    except (ValueError, ImportError):
        return users[0]


def _next_incident_id(incidents: list) -> str:
    """Generate next incident ID."""
    if not incidents:
        return "INC-001"
    last_id = incidents[-1].get("id", "INC-000")
    try:
        num = int(last_id.split("-")[1]) + 1
    except (ValueError, IndexError):
        num = len(incidents) + 1
    return f"INC-{num:03d}"


def cmd_oncall(cfg: FreqConfig, pack, args) -> int:
    """On-call management dispatch."""
    action = getattr(args, "action", None) or "whoami"
    routes = {
        "whoami": _cmd_whoami,
        "schedule": _cmd_schedule,
        "alert": _cmd_alert,
        "ack": _cmd_ack,
        "escalate": _cmd_escalate,
        "resolve": _cmd_resolve,
        "history": _cmd_history,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown oncall action: {action}")
    fmt.info("Available: whoami, schedule, alert, ack, escalate, resolve, history")
    return 1


def _cmd_whoami(cfg: FreqConfig, args) -> int:
    """Show who is currently on call."""
    schedule = _load_schedule(cfg)
    current = _get_current_oncall(schedule)

    fmt.header("On-Call")
    fmt.blank()

    if not current:
        fmt.line(f"  {fmt.C.YELLOW}No on-call schedule configured.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(
            f"  {fmt.C.DIM}Set up: freq oncall schedule --users 'alice,bob,charlie' --rotation weekly{fmt.C.RESET}"
        )
    else:
        fmt.line(f"  {fmt.C.GREEN}{fmt.C.BOLD}{current}{fmt.C.RESET} is on call")
        fmt.blank()
        users = schedule.get("users", [])
        rotation = schedule.get("rotation", "weekly")
        fmt.line(f"  Rotation: {rotation}")
        fmt.line(f"  Team: {', '.join(users)}")

    # Show open incidents
    incidents = _load_incidents(cfg)
    open_incidents = [i for i in incidents if i.get("status") in ("open", "acknowledged")]
    if open_incidents:
        fmt.blank()
        fmt.divider(f"Open Incidents ({len(open_incidents)})")
        fmt.blank()
        for inc in open_incidents:
            sev = inc.get("severity", "info")
            sev_color = {"critical": fmt.C.RED, "warning": fmt.C.YELLOW}.get(sev, fmt.C.CYAN)
            status = inc.get("status", "open")
            fmt.line(f"  {sev_color}{fmt.S.WARN}{fmt.C.RESET} {inc['id']} [{status}] {inc.get('message', '')[:50]}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_schedule(cfg: FreqConfig, args) -> int:
    """Set or show on-call schedule."""
    users_str = getattr(args, "users", None)

    schedule = _load_schedule(cfg)

    if not users_str:
        # Show current schedule
        fmt.header("On-Call Schedule")
        fmt.blank()
        users = schedule.get("users", [])
        if not users:
            fmt.line(f"  {fmt.C.DIM}No schedule configured.{fmt.C.RESET}")
        else:
            current = _get_current_oncall(schedule)
            for i, user in enumerate(users):
                marker = f" {fmt.C.GREEN}← ON CALL{fmt.C.RESET}" if user == current else ""
                fmt.line(f"  {i + 1}. {fmt.C.BOLD}{user}{fmt.C.RESET}{marker}")
            fmt.blank()
            fmt.line(f"  Rotation: {schedule.get('rotation', 'weekly')}")
            fmt.line(f"  Escalation: {schedule.get('escalation_mins', 15)} minutes")
        fmt.blank()
        fmt.footer()
        return 0

    # Set schedule
    users = [u.strip() for u in users_str.split(",") if u.strip()]
    rotation = getattr(args, "rotation", None) or schedule.get("rotation", "weekly")

    import datetime

    schedule["users"] = users
    schedule["rotation"] = rotation
    schedule["start_date"] = datetime.datetime.now().isoformat()

    _save_schedule(cfg, schedule)

    fmt.header("On-Call Schedule Updated")
    fmt.blank()
    fmt.step_ok(f"Users: {', '.join(users)}")
    fmt.line(f"  Rotation: {rotation}")
    fmt.line(f"  Current on-call: {_get_current_oncall(schedule)}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_alert(cfg: FreqConfig, args) -> int:
    """Create a new incident."""
    message = getattr(args, "message", None) or "Manual alert"
    severity = getattr(args, "alert_severity", None) or "warning"
    host = getattr(args, "target_host", None) or ""

    incidents = _load_incidents(cfg)
    inc_id = _next_incident_id(incidents)

    incident = {
        "id": inc_id,
        "message": message,
        "severity": severity,
        "host": host,
        "status": "open",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "acknowledged_by": "",
        "resolved_by": "",
        "notes": [],
    }

    incidents.append(incident)
    _save_incidents(cfg, incidents)

    # Notify on-call person
    schedule = _load_schedule(cfg)
    current = _get_current_oncall(schedule)

    fmt.header(f"Incident Created: {inc_id}")
    fmt.blank()
    fmt.line(f"  Severity: {severity}")
    fmt.line(f"  Message:  {message}")
    if host:
        fmt.line(f"  Host:     {host}")
    fmt.line(f"  On-call:  {current or 'nobody'}")
    fmt.blank()

    # Try to notify
    try:
        from freq.jarvis.notify import notify, configured_providers

        providers = configured_providers(cfg)
        if providers:
            notify(
                cfg,
                message=f"[{inc_id}] {severity.upper()}: {message}" + (f" (host: {host})" if host else ""),
                title=f"FREQ Incident: {inc_id}",
                severity=severity,
            )
            fmt.step_ok(f"Notified via {', '.join(providers)}")
    except ImportError:
        pass

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Acknowledge: freq oncall ack {inc_id}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_ack(cfg: FreqConfig, args) -> int:
    """Acknowledge an incident."""
    inc_id = getattr(args, "name", None)
    if not inc_id:
        fmt.error("Usage: freq oncall ack <INC-XXX>")
        return 1

    incidents = _load_incidents(cfg)
    inc = next((i for i in incidents if i["id"] == inc_id), None)
    if not inc:
        fmt.error(f"Incident not found: {inc_id}")
        return 1

    inc["status"] = "acknowledged"
    inc["acknowledged_by"] = os.environ.get("USER", "unknown")
    inc["acknowledged_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save_incidents(cfg, incidents)

    fmt.step_ok(f"{inc_id} acknowledged by {inc['acknowledged_by']}")
    return 0


def _cmd_escalate(cfg: FreqConfig, args) -> int:
    """Escalate an incident to next on-call."""
    inc_id = getattr(args, "name", None)
    if not inc_id:
        fmt.error("Usage: freq oncall escalate <INC-XXX>")
        return 1

    incidents = _load_incidents(cfg)
    inc = next((i for i in incidents if i["id"] == inc_id), None)
    if not inc:
        fmt.error(f"Incident not found: {inc_id}")
        return 1

    schedule = _load_schedule(cfg)
    users = schedule.get("users", [])
    current = _get_current_oncall(schedule)

    if current in users:
        idx = users.index(current)
        next_user = users[(idx + 1) % len(users)]
    else:
        next_user = users[0] if users else "nobody"

    inc["notes"].append(
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "text": f"Escalated from {current} to {next_user}",
        }
    )
    _save_incidents(cfg, incidents)

    fmt.step_ok(f"{inc_id} escalated to {next_user}")
    return 0


def _cmd_resolve(cfg: FreqConfig, args) -> int:
    """Resolve an incident."""
    inc_id = getattr(args, "name", None)
    if not inc_id:
        fmt.error("Usage: freq oncall resolve <INC-XXX>")
        return 1

    note = getattr(args, "note", "") or ""

    incidents = _load_incidents(cfg)
    inc = next((i for i in incidents if i["id"] == inc_id), None)
    if not inc:
        fmt.error(f"Incident not found: {inc_id}")
        return 1

    inc["status"] = "resolved"
    inc["resolved_by"] = os.environ.get("USER", "unknown")
    inc["resolved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if note:
        inc["notes"].append({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "text": note})
    _save_incidents(cfg, incidents)

    fmt.step_ok(f"{inc_id} resolved by {inc['resolved_by']}")
    return 0


def _cmd_history(cfg: FreqConfig, args) -> int:
    """Show incident history."""
    fmt.header("Incident History")
    fmt.blank()

    incidents = _load_incidents(cfg)
    if not incidents:
        fmt.line(f"  {fmt.C.DIM}No incidents recorded.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    lines = getattr(args, "lines", 20) or 20
    recent = incidents[-lines:]

    fmt.table_header(("ID", 10), ("STATUS", 14), ("SEVERITY", 10), ("MESSAGE", 30), ("TIME", 20))

    for inc in reversed(recent):
        status = inc.get("status", "open")
        status_color = {"open": fmt.C.RED, "acknowledged": fmt.C.YELLOW, "resolved": fmt.C.GREEN}.get(status, "")
        sev = inc.get("severity", "info")
        sev_color = {"critical": fmt.C.RED, "warning": fmt.C.YELLOW}.get(sev, fmt.C.CYAN)

        fmt.table_row(
            (inc["id"], 10),
            (f"{status_color}{status}{fmt.C.RESET}", 14),
            (f"{sev_color}{sev}{fmt.C.RESET}", 10),
            (inc.get("message", "")[:30], 30),
            (inc.get("created", "")[:19], 20),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(incidents)} total incidents ({len(recent)} shown){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
