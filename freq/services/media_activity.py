"""Media-activity normalization and transport below dashboard HTTP handling."""

import json
import os
import shlex

from freq.core.config import _resolve_container_vm_ip
from freq.core.ssh import run as ssh_single

_MEDIA_DEFAULT_PORTS = {
    "tautulli": 8181,
    "sabnzbd": 8080,
    "qbittorrent": 8080,
    "qbit": 8080,
    "plex": 32400,
}


def media_default_port(name: str) -> int:
    lname = (name or "").lower()
    for key, port in _MEDIA_DEFAULT_PORTS.items():
        if key in lname:
            return port
    return 0


def media_container_port(container) -> int:
    return int(
        getattr(container, "port", 0)
        or media_default_port(getattr(container, "name", ""))
        or 0
    )


def parse_sab_downloads(data, vm_label: str) -> list:
    downloads = []
    queue = data.get("queue", {}) if isinstance(data, dict) else {}
    speed_str = str(queue.get("speed", "0"))
    speed_val = float(
        speed_str.replace(" M", "").replace(" K", "").replace(" G", "") or 0
    )
    if "M" in speed_str:
        speed_val *= 1048576
    elif "K" in speed_str:
        speed_val *= 1024
    elif "G" in speed_str:
        speed_val *= 1073741824
    for s in queue.get("slots", []):
        pct = int(float(s.get("percentage", 0)))
        size_mb = float(s.get("mb", 0)) * 1048576
        downloads.append(
            {
                "name": s.get("filename", "?"),
                "size": int(size_mb),
                "progress": pct,
                "speed": int(speed_val),
                "client": "SABnzbd",
                "vm": vm_label,
            }
        )
    return downloads


def parse_qbit_downloads(data, vm_label: str) -> list:
    downloads = []
    if not isinstance(data, list):
        return downloads
    for t in data:
        downloads.append(
            {
                "name": t.get("name", "?"),
                "size": t.get("size", 0),
                "progress": round(t.get("progress", 0) * 100),
                "speed": t.get("dlspeed", 0),
                "client": "qBittorrent",
                "vm": vm_label,
            }
        )
    return downloads


def media_ssh_user_from_key(cfg) -> str:
    key_path = getattr(cfg, "ssh_key_path", "") or ""
    parts = key_path.split(os.sep)
    if len(parts) >= 3 and parts[-2] == ".ssh" and parts[-3]:
        return parts[-3]
    return ""


def media_ssh_single(cfg, vm, command: str, timeout: int = 10):
    def _run(**overrides):
        merged = dict(kwargs)
        merged.update(overrides)
        return ssh_single(cfg=cfg, **merged)

    kwargs = {
        "host": _resolve_container_vm_ip(vm),
        "command": command,
        "key_path": cfg.ssh_key_path,
        "connect_timeout": 3,
        "command_timeout": timeout,
        "htype": "docker",
        "use_sudo": False,
    }
    r = _run()
    if r.returncode == 255 and "Permission denied" in (r.stderr or ""):
        key_user = media_ssh_user_from_key(cfg)
        if key_user and key_user != getattr(cfg, "ssh_service_account", ""):
            r = _run(user=key_user)
    if (
        r.returncode != 0
        and "docker.sock" in (r.stderr or "")
        and "permission denied" in (r.stderr or "").lower()
    ):
        retry = {"use_sudo": True}
        key_user = media_ssh_user_from_key(cfg)
        if key_user and key_user != getattr(cfg, "ssh_service_account", ""):
            retry["user"] = key_user
        r = _run(**retry)
    return r


def docker_exec_json(cfg, vm, container_name: str, script: str, timeout: int = 10):
    r = media_ssh_single(
        cfg,
        vm,
        f"docker exec {shlex.quote(container_name)} sh -lc {shlex.quote(script)}",
        timeout=timeout,
    )
    if r.returncode != 0:
        return None, r
    try:
        return json.loads(r.stdout), r
    except (json.JSONDecodeError, TypeError):
        return None, r


def media_status_projection(cfg, resolve_vm, ssh_run):
    """Return per-container status rows and whether the registry is configured."""
    registry_configured = bool(cfg.container_vms)
    containers = []
    for vm in sorted(cfg.container_vms.values(), key=lambda value: value.vm_id):
        resolved_ip = resolve_vm(vm)
        result = ssh_run(
            host=resolved_ip,
            command="docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            htype="docker",
            use_sudo=False,
            cfg=cfg,
        )
        running = {}
        if result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                parts = line.split("|", 1)
                if len(parts) == 2:
                    running[parts[0].strip()] = parts[1].strip()

        for name, container in vm.containers.items():
            status = "not found"
            normalized_name = name.lower().replace("-", "_").replace(" ", "_")
            for running_name, running_status in running.items():
                normalized_running = running_name.lower().replace("-", "_").replace(" ", "_")
                if normalized_name in normalized_running or normalized_running in normalized_name:
                    status = running_status
                    break
            containers.append({
                "name": name,
                "vm_id": vm.vm_id,
                "vm_label": vm.label,
                "vm_ip": resolved_ip,
                "port": container.port,
                "status": "up" if "Up" in status else "down",
                "detail": status,
            })
    return containers, registry_configured


def media_dashboard_counts(cfg, health, resolve_vm, ssh_run):
    """Return configured and running media-container counts."""
    total = sum(len(vm.containers) for vm in cfg.container_vms.values())
    running = 0
    if health and "hosts" in health:
        docker_ips = {resolve_vm(vm) for vm in cfg.container_vms.values()}
        for host in health["hosts"]:
            if host.get("ip") in docker_ips and host.get("status") != "unreachable":
                try:
                    running += int(host.get("docker", "0"))
                except (ValueError, TypeError):
                    pass
    elif not health:
        for vm in cfg.container_vms.values():
            result = ssh_run(
                host=resolve_vm(vm),
                command="docker ps --format '{{.Names}}' 2>/dev/null | wc -l",
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=10,
                htype="docker",
                use_sudo=False,
                cfg=cfg,
            )
            if result.returncode == 0:
                try:
                    running += int(result.stdout.strip())
                except ValueError:
                    pass
    return total, running


def media_health_projection(cfg, resolve_vm, ssh_run):
    """Return probeable media-service health rows and skipped count."""
    results = []
    skipped = 0
    for vm in sorted(cfg.container_vms.values(), key=lambda value: value.vm_id):
        resolved_ip = resolve_vm(vm)
        for name, container in vm.containers.items():
            if not container.port or not container.api_path:
                skipped += 1
                continue
            result = ssh_run(
                host=resolved_ip,
                command=f"curl -s -o /dev/null -w '%{{http_code}}' "
                f"--connect-timeout 2 'http://localhost:{container.port}{container.api_path}' "
                f"2>/dev/null || echo 000",
                key_path=cfg.ssh_key_path,
                connect_timeout=3,
                command_timeout=5,
                htype="docker",
                use_sudo=False,
                cfg=cfg,
            )
            code = result.stdout.strip()[-3:] if result.returncode == 0 else "000"
            healthy = code in ("200", "301", "302")
            results.append({
                "name": name,
                "vm_label": vm.label,
                "status": "healthy" if healthy else "down",
                "http_code": code,
                "port": container.port,
            })
    return results, skipped


def qbit_container_local_downloads(cfg, vm, container, port, docker_exec, parse_downloads):
    """Return qBittorrent downloads from the credential-free container-local API."""
    data, result = docker_exec(
        cfg,
        vm,
        container.name,
        f'curl -s --connect-timeout 3 "http://localhost:{port}/api/v2/torrents/info?filter=downloading"',
    )
    if isinstance(data, list):
        return (
            parse_downloads(data, vm.label),
            {"client": "qBittorrent", "vm": vm.label, "source": "container-local"},
            True,
        )
    return [], None, False


def qbit_vault_auth_downloads(cfg, vm, port, vault_read, ssh_run, parse_downloads):
    """Return qBittorrent downloads or a secret-free warning after vault auth."""
    qb_user = vault_read(cfg, "DEFAULT", "qbittorrent_user") or "admin"
    qb_pass = vault_read(cfg, "DEFAULT", "qbittorrent_password") or ""
    if not qb_pass:
        return [], None, {
            "client": "qBittorrent",
            "vm": vm.label,
            "reason": "auth_required",
        }

    result = ssh_run(
        cfg,
        vm,
        f"curl -s -c /tmp/qb.cookie --connect-timeout 3 "
        f"'http://localhost:{port}/api/v2/auth/login' "
        f"-d 'username={qb_user}&password={qb_pass}' && "
        f"curl -s -b /tmp/qb.cookie --connect-timeout 3 "
        f"'http://localhost:{port}/api/v2/torrents/info?filter=downloading'",
        timeout=10,
    )
    if result.returncode != 0:
        return [], None, {
            "client": "qBittorrent",
            "vm": vm.label,
            "reason": "query_failed",
        }

    stdout = result.stdout
    bracket = stdout.find("[")
    if bracket >= 0:
        stdout = stdout[bracket:]
    try:
        downloads = parse_downloads(json.loads(stdout), vm.label)
    except (json.JSONDecodeError, TypeError):
        return [], None, {
            "client": "qBittorrent",
            "vm": vm.label,
            "reason": "bad_json",
        }
    return (
        downloads,
        {"client": "qBittorrent", "vm": vm.label, "source": "vault-auth"},
        None,
    )
