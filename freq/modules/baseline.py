"""Configuration baseline and drift detection for FREQ.

Commands: baseline (capture/compare/list/delete)

Capture a known-good config state. Compare later to detect drift.
Packages added? Services changed? Users modified? Network reconfigured?
Baseline catches it all.

Kills: Puppet (dead), Chef (dying), SaltStack (abandoned).
One command, not a DSL nobody understands.
"""
import json
import os
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many

# Baseline storage
BASELINE_DIR = "baselines"
BASELINE_CMD_TIMEOUT = 20

# What we capture
BASELINE_COMMAND = (
    'echo "---PACKAGES---"; '
    "dpkg --list 2>/dev/null | grep '^ii' | awk '{print $2\"=\"$3}' | sort || "
    "rpm -qa --queryformat '%{NAME}=%{VERSION}-%{RELEASE}\\n' 2>/dev/null | sort || "
    "echo 'unknown'; "
    'echo "---SERVICES---"; '
    "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | "
    "awk '{print $1}' | sort || echo 'unknown'; "
    'echo "---USERS---"; '
    "awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd 2>/dev/null | sort || echo 'unknown'; "
    'echo "---NETWORK---"; '
    "ip -4 addr show 2>/dev/null | grep 'inet ' | awk '{print $NF\"=\"$2}' | sort || echo 'unknown'; "
    'echo "---KERNEL---"; '
    "uname -r; "
    'echo "---HOSTNAME---"; '
    "hostname -f 2>/dev/null || hostname; "
    'echo "---DOCKER---"; '
    "docker ps --format '{{.Names}}={{.Image}}' 2>/dev/null | sort || echo 'none'; "
    'echo "---PORTS---"; '
    "ss -tlnp 2>/dev/null | awk 'NR>1 {print $4}' | sort -u || echo 'unknown'; "
    'echo "---END---"'
)


def _baseline_dir(cfg: FreqConfig) -> str:
    """Get or create baselines directory."""
    path = os.path.join(cfg.conf_dir, BASELINE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _parse_sections(output: str) -> dict:
    """Parse sectioned output into a dict of section_name → list of lines."""
    sections = {}
    current = None
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("---") and line.endswith("---"):
            current = line.strip("-").lower()
            sections[current] = []
        elif current and line:
            sections[current].append(line)
    return sections


def _load_baseline(cfg: FreqConfig, name: str) -> dict:
    """Load a baseline from disk."""
    filepath = os.path.join(_baseline_dir(cfg), f"{name}.json")
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_baseline(cfg: FreqConfig, name: str, data: dict):
    """Save a baseline to disk."""
    filepath = os.path.join(_baseline_dir(cfg), f"{name}.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _list_baselines(cfg: FreqConfig) -> list:
    """List saved baselines."""
    bdir = _baseline_dir(cfg)
    baselines = []
    for f in sorted(os.listdir(bdir)):
        if f.endswith(".json"):
            filepath = os.path.join(bdir, f)
            try:
                with open(filepath, "r") as fh:
                    data = json.load(fh)
                baselines.append({
                    "name": f.replace(".json", ""),
                    "timestamp": data.get("timestamp", "unknown"),
                    "host_count": len(data.get("hosts", {})),
                })
            except (json.JSONDecodeError, OSError):
                baselines.append({"name": f.replace(".json", ""), "timestamp": "corrupt", "host_count": 0})
    return baselines


def cmd_baseline(cfg: FreqConfig, pack, args) -> int:
    """Baseline management dispatch."""
    action = getattr(args, "action", None) or "list"

    routes = {
        "capture": _cmd_capture,
        "compare": _cmd_compare,
        "list": _cmd_list,
        "delete": _cmd_delete,
    }

    handler = routes.get(action)
    if handler:
        return handler(cfg, args)

    fmt.error(f"Unknown baseline action: {action}")
    fmt.info("Available: capture, compare, list, delete")
    return 1


def _cmd_capture(cfg: FreqConfig, args) -> int:
    """Capture a new baseline from current fleet state."""
    name = getattr(args, "name", None) or time.strftime("baseline-%Y%m%d-%H%M%S")

    fmt.header(f"Baseline Capture: {name}")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts in fleet.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.step_start(f"Scanning {len(hosts)} hosts")

    results = ssh_run_many(
        hosts=hosts,
        command=BASELINE_COMMAND,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=BASELINE_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    baseline = {
        "name": name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hosts": {},
    }

    captured = 0
    for h in hosts:
        r = results.get(h.label)
        if r and r.returncode == 0:
            sections = _parse_sections(r.stdout)
            baseline["hosts"][h.label] = sections
            captured += 1

    fmt.step_ok(f"Captured {captured}/{len(hosts)} hosts")
    fmt.blank()

    # Save
    _save_baseline(cfg, name, baseline)

    fmt.step_ok(f"Saved: {name}")
    fmt.blank()

    # Show what was captured
    for h in hosts:
        data = baseline["hosts"].get(h.label, {})
        if data:
            pkg = len(data.get("packages", []))
            svc = len(data.get("services", []))
            usr = len(data.get("users", []))
            net = len(data.get("network", []))
            dkr = len([d for d in data.get("docker", []) if d != "none"])
            fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {h.label}: "
                     f"{pkg} packages, {svc} services, {usr} users, "
                     f"{net} interfaces, {dkr} containers")
        else:
            fmt.line(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {h.label}: unreachable")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Compare later: freq baseline compare {name}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_compare(cfg: FreqConfig, args) -> int:
    """Compare current fleet state against a saved baseline."""
    name = getattr(args, "name", None)
    if not name:
        # Use most recent baseline
        baselines = _list_baselines(cfg)
        if not baselines:
            fmt.error("No baselines saved. Capture one first: freq baseline capture")
            return 1
        name = baselines[-1]["name"]

    baseline = _load_baseline(cfg, name)
    if not baseline:
        fmt.error(f"Baseline '{name}' not found")
        return 1

    fmt.header(f"Baseline Drift: {name}")
    fmt.blank()
    fmt.line(f"  Baseline from: {baseline.get('timestamp', 'unknown')}")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts in fleet.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Gather current state
    fmt.step_start(f"Scanning {len(hosts)} hosts")

    results = ssh_run_many(
        hosts=hosts,
        command=BASELINE_COMMAND,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=BASELINE_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    fmt.step_ok("Scan complete")
    fmt.blank()

    total_drift = 0
    baseline_hosts = baseline.get("hosts", {})

    for h in hosts:
        r = results.get(h.label)
        saved = baseline_hosts.get(h.label, {})

        if not saved:
            fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET} {h.label}: not in baseline (new host?)")
            continue

        if not r or r.returncode != 0:
            fmt.line(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {h.label}: unreachable (was in baseline)")
            total_drift += 1
            continue

        current = _parse_sections(r.stdout)

        # Compare each section
        host_drifts = []

        for section in ("packages", "services", "users", "network", "docker", "ports"):
            old_set = set(saved.get(section, []))
            new_set = set(current.get(section, []))

            added = new_set - old_set
            removed = old_set - new_set

            if added or removed:
                host_drifts.append({
                    "section": section,
                    "added": sorted(added),
                    "removed": sorted(removed),
                })

        # Check kernel change
        old_kernel = saved.get("kernel", [""])[0] if saved.get("kernel") else ""
        new_kernel = current.get("kernel", [""])[0] if current.get("kernel") else ""
        if old_kernel and new_kernel and old_kernel != new_kernel:
            host_drifts.append({
                "section": "kernel",
                "added": [new_kernel],
                "removed": [old_kernel],
            })

        # Report
        if not host_drifts:
            fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {h.label}: no drift")
        else:
            total_drift += len(host_drifts)
            fmt.line(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {h.label}: "
                     f"{fmt.C.YELLOW}{len(host_drifts)} section(s) changed{fmt.C.RESET}")

            for drift in host_drifts:
                section = drift["section"]
                added = drift["added"]
                removed = drift["removed"]

                if added:
                    # Show max 5 items
                    shown = added[:5]
                    extra = f" (+{len(added)-5} more)" if len(added) > 5 else ""
                    fmt.line(f"      {fmt.C.GREEN}+ {section}:{fmt.C.RESET} {', '.join(shown)}{extra}")

                if removed:
                    shown = removed[:5]
                    extra = f" (+{len(removed)-5} more)" if len(removed) > 5 else ""
                    fmt.line(f"      {fmt.C.RED}- {section}:{fmt.C.RESET} {', '.join(shown)}{extra}")

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()

    if total_drift == 0:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} Fleet matches baseline — zero drift.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.RED}{fmt.S.WARN} {total_drift} drift(s) detected since baseline.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 1 if total_drift > 0 else 0


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List saved baselines."""
    fmt.header("Saved Baselines")
    fmt.blank()

    baselines = _list_baselines(cfg)
    if not baselines:
        fmt.line(f"  {fmt.C.DIM}No baselines saved.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Capture one: freq baseline capture [name]{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("NAME", 30),
        ("TIMESTAMP", 22),
        ("HOSTS", 8),
    )

    for b in baselines:
        fmt.table_row(
            (f"{fmt.C.BOLD}{b['name']}{fmt.C.RESET}", 30),
            (b["timestamp"][:22], 22),
            (str(b["host_count"]), 8),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(baselines)} baseline(s){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_delete(cfg: FreqConfig, args) -> int:
    """Delete a saved baseline."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq baseline delete <name>")
        return 1

    filepath = os.path.join(_baseline_dir(cfg), f"{name}.json")
    if not os.path.exists(filepath):
        fmt.error(f"Baseline '{name}' not found")
        return 1

    os.remove(filepath)

    fmt.header("Baseline Deleted")
    fmt.blank()
    fmt.step_ok(f"Deleted: {name}")
    fmt.blank()
    fmt.footer()
    return 0
