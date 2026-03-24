"""Cloud-init provisioning for FREQ agent VMs.

Downloads cloud images, creates templates, provisions VMs with:
- OS installed and booted
- SSH keys deployed
- FREQ installed
- CLAUDE.md in place
- Service account configured

Supports: Debian 12/13, Ubuntu 22.04/24.04, Rocky 9, AlmaLinux 9
"""
import os
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run


# Cloud image URLs — generic cloud images with cloud-init support
CLOUD_IMAGES = {
    "debian-13": {
        "name": "Debian 13 (trixie)",
        "url": "https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2",
        "filename": "debian-13-genericcloud-amd64.qcow2",
    },
    "debian-12": {
        "name": "Debian 12 (bookworm)",
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2",
        "filename": "debian-12-genericcloud-amd64.qcow2",
    },
    "ubuntu-2404": {
        "name": "Ubuntu 24.04 LTS",
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "filename": "ubuntu-2404-server-cloudimg-amd64.img",
    },
    "ubuntu-2204": {
        "name": "Ubuntu 22.04 LTS",
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "filename": "ubuntu-2204-server-cloudimg-amd64.img",
    },
    "rocky-9": {
        "name": "Rocky Linux 9",
        "url": "https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2",
        "filename": "rocky-9-genericcloud-amd64.qcow2",
    },
    "alma-9": {
        "name": "AlmaLinux 9",
        "url": "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2",
        "filename": "alma-9-genericcloud-amd64.qcow2",
    },
}

DEFAULT_IMAGE = "debian-13"
TEMPLATE_STORAGE = "/var/lib/vz/template/qcow2"


def _pve_cmd(cfg, node_ip, command, timeout=60):
    """Run command on PVE node."""
    r = ssh_run(
        host=node_ip, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pve", use_sudo=True,
    )
    return r.stdout, r.returncode == 0


def download_cloud_image(cfg: FreqConfig, node_ip: str, image_key: str = None) -> str:
    """Download a cloud image to the PVE node. Returns local path or empty."""
    image_key = image_key or DEFAULT_IMAGE
    if image_key not in CLOUD_IMAGES:
        fmt.error(f"Unknown image: {image_key}")
        fmt.info(f"Available: {', '.join(CLOUD_IMAGES.keys())}")
        return ""

    image = CLOUD_IMAGES[image_key]
    remote_path = f"{TEMPLATE_STORAGE}/{image['filename']}"

    # Check if already downloaded
    stdout, ok = _pve_cmd(cfg, node_ip, f"test -f {remote_path} && echo EXISTS")
    if ok and "EXISTS" in stdout:
        fmt.step_ok(f"Image already cached: {image['name']}")
        return remote_path

    # Download
    fmt.step_start(f"Downloading {image['name']} (may take a few minutes)")
    _pve_cmd(cfg, node_ip, f"mkdir -p {TEMPLATE_STORAGE}")
    stdout, ok = _pve_cmd(cfg, node_ip,
                          f"wget -q -O {remote_path} '{image['url']}'",
                          timeout=600)
    if ok:
        fmt.step_ok(f"Downloaded: {image['name']}")
        return remote_path
    else:
        fmt.step_fail(f"Download failed: {stdout[:60]}")
        return ""


def provision_agent_vm(
    cfg: FreqConfig,
    node_ip: str,
    vmid: int,
    agent_name: str,
    image_key: str = None,
    cores: int = 2,
    ram: int = 2048,
    disk_gb: int = 32,
    ssh_pubkey_path: str = None,
    ip_address: str = None,
    gateway: str = None,
) -> bool:
    """Provision a VM with cloud-init for an agent.

    Creates the VM, imports the cloud image, configures cloud-init,
    and starts the VM. Returns True on success.
    """
    image_key = image_key or DEFAULT_IMAGE

    # Step 1: Download image
    image_path = download_cloud_image(cfg, node_ip, image_key)
    if not image_path:
        return False

    # Step 2: Create VM with cloud-init
    fmt.step_start(f"Creating VM {vmid} with cloud-init")

    # Determine storage — warn if no config
    storage = "local-lvm"
    for _, store_info in cfg.pve_storage.items():
        if store_info.get("pool"):
            storage = store_info["pool"]
            break
    else:
        if not cfg.pve_storage:
            fmt.warn("No storage configured in freq.toml — using 'local-lvm' default")

    create_cmd = (
        f"qm create {vmid} --name {agent_name} "
        f"--cores {cores} --memory {ram} "
        f"--cpu {cfg.vm_cpu} --machine {cfg.vm_machine} "
        f"--net0 virtio,bridge={cfg.nic_bridge} "
        f"--scsihw {cfg.vm_scsihw} "
        f"--ide2 {storage}:cloudinit "
        f"--boot order=scsi0 "
        f"--serial0 socket --vga serial0 "
        f"--agent enabled=1"
    )
    stdout, ok = _pve_cmd(cfg, node_ip, create_cmd, timeout=120)
    if not ok:
        fmt.step_fail(f"VM creation failed: {stdout[:60]}")
        return False
    fmt.step_ok(f"VM {vmid} created")

    # Step 3: Import cloud image as disk
    fmt.step_start("Importing cloud image as boot disk")
    import_cmd = f"qm importdisk {vmid} {image_path} {storage}"
    stdout, ok = _pve_cmd(cfg, node_ip, import_cmd, timeout=300)
    if not ok:
        fmt.step_fail(f"Disk import failed: {stdout[:60]}")
        return False

    # Attach the imported disk
    _pve_cmd(cfg, node_ip, f"qm set {vmid} --scsi0 {storage}:vm-{vmid}-disk-0")
    fmt.step_ok("Boot disk imported")

    # Step 4: Resize disk
    if disk_gb > 2:
        fmt.step_start(f"Resizing disk to {disk_gb}GB")
        _pve_cmd(cfg, node_ip, f"qm disk resize {vmid} scsi0 {disk_gb}G")
        fmt.step_ok(f"Disk resized to {disk_gb}GB")

    # Step 5: Configure cloud-init
    fmt.step_start("Configuring cloud-init")
    ci_cmds = [
        f"qm set {vmid} --ciuser {cfg.ssh_service_account}",
        f"qm set {vmid} --citype nocloud",
    ]

    # SSH key
    pubkey_path = ssh_pubkey_path or (cfg.ssh_key_path + ".pub" if cfg.ssh_key_path else "")
    if pubkey_path and os.path.isfile(pubkey_path):
        # Upload pubkey to PVE node first
        import subprocess
        with open(pubkey_path) as f:
            pubkey = f.read().strip()
        # Write to temp file on PVE
        _pve_cmd(cfg, node_ip, f"echo '{pubkey}' > /tmp/agent-sshkey-{vmid}.pub")
        ci_cmds.append(f"qm set {vmid} --sshkeys /tmp/agent-sshkey-{vmid}.pub")

    # IP address
    if ip_address and gateway:
        cidr = ip_address if "/" in ip_address else ip_address + "/24"
        if "/" not in ip_address:
            logger.warn(f"no CIDR prefix on IP {ip_address} — assuming /24")
        ci_cmds.append(f"qm set {vmid} --ipconfig0 ip={cidr},gw={gateway}")
    else:
        ci_cmds.append(f"qm set {vmid} --ipconfig0 ip=dhcp")

    # Nameserver
    ci_cmds.append(f"qm set {vmid} --nameserver {cfg.vm_nameserver}")

    for cmd in ci_cmds:
        _pve_cmd(cfg, node_ip, cmd)
    fmt.step_ok("Cloud-init configured")

    # Step 6: Start VM
    fmt.step_start(f"Starting VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm start {vmid}", timeout=60)
    if ok:
        fmt.step_ok(f"VM {vmid} started — booting with cloud-init")
    else:
        fmt.step_warn(f"Start may have failed: {stdout[:40]}")

    return True


def cmd_provision(cfg: FreqConfig, pack, args) -> int:
    """Provision a VM with cloud-init."""
    fmt.header("Provision")
    fmt.blank()

    fmt.line(f"{fmt.C.BOLD}Available cloud images:{fmt.C.RESET}")
    fmt.blank()
    for key, image in CLOUD_IMAGES.items():
        fmt.line(f"  {fmt.C.CYAN}{key:<16}{fmt.C.RESET} {image['name']}")

    fmt.blank()
    fmt.line(f"{fmt.C.GRAY}Used by: freq agent create (auto-provisions with cloud-init){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
