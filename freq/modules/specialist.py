"""Specialist VM workspace deployment for FREQ.

Commands: specialist create, specialist health, specialist status, specialist list

Deploys complete Claude Code workspaces: CLAUDE.md, settings, tmux, dev scripts,
mailbox structure. Each specialist gets a role-specific configuration.
"""
import json
import os
import time

from freq.core import fmt
from freq.core import resolve
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run


# Role templates — each defines the specialist's workspace configuration
ROLE_TEMPLATES = {
    "sandbox": {
        "description": "General-purpose sandbox for experimentation",
        "tmux_color": "red",
        "session_name": "SANDBOX",
        "model": "claude-sonnet-4-6",
    },
    "dev": {
        "description": "Development specialist for building features",
        "tmux_color": "blue",
        "session_name": "FREQDEV",
        "model": "claude-opus-4-6[1m]",
    },
    "infra": {
        "description": "Infrastructure manager for fleet operations",
        "tmux_color": "green",
        "session_name": "INFRA",
        "model": "claude-opus-4-6[1m]",
    },
    "security": {
        "description": "Security specialist for auditing and hardening",
        "tmux_color": "yellow",
        "session_name": "SECOPS",
        "model": "claude-sonnet-4-6",
    },
    "media": {
        "description": "Media operations specialist for Plex stack management",
        "tmux_color": "magenta",
        "session_name": "MEDIAOPS",
        "model": "claude-sonnet-4-6",
    },
}

TMUX_COLORS = {
    "red": "colour196",
    "blue": "colour33",
    "green": "colour46",
    "yellow": "colour226",
    "magenta": "colour201",
}


def cmd_specialist(cfg: FreqConfig, pack, args) -> int:
    """Specialist VM management."""
    action = getattr(args, "action", None)

    routes = {
        "create": _cmd_create,
        "health": _cmd_health,
        "status": _cmd_status,
        "list": _cmd_list,
        "roles": _cmd_roles,
    }

    handler = routes.get(action)
    if handler:
        return handler(cfg, args)

    if not action:
        return _cmd_list(cfg, args)

    fmt.error(f"Unknown specialist action: {action}")
    fmt.info("Available: create, health, status, list, roles")
    return 1


def _ssh_cmd(cfg, ip, command, timeout=30):
    """Run command on a specialist VM."""
    return ssh_run(
        host=ip, command=command, key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout, command_timeout=timeout,
        htype="linux", use_sudo=False,
    )


def _cmd_roles(cfg, args) -> int:
    """List available specialist roles."""
    fmt.header("Specialist Roles")
    fmt.blank()
    fmt.table_header(("ROLE", 12), ("DESCRIPTION", 40), ("MODEL", 24))

    for role, tmpl in ROLE_TEMPLATES.items():
        fmt.table_row(
            (f"{fmt.C.BOLD}{role}{fmt.C.RESET}", 12),
            (tmpl["description"], 40),
            (tmpl["model"], 24),
        )

    fmt.blank()
    fmt.info("Usage: freq specialist create <host> --role <role> --name <name>")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_create(cfg, args) -> int:
    """Deploy a complete Claude Code workspace to a VM."""
    target = getattr(args, "target", None)
    role = getattr(args, "role", None) or "sandbox"
    name = getattr(args, "name", None)

    if not target:
        fmt.error("Usage: freq specialist create <host_ip> --role <role> --name <name>")
        return 1

    if role not in ROLE_TEMPLATES:
        fmt.error(f"Unknown role: {role}")
        fmt.info(f"Available: {', '.join(ROLE_TEMPLATES.keys())}")
        return 1

    tmpl = ROLE_TEMPLATES[role]
    specialist_name = name or f"{role}-specialist"

    # Try to resolve as fleet host first, fall back to IP
    host = resolve.by_target(cfg.hosts, target)
    ip = host.ip if host else target

    fmt.header(f"Deploy Specialist: {specialist_name}")
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Target:{fmt.C.RESET}  {ip}")
    fmt.line(f"  {fmt.C.BOLD}Role:{fmt.C.RESET}    {role}")
    fmt.line(f"  {fmt.C.BOLD}Name:{fmt.C.RESET}    {specialist_name}")
    fmt.line(f"  {fmt.C.BOLD}Model:{fmt.C.RESET}   {tmpl['model']}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Deploy workspace? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Step 1: Create workspace directory
    home_dir = f"/home/{cfg.ssh_service_account}"
    workspace = f"{home_dir}/{specialist_name}"

    fmt.step_start("Creating workspace directory")
    r = _ssh_cmd(cfg, ip, f"mkdir -p {workspace}", timeout=10)
    if r.returncode == 0:
        fmt.step_ok(f"Workspace: {workspace}")
    else:
        fmt.step_fail(f"Cannot create workspace: {r.stderr}")
        return 1

    # Step 2: Deploy CLAUDE.md
    fmt.step_start("Deploying CLAUDE.md")
    claude_md = _generate_claude_md(specialist_name, role, tmpl, ip, cfg.ssh_service_account)
    r = _ssh_cmd(cfg, ip,
                  f"cat > {workspace}/CLAUDE.md << 'FREQEOF'\n{claude_md}\nFREQEOF",
                  timeout=10)
    fmt.step_ok("CLAUDE.md deployed") if r.returncode == 0 else fmt.step_fail("Failed")

    # Step 3: Deploy Claude Code settings
    fmt.step_start("Deploying Claude settings")
    settings = _generate_settings(tmpl)
    settings_dir = f"{home_dir}/.claude"
    r = _ssh_cmd(cfg, ip,
                  f"mkdir -p {settings_dir} && "
                  f"cat > {settings_dir}/settings.json << 'FREQEOF'\n{settings}\nFREQEOF",
                  timeout=10)
    fmt.step_ok("Settings deployed") if r.returncode == 0 else fmt.step_fail("Failed")

    # Step 4: Deploy tmux config
    fmt.step_start("Deploying tmux configuration")
    tmux_conf = _generate_tmux_conf(tmpl, specialist_name)
    r = _ssh_cmd(cfg, ip,
                  f"sudo tee /etc/tmux.conf > /dev/null << 'FREQEOF'\n{tmux_conf}\nFREQEOF",
                  timeout=10)
    fmt.step_ok("tmux.conf deployed") if r.returncode == 0 else fmt.step_fail("Failed")

    # Step 5: Deploy dev-start/dev-stop scripts
    fmt.step_start("Deploying dev scripts")
    dev_start = _generate_dev_start(tmpl, workspace, specialist_name)
    dev_stop = _generate_dev_stop(tmpl)
    r = _ssh_cmd(cfg, ip,
                  f"cat > {home_dir}/dev-start << 'FREQEOF'\n{dev_start}\nFREQEOF\n"
                  f"cat > {home_dir}/dev-stop << 'FREQEOF'\n{dev_stop}\nFREQEOF\n"
                  f"chmod +x {home_dir}/dev-start {home_dir}/dev-stop",
                  timeout=10)
    fmt.step_ok("dev-start/dev-stop deployed") if r.returncode == 0 else fmt.step_fail("Failed")

    # Step 6: Create mailbox structure
    fmt.step_start("Creating mailbox")
    r = _ssh_cmd(cfg, ip,
                  f"sudo mkdir -p /opt/jarvis-mailbox/{{inbox,outbox,archive}} && "
                  f"sudo chmod -R 777 /opt/jarvis-mailbox",
                  timeout=10)
    fmt.step_ok("Mailbox created") if r.returncode == 0 else fmt.step_fail("Failed")

    # Step 7: Set permissions
    fmt.step_start("Setting permissions")
    r = _ssh_cmd(cfg, ip,
                  f"chmod -R g+w {workspace} && "
                  f"chmod 700 {settings_dir}",
                  timeout=10)
    fmt.step_ok("Permissions set") if r.returncode == 0 else fmt.step_fail("Failed")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}Specialist '{specialist_name}' deployed to {ip}{fmt.C.RESET}")
    fmt.info(f"SSH in and run: bash ~/dev-start")
    fmt.blank()
    fmt.footer()

    logger.info(f"specialist create: {specialist_name} on {ip}", role=role)
    return 0


def _cmd_health(cfg, args) -> int:
    """Check specialist VM health — Claude Code running, tmux, mailbox."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq specialist health <host>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    ip = host.ip if host else target

    fmt.header(f"Specialist Health: {target}")
    fmt.blank()

    checks = {
        "SSH reachable": "echo ok",
        "Claude Code running": "pgrep -f 'claude' >/dev/null 2>&1 && echo running || echo stopped",
        "tmux session": "tmux list-sessions 2>/dev/null | head -3 || echo 'no sessions'",
        "Inbox messages": "ls /opt/jarvis-mailbox/inbox/*.md 2>/dev/null | wc -l",
        "Outbox messages": "ls /opt/jarvis-mailbox/outbox/*.md 2>/dev/null | wc -l",
        "Disk usage": "df -h / | awk 'NR==2 {print $5}'",
        "Uptime": "uptime -p 2>/dev/null || uptime",
        "Last code change": f"find /home/{cfg.ssh_service_account} -name '*.py' -newer /tmp/.freq-marker 2>/dev/null | wc -l; "
                            "touch /tmp/.freq-marker 2>/dev/null",
    }

    for check_name, cmd in checks.items():
        r = _ssh_cmd(cfg, ip, cmd, timeout=10)
        if r.returncode == 0:
            value = r.stdout.strip()
            if value in ("running", "ok") or (value.isdigit() and int(value) >= 0):
                sym = fmt.C.GREEN + fmt.S.TICK + fmt.C.RESET
            elif value == "stopped" or value == "no sessions":
                sym = fmt.C.YELLOW + fmt.S.WARN + fmt.C.RESET
            else:
                sym = fmt.C.GREEN + fmt.S.TICK + fmt.C.RESET
            print(f"    {sym} {fmt.C.GRAY}{check_name:>20}:{fmt.C.RESET}  {value}")
        else:
            print(f"    {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {fmt.C.GRAY}{check_name:>20}:{fmt.C.RESET}  "
                  f"{fmt.C.RED}error{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_status(cfg, args) -> int:
    """Quick status of all known specialist VMs."""
    return _cmd_list(cfg, args)


def _cmd_list(cfg, args) -> int:
    """List specialist VMs from the agent registry."""
    fmt.header("Specialists")
    fmt.blank()

    # Try the agent registry first
    try:
        from freq.jarvis.agent import _load_agents
        agents = _load_agents(cfg)
        if agents:
            fmt.table_header(("NAME", 16), ("ROLE", 10), ("VMID", 6), ("STATUS", 10))
            for name, agent in agents.items():
                fmt.table_row(
                    (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 16),
                    (agent.get("template", "?"), 10),
                    (str(agent.get("vmid", "?")), 6),
                    (agent.get("status", "?"), 10),
                )
            fmt.blank()
            fmt.footer()
            return 0
    except Exception as e:
        logger.warn(f"failed to load agent registry: {e}")

    fmt.line(f"  {fmt.C.DIM}No specialists registered.{fmt.C.RESET}")
    fmt.info("Create one: freq specialist create <host> --role <role>")
    fmt.blank()
    fmt.footer()
    return 0


# --- Generators ---

def _generate_claude_md(name, role, tmpl, ip, svc_account="admin"):
    """Generate CLAUDE.md for a specialist."""
    return f"""# {name} - {tmpl['description']}

> **Role:** {role} | **VM IP:** {ip} | **Created:** {time.strftime('%Y-%m-%d')}

## Identity
This agent is `{name}`. A {role} specialist deployed by FREQ.

## Environment
- VM IP: {ip}
- User: {svc_account}
- Workspace: /home/{svc_account}/{name}
- Mailbox: /opt/jarvis-mailbox/

## Communication
- Check inbox: ls /opt/jarvis-mailbox/inbox/
- Send messages: write to /opt/jarvis-mailbox/outbox/
- Format: YYYY-MM-DD-recipient-subject.md
"""


def _generate_settings(tmpl):
    """Generate Claude Code settings.json."""
    return json.dumps({
        "model": tmpl["model"],
        "effortLevel": "high",
        "permissions": {
            "allow": ["Read", "Glob", "Grep", "Bash(*)"],
            "deny": []
        },
    }, indent=2)


def _generate_tmux_conf(tmpl, name):
    """Generate tmux.conf with role-appropriate colors."""
    color = TMUX_COLORS.get(tmpl["tmux_color"], "colour33")
    return f"""# {name} tmux config — deployed by FREQ
set -g mouse on
set -g history-limit 50000
set -g default-terminal "tmux-256color"
set -g status-style "bg={color},fg=black"
set -g status-left " [{name}] "
set -g status-right " %H:%M "
set -g pane-active-border-style "fg={color}"
"""


def _generate_dev_start(tmpl, workspace, name):
    """Generate dev-start script."""
    session = tmpl["session_name"]
    return f"""#!/bin/bash
# {name} dev session launcher — deployed by FREQ
SESSION="{session}"
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session $SESSION already exists. Attaching..."
    tmux attach -t "$SESSION"
    exit 0
fi
tmux new-session -d -s "$SESSION" -c "{workspace}"
tmux send-keys -t "$SESSION" "cd {workspace} && claude" Enter
tmux attach -t "$SESSION"
"""


def _generate_dev_stop(tmpl):
    """Generate dev-stop script."""
    session = tmpl["session_name"]
    return f"""#!/bin/bash
# {session} session shutdown — deployed by FREQ
SESSION="{session}"
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "No $SESSION session found."
    exit 0
fi
echo "Stopping $SESSION..."
tmux send-keys -t "$SESSION" C-c
sleep 1
tmux send-keys -t "$SESSION" "exit" Enter
sleep 1
tmux kill-session -t "$SESSION" 2>/dev/null
echo "$SESSION stopped."
"""
