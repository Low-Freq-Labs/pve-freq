"""VM lifecycle management for FREQ.

Commands: create, clone, destroy, resize, snapshot, migrate

Every operation goes through the PVE API via SSH + qm/pvesh commands.
Safety gates enforce protected VMID ranges and confirmation prompts.
"""
import json
import subprocess
import time

from freq.core import fmt
from freq.core import validate
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# VM operation timeouts
VM_CMD_TIMEOUT = 60
VM_QUICK_TIMEOUT = 10
VM_CONFIG_TIMEOUT = 30
VM_CREATE_TIMEOUT = 120
VM_CLONE_TIMEOUT = 300
VM_MIGRATE_TIMEOUT = 600


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
        fmt.blank()
        fmt.footer()
        return 1

    new_name = getattr(args, "name", None) or f"clone-of-{src_vmid}"
    new_vmid = getattr(args, "vmid", None)
    ip_addr = getattr(args, "ip", None)
    vlan = getattr(args, "vlan", None)

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
                # Configure hostname
                _pve_cmd(cfg, node_ip,
                         f"echo '{new_name}' > /mnt/vm{new_vmid}/etc/hostname")
                # Clear machine-id for regen
                _pve_cmd(cfg, node_ip,
                         f"truncate -s 0 /mnt/vm{new_vmid}/etc/machine-id")
                # Remove SSH host keys for regen
                _pve_cmd(cfg, node_ip,
                         f"rm -f /mnt/vm{new_vmid}/etc/ssh/ssh_host_*")
                # Update /etc/hosts
                _pve_cmd(cfg, node_ip,
                         f"sed -i 's/127.0.1.1.*/127.0.1.1\\t{new_name}/' "
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
        return 1

    new_name = getattr(args, "name", None) or f"sandbox-{src_vmid}"
    ip_addr = getattr(args, "ip", None)

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


def cmd_migrate(cfg: FreqConfig, pack, args) -> int:
    """Migrate a VM between PVE nodes with auto storage mapping.

    Detects source/target storage pools and remaps if they differ.
    """
    target = getattr(args, "target", None)
    target_node = getattr(args, "node", None)
    target_storage = getattr(args, "storage", None)

    if not target or not target_node:
        fmt.error("Usage: freq migrate <vmid> --node <target_node> [--storage <pool>]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        return 1

    fmt.header(f"Migrate VM {vmid}")
    fmt.blank()
    fmt.line(f"  Target node: {fmt.C.CYAN}{target_node}{fmt.C.RESET}")

    # Auto-detect storage mapping if not specified
    if not target_storage:
        # Get target node storage pools
        stdout, ok = _pve_cmd(cfg, node_ip,
                               f"pvesh get /nodes/{target_node}/storage --output-format json 2>/dev/null")
        if ok:
            try:
                storages = json.loads(stdout)
                # Find first storage that supports images
                for s in storages:
                    content = s.get("content", "")
                    if "images" in content and s.get("active", False):
                        target_storage = s.get("storage", "")
                        break
            except json.JSONDecodeError:
                pass

    if target_storage:
        fmt.line(f"  Target storage: {fmt.C.CYAN}{target_storage}{fmt.C.RESET}")

    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Migrate? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Build migration command
    migrate_cmd = f"qm migrate {vmid} {target_node} --with-local-disks"
    if target_storage:
        migrate_cmd += f" --targetstorage {target_storage}"

    # Try online first, fall back to offline
    fmt.step_start(f"Migrating VM {vmid} to {target_node}")
    stdout, ok = _pve_cmd(cfg, node_ip, migrate_cmd + " --online", timeout=VM_MIGRATE_TIMEOUT)

    if not ok and "not running" in stdout.lower():
        # VM is stopped — offline migration
        fmt.step_fail("Online migration failed (VM not running), trying offline")
        fmt.step_start(f"Offline migration to {target_node}")
        stdout, ok = _pve_cmd(cfg, node_ip, migrate_cmd, timeout=VM_MIGRATE_TIMEOUT)

    if ok:
        fmt.step_ok(f"VM {vmid} migrated to {target_node}")
        logger.info(f"VM migrated: {vmid} -> {target_node}", storage=target_storage)
    else:
        fmt.step_fail(f"Migration failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1
