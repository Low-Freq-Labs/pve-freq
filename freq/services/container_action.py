"""Container-action execution below dashboard HTTP transport."""

import re
import shlex

from freq.core import resolve
from freq.core.ssh import run as ssh_single


def run_container_action(cfg, host, name, action):
    """Validate and execute one Docker container action.

    Returns the response payload and HTTP status so the caller owns only
    transport concerns.
    """
    if not host or not name:
        return {"error": "host and name required"}, 400
    if action not in ("restart", "stop", "start"):
        return {"error": "action must be restart, stop, or start"}, 400
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        return {"error": "Invalid container name"}, 400

    resolved_host = resolve.container_vm_host(cfg, host)
    if not resolved_host:
        return {"error": f"Host not found: {host}"}, 404

    result = ssh_single(
        host=resolved_host.ip,
        command=f"docker {action} {shlex.quote(name)} 2>&1",
        key_path=cfg.ssh_key_path,
        connect_timeout=5,
        command_timeout=30,
        htype=resolved_host.htype or "docker",
        use_sudo=False,
        cfg=cfg,
    )
    return {
        "ok": result.returncode == 0,
        "output": result.stdout.strip() if result and result.stdout else "",
        "error": result.stderr.strip() if result and result.returncode != 0 else "",
        "returncode": result.returncode if result else 1,
        "action": action,
        "container": name,
        "host": host,
        "resolved_host": resolved_host.label,
        "ip": resolved_host.ip,
    }, 200
