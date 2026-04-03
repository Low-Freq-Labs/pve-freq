"""Network device configuration management for FREQ — Oxidized-style.

Domain: freq net config <action> [target]
What: Backup, diff, search, and restore network device configurations.
      Stores running-configs as timestamped text files for history tracking,
      change detection, and compliance auditing.
Replaces: Oxidized, RANCID, manual SSH config pulls
Architecture:
    - Configs stored as flat files in conf/switch-configs/<label>-<timestamp>.conf
    - Uses deployer get_config() for pulling and push_config() for restoring
    - difflib for config diffs (unified format)
    - Regex search across all stored configs
Design decisions:
    - Flat files, not a database. Easy to git-track, backup, grep.
    - One file per backup per device. No overwriting — full history.
    - Diff against last backup or between any two versions.
    - Search is grep across all stored config files — fast, simple.
"""

import os
import re
import difflib
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Config Storage
# ---------------------------------------------------------------------------

CONFIG_DIR = "switch-configs"


def _config_dir(cfg):
    """Return the config storage directory path, creating if needed."""
    path = os.path.join(cfg.conf_dir, CONFIG_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _list_backups(cfg, label=None):
    """List all config backups, optionally filtered by device label.

    Returns list of (filepath, label, timestamp_str) sorted newest-first.
    """
    config_path = _config_dir(cfg)
    backups = []

    for f in os.listdir(config_path):
        if not f.endswith(".conf"):
            continue
        # Format: label-YYYYMMDD-HHMMSS.conf
        m = re.match(r"^(.+)-(\d{8}-\d{6})\.conf$", f)
        if m:
            file_label = m.group(1)
            ts = m.group(2)
            if label and file_label != label:
                continue
            backups.append((os.path.join(config_path, f), file_label, ts))

    backups.sort(key=lambda x: x[2], reverse=True)
    return backups


def _latest_backup(cfg, label):
    """Return the filepath of the most recent backup for a device, or None."""
    backups = _list_backups(cfg, label)
    return backups[0][0] if backups else None


def _resolve_switch_target(target, cfg):
    """Resolve target for config commands. Reuses switch_orchestration logic."""
    from freq.modules.switch_orchestration import _resolve_target, _get_deployer

    ip, label, vendor = _resolve_target(target, cfg)
    if not ip:
        return None, None, None, None
    deployer = _get_deployer(vendor)
    return ip, label, vendor, deployer


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_config_backup(cfg: FreqConfig, pack, args) -> int:
    """Pull and store running-config from a device or all devices."""
    run_all = getattr(args, "all", False)

    if run_all:
        return _backup_all(cfg)

    target = getattr(args, "target", None)
    ip, label, vendor, deployer = _resolve_switch_target(target, cfg)
    if not deployer:
        fmt.error("No switch target. Usage: freq net config backup <target> or --all")
        return 1

    fmt.header(f"Config Backup: {label}", breadcrumb="FREQ > Net > Config")
    fmt.blank()

    fmt.step_start(f"Pulling config from {label} ({ip})")
    config_text = deployer.get_config(ip, cfg)
    if not config_text:
        fmt.step_fail("Could not retrieve config")
        fmt.footer()
        return 1
    fmt.step_ok(f"{len(config_text.splitlines())} lines")

    # Save
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{label}-{ts}.conf"
    filepath = os.path.join(_config_dir(cfg), filename)
    with open(filepath, "w") as f:
        f.write(config_text)

    fmt.step_ok(f"Saved to {filepath}")

    # Show diff against previous if one exists
    previous = _latest_backup_before(cfg, label, ts)
    if previous:
        with open(previous) as f:
            old_lines = f.read().splitlines()
        new_lines = config_text.splitlines()
        changes = list(
            difflib.unified_diff(old_lines, new_lines, lineterm="", fromfile="previous", tofile="current", n=0)
        )
        added = sum(1 for l in changes if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in changes if l.startswith("-") and not l.startswith("---"))
        if added or removed:
            fmt.info(f"Changes since last backup: +{added} -{removed} lines")
        else:
            fmt.info("No changes since last backup")

    fmt.blank()
    logger.info("config_backup", target=label, ip=ip, lines=len(config_text.splitlines()))
    fmt.footer()
    return 0


def _backup_all(cfg):
    """Backup configs from all switches."""
    from freq.modules.switch_orchestration import _get_switch_hosts, _get_deployer, _vendor_for_host

    switches = _get_switch_hosts(cfg)
    if not switches:
        fmt.error("No switches in hosts.conf")
        return 1

    fmt.header("Config Backup: All Switches", breadcrumb="FREQ > Net > Config")
    fmt.blank()

    ok_count = 0
    for h in switches:
        vendor = _vendor_for_host(h)
        deployer = _get_deployer(vendor)
        if not deployer:
            fmt.step_fail(f"{h.label}: no deployer for {vendor}")
            continue

        fmt.step_start(f"Backing up {h.label} ({h.ip})")
        config_text = deployer.get_config(h.ip, cfg)
        if not config_text:
            fmt.step_fail(f"{h.label}: could not retrieve config")
            continue

        ts = time.strftime("%Y%m%d-%H%M%S")
        filename = f"{h.label}-{ts}.conf"
        filepath = os.path.join(_config_dir(cfg), filename)
        with open(filepath, "w") as f:
            f.write(config_text)
        fmt.step_ok(f"{h.label}: {len(config_text.splitlines())} lines")
        ok_count += 1

    fmt.blank()
    fmt.info(f"{ok_count}/{len(switches)} devices backed up")
    logger.info("config_backup_all", targets=len(switches), ok=ok_count)
    fmt.footer()
    return 0 if ok_count > 0 else 1


def _latest_backup_before(cfg, label, current_ts):
    """Return filepath of the most recent backup BEFORE current_ts, or None."""
    backups = _list_backups(cfg, label)
    for filepath, _, ts in backups:
        if ts < current_ts:
            return filepath
    return None


def cmd_config_history(cfg: FreqConfig, pack, args) -> int:
    """Show config backup history for a device."""
    target = getattr(args, "target", None)
    if not target:
        # Show all devices
        return _history_all(cfg)

    # Resolve to label
    ip, label, vendor, deployer = _resolve_switch_target(target, cfg)
    if not label:
        label = target  # Use raw target as label for history lookup

    backups = _list_backups(cfg, label)

    fmt.header(f"Config History: {label}", breadcrumb="FREQ > Net > Config")
    fmt.blank()

    if not backups:
        fmt.warn(f"No backups found for {label}")
        fmt.info("Run: freq net config backup <target>")
        fmt.footer()
        return 0

    fmt.table_header(("Version", 8), ("Timestamp", 20), ("Size", 10))
    for i, (filepath, _, ts) in enumerate(backups):
        # Format timestamp: 20260401-183000 -> 2026-04-01 18:30:00
        formatted = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
        size = os.path.getsize(filepath)
        size_str = f"{size:,} B" if size < 1024 else f"{size // 1024} KB"
        version = len(backups) - i
        fmt.table_row(
            (f"v{version}", 8),
            (formatted, 20),
            (size_str, 10),
        )

    fmt.blank()
    fmt.info(f"{len(backups)} backup(s)")
    fmt.footer()
    return 0


def _history_all(cfg):
    """Show backup summary across all devices."""
    backups = _list_backups(cfg)

    fmt.header("Config History: All Devices", breadcrumb="FREQ > Net > Config")
    fmt.blank()

    if not backups:
        fmt.warn("No backups found")
        fmt.info("Run: freq net config backup <target> or --all")
        fmt.footer()
        return 0

    # Group by label
    by_label = {}
    for filepath, label, ts in backups:
        by_label.setdefault(label, []).append((filepath, ts))

    fmt.table_header(("Device", 16), ("Backups", 8), ("Latest", 20), ("Oldest", 20))
    for label in sorted(by_label):
        entries = by_label[label]
        latest = entries[0][1]
        oldest = entries[-1][1]
        lat_fmt = f"{latest[:4]}-{latest[4:6]}-{latest[6:8]} {latest[9:11]}:{latest[11:13]}"
        old_fmt = f"{oldest[:4]}-{oldest[4:6]}-{oldest[6:8]} {oldest[9:11]}:{oldest[11:13]}"
        fmt.table_row(
            (label, 16),
            (str(len(entries)), 8),
            (lat_fmt, 20),
            (old_fmt, 20),
        )

    fmt.blank()
    fmt.info(f"{len(by_label)} device(s), {len(backups)} total backup(s)")
    fmt.footer()
    return 0


def cmd_config_diff(cfg: FreqConfig, pack, args) -> int:
    """Diff running config vs last backup, or between two versions."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq net config diff <target> [--version N]")
        return 1

    ip, label, vendor, deployer = _resolve_switch_target(target, cfg)
    version = getattr(args, "version", None)

    fmt.header(f"Config Diff: {label or target}", breadcrumb="FREQ > Net > Config")
    fmt.blank()

    # If we have a live deployer, diff running vs last backup
    if deployer and ip:
        fmt.step_start(f"Pulling running config from {label}")
        running = deployer.get_config(ip, cfg)
        if not running:
            fmt.step_fail("Could not retrieve running config")
            fmt.footer()
            return 1
        fmt.step_ok("Got running config")

        latest_path = _latest_backup(cfg, label)
        if not latest_path:
            fmt.warn("No previous backup to compare against")
            fmt.info("Run: freq net config backup <target>")
            fmt.footer()
            return 0

        with open(latest_path) as f:
            stored = f.read()

        _show_diff(stored.splitlines(), running.splitlines(), "last backup", "running")
    else:
        # Offline diff between two stored versions
        if not label:
            label = target
        backups = _list_backups(cfg, label)
        if len(backups) < 2:
            fmt.warn(f"Need at least 2 backups to diff. Found {len(backups)}")
            fmt.footer()
            return 0

        if version:
            idx = len(backups) - int(version)
            if idx < 0 or idx >= len(backups):
                fmt.error(f"Version {version} not found (have {len(backups)} backups)")
                fmt.footer()
                return 1
            old_path = backups[idx][0]
        else:
            old_path = backups[1][0]  # second newest

        new_path = backups[0][0]  # newest

        with open(old_path) as f:
            old_lines = f.read().splitlines()
        with open(new_path) as f:
            new_lines = f.read().splitlines()

        _show_diff(old_lines, new_lines, os.path.basename(old_path), os.path.basename(new_path))

    fmt.blank()
    logger.info("config_diff", target=label or target)
    fmt.footer()
    return 0


def _show_diff(old_lines, new_lines, old_label, new_label):
    """Display a unified diff between two config versions."""
    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm="",
            fromfile=old_label,
            tofile=new_label,
            n=3,
        )
    )

    if not diff:
        fmt.success("No differences")
        return

    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    fmt.info(f"+{added} -{removed} lines changed")
    fmt.blank()

    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            fmt.line(f"{fmt.C.BOLD}{line}{fmt.C.RESET}")
        elif line.startswith("@@"):
            fmt.line(f"{fmt.C.CYAN}{line}{fmt.C.RESET}")
        elif line.startswith("+"):
            fmt.line(f"{fmt.C.GREEN}{line}{fmt.C.RESET}")
        elif line.startswith("-"):
            fmt.line(f"{fmt.C.RED}{line}{fmt.C.RESET}")
        else:
            fmt.line(f"{fmt.C.DIM}{line}{fmt.C.RESET}")


def cmd_config_search(cfg: FreqConfig, pack, args) -> int:
    """Search across all stored device configs."""
    pattern = getattr(args, "pattern", None)
    if not pattern:
        fmt.error('Usage: freq net config search "<pattern>"')
        return 1

    fmt.header(f"Config Search: {pattern}", breadcrumb="FREQ > Net > Config")
    fmt.blank()

    config_path = _config_dir(cfg)
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        fmt.error(f"Invalid pattern: {e}")
        return 1

    # Search latest backup per device only
    seen_labels = set()
    backups = _list_backups(cfg)
    latest_per_device = []
    for filepath, label, ts in backups:
        if label not in seen_labels:
            seen_labels.add(label)
            latest_per_device.append((filepath, label))

    total_matches = 0
    for filepath, label in latest_per_device:
        with open(filepath) as f:
            lines = f.readlines()

        matches = []
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append((i, line.rstrip()))

        if matches:
            fmt.line(f"{fmt.C.BOLD}{label}{fmt.C.RESET} ({len(matches)} match{'es' if len(matches) > 1 else ''})")
            for lineno, text in matches[:10]:
                highlighted = regex.sub(
                    lambda m: f"{fmt.C.YELLOW}{m.group()}{fmt.C.DIM}",
                    text,
                )
                fmt.line(f"  {fmt.C.DIM}{lineno:>4}: {highlighted}{fmt.C.RESET}")
            if len(matches) > 10:
                fmt.line(f"  {fmt.C.DIM}... and {len(matches) - 10} more{fmt.C.RESET}")
            fmt.blank()
            total_matches += len(matches)

    if total_matches == 0:
        fmt.warn(f"No matches for '{pattern}' across {len(latest_per_device)} device(s)")
    else:
        fmt.info(f"{total_matches} match(es) across {len(seen_labels)} device(s)")

    logger.info("config_search", pattern=pattern, matches=total_matches)
    fmt.footer()
    return 0


def cmd_config_restore(cfg: FreqConfig, pack, args) -> int:
    """Restore a previous config version to a device."""
    target = getattr(args, "target", None)
    version = getattr(args, "version", None)

    if not target:
        fmt.error("Usage: freq net config restore <target> --version N")
        return 1

    ip, label, vendor, deployer = _resolve_switch_target(target, cfg)
    if not deployer or not ip:
        fmt.error(f"Cannot reach switch '{target}' — need live connection for restore")
        return 1

    backups = _list_backups(cfg, label)
    if not backups:
        fmt.error(f"No backups found for {label}")
        return 1

    # Resolve version
    if version:
        idx = len(backups) - int(version)
        if idx < 0 or idx >= len(backups):
            fmt.error(f"Version {version} not found (have {len(backups)} backups)")
            return 1
        restore_path = backups[idx][0]
    else:
        if len(backups) < 2:
            fmt.error("Only 1 backup exists — nothing to restore from. Specify --version N")
            return 1
        restore_path = backups[1][0]  # second newest (roll back one)

    with open(restore_path) as f:
        restore_config = f.read()

    restore_lines = [
        l for l in restore_config.splitlines() if l.strip() and not l.startswith("!") and not l.startswith("Building")
    ]

    fmt.header(f"Config Restore: {label}", breadcrumb="FREQ > Net > Config")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Source:{fmt.C.RESET}  {os.path.basename(restore_path)}")
    fmt.line(f"{fmt.C.BOLD}Target:{fmt.C.RESET}  {label} ({ip})")
    fmt.line(f"{fmt.C.BOLD}Lines:{fmt.C.RESET}   {len(restore_lines)}")
    fmt.blank()

    # Backup current config first
    fmt.step_start("Backing up current config before restore")
    current = deployer.get_config(ip, cfg)
    if current:
        ts = time.strftime("%Y%m%d-%H%M%S")
        pre_restore = os.path.join(_config_dir(cfg), f"{label}-{ts}-pre-restore.conf")
        with open(pre_restore, "w") as f:
            f.write(current)
        fmt.step_ok(f"Saved to {os.path.basename(pre_restore)}")
    else:
        fmt.step_warn("Could not backup current config — proceeding anyway")

    # Push restore config
    fmt.step_start("Pushing config to device")
    if deployer.push_config(ip, cfg, restore_lines):
        fmt.step_ok("Config pushed")
    else:
        fmt.step_fail("Failed to push config")
        fmt.footer()
        return 1

    fmt.step_start("Saving to startup config")
    if deployer.save_config(ip, cfg):
        fmt.step_ok("Saved")
    else:
        fmt.step_warn("Save failed — config may not persist across reboot")

    fmt.blank()
    fmt.success(f"Restored {label} to {os.path.basename(restore_path)}")
    logger.info("config_restore", target=label, ip=ip, source=os.path.basename(restore_path))
    fmt.footer()
    return 0
