"""File integrity monitoring for FREQ.

Domain: freq secure fim <action>
What: Track file hashes on fleet hosts. Detect unauthorized changes.
      Baseline critical system files, alert on modifications.
Replaces: OSSEC, AIDE, Tripwire
Architecture:
    - Baseline: SSH to hosts, hash critical files, store in conf/fim/
    - Check: re-hash and compare against baseline
    - Paths: /etc/passwd, /etc/shadow, /etc/ssh/sshd_config, etc.
Design decisions:
    - sha256sum via SSH — no agent needed.
    - Critical paths are hardcoded sensible defaults, extensible via config.
    - Per-host baselines stored as JSON.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many
from freq.core import log as logger


FIM_DIR = "fim"

DEFAULT_PATHS = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/group",
    "/etc/sudoers",
    "/etc/ssh/sshd_config",
    "/etc/hosts",
    "/etc/fstab",
    "/etc/crontab",
    "/etc/resolv.conf",
]


def _fim_dir(cfg):
    path = os.path.join(cfg.conf_dir, FIM_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_baseline(cfg, host_label):
    filepath = os.path.join(_fim_dir(cfg), f"{host_label}-baseline.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return None


def _save_baseline(cfg, host_label, data):
    filepath = os.path.join(_fim_dir(cfg), f"{host_label}-baseline.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def cmd_fim_baseline(cfg: FreqConfig, pack, args) -> int:
    """Create file integrity baseline for fleet hosts."""
    fmt.header("FIM Baseline", breadcrumb="FREQ > Secure > FIM")
    fmt.blank()

    paths_str = " ".join(DEFAULT_PATHS)
    cmd = f"sha256sum {paths_str} 2>/dev/null"

    linux_hosts = [h for h in cfg.hosts if h.htype in ("linux", "pve", "docker")]
    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in linux_hosts]
    results = run_many(
        hosts=hosts_data,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=10,
    )

    ok_count = 0
    for h in linux_hosts:
        r = results.get(h.ip)
        if r and r.returncode == 0:
            hashes = _parse_hashes(r.stdout)
            baseline = {
                "host": h.label,
                "ip": h.ip,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "files": hashes,
            }
            _save_baseline(cfg, h.label, baseline)
            fmt.step_ok(f"{h.label}: {len(hashes)} files baselined")
            ok_count += 1
        else:
            fmt.step_fail(f"{h.label}: unreachable")

    fmt.blank()
    fmt.info(f"{ok_count}/{len(linux_hosts)} hosts baselined")
    logger.info("fim_baseline", hosts=ok_count)
    fmt.footer()
    return 0


def cmd_fim_check(cfg: FreqConfig, pack, args) -> int:
    """Check file integrity against baseline."""
    fmt.header("FIM Check", breadcrumb="FREQ > Secure > FIM")
    fmt.blank()

    paths_str = " ".join(DEFAULT_PATHS)
    cmd = f"sha256sum {paths_str} 2>/dev/null"

    linux_hosts = [h for h in cfg.hosts if h.htype in ("linux", "pve", "docker")]
    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in linux_hosts]
    results = run_many(
        hosts=hosts_data,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=10,
    )

    total_changes = 0
    for h in linux_hosts:
        baseline = _load_baseline(cfg, h.label)
        if not baseline:
            fmt.step_warn(f"{h.label}: no baseline (run freq secure fim baseline)")
            continue

        r = results.get(h.ip)
        if not r or r.returncode != 0:
            fmt.step_fail(f"{h.label}: unreachable")
            continue

        current = _parse_hashes(r.stdout)
        baseline_files = baseline.get("files", {})
        changes = []

        for path, hash_val in current.items():
            if path in baseline_files and baseline_files[path] != hash_val:
                changes.append(("modified", path))
        for path in baseline_files:
            if path not in current:
                changes.append(("removed", path))
        for path in current:
            if path not in baseline_files:
                changes.append(("added", path))

        if changes:
            fmt.step_warn(f"{h.label}: {len(changes)} change(s)")
            for change_type, path in changes:
                color = fmt.C.RED if change_type == "modified" else fmt.C.YELLOW
                fmt.line(f"    {color}{change_type:<10}{fmt.C.RESET} {path}")
            total_changes += len(changes)
        else:
            fmt.step_ok(f"{h.label}: no changes")

    fmt.blank()
    if total_changes > 0:
        fmt.warn(f"{total_changes} file change(s) detected across fleet")
    else:
        fmt.success("All files match baseline")

    logger.info("fim_check", changes=total_changes)
    fmt.footer()
    return 0


def cmd_fim_status(cfg: FreqConfig, pack, args) -> int:
    """Show FIM baseline status for all hosts."""
    fmt.header("FIM Status", breadcrumb="FREQ > Secure > FIM")
    fmt.blank()

    path = _fim_dir(cfg)
    baselines = [f for f in os.listdir(path) if f.endswith("-baseline.json")]

    if not baselines:
        fmt.warn("No baselines. Run: freq secure fim baseline")
        fmt.footer()
        return 0

    for bl_file in sorted(baselines):
        filepath = os.path.join(path, bl_file)
        with open(filepath) as f:
            data = json.load(f)
        host = data.get("host", bl_file)
        created = data.get("created", "?")
        files = len(data.get("files", {}))
        fmt.line(f"  {fmt.C.CYAN}{host:<14}{fmt.C.RESET} {files} files  baselined {created}")

    fmt.blank()
    fmt.info(f"{len(baselines)} baseline(s)")
    fmt.footer()
    return 0


def _parse_hashes(text):
    result = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            result[parts[1]] = parts[0]
    return result
