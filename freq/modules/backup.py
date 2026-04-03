"""VM backup and config export for FREQ.

Domain: freq dr <backup-list|backup-create|backup-export|backup-status|backup-prune>

Lists PVE backups and snapshots, creates new backups with retention awareness,
exports FREQ config state, and prunes expired backup artifacts. One command
to see every backup across every node.

Replaces: Veeam Backup ($$$), manual vzdump scripts, PVE GUI backup tab

Architecture:
    - PVE operations via SSH to cluster nodes (pvesh/vzdump)
    - Config export serializes freq.toml + hosts.conf to portable archive
    - Reuses freq/modules/pve.py helpers for node discovery

Design decisions:
    - Backup list aggregates across all PVE nodes, not just one.
      Single-node backup views are what the PVE GUI already does.
"""

import os
import time
import json

from freq.core import fmt
from freq.core.config import FreqConfig

# Backup timeouts
BACKUP_PRUNE_TIMEOUT = 120


def cmd_backup(cfg: FreqConfig, pack, args) -> int:
    """Backup management — VM snapshots + config export."""
    action = getattr(args, "action", None) or "list"

    if action == "list":
        return _backup_list(cfg)
    elif action == "create":
        return _backup_create(cfg, args)
    elif action == "export":
        return _backup_export(cfg)
    elif action == "status":
        return _backup_status(cfg)
    elif action == "prune":
        return _backup_prune(cfg, args)
    else:
        fmt.error(f"Unknown action: {action}")
        fmt.info("Usage: freq backup [list|create|export|status|prune]")
        return 1


def _backup_list(cfg: FreqConfig) -> int:
    """List available backups and snapshots."""
    fmt.header("Backups")
    fmt.blank()

    from freq.modules.pve import _find_reachable_node, _pve_cmd

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.line(f"{fmt.C.YELLOW}No PVE node reachable.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # List VM snapshots
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/resources --type vm --output-format json")
    if ok and stdout:
        try:
            vms = json.loads(stdout)
            if vms:
                fmt.line(f"{fmt.C.BOLD}VM Snapshots:{fmt.C.RESET}")
                fmt.blank()
                for vm in vms:
                    vmid = vm.get("vmid", "?")
                    name = vm.get("name", "?")
                    snap_out, snap_ok = _pve_cmd(cfg, node_ip, f"qm listsnapshot {vmid} 2>/dev/null")
                    if snap_ok and snap_out.strip():
                        snap_lines = [
                            l.strip() for l in snap_out.split("\n") if l.strip() and "current" not in l.lower()
                        ]
                        if snap_lines:
                            fmt.line(f"  {fmt.C.CYAN}VM {vmid}{fmt.C.RESET} ({name}): {len(snap_lines)} snapshot(s)")
                            for line in snap_lines[:3]:
                                print(f"    {fmt.C.DIM}{line}{fmt.C.RESET}")
        except json.JSONDecodeError:
            pass

    # Check for config exports
    export_dir = os.path.join(cfg.data_dir, "backups")
    if os.path.isdir(export_dir):
        exports = sorted(os.listdir(export_dir), reverse=True)
        if exports:
            fmt.blank()
            fmt.line(f"{fmt.C.BOLD}Config Exports:{fmt.C.RESET}")
            fmt.blank()
            for f in exports[:5]:
                fmt.line(f"  {fmt.C.DIM}{f}{fmt.C.RESET}")
    else:
        fmt.blank()
        fmt.line(f"{fmt.C.GRAY}No config exports found.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _backup_create(cfg: FreqConfig, args) -> int:
    """Create a snapshot of a VM."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq backup create <vmid>")
        return 1

    from freq.modules.pve import cmd_snapshot

    return cmd_snapshot(cfg, None, args)


def _backup_status(cfg: FreqConfig) -> int:
    """Show backup retention status across PVE cluster."""
    fmt.header("Backup Status")
    fmt.blank()

    from freq.modules.pve import _find_reachable_node, _pve_cmd

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.error("No PVE node reachable.")
        return 1

    # Check vzdump backup storage
    fmt.line(f"{fmt.C.PURPLE_BOLD}PVE Backup Storage{fmt.C.RESET}")
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/backup --output-format json 2>/dev/null")
    if ok and stdout:
        try:
            jobs = json.loads(stdout)
            if jobs:
                fmt.blank()
                fmt.table_header(("ID", 6), ("SCHEDULE", 14), ("VMs", 20), ("STORAGE", 12))
                for job in jobs:
                    fmt.table_row(
                        (str(job.get("id", "?")), 6),
                        (job.get("schedule", "?"), 14),
                        (job.get("vmid", "all")[:20], 20),
                        (job.get("storage", "?"), 12),
                    )
            else:
                fmt.line(f"  {fmt.C.YELLOW}No backup jobs configured.{fmt.C.RESET}")
        except json.JSONDecodeError:
            fmt.line(f"  {fmt.C.DIM}Cannot parse backup config.{fmt.C.RESET}")
    fmt.blank()

    # List backup files on storage
    stdout, ok = _pve_cmd(cfg, node_ip, "find /var/lib/vz/dump/ -name '*.vma*' -o -name '*.tar*' 2>/dev/null | wc -l")
    if ok:
        count = stdout.strip()
        fmt.line(f"  {fmt.C.BOLD}Backup files on local storage:{fmt.C.RESET} {count}")

    # Show disk usage of backup location
    stdout, ok = _pve_cmd(cfg, node_ip, "du -sh /var/lib/vz/dump/ 2>/dev/null | awk '{print $1}'")
    if ok:
        size = stdout.strip()
        fmt.line(f"  {fmt.C.BOLD}Backup storage used:{fmt.C.RESET} {size}")

    fmt.blank()
    fmt.info("Recommended retention: keep-daily=7, keep-weekly=4, keep-monthly=3")
    fmt.blank()
    fmt.footer()
    return 0


def _backup_prune(cfg: FreqConfig, args) -> int:
    """Prune old backups based on retention policy."""
    fmt.header("Backup Prune")
    fmt.blank()

    from freq.modules.pve import _find_reachable_node, _pve_cmd

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.error("No PVE node reachable.")
        return 1

    # List old backups (>30 days)
    fmt.step_start("Finding old backups (>30 days)")
    stdout, ok = _pve_cmd(
        cfg, node_ip, "find /var/lib/vz/dump/ \\( -name '*.vma*' -o -name '*.tar*' \\) -mtime +30 2>/dev/null"
    )
    if not ok or not stdout.strip():
        fmt.step_ok("No old backups to prune")
        fmt.blank()
        fmt.footer()
        return 0

    old_files = [f.strip() for f in stdout.strip().split("\n") if f.strip()]
    fmt.step_ok(f"Found {len(old_files)} old backup(s)")
    fmt.blank()

    for f in old_files[:10]:
        fmt.line(f"  {fmt.C.DIM}{f}{fmt.C.RESET}")
    if len(old_files) > 10:
        fmt.line(f"  {fmt.C.DIM}... and {len(old_files) - 10} more{fmt.C.RESET}")

    fmt.blank()
    if not getattr(args, "yes", False):
        try:
            confirm = (
                input(f"  {fmt.C.YELLOW}Delete {len(old_files)} old backup(s)? [y/N]:{fmt.C.RESET} ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    fmt.step_start(f"Pruning {len(old_files)} old backups")
    stdout, ok = _pve_cmd(
        cfg,
        node_ip,
        "find /var/lib/vz/dump/ \\( -name '*.vma*' -o -name '*.tar*' \\) -mtime +30 -delete 2>&1",
        timeout=BACKUP_PRUNE_TIMEOUT,
    )
    if ok:
        fmt.step_ok(f"Pruned {len(old_files)} old backups")
    else:
        fmt.step_fail(f"Prune failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0


def _backup_export(cfg: FreqConfig) -> int:
    """Export FREQ configuration to a backup file."""
    fmt.header("Config Export")
    fmt.blank()

    export_dir = os.path.join(cfg.data_dir, "backups")
    os.makedirs(export_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    export_file = os.path.join(export_dir, f"freq-config-{timestamp}.json")

    # Gather all config
    export_data = {
        "timestamp": timestamp,
        "version": cfg.version,
        "hosts": [{"ip": h.ip, "label": h.label, "htype": h.htype, "groups": h.groups} for h in cfg.hosts],
        "vlans": [{"id": v.id, "name": v.name, "subnet": v.subnet} for v in cfg.vlans],
        "pve_nodes": cfg.pve_nodes,
        "cluster_name": cfg.cluster_name,
    }

    fmt.step_start("Exporting configuration")
    with open(export_file, "w") as f:
        json.dump(export_data, f, indent=2)
    fmt.step_ok(f"Saved to {export_file}")

    fmt.blank()
    fmt.line(
        f"  {fmt.C.GRAY}Exported: {len(export_data['hosts'])} hosts, {len(export_data['vlans'])} VLANs{fmt.C.RESET}"
    )
    fmt.blank()
    fmt.footer()
    return 0
