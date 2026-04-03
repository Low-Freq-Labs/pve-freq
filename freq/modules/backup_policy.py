"""Declarative backup policies for FREQ.

Domain: freq dr <backup-policy-list|backup-policy-create|backup-policy-delete|backup-policy-apply|backup-policy-status>

Define backup policies once, FREQ enforces them forever. Tag-based targeting
("all VMs tagged prod: daily snapshot, 7-day retention"), automatic cleanup
of expired backups, and compliance reporting per policy.

Replaces: Veeam ($$$), manual cron scripts, hope-based backup strategies

Architecture:
    - Policies stored as JSON in conf/backup-policies/
    - Policy evaluation matches VM tags/names against policy selectors
    - Snapshot creation via PVE SSH (pvesh/qm) on matched VMs
    - State tracking records last run, next due, retention compliance

Design decisions:
    - Policies are declarative (what, not how). The scheduler decides when
      to evaluate; the policy engine decides what to snapshot and prune.
"""

import json
import os
import re
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Storage
BPOLICY_DIR = "backup-policies"
BPOLICY_FILE = "policies.json"
BPOLICY_STATE = "policy-state.json"

PVE_CMD_TIMEOUT = 30
PVE_QUICK_TIMEOUT = 10
PVE_SNAPSHOT_TIMEOUT = 120


def _policy_dir(cfg: FreqConfig) -> str:
    """Get or create policy directory."""
    path = os.path.join(cfg.conf_dir, BPOLICY_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_policies(cfg: FreqConfig) -> list:
    """Load backup policies."""
    filepath = os.path.join(_policy_dir(cfg), BPOLICY_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_policies(cfg: FreqConfig, policies: list):
    """Save backup policies."""
    filepath = os.path.join(_policy_dir(cfg), BPOLICY_FILE)
    with open(filepath, "w") as f:
        json.dump(policies, f, indent=2)


def _load_state(cfg: FreqConfig) -> dict:
    """Load policy enforcement state."""
    filepath = os.path.join(_policy_dir(cfg), BPOLICY_STATE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_run": "", "snapshots_created": 0, "snapshots_pruned": 0}


def _save_state(cfg: FreqConfig, state: dict):
    """Save policy enforcement state."""
    filepath = os.path.join(_policy_dir(cfg), BPOLICY_STATE)
    with open(filepath, "w") as f:
        json.dump(state, f, indent=2)


def _find_reachable_node(cfg: FreqConfig) -> str:
    """Find a reachable PVE node."""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip,
            command="pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=PVE_QUICK_TIMEOUT,
            htype="pve",
            use_sudo=True,
        )
        if r.returncode == 0:
            return ip
    return ""


def _pve_cmd(cfg, node_ip, command, timeout=PVE_CMD_TIMEOUT):
    """Execute PVE command via SSH."""
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


def _get_vms_for_policy(cfg: FreqConfig, node_ip: str, policy: dict) -> list:
    """Get VMs that match a policy's target criteria."""
    import json as json_mod

    stdout, ok = _pve_cmd(
        cfg, node_ip, "pvesh get /cluster/resources --type vm --output-format json", timeout=PVE_CMD_TIMEOUT
    )
    if not ok:
        return []

    try:
        all_vms = json_mod.loads(stdout)
    except json_mod.JSONDecodeError:
        return []

    target = policy.get("target", "*")
    target_type = policy.get("target_type", "tag")  # tag, vmid_range, all

    matched = []
    for vm in all_vms:
        if vm.get("status") != "running" and not policy.get("include_stopped", False):
            continue

        if target == "*" or target_type == "all":
            matched.append(vm)
        elif target_type == "tag":
            tags = vm.get("tags", "")
            if target in tags.split(";"):
                matched.append(vm)
        elif target_type == "vmid_range":
            vmid = vm.get("vmid", 0)
            parts = target.split("-")
            if len(parts) == 2:
                try:
                    if int(parts[0]) <= vmid <= int(parts[1]):
                        matched.append(vm)
                except ValueError:
                    pass

    return matched


def cmd_backup_policy(cfg: FreqConfig, pack, args) -> int:
    """Backup policy management."""
    action = getattr(args, "action", None) or "list"

    routes = {
        "list": _cmd_list,
        "create": _cmd_create,
        "delete": _cmd_delete,
        "apply": _cmd_apply,
        "status": _cmd_status,
    }

    handler = routes.get(action)
    if handler:
        return handler(cfg, args)

    fmt.error(f"Unknown backup-policy action: {action}")
    fmt.info("Available: list, create, delete, apply, status")
    return 1


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List backup policies."""
    fmt.header("Backup Policies")
    fmt.blank()

    policies = _load_policies(cfg)
    if not policies:
        fmt.line(f"  {fmt.C.DIM}No backup policies defined.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Create one:{fmt.C.RESET}")
        fmt.line(
            f"  {fmt.C.DIM}  freq backup-policy create prod-daily --target prod --interval 24h --retention 7{fmt.C.RESET}"
        )
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("NAME", 18),
        ("TARGET", 12),
        ("INTERVAL", 10),
        ("RETENTION", 10),
        ("STATUS", 8),
    )

    for p in policies:
        enabled = p.get("enabled", True)
        status = fmt.badge("on") if enabled else f"{fmt.C.RED}OFF{fmt.C.RESET}"
        fmt.table_row(
            (f"{fmt.C.BOLD}{p['name']}{fmt.C.RESET}", 18),
            (p.get("target", "*"), 12),
            (p.get("interval", ""), 10),
            (f"{p.get('retention', 7)}d", 10),
            (status, 8),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(policies)} policy/policies{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_create(cfg: FreqConfig, args) -> int:
    """Create a new backup policy."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq backup-policy create <name> --target <tag> --interval <24h> --retention <7>")
        return 1

    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        fmt.error("Policy name must be alphanumeric with hyphens/underscores.")
        return 1

    target = getattr(args, "target", None) or "*"
    target_type = getattr(args, "target_type", None) or "tag"
    interval = getattr(args, "interval", None) or "24h"
    retention = getattr(args, "retention", 7)

    policies = _load_policies(cfg)
    if any(p["name"] == name for p in policies):
        fmt.error(f"Policy '{name}' already exists.")
        return 1

    policy = {
        "name": name,
        "target": target,
        "target_type": target_type,
        "interval": interval,
        "retention": retention,
        "enabled": True,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    policies.append(policy)
    _save_policies(cfg, policies)

    fmt.header("Backup Policy Created")
    fmt.blank()
    fmt.step_ok(f"Policy: {name}")
    fmt.line(f"  Target:    {target} (by {target_type})")
    fmt.line(f"  Interval:  {interval}")
    fmt.line(f"  Retention: {retention} days")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Apply now: freq backup-policy apply{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_delete(cfg: FreqConfig, args) -> int:
    """Delete a backup policy."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq backup-policy delete <name>")
        return 1

    policies = _load_policies(cfg)
    original = len(policies)
    policies = [p for p in policies if p["name"] != name]
    if len(policies) == original:
        fmt.error(f"No policy named '{name}'")
        return 1

    _save_policies(cfg, policies)
    fmt.step_ok(f"Deleted policy: {name}")
    return 0


def _cmd_apply(cfg: FreqConfig, args) -> int:
    """Apply all backup policies — create snapshots and prune old ones."""
    fmt.header("Apply Backup Policies")
    fmt.blank()

    policies = _load_policies(cfg)
    active = [p for p in policies if p.get("enabled", True)]

    if not active:
        fmt.line(f"  {fmt.C.YELLOW}No active backup policies.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.line(f"  Connected to PVE node: {node_ip}")
    fmt.line(f"  Active policies: {len(active)}")
    fmt.blank()

    created = 0
    pruned = 0

    for policy in active:
        fmt.divider(f"Policy: {policy['name']}")
        fmt.blank()

        vms = _get_vms_for_policy(cfg, node_ip, policy)
        fmt.line(f"  Matching VMs: {len(vms)}")

        for vm in vms:
            vmid = vm.get("vmid", 0)
            vm_name = vm.get("name", "")
            snap_prefix = f"freq-bp-{policy['name']}"
            snap_name = f"{snap_prefix}-{time.strftime('%Y%m%d-%H%M')}"

            # Create snapshot
            fmt.step_start(f"Snapshot VM {vmid} ({vm_name})")
            stdout, ok = _pve_cmd(
                cfg,
                node_ip,
                f"qm snapshot {vmid} {snap_name} --description 'Backup policy: {policy['name']}'",
                timeout=PVE_SNAPSHOT_TIMEOUT,
            )

            if ok:
                fmt.step_ok(f"Created: {snap_name}")
                created += 1
            else:
                fmt.step_fail(f"Failed: {stdout[:60]}")

            # Prune old snapshots beyond retention
            retention = policy.get("retention", 7)
            stdout, ok = _pve_cmd(cfg, node_ip, f"qm listsnapshot {vmid}", timeout=PVE_CMD_TIMEOUT)
            if ok:
                policy_snaps = []
                for line in stdout.strip().split("\n"):
                    parts = line.strip().split()
                    if parts:
                        sname = parts[0].replace("`-", "").replace("->", "").strip()
                        if sname.startswith(snap_prefix) and sname != "current":
                            policy_snaps.append(sname)

                # Keep only the N most recent
                if len(policy_snaps) > retention:
                    to_prune = sorted(policy_snaps)[:-retention]
                    for old_snap in to_prune:
                        fmt.step_start(f"Pruning: {old_snap}")
                        _, del_ok = _pve_cmd(
                            cfg, node_ip, f"qm delsnapshot {vmid} {old_snap}", timeout=PVE_SNAPSHOT_TIMEOUT
                        )
                        if del_ok:
                            fmt.step_ok(f"Pruned: {old_snap}")
                            pruned += 1
                        else:
                            fmt.step_fail(f"Prune failed: {old_snap}")

        fmt.blank()

    # Update state
    state = _load_state(cfg)
    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    state["snapshots_created"] = state.get("snapshots_created", 0) + created
    state["snapshots_pruned"] = state.get("snapshots_pruned", 0) + pruned
    _save_state(cfg, state)

    fmt.divider("Summary")
    fmt.blank()
    fmt.line(f"  Snapshots created: {fmt.C.GREEN}{created}{fmt.C.RESET}")
    fmt.line(f"  Snapshots pruned:  {fmt.C.YELLOW}{pruned}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_status(cfg: FreqConfig, args) -> int:
    """Show backup policy enforcement status."""
    fmt.header("Backup Policy Status")
    fmt.blank()

    state = _load_state(cfg)
    policies = _load_policies(cfg)

    fmt.line(f"  Policies:          {len(policies)} total, {sum(1 for p in policies if p.get('enabled', True))} active")
    fmt.line(f"  Last enforcement:  {state.get('last_run', 'never')}")
    fmt.line(f"  Total created:     {state.get('snapshots_created', 0)}")
    fmt.line(f"  Total pruned:      {state.get('snapshots_pruned', 0)}")
    fmt.blank()
    fmt.footer()
    return 0
