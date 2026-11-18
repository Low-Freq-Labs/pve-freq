"""Cloud-init VM provisioning for FREQ.

Domain: freq vm provision / freq vm import

Downloads cloud images, creates PVE VMs with cloud-init, deploys SSH keys,
and boots ready-to-use instances. Supports Debian 12/13, Ubuntu 22.04/24.04,
Rocky 9, and AlmaLinux 9.

Replaces: Terraform + Packer image pipelines ($0 — Proxmox-native)

Architecture:
    - Cloud images cached on PVE node at /var/lib/vz/template/qcow2/
    - provision_agent_vm() creates VM, imports disk, configures cloud-init, starts
    - ZFS-aware: uses raw format on ZFS storage to avoid double copy-on-write

Design decisions:
    - Image cache avoids re-downloading on every provision
    - Node-aware storage selection reads pve_storage map from freq.toml
"""

import os
import shlex

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import remote_command, run as ssh_run
from freq.core.validate import label as valid_label, vmid as valid_vmid
from freq.services.cloud_init_legacy_inputs import InvalidNetworkIntent, legacy_static_ipv4, legacy_dns_servers, InvalidIdentityIntent, legacy_guest_user

# Provisioning timeouts
PROVISION_CMD_TIMEOUT = 60
PROVISION_DOWNLOAD_TIMEOUT = 600
PROVISION_CREATE_TIMEOUT = 120
PROVISION_IMPORT_TIMEOUT = 300


# Cloud image URLs — generic cloud images with cloud-init support
CLOUD_IMAGES = {
    "debian-13": {
        "name": "Debian 13 (trixie)",
        "url": "https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-amd64.qcow2",
        "filename": "debian-13-generic-amd64.qcow2",
    },
    "debian-12": {
        "name": "Debian 12 (bookworm)",
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "filename": "debian-12-generic-amd64.qcow2",
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


def _pve_cmd(cfg, node_ip, command, timeout=PROVISION_CMD_TIMEOUT):
    """Run command on PVE node."""
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


def download_cloud_image(cfg: FreqConfig, node_ip: str, image_key: str = None) -> str:
    """Prepare an image path after command ACKs, not verified image integrity."""
    image_key = image_key or DEFAULT_IMAGE
    if image_key not in CLOUD_IMAGES:
        fmt.error(f"Unknown image: {image_key}")
        fmt.info(f"Available: {', '.join(CLOUD_IMAGES.keys())}")
        return ""

    image = CLOUD_IMAGES[image_key]
    remote_path = f"{TEMPLATE_STORAGE}/{image['filename']}"

    # The fixed probe reports absence as data. Transport failure cannot be
    # mistaken for an absent cache entry and authorize a fresh download.
    stdout, ok = _provision_command_ack(cfg, node_ip, remote_command(
        script='test -f "$1"; status=$?; case "$status" in 0) printf "%s\\n" EXISTS;; 1) printf "%s\\n" MISSING;; *) exit "$status";; esac',
        args=(remote_path,)))
    if not ok:
        return ""
    cache_state = stdout.strip()
    if cache_state == "EXISTS":
        fmt.step_ok(f"Image already cached: {image['name']}")
        return remote_path
    if cache_state != "MISSING":
        fmt.step_warn("Image cache probe was not recognized; inspect before retry.")
        return ""

    fmt.step_start(f"Downloading {image['name']} (may take a few minutes)")
    _, prepared = _provision_command_ack(cfg, node_ip, remote_command(
        argv=("mkdir", "-p", "--", TEMPLATE_STORAGE)))
    if not prepared:
        return ""
    _, downloaded = _provision_command_ack(
        cfg, node_ip, remote_command(argv=("wget", "-q", "-O", remote_path, "--", image['url'])),
        timeout=PROVISION_DOWNLOAD_TIMEOUT)
    if not downloaded:
        return ""
    fmt.step_ok(f"Download command acknowledged: {image['name']}")
    return remote_path


def _provision_command_ack(cfg, node_ip, command, timeout=PROVISION_CMD_TIMEOUT):
    """Observe one existing transport ACK; never retry or compensate.

    A missing ACK, malformed response or ordinary transport exception can
    follow a remote effect. Return False and leave inspection/recovery to
    the operation owner. Even True does not mean guest state is effective.
    """
    try:
        result = _pve_cmd(cfg, node_ip, command, timeout=timeout)
    except Exception:
        result = None
    if (type(result) is not tuple or len(result) != 2 or
            type(result[0]) is not str or result[1] is not True):
        fmt.step_warn("Provisioning halted: command not acknowledged; remote state may be partial. Inspect before retry.")
        return "", False
    return result


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
    and requests VM start. True means all issued command ACKs were observed;
    it does not establish effective guest configuration or readiness.
    """
    # Request syntax and existing product bounds only; no target admission,
    # capacity, source ownership or effective guest configuration is implied.
    if (type(vmid) is not int or not valid_vmid(vmid) or
            type(agent_name) is not str or agent_name != agent_name.strip() or
            not valid_label(agent_name) or
            type(cores) is not int or not 1 <= cores <= 256 or
            type(ram) is not int or ram < 256 or
            type(disk_gb) is not int or disk_gb < 1):
        fmt.error("Provisioning requires a valid VMID, label and explicit resource values")
        return False
    if ip_address is not None:
        try:
            ip_address, gateway = legacy_static_ipv4(ip_address, gateway)
        except InvalidNetworkIntent:
            fmt.error("Provisioning requires an explicit valid IPv4 CIDR and optional on-link gateway")
            return False
    elif gateway is not None and gateway != "":
        fmt.error("A gateway requires an explicit static IPv4 CIDR")
        return False
    try:
        nameserver = legacy_dns_servers(cfg.vm_nameserver)
    except InvalidNetworkIntent:
        fmt.error("Provisioning requires valid resolver address inputs")
        return False
    try:
        ciuser = legacy_guest_user(cfg.ssh_service_account)
    except InvalidIdentityIntent:
        fmt.error("Provisioning requires an explicit supported guest user")
        return False
    image_key = image_key or DEFAULT_IMAGE

    # Step 1: Download image
    try:
        image_path = download_cloud_image(cfg, node_ip, image_key)
    except Exception:
        fmt.step_warn("Image preparation interrupted; remote state may be partial. Inspect before retry.")
        return False
    if not image_path:
        return False

    # Step 2: Create VM with cloud-init
    fmt.step_start(f"Creating VM {vmid} with cloud-init")

    # Determine storage — node-aware selection
    storage = "local-lvm"
    # Resolve node IP → name for node-specific storage
    target_name = ""
    for i, ip in enumerate(cfg.pve_nodes):
        if ip == node_ip and i < len(cfg.pve_node_names):
            target_name = cfg.pve_node_names[i]
            break
    if target_name and target_name in cfg.pve_storage:
        pool = cfg.pve_storage[target_name].get("pool", "")
        if pool:
            storage = pool
    else:
        for _, store_info in cfg.pve_storage.items():
            if store_info.get("pool"):
                storage = store_info["pool"]
                break
        else:
            if not cfg.pve_storage:
                fmt.warn("No storage configured in freq.toml — using 'local-lvm' default")

    create_cmd = remote_command(argv=(
        "qm", "create", str(vmid), "--name", str(agent_name),
        "--cores", str(cores), "--memory", str(ram), "--balloon", "512",
        "--cpu", str(cfg.vm_cpu), "--machine", str(cfg.vm_machine),
        "--net0", f"virtio,bridge={cfg.nic_bridge}",
        "--scsihw", str(cfg.vm_scsihw), "--ide2", f"{storage}:cloudinit",
        "--boot", "order=scsi0", "--serial0", "socket", "--vga", "serial0",
        "--rng0", "source=/dev/urandom", "--tablet", "0",
        "--agent", "enabled=1,fstrim_cloned_disks=1",
    ))
    stdout, ok = _provision_command_ack(cfg, node_ip, create_cmd, timeout=PROVISION_CREATE_TIMEOUT)
    if not ok:
        fmt.step_warn("VM creation was not acknowledged; inspect partial remote state before retry")
        return False
    fmt.step_ok(f"VM {vmid} created")

    # Step 3: Import cloud image as disk
    fmt.step_start("Importing cloud image as boot disk")
    # Detect ZFS storage via PVE API — use raw format to avoid double CoW
    storage_type = ""
    st_out, st_ok = _provision_command_ack(
        cfg, node_ip, remote_command(argv=("pvesm", "status", "--storage", str(storage))))
    if not st_ok:
        return False
    if st_out.strip():
        # Keep the original last-row interpretation without a remote pipeline
        # whose tail status could hide failure of the pvesm producer.
        st_parts = st_out.strip().splitlines()[-1].split()
        if len(st_parts) >= 2:
            storage_type = st_parts[1]  # type column
    import_cmd = remote_command(argv=(
        "qm", "importdisk", str(vmid), str(image_path), str(storage),
        *(("--format", "raw") if "zfs" in storage_type.lower() else ()),
    ))
    stdout, ok = _provision_command_ack(cfg, node_ip, import_cmd, timeout=PROVISION_IMPORT_TIMEOUT)
    if not ok:
        fmt.step_warn("Disk import was not acknowledged; inspect partial remote state before retry")
        return False

    # Attach the imported disk with performance flags
    _, attached = _provision_command_ack(cfg, node_ip, remote_command(argv=(
        "qm", "set", str(vmid), "--scsi0", f"{storage}:vm-{vmid}-disk-0,discard=on,ssd=1,iothread=1")))
    if not attached:
        return False
    fmt.step_ok("Boot disk imported")

    # Step 4: Resize disk
    if disk_gb > 2:
        fmt.step_start(f"Resizing disk to {disk_gb}GB")
        _, resized = _provision_command_ack(cfg, node_ip, remote_command(argv=(
            "qm", "disk", "resize", str(vmid), "scsi0", f"{disk_gb}G")))
        if not resized:
            return False
        fmt.step_ok(f"Disk resized to {disk_gb}GB")

    # Step 5: Configure cloud-init
    fmt.step_start("Configuring cloud-init")
    ci_cmds = [
        remote_command(argv=("qm", "set", str(vmid), "--ciuser", ciuser)),
        remote_command(argv=("qm", "set", str(vmid), "--citype", "nocloud")),
    ]

    # SSH key
    pubkey_path = ssh_pubkey_path or (cfg.ssh_key_path + ".pub" if cfg.ssh_key_path else "")
    if pubkey_path and os.path.isfile(pubkey_path):
        with open(pubkey_path) as f:
            pubkey = f.read().strip()
        # One command owns the exclusive temporary file through key application
        # and normal-exit cleanup. Cleanup failure cannot yield a positive ACK.
        # Signals/lost remote returns still require original native custody;
        # this fixed script does not establish that lifetime or target identity.
        ci_cmds.append(remote_command(
            script=(
                'umask 077\n'
                '_key_file=$(mktemp /tmp/freq-sshkey.XXXXXXXXXX) || exit "$?"\n'
                '[ -n "$_key_file" ] || exit 1\n'
                '_cleanup() {\n'
                '    _body_status=$?\n'
                '    trap - EXIT HUP INT TERM\n'
                '    rm -f -- "$_key_file"\n'
                '    _cleanup_status=$?\n'
                '    if [ "$_body_status" -ne 0 ]; then\n'
                '        exit "$_body_status"\n'
                '    fi\n'
                '    exit "$_cleanup_status"\n'
                '}\n'
                'trap _cleanup EXIT\n'
                "trap 'exit 129' HUP\n"
                "trap 'exit 130' INT\n"
                "trap 'exit 143' TERM\n"
                'printf \'%s\\n\' "$1" > "$_key_file" || exit "$?"\n'
                'qm set "$2" --sshkeys "$_key_file"\n'
            ),
            args=(pubkey, str(vmid))))

    # IP address
    if ip_address:
        gateway_suffix = f",gw={gateway}" if gateway is not None else ""
        ci_cmds.append(remote_command(argv=(
            "qm", "set", str(vmid), "--ipconfig0", f"ip={ip_address}{gateway_suffix}")))
    else:
        ci_cmds.append(remote_command(argv=("qm", "set", str(vmid), "--ipconfig0", "ip=dhcp")))

    # Nameserver
    if nameserver:
        ci_cmds.append(remote_command(argv=("qm", "set", str(vmid), "--nameserver", nameserver)))

    for cmd in ci_cmds:
        _, acknowledged = _provision_command_ack(cfg, node_ip, cmd)
        if not acknowledged:
            return False
    fmt.step_ok("Cloud-init commands acknowledged; effective guest state is unverified")

    # Step 6: Start VM
    fmt.step_start(f"Starting VM {vmid}")
    stdout, ok = _provision_command_ack(cfg, node_ip, remote_command(argv=(
        "qm", "start", str(vmid))), timeout=PROVISION_CMD_TIMEOUT)
    if ok:
        fmt.step_ok(f"VM {vmid} start command acknowledged; guest readiness is unverified")
    else:
        return False

    return True


def cmd_import(cfg: FreqConfig, pack, args) -> int:
    """Import a cloud image after explicit request syntax and one ID read.

    A returned nextid is a suggestion, never a reservation or admission grant.
    Target/currentness and existing operation ownership remain separate.
    """
    image = getattr(args, "image", None)
    if image is None:
        image = DEFAULT_IMAGE
    if type(image) is not str or image not in CLOUD_IMAGES:
        fmt.error("Import requires an available cloud image selection")
        return 1
    name = getattr(args, "name", None)
    if name is None:
        name = "freq-{}".format(image)
    vmid = getattr(args, "vmid", None)
    if (type(name) is not str or name != name.strip() or not valid_label(name) or
            vmid is not None and (type(vmid) is not int or not valid_vmid(vmid))):
        fmt.error("Import requires a valid VM label and optional explicit VMID")
        return 1
    try:
        legacy_dns_servers(cfg.vm_nameserver)
    except InvalidNetworkIntent:
        fmt.error("Import requires valid resolver address inputs")
        return 1
    # Import/discovery is deliberately after request and resolver validation.
    from freq.modules.pve import _find_reachable_node
    from freq.modules.pve import _pve_cmd as pve_cmd

    fmt.header("Import: {}".format(image))
    fmt.blank()
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.error("No PVE node reachable.")
        return 1

    if vmid is None:
        try:
            result = pve_cmd(cfg, node_ip, "pvesh get /cluster/nextid")
        except Exception:
            result = None
        if (type(result) is not tuple or len(result) != 2 or
                type(result[0]) is not str or result[1] is not True):
            fmt.error("Cannot determine a VMID; inspect before retry")
            return 1
        text = result[0].strip()
        # Bound conversion first; refuse noncanonical/coerced numeric forms.
        if (not 1 <= len(text) <= 9 or not text.isascii() or
                not text.isdecimal() or text[0] == "0"):
            fmt.error("Cannot determine a valid VMID")
            return 1
        vmid = int(text)
        if not valid_vmid(vmid):
            fmt.error("Cannot determine a valid VMID")
            return 1

    fmt.line("  {b}Image:{r}  {n}".format(b=fmt.C.BOLD, r=fmt.C.RESET, n=CLOUD_IMAGES[image]["name"]))
    fmt.line("  {b}VMID:{r}   {v}".format(b=fmt.C.BOLD, r=fmt.C.RESET, v=vmid))
    fmt.line("  {b}Name:{r}   {n}".format(b=fmt.C.BOLD, r=fmt.C.RESET, n=name))
    fmt.blank()

    ok = provision_agent_vm(cfg, node_ip, vmid, name, image_key=image)
    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def cmd_provision(cfg: FreqConfig, pack, args) -> int:
    """Provision a VM with cloud-init."""
    fmt.header("Provision")
    fmt.blank()

    fmt.line(f"{fmt.C.BOLD}Available cloud images:{fmt.C.RESET}")
    fmt.blank()
    for key, image in CLOUD_IMAGES.items():
        fmt.line(f"  {fmt.C.CYAN}{key:<16}{fmt.C.RESET} {image['name']}")

    fmt.blank()
    fmt.line(f"{fmt.C.GRAY}Used by: freq vm provision (cloud-init){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
