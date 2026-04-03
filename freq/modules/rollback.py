"""One-command VM rollback for FREQ.

Domain: freq vm <rollback>

One command: freq vm rollback <vmid>. Finds the latest snapshot for a VM
and restores it. No fumbling with snapshot names, no PVE GUI navigation.
For when things go sideways and you need to undo. Fast.

Replaces: PVE GUI snapshot restore (slow, multi-click), manual qm rollback

Architecture:
    - Snapshot listing via pvesh on reachable PVE node
    - Selects most recent freq-created snapshot (freq-snap-* naming)
    - Rollback via qm rollback with extended timeout (180s)
    - PVE node discovery shared with freq/modules/pve.py pattern

Design decisions:
    - Auto-selects latest snapshot, no user input needed. In an emergency,
      fewer decisions means faster recovery. Override with --snapshot flag.
"""
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Timeouts
PVE_CMD_TIMEOUT = 30
PVE_ROLLBACK_TIMEOUT = 180
PVE_QUICK_TIMEOUT = 10


def _find_reachable_node(cfg: FreqConfig) -> str:
    """Find the first reachable PVE node."""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip, command="pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path, connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=PVE_QUICK_TIMEOUT, htype="pve", use_sudo=True,
        )
        if r.returncode == 0:
            return ip
    return ""


def _pve_cmd(cfg: FreqConfig, node_ip: str, command: str, timeout: int = PVE_CMD_TIMEOUT) -> tuple:
    """Execute a command on a PVE node via SSH + sudo."""
    r = ssh_run(
        host=node_ip, command=command,
        key_path=cfg.ssh_key_path, connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout, htype="pve", use_sudo=True,
    )
    return r.stdout, r.returncode == 0


def _get_snapshots(cfg: FreqConfig, node_ip: str, vmid: int) -> list:
    """Get list of snapshots for a VM, sorted by name (most recent freq-snap last)."""
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm listsnapshot {vmid}", timeout=PVE_CMD_TIMEOUT)
    if not ok:
        return []

    snaps = []
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts:
            name = parts[0].replace("`-", "").replace("->", "").strip()
            if name and name != "current":
                snaps.append(name)

    return snaps


def _get_vm_status(cfg: FreqConfig, node_ip: str, vmid: int) -> str:
    """Get current VM status (running/stopped/etc)."""
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm status {vmid}", timeout=PVE_QUICK_TIMEOUT)
    if ok and stdout.strip():
        # Output: "status: running" or "status: stopped"
        parts = stdout.strip().split(":", 1)
        if len(parts) == 2:
            return parts[1].strip()
    return "unknown"


def cmd_rollback(cfg: FreqConfig, pack, args) -> int:
    """Roll back a VM to its most recent snapshot."""
    target = getattr(args, "target", None)
    snap_name = getattr(args, "name", None)

    if not target:
        fmt.error("Usage: freq rollback <vmid> [--name <snapshot>]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    fmt.header(f"Rollback VM {vmid}")
    fmt.blank()

    # Find a PVE node
    fmt.step_start("Connecting to PVE cluster")
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok(f"Connected to {node_ip}")

    # Get VM status
    status = _get_vm_status(cfg, node_ip, vmid)
    fmt.line(f"  VM {vmid} status: {status}")

    # Get snapshots
    fmt.step_start(f"Finding snapshots for VM {vmid}")
    snaps = _get_snapshots(cfg, node_ip, vmid)

    if not snaps:
        fmt.step_fail(f"No snapshots found for VM {vmid} — nothing to roll back to")
        fmt.blank()
        fmt.footer()
        return 1

    # Pick snapshot: explicit name or latest
    if snap_name:
        if snap_name not in snaps:
            fmt.step_fail(f"Snapshot '{snap_name}' not found. Available: {', '.join(snaps)}")
            fmt.blank()
            fmt.footer()
            return 1
    else:
        snap_name = snaps[-1]  # Most recent

    fmt.step_ok(f"Using snapshot: {snap_name}")
    fmt.line(f"  Available snapshots: {', '.join(snaps)}")
    fmt.blank()

    # Confirm unless --yes
    if not getattr(args, "yes", False):
        fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} This will revert VM {vmid} to snapshot '{snap_name}'.{fmt.C.RESET}")
        if status == "running":
            fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} The VM is currently running and will be stopped.{fmt.C.RESET}")
        fmt.blank()
        try:
            confirm = input(f"  {fmt.C.YELLOW}Proceed? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Rollback cancelled.")
            return 0

    # Stop VM if running
    if status == "running":
        fmt.step_start(f"Stopping VM {vmid}")
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm stop {vmid}", timeout=PVE_CMD_TIMEOUT)
        if not ok:
            fmt.step_fail(f"Failed to stop VM: {stdout}")
            fmt.blank()
            fmt.footer()
            return 1
        fmt.step_ok(f"VM {vmid} stopped")

        # Wait for stop
        for _ in range(30):
            time.sleep(1)
            s = _get_vm_status(cfg, node_ip, vmid)
            if s == "stopped":
                break

    # Perform rollback
    fmt.step_start(f"Rolling back to '{snap_name}'")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm rollback {vmid} {snap_name}",
                          timeout=PVE_ROLLBACK_TIMEOUT)

    if not ok:
        fmt.step_fail(f"Rollback failed: {stdout}")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.step_ok(f"VM {vmid} rolled back to '{snap_name}'")

    # Start VM back up
    start_after = getattr(args, "start", True)
    if start_after:
        fmt.step_start(f"Starting VM {vmid}")
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm start {vmid}", timeout=PVE_CMD_TIMEOUT)
        if ok:
            fmt.step_ok(f"VM {vmid} is running")
        else:
            fmt.step_fail(f"Failed to start VM: {stdout}")
            fmt.line(f"  {fmt.C.DIM}VM was rolled back successfully but needs manual start.{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} Rollback complete.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()

    logger.info(f"rollback vm={vmid} snapshot={snap_name}")
    return 0
