"""Media stack management for FREQ.

Domain: freq media <status|restart|update|logs|backup|health|config>

Manages Docker containers across multiple VMs: Plex, Sonarr, Radarr,
Prowlarr, qBittorrent, SABnzbd, Tdarr, Bazarr, Overseerr, Tautulli, and
more. Container registry maps every container to its VM. API access via SSH
tunnel to localhost — no direct port exposure.

Replaces: Portainer ($0 but 3-node paywall), manual docker-compose per VM,
          SSH-and-pray container management

Architecture:
    - Container registry loaded from conf/containers.toml
    - API calls via SSH tunnel: SSH to VM, curl localhost:port
    - Docker operations (restart, update, logs) via SSH + docker CLI
    - Vault integration for API keys (Sonarr, Radarr, etc.)

Design decisions:
    - SSH tunnel for API access, not direct exposure. Media containers stay
      on localhost. FREQ reaches them through the fleet SSH transport.
"""

import json
import os
import shlex
import subprocess
import time

from freq.core import fmt
from freq.core import resolve
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Timeout constants (seconds)
API_TIMEOUT = 10
API_QUICK_TIMEOUT = 5
API_SLOW_TIMEOUT = 15
DOCKER_CMD_TIMEOUT = 30
DOCKER_ACTION_TIMEOUT = 60
DOCKER_LONG_TIMEOUT = 120
DOCKER_BUILD_TIMEOUT = 300
SCP_TIMEOUT = 30
SSH_CMD_TIMEOUT = 10
VPN_CHECK_TIMEOUT = 3


# --- Helpers ---


def _get_vault_credential(cfg, vault_key):
    """Try to get a credential from vault. Returns empty string on failure."""
    if not vault_key:
        return ""
    try:
        from freq.modules.vault import vault_get

        return vault_get(cfg, "DEFAULT", vault_key) or ""
    except (ImportError, OSError) as e:
        logger.warn(f"vault credential lookup failed for {vault_key}: {e}")
        return ""


def _api_call(
    cfg,
    vm,
    port,
    endpoint,
    method="GET",
    auth_header="",
    auth_value="",
    auth_param="",
    auth_param_value="",
    body="",
    timeout=API_TIMEOUT,
):
    """SSH to a VM and curl a local API endpoint. Returns CmdResult."""
    url = f"http://localhost:{port}{endpoint}"
    if auth_param and auth_param_value:
        sep = "&" if "?" in url else "?"
        url += f"{sep}{auth_param}={auth_param_value}"

    curl_cmd = f"curl -s --connect-timeout 3 -X {shlex.quote(method)}"
    if auth_header and auth_value:
        # Escape header values to prevent injection via quotes
        safe_header = f"{auth_header}: {auth_value}".replace("'", "'\\''")
        curl_cmd += f" -H '{safe_header}'"
    if body:
        safe_body = body.replace("'", "'\\''")
        curl_cmd += f" -H 'Content-Type: application/json' -d '{safe_body}'"
    curl_cmd += f" '{url}'"

    return ssh_run(
        host=vm.ip,
        command=curl_cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="docker",
        use_sudo=False,
    )


def _api_call_authed(cfg, vm, container, endpoint, method="GET", body="", timeout=API_TIMEOUT):
    """API call with automatic auth from container registry + vault."""
    auth_header = ""
    auth_value = ""
    auth_param = ""
    auth_param_value = ""

    if container.vault_key:
        cred = _get_vault_credential(cfg, container.vault_key)
        if cred:
            if container.auth_type == "header":
                auth_header = container.auth_header
                auth_value = cred
            elif container.auth_type == "param":
                auth_param = container.auth_param
                auth_param_value = cred

    return _api_call(
        cfg,
        vm,
        container.port,
        endpoint,
        method=method,
        auth_header=auth_header,
        auth_value=auth_value,
        auth_param=auth_param,
        auth_param_value=auth_param_value,
        body=body,
        timeout=timeout,
    )


def _docker_cmd(cfg, vm, command, timeout=DOCKER_CMD_TIMEOUT):
    """Run a docker command on a VM via SSH."""
    return ssh_run(
        host=vm.ip,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="docker",
        use_sudo=False,
    )


def _find_container(cfg, service):
    """Find a container and its VM by service name. Returns (Container, ContainerVM) or (None, None)."""
    return resolve.container_by_name(cfg.container_vms, service)


def _all_vms(cfg):
    """Get all container VMs sorted by ID."""
    return sorted(cfg.container_vms.values(), key=lambda v: v.vm_id)


def _parse_json(text):
    """Safely parse JSON. Returns None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _get_containers_status(cfg, vm):
    """Get all running containers on a VM. Returns dict of name->status."""
    r = _docker_cmd(cfg, vm, "docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null")
    containers = {}
    if r.returncode == 0 and r.stdout.strip():
        for line in r.stdout.strip().split("\n"):
            parts = line.split("|", 1)
            if len(parts) == 2:
                containers[parts[0].strip()] = parts[1].strip()
    return containers


# --- Entry Point ---


def cmd_media(cfg: FreqConfig, pack, args) -> int:
    """Media stack management — routes to subcommands."""
    action = getattr(args, "action", None)
    service = getattr(args, "service", None)

    if not cfg.container_vms:
        # Fallback: try docker host from fleet
        docker_hosts = resolve.by_type(cfg.hosts, "docker")
        if not docker_hosts:
            fmt.error("No container VMs configured. Add containers.toml to conf/.")
            return 1
        return _media_overview_legacy(cfg, docker_hosts[0])

    routes = {
        # Lifecycle
        "status": _cmd_status,
        "restart": _cmd_restart,
        "stop": _cmd_stop,
        "start": _cmd_start,
        "logs": _cmd_logs,
        "stats": _cmd_stats,
        # Updates
        "update": _cmd_update,
        "prune": _cmd_prune,
        # Backup
        "backup": _cmd_backup,
        "restore": _cmd_restore,
        # Health
        "health": _cmd_health,
        "doctor": _cmd_doctor,
        "queue": _cmd_queue,
        "streams": _cmd_streams,
        "vpn": _cmd_vpn,
        "disk": _cmd_disk,
        # Library
        "missing": _cmd_missing,
        "search": _cmd_search,
        "scan": _cmd_scan,
        "activity": _cmd_activity,
        "wanted": _cmd_wanted,
        # Indexers
        "indexers": _cmd_indexers,
        # Downloads
        "downloads": _cmd_downloads,
        # Transcode
        "transcode": _cmd_transcode,
        # Subtitles
        "subtitles": _cmd_subtitles,
        # Requests
        "requests": _cmd_requests,
        # Stack ops
        "nuke": _cmd_nuke,
        "export": _cmd_export,
        # Dashboard
        "dashboard": _cmd_dashboard,
        "report": _cmd_report,
        # Compose audit
        "compose": _cmd_compose,
        # Mounts
        "mounts": _cmd_mounts,
        # Additional
        "unmonitored": _cmd_unmonitored,
        "password": _cmd_password,
        "import": _cmd_import,
        # Cleanup
        "cleanup": _cmd_cleanup,
        # GPU
        "gpu": _cmd_gpu,
    }

    if action and action in routes:
        return routes[action](cfg, args)

    # Default: overview
    return _cmd_status(cfg, args)


# ============================================================================
# Container Lifecycle
# ============================================================================


def _cmd_status(cfg, args) -> int:
    """All containers across all VMs with up/down and API health."""
    fmt.header("Media Stack Status", "PVE FREQ")
    fmt.blank()

    total_up = 0
    total_down = 0
    total_containers = 0

    for vm in _all_vms(cfg):
        running = _get_containers_status(cfg, vm)
        if not vm.containers:
            continue

        fmt.divider(f"VM {vm.vm_id} — {vm.label} ({vm.ip})")
        fmt.blank()
        fmt.table_header(
            ("SERVICE", 14),
            ("CONTAINER", 10),
            ("API", 8),
            ("DETAIL", 30),
        )

        for cname, container in sorted(vm.containers.items()):
            total_containers += 1
            # Find matching running container
            cstatus = None
            for rname, rstatus in running.items():
                if cname.lower() in rname.lower() or rname.lower() in cname.lower():
                    cstatus = rstatus
                    break

            if cstatus is None:
                total_down += 1
                fmt.table_row(
                    (f"{fmt.C.BOLD}{cname}{fmt.C.RESET}", 14),
                    (fmt.badge("down"), 10),
                    (f"{fmt.C.DIM}-{fmt.C.RESET}", 8),
                    (f"{fmt.C.DIM}not found{fmt.C.RESET}", 30),
                )
                continue

            is_up = "Up" in cstatus
            container_badge = fmt.badge("up") if is_up else fmt.badge("down")

            if is_up:
                total_up += 1
            else:
                total_down += 1

            # API health check
            api_badge = f"{fmt.C.DIM}-{fmt.C.RESET}"
            detail = cstatus[:30]

            if is_up and container.port > 0 and container.api_path:
                r = _api_call(cfg, vm, container.port, container.api_path, timeout=API_QUICK_TIMEOUT)
                if r.returncode == 0:
                    stdout = r.stdout.strip()
                    # Check for HTTP-like response or valid JSON
                    if stdout and (
                        stdout.startswith("{") or stdout.startswith("[") or stdout.startswith("<") or len(stdout) > 0
                    ):
                        api_badge = fmt.badge("ok")
                        detail = f"port {container.port} responding"
                    else:
                        api_badge = fmt.badge("warn")
                        detail = f"port {container.port} empty response"
                elif r.returncode != 0 and "401" in r.stdout:
                    api_badge = fmt.badge("ok")
                    detail = f"port {container.port} (auth required)"
                else:
                    api_badge = fmt.badge("down")
                    detail = f"port {container.port} not responding"

            fmt.table_row(
                (f"{fmt.C.BOLD}{cname}{fmt.C.RESET}", 14),
                (container_badge, 10),
                (api_badge, 8),
                (detail, 30),
            )

        fmt.blank()

    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{total_up}{fmt.C.RESET} running  "
        f"{fmt.C.RED}{total_down}{fmt.C.RESET} down  "
        f"({total_containers} total across {len(cfg.container_vms)} VMs)"
    )
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_restart(cfg, args) -> int:
    """Restart a container or all containers."""
    service = getattr(args, "service", None)

    if service and service.lower() == "all":
        return _rolling_restart(cfg)

    if not service:
        fmt.error("Usage: freq media restart <service|all>")
        return 1

    container, vm = _find_container(cfg, service)
    if not container:
        fmt.error(f"Container not found: {service}")
        return 1

    fmt.header(f"Restart: {container.name}")
    fmt.blank()
    fmt.step_start(f"Restarting {container.name} on {vm.label}")

    r = _docker_cmd(cfg, vm, f"docker restart {container.name}", timeout=DOCKER_ACTION_TIMEOUT)
    if r.returncode == 0:
        fmt.step_ok(f"{container.name} restarted")
        logger.info(f"media restart: {container.name}", vm=vm.label)
    else:
        fmt.step_fail(f"Restart failed: {r.stderr}")

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


def _cmd_stop(cfg, args) -> int:
    """Stop a container."""
    service = getattr(args, "service", None)
    if not service:
        fmt.error("Usage: freq media stop <service>")
        return 1

    container, vm = _find_container(cfg, service)
    if not container:
        fmt.error(f"Container not found: {service}")
        return 1

    fmt.header(f"Stop: {container.name}")
    fmt.blank()
    fmt.step_start(f"Stopping {container.name} on {vm.label}")

    r = _docker_cmd(cfg, vm, f"docker stop {container.name}", timeout=DOCKER_ACTION_TIMEOUT)
    if r.returncode == 0:
        fmt.step_ok(f"{container.name} stopped")
    else:
        fmt.step_fail(f"Stop failed: {r.stderr}")

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


def _cmd_start(cfg, args) -> int:
    """Start a container."""
    service = getattr(args, "service", None)
    if not service:
        fmt.error("Usage: freq media start <service>")
        return 1

    container, vm = _find_container(cfg, service)
    if not container:
        fmt.error(f"Container not found: {service}")
        return 1

    fmt.header(f"Start: {container.name}")
    fmt.blank()
    fmt.step_start(f"Starting {container.name} on {vm.label}")

    r = _docker_cmd(cfg, vm, f"docker start {container.name}", timeout=DOCKER_ACTION_TIMEOUT)
    if r.returncode == 0:
        fmt.step_ok(f"{container.name} started")
    else:
        fmt.step_fail(f"Start failed: {r.stderr}")

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


def _cmd_logs(cfg, args) -> int:
    """Show container logs with optional filtering."""
    service = getattr(args, "service", None)
    if not service:
        fmt.error("Usage: freq media logs <service> [--lines N] [--errors] [--since 1h]")
        return 1

    container, vm = _find_container(cfg, service)
    if not container:
        fmt.error(f"Container not found: {service}")
        return 1

    lines = getattr(args, "lines", 50) or 50
    errors_only = getattr(args, "errors", False)
    since = getattr(args, "since", None)

    fmt.header(f"Logs: {container.name}")
    fmt.blank()

    docker_args = f"--tail {lines}"
    if since:
        docker_args += f" --since {since}"

    r = _docker_cmd(cfg, vm, f"docker logs {docker_args} {container.name} 2>&1", timeout=API_SLOW_TIMEOUT)
    if r.returncode == 0 and r.stdout:
        for line in r.stdout.split("\n"):
            is_error = "error" in line.lower() or "fail" in line.lower() or "fatal" in line.lower()
            is_warn = "warn" in line.lower()

            if errors_only and not is_error and not is_warn:
                continue

            if is_error:
                print(f"  {fmt.C.RED}{line}{fmt.C.RESET}")
            elif is_warn:
                print(f"  {fmt.C.YELLOW}{line}{fmt.C.RESET}")
            else:
                print(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    else:
        fmt.line(f"{fmt.C.RED}Cannot retrieve logs.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_stats(cfg, args) -> int:
    """Docker stats across all VMs."""
    fmt.header("Container Stats")
    fmt.blank()

    for vm in _all_vms(cfg):
        if not vm.containers:
            continue
        r = _docker_cmd(
            cfg,
            vm,
            "docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}' 2>/dev/null",
            timeout=API_SLOW_TIMEOUT,
        )
        if r.returncode != 0 or not r.stdout.strip():
            continue

        fmt.divider(f"{vm.label} ({vm.ip})")
        fmt.blank()
        fmt.table_header(
            ("NAME", 16),
            ("CPU", 8),
            ("MEMORY", 20),
            ("NET I/O", 20),
        )

        for line in r.stdout.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 4:
                fmt.table_row(
                    (f"{fmt.C.BOLD}{parts[0]}{fmt.C.RESET}", 16),
                    (parts[1], 8),
                    (parts[2], 20),
                    (parts[3], 20),
                )
        fmt.blank()

    fmt.footer()
    return 0


# ============================================================================
# Updates
# ============================================================================


def _cmd_update(cfg, args) -> int:
    """Update container images via docker-compose."""
    service = getattr(args, "service", None)
    check_only = getattr(args, "check", False)

    if check_only:
        return _update_check(cfg)

    if service and service.lower() == "all":
        return _update_all(cfg)

    if not service:
        fmt.error("Usage: freq media update <service|all> [--check]")
        return 1

    container, vm = _find_container(cfg, service)
    if not container:
        fmt.error(f"Container not found: {service}")
        return 1

    fmt.header(f"Update: {container.name}")
    fmt.blank()

    if not vm.compose_path:
        fmt.error(f"No compose path for VM {vm.vm_id}")
        return 1

    compose_dir = vm.compose_path.rsplit("/", 1)[0]
    fmt.step_start(f"Pulling latest image for {container.name}")
    r = _docker_cmd(cfg, vm, f"cd {compose_dir} && docker compose pull {container.name}", timeout=DOCKER_LONG_TIMEOUT)
    if r.returncode != 0:
        fmt.step_fail(f"Pull failed: {r.stderr}")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok("Image pulled")

    fmt.step_start(f"Recreating {container.name}")
    r = _docker_cmd(
        cfg, vm, f"cd {compose_dir} && docker compose up -d {container.name}", timeout=DOCKER_ACTION_TIMEOUT
    )
    if r.returncode == 0:
        fmt.step_ok(f"{container.name} updated and running")
        logger.info(f"media update: {container.name}", vm=vm.label)
    else:
        fmt.step_fail(f"Recreate failed: {r.stderr}")

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


def _update_check(cfg) -> int:
    """Check for available image updates."""
    fmt.header("Update Check")
    fmt.blank()
    fmt.table_header(("SERVICE", 16), ("CURRENT", 30), ("VM", 12))

    for vm in _all_vms(cfg):
        for cname in vm.containers:
            r = _docker_cmd(cfg, vm, f"docker inspect --format '{{{{.Config.Image}}}}' {cname} 2>/dev/null")
            image = r.stdout.strip() if r.returncode == 0 else "unknown"
            fmt.table_row(
                (f"{fmt.C.BOLD}{cname}{fmt.C.RESET}", 16),
                (image[:30], 30),
                (vm.label[:12], 12),
            )

    fmt.blank()
    fmt.info("Run 'freq media update <service>' to pull latest.")
    fmt.blank()
    fmt.footer()
    return 0


def _update_all(cfg) -> int:
    """Update all containers across all VMs."""
    fmt.header("Update All Containers")
    fmt.blank()

    for vm in _all_vms(cfg):
        if not vm.compose_path:
            continue
        compose_dir = vm.compose_path.rsplit("/", 1)[0]
        fmt.step_start(f"Updating {vm.label} ({vm.ip})")
        r = _docker_cmd(
            cfg, vm, f"cd {compose_dir} && docker compose pull && docker compose up -d", timeout=DOCKER_BUILD_TIMEOUT
        )
        if r.returncode == 0:
            fmt.step_ok(f"{vm.label} updated")
        else:
            fmt.step_fail(f"{vm.label} failed: {r.stderr[:60]}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_prune(cfg, args) -> int:
    """Docker system prune on all VMs."""
    fmt.header("Docker Prune")
    fmt.blank()

    for vm in _all_vms(cfg):
        fmt.step_start(f"Pruning {vm.label}")
        r = _docker_cmd(cfg, vm, "docker system prune -f 2>&1", timeout=DOCKER_ACTION_TIMEOUT)
        if r.returncode == 0:
            # Extract space reclaimed
            for line in r.stdout.split("\n"):
                if "reclaimed" in line.lower():
                    fmt.step_ok(f"{vm.label}: {line.strip()}")
                    break
            else:
                fmt.step_ok(f"{vm.label} pruned")
        else:
            fmt.step_fail(f"{vm.label}: {r.stderr[:40]}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Backup & Restore
# ============================================================================


def _cmd_backup(cfg, args) -> int:
    """Backup container config directory."""
    service = getattr(args, "service", None)
    list_mode = getattr(args, "list", False)

    if list_mode or not service:
        return _backup_list(cfg)

    container, vm = _find_container(cfg, service)
    if not container:
        fmt.error(f"Container not found: {service}")
        return 1

    fmt.header(f"Backup: {container.name}")
    fmt.blank()

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_name = f"{container.name}-{timestamp}.tar.gz"
    config_base = cfg.docker_config_base
    backup_dir = cfg.docker_backup_dir
    if not config_base or not backup_dir:
        fmt.error("docker_config_base and docker_backup_dir must be set in freq.toml [infrastructure]")
        return 1
    config_dir = f"{config_base}/{container.name}"

    fmt.step_start(f"Stopping {container.name}")
    _docker_cmd(cfg, vm, f"docker stop {container.name}", timeout=DOCKER_ACTION_TIMEOUT)
    fmt.step_ok("Stopped")

    fmt.step_start(f"Creating backup {backup_name}")
    r = _docker_cmd(
        cfg,
        vm,
        f"mkdir -p {backup_dir} && tar czf {backup_dir}/{backup_name} -C {config_dir} . 2>&1",
        timeout=DOCKER_LONG_TIMEOUT,
    )
    if r.returncode == 0:
        fmt.step_ok(f"Backup saved: {backup_dir}/{backup_name}")
    else:
        fmt.step_fail(f"Backup failed: {r.stderr}")

    fmt.step_start(f"Starting {container.name}")
    _docker_cmd(cfg, vm, f"docker start {container.name}", timeout=DOCKER_ACTION_TIMEOUT)
    fmt.step_ok("Started")

    fmt.blank()
    fmt.footer()
    return 0


def _backup_list(cfg) -> int:
    """List available backups across all VMs."""
    fmt.header("Media Backups")
    fmt.blank()
    backup_dir = cfg.docker_backup_dir
    if not backup_dir:
        fmt.error("docker_backup_dir must be set in freq.toml [infrastructure]")
        return 1

    for vm in _all_vms(cfg):
        r = _docker_cmd(
            cfg, vm, f'ls -lh {backup_dir}/*.tar.gz 2>/dev/null | awk \'{{print $NF"|"$5"|"$6" "$7" "$8}}\''
        )
        if r.returncode != 0 or not r.stdout.strip():
            continue

        fmt.divider(f"{vm.label}")
        fmt.blank()
        for line in r.stdout.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 2:
                name = parts[0].split("/")[-1]
                size = parts[1] if len(parts) > 1 else "?"
                date = parts[2] if len(parts) > 2 else ""
                fmt.line(f"  {fmt.C.BOLD}{name}{fmt.C.RESET}  {size}  {fmt.C.DIM}{date}{fmt.C.RESET}")
        fmt.blank()

    fmt.footer()
    return 0


def _cmd_restore(cfg, args) -> int:
    """Restore a container from backup."""
    service = getattr(args, "service", None)
    if not service:
        fmt.error("Usage: freq media restore <service>")
        return 1

    container, vm = _find_container(cfg, service)
    if not container:
        fmt.error(f"Container not found: {service}")
        return 1

    fmt.header(f"Restore: {container.name}")
    fmt.blank()
    backup_dir = cfg.docker_backup_dir
    config_base = cfg.docker_config_base
    if not backup_dir or not config_base:
        fmt.error("docker_config_base and docker_backup_dir must be set in freq.toml [infrastructure]")
        return 1

    # List available backups
    r = _docker_cmd(cfg, vm, f"ls -1t {backup_dir}/{container.name}-*.tar.gz 2>/dev/null")
    if r.returncode != 0 or not r.stdout.strip():
        fmt.error(f"No backups found for {container.name}")
        fmt.blank()
        fmt.footer()
        return 1

    backups = r.stdout.strip().split("\n")
    fmt.line(f"  Available backups for {fmt.C.BOLD}{container.name}{fmt.C.RESET}:")
    fmt.blank()
    for i, b in enumerate(backups[:10], 1):
        name = b.split("/")[-1]
        fmt.line(f"  {fmt.C.CYAN}[{i}]{fmt.C.RESET}  {name}")

    fmt.blank()
    try:
        choice = input(f"  {fmt.C.CYAN}Select backup [1]:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    idx = int(choice) - 1 if choice.isdigit() else 0
    if idx < 0 or idx >= len(backups):
        idx = 0

    backup_path = backups[idx]
    config_dir = f"{config_base}/{container.name}"

    fmt.step_start(f"Stopping {container.name}")
    _docker_cmd(cfg, vm, f"docker stop {container.name}", timeout=DOCKER_ACTION_TIMEOUT)
    fmt.step_ok("Stopped")

    fmt.step_start(f"Restoring from {backup_path.split('/')[-1]}")
    r = _docker_cmd(cfg, vm, f"tar xzf {backup_path} -C {config_dir} 2>&1", timeout=DOCKER_LONG_TIMEOUT)
    if r.returncode == 0:
        fmt.step_ok("Restored")
    else:
        fmt.step_fail(f"Restore failed: {r.stderr}")

    fmt.step_start(f"Starting {container.name}")
    _docker_cmd(cfg, vm, f"docker start {container.name}", timeout=DOCKER_ACTION_TIMEOUT)
    fmt.step_ok("Started")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Health & Monitoring
# ============================================================================


def _cmd_health(cfg, args) -> int:
    """API health check for all services."""
    fmt.header("Media Health")
    fmt.blank()
    fmt.table_header(
        ("SERVICE", 14),
        ("VM", 14),
        ("API", 8),
        ("STATUS", 30),
    )

    ok_count = 0
    fail_count = 0

    for vm in _all_vms(cfg):
        for cname, container in sorted(vm.containers.items()):
            if not container.port or not container.api_path:
                continue

            r = _api_call_authed(
                cfg,
                vm,
                container,
                container.api_path + "/system/status" if "/api/" in container.api_path else container.api_path,
                timeout=API_QUICK_TIMEOUT,
            )

            if r.returncode == 0 and r.stdout.strip():
                ok_count += 1
                status = "healthy"
                badge = fmt.badge("ok")
            else:
                fail_count += 1
                status = "unreachable"
                badge = fmt.badge("down")

            fmt.table_row(
                (f"{fmt.C.BOLD}{cname}{fmt.C.RESET}", 14),
                (vm.label[:14], 14),
                (badge, 8),
                (status, 30),
            )

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{ok_count}{fmt.C.RESET} healthy  {fmt.C.RED}{fail_count}{fmt.C.RESET} down")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_doctor(cfg, args) -> int:
    """Comprehensive media stack diagnostic."""
    fmt.header("Media Doctor")
    fmt.blank()

    issues = []

    # Check 1: Container status
    fmt.line(f"{fmt.C.PURPLE_BOLD}Container Status{fmt.C.RESET}")
    for vm in _all_vms(cfg):
        running = _get_containers_status(cfg, vm)
        for cname in vm.containers:
            found = any(cname.lower() in rn.lower() for rn in running)
            if found:
                status = next((v for k, v in running.items() if cname.lower() in k.lower()), "")
                if "Up" in status:
                    print(f"    {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {cname} ({vm.label})")
                else:
                    print(f"    {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {cname} ({vm.label}) — {status}")
                    issues.append(f"{cname} not running on {vm.label}")
            else:
                print(f"    {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {cname} ({vm.label}) — not found")
                issues.append(f"{cname} not found on {vm.label}")
    fmt.blank()

    # Check 2: Disk usage
    fmt.line(f"{fmt.C.PURPLE_BOLD}Disk Usage{fmt.C.RESET}")
    for vm in _all_vms(cfg):
        r = _docker_cmd(cfg, vm, "df -h / | awk 'NR==2 {print $5}'")
        if r.returncode == 0:
            pct = r.stdout.strip()
            try:
                val = int(pct.replace("%", ""))
                color = fmt.C.RED if val >= 90 else fmt.C.YELLOW if val >= 75 else fmt.C.GREEN
                sym = fmt.S.CROSS if val >= 90 else fmt.S.WARN if val >= 75 else fmt.S.TICK
                print(f"    {color}{sym}{fmt.C.RESET} {vm.label}: {pct}")
                if val >= 90:
                    issues.append(f"{vm.label} disk at {pct}")
            except ValueError:
                print(f"    {fmt.C.DIM}? {vm.label}: {pct}{fmt.C.RESET}")
    fmt.blank()

    # Check 3: NFS mounts
    fmt.line(f"{fmt.C.PURPLE_BOLD}NFS Mounts{fmt.C.RESET}")
    for vm in _all_vms(cfg):
        r = _docker_cmd(cfg, vm, "mount | grep nfs 2>/dev/null")
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n"):
                print(f"    {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {vm.label}: {line.split()[2]}")
        else:
            print(f"    {fmt.C.DIM}- {vm.label}: no NFS mounts{fmt.C.RESET}")
    fmt.blank()

    # Summary
    fmt.divider("Diagnosis")
    fmt.blank()
    if issues:
        fmt.line(f"  {fmt.C.RED}{len(issues)} issue(s) found:{fmt.C.RESET}")
        for issue in issues:
            fmt.line(f"    {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET} {issue}")
    else:
        fmt.line(f"  {fmt.C.GREEN}All checks passed.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 1 if issues else 0


def _cmd_queue(cfg, args) -> int:
    """Show download queues from qBittorrent + SABnzbd."""
    fmt.header("Download Queue")
    fmt.blank()

    # qBittorrent instances
    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "qbittorrent" not in cname.lower():
                continue
            r = _api_call(cfg, vm, container.port, "/api/v2/torrents/info?filter=downloading", timeout=API_TIMEOUT)
            if r.returncode == 0:
                data = _parse_json(r.stdout)
                if data and isinstance(data, list):
                    fmt.divider(f"qBittorrent — {vm.label}")
                    fmt.blank()
                    if not data:
                        fmt.line(f"  {fmt.C.DIM}No active downloads.{fmt.C.RESET}")
                    else:
                        fmt.table_header(("NAME", 40), ("SIZE", 8), ("PROGRESS", 10), ("SPEED", 10))
                        for t in data[:20]:
                            name = t.get("name", "?")[:40]
                            size = _human_size(t.get("size", 0))
                            progress = f"{t.get('progress', 0) * 100:.0f}%"
                            speed = _human_size(t.get("dlspeed", 0)) + "/s"
                            fmt.table_row(
                                (name, 40),
                                (size, 8),
                                (progress, 10),
                                (speed, 10),
                            )
                    fmt.blank()

    # SABnzbd
    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "sabnzbd" not in cname.lower():
                continue
            cred = _get_vault_credential(cfg, container.vault_key)
            if cred:
                r = _api_call(
                    cfg, vm, container.port, f"/api?mode=queue&output=json&apikey={cred}", timeout=API_TIMEOUT
                )
            else:
                r = _api_call(cfg, vm, container.port, "/api?mode=queue&output=json", timeout=API_TIMEOUT)
            if r.returncode == 0:
                data = _parse_json(r.stdout)
                if data and "queue" in data:
                    slots = data["queue"].get("slots", [])
                    fmt.divider(f"SABnzbd — {vm.label}")
                    fmt.blank()
                    if not slots:
                        fmt.line(f"  {fmt.C.DIM}No active downloads.{fmt.C.RESET}")
                    else:
                        fmt.table_header(("NAME", 40), ("SIZE", 8), ("STATUS", 10), ("ETA", 10))
                        for s in slots[:20]:
                            fmt.table_row(
                                (s.get("filename", "?")[:40], 40),
                                (s.get("size", "?"), 8),
                                (s.get("status", "?"), 10),
                                (s.get("timeleft", "?"), 10),
                            )
                    fmt.blank()

    fmt.footer()
    return 0


def _cmd_streams(cfg, args) -> int:
    """Active Plex streams via Tautulli."""
    fmt.header("Active Streams")
    fmt.blank()

    container, vm = _find_container(cfg, "tautulli")
    if not container:
        fmt.error("Tautulli not found in container registry.")
        fmt.blank()
        fmt.footer()
        return 1

    cred = _get_vault_credential(cfg, container.vault_key)
    if cred:
        r = _api_call(cfg, vm, container.port, f"/api/v2?apikey={cred}&cmd=get_activity", timeout=API_TIMEOUT)
    else:
        r = _api_call(cfg, vm, container.port, "/api/v2?cmd=get_activity", timeout=API_TIMEOUT)

    if r.returncode != 0:
        fmt.error("Cannot reach Tautulli API.")
        fmt.blank()
        fmt.footer()
        return 1

    data = _parse_json(r.stdout)
    if not data or "response" not in data:
        fmt.line(f"  {fmt.C.DIM}No stream data available.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    sessions = data.get("response", {}).get("data", {}).get("sessions", [])
    stream_count = data.get("response", {}).get("data", {}).get("stream_count", 0)

    if not sessions:
        fmt.line(f"  {fmt.C.DIM}No active streams.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.BOLD}{stream_count} active stream(s){fmt.C.RESET}")
        fmt.blank()
        fmt.table_header(("USER", 14), ("TITLE", 30), ("TYPE", 8), ("QUALITY", 12))
        for s in sessions:
            user = s.get("friendly_name", "?")[:14]
            title = s.get("full_title", s.get("title", "?"))[:30]
            media_type = s.get("media_type", "?")
            quality = s.get("quality_profile", s.get("video_resolution", "?"))
            fmt.table_row(
                (f"{fmt.C.BOLD}{user}{fmt.C.RESET}", 14),
                (title, 30),
                (media_type, 8),
                (quality, 12),
            )

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_vpn(cfg, args) -> int:
    """VPN status for Gluetun containers."""
    fmt.header("VPN Status")
    fmt.blank()

    found = False
    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "gluetun" not in cname.lower():
                continue
            found = True

            # VPN status — use container port if configured, default to 8000
            gluetun_port = getattr(container, "port", 0) or 8000
            r = _api_call(cfg, vm, gluetun_port, "/v1/openvpn/status", timeout=API_QUICK_TIMEOUT)
            vpn_status = "unknown"
            if r.returncode == 0:
                data = _parse_json(r.stdout)
                if data:
                    vpn_status = data.get("status", "unknown")

            # Public IP
            r2 = _api_call(cfg, vm, 8000, "/v1/publicip/ip", timeout=API_QUICK_TIMEOUT)
            public_ip = "unknown"
            if r2.returncode == 0:
                data2 = _parse_json(r2.stdout)
                if data2:
                    public_ip = data2.get("public_ip", data2.get("ip", "unknown"))

            color = fmt.C.GREEN if vpn_status == "running" else fmt.C.RED
            fmt.line(
                f"  {fmt.C.BOLD}{vm.label}{fmt.C.RESET}  "
                f"VPN: {color}{vpn_status}{fmt.C.RESET}  "
                f"IP: {fmt.C.CYAN}{public_ip}{fmt.C.RESET}"
            )

    if not found:
        fmt.line(f"  {fmt.C.DIM}No Gluetun containers found.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_disk(cfg, args) -> int:
    """Disk usage across all media VMs."""
    fmt.header("Media Disk Usage")
    fmt.blank()
    fmt.table_header(("VM", 16), ("DISK", 8), ("USED", 8), ("AVAIL", 8), ("USE%", 6))

    for vm in _all_vms(cfg):
        r = _docker_cmd(cfg, vm, 'df -h / | awk \'NR==2 {print $2"|"$3"|"$4"|"$5}\'')
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split("|")
            if len(parts) >= 4:
                try:
                    pct = int(parts[3].replace("%", ""))
                    color = fmt.C.RED if pct >= 90 else fmt.C.YELLOW if pct >= 75 else fmt.C.GREEN
                    pct_str = f"{color}{parts[3]}{fmt.C.RESET}"
                except ValueError:
                    pct_str = parts[3]
                fmt.table_row(
                    (f"{fmt.C.BOLD}{vm.label}{fmt.C.RESET}", 16),
                    (parts[0], 8),
                    (parts[1], 8),
                    (parts[2], 8),
                    (pct_str, 6),
                )

    # Docker disk usage
    fmt.blank()
    fmt.divider("Docker Disk")
    fmt.blank()
    for vm in _all_vms(cfg):
        r = _docker_cmd(
            cfg,
            vm,
            "docker system df --format "
            "'Images: {{.Images}} | Containers: {{.Containers}} | "
            "Volumes: {{.Volumes}} | Reclaimable: {{.Reclaimable}}' 2>/dev/null | head -1",
        )
        if r.returncode == 0 and r.stdout.strip():
            fmt.line(f"  {fmt.C.BOLD}{vm.label}{fmt.C.RESET}: {r.stdout.strip()}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Library
# ============================================================================


def _cmd_missing(cfg, args) -> int:
    """Missing episodes/movies from Sonarr + Radarr."""
    fmt.header("Missing Media")
    fmt.blank()

    # Sonarr missing
    container, vm = _find_container(cfg, "sonarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/wanted/missing?pageSize=20")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data and "records" in data:
            total = data.get("totalRecords", 0)
            fmt.divider(f"Sonarr — {total} missing episodes")
            fmt.blank()
            for rec in data["records"][:15]:
                series = rec.get("series", {}).get("title", "?")
                ep = f"S{rec.get('seasonNumber', 0):02d}E{rec.get('episodeNumber', 0):02d}"
                title = rec.get("title", "")[:30]
                fmt.line(f"  {fmt.C.BOLD}{series}{fmt.C.RESET} {ep} — {title}")
            fmt.blank()

    # Radarr missing
    container, vm = _find_container(cfg, "radarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/movie?monitored=true")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data and isinstance(data, list):
            missing = [m for m in data if not m.get("hasFile", True) and m.get("monitored", False)]
            fmt.divider(f"Radarr — {len(missing)} missing movies")
            fmt.blank()
            for m in missing[:15]:
                title = m.get("title", "?")[:40]
                year = m.get("year", "?")
                fmt.line(f"  {fmt.C.BOLD}{title}{fmt.C.RESET} ({year})")
            fmt.blank()

    fmt.footer()
    return 0


def _cmd_search(cfg, args) -> int:
    """Search Sonarr + Radarr libraries."""
    query = getattr(args, "service", None) or getattr(args, "query", None)
    if not query:
        fmt.error("Usage: freq media search <query>")
        return 1

    fmt.header(f"Search: {query}")
    fmt.blank()

    # Sonarr
    container, vm = _find_container(cfg, "sonarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/series")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data:
            matches = [s for s in data if query.lower() in s.get("title", "").lower()]
            if matches:
                fmt.divider(f"Sonarr — {len(matches)} match(es)")
                fmt.blank()
                for s in matches[:10]:
                    status = s.get("status", "?")
                    eps = f"{s.get('episodeFileCount', 0)}/{s.get('episodeCount', 0)} eps"
                    fmt.line(f"  {fmt.C.BOLD}{s.get('title', '?')}{fmt.C.RESET}  ({status}, {eps})")
                fmt.blank()

    # Radarr
    container, vm = _find_container(cfg, "radarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/movie")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data:
            matches = [m for m in data if query.lower() in m.get("title", "").lower()]
            if matches:
                fmt.divider(f"Radarr — {len(matches)} match(es)")
                fmt.blank()
                for m in matches[:10]:
                    has_file = "on disk" if m.get("hasFile") else "missing"
                    fmt.line(f"  {fmt.C.BOLD}{m.get('title', '?')}{fmt.C.RESET}  ({m.get('year', '?')}, {has_file})")
                fmt.blank()

    fmt.footer()
    return 0


def _cmd_scan(cfg, args) -> int:
    """Trigger library scan on Sonarr + Radarr."""
    fmt.header("Library Scan")
    fmt.blank()

    for svc_name in ["sonarr", "radarr"]:
        container, vm = _find_container(cfg, svc_name)
        if not container:
            continue
        fmt.step_start(f"Scanning {svc_name}")
        cmd_name = "RescanSeries" if svc_name == "sonarr" else "RescanMovie"
        r2 = _api_call_authed(cfg, vm, container, "/api/v3/command", method="POST", body=f'{{"name": "{cmd_name}"}}')
        if r2.returncode == 0:
            fmt.step_ok(f"{svc_name} scan triggered")
        else:
            fmt.step_fail(f"{svc_name} scan failed")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_activity(cfg, args) -> int:
    """Recent grabs/imports from Sonarr + Radarr."""
    fmt.header("Recent Activity")
    fmt.blank()

    for svc_name in ["sonarr", "radarr"]:
        container, vm = _find_container(cfg, svc_name)
        if not container:
            continue
        r = _api_call_authed(cfg, vm, container, "/api/v3/history?pageSize=10&sortDirection=descending&sortKey=date")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data and "records" in data:
            fmt.divider(f"{svc_name.title()} — Recent Activity")
            fmt.blank()
            for rec in data["records"][:10]:
                event = rec.get("eventType", "?")
                title = rec.get("sourceTitle", "?")[:40]
                date = rec.get("date", "")[:10]
                fmt.line(f"  {fmt.C.DIM}{date}{fmt.C.RESET} {fmt.C.CYAN}{event:>12}{fmt.C.RESET} {title}")
            fmt.blank()

    fmt.footer()
    return 0


def _cmd_wanted(cfg, args) -> int:
    """Wanted/cutoff unmet from Sonarr + Radarr."""
    fmt.header("Wanted Media")
    fmt.blank()

    # Sonarr wanted
    container, vm = _find_container(cfg, "sonarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/wanted/missing?pageSize=15")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data:
            total = data.get("totalRecords", 0)
            fmt.divider(f"Sonarr — {total} wanted")
            fmt.blank()
            for rec in data.get("records", [])[:10]:
                series = rec.get("series", {}).get("title", "?")
                ep = f"S{rec.get('seasonNumber', 0):02d}E{rec.get('episodeNumber', 0):02d}"
                fmt.line(f"  {fmt.C.BOLD}{series}{fmt.C.RESET} {ep}")
            fmt.blank()

    # Radarr wanted
    container, vm = _find_container(cfg, "radarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/movie?monitored=true")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data:
            wanted = [m for m in data if not m.get("hasFile") and m.get("monitored")]
            fmt.divider(f"Radarr — {len(wanted)} wanted")
            fmt.blank()
            for m in wanted[:10]:
                fmt.line(f"  {fmt.C.BOLD}{m.get('title', '?')}{fmt.C.RESET} ({m.get('year', '?')})")
            fmt.blank()

    fmt.footer()
    return 0


# ============================================================================
# Indexers
# ============================================================================


def _cmd_indexers(cfg, args) -> int:
    """Prowlarr indexer management — source of truth."""
    service = getattr(args, "service", None)

    container, vm = _find_container(cfg, "prowlarr")
    if not container:
        fmt.error("Prowlarr not found in container registry.")
        return 1

    if service == "test":
        return _indexers_test(cfg, vm, container)
    elif service == "sync":
        return _indexers_sync(cfg, vm, container)

    fmt.header("Indexers (Prowlarr)")
    fmt.blank()
    fmt.info("Prowlarr is SOURCE OF TRUTH for all indexers.")
    fmt.blank()

    r = _api_call_authed(cfg, vm, container, "/api/v1/indexer")
    data = _parse_json(r.stdout) if r.returncode == 0 else None
    if not data:
        fmt.error("Cannot reach Prowlarr API.")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.table_header(("NAME", 20), ("PROTOCOL", 10), ("STATUS", 10), ("PRIORITY", 8))
    for idx in data:
        name = idx.get("name", "?")[:20]
        protocol = idx.get("protocol", "?")
        enabled = "enabled" if idx.get("enable", False) else "disabled"
        badge = fmt.badge("ok") if enabled == "enabled" else fmt.badge("warn")
        priority = str(idx.get("priority", "?"))
        fmt.table_row(
            (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 20),
            (protocol, 10),
            (badge, 10),
            (priority, 8),
        )

    fmt.blank()
    fmt.footer()
    return 0


def _indexers_test(cfg, vm, container) -> int:
    """Test all indexers via Prowlarr."""
    fmt.header("Indexer Test")
    fmt.blank()

    r = _api_call_authed(cfg, vm, container, "/api/v1/indexer")
    data = _parse_json(r.stdout) if r.returncode == 0 else None
    if not data:
        fmt.error("Cannot reach Prowlarr.")
        return 1

    for idx in data:
        name = idx.get("name", "?")
        idx_id = idx.get("id")
        if not idx_id:
            continue
        fmt.step_start(f"Testing {name}")
        r2 = _api_call_authed(
            cfg, vm, container, f"/api/v1/indexer/{idx_id}/test", method="POST", timeout=API_SLOW_TIMEOUT
        )
        if r2.returncode == 0 and not r2.stdout.strip().startswith('{"isWarning'):
            fmt.step_ok(f"{name} passed")
        else:
            fmt.step_fail(f"{name} failed")

    fmt.blank()
    fmt.footer()
    return 0


def _indexers_sync(cfg, vm, container) -> int:
    """Trigger Prowlarr sync to arr apps."""
    fmt.header("Indexer Sync")
    fmt.blank()

    fmt.step_start("Triggering Prowlarr sync")
    r = _api_call_authed(
        cfg,
        vm,
        container,
        "/api/v1/command",
        method="POST",
        body='{"name": "AppIndexerSync"}',
        timeout=API_SLOW_TIMEOUT,
    )
    if r.returncode == 0:
        fmt.step_ok("Sync triggered")
    else:
        fmt.step_fail("Sync failed")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Downloads
# ============================================================================


def _cmd_downloads(cfg, args) -> int:
    """Download management across qBit + SABnzbd."""
    service = getattr(args, "service", None)

    if service == "pause":
        return _downloads_control(cfg, "pause")
    elif service == "resume":
        return _downloads_control(cfg, "resume")
    elif service == "clear":
        return _downloads_control(cfg, "clear")
    elif service == "speed":
        return _downloads_speed(cfg)

    # Default: show active downloads
    return _cmd_queue(cfg, args)


def _downloads_control(cfg, action) -> int:
    """Pause/resume/clear downloads across all clients."""
    fmt.header(f"Downloads: {action.title()}")
    fmt.blank()

    # qBittorrent
    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "qbittorrent" not in cname.lower():
                continue
            endpoint_map = {
                "pause": "/api/v2/torrents/pause?hashes=all",
                "resume": "/api/v2/torrents/resume?hashes=all",
                "clear": "/api/v2/torrents/delete?hashes=all&deleteFiles=false",
            }
            endpoint = endpoint_map.get(action, "")
            if endpoint:
                fmt.step_start(f"{action} qBit on {vm.label}")
                r = _api_call(cfg, vm, container.port, endpoint, method="POST")
                if r.returncode == 0:
                    fmt.step_ok(f"qBit {action}d")
                else:
                    fmt.step_fail(f"qBit {action} failed")

    # SABnzbd
    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "sabnzbd" not in cname.lower():
                continue
            cred = _get_vault_credential(cfg, container.vault_key)
            mode_map = {"pause": "pause", "resume": "resume", "clear": "history&name=delete&value=all"}
            mode = mode_map.get(action, "")
            if mode and cred:
                fmt.step_start(f"{action} SABnzbd on {vm.label}")
                r = _api_call(cfg, vm, container.port, f"/api?mode={mode}&apikey={cred}&output=json")
                if r.returncode == 0:
                    fmt.step_ok(f"SABnzbd {action}d")
                else:
                    fmt.step_fail(f"SABnzbd {action} failed")

    fmt.blank()
    fmt.footer()
    return 0


def _downloads_speed(cfg) -> int:
    """Current download speeds."""
    fmt.header("Download Speeds")
    fmt.blank()

    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "qbittorrent" not in cname.lower():
                continue
            r = _api_call(cfg, vm, container.port, "/api/v2/transfer/info")
            data = _parse_json(r.stdout) if r.returncode == 0 else None
            if data:
                dl = _human_size(data.get("dl_info_speed", 0)) + "/s"
                ul = _human_size(data.get("up_info_speed", 0)) + "/s"
                fmt.line(
                    f"  {fmt.C.BOLD}{vm.label}{fmt.C.RESET} qBit  "
                    f"{fmt.C.GREEN}DL: {dl}{fmt.C.RESET}  "
                    f"{fmt.C.CYAN}UL: {ul}{fmt.C.RESET}"
                )

    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "sabnzbd" not in cname.lower():
                continue
            cred = _get_vault_credential(cfg, container.vault_key)
            if cred:
                r = _api_call(cfg, vm, container.port, f"/api?mode=queue&output=json&apikey={cred}")
                data = _parse_json(r.stdout) if r.returncode == 0 else None
                if data and "queue" in data:
                    speed = data["queue"].get("speed", "0")
                    fmt.line(f"  {fmt.C.BOLD}{vm.label}{fmt.C.RESET} SABnzbd  {fmt.C.GREEN}DL: {speed}{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Transcode
# ============================================================================


def _cmd_transcode(cfg, args) -> int:
    """Tdarr transcode management."""
    service = getattr(args, "service", None)

    container, vm = _find_container(cfg, "tdarr")
    if not container:
        fmt.error("Tdarr not found in container registry.")
        return 1

    if service == "pause":
        fmt.header("Tdarr: Pause")
        fmt.blank()
        fmt.step_start("Pausing Tdarr workers")
        # Tdarr pause via API
        r = ssh_run(
            host=vm.ip,
            command=f"curl -s -X POST 'http://localhost:{container.port}/api/v2/cruddb' "
            f"-H 'Content-Type: application/json' "
            f'-d \'{{"data": {{"collection": "Node", "mode": "update", '
            f'"docID": "all", "update": {{"nodePaused": true}}}}}}\'',
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=SSH_CMD_TIMEOUT,
            htype="docker",
            use_sudo=False,
        )
        fmt.step_ok("Workers paused") if r.returncode == 0 else fmt.step_fail("Failed")
        fmt.blank()
        fmt.footer()
        return 0

    if service == "resume":
        fmt.header("Tdarr: Resume")
        fmt.blank()
        fmt.step_start("Resuming Tdarr workers")
        r = ssh_run(
            host=vm.ip,
            command=f"curl -s -X POST 'http://localhost:{container.port}/api/v2/cruddb' "
            f"-H 'Content-Type: application/json' "
            f'-d \'{{"data": {{"collection": "Node", "mode": "update", '
            f'"docID": "all", "update": {{"nodePaused": false}}}}}}\'',
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=SSH_CMD_TIMEOUT,
            htype="docker",
            use_sudo=False,
        )
        fmt.step_ok("Workers resumed") if r.returncode == 0 else fmt.step_fail("Failed")
        fmt.blank()
        fmt.footer()
        return 0

    if service == "stats":
        return _transcode_stats(cfg, vm, container)

    # Default: status
    fmt.header("Tdarr Status")
    fmt.blank()

    r = _api_call(cfg, vm, container.port, "/api/v2/get-nodes", timeout=API_TIMEOUT)
    data = _parse_json(r.stdout) if r.returncode == 0 else None
    if data:
        for node_id, node in data.items():
            paused = node.get("nodePaused", False)
            workers = node.get("workers", {})
            status_badge = fmt.badge("warn") if paused else fmt.badge("ok")
            fmt.line(f"  {fmt.C.BOLD}{node_id}{fmt.C.RESET}  {status_badge}  Workers: {len(workers)}")
    else:
        fmt.line(f"  {fmt.C.DIM}Cannot reach Tdarr API.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _transcode_stats(cfg, vm, container) -> int:
    """Tdarr transcoding statistics."""
    fmt.header("Tdarr Statistics")
    fmt.blank()

    r = ssh_run(
        host=vm.ip,
        command=f"curl -s -X POST 'http://localhost:{container.port}/api/v2/cruddb' "
        f"-H 'Content-Type: application/json' "
        f'-d \'{{"data": {{"collection": "StatisticsJSONDB", "mode": "getAll"}}}}\'',
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=SSH_CMD_TIMEOUT,
        htype="docker",
        use_sudo=False,
    )
    data = _parse_json(r.stdout) if r.returncode == 0 else None
    if data:
        if isinstance(data, list) and data:
            stats = data[0] if data else {}
        elif isinstance(data, dict):
            stats = data
        else:
            stats = {}

        total = stats.get("totalFileCount", "?")
        transcoded = stats.get("totalTranscodeCount", "?")
        health = stats.get("totalHealthCheckCount", "?")
        saved = stats.get("sizeDiff", "?")

        fmt.line(f"  {fmt.C.BOLD}Total Files:{fmt.C.RESET}    {total}")
        fmt.line(f"  {fmt.C.BOLD}Transcoded:{fmt.C.RESET}     {transcoded}")
        fmt.line(f"  {fmt.C.BOLD}Health Checks:{fmt.C.RESET}  {health}")
        fmt.line(f"  {fmt.C.BOLD}Space Saved:{fmt.C.RESET}    {saved}")
    else:
        fmt.line(f"  {fmt.C.DIM}Cannot retrieve Tdarr statistics.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Subtitles
# ============================================================================


def _cmd_subtitles(cfg, args) -> int:
    """Bazarr subtitle management."""
    service = getattr(args, "service", None)

    container, vm = _find_container(cfg, "bazarr")
    if not container:
        fmt.error("Bazarr not found in container registry.")
        return 1

    if service == "search":
        fmt.header("Subtitle Search")
        fmt.blank()
        fmt.step_start("Triggering Bazarr subtitle search")
        r = _api_call_authed(cfg, vm, container, "/api/system/tasks", method="POST")
        fmt.step_ok("Search triggered") if r.returncode == 0 else fmt.step_fail("Failed")
        fmt.blank()
        fmt.footer()
        return 0

    if service == "wanted":
        fmt.header("Wanted Subtitles")
        fmt.blank()
        r = _api_call_authed(cfg, vm, container, "/api/episodes/wanted?length=20")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data and "data" in data:
            for ep in data["data"][:15]:
                title = ep.get("seriesTitle", "?")
                episode = ep.get("episode_number", "?")
                fmt.line(f"  {fmt.C.BOLD}{title}{fmt.C.RESET} — {episode}")
        else:
            fmt.line(f"  {fmt.C.DIM}Cannot retrieve wanted subtitles.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Default: status
    fmt.header("Subtitle Status")
    fmt.blank()
    r = _api_call_authed(cfg, vm, container, "/api/system/status")
    data = _parse_json(r.stdout) if r.returncode == 0 else None
    if data:
        fmt.line(f"  {fmt.C.BOLD}Bazarr:{fmt.C.RESET} {fmt.badge('ok')} running")
        fmt.line(f"  {fmt.C.BOLD}Version:{fmt.C.RESET} {data.get('data', {}).get('bazarr_version', '?')}")
    else:
        fmt.line(f"  {fmt.C.RED}Cannot reach Bazarr.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Requests
# ============================================================================


def _cmd_requests(cfg, args) -> int:
    """Overseerr request management."""
    service = getattr(args, "service", None)

    container, vm = _find_container(cfg, "overseerr")
    if not container:
        fmt.error("Overseerr not found in container registry.")
        return 1

    if service == "approve":
        req_id = getattr(args, "query", None)
        if not req_id:
            fmt.error("Usage: freq media requests approve <id>")
            return 1
        fmt.step_start(f"Approving request {req_id}")
        r = _api_call_authed(cfg, vm, container, f"/api/v1/request/{req_id}/approve", method="POST")
        fmt.step_ok("Approved") if r.returncode == 0 else fmt.step_fail("Failed")
        return 0

    if service == "deny":
        req_id = getattr(args, "query", None)
        if not req_id:
            fmt.error("Usage: freq media requests deny <id>")
            return 1
        fmt.step_start(f"Denying request {req_id}")
        r = _api_call_authed(cfg, vm, container, f"/api/v1/request/{req_id}/decline", method="POST")
        fmt.step_ok("Denied") if r.returncode == 0 else fmt.step_fail("Failed")
        return 0

    # Default: list requests
    fmt.header("Media Requests")
    fmt.blank()

    r = _api_call_authed(cfg, vm, container, "/api/v1/request?take=20")
    data = _parse_json(r.stdout) if r.returncode == 0 else None
    if data and "results" in data:
        requests = data["results"]
        if not requests:
            fmt.line(f"  {fmt.C.DIM}No pending requests.{fmt.C.RESET}")
        else:
            fmt.table_header(("ID", 6), ("TYPE", 8), ("TITLE", 30), ("STATUS", 10), ("USER", 14))
            for req in requests:
                rid = str(req.get("id", "?"))
                rtype = req.get("type", "?")
                media = req.get("media", {})
                title = media.get("title", media.get("name", "?"))[:30]
                status_val = req.get("status", 0)
                status_map = {1: "pending", 2: "approved", 3: "declined"}
                status_str = status_map.get(status_val, str(status_val))
                badge = (
                    fmt.badge("warn") if status_val == 1 else fmt.badge("ok") if status_val == 2 else fmt.badge("down")
                )
                user = req.get("requestedBy", {}).get("displayName", "?")[:14]
                fmt.table_row(
                    (rid, 6),
                    (rtype, 8),
                    (title, 30),
                    (badge, 10),
                    (f"{fmt.C.BOLD}{user}{fmt.C.RESET}", 14),
                )
    else:
        fmt.line(f"  {fmt.C.DIM}Cannot reach Overseerr.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Stack Operations
# ============================================================================


def _rolling_restart(cfg) -> int:
    """Rolling restart all containers in dependency order."""
    fmt.header("Rolling Restart — All Containers")
    fmt.blank()

    # Order: infrastructure first (gluetun), then services, then frontends
    order = [
        "gluetun",
        "qbittorrent",
        "flaresolverr",  # VPN + downloaders
        "sabnzbd",  # Usenet
        "prowlarr",  # Indexer hub
        "sonarr",
        "radarr",
        "bazarr",  # *arr stack
        "tdarr",
        "tdarr-node",  # Transcode
        "plex",
        "tautulli",  # Playback
        "overseerr",
        "huntarr",
        "agregarr",  # Frontends
        "recyclarr",
        "unpackerr",
        "kometa",  # Background
    ]

    restarted = 0
    for svc_name in order:
        container, vm = _find_container(cfg, svc_name)
        if not container:
            continue
        fmt.step_start(f"Restarting {svc_name} on {vm.label}")
        r = _docker_cmd(cfg, vm, f"docker restart {svc_name}", timeout=DOCKER_ACTION_TIMEOUT)
        if r.returncode == 0:
            fmt.step_ok(f"{svc_name} restarted")
            restarted += 1
        else:
            fmt.step_fail(f"{svc_name} failed")

    # Restart any registered containers not in the order list
    for vm in _all_vms(cfg):
        for cname in vm.containers:
            if cname not in order:
                fmt.step_start(f"Restarting {cname} on {vm.label}")
                r = _docker_cmd(cfg, vm, f"docker restart {cname}", timeout=DOCKER_ACTION_TIMEOUT)
                if r.returncode == 0:
                    fmt.step_ok(f"{cname} restarted")
                    restarted += 1
                else:
                    fmt.step_fail(f"{cname} failed")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{restarted}{fmt.C.RESET} containers restarted")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_nuke(cfg, args) -> int:
    """Destroy and recreate entire media stack. Requires explicit YES."""
    fmt.header("NUKE Media Stack")
    fmt.blank()
    fmt.line(f"  {fmt.C.RED}{fmt.C.BOLD}WARNING: This will destroy and recreate ALL media containers.{fmt.C.RESET}")
    config_base = cfg.docker_config_base
    if not config_base:
        fmt.error("docker_config_base must be set in freq.toml [infrastructure]")
        return 1
    fmt.line(f"  {fmt.C.RED}Config data in {config_base} will be PRESERVED.{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.RED}Download data will be PRESERVED.{fmt.C.RESET}")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.RED}Type YES to confirm nuke:{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "YES":
            fmt.info("Cancelled. Must type exactly YES.")
            return 0

    for vm in _all_vms(cfg):
        if not vm.compose_path:
            continue
        compose_dir = vm.compose_path.rsplit("/", 1)[0]
        fmt.step_start(f"Nuking {vm.label}")
        r = _docker_cmd(
            cfg, vm, f"cd {compose_dir} && docker compose down && docker compose up -d", timeout=DOCKER_BUILD_TIMEOUT
        )
        if r.returncode == 0:
            fmt.step_ok(f"{vm.label} recreated")
        else:
            fmt.step_fail(f"{vm.label}: {r.stderr[:40]}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_export(cfg, args) -> int:
    """Export all compose files to a backup."""
    fmt.header("Export Compose Files")
    fmt.blank()

    timestamp = time.strftime("%Y%m%d-%H%M%S")

    for vm in _all_vms(cfg):
        if not vm.compose_path:
            continue
        fmt.step_start(f"Exporting {vm.label}")
        r = _docker_cmd(cfg, vm, f"cat {vm.compose_path} 2>/dev/null", timeout=API_TIMEOUT)
        if r.returncode == 0 and r.stdout:
            # Save locally
            export_dir = os.path.join(cfg.data_dir, "exports", "compose")
            os.makedirs(export_dir, exist_ok=True)
            export_path = os.path.join(export_dir, f"vm{vm.vm_id}-{timestamp}.yml")
            try:
                with open(export_path, "w") as f:
                    f.write(r.stdout)
                fmt.step_ok(f"Saved to {export_path}")
            except OSError as e:
                fmt.step_fail(f"Write failed: {e}")
        else:
            fmt.step_fail(f"Cannot read compose file")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Dashboard & Reports
# ============================================================================


def _cmd_dashboard(cfg, args) -> int:
    """Aggregate one-screen media dashboard."""
    fmt.header("Media Dashboard", "PVE FREQ")
    fmt.blank()

    # Container counts
    total = 0
    running = 0
    for vm in _all_vms(cfg):
        statuses = _get_containers_status(cfg, vm)
        total += len(vm.containers)
        for cname in vm.containers:
            for rname, rstatus in statuses.items():
                if cname.lower() in rname.lower() and "Up" in rstatus:
                    running += 1
                    break

    down = total - running

    fmt.line(
        f"  {fmt.C.BOLD}Containers:{fmt.C.RESET}  "
        f"{fmt.C.GREEN}{running}{fmt.C.RESET} up  "
        f"{fmt.C.RED}{down}{fmt.C.RESET} down  "
        f"({total} total, {len(cfg.container_vms)} VMs)"
    )
    fmt.blank()

    # Active downloads
    dl_count = 0
    for vm in _all_vms(cfg):
        for cname, container in vm.containers.items():
            if "qbittorrent" in cname.lower():
                r = _api_call(
                    cfg, vm, container.port, "/api/v2/torrents/info?filter=downloading", timeout=API_QUICK_TIMEOUT
                )
                data = _parse_json(r.stdout) if r.returncode == 0 else None
                if data and isinstance(data, list):
                    dl_count += len(data)

    fmt.line(f"  {fmt.C.BOLD}Downloads:{fmt.C.RESET}    {dl_count} active")

    # Active streams
    container, vm = _find_container(cfg, "tautulli")
    stream_count = 0
    if container:
        cred = _get_vault_credential(cfg, container.vault_key)
        if cred:
            r = _api_call(cfg, vm, container.port, f"/api/v2?apikey={cred}&cmd=get_activity", timeout=API_QUICK_TIMEOUT)
            data = _parse_json(r.stdout) if r.returncode == 0 else None
            if data and "response" in data:
                stream_count = data.get("response", {}).get("data", {}).get("stream_count", 0)
    fmt.line(f"  {fmt.C.BOLD}Streams:{fmt.C.RESET}      {stream_count} active")

    # VPN status
    vpn_ok = 0
    vpn_total = 0
    for vm in _all_vms(cfg):
        for cname in vm.containers:
            if "gluetun" in cname.lower():
                vpn_total += 1
                r = _api_call(cfg, vm, 8000, "/v1/openvpn/status", timeout=VPN_CHECK_TIMEOUT)
                data = _parse_json(r.stdout) if r.returncode == 0 else None
                if data and data.get("status") == "running":
                    vpn_ok += 1

    if vpn_total > 0:
        vpn_color = fmt.C.GREEN if vpn_ok == vpn_total else fmt.C.RED
        fmt.line(f"  {fmt.C.BOLD}VPN:{fmt.C.RESET}          {vpn_color}{vpn_ok}/{vpn_total}{fmt.C.RESET} connected")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_report(cfg, args) -> int:
    """Generate text report of entire stack state."""
    fmt.header("Media Stack Report")
    fmt.blank()

    report_lines = []
    report_lines.append(f"FREQ Media Stack Report — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("=" * 60)

    for vm in _all_vms(cfg):
        statuses = _get_containers_status(cfg, vm)
        report_lines.append(f"\nVM {vm.vm_id} — {vm.label} ({vm.ip})")
        report_lines.append("-" * 40)
        for cname in sorted(vm.containers):
            found = False
            for rname, rstatus in statuses.items():
                if cname.lower() in rname.lower():
                    report_lines.append(f"  {cname}: {rstatus}")
                    found = True
                    break
            if not found:
                report_lines.append(f"  {cname}: NOT FOUND")

    report = "\n".join(report_lines)
    print(report)
    fmt.blank()

    # Save report
    try:
        report_dir = os.path.join(cfg.data_dir, "reports")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, f"media-{time.strftime('%Y%m%d-%H%M%S')}.txt")
        with open(report_path, "w") as f:
            f.write(report)
        fmt.info(f"Report saved: {report_path}")
    except OSError as e:
        logger.warn(f"failed to save media report: {e}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Compose Audit, Mounts, Cleanup, GPU
# ============================================================================


def _cmd_compose(cfg, args) -> int:
    """Scan compose files for exposed secrets."""
    service = getattr(args, "service", None)
    if service != "audit" and service is not None:
        fmt.error("Usage: freq media compose audit")
        return 1

    fmt.header("Compose Audit")
    fmt.blank()

    issues = []
    secret_patterns = ["password", "api_key", "apikey", "secret", "token", "credential"]

    for vm in _all_vms(cfg):
        if not vm.compose_path:
            continue
        r = _docker_cmd(cfg, vm, f"cat {vm.compose_path} 2>/dev/null")
        if r.returncode != 0 or not r.stdout:
            continue

        fmt.divider(f"{vm.label} — {vm.compose_path}")
        fmt.blank()

        found_issues = False
        for i, line in enumerate(r.stdout.split("\n"), 1):
            line_lower = line.lower().strip()
            for pattern in secret_patterns:
                if pattern in line_lower and "=" in line_lower and not line_lower.startswith("#"):
                    if "${" not in line and "vault" not in line_lower:
                        issues.append(f"{vm.label}:{i} — possible hardcoded secret: {pattern}")
                        fmt.line(
                            f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET} "
                            f"Line {i}: {fmt.C.RED}{line.strip()[:60]}{fmt.C.RESET}"
                        )
                        found_issues = True

        if not found_issues:
            fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} No exposed secrets found")
        fmt.blank()

    fmt.divider("Summary")
    fmt.blank()
    if issues:
        fmt.line(f"  {fmt.C.YELLOW}{len(issues)} potential issue(s){fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.GREEN}All compose files clean.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_mounts(cfg, args) -> int:
    """Verify NFS mounts responding."""
    fmt.header("NFS Mount Check")
    fmt.blank()

    ok_count = 0
    fail_count = 0

    for vm in _all_vms(cfg):
        r = _docker_cmd(cfg, vm, "mount | grep -E 'nfs|cifs' 2>/dev/null")
        if r.returncode != 0 or not r.stdout.strip():
            fmt.line(f"  {fmt.C.DIM}{vm.label}: no network mounts{fmt.C.RESET}")
            continue

        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3:
                mount_point = parts[2]
                # Test if mount is responsive
                r2 = _docker_cmd(cfg, vm, f"ls {mount_point} >/dev/null 2>&1", timeout=API_QUICK_TIMEOUT)
                if r2.returncode == 0:
                    ok_count += 1
                    print(
                        f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {fmt.C.BOLD}{vm.label}{fmt.C.RESET}: {mount_point}"
                    )
                else:
                    fail_count += 1
                    print(
                        f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} "
                        f"{fmt.C.BOLD}{vm.label}{fmt.C.RESET}: {mount_point} — STALE"
                    )

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{ok_count}{fmt.C.RESET} ok  {fmt.C.RED}{fail_count}{fmt.C.RESET} stale/failed")
    fmt.blank()
    fmt.footer()
    return 1 if fail_count > 0 else 0


def _cmd_cleanup(cfg, args) -> int:
    """Find old backups, temp files, orphaned downloads."""
    fmt.header("Media Cleanup")
    fmt.blank()
    backup_dir = cfg.docker_backup_dir
    if not backup_dir:
        fmt.error("docker_backup_dir must be set in freq.toml [infrastructure]")
        return 1

    for vm in _all_vms(cfg):
        fmt.divider(f"{vm.label}")
        fmt.blank()

        # Old backups (>30 days)
        r = _docker_cmd(cfg, vm, f"find {backup_dir} -name '*.tar.gz' -mtime +30 2>/dev/null | wc -l")
        if r.returncode == 0:
            count = r.stdout.strip()
            if count != "0":
                fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET} {count} old backup(s) (>30 days)")

        # Docker dangling images
        r = _docker_cmd(cfg, vm, "docker images -f dangling=true -q 2>/dev/null | wc -l")
        if r.returncode == 0:
            count = r.stdout.strip()
            if count != "0":
                fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET} {count} dangling Docker image(s)")

        # Stopped containers
        r = _docker_cmd(cfg, vm, "docker ps -a --filter status=exited --format '{{.Names}}' 2>/dev/null | wc -l")
        if r.returncode == 0:
            count = r.stdout.strip()
            if count != "0":
                fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET} {count} stopped container(s)")

        fmt.blank()

    fmt.info("Run 'freq media prune' to clean Docker resources.")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_gpu(cfg, args) -> int:
    """GPU status for transcode workers."""
    fmt.header("GPU / Transcode Hardware")
    fmt.blank()

    # Check tdarr-node VM (301)
    container, vm = _find_container(cfg, "tdarr-node")
    if not container:
        # Try any VM with GPU
        for v in _all_vms(cfg):
            r = _docker_cmd(cfg, v, "ls /dev/dri 2>/dev/null")
            # Fallback
        fmt.line(f"  {fmt.C.DIM}No GPU-equipped containers found.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Check GPU device
    r = _docker_cmd(cfg, vm, "ls -la /dev/dri/ 2>/dev/null")
    if r.returncode == 0 and r.stdout:
        fmt.divider(f"{vm.label} — GPU Devices")
        fmt.blank()
        for line in r.stdout.strip().split("\n"):
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        fmt.blank()

    # VAAPI check
    r = _docker_cmd(cfg, vm, "vainfo 2>&1 | head -5")
    if r.returncode == 0 and r.stdout:
        fmt.divider("VAAPI Info")
        fmt.blank()
        for line in r.stdout.strip().split("\n"):
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        fmt.blank()

    # ROCm check
    r = _docker_cmd(cfg, vm, "rocm-smi 2>/dev/null | head -10")
    if r.returncode == 0 and r.stdout:
        fmt.divider("ROCm Info")
        fmt.blank()
        for line in r.stdout.strip().split("\n"):
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        fmt.blank()

    fmt.footer()
    return 0


# ============================================================================
# Utilities
# ============================================================================


def _human_size(size_bytes):
    """Convert bytes to human-readable size."""
    if not isinstance(size_bytes, (int, float)) or size_bytes == 0:
        return "0B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}PB"


def _media_overview_legacy(cfg, host) -> int:
    """Legacy overview when no containers.toml — uses first docker host."""
    fmt.header("Media Stack", "PVE FREQ")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Host:{fmt.C.RESET} {host.label} ({host.ip})")
    fmt.blank()

    r = ssh_run(
        host=host.ip,
        command="docker ps --format '{{.Names}}|{{.Status}}' 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=SSH_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )

    if r.returncode != 0 or not r.stdout.strip():
        fmt.line(f"{fmt.C.RED}Cannot reach Docker on {host.label}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    for line in sorted(r.stdout.strip().split("\n")):
        parts = line.split("|", 1)
        if len(parts) == 2:
            name = parts[0].strip()
            status = parts[1].strip()
            badge = fmt.badge("up") if "Up" in status else fmt.badge("down")
            print(f"  {badge} {fmt.C.BOLD}{name}{fmt.C.RESET}  {fmt.C.DIM}{status}{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


# ============================================================================
# Additional Commands
# ============================================================================


def _cmd_unmonitored(cfg, args) -> int:
    """Show unmonitored series/movies in Sonarr + Radarr."""
    fmt.header("Unmonitored Media")
    fmt.blank()

    # Sonarr
    container, vm = _find_container(cfg, "sonarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/series")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data and isinstance(data, list):
            unmon = [s for s in data if not s.get("monitored", True)]
            fmt.divider(f"Sonarr — {len(unmon)} unmonitored series")
            fmt.blank()
            if unmon:
                for s in unmon[:20]:
                    status = s.get("status", "?")
                    eps = f"{s.get('episodeFileCount', 0)} eps on disk"
                    fmt.line(f"  {fmt.C.BOLD}{s.get('title', '?')}{fmt.C.RESET}  ({status}, {eps})")
            else:
                fmt.line(f"  {fmt.C.DIM}All series are monitored.{fmt.C.RESET}")
            fmt.blank()

    # Radarr
    container, vm = _find_container(cfg, "radarr")
    if container:
        r = _api_call_authed(cfg, vm, container, "/api/v3/movie")
        data = _parse_json(r.stdout) if r.returncode == 0 else None
        if data and isinstance(data, list):
            unmon = [m for m in data if not m.get("monitored", True)]
            fmt.divider(f"Radarr — {len(unmon)} unmonitored movies")
            fmt.blank()
            if unmon:
                for m in unmon[:20]:
                    has_file = "on disk" if m.get("hasFile") else "missing"
                    fmt.line(f"  {fmt.C.BOLD}{m.get('title', '?')}{fmt.C.RESET}  ({m.get('year', '?')}, {has_file})")
            else:
                fmt.line(f"  {fmt.C.DIM}All movies are monitored.{fmt.C.RESET}")
            fmt.blank()

    fmt.footer()
    return 0


def _cmd_password(cfg, args) -> int:
    """Password/credential sync across media services."""
    service = getattr(args, "service", None)
    if service != "sync":
        fmt.error("Usage: freq media password sync")
        fmt.info("Syncs download client credentials across Sonarr/Radarr after a password change.")
        return 1

    fmt.header("Password Sync")
    fmt.blank()
    fmt.info("This updates download client credentials in Sonarr/Radarr to match vault.")
    fmt.blank()

    # Get qBittorrent credentials from vault
    for qbit_key in ["qbit1_password", "qbit2_password"]:
        cred = _get_vault_credential(cfg, qbit_key)
        if cred:
            fmt.step_ok(f"Vault key '{qbit_key}' found")
        else:
            fmt.step_fail(f"Vault key '{qbit_key}' not set — use 'freq vault set {qbit_key}'")

    fmt.blank()
    fmt.info("To update download client configs in Sonarr/Radarr:")
    fmt.info("  1. Update password in vault: freq vault set qbit1_password")
    fmt.info("  2. Update in qBittorrent WebUI: Settings > Web UI > Password")
    fmt.info("  3. Update in Sonarr/Radarr: Settings > Download Clients > qBittorrent > Password")
    fmt.info("  (API-based auto-sync requires auth tokens — use WebUI for now)")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_import(cfg, args) -> int:
    """Import/restore entire media stack from export bundle."""
    fmt.header("Import Media Stack")
    fmt.blank()

    import_dir = os.path.join(cfg.data_dir, "exports", "compose")
    if not os.path.isdir(import_dir):
        fmt.error(f"No exports found at {import_dir}")
        fmt.info("Run 'freq media export' first to create backups.")
        fmt.blank()
        fmt.footer()
        return 1

    # List available exports
    try:
        files = sorted(os.listdir(import_dir), reverse=True)
    except OSError:
        files = []

    if not files:
        fmt.error("No export files found.")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.line(f"  Available exports:")
    fmt.blank()
    for i, f in enumerate(files[:10], 1):
        fmt.line(f"  {fmt.C.CYAN}[{i}]{fmt.C.RESET}  {f}")

    fmt.blank()
    try:
        choice = input(f"  {fmt.C.CYAN}Select export [1]:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    idx = int(choice) - 1 if choice.isdigit() else 0
    if idx < 0 or idx >= len(files):
        idx = 0

    selected = files[idx]
    filepath = os.path.join(import_dir, selected)

    # Parse VM ID from filename (vm101-YYYYMMDD-HHMMSS.yml)
    parts = selected.split("-")
    vm_id_str = parts[0].replace("vm", "") if parts else ""

    try:
        vm_id = int(vm_id_str)
    except ValueError:
        fmt.error(f"Cannot determine VM ID from filename: {selected}")
        return 1

    vm = cfg.container_vms.get(vm_id)
    if not vm:
        fmt.error(f"VM {vm_id} not in container registry.")
        return 1

    fmt.line(f"  Restoring {selected} to {vm.label} ({vm.ip})")
    fmt.blank()

    if not getattr(args, "yes", False):
        try:
            confirm = input(f"  {fmt.C.YELLOW}Restore compose file? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Read local file and write to remote
    try:
        with open(filepath) as f:
            content = f.read()
    except OSError as e:
        fmt.error(f"Cannot read {filepath}: {e}")
        return 1

    if not vm.compose_path:
        fmt.error(f"No compose path configured for VM {vm_id}")
        return 1

    # SCP the compose file
    r = subprocess.run(
        [
            "scp",
            "-i",
            cfg.ssh_key_path,
            "-o",
            "StrictHostKeyChecking=accept-new",
            filepath,
            f"{cfg.ssh_service_account}@{vm.ip}:{vm.compose_path}",
        ],
        capture_output=True,
        text=True,
        timeout=SCP_TIMEOUT,
    )

    if r.returncode == 0:
        fmt.step_ok(f"Compose file restored to {vm.label}:{vm.compose_path}")

        # Recreate stack
        compose_dir = vm.compose_path.rsplit("/", 1)[0]
        fmt.step_start(f"Recreating stack on {vm.label}")
        r2 = _docker_cmd(cfg, vm, f"cd {compose_dir} && docker compose up -d", timeout=DOCKER_LONG_TIMEOUT)
        if r2.returncode == 0:
            fmt.step_ok("Stack recreated")
        else:
            fmt.step_fail(f"Recreate failed: {r2.stderr[:60]}")
    else:
        fmt.step_fail(f"SCP failed: {r.stderr}")

    fmt.blank()
    fmt.footer()
    return 0
