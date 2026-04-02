"""Automation engine for FREQ — reactors, workflows, event-driven ops.

Domain: freq auto react/workflow/job <action>
What: Event-driven automation with self-healing rules, DAG workflows,
      scheduled jobs. The "if X then Y" engine for infrastructure.
Replaces: StackStorm, Rundeck, custom cron scripts, manual remediation
Architecture:
    - Reactors: if-then rules stored in conf/auto/reactors.json
    - Workflows: ordered step lists stored in conf/auto/workflows/
    - Jobs: named operations with schedule, stored in conf/auto/jobs.json
    - Event bus: all freq operations can emit events (future)
Design decisions:
    - Reactors are declarative JSON, not scripts. Safe and auditable.
    - Workflows are linear step lists (not DAGs yet — YAGNI for v3.0.0).
    - Jobs wrap existing freq commands — no new execution model.
    - Cooldowns prevent reactor storms.
"""
import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


AUTO_DIR = "auto"


def _auto_dir(cfg):
    path = os.path.join(cfg.conf_dir, AUTO_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_reactors(cfg):
    filepath = os.path.join(_auto_dir(cfg), "reactors.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return {"reactors": []}


def _save_reactors(cfg, data):
    filepath = os.path.join(_auto_dir(cfg), "reactors.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _workflows_dir(cfg):
    path = os.path.join(_auto_dir(cfg), "workflows")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Reactor Commands
# ---------------------------------------------------------------------------

def cmd_react_list(cfg: FreqConfig, pack, args) -> int:
    """List automation reactors."""
    data = _load_reactors(cfg)
    reactors = data.get("reactors", [])

    fmt.header("Reactors", breadcrumb="FREQ > Auto > React")
    fmt.blank()

    if not reactors:
        fmt.info("No reactors defined")
        fmt.info("Add: freq auto react add --name <name> --trigger <event> --action <command>")
        fmt.footer()
        return 0

    fmt.table_header(("Name", 16), ("Trigger", 20), ("Action", 24), ("Enabled", 8))
    for r in reactors:
        enabled = r.get("enabled", True)
        color = fmt.C.GREEN if enabled else fmt.C.DIM
        fmt.table_row(
            (r.get("name", ""), 16),
            (r.get("trigger", ""), 20),
            (r.get("action", ""), 24),
            (f"{color}{'yes' if enabled else 'no'}{fmt.C.RESET}", 8),
        )

    fmt.blank()
    fmt.info(f"{len(reactors)} reactor(s)")
    fmt.footer()
    return 0


def cmd_react_add(cfg: FreqConfig, pack, args) -> int:
    """Add an automation reactor."""
    name = getattr(args, "name", None)
    trigger = getattr(args, "trigger", None)
    action = getattr(args, "action", None)

    if not name or not trigger or not action:
        fmt.error("Usage: freq auto react add --name <name> --trigger <event> --action <command>")
        return 1

    data = _load_reactors(cfg)
    reactors = data.get("reactors", [])

    if any(r["name"] == name for r in reactors):
        fmt.error(f"Reactor '{name}' already exists")
        return 1

    reactors.append({
        "name": name,
        "trigger": trigger,
        "action": action,
        "enabled": True,
        "cooldown": int(getattr(args, "cooldown", 300)),
        "created": time.strftime("%Y-%m-%d"),
    })
    data["reactors"] = reactors
    _save_reactors(cfg, data)

    fmt.success(f"Reactor '{name}' added: {trigger} -> {action}")
    return 0


def cmd_react_disable(cfg: FreqConfig, pack, args) -> int:
    """Disable a reactor."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq auto react disable <name>")
        return 1

    data = _load_reactors(cfg)
    for r in data.get("reactors", []):
        if r["name"] == name:
            r["enabled"] = False
            _save_reactors(cfg, data)
            fmt.success(f"Reactor '{name}' disabled")
            return 0

    fmt.error(f"Reactor '{name}' not found")
    return 1


# ---------------------------------------------------------------------------
# Workflow Commands
# ---------------------------------------------------------------------------

def cmd_workflow_list(cfg: FreqConfig, pack, args) -> int:
    """List workflows."""
    path = _workflows_dir(cfg)
    files = [f[:-5] for f in sorted(os.listdir(path)) if f.endswith(".json")]

    fmt.header("Workflows", breadcrumb="FREQ > Auto > Workflow")
    fmt.blank()

    if not files:
        fmt.info("No workflows defined")
        fmt.footer()
        return 0

    for name in files:
        filepath = os.path.join(path, f"{name}.json")
        with open(filepath) as f:
            wf = json.load(f)
        steps = len(wf.get("steps", []))
        desc = wf.get("description", "")
        fmt.line(f"  {fmt.C.CYAN}{name:<20}{fmt.C.RESET} {steps} steps — {desc}")

    fmt.blank()
    fmt.info(f"{len(files)} workflow(s)")
    fmt.footer()
    return 0


def cmd_workflow_create(cfg: FreqConfig, pack, args) -> int:
    """Create a workflow."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq auto workflow create <name>")
        return 1

    filepath = os.path.join(_workflows_dir(cfg), f"{name}.json")
    if os.path.exists(filepath):
        fmt.error(f"Workflow '{name}' already exists")
        return 1

    workflow = {
        "name": name,
        "description": getattr(args, "description", ""),
        "created": time.strftime("%Y-%m-%d"),
        "steps": [
            {"order": 1, "command": "freq fleet status", "description": "Check fleet health"},
        ],
    }

    with open(filepath, "w") as f:
        json.dump(workflow, f, indent=2)

    fmt.success(f"Workflow '{name}' created")
    fmt.info(f"Edit: {filepath}")
    return 0


# ---------------------------------------------------------------------------
# Job Commands
# ---------------------------------------------------------------------------

def cmd_job_list(cfg: FreqConfig, pack, args) -> int:
    """List scheduled jobs."""
    filepath = os.path.join(_auto_dir(cfg), "jobs.json")
    if not os.path.exists(filepath):
        fmt.info("No jobs defined")
        return 0

    with open(filepath) as f:
        data = json.load(f)

    jobs = data.get("jobs", [])
    fmt.header("Jobs", breadcrumb="FREQ > Auto > Job")
    fmt.blank()

    if not jobs:
        fmt.info("No jobs defined")
        fmt.footer()
        return 0

    fmt.table_header(("Name", 16), ("Command", 30), ("Schedule", 12), ("Last Run", 18))
    for j in jobs:
        fmt.table_row(
            (j.get("name", ""), 16),
            (j.get("command", ""), 30),
            (j.get("schedule", ""), 12),
            (j.get("last_run", "never"), 18),
        )

    fmt.blank()
    fmt.info(f"{len(jobs)} job(s)")
    fmt.footer()
    return 0
