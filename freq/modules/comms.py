"""Inter-VM communication for FREQ.

Commands: comms setup, comms send, comms check

Simple file-based mailbox system between VMs.
Messages are stored in /opt/freq-comms/ on a designated relay host.
"""
import base64
import json
import os
import time

from freq.core import fmt
from freq.core import resolve
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run


COMMS_DIR = "/opt/freq-comms"
INBOX = f"{COMMS_DIR}/inbox"
OUTBOX = f"{COMMS_DIR}/outbox"


def cmd_comms(cfg: FreqConfig, pack, args) -> int:
    """Inter-VM comms management."""
    action = getattr(args, "action", None) or "check"

    routes = {
        "setup": _cmd_setup,
        "send": _cmd_send,
        "check": _cmd_check,
        "read": _cmd_read,
        "list": _cmd_check,
    }

    handler = routes.get(action)
    if handler:
        return handler(cfg, args)

    fmt.error(f"Unknown comms action: {action}")
    fmt.info("Available: setup, send, check, read")
    return 1


def _get_relay_host(cfg):
    """Find the comms relay host (first PVE node in fleet)."""
    pve_hosts = resolve.by_type(cfg.hosts, "pve")
    return pve_hosts[0] if pve_hosts else None


def _cmd_setup(cfg, args) -> int:
    """Set up comms directory on relay host."""
    relay = _get_relay_host(cfg)
    if not relay:
        fmt.error("No relay host available.")
        return 1

    fmt.header("Comms Setup")
    fmt.blank()

    fmt.step_start(f"Creating comms directory on {relay.label}")
    r = ssh_run(
        host=relay.ip,
        command=f"sudo mkdir -p {INBOX} {OUTBOX} && sudo chmod -R 777 {COMMS_DIR}",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=10, htype=relay.htype, use_sudo=False,
    )
    if r.returncode == 0:
        fmt.step_ok(f"Comms directory ready at {relay.label}:{COMMS_DIR}")
    else:
        fmt.step_fail(f"Setup failed: {r.stderr}")

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


def _cmd_send(cfg, args) -> int:
    """Send a message to another VM."""
    target = getattr(args, "target", None)
    message = getattr(args, "message", None)

    if not message:
        fmt.error("Usage: freq comms send --target <host> --message '<text>'")
        return 1

    relay = _get_relay_host(cfg)
    if not relay:
        fmt.error("No relay host available.")
        return 1

    sender = os.environ.get("HOSTNAME", "freq")
    timestamp = time.strftime("%Y-%m-%d-%H%M%S")
    filename = f"{timestamp}-{sender}.json"

    msg_data = json.dumps({
        "from": sender,
        "to": target or "all",
        "timestamp": timestamp,
        "message": message,
    })

    fmt.step_start(f"Sending message via {relay.label}")
    r = ssh_run(
        host=relay.ip,
        command=f"printf '%s' {base64.b64encode(msg_data.encode()).decode()} | base64 -d > {INBOX}/{filename}",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=10, htype=relay.htype, use_sudo=False,
    )

    if r.returncode == 0:
        fmt.step_ok("Message sent")
        logger.info(f"comms send: {target or 'all'}", message=message[:50])
    else:
        fmt.step_fail(f"Send failed: {r.stderr}")

    return 0 if r.returncode == 0 else 1


def _cmd_check(cfg, args) -> int:
    """Check for messages in the inbox."""
    relay = _get_relay_host(cfg)
    if not relay:
        fmt.error("No relay host available.")
        return 1

    fmt.header("Comms Inbox")
    fmt.blank()

    r = ssh_run(
        host=relay.ip,
        command=f"ls -1t {INBOX}/*.json 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=10, htype=relay.htype, use_sudo=False,
    )

    if r.returncode != 0 or not r.stdout.strip():
        fmt.line(f"  {fmt.C.DIM}No messages.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    files = r.stdout.strip().split("\n")
    fmt.line(f"  {fmt.C.BOLD}{len(files)} message(s){fmt.C.RESET}")
    fmt.blank()

    for f_path in files[:20]:
        fname = f_path.split("/")[-1]
        r2 = ssh_run(
            host=relay.ip, command=f"cat {f_path}",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=5, htype=relay.htype, use_sudo=False,
        )
        if r2.returncode == 0:
            try:
                msg = json.loads(r2.stdout)
                sender = msg.get("from", "?")
                ts = msg.get("timestamp", "?")
                text = msg.get("message", "")[:60]
                fmt.line(f"  {fmt.C.CYAN}{ts}{fmt.C.RESET} "
                         f"{fmt.C.BOLD}{sender}{fmt.C.RESET}: {text}")
            except json.JSONDecodeError:
                fmt.line(f"  {fname}: {fmt.C.DIM}(invalid JSON){fmt.C.RESET}")
        else:
            fmt.line(f"  {fname}: {fmt.C.DIM}(unreadable){fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_read(cfg, args) -> int:
    """Read a specific message."""
    return _cmd_check(cfg, args)
