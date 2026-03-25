"""VM lifecycle management for FREQ.

Commands: create, clone, destroy, resize, snapshot, migrate

Every operation goes through the PVE API via SSH + qm/pvesh commands.
Safety gates enforce protected VMID ranges and confirmation prompts.
"""
import json
import shlex
import subprocess
import threading
import time

from freq.core import fmt
from freq.core import validate
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

class _ProgressTicker:
    """Prints elapsed time every N seconds during long operations."""

    def __init__(self, label, interval=5):
        self._label = label
        self._interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._start = None

    def __enter__(self):
        self._start = time.monotonic()
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=1)

    def _tick(self):
        while not self._stop.wait(self._interval):
            elapsed = int(time.monotonic() - self._start)
            fmt.line("  {d}{l} ({e}s elapsed){z}".format(
                d=fmt.C.DIM, l=self._label, e=elapsed, z=fmt.C.RESET))


# VM operation timeouts
VM_CMD_TIMEOUT = 60
VM_QUICK_TIMEOUT = 10
VM_CONFIG_TIMEOUT = 30
VM_CREATE_TIMEOUT = 120
VM_CLONE_TIMEOUT = 300
VM_MIGRATE_TIMEOUT = 1800  # 30 min — large disks over 1Gbps need time


def _pve_cmd(cfg: FreqConfig, node_ip: str, command: str, timeout: int = VM_CMD_TIMEOUT) -> tuple:
    """Execute command on PVE node via SSH + sudo."""
    r = ssh_run(
        host=node_ip, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pve", use_sudo=True,
    )
    return r.stdout, r.returncode == 0


def _pve_unreachable_hint(cfg):
    """Show remediation hints when no PVE node is reachable."""
    if cfg.pve_nodes:
        fmt.info("Configured nodes: {}".format(", ".join(cfg.pve_nodes)))
    else:
        fmt.info("No PVE nodes configured. Check conf/freq.toml [pve]")
    fmt.info("Try: freq doctor")


def _find_node(cfg: FreqConfig) -> str:
    """Find first reachable PVE node."""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip, command="sudo pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path, connect_timeout=3, command_timeout=VM_QUICK_TIMEOUT,
            htype="pve", use_sudo=False,
        )
        if r.returncode == 0:
            return ip
    return ""


def _find_vm_node(cfg: FreqConfig, vmid: int) -> str:
    """Find which PVE node hosts a specific VMID."""
    node_ip = _find_node(cfg)
    if not node_ip:
        return ""

    stdout, ok = _pve_cmd(cfg, node_ip,
        f"pvesh get /cluster/resources --type vm --output-format json")
    if not ok:
        return ""

    try:
        vms = json.loads(stdout)
        for v in vms:
            if v.get("vmid") == vmid:
                # Find the IP for this node name
                node_name = v.get("node", "")
                for i, name in enumerate(cfg.pve_node_names):
                    if name == node_name and i < len(cfg.pve_nodes):
                        return cfg.pve_nodes[i]
                # Fallback: return any reachable node (cluster-aware)
                return node_ip
    except json.JSONDecodeError:
        pass
    return ""


def _next_vmid(cfg: FreqConfig, node_ip: str) -> int:
    """Get the next available VMID from the cluster."""
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
    if ok and stdout.strip().isdigit():
        return int(stdout.strip())
    return 0


def _safety_check(cfg: FreqConfig, vmid: int, operation: str) -> bool:
    """Check if a VMID is safe to operate on. Returns True if safe."""
    if validate.is_protected_vmid(vmid, cfg.protected_vmids, cfg.protected_ranges):
        fmt.error(f"VM {vmid} is PROTECTED. Cannot {operation}.")
        fmt.info(f"Protected VMIDs: {cfg.protected_vmids}")
        fmt.info(f"Protected ranges: {cfg.protected_ranges}")
        return False
    return True


def cmd_create(cfg: FreqConfig, pack, args) -> int:
    """Create a new VM."""
    fmt.header("Create VM")
    fmt.blank()

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        fmt.blank()
        fmt.footer()
        return 1

    # Get parameters
    name = getattr(args, "name", None)
    image = getattr(args, "image", None)
    node = getattr(args, "node", None)
    cores = getattr(args, "cores", None) or cfg.vm_default_cores
    ram = getattr(args, "ram", None) or cfg.vm_default_ram
    disk = getattr(args, "disk", None) or cfg.vm_default_disk
    vmid = getattr(args, "vmid", None)

    if not name:
        try:
            name = input(f"  {fmt.C.CYAN}VM name:{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if not name:
            fmt.error("VM name is required.")
            return 1

    if not validate.shell_safe_name(name):
        fmt.error("Invalid VM name: {}".format(name))
        fmt.info("Names: alphanumeric, hyphens, underscores, dots. Max 63 chars.")
        return 1

    # Get next VMID if not specified
    if not vmid:
        vmid = _next_vmid(cfg, node_ip)
        if not vmid:
            fmt.error("Cannot get next VMID from cluster.")
            return 1

    # Safety check
    if not _safety_check(cfg, vmid, "create"):
        return 1

    # Pick storage from config, warn if falling back to default
    storage = "local-lvm"
    for node_name, store_info in cfg.pve_storage.items():
        if store_info.get("pool"):
            storage = store_info["pool"]
            break
    else:
        if not cfg.pve_storage:
            logger.warn("no pve_storage configured — falling back to 'local-lvm'")
            fmt.warn("No storage configured in freq.toml — using 'local-lvm' default")

    # Show plan
    fmt.line(f"  {fmt.C.BOLD}Creating VM:{fmt.C.RESET}")
    fmt.line(f"    VMID:    {fmt.C.CYAN}{vmid}{fmt.C.RESET}")
    fmt.line(f"    Name:    {fmt.C.CYAN}{name}{fmt.C.RESET}")
    fmt.line(f"    Cores:   {cores}")
    fmt.line(f"    RAM:     {ram}MB")
    fmt.line(f"    Disk:    {disk}GB")
    fmt.line(f"    Storage: {storage}")
    fmt.line(f"    Node:    {node_ip}")
    fmt.blank()

    # Confirm unless --yes
    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Create this VM? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Create
    fmt.step_start(f"Creating VM {vmid}")
    create_cmd = (
        f"qm create {vmid} --name {name} "
        f"--cores {cores} --memory {ram} "
        f"--cpu {cfg.vm_cpu} --machine {cfg.vm_machine} "
        f"--net0 virtio,bridge={cfg.nic_bridge} "
        f"--scsihw {cfg.vm_scsihw}"
    )

    stdout, ok = _pve_cmd(cfg, node_ip, create_cmd, timeout=VM_CREATE_TIMEOUT)
    if ok:
        fmt.step_ok(f"VM {vmid} '{name}' created")
        logger.info(f"VM created: {vmid} {name}", node=node_ip)
        return 0
    else:
        fmt.step_fail(f"Create failed: {stdout}")
        return 1


def cmd_clone(cfg: FreqConfig, pack, args) -> int:
    """Clone a VM with optional network configuration via disk mount.

    Enhanced clone: --ip and --vlan flags trigger post-clone disk mount to
    configure /etc/network/interfaces, hostname, machine-id, and SSH keys
    before first boot. One command, zero manual steps.
    """
    source = getattr(args, "source", None)
    if not source:
        fmt.error("Usage: freq clone <source_vmid> [--name <name>] [--vmid <new_vmid>] [--ip <ip>] [--vlan <vlan>]")
        return 1

    try:
        src_vmid = int(source)
    except ValueError:
        fmt.error(f"Invalid source VMID: {source}")
        return 1

    fmt.header(f"Clone VM {src_vmid}")
    fmt.blank()

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        fmt.blank()
        fmt.footer()
        return 1

    new_name = getattr(args, "name", None) or f"clone-of-{src_vmid}"
    new_vmid = getattr(args, "vmid", None)
    ip_addr = getattr(args, "ip", None)
    vlan = getattr(args, "vlan", None)

    if not validate.shell_safe_name(new_name):
        fmt.error("Invalid VM name: {}".format(new_name))
        fmt.info("Names: alphanumeric, hyphens, underscores, dots. Max 63 chars.")
        return 1
    if ip_addr and not validate.ip(ip_addr.split("/")[0]):
        fmt.error("Invalid IP address: {}".format(ip_addr))
        return 1
    if vlan and not validate.vlan_id(vlan):
        fmt.error("Invalid VLAN ID: {} (must be 0-4094)".format(vlan))
        return 1

    if not new_vmid:
        new_vmid = _next_vmid(cfg, node_ip)
        if not new_vmid:
            fmt.error("Cannot get next VMID.")
            return 1

    if not _safety_check(cfg, new_vmid, "clone into"):
        return 1

    fmt.line(f"  Source:  VM {src_vmid}")
    fmt.line(f"  Target:  VM {new_vmid} '{new_name}'")
    if ip_addr:
        fmt.line(f"  IP:      {ip_addr}")
    if vlan:
        fmt.line(f"  VLAN:    {vlan}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Clone? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Step 1: Full clone
    fmt.step_start(f"Cloning VM {src_vmid} to {new_vmid}")
    with _ProgressTicker("Cloning"):
        stdout, ok = _pve_cmd(cfg, node_ip,
            f"qm clone {src_vmid} {new_vmid} --name {new_name} --full", timeout=VM_CLONE_TIMEOUT)

    if not ok:
        fmt.step_fail(f"Clone failed: {stdout}")
        return 1
    fmt.step_ok(f"VM {new_vmid} cloned")

    # Step 2: Post-clone network config via disk mount (if --ip provided)
    if ip_addr:
        fmt.step_start("Configuring network via disk mount")

        # Find the disk path — get config to find storage volume
        config_out, _ = _pve_cmd(cfg, node_ip, f"qm config {new_vmid}")
        disk_path = ""
        for line in config_out.split("\n"):
            if line.startswith("scsi0:") or line.startswith("virtio0:"):
                # Format: scsi0: local-lvm:vm-VMID-disk-0,size=32G
                disk_ref = line.split(":", 1)[1].strip().split(",")[0]
                # Try to resolve ZFS/LVM path
                disk_path = f"/dev/zvol/{disk_ref.replace(':', '/')}" if ":" in disk_ref else ""
                break

        if disk_path:
            # Attempt disk mount approach
            mount_cmds = (
                f"mkdir -p /mnt/vm{new_vmid} && "
                f"mount {disk_path}-part1 /mnt/vm{new_vmid} 2>/dev/null || "
                f"mount {disk_path}p1 /mnt/vm{new_vmid} 2>/dev/null"
            )
            stdout, ok = _pve_cmd(cfg, node_ip, mount_cmds, timeout=VM_CONFIG_TIMEOUT)

            if ok:
                # Configure hostname (validated name + printf for safety)
                safe_name = shlex.quote(new_name)
                _pve_cmd(cfg, node_ip,
                         f"printf '%s\\n' {safe_name} > /mnt/vm{new_vmid}/etc/hostname")
                # Clear machine-id for regen
                _pve_cmd(cfg, node_ip,
                         f"truncate -s 0 /mnt/vm{new_vmid}/etc/machine-id")
                # Remove SSH host keys for regen
                _pve_cmd(cfg, node_ip,
                         f"rm -f /mnt/vm{new_vmid}/etc/ssh/ssh_host_*")
                # Update /etc/hosts
                _pve_cmd(cfg, node_ip,
                         f"sed -i 's/127.0.1.1.*/127.0.1.1\\t'{safe_name}'/' "
                         f"/mnt/vm{new_vmid}/etc/hosts")

                # Set static IP if interfaces file exists
                _pve_cmd(cfg, node_ip,
                         f"if [ -f /mnt/vm{new_vmid}/etc/network/interfaces ]; then "
                         f"  sed -i 's/address .*/address {ip_addr}/' "
                         f"  /mnt/vm{new_vmid}/etc/network/interfaces; fi")

                # Unmount
                _pve_cmd(cfg, node_ip, f"umount /mnt/vm{new_vmid}")
                fmt.step_ok(f"Network configured: {ip_addr}, hostname: {new_name}")
            else:
                # Fallback: use cloud-init
                fmt.step_fail("Disk mount failed, trying cloud-init")
                ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
                if "/" not in ip_addr:
                    logger.warn(f"no CIDR prefix on IP {ip_addr} — assuming /24")
                _pve_cmd(cfg, node_ip,
                         f"qm set {new_vmid} --ipconfig0 ip={ip_with_prefix},gw={cfg.vm_gateway}")
                fmt.step_ok(f"Cloud-init IP set: {ip_addr}")
        else:
            # No disk path found — use cloud-init
            ip_with_prefix = ip_addr if "/" in ip_addr else f"{ip_addr}/24"
            if "/" not in ip_addr:
                logger.warn(f"no CIDR prefix on IP {ip_addr} — assuming /24")
            _pve_cmd(cfg, node_ip,
                     f"qm set {new_vmid} --ipconfig0 ip={ip_with_prefix},gw={cfg.vm_gateway}")
            fmt.step_ok(f"Cloud-init IP set: {ip_addr}")

    # Step 3: Start if requested
    if ip_addr or getattr(args, "start", False):
        fmt.step_start(f"Starting VM {new_vmid}")
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm start {new_vmid}", timeout=VM_CMD_TIMEOUT)
        if ok:
            fmt.step_ok(f"VM {new_vmid} running")
        else:
            fmt.step_fail(f"Start failed: {stdout}")

    fmt.blank()
    logger.info(f"VM cloned: {src_vmid} -> {new_vmid} {new_name}", ip=ip_addr)
    fmt.footer()
    return 0


def cmd_destroy(cfg: FreqConfig, pack, args) -> int:
    """Destroy a VM with safety checks."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq destroy <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    fmt.header(f"Destroy VM {vmid}")
    fmt.blank()

    # Safety gate
    if not _safety_check(cfg, vmid, "destroy"):
        fmt.blank()
        fmt.footer()
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        fmt.blank()
        fmt.footer()
        return 1

    # Get VM info first
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
    if not ok:
        fmt.error(f"VM {vmid} not found.")
        fmt.blank()
        fmt.footer()
        return 1

    vm_name = "unknown"
    for line in stdout.split("\n"):
        if line.startswith("name:"):
            vm_name = line.split(":", 1)[1].strip()
            break

    fmt.line(f"  {fmt.C.RED}{fmt.C.BOLD}WARNING: This will permanently destroy VM {vmid} '{vm_name}'{fmt.C.RESET}")
    fmt.blank()

    # Dry-run stops here
    if getattr(args, "dry_run", False):
        fmt.info("Dry run — no changes made.")
        fmt.blank()
        fmt.footer()
        return 0

    # Double confirmation for destructive operations
    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.RED}Type the VMID to confirm destruction:{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != str(vmid):
            fmt.info("Cancelled. VMID did not match.")
            return 0

    # Stop first if running
    fmt.step_start(f"Stopping VM {vmid}")
    _pve_cmd(cfg, node_ip, f"qm stop {vmid}", timeout=VM_CMD_TIMEOUT)
    fmt.step_ok("Stopped (or already stopped)")

    # Destroy
    fmt.step_start(f"Destroying VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=VM_CREATE_TIMEOUT)

    if ok:
        fmt.step_ok(f"VM {vmid} '{vm_name}' destroyed")
        logger.info(f"VM destroyed: {vmid} {vm_name}")
    else:
        fmt.step_fail(f"Destroy failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def cmd_resize(cfg: FreqConfig, pack, args) -> int:
    """Resize a VM's CPU, RAM, or disk."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq resize <vmid> [--cores N] [--ram MB] [--disk GB]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    cores = getattr(args, "cores", None)
    ram = getattr(args, "ram", None)
    disk = getattr(args, "disk", None)

    if not any([cores, ram, disk]):
        fmt.error("Specify at least one: --cores, --ram, or --disk")
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Resize VM {vmid}")
    fmt.blank()

    changes = []
    if cores:
        changes.append(f"cores: {cores}")
    if ram:
        changes.append(f"RAM: {ram}MB")
    if disk:
        changes.append(f"disk: +{disk}GB")

    fmt.line(f"  Changes: {', '.join(changes)}")
    fmt.blank()

    # Apply CPU/RAM changes
    if cores or ram:
        set_parts = []
        if cores:
            set_parts.append(f"--cores {cores}")
        if ram:
            set_parts.append(f"--memory {ram}")

        fmt.step_start("Updating CPU/RAM")
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} {' '.join(set_parts)}")
        if ok:
            fmt.step_ok("CPU/RAM updated")
        else:
            fmt.step_fail(f"Failed: {stdout}")
            return 1

    # Disk resize
    if disk:
        fmt.step_start(f"Expanding disk by {disk}GB")
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm disk resize {vmid} scsi0 +{disk}G")
        if ok:
            fmt.step_ok(f"Disk expanded by {disk}GB")
        else:
            fmt.step_fail(f"Failed: {stdout}")
            return 1

    fmt.blank()
    fmt.footer()
    return 0


def cmd_template(cfg: FreqConfig, pack, args) -> int:
    """Convert a VM to a template."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq vm template <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    if not _safety_check(cfg, vmid, "templatize"):
        return 1

    node_ip = _find_vm_node(cfg, vmid)
    if not node_ip:
        node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Template VM {vmid}")
    fmt.blank()

    # Get current config
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
    if not ok:
        fmt.error(f"VM {vmid} not found.")
        return 1

    vm_name = "unknown"
    for line in stdout.split("\n"):
        if line.startswith("name:"):
            vm_name = line.split(":", 1)[1].strip()
            break

    fmt.line(f"  {fmt.C.BOLD}VM:{fmt.C.RESET}   {vmid} '{vm_name}'")
    fmt.line(f"  {fmt.C.YELLOW}This will stop the VM and convert it to a template.{fmt.C.RESET}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Convert to template? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Stop VM
    fmt.step_start(f"Stopping VM {vmid}")
    _pve_cmd(cfg, node_ip, f"qm stop {vmid}", timeout=VM_CMD_TIMEOUT)
    fmt.step_ok("Stopped")

    # Clean machine-id and SSH host keys for template
    fmt.step_start("Cleaning template (machine-id, SSH keys)")
    _pve_cmd(cfg, node_ip,
             f"qm guest exec {vmid} -- bash -c '"
             f"truncate -s 0 /etc/machine-id; "
             f"rm -f /etc/ssh/ssh_host_*; "
             f"echo CHANGEME > /etc/hostname"
             f"' 2>/dev/null", timeout=VM_CONFIG_TIMEOUT)
    fmt.step_ok("Cleaned (or VM was off)")

    # Convert to template
    fmt.step_start(f"Converting VM {vmid} to template")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm template {vmid}", timeout=VM_CREATE_TIMEOUT)
    if ok:
        fmt.step_ok(f"VM {vmid} is now a template")
        logger.info(f"VM templated: {vmid} {vm_name}")
    else:
        fmt.step_fail(f"Template conversion failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def cmd_rename(cfg: FreqConfig, pack, args) -> int:
    """Rename a VM (change VMID)."""
    target = getattr(args, "target", None)
    new_name = getattr(args, "name", None)

    if not target:
        fmt.error("Usage: freq vm rename <vmid> --name <new_name>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    node_ip = _find_vm_node(cfg, vmid)
    if not node_ip:
        node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Rename VM {vmid}")
    fmt.blank()

    if not new_name:
        try:
            new_name = input(f"  {fmt.C.CYAN}New hostname:{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if not new_name:
            fmt.error("Name is required.")
            return 1

    if not validate.shell_safe_name(new_name):
        fmt.error("Invalid VM name: {}".format(new_name))
        fmt.info("Names: alphanumeric, hyphens, underscores, dots. Max 63 chars.")
        return 1

    fmt.line(f"  {fmt.C.BOLD}VM:{fmt.C.RESET}       {vmid}")
    fmt.line(f"  {fmt.C.BOLD}New name:{fmt.C.RESET}  {new_name}")
    fmt.blank()

    fmt.step_start(f"Renaming VM {vmid} to {new_name}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} --name {new_name}")
    if ok:
        fmt.step_ok(f"VM {vmid} renamed to {new_name}")
        logger.info(f"VM renamed: {vmid} -> {new_name}")
    else:
        fmt.step_fail(f"Rename failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def cmd_add_disk(cfg: FreqConfig, pack, args) -> int:
    """Add disk(s) to a VM."""
    target = getattr(args, "target", None)
    size = getattr(args, "size", None)
    count = getattr(args, "count", 1) or 1

    if not target or not size:
        fmt.error("Usage: freq vm add-disk <vmid> --size <GB> [--count N]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    node_ip = _find_vm_node(cfg, vmid)
    if not node_ip:
        node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Add Disk to VM {vmid}")
    fmt.blank()

    # Find next available disk slot
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
    if not ok:
        fmt.error(f"VM {vmid} not found.")
        return 1

    existing_disks = []
    for line in stdout.split("\n"):
        if line.startswith("scsi") and ":" in line:
            disk_name = line.split(":")[0]
            existing_disks.append(disk_name)

    next_slot = 0
    for i in range(20):
        if f"scsi{i}" not in existing_disks:
            next_slot = i
            break

    storage = "local-lvm"
    for node_name, store_info in cfg.pve_storage.items():
        if store_info.get("pool"):
            storage = store_info["pool"]
            break
    else:
        if not cfg.pve_storage:
            logger.warn("no pve_storage configured — falling back to 'local-lvm'")

    added = 0
    for i in range(count):
        slot = next_slot + i
        fmt.step_start(f"Adding {size}GB disk as scsi{slot}")
        stdout, ok = _pve_cmd(cfg, node_ip,
                               f"qm set {vmid} --scsi{slot} {storage}:{size}")
        if ok:
            fmt.step_ok(f"scsi{slot} ({size}GB) added")
            added += 1
        else:
            fmt.step_fail(f"Failed: {stdout}")

    fmt.blank()
    fmt.line(f"  {added}/{count} disk(s) added to VM {vmid}")
    fmt.blank()
    fmt.footer()
    return 0 if added == count else 1


def cmd_tag(cfg: FreqConfig, pack, args) -> int:
    """Set/remove PVE tags on a VM."""
    target = getattr(args, "target", None)
    tags = getattr(args, "tags", None)

    if not target:
        fmt.error("Usage: freq vm tag <vmid> <tags>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    node_ip = _find_vm_node(cfg, vmid)
    if not node_ip:
        node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    if not tags:
        # Show current tags
        stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
        if ok:
            for line in stdout.split("\n"):
                if line.startswith("tags:"):
                    current = line.split(":", 1)[1].strip()
                    fmt.line(f"  VM {vmid} tags: {fmt.C.CYAN}{current}{fmt.C.RESET}")
                    return 0
            fmt.line(f"  VM {vmid}: no tags set")
        return 0

    fmt.step_start(f"Setting tags on VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} --tags {tags}")
    if ok:
        fmt.step_ok(f"Tags set: {tags}")
    else:
        fmt.step_fail(f"Failed: {stdout}")
    return 0 if ok else 1


def cmd_pool(cfg: FreqConfig, pack, args) -> int:
    """PVE pool management."""
    action = getattr(args, "pool_action", None) or getattr(args, "action", None)

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    if action == "create":
        pool_name = getattr(args, "name", None)
        if not pool_name:
            try:
                pool_name = input(f"  {fmt.C.CYAN}Pool name:{fmt.C.RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 1
        fmt.step_start(f"Creating pool {pool_name}")
        stdout, ok = _pve_cmd(cfg, node_ip, f"pvesh create /pools --poolid {pool_name}")
        if ok:
            fmt.step_ok(f"Pool {pool_name} created")
        else:
            fmt.step_fail(f"Failed: {stdout}")
        return 0 if ok else 1

    if action == "add":
        pool_name = getattr(args, "name", None)
        vmid = getattr(args, "target", None)
        if not pool_name or not vmid:
            fmt.error("Usage: freq pool add --name <pool> --target <vmid>")
            return 1
        fmt.step_start(f"Adding VM {vmid} to pool {pool_name}")
        stdout, ok = _pve_cmd(cfg, node_ip,
                               f"pvesh set /pools/{pool_name} --vms {vmid}")
        if ok:
            fmt.step_ok(f"VM {vmid} added to {pool_name}")
        else:
            fmt.step_fail(f"Failed: {stdout}")
        return 0 if ok else 1

    # Default: list pools
    fmt.header("PVE Pools")
    fmt.blank()

    stdout, ok = _pve_cmd(cfg, node_ip,
                           "pvesh get /pools --output-format json 2>/dev/null")
    if ok:
        try:
            pools = json.loads(stdout)
            if not pools:
                fmt.line(f"  {fmt.C.DIM}No pools defined.{fmt.C.RESET}")
            else:
                fmt.table_header(("POOL", 20), ("COMMENT", 30))
                for p in pools:
                    fmt.table_row(
                        (f"{fmt.C.BOLD}{p.get('poolid', '?')}{fmt.C.RESET}", 20),
                        (p.get("comment", ""), 30),
                    )
        except json.JSONDecodeError:
            fmt.line(stdout)
    else:
        fmt.error("Cannot list pools.")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_sandbox(cfg: FreqConfig, pack, args) -> int:
    """Clone from template, configure IPs, set hostname, start."""
    source = getattr(args, "source", None)
    if not source:
        fmt.error("Usage: freq sandbox spawn <template_vmid> [--name <name>] [--ip <ip>]")
        return 1

    try:
        src_vmid = int(source)
    except ValueError:
        fmt.error(f"Invalid VMID: {source}")
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    new_name = getattr(args, "name", None) or f"sandbox-{src_vmid}"
    ip_addr = getattr(args, "ip", None)

    if not validate.shell_safe_name(new_name):
        fmt.error("Invalid VM name: {}".format(new_name))
        fmt.info("Names: alphanumeric, hyphens, underscores, dots. Max 63 chars.")
        return 1
    if ip_addr and not validate.ip(ip_addr.split("/")[0]):
        fmt.error("Invalid IP address: {}".format(ip_addr))
        return 1

    # Get next VMID
    new_vmid = getattr(args, "vmid", None)
    if not new_vmid:
        new_vmid = _next_vmid(cfg, node_ip)
        if not new_vmid:
            fmt.error("Cannot allocate VMID.")
            return 1

    if not _safety_check(cfg, new_vmid, "create sandbox"):
        return 1

    fmt.header(f"Sandbox Spawn from {src_vmid}")
    fmt.blank()
    fmt.line(f"  Source:  VM {src_vmid}")
    fmt.line(f"  Target:  VM {new_vmid} '{new_name}'")
    if ip_addr:
        fmt.line(f"  IP:      {ip_addr}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Spawn sandbox? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Clone
    fmt.step_start(f"Cloning VM {src_vmid} to {new_vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip,
                           f"qm clone {src_vmid} {new_vmid} --name {new_name} --full",
                           timeout=VM_CLONE_TIMEOUT)
    if not ok:
        fmt.step_fail(f"Clone failed: {stdout}")
        return 1
    fmt.step_ok(f"VM {new_vmid} cloned")

    # Set hostname via cloud-init if IP provided
    if ip_addr:
        fmt.step_start(f"Setting IP to {ip_addr}")
        stdout, ok = _pve_cmd(cfg, node_ip,
                               f"qm set {new_vmid} --ipconfig0 ip={ip_addr if '/' in ip_addr else ip_addr + '/24'},gw={cfg.vm_gateway}")
        if "/" not in ip_addr:
            logger.warn(f"no CIDR prefix on IP {ip_addr} — assuming /24")
        if ok:
            fmt.step_ok("IP configured")
        else:
            fmt.step_fail(f"IP config failed: {stdout}")

    # Start
    fmt.step_start(f"Starting VM {new_vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm start {new_vmid}", timeout=VM_CMD_TIMEOUT)
    if ok:
        fmt.step_ok(f"VM {new_vmid} '{new_name}' running")
        logger.info(f"Sandbox spawned: {src_vmid} -> {new_vmid} {new_name}")
    else:
        fmt.step_fail(f"Start failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_file_send(cfg: FreqConfig, pack, args) -> int:
    """SCP file to a fleet host."""
    src = getattr(args, "source", None)
    dst = getattr(args, "destination", None)

    if not src or not dst:
        fmt.error("Usage: freq file send <local_path> <host>:<remote_path>")
        return 1

    # Parse destination: host:path
    if ":" not in dst:
        fmt.error("Destination must be host:path format")
        return 1

    host_label, remote_path = dst.split(":", 1)

    from freq.core import resolve as res
    host = res.by_target(cfg.hosts, host_label)
    if not host:
        fmt.error(f"Host not found: {host_label}")
        return 1

    from freq.core.ssh import PLATFORM_SSH
    platform = PLATFORM_SSH.get(host.htype, PLATFORM_SSH["linux"])
    user = platform["user"]

    scp_cmd = ["scp"]
    if cfg.ssh_key_path:
        scp_cmd.extend(["-i", cfg.ssh_key_path])
    scp_cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
    scp_cmd.extend([src, f"{user}@{host.ip}:{remote_path}"])

    fmt.step_start(f"Sending {src} to {host.label}:{remote_path}")
    r = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=VM_CREATE_TIMEOUT)
    if r.returncode == 0:
        fmt.step_ok("File sent")
    else:
        fmt.step_fail(f"SCP failed: {r.stderr}")
    return r.returncode


def _find_best_local_storage(cfg: FreqConfig, node_ip: str, target_node: str) -> str:
    """Find best local storage on target node for VM disks.

    Prefers local SSD/ZFS over NFS. Never picks shared NFS for permanent
    VM placement — NFS is a transit layer, not a home.
    """
    stdout, ok = _pve_cmd(cfg, node_ip,
                           f"pvesh get /nodes/{target_node}/storage --output-format json 2>/dev/null")
    if not ok:
        return ""

    try:
        storages = json.loads(stdout)
    except json.JSONDecodeError:
        return ""

    # Score storages: local SSD > local HDD > shared (never pick shared)
    candidates = []
    for s in storages:
        content = s.get("content", "")
        if "images" not in content or not s.get("active", False):
            continue
        stype = s.get("type", "")
        name = s.get("storage", "")
        shared = s.get("shared", 0)

        # Skip shared/NFS storage — VMs belong on local disks
        if shared or stype in ("nfs", "cifs", "cephfs", "glusterfs"):
            continue

        # Prefer SSD-named pools, then ZFS, then anything local
        score = 0
        if "ssd" in name.lower():
            score = 100
        elif stype == "zfspool":
            score = 80
        elif stype in ("lvmthin", "lvm"):
            score = 60
        else:
            score = 40
        candidates.append((score, name))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return ""


def _check_snapshots(cfg: FreqConfig, source_ip: str, vmid: int) -> list:
    """Check if VM has snapshots that would block live migration."""
    stdout, ok = _pve_cmd(cfg, source_ip, f"qm listsnapshot {vmid}")
    if not ok:
        return []
    snapshots = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line or "current" in line.lower():
            continue
        # Parse snapshot name from qm listsnapshot output
        # Format: `-> name  timestamp  description` or ` `-> name ...`
        parts = line.lstrip("`-> ").lstrip("-> ").split()
        if parts:
            snapshots.append(parts[0])
    return snapshots


def _delete_snapshots(cfg: FreqConfig, source_ip: str, vmid: int, snapshots: list) -> bool:
    """Delete all snapshots from a VM."""
    for snap in snapshots:
        fmt.step_start(f"Deleting snapshot '{snap}'")
        stdout, ok = _pve_cmd(cfg, source_ip, f"qm delsnapshot {vmid} {snap}",
                               timeout=VM_CLONE_TIMEOUT)
        if ok:
            fmt.step_ok(f"Deleted '{snap}'")
        else:
            fmt.step_fail(f"Failed to delete '{snap}': {stdout}")
            return False
    return True


def cmd_migrate(cfg: FreqConfig, pack, args) -> int:
    """Live migrate a VM between PVE nodes.

    Workflow:
      1. Find which node currently hosts the VM
      2. Check for snapshots (block live migration) and offer to delete
      3. Auto-detect best LOCAL storage on target (prefers SSD, never NFS)
      4. Live migrate with --with-local-disks (direct node-to-node, no NFS middleman)
      5. Fall back to offline if VM is stopped
      6. Verify VM is running on target after migration
    """
    target = getattr(args, "target", None)
    target_node = getattr(args, "node", None)
    target_storage = getattr(args, "storage", None)
    skip_confirm = getattr(args, "yes", False)

    if not target or not target_node:
        fmt.error("Usage: freq migrate <vmid> --node <target_node> [--storage <pool>]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    # Find which node actually hosts this VM (must run migrate from source)
    source_ip = _find_vm_node(cfg, vmid)
    if not source_ip:
        fmt.error(f"Cannot find VM {vmid} on any PVE node")
        return 1

    # Resolve source node name for display
    source_node = "unknown"
    for i, ip in enumerate(cfg.pve_nodes):
        if ip == source_ip and i < len(cfg.pve_node_names):
            source_node = cfg.pve_node_names[i]
            break

    # Don't migrate to the same node
    if source_node == target_node:
        fmt.error(f"VM {vmid} is already on {target_node}")
        return 1

    fmt.header(f"Migrate VM {vmid}")
    fmt.blank()
    fmt.line(f"  Source: {fmt.C.CYAN}{source_node}{fmt.C.RESET} ({source_ip})")
    fmt.line(f"  Target: {fmt.C.CYAN}{target_node}{fmt.C.RESET}")

    # Auto-detect best local storage on target if not specified
    if not target_storage:
        target_storage = _find_best_local_storage(cfg, source_ip, target_node)
        if target_storage:
            fmt.line(f"  Storage: {fmt.C.CYAN}{target_storage}{fmt.C.RESET} (auto-detected, local)")
        else:
            fmt.warn("No local storage found on target — migration may use default")
    else:
        fmt.line(f"  Storage: {fmt.C.CYAN}{target_storage}{fmt.C.RESET}")

    # Check for snapshots — they block live migration with local disks
    snapshots = _check_snapshots(cfg, source_ip, vmid)
    if snapshots:
        fmt.blank()
        fmt.warn(f"VM has {len(snapshots)} snapshot(s) that block live migration:")
        for s in snapshots:
            fmt.line(f"    - {s}")
        fmt.blank()

        if not skip_confirm:
            try:
                confirm = input(
                    f"  {fmt.C.YELLOW}Delete snapshots to enable live migration? [y/N]:{fmt.C.RESET} "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return 1
            if confirm != "y":
                fmt.info("Cancelled — cannot live migrate with snapshots.")
                return 1
        else:
            fmt.info("Auto-deleting snapshots (--yes)")

        if not _delete_snapshots(cfg, source_ip, vmid, snapshots):
            fmt.error("Failed to delete snapshots — aborting migration")
            return 1

    fmt.blank()

    if not skip_confirm:
        try:
            confirm = input(f"  {fmt.C.YELLOW}Migrate? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Build migration command — direct node-to-node, no NFS middleman
    migrate_cmd = f"qm migrate {vmid} {target_node} --with-local-disks"
    if target_storage:
        migrate_cmd += f" --targetstorage {target_storage}"

    # Dry-run stops here
    if getattr(args, "dry_run", False):
        fmt.info("Dry run — migration plan shown above, no changes made.")
        fmt.blank()
        fmt.footer()
        return 0

    # Try online first (zero downtime), fall back to offline
    fmt.step_start(f"Live migrating VM {vmid} to {target_node} (this may take several minutes)")
    with _ProgressTicker("Migrating"):
        stdout, ok = _pve_cmd(cfg, source_ip, migrate_cmd + " --online", timeout=VM_MIGRATE_TIMEOUT)

    if not ok:
        if "not running" in stdout.lower():
            fmt.step_fail("VM is stopped — switching to offline migration")
            fmt.step_start(f"Offline migration to {target_node}")
            stdout, ok = _pve_cmd(cfg, source_ip, migrate_cmd, timeout=VM_MIGRATE_TIMEOUT)
        elif "snapshot" in stdout.lower():
            fmt.step_fail("Snapshot still blocking migration — check qm listsnapshot")
            fmt.blank()
            fmt.footer()
            return 1

    if ok:
        fmt.step_ok(f"VM {vmid} migrated to {target_node}")
        logger.info(f"VM migrated: {vmid} -> {target_node} (storage={target_storage})")

        # Verify VM is running on target
        fmt.step_start("Verifying VM on target node")
        new_ip = _find_vm_node(cfg, vmid)
        target_resolved = ""
        for i, name in enumerate(cfg.pve_node_names):
            if name == target_node and i < len(cfg.pve_nodes):
                target_resolved = cfg.pve_nodes[i]
                break
        if new_ip == target_resolved:
            fmt.step_ok(f"Confirmed: VM {vmid} running on {target_node}")
        else:
            fmt.step_fail(f"VM {vmid} not found on {target_node} — check PVE cluster status")
    else:
        fmt.step_fail(f"Migration failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def cmd_nic(cfg: FreqConfig, pack, args) -> int:
    """NIC management: add, clear, change-ip, change-id, check-ip."""
    action = getattr(args, "action", None)
    target = getattr(args, "target", None)

    if not action:
        fmt.error("Usage: freq nic <add|clear|change-ip|change-id|check-ip> <vmid> [options]")
        return 1

    dispatch = {
        "add": _nic_add,
        "clear": _nic_clear,
        "change-ip": _nic_change_ip,
        "change-id": _nic_change_id,
        "check-ip": _nic_check_ip,
    }

    handler = dispatch.get(action)
    if not handler:
        fmt.error(f"Unknown NIC action: {action}. Use add|clear|change-ip|change-id|check-ip")
        return 1

    return handler(cfg, args)


def _nic_add(cfg: FreqConfig, args) -> int:
    """Add a NIC to a VM."""
    target = getattr(args, "target", None)
    ip = getattr(args, "ip", None)
    gateway = getattr(args, "gw", None)
    vlan = getattr(args, "vlan", None)

    if not target or not ip:
        fmt.error("Usage: freq nic add <vmid> --ip <ip> [--gw <gateway>] [--vlan <vlan>]")
        return 1

    if not validate.ip(ip.split("/")[0]):
        fmt.error("Invalid IP address: {}".format(ip))
        return 1
    if vlan and not validate.vlan_id(vlan):
        fmt.error("Invalid VLAN ID: {} (must be 0-4094)".format(vlan))
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    if not _safety_check(cfg, vmid, "configure"):
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Add NIC: VM {vmid}")
    fmt.blank()

    # Find next available NIC index
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}", timeout=VM_CONFIG_TIMEOUT)
    next_nic = 0
    if ok:
        for line in stdout.split("\n"):
            key = line.split(":")[0].strip()
            if key.startswith("net"):
                try:
                    idx = int(key.replace("net", ""))
                    if idx >= next_nic:
                        next_nic = idx + 1
                except ValueError:
                    pass

    cidr = ip if "/" in ip else ip + "/24"
    gw_part = f",gw={gateway}" if gateway else ""
    tag_part = f",tag={vlan}" if vlan else ""

    # Create NIC
    fmt.step_start(f"Adding net{next_nic} to VM {vmid}")
    stdout1, ok1 = _pve_cmd(cfg, node_ip,
        f"qm set {vmid} --net{next_nic} virtio,bridge={cfg.nic_bridge}{tag_part}",
        timeout=VM_CONFIG_TIMEOUT)

    # Set IP config
    stdout2, ok2 = _pve_cmd(cfg, node_ip,
        f"qm set {vmid} --ipconfig{next_nic} ip={cidr}{gw_part}",
        timeout=VM_CONFIG_TIMEOUT)

    if ok1 and ok2:
        fmt.step_ok(f"net{next_nic} added: {ip}" + (f" VLAN {vlan}" if vlan else ""))
        logger.info(f"NIC added to VM {vmid}: net{next_nic} ip={ip}")
    else:
        err = stdout1 if not ok1 else stdout2
        fmt.step_fail(f"Failed: {err}")

    fmt.blank()
    fmt.footer()
    return 0 if ok1 and ok2 else 1


def _nic_clear(cfg: FreqConfig, args) -> int:
    """Remove all NICs from a VM."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq nic clear <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    if not _safety_check(cfg, vmid, "configure"):
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Clear NICs: VM {vmid}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Remove ALL NICs from VM {vmid}? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Get current config
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}", timeout=VM_CONFIG_TIMEOUT)
    if not ok:
        fmt.step_fail(f"Cannot read VM config: {stdout}")
        fmt.blank()
        fmt.footer()
        return 1

    deleted = []
    for line in stdout.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key = line.split(":")[0].strip()
        if key.startswith("ipconfig") or key.startswith("net"):
            fmt.step_start(f"Removing {key}")
            _, del_ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} --delete {key}", timeout=VM_CONFIG_TIMEOUT)
            if del_ok:
                fmt.step_ok(f"Removed {key}")
                deleted.append(key)
            else:
                fmt.step_fail(f"Failed to remove {key}")

    fmt.blank()
    fmt.line(f"  Cleared {len(deleted)} NIC entries from VM {vmid}")
    fmt.blank()
    fmt.footer()
    return 0


def _nic_change_ip(cfg: FreqConfig, args) -> int:
    """Change a VM's IP configuration."""
    target = getattr(args, "target", None)
    ip = getattr(args, "ip", None)
    gateway = getattr(args, "gw", None)
    nic_idx = getattr(args, "nic_index", 0) or 0
    vlan = getattr(args, "vlan", None)

    if not target or not ip:
        fmt.error("Usage: freq nic change-ip <vmid> --ip <ip> [--gw <gw>] [--nic-index N] [--vlan V]")
        return 1

    if not validate.ip(ip.split("/")[0]):
        fmt.error("Invalid IP address: {}".format(ip))
        return 1
    if vlan and not validate.vlan_id(vlan):
        fmt.error("Invalid VLAN ID: {} (must be 0-4094)".format(vlan))
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    if not _safety_check(cfg, vmid, "configure"):
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Change IP: VM {vmid}")
    fmt.blank()

    cidr = ip if "/" in ip else ip + "/24"
    gw_part = f",gw={gateway}" if gateway else ""
    tag_part = f",tag={vlan}" if vlan else ""

    # Set NIC
    fmt.step_start(f"Updating net{nic_idx}")
    stdout1, ok1 = _pve_cmd(cfg, node_ip,
        f"qm set {vmid} --net{nic_idx} virtio,bridge={cfg.nic_bridge}{tag_part}",
        timeout=VM_CONFIG_TIMEOUT)

    # Set IP config
    fmt.step_start(f"Setting ipconfig{nic_idx} to {ip}")
    stdout2, ok2 = _pve_cmd(cfg, node_ip,
        f"qm set {vmid} --ipconfig{nic_idx} ip={cidr}{gw_part}",
        timeout=VM_CONFIG_TIMEOUT)

    if ok1 and ok2:
        fmt.step_ok(f"VM {vmid} net{nic_idx} → {ip}")
    else:
        err = stdout1 if not ok1 else stdout2
        fmt.step_fail(f"Failed: {err}")

    fmt.blank()
    fmt.footer()
    return 0 if ok1 and ok2 else 1


def _nic_change_id(cfg: FreqConfig, args) -> int:
    """Change a VM's VMID (clone + destroy)."""
    target = getattr(args, "target", None)
    new_id = getattr(args, "new_id", None)

    if not target or not new_id:
        fmt.error("Usage: freq nic change-id <vmid> --new-id <new_vmid>")
        return 1

    try:
        vmid = int(target)
        newid = int(new_id)
    except ValueError:
        fmt.error("Both VMIDs must be integers")
        return 1

    if not _safety_check(cfg, vmid, "change-id"):
        return 1
    if not _safety_check(cfg, newid, "change-id"):
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        _pve_unreachable_hint(cfg)
        return 1

    fmt.header(f"Change VMID: {vmid} → {newid}")
    fmt.blank()

    # Check VM is stopped
    stdout, _ = _pve_cmd(cfg, node_ip, f"qm status {vmid}", timeout=VM_QUICK_TIMEOUT)
    if "running" in (stdout or ""):
        fmt.error(f"VM {vmid} must be stopped first")
        return 1

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Change VMID {vmid} → {newid}? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Clone to new ID
    fmt.step_start(f"Cloning {vmid} → {newid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm clone {vmid} {newid} --full", timeout=VM_CLONE_TIMEOUT)
    if not ok:
        fmt.step_fail(f"Clone failed: {stdout}")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok("Clone complete")

    # Destroy old
    fmt.step_start(f"Removing old VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=VM_CREATE_TIMEOUT)
    if ok:
        fmt.step_ok(f"VMID changed: {vmid} → {newid}")
        logger.info(f"VMID changed: {vmid} -> {newid}")
    else:
        fmt.step_fail(f"Destroy old VM failed: {stdout}")
        fmt.warn(f"New VM {newid} exists but old VM {vmid} remains")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def _nic_check_ip(cfg: FreqConfig, args) -> int:
    """Check if an IP address is available (ping test)."""
    ip = getattr(args, "ip", None)
    if not ip:
        fmt.error("Usage: freq nic check-ip --ip <ip_address>")
        return 1

    fmt.header(f"IP Check: {ip}")
    fmt.blank()

    fmt.step_start(f"Pinging {ip}")
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            fmt.step_ok(f"{ip} is REACHABLE (in use)")
            fmt.line(f"  {fmt.C.YELLOW}This IP is already taken.{fmt.C.RESET}")
        else:
            fmt.step_ok(f"{ip} is UNREACHABLE (available)")
            fmt.line(f"  {fmt.C.GREEN}This IP appears to be free.{fmt.C.RESET}")
    except subprocess.TimeoutExpired:
        fmt.step_ok(f"{ip} is UNREACHABLE (available)")
        fmt.line(f"  {fmt.C.GREEN}This IP appears to be free.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0
