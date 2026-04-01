"""Service manager abstraction — multi-distro service operations.

Provides platform-aware commands for managing services across
systemd, OpenRC, runit, sysvinit, and FreeBSD rc.d.

Usage:
    from freq.core.services import service_cmd, service_enable_cmd, service_logs_cmd

    cmd = service_cmd("start", "sshd", init_system="systemd")
    # "systemctl start sshd"

    cmd = service_cmd("restart", "sshd", init_system="openrc")
    # "rc-service sshd restart"
"""


# ---------------------------------------------------------------------------
# Service actions: start, stop, restart, status
# ---------------------------------------------------------------------------

_SERVICE_CMDS = {
    "systemd": "systemctl {action} {service}",
    "openrc": "rc-service {service} {action}",
    "runit": "sv {action} {service}",
    "sysvinit": "/etc/init.d/{service} {action}",
    "rc.d": "service {service} {action}",
}


def service_cmd(action: str, service: str, init_system: str) -> str:
    """Return the shell command for a service action (start/stop/restart/status).

    Handles the sshd/ssh service name split automatically.
    """
    service = _resolve_service_name(service, init_system)
    template = _SERVICE_CMDS.get(init_system)
    if not template:
        return f"echo 'Unknown init system: {init_system}'"
    return template.format(action=action, service=service)


# ---------------------------------------------------------------------------
# Enable/disable (boot persistence)
# ---------------------------------------------------------------------------

_ENABLE_CMDS = {
    "systemd": "systemctl enable {service}",
    "openrc": "rc-update add {service} default",
    "runit": "ln -sf /etc/sv/{service} /var/service/",
    "sysvinit": "update-rc.d {service} defaults",
    "rc.d": 'sysrc {service}_enable="YES"',
}

_DISABLE_CMDS = {
    "systemd": "systemctl disable {service}",
    "openrc": "rc-update del {service} default",
    "runit": "rm -f /var/service/{service}",
    "sysvinit": "update-rc.d {service} remove",
    "rc.d": 'sysrc {service}_enable="NO"',
}


def service_enable_cmd(service: str, init_system: str, enable: bool = True) -> str:
    """Return the command to enable or disable a service at boot."""
    service = _resolve_service_name(service, init_system)
    cmds = _ENABLE_CMDS if enable else _DISABLE_CMDS
    template = cmds.get(init_system)
    if not template:
        return f"echo 'Cannot enable on {init_system}'"
    return template.format(service=service)


# ---------------------------------------------------------------------------
# Check if service is active
# ---------------------------------------------------------------------------

_IS_ACTIVE_CMDS = {
    "systemd": "systemctl is-active {service} >/dev/null 2>&1",
    "openrc": "rc-service {service} status >/dev/null 2>&1",
    "runit": "sv check {service} >/dev/null 2>&1",
    "sysvinit": "/etc/init.d/{service} status >/dev/null 2>&1",
    "rc.d": "service {service} onestatus >/dev/null 2>&1",
}


def is_active_cmd(service: str, init_system: str) -> str:
    """Return a command that exits 0 if the service is running."""
    service = _resolve_service_name(service, init_system)
    template = _IS_ACTIVE_CMDS.get(init_system)
    if not template:
        return "false"
    return template.format(service=service)


# ---------------------------------------------------------------------------
# Service logs
# ---------------------------------------------------------------------------

_LOG_CMDS = {
    "systemd": "journalctl -u {service} -n {lines} --no-pager",
    "openrc": "tail -n {lines} /var/log/{service}.log 2>/dev/null || tail -n {lines} /var/log/messages",
    "runit": "svlogd -tt /var/log/{service} 2>/dev/null | tail -n {lines}",
    "sysvinit": "tail -n {lines} /var/log/syslog",
    "rc.d": "tail -n {lines} /var/log/{service}.log 2>/dev/null || tail -n {lines} /var/log/messages",
}


def service_logs_cmd(service: str, init_system: str, lines: int = 50) -> str:
    """Return the command to view recent service logs."""
    service = _resolve_service_name(service, init_system)
    template = _LOG_CMDS.get(init_system)
    if not template:
        return f"echo 'No log support for {init_system}'"
    return template.format(service=service, lines=lines)


# ---------------------------------------------------------------------------
# List services
# ---------------------------------------------------------------------------

_LIST_CMDS = {
    "systemd": "systemctl list-units --type=service --no-pager --no-legend",
    "openrc": "rc-status --all",
    "runit": "ls /var/service/",
    "sysvinit": "ls /etc/init.d/",
    "rc.d": "service -l",
}


def list_services_cmd(init_system: str) -> str:
    """Return the command to list all services."""
    return _LIST_CMDS.get(init_system, "echo 'unsupported'")


# ---------------------------------------------------------------------------
# Service name resolution
# ---------------------------------------------------------------------------

# Some services have different names across distros/init systems
# Key: generic name, Value: {init_system: actual_name}
_SERVICE_NAMES = {
    "sshd": {
        # Ubuntu/Debian call the SSH service "ssh", others call it "sshd"
        "systemd_debian": "ssh",
        "systemd": "sshd",
        "openrc": "sshd",
        "runit": "sshd",
        "sysvinit": "ssh",
        "rc.d": "sshd",
    },
    "cron": {
        "systemd_rhel": "crond",
        "systemd": "cron",
        "openrc": "cronie",
        "rc.d": "cron",
    },
}


def _resolve_service_name(service: str, init_system: str, os_family: str = "") -> str:
    """Resolve generic service name to platform-specific name."""
    mapping = _SERVICE_NAMES.get(service)
    if not mapping:
        return service

    # Try family-specific key first (e.g. "systemd_debian")
    if os_family:
        key = f"{init_system}_{os_family}"
        if key in mapping:
            return mapping[key]

    # Fall back to init system key
    return mapping.get(init_system, service)
