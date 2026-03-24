"""Proxmox VE management for FREQ.

Commands: list, vm-overview, vmconfig, create, clone, destroy, resize,
          snapshot, migrate, rescue

All PVE operations go through SSH + qm/pvesh commands on PVE nodes.
No REST API, no tokens — just SSH keys and native Proxmox tools.
"""
import json

from freq.core import fmt
from freq.core import log as logger
from freq.core import validate
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run


def _pve_cmd(cfg: FreqConfig, node_ip: str, command: str, timeout: int = 30) -> tuple:
    """Execute a command on a PVE node via SSH + sudo.

    Returns (stdout, success). This is the foundation — every PVE
    operation goes through here.
    """
    r = ssh_run(
        host=node_ip,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pve",
        use_sudo=True,
    )
    return r.stdout, r.returncode == 0


def _find_reachable_node(cfg: FreqConfig) -> str:
    """Find the first reachable PVE node. Any node can answer cluster queries."""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip, command="pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path, connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=10, htype="pve", use_sudo=True,
        )
        if r.returncode == 0:
            return ip
    return ""


def cmd_list(cfg: FreqConfig, pack, args) -> int:
    """List all VMs across the PVE cluster."""
    fmt.header("VM Inventory")
    fmt.blank()

    if not cfg.pve_nodes:
        fmt.line(f"{fmt.C.YELLOW}No PVE nodes configured.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Find a reachable node
    fmt.step_start("Connecting to PVE cluster")
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.line(f"{fmt.C.GRAY}Configured nodes: {', '.join(cfg.pve_nodes)}{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Check SSH access: ssh {cfg.ssh_service_account}@<node-ip>{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Get cluster VM list
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/resources --type vm --output-format json")
    if not ok or not stdout:
        fmt.step_fail("Failed to query cluster resources")
        fmt.blank()
        fmt.footer()
        return 1

    try:
        vms = json.loads(stdout)
    except json.JSONDecodeError:
        fmt.step_fail("Invalid JSON from PVE API")
        fmt.blank()
        fmt.footer()
        return 1

    # Filter by args
    node_filter = getattr(args, "node", None)
    status_filter = getattr(args, "status", None)

    if node_filter:
        vms = [v for v in vms if v.get("node", "") == node_filter]
    if status_filter:
        vms = [v for v in vms if v.get("status", "") == status_filter.lower()]

    # Sort by node, then VMID
    vms.sort(key=lambda v: (v.get("node", ""), v.get("vmid", 0)))

    fmt.step_ok(f"Found {len(vms)} VMs across cluster")
    fmt.blank()

    if not vms:
        fmt.line(f"{fmt.C.YELLOW}No VMs found.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Table
    fmt.table_header(
        ("VMID", 6),
        ("NAME", 20),
        ("NODE", 8),
        ("STATUS", 10),
        ("CPU", 4),
        ("RAM", 8),
        ("TYPE", 6),
    )

    for v in vms:
        vmid = v.get("vmid", "?")
        name = v.get("name", "—")[:20]
        node = v.get("node", "?")
        status = v.get("status", "?")
        cpus = str(v.get("maxcpu", "?"))
        ram_bytes = v.get("maxmem", 0)
        ram_mb = ram_bytes // (1024 * 1024) if ram_bytes else 0
        ram_str = f"{ram_mb}MB" if ram_mb else "?"
        vm_type = v.get("type", "?")

        # Color status
        if status == "running":
            status_badge = fmt.badge("running")
        elif status == "stopped":
            status_badge = fmt.badge("down")
        else:
            status_badge = fmt.badge(status)

        # Protected VMID indicator
        protected = ""
        if validate.is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges):
            protected = f" {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}"

        fmt.table_row(
            (f"{vmid}{protected}", 6),
            (name, 20),
            (node, 8),
            (status_badge, 10),
            (cpus, 4),
            (ram_str, 8),
            (vm_type, 6),
        )

    fmt.blank()

    # Summary
    running = sum(1 for v in vms if v.get("status") == "running")
    stopped = sum(1 for v in vms if v.get("status") == "stopped")
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{running}{fmt.C.RESET} running  "
        f"{fmt.C.RED}{stopped}{fmt.C.RESET} stopped  "
        f"({len(vms)} total)"
    )
    fmt.blank()
    fmt.footer()

    return 0


def cmd_vm_overview(cfg: FreqConfig, pack, args) -> int:
    """VM inventory across cluster — alias for list with extra detail."""
    return cmd_list(cfg, pack, args)


def cmd_vmconfig(cfg: FreqConfig, pack, args) -> int:
    """View VM configuration."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq vmconfig <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    fmt.header(f"VM Config: {vmid}")
    fmt.blank()

    # Find which node has this VM
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    # Get VM config
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
    if not ok:
        fmt.line(f"{fmt.C.RED}VM {vmid} not found or not accessible.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Parse and display config
    for line in stdout.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            fmt.line(f"  {fmt.C.CYAN}{key:>20}{fmt.C.RESET}: {value}")
        elif line.strip():
            fmt.line(f"  {line}")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_snapshot(cfg: FreqConfig, pack, args) -> int:
    """Create a VM snapshot."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq snapshot <vmid> [--name <snap_name>]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    snap_name = getattr(args, "name", None) or f"freq-snap-{vmid}"

    fmt.header(f"Snapshot VM {vmid}")
    fmt.blank()

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.step_start(f"Creating snapshot '{snap_name}' for VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm snapshot {vmid} {snap_name} --description 'Created by FREQ'", timeout=120)

    if ok:
        fmt.step_ok(f"Snapshot '{snap_name}' created for VM {vmid}")
    else:
        fmt.step_fail(f"Snapshot failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1
