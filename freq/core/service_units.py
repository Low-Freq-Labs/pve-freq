"""Canonical service definitions for FREQ's host-managed runtime."""

from __future__ import annotations

import re

_SERVICE_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SAFE_PATH_BYTES = frozenset(b"/ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


def _unit_quote(value: str) -> str:
    value = str(value)
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("systemd unit values cannot contain line breaks or NUL bytes")
    escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unit_path(value: str) -> str:
    """Escape an absolute path for a systemd path-valued directive."""
    value = str(value)
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("systemd paths cannot contain line breaks or NUL bytes")
    return "".join(
        chr(byte) if byte in _SAFE_PATH_BYTES else f"\\x{byte:02x}"
        for byte in value.encode("utf-8")
    )


def dashboard_service_unit(
    service_user: str,
    install_dir: str,
    *,
    freq_bin: str = "/usr/local/bin/freq",
) -> str:
    """Render the one supported host-systemd dashboard service unit."""
    if not _SERVICE_USER_RE.fullmatch(str(service_user or "")):
        raise ValueError(f"invalid service account: {service_user!r}")
    if not str(install_dir or "").startswith("/"):
        raise ValueError("install_dir must be an absolute path")
    if not str(freq_bin or "").startswith("/"):
        raise ValueError("freq_bin must be an absolute path")

    return f"""[Unit]
Description=PVE FREQ Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={service_user}
Group={service_user}
WorkingDirectory={_unit_path(install_dir)}
Environment={_unit_quote(f"FREQ_DIR={install_dir}")}
ExecStart={_unit_quote(freq_bin)} serve
Restart=always
RestartSec=10
TimeoutStopSec=10
KillMode=mixed
StandardOutput=journal
StandardError=journal
SyslogIdentifier=freq-serve

[Install]
WantedBy=multi-user.target
"""


def setup_dashboard_service_unit(
    setup_user: str,
    setup_group: str,
    install_dir: str,
    *,
    freq_bin: str = "/usr/local/bin/freq",
) -> str:
    """Render the temporary pre-init HTTPS listener.

    The managed dashboard cannot run as its final service account until init
    creates that account.  This unit deliberately uses an existing bootstrap
    identity and is disabled by the web-init runtime handoff.
    """
    if not _SERVICE_USER_RE.fullmatch(str(setup_user or "")):
        raise ValueError(f"invalid setup account: {setup_user!r}")
    if not _SERVICE_USER_RE.fullmatch(str(setup_group or "")):
        raise ValueError(f"invalid setup group: {setup_group!r}")
    if not str(install_dir or "").startswith("/"):
        raise ValueError("install_dir must be an absolute path")
    if not str(freq_bin or "").startswith("/"):
        raise ValueError("freq_bin must be an absolute path")

    return f"""[Unit]
Description=PVE FREQ First-Run HTTPS Setup
After=network-online.target
Wants=network-online.target
ConditionPathExists=!{_unit_path(install_dir)}/data/.initialized

[Service]
Type=simple
User={setup_user}
Group={setup_group}
WorkingDirectory={_unit_path(install_dir)}
Environment={_unit_quote(f"FREQ_DIR={install_dir}")}
ExecStart={_unit_quote(freq_bin)} serve
Restart=on-failure
RestartSec=10
TimeoutStopSec=10
KillMode=mixed
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pve-freq-setup

[Install]
WantedBy=multi-user.target
"""
