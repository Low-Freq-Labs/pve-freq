"""Container-log retrieval below dashboard HTTP transport."""

import re
import shlex

from freq.core import resolve
from freq.core.ssh import run as ssh_single


def read_container_logs(cfg, host, name, requested_lines):
    """Validate and retrieve one container's bounded log tail."""
    lines = min(int(requested_lines), 200)
    if not host or not name:
        return {"error": "host and name required"}, 400
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        return {"error": "Invalid container name"}, 400

    resolved_host = resolve.container_vm_host(cfg, host)
    if not resolved_host:
        return {"error": f"Host not found: {host}"}, 404

    result = ssh_single(
        host=resolved_host.ip,
        command=f"docker logs --tail {lines} {shlex.quote(name)} 2>&1",
        key_path=cfg.ssh_key_path,
        connect_timeout=5,
        command_timeout=15,
        htype=resolved_host.htype or "docker",
        use_sudo=False,
        cfg=cfg,
    )
    return {
        "ok": result.returncode == 0,
        "output": result.stdout if result and result.returncode == 0 else "",
        "error": result.stderr.strip() if result and result.returncode != 0 else "",
        "returncode": result.returncode if result else 1,
        "container": name,
        "host": host,
        "resolved_host": resolved_host.label,
        "ip": resolved_host.ip,
        "lines": lines,
    }, 200
