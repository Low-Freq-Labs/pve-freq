"""Incident and change management for FREQ.

Domain: freq ops incident/change <action>
What: Track incidents, manage changes, maintenance windows. ITIL-lite
      for homelab and SMB — just the useful parts, none of the bureaucracy.
Replaces: PagerDuty incident tracking, ServiceNow change management,
          spreadsheet-based incident logs
Architecture:
    - Incidents stored in conf/incidents/ as JSON files
    - Changes stored in conf/changes/ as JSON files
    - Timeline is append-only per incident
    - Notification integration via jarvis/notify.py
Design decisions:
    - One file per incident/change. Simple, grep-able, git-trackable.
    - Status workflow: open -> investigating -> resolved -> closed.
    - Changes: draft -> approved -> implementing -> completed/rolled-back.
    - No database. JSON files are the database.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


INC_DIR = "incidents"
CHG_DIR = "changes"


def _inc_dir(cfg):
    path = os.path.join(cfg.conf_dir, INC_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _chg_dir(cfg):
    path = os.path.join(cfg.conf_dir, CHG_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _next_id(directory, prefix):
    existing = [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".json")]
    nums = []
    for f in existing:
        try:
            nums.append(int(f.replace(prefix, "").replace(".json", "")))
        except ValueError:
            pass
    return max(nums) + 1 if nums else 1


# ---------------------------------------------------------------------------
# Incident Commands
# ---------------------------------------------------------------------------


def cmd_incident_create(cfg: FreqConfig, pack, args) -> int:
    """Create a new incident."""
    title = getattr(args, "title", None)
    severity = getattr(args, "severity", "warning")
    if not title:
        fmt.error("Usage: freq ops incident create <title> [--severity critical|warning|info]")
        return 1

    inc_id = _next_id(_inc_dir(cfg), "INC-")
    incident = {
        "id": f"INC-{inc_id}",
        "title": title,
        "severity": severity,
        "status": "open",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "timeline": [{"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": "created", "note": title}],
    }

    filepath = os.path.join(_inc_dir(cfg), f"INC-{inc_id}.json")
    with open(filepath, "w") as f:
        json.dump(incident, f, indent=2)

    fmt.success(f"Incident INC-{inc_id} created: {title}")
    logger.info("incident_create", id=f"INC-{inc_id}", title=title)
    return 0


def cmd_incident_list(cfg: FreqConfig, pack, args) -> int:
    """List incidents."""
    path = _inc_dir(cfg)
    files = sorted([f for f in os.listdir(path) if f.endswith(".json")], reverse=True)

    fmt.header("Incidents", breadcrumb="FREQ > Ops > Incident")
    fmt.blank()

    if not files:
        fmt.info("No incidents recorded")
        fmt.footer()
        return 0

    fmt.table_header(("ID", 8), ("Status", 14), ("Severity", 10), ("Title", 36), ("Created", 18))
    for fname in files[:20]:
        with open(os.path.join(path, fname)) as f:
            inc = json.load(f)
        status = inc.get("status", "?")
        sev = inc.get("severity", "?")
        s_color = fmt.C.RED if status == "open" else fmt.C.YELLOW if status == "investigating" else fmt.C.GREEN
        fmt.table_row(
            (inc.get("id", ""), 8),
            (f"{s_color}{status}{fmt.C.RESET}", 14),
            (sev, 10),
            (inc.get("title", "")[:36], 36),
            (inc.get("created", "")[:16], 18),
        )

    fmt.blank()
    fmt.info(f"{len(files)} incident(s)")
    fmt.footer()
    return 0


def cmd_incident_update(cfg: FreqConfig, pack, args) -> int:
    """Update incident status."""
    inc_id = getattr(args, "id", None)
    status = getattr(args, "status", None)
    note = getattr(args, "note", "")

    if not inc_id or not status:
        fmt.error("Usage: freq ops incident update <id> --status investigating|resolved|closed [--note text]")
        return 1

    filepath = os.path.join(_inc_dir(cfg), f"{inc_id}.json")
    if not os.path.exists(filepath):
        fmt.error(f"Incident {inc_id} not found")
        return 1

    with open(filepath) as f:
        inc = json.load(f)

    inc["status"] = status
    inc["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    inc["timeline"].append(
        {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "action": f"status -> {status}",
            "note": note,
        }
    )

    with open(filepath, "w") as f:
        json.dump(inc, f, indent=2)

    fmt.success(f"{inc_id} updated to {status}")
    return 0


# ---------------------------------------------------------------------------
# Change Commands
# ---------------------------------------------------------------------------


def cmd_change_create(cfg: FreqConfig, pack, args) -> int:
    """Create a change request."""
    title = getattr(args, "title", None)
    if not title:
        fmt.error("Usage: freq ops change create <title>")
        return 1

    chg_id = _next_id(_chg_dir(cfg), "CHG-")
    change = {
        "id": f"CHG-{chg_id}",
        "title": title,
        "status": "draft",
        "risk": getattr(args, "risk", "low"),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "timeline": [{"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": "created"}],
    }

    filepath = os.path.join(_chg_dir(cfg), f"CHG-{chg_id}.json")
    with open(filepath, "w") as f:
        json.dump(change, f, indent=2)

    fmt.success(f"Change CHG-{chg_id} created: {title}")
    return 0


def cmd_change_list(cfg: FreqConfig, pack, args) -> int:
    """List change requests."""
    path = _chg_dir(cfg)
    files = sorted([f for f in os.listdir(path) if f.endswith(".json")], reverse=True)

    fmt.header("Changes", breadcrumb="FREQ > Ops > Change")
    fmt.blank()

    if not files:
        fmt.info("No change requests")
        fmt.footer()
        return 0

    fmt.table_header(("ID", 8), ("Status", 14), ("Risk", 6), ("Title", 36), ("Created", 18))
    for fname in files[:20]:
        with open(os.path.join(path, fname)) as f:
            chg = json.load(f)
        fmt.table_row(
            (chg.get("id", ""), 8),
            (chg.get("status", ""), 14),
            (chg.get("risk", ""), 6),
            (chg.get("title", "")[:36], 36),
            (chg.get("created", "")[:16], 18),
        )

    fmt.blank()
    fmt.info(f"{len(files)} change(s)")
    fmt.footer()
    return 0
