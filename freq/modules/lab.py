"""Lab environment management for FREQ.

Domain: freq lab <status|media|resize|rebuild|deploy>

Manages lab hosts: sandbox VMs, docker-dev instances, test media stacks,
and lab PVE nodes. Lab hosts are identified by the 'lab' group in hosts.toml.
Provides media stack deployment, VM resizing, and full lab rebuilds.

Replaces: Manual SSH-and-script lab management, Vagrant ($0 but heavy)

Architecture:
    - Lab hosts filtered from fleet by group membership ('lab' in groups)
    - SSH operations via freq/core/ssh.py with lab-specific timeouts
    - Media deploy pushes Docker Compose stacks to lab media hosts
    - Rebuild tears down and re-provisions lab VMs from scratch

Design decisions:
    - Lab is a group filter, not a separate inventory. Lab hosts are normal
      fleet hosts with a 'lab' group tag. No duplicate management.
"""

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Lab timeouts
LAB_CMD_TIMEOUT = 30
LAB_QUICK_TIMEOUT = 5
LAB_API_TIMEOUT = 10
LAB_DOCKER_TIMEOUT = 60
LAB_LONG_TIMEOUT = 120
LAB_BUILD_TIMEOUT = 300


def _get_lab_hosts(cfg: FreqConfig) -> list:
    """Get lab hosts from fleet config — hosts with 'lab' in their groups."""
    return [h for h in cfg.hosts if "lab" in (h.groups or "").split(",")]


def _ssh(cfg, ip, command, timeout=LAB_CMD_TIMEOUT):
    """SSH to a lab host."""
    return ssh_run(
        host=ip,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="linux",
        use_sudo=False,
    )


def cmd_lab(cfg: FreqConfig, pack, args) -> int:
    """Lab environment management."""
    action = getattr(args, "action", None)

    routes = {
        "status": _cmd_status,
        "media": _cmd_media,
        "resize": _cmd_resize,
        "rebuild": _cmd_rebuild,
        "deploy": _cmd_media,
    }

    handler = routes.get(action)
    if handler:
        return handler(cfg, args)

    if not action:
        return _cmd_status(cfg, args)

    fmt.error(f"Unknown lab action: {action}")
    fmt.info("Available: status, media deploy, resize, rebuild")
    return 1


def _cmd_status(cfg, args) -> int:
    """Show all lab VMs, specs, and connectivity."""
    fmt.header("Lab Status")
    fmt.blank()

    lab_hosts = _get_lab_hosts(cfg)
    if not lab_hosts:
        fmt.line(f"{fmt.C.YELLOW}No lab hosts found.{fmt.C.RESET}")
        fmt.blank()
        fmt.info("Add hosts with group 'lab' to hosts.toml.")
        fmt.info("Example: 192.168.1.50  my-lab-vm  linux  lab")
        fmt.blank()
        fmt.footer()
        return 0

    # Ping all lab hosts
    fmt.line(f"{fmt.C.BOLD}Checking lab fleet...{fmt.C.RESET}")
    fmt.blank()

    fmt.table_header(
        ("HOST", 14),
        ("IP", 14),
        ("STATUS", 8),
        ("TYPE", 10),
        ("UPTIME", 16),
    )

    up = 0
    down = 0

    for host in lab_hosts:
        r = _ssh(cfg, host.ip, "uptime -p 2>/dev/null || echo unknown", timeout=LAB_QUICK_TIMEOUT)
        if r.returncode == 0:
            up += 1
            uptime = r.stdout.strip().replace("up ", "")[:16]
            fmt.table_row(
                (f"{fmt.C.BOLD}{host.label}{fmt.C.RESET}", 14),
                (host.ip, 14),
                (fmt.badge("up"), 8),
                (host.htype, 10),
                (uptime, 16),
            )
        else:
            down += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{host.label}{fmt.C.RESET}", 14),
                (host.ip, 14),
                (fmt.badge("down"), 8),
                (host.htype, 10),
                ("—", 16),
            )

    fmt.blank()

    # Docker containers on docker-dev (if configured)
    docker_dev_ip = cfg.docker_dev_ip
    if docker_dev_ip:
        r = _ssh(cfg, docker_dev_ip, "docker ps --format '{{.Names}}|{{.Status}}' 2>/dev/null", timeout=LAB_API_TIMEOUT)
        if r.returncode == 0 and r.stdout.strip():
            containers = r.stdout.strip().split("\n")
            fmt.divider(f"docker-dev Containers ({len(containers)})")
            fmt.blank()
            for line in containers:
                parts = line.split("|", 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    status = parts[1].strip()
                    badge = fmt.badge("up") if "Up" in status else fmt.badge("down")
                    print(f"    {badge} {fmt.C.BOLD}{name}{fmt.C.RESET}")
            fmt.blank()

    fmt.divider("Summary")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{up}{fmt.C.RESET} up  {fmt.C.RED}{down}{fmt.C.RESET} down  ({len(lab_hosts)} lab hosts)")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_media(cfg, args) -> int:
    """Deploy or check media stack on lab docker-dev."""
    service = getattr(args, "service", None) or getattr(args, "target", None)

    docker_dev_ip = cfg.docker_dev_ip
    if not docker_dev_ip:
        fmt.error("No docker_dev_ip configured.")
        fmt.info("Set docker_dev_ip in freq.toml [infrastructure] section.")
        return 1

    if service == "status" or not service or service == "deploy":
        # Check existing status
        fmt.header("Lab Media Stack")
        fmt.blank()

        r = _ssh(cfg, docker_dev_ip, "docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}' 2>/dev/null")
        if r.returncode != 0:
            fmt.error(f"Cannot reach docker-dev ({docker_dev_ip})")
            fmt.blank()
            fmt.footer()
            return 1

        if not r.stdout.strip():
            fmt.line(f"  {fmt.C.YELLOW}No containers running on docker-dev.{fmt.C.RESET}")
            fmt.blank()
            fmt.info("To deploy: freq lab media deploy")
            fmt.blank()
            fmt.footer()
            return 0

        fmt.table_header(("NAME", 16), ("STATUS", 10), ("PORTS", 30))
        for line in r.stdout.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 3:
                name = parts[0]
                status = parts[1]
                ports = parts[2][:30]
                badge = fmt.badge("up") if "Up" in status else fmt.badge("down")
                fmt.table_row(
                    (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 16),
                    (badge, 10),
                    (f"{fmt.C.DIM}{ports}{fmt.C.RESET}", 30),
                )

        fmt.blank()
        fmt.footer()
        return 0

    if service == "deploy":
        return _deploy_media_stack(cfg, docker_dev_ip)

    fmt.error(f"Unknown lab media action: {service}")
    return 1


def _deploy_media_stack(cfg, docker_dev_ip) -> int:
    """Deploy a minimal media stack to docker-dev for testing."""
    fmt.header("Deploy Lab Media Stack")
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Target:{fmt.C.RESET} docker-dev ({docker_dev_ip})")
    fmt.blank()

    tz = cfg.timezone or "UTC"

    if not getattr(cfg, "_yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Deploy media stack? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Create directories
    fmt.step_start("Creating directories")
    r = _ssh(
        cfg,
        docker_dev_ip,
        "sudo mkdir -p /opt/media-lab/{movies,tv,downloads,config/{sonarr,radarr,prowlarr}} && "
        "sudo chmod -R 777 /opt/media-lab",
        timeout=LAB_API_TIMEOUT,
    )
    fmt.step_ok("Directories created") if r.returncode == 0 else fmt.step_fail("Failed")

    # Deploy compose file
    compose = f"""version: "3.8"
services:
  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    container_name: sonarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={tz}
    volumes:
      - /opt/media-lab/config/sonarr:/config
      - /opt/media-lab/tv:/tv
      - /opt/media-lab/downloads:/downloads
    ports:
      - 8989:8989
    restart: unless-stopped

  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: radarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={tz}
    volumes:
      - /opt/media-lab/config/radarr:/config
      - /opt/media-lab/movies:/movies
      - /opt/media-lab/downloads:/downloads
    ports:
      - 7878:7878
    restart: unless-stopped

  prowlarr:
    image: lscr.io/linuxserver/prowlarr:latest
    container_name: prowlarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ={tz}
    volumes:
      - /opt/media-lab/config/prowlarr:/config
    ports:
      - 9696:9696
    restart: unless-stopped
"""

    fmt.step_start("Deploying docker-compose.yml")
    r = _ssh(
        cfg,
        docker_dev_ip,
        f"cat > /opt/media-lab/docker-compose.yml << 'FREQEOF'\n{compose}\nFREQEOF",
        timeout=LAB_API_TIMEOUT,
    )
    fmt.step_ok("Compose file deployed") if r.returncode == 0 else fmt.step_fail("Failed")

    # Create test media
    fmt.step_start("Creating test media files")
    r = _ssh(
        cfg,
        docker_dev_ip,
        "mkdir -p '/opt/media-lab/movies/Test Movie (2024)' && "
        "dd if=/dev/zero of='/opt/media-lab/movies/Test Movie (2024)/Test.Movie.2024.mkv' "
        "bs=1M count=1 2>/dev/null && "
        "mkdir -p '/opt/media-lab/tv/Test Show/Season 01' && "
        "dd if=/dev/zero of='/opt/media-lab/tv/Test Show/Season 01/S01E01.mkv' "
        "bs=1M count=1 2>/dev/null",
        timeout=LAB_API_TIMEOUT,
    )
    fmt.step_ok("Test media created") if r.returncode == 0 else fmt.step_fail("Failed")

    # Start stack
    fmt.step_start("Starting media stack")
    r = _ssh(cfg, docker_dev_ip, "cd /opt/media-lab && docker compose up -d", timeout=LAB_LONG_TIMEOUT)
    if r.returncode == 0:
        fmt.step_ok("Media stack running")
    else:
        fmt.step_fail(f"Start failed: {r.stderr[:60]}")

    fmt.blank()
    fmt.info("WebUIs:")
    fmt.info(f"  Sonarr:   http://{docker_dev_ip}:8989")
    fmt.info(f"  Radarr:   http://{docker_dev_ip}:7878")
    fmt.info(f"  Prowlarr: http://{docker_dev_ip}:9696")
    fmt.blank()
    fmt.footer()

    logger.info("lab media deploy", target=docker_dev_ip)
    return 0


def _cmd_resize(cfg, args) -> int:
    """Resize a lab VM to minimum viable specs."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq lab resize <vmid> [--min]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    min_mode = getattr(args, "min", False)

    # Find PVE node
    from freq.modules.vm import _find_node, _pve_cmd

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        return 1

    fmt.header(f"Lab Resize: VM {vmid}")
    fmt.blank()

    if min_mode:
        cores = 2
        ram = 2048
        fmt.line(f"  Setting minimum specs: {cores} cores, {ram}MB RAM")
    else:
        cores = getattr(args, "cores", 2)
        ram = getattr(args, "ram", 2048)
        fmt.line(f"  Setting: {cores} cores, {ram}MB RAM")

    fmt.blank()

    fmt.step_start(f"Resizing VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm set {vmid} --cores {cores} --memory {ram}")
    if ok:
        fmt.step_ok(f"VM {vmid} resized to {cores} cores / {ram}MB")
    else:
        fmt.step_fail(f"Resize failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1


def _cmd_rebuild(cfg, args) -> int:
    """Destroy and recreate a lab VM from template."""
    target = getattr(args, "target", None)
    template = getattr(args, "template", None)

    if not target:
        fmt.error("Usage: freq lab rebuild <vmid> [--template <template_vmid>]")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    from freq.modules.vm import _find_node, _pve_cmd, _safety_check

    if not _safety_check(cfg, vmid, "rebuild"):
        return 1

    node_ip = _find_node(cfg)
    if not node_ip:
        fmt.error("Cannot reach any PVE node")
        return 1

    fmt.header(f"Lab Rebuild: VM {vmid}")
    fmt.blank()
    fmt.line(f"  {fmt.C.RED}{fmt.C.BOLD}WARNING: This will destroy VM {vmid} and recreate it.{fmt.C.RESET}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.RED}Type VMID to confirm:{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != str(vmid):
            fmt.info("Cancelled.")
            return 0

    # Get current name before destroying
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm config {vmid}")
    vm_name = "lab-rebuild"
    if ok:
        for line in stdout.split("\n"):
            if line.startswith("name:"):
                vm_name = line.split(":", 1)[1].strip()
                break

    # Destroy
    fmt.step_start(f"Stopping VM {vmid}")
    _pve_cmd(cfg, node_ip, f"qm stop {vmid}", timeout=LAB_DOCKER_TIMEOUT)
    fmt.step_ok("Stopped")

    fmt.step_start(f"Destroying VM {vmid}")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm destroy {vmid} --purge", timeout=LAB_LONG_TIMEOUT)
    if ok:
        fmt.step_ok("Destroyed")
    else:
        fmt.step_fail(f"Destroy failed: {stdout}")
        return 1

    # Recreate from template or as blank
    if template:
        fmt.step_start(f"Cloning from template {template}")
        stdout, ok = _pve_cmd(
            cfg, node_ip, f"qm clone {template} {vmid} --name {vm_name} --full", timeout=LAB_BUILD_TIMEOUT
        )
    else:
        fmt.step_start(f"Creating blank VM {vmid}")
        stdout, ok = _pve_cmd(
            cfg,
            node_ip,
            f"qm create {vmid} --name {vm_name} --cores 2 --memory 2048 --net0 virtio,bridge={cfg.nic_bridge}",
            timeout=LAB_DOCKER_TIMEOUT,
        )

    if ok:
        fmt.step_ok(f"VM {vmid} '{vm_name}' recreated")
        logger.info(f"lab rebuild: {vmid} {vm_name}")
    else:
        fmt.step_fail(f"Create failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1
