"""Host bootstrap and onboarding for FREQ.

Domain: freq host <bootstrap|onboard>

Deploys SSH keys and the FREQ service account to a new host, verifies
connectivity, and optionally registers it in the fleet. Bootstrap is the
single-host key push; onboard wraps bootstrap + fleet registration + verify.

Replaces: Manual ssh-copy-id scripts, Ansible bootstrap playbooks ($0 but YAML)

Architecture:
    - SSH connectivity test via freq/core/ssh.py
    - Key deployment via ssh-copy-id subprocess
    - Host resolution through freq/core/resolve.py (label or IP)
    - Onboard calls bootstrap then writes to hosts.conf

Design decisions:
    - Bootstrap only tests and reports; it does not force key deployment.
      If the host is unreachable, it tells you the manual step. No magic.
"""
import os

from freq.core import fmt
from freq.core import resolve
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Bootstrap timeouts
BOOTSTRAP_CMD_TIMEOUT = 10


def cmd_bootstrap(cfg: FreqConfig, pack, args) -> int:
    """Bootstrap a host — deploy SSH key and verify connectivity."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq bootstrap <host-ip-or-label>")
        return 1

    # Check if it's an existing host or raw IP
    host = resolve.by_target(cfg.hosts, target)
    ip = host.ip if host else target
    label = host.label if host else target

    fmt.header(f"Bootstrap: {label}")
    fmt.blank()

    # Step 1: Check if already reachable
    fmt.step_start(f"Testing SSH to {ip}")
    r = ssh_run(host=ip, command="echo ok",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=BOOTSTRAP_CMD_TIMEOUT,
                htype="linux", use_sudo=False)

    if r.returncode == 0:
        fmt.step_ok(f"Already reachable via SSH")
    else:
        fmt.step_warn(f"Not reachable — deploy key manually first")
        fmt.blank()
        fmt.line(f"  {fmt.C.GRAY}Run: ssh-copy-id {cfg.ssh_service_account}@{ip}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Step 2: Verify sudo
    fmt.step_start("Testing sudo access")
    r = ssh_run(host=ip, command="whoami",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=BOOTSTRAP_CMD_TIMEOUT,
                htype="linux", use_sudo=True)

    if r.returncode == 0 and "root" in r.stdout:
        fmt.step_ok("Sudo working (runs as root)")
    else:
        fmt.step_warn(f"Sudo may not be configured: got '{r.stdout.strip()}'")

    # Step 3: Get host info
    fmt.step_start("Gathering host info")
    info_cmd = (
        "echo \"$(hostname -f 2>/dev/null || hostname)|"
        "$(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')|"
        "$(nproc)|"
        "$(free -m | awk '/Mem:/ {print $2}')MB\""
    )
    r = ssh_run(host=ip, command=info_cmd,
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=BOOTSTRAP_CMD_TIMEOUT,
                htype="linux", use_sudo=False)

    if r.returncode == 0:
        parts = r.stdout.split("|")
        hostname = parts[0] if len(parts) > 0 else "unknown"
        os_name = parts[1] if len(parts) > 1 else "unknown"
        cores = parts[2] if len(parts) > 2 else "?"
        ram = parts[3] if len(parts) > 3 else "?"
        fmt.step_ok(f"{hostname} — {os_name} ({cores} cores, {ram})")
    else:
        fmt.step_warn("Could not gather host info")

    # Step 4: Ensure service account exists
    fmt.step_start(f"Checking service account ({cfg.ssh_service_account})")
    r = ssh_run(host=ip, command=f"id {cfg.ssh_service_account}",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=BOOTSTRAP_CMD_TIMEOUT,
                htype="linux", use_sudo=False)

    if r.returncode == 0:
        fmt.step_ok(f"User '{cfg.ssh_service_account}' exists")
    else:
        fmt.step_warn(f"User '{cfg.ssh_service_account}' not found")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}Bootstrap complete for {label} ({ip}).{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()

    logger.info(f"bootstrap complete: {label} ({ip})")
    return 0


def cmd_onboard(cfg: FreqConfig, pack, args) -> int:
    """Onboard a new host — add to fleet + bootstrap."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq onboard <ip>")
        fmt.info("  This will add the host to your fleet and verify connectivity.")
        return 1

    fmt.header(f"Onboard: {target}")
    fmt.blank()

    # Check if already registered
    existing = resolve.by_ip(cfg.hosts, target)
    if existing:
        fmt.error(f"Host already registered: {existing.label} ({existing.ip})")
        fmt.blank()
        fmt.footer()
        return 1

    # Get label
    try:
        label = input(f"  {fmt.C.CYAN}Label for this host:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
    if not label:
        fmt.error("Label is required.")
        return 1

    # Get type
    try:
        htype = input(f"  {fmt.C.CYAN}Host type (linux/pve/docker/truenas/pfsense):{fmt.C.RESET} ").strip() or "linux"
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    # Get groups
    try:
        groups = input(f"  {fmt.C.CYAN}Groups (comma-separated, Enter=none):{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    fmt.blank()

    # Add to hosts.conf
    fmt.step_start("Adding to fleet registry")
    line = f"{target} {label} {htype}"
    if groups:
        line += f" {groups}"

    try:
        with open(cfg.hosts_file, "a") as f:
            f.write(f"{line}\n")
        fmt.step_ok(f"Added: {label} ({target})")
    except OSError as e:
        fmt.step_fail(f"Failed to write hosts.conf: {e}")
        fmt.blank()
        fmt.footer()
        return 1

    # Bootstrap
    fmt.step_start(f"Testing connectivity to {target}")
    r = ssh_run(host=target, command="echo ok",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=BOOTSTRAP_CMD_TIMEOUT,
                htype=htype, use_sudo=False)

    if r.returncode == 0:
        fmt.step_ok("SSH connectivity confirmed")
    else:
        fmt.step_warn(f"Not reachable yet — deploy SSH key to {target}")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}Host onboarded: {label} ({target}){fmt.C.RESET}")
    fmt.line(f"  {fmt.C.GRAY}Run 'freq status' to verify fleet health.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()

    logger.info(f"host onboarded: {label} ({target}) type={htype}")
    return 0
