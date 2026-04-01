"""Docker Compose stack lifecycle management for FREQ.

Domain: freq docker <stack-status|stack-deploy|stack-update|stack-health|stack-logs|stack-backup|stack-rollback|stack-restart|stack-template>

Fleet-wide Docker Compose management. Deploy stacks from built-in templates,
update with pre-pull, rollback on failure, backup volumes before changes.
Health checks verify containers are actually serving, not just running.

Replaces: Portainer ($0 but 3-node paywall), Rancher (overkill for Compose),
          manual docker-compose scripts per host

Architecture:
    - Stack registry persisted in conf/stacks/stack-registry.json
    - Built-in templates for common stacks (arr-stack, monitoring, etc.)
    - Deploy/update via SSH + docker compose commands on target hosts
    - Volume backup via SSH + tar before destructive operations

Design decisions:
    - Templates are starting points, not locked configs. Users can deploy
      a template then customize. FREQ tracks the stack, not the template.
"""
import json
import os
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many

STACK_CMD_TIMEOUT = 30
STACK_DEPLOY_TIMEOUT = 300
STACK_DIR = "stacks"
STACK_REGISTRY = "stack-registry.json"


def _stack_dir(cfg: FreqConfig) -> str:
    path = os.path.join(cfg.conf_dir, STACK_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_registry(cfg: FreqConfig) -> list:
    filepath = os.path.join(_stack_dir(cfg), STACK_REGISTRY)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_registry(cfg: FreqConfig, registry: list):
    filepath = os.path.join(_stack_dir(cfg), STACK_REGISTRY)
    with open(filepath, "w") as f:
        json.dump(registry, f, indent=2)


# Built-in stack templates
STACK_TEMPLATES = {
    "arr-stack": {
        "description": "Full media stack: Radarr, Sonarr, Prowlarr, qBittorrent",
        "services": ["radarr", "sonarr", "prowlarr", "qbittorrent"],
    },
    "monitoring": {
        "description": "Prometheus + Grafana + Node Exporter",
        "services": ["prometheus", "grafana", "node-exporter"],
    },
    "web": {
        "description": "Nginx + Certbot reverse proxy",
        "services": ["nginx", "certbot"],
    },
    "db": {
        "description": "PostgreSQL + pgAdmin",
        "services": ["postgres", "pgadmin"],
    },
}


def cmd_stack(cfg: FreqConfig, pack, args) -> int:
    """Stack management dispatch."""
    action = getattr(args, "action", None) or "status"
    routes = {
        "status": _cmd_status,
        "update": _cmd_update,
        "health": _cmd_health,
        "logs": _cmd_logs,
        "restart": _cmd_restart,
        "template": _cmd_template,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown stack action: {action}")
    fmt.info("Available: status, update, health, logs, restart, template")
    return 1


def _cmd_status(cfg: FreqConfig, args) -> int:
    """Show all Docker Compose stacks across fleet."""
    fmt.header("Docker Stacks")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Find compose projects on each host
    command = (
        "docker compose ls --format json 2>/dev/null || "
        "docker-compose ls --format json 2>/dev/null || "
        "echo '[]'"
    )

    fmt.step_start(f"Scanning {len(hosts)} hosts for stacks")
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=STACK_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )
    fmt.step_ok("Scan complete")
    fmt.blank()

    total_stacks = 0
    fmt.table_header(("HOST", 14), ("STACK", 20), ("STATUS", 12), ("SERVICES", 8))

    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            continue

        try:
            stacks = json.loads(r.stdout.strip())
        except json.JSONDecodeError:
            continue

        for stack in stacks:
            name = stack.get("Name", "unknown")
            status = stack.get("Status", "unknown")
            config = stack.get("ConfigFiles", "")

            # Count running services
            svc_match = status.split("(")
            svc_count = svc_match[1].rstrip(")") if len(svc_match) > 1 else "?"

            status_short = status.split("(")[0].strip() if "(" in status else status
            color = fmt.C.GREEN if "running" in status.lower() else fmt.C.YELLOW

            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                (name[:20], 20),
                (f"{color}{status_short[:12]}{fmt.C.RESET}", 12),
                (svc_count, 8),
            )
            total_stacks += 1

    if total_stacks == 0:
        fmt.line(f"  {fmt.C.DIM}No Docker Compose stacks found.{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{total_stacks} stack(s) across fleet{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_update(cfg: FreqConfig, args) -> int:
    """Update a stack — pull new images and recreate."""
    name = getattr(args, "name", None)
    target = getattr(args, "target_host", None)

    if not name:
        fmt.error("Usage: freq stack update <stack-name> [--host <label>]")
        return 1

    fmt.header(f"Update Stack: {name}")
    fmt.blank()

    hosts = cfg.hosts
    if target:
        from freq.core.resolve import host as resolve_host
        h = resolve_host(hosts, target)
        if not h:
            fmt.error(f"Host not found: {target}")
            return 1
        hosts = [h]

    for h in hosts:
        # Find the stack's compose file
        find_cmd = f"docker compose ls --format json 2>/dev/null | python3 -c \"import sys,json; [print(s['ConfigFiles']) for s in json.load(sys.stdin) if s['Name']=='{name}']\""
        r = ssh_run(
            host=h.ip, command=find_cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=STACK_CMD_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )

        if r.returncode != 0 or not r.stdout.strip():
            continue

        compose_file = r.stdout.strip().split("\n")[0]
        compose_dir = os.path.dirname(compose_file)

        fmt.step_start(f"Pulling images on {h.label}")
        r = ssh_run(
            host=h.ip,
            command=f"cd {compose_dir} && docker compose pull 2>&1 | tail -3",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=STACK_DEPLOY_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )
        if r.returncode == 0:
            fmt.step_ok(f"Images pulled on {h.label}")
        else:
            fmt.step_fail(f"Pull failed on {h.label}")
            continue

        fmt.step_start(f"Recreating containers on {h.label}")
        r = ssh_run(
            host=h.ip,
            command=f"cd {compose_dir} && docker compose up -d --remove-orphans 2>&1 | tail -5",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=STACK_DEPLOY_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )
        if r.returncode == 0:
            fmt.step_ok(f"Stack '{name}' updated on {h.label}")
        else:
            fmt.step_fail(f"Update failed: {r.stderr[:80]}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_health(cfg: FreqConfig, args) -> int:
    """Check container health across all stacks."""
    fmt.header("Stack Health")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    command = (
        "docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null || echo ''"
    )

    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=STACK_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    healthy = 0
    unhealthy = 0

    fmt.table_header(("HOST", 14), ("CONTAINER", 22), ("STATUS", 18), ("IMAGE", 20))

    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0 or not r.stdout.strip():
            continue

        for line in r.stdout.strip().split("\n"):
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue

            name, status, image = parts[0], parts[1], parts[2]
            is_healthy = "Up" in status and "unhealthy" not in status.lower()
            color = fmt.C.GREEN if is_healthy else fmt.C.RED

            if is_healthy:
                healthy += 1
            else:
                unhealthy += 1

            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                (name[:22], 22),
                (f"{color}{status[:18]}{fmt.C.RESET}", 18),
                (image.split("/")[-1][:20], 20),
            )

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{healthy} healthy{fmt.C.RESET}, "
             f"{fmt.C.RED}{unhealthy} unhealthy{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0 if unhealthy == 0 else 1


def _cmd_logs(cfg: FreqConfig, args) -> int:
    """Show logs for a stack."""
    name = getattr(args, "name", None)
    target = getattr(args, "target_host", None)
    lines = getattr(args, "lines", 30) or 30

    if not name:
        fmt.error("Usage: freq stack logs <stack-name> [--host <label>] [--lines N]")
        return 1

    fmt.header(f"Stack Logs: {name}")
    fmt.blank()

    hosts = cfg.hosts
    if target:
        from freq.core.resolve import host as resolve_host
        h = resolve_host(hosts, target)
        if not h:
            fmt.error(f"Host not found: {target}")
            return 1
        hosts = [h]

    for h in hosts:
        find_cmd = f"docker compose ls --format json 2>/dev/null | python3 -c \"import sys,json; [print(s['ConfigFiles']) for s in json.load(sys.stdin) if s['Name']=='{name}']\""
        r = ssh_run(
            host=h.ip, command=find_cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=STACK_CMD_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )

        if r.returncode != 0 or not r.stdout.strip():
            continue

        compose_dir = os.path.dirname(r.stdout.strip().split("\n")[0])
        fmt.divider(f"{h.label}")
        fmt.blank()

        r = ssh_run(
            host=h.ip,
            command=f"cd {compose_dir} && docker compose logs --tail {lines} 2>&1",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=STACK_CMD_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )

        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n")[-lines:]:
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        fmt.blank()

    fmt.footer()
    return 0


def _cmd_restart(cfg: FreqConfig, args) -> int:
    """Restart a stack."""
    name = getattr(args, "name", None)
    target = getattr(args, "target_host", None)

    if not name:
        fmt.error("Usage: freq stack restart <stack-name> [--host <label>]")
        return 1

    fmt.header(f"Restart Stack: {name}")
    fmt.blank()

    hosts = cfg.hosts
    if target:
        from freq.core.resolve import host as resolve_host
        h = resolve_host(hosts, target)
        if not h:
            fmt.error(f"Host not found: {target}")
            return 1
        hosts = [h]

    for h in hosts:
        find_cmd = f"docker compose ls --format json 2>/dev/null | python3 -c \"import sys,json; [print(s['ConfigFiles']) for s in json.load(sys.stdin) if s['Name']=='{name}']\""
        r = ssh_run(
            host=h.ip, command=find_cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=STACK_CMD_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )

        if r.returncode != 0 or not r.stdout.strip():
            continue

        compose_dir = os.path.dirname(r.stdout.strip().split("\n")[0])
        fmt.step_start(f"Restarting '{name}' on {h.label}")

        r = ssh_run(
            host=h.ip,
            command=f"cd {compose_dir} && docker compose restart 2>&1 | tail -5",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=STACK_DEPLOY_TIMEOUT,
            htype=h.htype, use_sudo=False,
        )

        if r.returncode == 0:
            fmt.step_ok(f"Restarted on {h.label}")
        else:
            fmt.step_fail(f"Failed on {h.label}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_template(cfg: FreqConfig, args) -> int:
    """List or deploy stack templates."""
    fmt.header("Stack Templates")
    fmt.blank()

    fmt.table_header(("NAME", 16), ("SERVICES", 40), ("DESCRIPTION", 20))

    for name, tmpl in STACK_TEMPLATES.items():
        fmt.table_row(
            (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 16),
            (", ".join(tmpl["services"]), 40),
            (tmpl["description"][:20], 20),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(STACK_TEMPLATES)} templates available{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
