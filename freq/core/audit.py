"""FREQ Audit Trail — append-only log of infrastructure changes.

Records every modification freq makes to fleet infrastructure:
user creation, key deployment, service installation, config writes.
Separate from general logging — this answers "what did freq change?"

Format: JSON Lines at data/log/audit.jsonl
Each line: {"ts": "...", "action": "deploy_user", "target": "10.0.0.1", ...}
"""

import json
import os
from datetime import datetime, timezone

from freq.core.log import _redact


_AUDIT_FILE: str = ""


def init(log_dir: str) -> None:
    """Initialize audit trail. Called once at startup."""
    global _AUDIT_FILE
    os.makedirs(log_dir, exist_ok=True)
    _AUDIT_FILE = os.path.join(log_dir, "audit.jsonl")


def record(action: str, target: str, result: str, **details) -> None:
    """Record an infrastructure change.

    Args:
        action: What was done (deploy_user, deploy_key, deploy_service, etc.)
        target: What was affected (IP address, hostname, file path)
        result: Outcome (success, failed, skipped, dry_run)
        **details: Additional context (user, method, error, etc.)
    """
    if not _AUDIT_FILE:
        return

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": _redact(target),
        "result": result,
    }
    entry.update({k: _redact(str(v)) for k, v in details.items()})

    try:
        with open(_AUDIT_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except (OSError, PermissionError):
        pass  # Audit logging should never crash the tool


def record_change(host: str, action: str, before: dict, after: dict, **details) -> None:
    """Record a before/after change on a host.

    Writes to data/log/changes.jsonl for change tracking (Item 7).
    """
    if not _AUDIT_FILE:
        return

    changes_file = _AUDIT_FILE.replace("audit.jsonl", "changes.jsonl")
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "action": action,
        "before": before,
        "after": after,
    }
    entry.update(details)

    try:
        with open(changes_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except (OSError, PermissionError):
        pass


def read_log(path: str = "", last: int = 0, host: str = "", action: str = "") -> list:
    """Read audit entries with optional filtering."""
    audit_file = path or _AUDIT_FILE
    if not audit_file or not os.path.isfile(audit_file):
        return []

    entries = []
    try:
        with open(audit_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if host and entry.get("target") != host:
                    continue
                if action and entry.get("action") != action:
                    continue
                entries.append(entry)
    except (OSError, PermissionError):
        return []

    if last > 0:
        entries = entries[-last:]
    return entries


def snapshot_host(ip: str, svc_name: str, htype: str, cfg=None) -> dict:
    """Check current state of a host before/after modification.

    Returns dict with: user_exists, sudo, key_deployed
    """
    from freq.core.ssh import run as ssh_run

    state = {"user_exists": False, "sudo": False, "key_deployed": False}

    if htype in ("idrac", "switch"):
        # For legacy devices, just check if SSH as svc_name works
        r = ssh_run(
            host=ip,
            command="echo OK" if htype == "switch" else "racadm getsysinfo -s",
            key_path=getattr(cfg, "ssh_rsa_key_path", None) if cfg else None,
            connect_timeout=5,
            command_timeout=10,
            htype=htype,
            use_sudo=False,
            cfg=cfg,
        )
        state["user_exists"] = r.returncode == 0
        return state

    key_path = getattr(cfg, "ssh_key_path", None) if cfg else None
    if not key_path:
        return state

    # Check user exists + sudo + key
    cmd = (
        f"id {svc_name} >/dev/null 2>&1 && echo USER_OK;"
        f"sudo -n true 2>/dev/null && echo SUDO_OK;"
        f"test -f /home/{svc_name}/.ssh/authorized_keys && echo KEY_OK"
    )
    r = ssh_run(
        host=ip, command=cmd, key_path=key_path,
        connect_timeout=5, command_timeout=10,
        htype=htype, use_sudo=False, cfg=cfg,
    )
    out = r.stdout or ""
    state["user_exists"] = "USER_OK" in out
    state["sudo"] = "SUDO_OK" in out
    state["key_deployed"] = "KEY_OK" in out
    return state
