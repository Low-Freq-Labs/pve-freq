"""Storage management for FREQ — TrueNAS, ZFS, fleet shares.

Domain: freq store <action>
What: Manage TrueNAS via midclt SSH, direct ZFS on any fleet host,
      audit NFS/SMB shares across the fleet. Graduated from
      infrastructure.py _device_cmd() for TrueNAS.
Replaces: TrueNAS WebUI, manual SSH to NAS boxes, zfs commands
Architecture:
    - TrueNAS: SSH with midclt call commands (no REST API dependency)
    - ZFS: SSH to any fleet host running ZFS (PVE nodes, NAS, Linux)
    - Shares: SSH fleet-wide to discover NFS exports and SMB shares
    - Data stored in conf/storage/
Design decisions:
    - midclt SSH, not REST API. Works on TrueNAS CORE and SCALE.
    - ZFS commands work on any host — not TrueNAS-specific.
    - Share audit discovers what's exported, not just what's mounted.
"""
import json
import os
import re
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run
from freq.core import log as logger


# ---------------------------------------------------------------------------
# SSH Helpers
# ---------------------------------------------------------------------------

TRUENAS_TIMEOUT = 30


def _nas_ssh(ip, cmd, cfg, timeout=TRUENAS_TIMEOUT):
    """Run a command on TrueNAS via SSH."""
    r = ssh_run(
        host=ip, command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="truenas", use_sudo=True,
    )
    return r.stdout or "", r.returncode == 0


def _zfs_ssh(ip, cmd, cfg, timeout=15):
    """Run a ZFS command on any fleet host."""
    r = ssh_run(
        host=ip, command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="linux", use_sudo=True,
    )
    return r.stdout or "", r.returncode == 0


def _get_nas_ip(cfg):
    """Get TrueNAS IP."""
    if cfg.truenas_ip:
        return cfg.truenas_ip
    for h in cfg.hosts:
        if h.htype == "truenas":
            return h.ip
    return None


def _storage_dir(cfg):
    """Return storage data directory."""
    path = os.path.join(cfg.conf_dir, "storage")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Commands — TrueNAS
# ---------------------------------------------------------------------------

def cmd_store_status(cfg: FreqConfig, pack, args) -> int:
    """Show TrueNAS system status."""
    ip = _get_nas_ip(cfg)
    if not ip:
        fmt.error("No TrueNAS configured. Set truenas_ip in freq.toml")
        return 1

    fmt.header("TrueNAS Status", breadcrumb="FREQ > Storage")
    fmt.blank()

    out, ok = _nas_ssh(ip, "midclt call system.info 2>/dev/null", cfg)
    if ok and out.strip():
        try:
            info = json.loads(out)
            fmt.line(f"{fmt.C.BOLD}Hostname:{fmt.C.RESET}  {info.get('hostname', '?')}")
            fmt.line(f"{fmt.C.BOLD}Version:{fmt.C.RESET}   {info.get('version', '?')}")
            fmt.line(f"{fmt.C.BOLD}Uptime:{fmt.C.RESET}    {info.get('uptime', '?')}")
            fmt.blank()
        except json.JSONDecodeError:
            fmt.line(f"  {fmt.C.DIM}{out.strip()[:200]}{fmt.C.RESET}")
    else:
        fmt.warn(f"Cannot reach TrueNAS at {ip}")
        fmt.footer()
        return 1

    # Pool status
    pool_out, pool_ok = _nas_ssh(ip, "zpool list 2>/dev/null", cfg)
    if pool_ok and pool_out.strip():
        fmt.line(f"{fmt.C.BOLD}ZFS Pools:{fmt.C.RESET}")
        for line in pool_out.strip().splitlines():
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        fmt.blank()

    # Health
    health_out, health_ok = _nas_ssh(ip, "zpool status -x 2>/dev/null", cfg)
    if health_ok:
        if "all pools are healthy" in health_out:
            fmt.success("All pools healthy")
        else:
            fmt.warn("Pool health issue detected")
            for line in health_out.strip().splitlines()[:5]:
                fmt.line(f"  {fmt.C.RED}{line}{fmt.C.RESET}")

    fmt.blank()
    logger.info("store_status", ip=ip)
    fmt.footer()
    return 0


def cmd_store_pools(cfg: FreqConfig, pack, args) -> int:
    """Show ZFS pool details."""
    target = getattr(args, "target", None)
    ip = _resolve_storage_target(target, cfg)
    if not ip:
        fmt.error("No storage target")
        return 1

    fmt.header("ZFS Pools", breadcrumb="FREQ > Storage")
    fmt.blank()

    out, ok = _zfs_ssh(ip, "zpool list -o name,size,alloc,free,cap,health 2>/dev/null", cfg)
    if ok and out.strip():
        for line in out.strip().splitlines():
            if "HEALTH" in line:
                fmt.line(f"  {fmt.C.BOLD}{line}{fmt.C.RESET}")
            elif "ONLINE" in line:
                fmt.line(f"  {fmt.C.GREEN}{line}{fmt.C.RESET}")
            elif "DEGRADED" in line or "FAULTED" in line:
                fmt.line(f"  {fmt.C.RED}{line}{fmt.C.RESET}")
            else:
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    else:
        fmt.warn("No ZFS pools found or zpool not available")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_store_datasets(cfg: FreqConfig, pack, args) -> int:
    """Show ZFS datasets."""
    target = getattr(args, "target", None)
    ip = _resolve_storage_target(target, cfg)
    if not ip:
        fmt.error("No storage target")
        return 1

    fmt.header("ZFS Datasets", breadcrumb="FREQ > Storage")
    fmt.blank()

    out, ok = _zfs_ssh(ip, "zfs list -o name,used,avail,refer,mountpoint 2>/dev/null | head -30", cfg)
    if ok and out.strip():
        lines = out.strip().splitlines()
        if lines:
            fmt.line(f"  {fmt.C.BOLD}{lines[0]}{fmt.C.RESET}")
            for line in lines[1:]:
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    else:
        fmt.warn("No ZFS datasets found")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_store_snapshots(cfg: FreqConfig, pack, args) -> int:
    """Show ZFS snapshots."""
    target = getattr(args, "target", None)
    ip = _resolve_storage_target(target, cfg)
    if not ip:
        fmt.error("No storage target")
        return 1

    fmt.header("ZFS Snapshots", breadcrumb="FREQ > Storage")
    fmt.blank()

    out, ok = _zfs_ssh(ip, "zfs list -t snapshot -o name,used,creation 2>/dev/null | head -30", cfg)
    if ok and out.strip():
        lines = out.strip().splitlines()
        if lines:
            fmt.line(f"  {fmt.C.BOLD}{lines[0]}{fmt.C.RESET}")
            for line in lines[1:]:
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        fmt.blank()
        fmt.info(f"{len(lines) - 1} snapshot(s) shown")
    else:
        fmt.info("No ZFS snapshots found")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_store_smart(cfg: FreqConfig, pack, args) -> int:
    """Show SMART health for drives."""
    ip = _get_nas_ip(cfg)
    if not ip:
        fmt.error("No TrueNAS configured")
        return 1

    fmt.header("SMART Health", breadcrumb="FREQ > Storage")
    fmt.blank()

    out, ok = _nas_ssh(ip, "midclt call disk.query '[]' 2>/dev/null", cfg)
    if ok and out.strip():
        try:
            disks = json.loads(out)
            fmt.table_header(("Name", 8), ("Serial", 22), ("Size", 10), ("Type", 8), ("Temp", 6))
            for d in disks:
                name = d.get("name", "?")
                serial = d.get("serial", "?")
                size = d.get("size", 0)
                size_gb = f"{size // (1024**3)}G" if size else "?"
                dtype = d.get("type", "?")
                temp = d.get("temperature", "")
                temp_str = f"{temp}°" if temp else "—"
                fmt.table_row(
                    (name, 8), (serial, 22), (size_gb, 10),
                    (dtype, 8), (temp_str, 6),
                )
            fmt.blank()
            fmt.info(f"{len(disks)} drive(s)")
        except json.JSONDecodeError:
            fmt.warn("Could not parse disk data")
    else:
        fmt.warn("Could not retrieve disk info (midclt not available)")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_store_shares(cfg: FreqConfig, pack, args) -> int:
    """List NFS/SMB shares on TrueNAS."""
    ip = _get_nas_ip(cfg)
    if not ip:
        fmt.error("No TrueNAS configured")
        return 1

    fmt.header("Shares", breadcrumb="FREQ > Storage")
    fmt.blank()

    # SMB shares
    smb_out, smb_ok = _nas_ssh(ip, "midclt call sharing.smb.query '[]' 2>/dev/null", cfg)
    if smb_ok and smb_out.strip():
        try:
            shares = json.loads(smb_out)
            if shares:
                fmt.line(f"{fmt.C.BOLD}SMB Shares ({len(shares)}):{fmt.C.RESET}")
                for s in shares:
                    enabled = "enabled" if s.get("enabled") else "disabled"
                    color = fmt.C.GREEN if s.get("enabled") else fmt.C.DIM
                    fmt.line(f"  {color}{s.get('name', '?'):<20}{fmt.C.RESET} "
                             f"{s.get('path', '?'):<30} {enabled}")
                fmt.blank()
        except json.JSONDecodeError:
            pass

    # NFS shares
    nfs_out, nfs_ok = _nas_ssh(ip, "midclt call sharing.nfs.query '[]' 2>/dev/null", cfg)
    if nfs_ok and nfs_out.strip():
        try:
            nfs_shares = json.loads(nfs_out)
            if nfs_shares:
                fmt.line(f"{fmt.C.BOLD}NFS Exports ({len(nfs_shares)}):{fmt.C.RESET}")
                for s in nfs_shares:
                    paths = ", ".join(s.get("paths", []))
                    enabled = "enabled" if s.get("enabled") else "disabled"
                    color = fmt.C.GREEN if s.get("enabled") else fmt.C.DIM
                    fmt.line(f"  {color}{paths:<40}{fmt.C.RESET} {enabled}")
                fmt.blank()
        except json.JSONDecodeError:
            pass

    fmt.footer()
    return 0


def cmd_store_alerts(cfg: FreqConfig, pack, args) -> int:
    """Show TrueNAS alerts."""
    ip = _get_nas_ip(cfg)
    if not ip:
        fmt.error("No TrueNAS configured")
        return 1

    fmt.header("TrueNAS Alerts", breadcrumb="FREQ > Storage")
    fmt.blank()

    out, ok = _nas_ssh(ip, "midclt call alert.list 2>/dev/null", cfg)
    if ok and out.strip():
        try:
            alerts = json.loads(out)
            if alerts:
                for a in alerts:
                    level = a.get("level", "INFO")
                    color = fmt.C.RED if level in ("CRITICAL", "ERROR") else fmt.C.YELLOW if level == "WARNING" else fmt.C.DIM
                    fmt.line(f"  {color}[{level}]{fmt.C.RESET} {a.get('formatted', a.get('text', '?'))}")
                fmt.blank()
                fmt.info(f"{len(alerts)} alert(s)")
            else:
                fmt.success("No active alerts")
        except json.JSONDecodeError:
            fmt.warn("Could not parse alerts")
    else:
        fmt.warn("Could not retrieve alerts")

    fmt.blank()
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_storage_target(target, cfg):
    """Resolve target to IP — defaults to TrueNAS."""
    if target:
        for h in cfg.hosts:
            if h.label == target or h.ip == target:
                return h.ip
        return target
    return _get_nas_ip(cfg)
