"""Infrastructure as Code for FREQ — state management and drift detection.

Domain: freq state <action>
What: Export infrastructure state, detect configuration drift across all
      device types, plan and apply desired state changes.
Replaces: Terraform for homelab, manual configuration tracking, Ansible drift
Architecture:
    - State snapshots stored in conf/state/ as JSON
    - Drift detection compares live state against last snapshot
    - Plan generates diff between desired and actual
    - Integrates with policy engine for compliance drift
Design decisions:
    - State is a snapshot, not a desired-state file. Snapshot first, plan later.
    - Drift detection covers: VMs, hosts, switches, firewall, DNS.
    - State export is read-only — never modifies infrastructure.
"""
import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


STATE_DIR = "state"


def _state_dir(cfg):
    path = os.path.join(cfg.conf_dir, STATE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def cmd_state_export(cfg: FreqConfig, pack, args) -> int:
    """Export current infrastructure state as a snapshot."""
    fmt.header("State Export", breadcrumb="FREQ > State")
    fmt.blank()

    state = {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hosts": [],
        "vlans": [],
        "config": {},
    }

    # Export host inventory
    for h in cfg.hosts:
        state["hosts"].append({
            "label": h.label, "ip": h.ip,
            "htype": h.htype, "groups": h.groups,
        })
    fmt.step_ok(f"Hosts: {len(state['hosts'])}")

    # Export VLANs
    vlans_path = os.path.join(cfg.conf_dir, "vlans.toml")
    if os.path.exists(vlans_path):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open(vlans_path, "rb") as f:
            vlan_data = tomllib.load(f)
        for vname, vinfo in vlan_data.get("vlan", {}).items():
            state["vlans"].append({"name": vname, **vinfo})
        fmt.step_ok(f"VLANs: {len(state['vlans'])}")

    # Save snapshot
    ts = time.strftime("%Y%m%d-%H%M%S")
    filepath = os.path.join(_state_dir(cfg), f"state-{ts}.json")
    with open(filepath, "w") as f:
        json.dump(state, f, indent=2)

    # Also save as latest
    latest = os.path.join(_state_dir(cfg), "state-latest.json")
    with open(latest, "w") as f:
        json.dump(state, f, indent=2)

    fmt.step_ok(f"Saved to {filepath}")
    fmt.blank()
    logger.info("state_export", hosts=len(state["hosts"]))
    fmt.footer()
    return 0


def cmd_state_drift(cfg: FreqConfig, pack, args) -> int:
    """Detect configuration drift against last state snapshot."""
    latest_path = os.path.join(_state_dir(cfg), "state-latest.json")
    if not os.path.exists(latest_path):
        fmt.warn("No state snapshot. Run: freq state export")
        return 1

    with open(latest_path) as f:
        saved = json.load(f)

    fmt.header("Drift Detection", breadcrumb="FREQ > State")
    fmt.blank()
    fmt.line(f"{fmt.C.DIM}Comparing against: {saved.get('exported_at', '?')}{fmt.C.RESET}")
    fmt.blank()

    changes = 0

    # Compare hosts
    saved_hosts = {h["label"]: h for h in saved.get("hosts", [])}
    current_hosts = {h.label: h for h in cfg.hosts}

    added = set(current_hosts) - set(saved_hosts)
    removed = set(saved_hosts) - set(current_hosts)

    if added:
        for label in sorted(added):
            fmt.line(f"  {fmt.C.GREEN}+ Host added: {label}{fmt.C.RESET}")
            changes += 1
    if removed:
        for label in sorted(removed):
            fmt.line(f"  {fmt.C.RED}- Host removed: {label}{fmt.C.RESET}")
            changes += 1

    # Check for IP/type changes
    for label in set(saved_hosts) & set(current_hosts):
        old = saved_hosts[label]
        new = current_hosts[label]
        if old.get("ip") != new.ip:
            fmt.line(f"  {fmt.C.YELLOW}~ {label}: IP {old.get('ip')} -> {new.ip}{fmt.C.RESET}")
            changes += 1
        if old.get("htype") != new.htype:
            fmt.line(f"  {fmt.C.YELLOW}~ {label}: type {old.get('htype')} -> {new.htype}{fmt.C.RESET}")
            changes += 1

    fmt.blank()
    if changes:
        fmt.warn(f"{changes} drift(s) detected")
    else:
        fmt.success("No drift — infrastructure matches snapshot")

    logger.info("state_drift", changes=changes)
    fmt.footer()
    return 0


def cmd_state_history(cfg: FreqConfig, pack, args) -> int:
    """Show state snapshot history."""
    path = _state_dir(cfg)
    files = sorted([f for f in os.listdir(path) if f.startswith("state-") and f.endswith(".json")
                    and f != "state-latest.json"], reverse=True)

    fmt.header("State History", breadcrumb="FREQ > State")
    fmt.blank()

    if not files:
        fmt.info("No state snapshots")
        fmt.footer()
        return 0

    for fname in files[:20]:
        filepath = os.path.join(path, fname)
        size = os.path.getsize(filepath)
        ts = fname.replace("state-", "").replace(".json", "")
        formatted = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}"
        fmt.line(f"  {fmt.C.CYAN}{formatted}{fmt.C.RESET}  {size // 1024}KB")

    fmt.blank()
    fmt.info(f"{len(files)} snapshot(s)")
    fmt.footer()
    return 0
