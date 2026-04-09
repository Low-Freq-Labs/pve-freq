"""Disaster recovery orchestration for FREQ.

Domain: freq dr <action>
What: Backup management, replication monitoring, SLA tracking with RPO/RTO
      targets, DR runbooks, failover orchestration. Extends existing
      backup.py, backup_policy.py, rollback.py, and sla.py.
Replaces: Manual backup verification, spreadsheet RPO tracking, no DR testing
Architecture:
    - PVE API for backup/snapshot/replication operations
    - SLA targets stored in conf/dr/sla-targets.json
    - Runbooks stored in conf/dr/runbooks/ as JSON
    - Backup verification via PVE vzdump + instant restore
Design decisions:
    - SLA targets are per-VM. Each VM gets RPO, RTO, tier, and priority.
    - Runbooks are ordered step lists — not scripts. Human-readable.
    - DR testing is non-destructive — tabletop and read-only verification.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Data Storage
# ---------------------------------------------------------------------------

DR_DIR = "dr"


def _dr_dir(cfg):
    """Return DR data directory."""
    path = os.path.join(cfg.conf_dir, DR_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_sla_targets(cfg):
    """Load SLA targets per VM."""
    filepath = os.path.join(_dr_dir(cfg), "sla-targets.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return {"targets": []}


def _save_sla_targets(cfg, data):
    """Save SLA targets."""
    filepath = os.path.join(_dr_dir(cfg), "sla-targets.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _runbooks_dir(cfg):
    """Return runbooks directory."""
    path = os.path.join(_dr_dir(cfg), "runbooks")
    os.makedirs(path, exist_ok=True)
    return path


def _load_runbook(cfg, name):
    """Load a runbook by name."""
    filepath = os.path.join(_runbooks_dir(cfg), f"{name}.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return None


def _save_runbook(cfg, name, data):
    """Save a runbook."""
    filepath = os.path.join(_runbooks_dir(cfg), f"{name}.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Commands — Backup Management
# ---------------------------------------------------------------------------


def cmd_dr_backup_list(cfg: FreqConfig, pack, args) -> int:
    """List recent backups across PVE cluster."""
    fmt.header("Backup Inventory", breadcrumb="FREQ > DR > Backup")
    fmt.blank()

    from freq.modules.pve import _find_reachable_node, _pve_api_get

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.warn("Cannot reach any PVE node")
        fmt.footer()
        return 1

    # Get backup storage
    storages = _pve_api_get(cfg, node_ip, "/api2/json/storage")
    backup_storages = []
    if storages:
        for s in storages.get("data", []):
            content = s.get("content", "")
            if "backup" in content:
                backup_storages.append(s.get("storage", ""))

    if not backup_storages:
        fmt.warn("No backup storage configured in PVE")
        fmt.footer()
        return 1

    # List backups from each storage
    total = 0
    for storage in backup_storages:
        fmt.line(f"{fmt.C.BOLD}Storage: {storage}{fmt.C.RESET}")
        for node in cfg.pve_nodes if hasattr(cfg, "pve_nodes") and cfg.pve_nodes else []:
            content = _pve_api_get(cfg, node_ip, f"/api2/json/nodes/{node}/storage/{storage}/content")
            if content:
                backups = [c for c in content.get("data", []) if c.get("content") == "backup"]
                for b in sorted(backups, key=lambda x: x.get("ctime", 0), reverse=True)[:10]:
                    vmid = b.get("vmid", "?")
                    size = b.get("size", 0)
                    size_str = f"{size // (1024**3)}G" if size > 0 else "?"
                    ctime = time.strftime("%Y-%m-%d %H:%M", time.localtime(b.get("ctime", 0)))
                    fmt.line(f"  VM {vmid:<6} {size_str:<8} {ctime}")
                    total += 1
        fmt.blank()

    if total == 0:
        fmt.info("No backups found (PVE API may require auth)")

    fmt.info(f"{total} backup(s) found")
    fmt.footer()
    return 0


def cmd_dr_backup_verify(cfg: FreqConfig, pack, args) -> int:
    """Verify backup integrity — check all VMs have recent backups against SLA."""
    fmt.header("Backup Verification", breadcrumb="FREQ > DR > Backup")
    fmt.blank()

    from freq.modules.pve import _find_reachable_node, _pve_cmd

    # Check ALL reachable nodes — backups can live on any node or shared storage
    reachable_nodes = []
    for ip in cfg.pve_nodes:
        r = _pve_cmd(cfg, ip, "echo OK", timeout=5)
        if r[1]:
            reachable_nodes.append(ip)

    if not reachable_nodes:
        fmt.step_fail("Cannot reach any PVE node — verification impossible")
        fmt.footer()
        return 1

    fmt.step_ok(f"{len(reachable_nodes)}/{len(cfg.pve_nodes)} PVE nodes reachable")

    sla_data = _load_sla_targets(cfg)
    targets = sla_data.get("targets", [])

    if not targets:
        fmt.warn("No SLA targets defined — checking all VMs for any recent backup")
        fmt.info("Set targets: freq dr sla set <vmid> --rpo 24 --rto 4")
        fmt.blank()

    # Query backup inventory from ALL reachable nodes
    # Covers local storage, shared storage, and different node-local dumps
    cmd = (
        "for d in /var/lib/vz/dump /mnt/*/dump /mnt/pbs-*; do "
        '  [ -d "$d" ] || continue; '
        '  for f in "$d"/vzdump-qemu-*.vma* "$d"/vzdump-lxc-*.tar*; do '
        '    [ -f "$f" ] || continue; '
        '    base=$(basename "$f"); '
        "    vmid=$(echo \"$base\" | grep -oP '(?<=vzdump-(qemu|lxc)-)\\d+'); "
        "    epoch=$(stat -c%Y \"$f\" 2>/dev/null || echo 0); "
        '    echo "$vmid|$epoch"; '
        "  done; "
        "done 2>/dev/null | sort -t'|' -k1,1n -k2,2rn"
    )

    backup_ages = {}
    nodes_queried = 0
    nodes_failed = []
    for node_ip in reachable_nodes:
        r = _pve_cmd(cfg, node_ip, cmd, timeout=30)
        if r[1] and r[0]:
            nodes_queried += 1
            for line in r[0].strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 2 and parts[0].strip().isdigit():
                    vid = int(parts[0].strip())
                    try:
                        epoch = int(parts[1].strip())
                    except ValueError:
                        epoch = 0
                    if vid not in backup_ages or epoch > backup_ages[vid]:
                        backup_ages[vid] = epoch
        elif not r[1]:
            nodes_failed.append(node_ip)

    if nodes_queried == 0:
        fmt.step_fail("Could not list backups from any node")
        fmt.footer()
        return 1

    if nodes_failed:
        fmt.step_warn(f"Backup query failed on: {', '.join(nodes_failed)}")

    now = time.time()
    pass_count = 0
    fail_count = 0
    unknown_count = 0

    # If SLA targets exist, verify against RPO
    check_list = targets if targets else [{"vmid": vid, "rpo_hours": 24, "name": f"VM {vid}"} for vid in sorted(backup_ages.keys())]

    fmt.table_header(("STATUS", 8), ("VM", 20), ("VMID", 6), ("LAST BACKUP", 16), ("AGE", 10), ("RPO", 6))
    for t in check_list:
        vmid = t.get("vmid", 0)
        rpo_hours = t.get("rpo_hours", 24)
        name = t.get("name", f"VM {vmid}")

        if vmid not in backup_ages:
            fmt.table_row(
                (f"{fmt.C.RED}FAIL{fmt.C.RESET}", 8),
                (name[:20], 20),
                (str(vmid), 6),
                ("NONE", 16),
                ("—", 10),
                (f"{rpo_hours}h", 6),
            )
            fail_count += 1
            continue

        age_seconds = now - backup_ages[vmid]
        age_hours = age_seconds / 3600
        age_str = f"{age_hours:.1f}h" if age_hours < 48 else f"{age_hours / 24:.1f}d"
        backup_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(backup_ages[vmid]))

        if age_hours <= rpo_hours:
            status = f"{fmt.C.GREEN}PASS{fmt.C.RESET}"
            pass_count += 1
        else:
            status = f"{fmt.C.RED}FAIL{fmt.C.RESET}"
            fail_count += 1

        fmt.table_row(
            (status, 8),
            (name[:20], 20),
            (str(vmid), 6),
            (backup_time, 16),
            (age_str, 10),
            (f"{rpo_hours}h", 6),
        )

    fmt.blank()
    summary = f"  {fmt.C.GREEN}{pass_count} pass{fmt.C.RESET}"
    if fail_count:
        summary += f", {fmt.C.RED}{fail_count} fail{fmt.C.RESET}"
    if unknown_count:
        summary += f", {fmt.C.YELLOW}{unknown_count} unknown{fmt.C.RESET}"
    fmt.line(summary)

    fmt.blank()
    fmt.footer()
    return 1 if fail_count else 0


# ---------------------------------------------------------------------------
# Commands — SLA Management
# ---------------------------------------------------------------------------


def cmd_dr_sla_list(cfg: FreqConfig, pack, args) -> int:
    """List SLA targets (RPO/RTO) per VM."""
    data = _load_sla_targets(cfg)
    targets = data.get("targets", [])

    fmt.header("DR SLA Targets", breadcrumb="FREQ > DR > SLA")
    fmt.blank()

    if not targets:
        fmt.info("No SLA targets defined")
        fmt.info('Set: freq dr sla set <vmid> --rpo 24 --rto 4 --name "VM Name"')
        fmt.footer()
        return 0

    fmt.table_header(("VMID", 6), ("Name", 20), ("RPO", 8), ("RTO", 8), ("Tier", 8), ("Priority", 8))
    for t in sorted(targets, key=lambda x: x.get("priority", 99)):
        fmt.table_row(
            (str(t.get("vmid", "?")), 6),
            (t.get("name", ""), 20),
            (f"{t.get('rpo_hours', '?')}h", 8),
            (f"{t.get('rto_hours', '?')}h", 8),
            (t.get("tier", "—"), 8),
            (str(t.get("priority", "—")), 8),
        )

    fmt.blank()
    fmt.info(f"{len(targets)} target(s)")
    fmt.footer()
    return 0


def cmd_dr_sla_set(cfg: FreqConfig, pack, args) -> int:
    """Set SLA targets for a VM."""
    vmid = getattr(args, "vmid", None)
    if not vmid:
        fmt.error("Usage: freq dr sla set <vmid> --rpo 24 --rto 4")
        return 1

    rpo = getattr(args, "rpo", 24)
    rto = getattr(args, "rto", 4)
    name = getattr(args, "name", "")
    tier = getattr(args, "tier", "standard")
    priority = getattr(args, "priority", 50)

    data = _load_sla_targets(cfg)
    targets = data.get("targets", [])

    # Update existing or add new
    found = False
    for t in targets:
        if str(t.get("vmid")) == str(vmid):
            t["rpo_hours"] = int(rpo)
            t["rto_hours"] = int(rto)
            if name:
                t["name"] = name
            t["tier"] = tier
            t["priority"] = int(priority)
            found = True
            break

    if not found:
        targets.append(
            {
                "vmid": int(vmid),
                "name": name or f"VM {vmid}",
                "rpo_hours": int(rpo),
                "rto_hours": int(rto),
                "tier": tier,
                "priority": int(priority),
                "created": time.strftime("%Y-%m-%d"),
            }
        )

    data["targets"] = targets
    _save_sla_targets(cfg, data)

    action = "Updated" if found else "Created"
    fmt.success(f"{action} SLA target for VM {vmid}: RPO={rpo}h, RTO={rto}h, tier={tier}")
    logger.info("dr_sla_set", vmid=vmid, rpo=rpo, rto=rto)
    return 0


# ---------------------------------------------------------------------------
# Commands — Runbooks
# ---------------------------------------------------------------------------


def cmd_dr_runbook_list(cfg: FreqConfig, pack, args) -> int:
    """List DR runbooks."""
    path = _runbooks_dir(cfg)
    runbooks = [f[:-5] for f in sorted(os.listdir(path)) if f.endswith(".json")]

    fmt.header("DR Runbooks", breadcrumb="FREQ > DR > Runbook")
    fmt.blank()

    if not runbooks:
        fmt.info("No runbooks defined")
        fmt.info("Create: freq dr runbook create <name>")
        fmt.footer()
        return 0

    for name in runbooks:
        rb = _load_runbook(cfg, name)
        if rb:
            steps = len(rb.get("steps", []))
            desc = rb.get("description", "")
            fmt.line(f"  {fmt.C.CYAN}{name:<20}{fmt.C.RESET} {steps} steps — {desc}")

    fmt.blank()
    fmt.info(f"{len(runbooks)} runbook(s)")
    fmt.footer()
    return 0


def cmd_dr_runbook_create(cfg: FreqConfig, pack, args) -> int:
    """Create a new DR runbook."""
    name = getattr(args, "name", None)
    description = getattr(args, "description", "")
    if not name:
        fmt.error('Usage: freq dr runbook create <name> --description "..."')
        return 1

    existing = _load_runbook(cfg, name)
    if existing:
        fmt.error(f"Runbook '{name}' already exists")
        return 1

    runbook = {
        "name": name,
        "description": description,
        "created": time.strftime("%Y-%m-%d"),
        "steps": [
            {"order": 1, "action": "Verify backups are current", "type": "verify"},
            {"order": 2, "action": "Notify stakeholders", "type": "notify"},
            {"order": 3, "action": "Begin recovery procedure", "type": "execute"},
            {"order": 4, "action": "Verify services restored", "type": "verify"},
            {"order": 5, "action": "Post-incident review", "type": "document"},
        ],
    }

    _save_runbook(cfg, name, runbook)
    fmt.success(f"Runbook '{name}' created with 5 default steps")
    fmt.info(f"Edit: {os.path.join(_runbooks_dir(cfg), name + '.json')}")
    logger.info("dr_runbook_create", name=name)
    return 0


def cmd_dr_runbook_show(cfg: FreqConfig, pack, args) -> int:
    """Show a DR runbook with steps."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq dr runbook show <name>")
        return 1

    rb = _load_runbook(cfg, name)
    if not rb:
        fmt.error(f"Runbook '{name}' not found")
        return 1

    fmt.header(f"Runbook: {name}", breadcrumb="FREQ > DR > Runbook")
    fmt.blank()

    if rb.get("description"):
        fmt.line(f"{fmt.C.BOLD}Description:{fmt.C.RESET} {rb['description']}")
        fmt.blank()

    steps = rb.get("steps", [])
    for s in sorted(steps, key=lambda x: x.get("order", 0)):
        order = s.get("order", "?")
        action = s.get("action", "")
        step_type = s.get("type", "")
        type_color = {
            "verify": fmt.C.CYAN,
            "execute": fmt.C.YELLOW,
            "notify": fmt.C.PURPLE_BOLD if hasattr(fmt.C, "PURPLE_BOLD") else fmt.C.BOLD,
            "document": fmt.C.DIM,
        }.get(step_type, fmt.C.RESET)
        fmt.line(f"  {fmt.C.BOLD}{order}.{fmt.C.RESET} {action}  {type_color}[{step_type}]{fmt.C.RESET}")

    fmt.blank()
    fmt.info(f"{len(steps)} step(s)")
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — DR Status Overview
# ---------------------------------------------------------------------------


def cmd_dr_status(cfg: FreqConfig, pack, args) -> int:
    """Show DR readiness overview."""
    fmt.header("DR Status", breadcrumb="FREQ > DR")
    fmt.blank()

    # SLA targets
    sla_data = _load_sla_targets(cfg)
    targets = sla_data.get("targets", [])
    fmt.line(f"{fmt.C.BOLD}SLA Targets:{fmt.C.RESET} {len(targets)} VM(s) with defined RPO/RTO")

    # Runbooks
    path = _runbooks_dir(cfg)
    runbooks = [f for f in os.listdir(path) if f.endswith(".json")]
    fmt.line(f"{fmt.C.BOLD}Runbooks:{fmt.C.RESET}    {len(runbooks)} defined")

    # Replication status (if PVE available)
    fmt.line(f"{fmt.C.BOLD}Backups:{fmt.C.RESET}     Check with freq dr backup list")
    fmt.line(f"{fmt.C.BOLD}Verify:{fmt.C.RESET}      Check with freq dr backup verify")

    fmt.blank()

    if not targets and not runbooks:
        fmt.warn("DR is not configured")
        fmt.info("Start with:")
        fmt.info("  freq dr sla set <vmid> --rpo 24 --rto 4")
        fmt.info("  freq dr runbook create <name>")
    elif not targets:
        fmt.warn("No SLA targets — set RPO/RTO per VM")
    elif not runbooks:
        fmt.warn("No runbooks — create recovery procedures")
    else:
        fmt.success("DR framework configured")

    fmt.blank()
    fmt.footer()
    return 0
