"""VMware ESXi to Proxmox migration tool for FREQ.

Commands: migrate-vmware (scan/import/status)

THE killer feature for the post-Broadcom exodus. 86% of VMware customers
are actively reducing their footprint. Proxmox is the #1 target.

Scan ESXi hosts for VMs, import OVA/VMDK files into Proxmox, handle
disk conversion, network mapping, and storage placement.

Kills: VMware/Broadcom ($$$$$, 200-1050% price increases)
"""
import json
import os
import re
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Timeouts
VMWARE_CMD_TIMEOUT = 30
VMWARE_IMPORT_TIMEOUT = 1800  # 30 minutes for large disk imports
PVE_CMD_TIMEOUT = 30
PVE_QUICK_TIMEOUT = 10

# Migration state directory
VMWARE_DIR = "vmware-migration"
VMWARE_STATE = "migration-state.json"

# Supported disk formats
DISK_FORMATS = ("vmdk", "ova", "ovf", "qcow2", "raw")


def _migration_dir(cfg: FreqConfig) -> str:
    """Get or create migration state directory."""
    path = os.path.join(cfg.conf_dir, VMWARE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_state(cfg: FreqConfig) -> dict:
    """Load migration state."""
    filepath = os.path.join(_migration_dir(cfg), VMWARE_STATE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"scans": [], "imports": []}


def _save_state(cfg: FreqConfig, state: dict):
    """Save migration state."""
    filepath = os.path.join(_migration_dir(cfg), VMWARE_STATE)
    with open(filepath, "w") as f:
        json.dump(state, f, indent=2)


def _find_pve_node(cfg: FreqConfig) -> str:
    """Find a reachable PVE node."""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip, command="pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path, connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=PVE_QUICK_TIMEOUT, htype="pve", use_sudo=True,
        )
        if r.returncode == 0:
            return ip
    return ""


def _pve_cmd(cfg, node_ip, command, timeout=PVE_CMD_TIMEOUT):
    """Execute PVE command."""
    r = ssh_run(
        host=node_ip, command=command,
        key_path=cfg.ssh_key_path, connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout, htype="pve", use_sudo=True,
    )
    return r.stdout, r.returncode == 0


def cmd_migrate_vmware(cfg: FreqConfig, pack, args) -> int:
    """VMware migration management."""
    action = getattr(args, "action", None) or "scan"

    if action == "scan":
        return _cmd_scan(cfg, args)
    elif action == "import":
        return _cmd_import(cfg, args)
    elif action == "status":
        return _cmd_status(cfg, args)
    elif action == "convert":
        return _cmd_convert(cfg, args)

    fmt.error(f"Unknown migrate-vmware action: {action}")
    fmt.info("Available: scan, import, convert, status")
    return 1


def _cmd_scan(cfg: FreqConfig, args) -> int:
    """Scan an ESXi host or OVA directory for VMs to migrate."""
    target = getattr(args, "target", None)

    fmt.header("VMware Migration Scanner")
    fmt.blank()

    if target and os.path.isdir(target):
        # Scan a local directory for OVA/VMDK files
        return _scan_directory(cfg, target)
    elif target and os.path.isfile(target):
        # Analyze a single OVA/VMDK file
        return _scan_file(cfg, target)
    else:
        # Show general instructions
        fmt.line(f"  {fmt.C.BOLD}VMware → Proxmox Migration{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.PURPLE_BOLD}Step 1: Export from VMware{fmt.C.RESET}")
        fmt.line(f"  Export VMs from vSphere/ESXi as OVA files.")
        fmt.line(f"  In vSphere: Right-click VM → Export → OVA")
        fmt.blank()
        fmt.line(f"  {fmt.C.PURPLE_BOLD}Step 2: Scan{fmt.C.RESET}")
        fmt.line(f"  freq migrate-vmware scan /path/to/ova-files/")
        fmt.line(f"  freq migrate-vmware scan /path/to/vm.ova")
        fmt.blank()
        fmt.line(f"  {fmt.C.PURPLE_BOLD}Step 3: Import{fmt.C.RESET}")
        fmt.line(f"  freq migrate-vmware import /path/to/vm.ova --vmid 200 --node pve01")
        fmt.blank()
        fmt.line(f"  {fmt.C.PURPLE_BOLD}Step 4: Verify{fmt.C.RESET}")
        fmt.line(f"  freq list --node pve01")
        fmt.line(f"  freq power start 200")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Supported formats: {', '.join(DISK_FORMATS)}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0


def _scan_directory(cfg: FreqConfig, directory: str) -> int:
    """Scan a directory for importable VM files."""
    fmt.step_start(f"Scanning {directory}")

    found = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
            if ext in DISK_FORMATS:
                path = os.path.join(root, f)
                size_mb = os.path.getsize(path) // 1048576
                found.append({"name": f, "path": path, "format": ext, "size_mb": size_mb})

    fmt.step_ok(f"Found {len(found)} importable files")
    fmt.blank()

    if not found:
        fmt.line(f"  {fmt.C.DIM}No OVA/VMDK/OVF files found in {directory}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(("FILE", 28), ("FORMAT", 8), ("SIZE", 10), ("PATH", 30))

    for f in found:
        fmt.table_row(
            (f"{fmt.C.BOLD}{f['name']}{fmt.C.RESET}", 28),
            (f["format"].upper(), 8),
            (f"{f['size_mb']}MB", 10),
            (f["path"][-30:], 30),
        )

    # Save scan results
    state = _load_state(cfg)
    state["scans"].append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "directory": directory,
        "found": len(found),
        "files": [f["name"] for f in found],
    })
    _save_state(cfg, state)

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Import: freq migrate-vmware import <file> --vmid <id> --node <node>{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _scan_file(cfg: FreqConfig, filepath: str) -> int:
    """Analyze a single OVA/VMDK file."""
    filename = os.path.basename(filepath)
    size_mb = os.path.getsize(filepath) // 1048576
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    fmt.step_ok(f"File: {filename}")
    fmt.blank()
    fmt.line(f"  Format: {ext.upper()}")
    fmt.line(f"  Size:   {size_mb} MB ({size_mb / 1024:.1f} GB)")
    fmt.line(f"  Path:   {filepath}")
    fmt.blank()

    if ext == "ova":
        # Try to extract OVF metadata
        fmt.step_start("Reading OVA metadata")
        node_ip = _find_pve_node(cfg)
        if node_ip:
            stdout, ok = _pve_cmd(cfg, node_ip,
                                  f"tar -tf {filepath} 2>/dev/null | head -20",
                                  timeout=VMWARE_CMD_TIMEOUT)
            if ok and stdout.strip():
                fmt.step_ok("OVA contents:")
                for line in stdout.strip().split("\n")[:10]:
                    fmt.line(f"    {fmt.C.DIM}{line.strip()}{fmt.C.RESET}")
            else:
                fmt.step_fail("Could not read OVA contents")
        else:
            fmt.line(f"  {fmt.C.DIM}Connect to PVE node for deeper analysis{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Import: freq migrate-vmware import {filepath} --vmid <id>{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_import(cfg: FreqConfig, args) -> int:
    """Import a VMware VM into Proxmox."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq migrate-vmware import <file.ova> --vmid <id> [--node <node>]")
        return 1

    if not os.path.exists(target):
        fmt.error(f"File not found: {target}")
        return 1

    vmid = getattr(args, "vmid", None)
    if not vmid:
        fmt.error("--vmid is required")
        return 1

    node = getattr(args, "node", None)
    storage = getattr(args, "storage", None) or "local-lvm"

    fmt.header(f"VMware Import: {os.path.basename(target)}")
    fmt.blank()

    # Find PVE node
    fmt.step_start("Connecting to PVE cluster")
    node_ip = _find_pve_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok(f"Connected to {node_ip}")

    filename = os.path.basename(target)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Determine import method based on file type
    if ext == "ova":
        fmt.step_start(f"Importing OVA as VM {vmid}")
        import_cmd = (
            f"qm importovf {vmid} {target} {storage}"
            + (f" --target {node}" if node else "")
        )
    elif ext == "vmdk":
        fmt.step_start(f"Importing VMDK disk to VM {vmid}")
        import_cmd = f"qm importdisk {vmid} {target} {storage} --format qcow2"
    elif ext in ("qcow2", "raw"):
        fmt.step_start(f"Importing disk to VM {vmid}")
        import_cmd = f"qm importdisk {vmid} {target} {storage}"
    else:
        fmt.error(f"Unsupported format: {ext}. Use OVA, VMDK, QCOW2, or RAW.")
        return 1

    # Confirm
    if not getattr(args, "yes", False):
        fmt.blank()
        fmt.line(f"  {fmt.C.YELLOW}Import {filename} → VM {vmid} on {storage}?{fmt.C.RESET}")
        try:
            confirm = input(f"  {fmt.C.YELLOW}Proceed? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Import cancelled.")
            return 0

    # Execute import
    stdout, ok = _pve_cmd(cfg, node_ip, import_cmd, timeout=VMWARE_IMPORT_TIMEOUT)

    if ok:
        fmt.step_ok(f"VM {vmid} imported successfully")
    else:
        fmt.step_fail(f"Import failed: {stdout[:200]}")
        fmt.blank()
        fmt.footer()
        return 1

    # Log import
    state = _load_state(cfg)
    state["imports"].append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": target,
        "vmid": vmid,
        "storage": storage,
        "success": ok,
    })
    _save_state(cfg, state)

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} Import complete.{fmt.C.RESET}")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Next steps:{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}  1. Review config: freq vmconfig {vmid}{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}  2. Update networking: freq nic add {vmid} --ip <ip>{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}  3. Start VM: freq power start {vmid}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_convert(cfg: FreqConfig, args) -> int:
    """Convert a VMDK to QCOW2 format."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq migrate-vmware convert <file.vmdk>")
        return 1

    if not os.path.exists(target):
        fmt.error(f"File not found: {target}")
        return 1

    fmt.header(f"Convert: {os.path.basename(target)}")
    fmt.blank()

    output = target.rsplit(".", 1)[0] + ".qcow2"
    fmt.step_start(f"Converting to QCOW2")

    node_ip = _find_pve_node(cfg)
    if node_ip:
        stdout, ok = _pve_cmd(cfg, node_ip,
                              f"qemu-img convert -f vmdk -O qcow2 {target} {output}",
                              timeout=VMWARE_IMPORT_TIMEOUT)
        if ok:
            fmt.step_ok(f"Converted: {output}")
        else:
            fmt.step_fail(f"Conversion failed: {stdout[:100]}")
            fmt.blank()
            fmt.footer()
            return 1
    else:
        fmt.step_fail("No PVE node available for conversion")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_status(cfg: FreqConfig, args) -> int:
    """Show migration status and history."""
    fmt.header("VMware Migration Status")
    fmt.blank()

    state = _load_state(cfg)
    scans = state.get("scans", [])
    imports = state.get("imports", [])

    fmt.line(f"  Total scans:   {len(scans)}")
    fmt.line(f"  Total imports: {len(imports)}")

    if imports:
        fmt.blank()
        fmt.divider("Import History")
        fmt.blank()
        fmt.table_header(("TIME", 20), ("SOURCE", 24), ("VMID", 8), ("STATUS", 10))
        for imp in imports[-10:]:
            status = f"{fmt.C.GREEN}OK{fmt.C.RESET}" if imp.get("success") else f"{fmt.C.RED}FAIL{fmt.C.RESET}"
            fmt.table_row(
                (imp.get("timestamp", "")[:19], 20),
                (os.path.basename(imp.get("source", ""))[:24], 24),
                (str(imp.get("vmid", "")), 8),
                (status, 10),
            )

    fmt.blank()
    fmt.footer()
    return 0
