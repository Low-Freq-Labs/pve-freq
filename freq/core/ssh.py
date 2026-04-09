"""SSH transport for FREQ — the network spine.

Provides: run(), async_run(), run_many(), async_run_many()

Every remote operation goes through here. Parallel subprocess-based SSH
with platform-aware configuration for 6 host types (linux, pve, truenas,
pfsense/docker, idrac, switch). Legacy devices get RSA keys and weak ciphers
automatically — no user configuration needed.

Replaces: Ansible SSH transport ($0 but Python dependency hell),
          Fabric/Paramiko ($0 but requires pip install)

Architecture:
    - asyncio.create_subprocess_exec for parallel fleet operations
    - Sync wrapper (run) for single-host commands
    - SSH multiplexing (ControlMaster) for connection reuse — 4x speedup
    - Platform-specific cipher/key negotiation per host type
    - CmdResult dataclass for structured return (rc, stdout, stderr)

Design decisions:
    - subprocess, not paramiko. Zero dependencies. Ships with Python.
    - SSH multiplexing persists 5 minutes — fleet ops on 14 hosts in 2.7s.
    - Legacy host types (iDRAC, Cisco) auto-negotiate weak ciphers.
      This is a hardware limitation, not a security choice.
    - Timeout defaults: 5s connect, 30s command. Overridable per call.
"""

import asyncio
import os
import subprocess
import time
from typing import Optional

from freq.core.types import CmdResult, Host
from freq.core import log as logger


# Legacy host types that require RSA keys (no ed25519 support)
LEGACY_HTYPES = {"idrac", "switch"}

# SSH multiplexing settings
MUX_CONTROL_DIR = "~/.ssh/freq-mux"
MUX_PERSIST_SECONDS = 300


# Platform-specific SSH configuration
# Each platform type has different auth, sudo, and cipher requirements
_PLATFORM_SSH_BASE = {
    "linux": {
        "sudo": "sudo ",
        "extra_opts": [],
    },
    "pve": {
        "sudo": "sudo ",
        "extra_opts": [],
    },
    "truenas": {
        "sudo": "sudo ",
        "extra_opts": [],
    },
    "pfsense": {
        "sudo": "",
        "extra_opts": [],
    },
    "docker": {
        "sudo": "sudo ",
        "extra_opts": [],
    },
    "idrac": {
        "sudo": "",
        "extra_opts": [
            "-o",
            "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1",
            "-o",
            "HostKeyAlgorithms=+ssh-rsa",
            "-o",
            "PubkeyAcceptedAlgorithms=+ssh-rsa",
        ],
    },
    "switch": {
        "sudo": "",
        "extra_opts": [
            "-o",
            "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1",
            "-o",
            "HostKeyAlgorithms=+ssh-rsa",
            "-o",
            "PubkeyAcceptedAlgorithms=+ssh-rsa",
        ],
    },
}


def get_platform_ssh(htype: str, cfg=None) -> dict:
    """Return platform SSH config for the given host type.

    Merges base config with dynamic values from FreqConfig:
    - user: from cfg.ssh_service_account (default: freq-admin)
    - password_file: from cfg.legacy_password_file for idrac/switch
    """
    base = _PLATFORM_SSH_BASE.get(htype, _PLATFORM_SSH_BASE["linux"]).copy()

    # Set user from config or default
    if cfg and hasattr(cfg, "ssh_service_account") and cfg.ssh_service_account:
        base["user"] = cfg.ssh_service_account
    else:
        from freq.core.config import _DEFAULTS

        base["user"] = _DEFAULTS["ssh_service_account"]

    # Set password_file for legacy devices (only if configured)
    if htype in LEGACY_HTYPES:
        if cfg and hasattr(cfg, "legacy_password_file") and cfg.legacy_password_file:
            base["password_file"] = cfg.legacy_password_file

    return base


# Backwards-compatible module-level dict (for callers that access PLATFORM_SSH directly)
PLATFORM_SSH = {htype: get_platform_ssh(htype) for htype in _PLATFORM_SSH_BASE}


def _resolve_legacy_key(key_path: str) -> str:
    """For legacy devices (iDRAC, switch), find RSA key in same directory.

    These devices don't support ed25519. If the given key is ed25519,
    look for a sibling RSA key. Zero changes to callers needed.
    """
    if not key_path:
        return key_path

    key_dir = os.path.dirname(key_path)
    rsa_candidates = [
        os.path.join(key_dir, "freq_id_rsa"),
        os.path.join(key_dir, "id_rsa"),
    ]
    for rsa_path in rsa_candidates:
        if os.path.isfile(rsa_path):
            return rsa_path

    # No RSA key found — return original (will likely fail, but at least
    # the error message will point to the real problem)
    return key_path


def _resolve_connect_timeout(connect_timeout, cfg) -> int:
    """Resolve SSH connect timeout: explicit value > cfg > default 5."""
    if connect_timeout is not None:
        return connect_timeout
    if cfg and hasattr(cfg, "ssh_connect_timeout"):
        return cfg.ssh_connect_timeout
    return 5


def _build_ssh_cmd(
    host: str,
    command: str,
    user: Optional[str] = None,
    key_path: Optional[str] = None,
    connect_timeout: Optional[int] = None,
    htype: str = "linux",
    use_sudo: bool = True,
    extra_opts: Optional[list] = None,
    cfg=None,
) -> list:
    """Build an SSH command list for subprocess execution."""
    connect_timeout = _resolve_connect_timeout(connect_timeout, cfg)
    platform = get_platform_ssh(htype, cfg)

    ssh_user = user or platform["user"]
    sudo_prefix = platform["sudo"] if use_sudo else ""
    password_file = platform.get("password_file", "")

    # Resolve: only use password auth if the file actually exists on disk.
    # If configured but missing, fall back to key auth with BatchMode=yes
    # so SSH fails silently instead of prompting on /dev/tty.
    use_password = bool(password_file and os.path.isfile(password_file))

    prefix = []
    if use_password:
        prefix = ["sshpass", "-f", password_file]

    cmd = ["ssh"]

    # Connection options
    cmd.extend(["-o", f"ConnectTimeout={connect_timeout}"])
    cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
    if not use_password:
        cmd.extend(["-o", "BatchMode=yes"])

    # SSH multiplexing — skip for password-auth and legacy devices
    # iDRAC/switch have 2-session SSH limits; mux sockets hold connections and exhaust slots
    if not use_password and htype not in LEGACY_HTYPES:
        control_dir = os.path.expanduser(MUX_CONTROL_DIR)
        os.makedirs(control_dir, mode=0o700, exist_ok=True)
        control_path = os.path.join(control_dir, "%r@%h:%p")
        cmd.extend(["-o", f"ControlPath={control_path}"])
        cmd.extend(["-o", "ControlMaster=auto"])
        cmd.extend(["-o", f"ControlPersist={MUX_PERSIST_SECONDS}"])

    # Key — auto-resolve to RSA for legacy devices (iDRAC, switch)
    # Skip key for password-auth devices
    if not use_password:
        resolved_key = key_path
        if key_path and htype in LEGACY_HTYPES:
            resolved_key = _resolve_legacy_key(key_path)
        if resolved_key:
            cmd.extend(["-i", resolved_key])

    # Platform-specific options
    cmd.extend(platform.get("extra_opts", []))

    # Extra options
    if extra_opts:
        cmd.extend(extra_opts)

    # User@host
    cmd.append(f"{ssh_user}@{host}")

    # Command with sudo if needed — wrap entire command in sudo sh -c
    # so ALL chained commands (semicolons, pipes) run as root
    if sudo_prefix and command:
        escaped = command.replace("'", "'\\''")
        cmd.append(f"sudo sh -c '{escaped}'")
    elif command:
        cmd.append(command)

    return prefix + cmd


def run(
    host: str,
    command: str,
    user: Optional[str] = None,
    key_path: Optional[str] = None,
    connect_timeout: Optional[int] = None,
    command_timeout: int = 30,
    htype: str = "linux",
    use_sudo: bool = True,
    cfg=None,
) -> CmdResult:
    """Execute a command on a remote host via SSH (synchronous).

    Returns CmdResult with stdout, stderr, returncode, and duration.
    """
    ssh_cmd = _build_ssh_cmd(
        host=host,
        command=command,
        user=user,
        key_path=key_path,
        connect_timeout=connect_timeout,
        htype=htype,
        use_sudo=use_sudo,
        cfg=cfg,
    )

    logger.debug(f"ssh_start: {host} [{htype}]", command=command[:120])

    start = time.monotonic()
    try:
        result = subprocess.run(
            ssh_cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=command_timeout,
        )
        duration = time.monotonic() - start

        logger.cmd(
            f"ssh {host}: {command[:80]}",
            exit_code=result.returncode,
            duration=duration,
            htype=htype,
        )

        if result.returncode != 0:
            stderr_snippet = (result.stderr or "").strip()[:200]
            logger.error(
                f"ssh_failed: {host} [{htype}] rc={result.returncode}",
                command=command[:120],
                stderr=stderr_snippet,
                duration=duration,
            )

        # Performance tracking
        logger.perf("ssh", duration, host=host, htype=htype, ok=result.returncode == 0)

        return CmdResult(
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            returncode=result.returncode,
            duration=duration,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        logger.error(f"ssh_timeout: {host} [{htype}] after {command_timeout}s", command=command[:120])
        logger.perf("ssh", duration, host=host, htype=htype, ok=False, timeout=True)
        return CmdResult(stdout="", stderr=f"Timeout after {command_timeout}s", returncode=124, duration=duration)
    except OSError as e:
        duration = time.monotonic() - start
        logger.error(f"ssh_error: {host} [{htype}]: {e}", command=command[:120])
        logger.perf("ssh", duration, host=host, htype=htype, ok=False, error=str(e)[:80])
        return CmdResult(stdout="", stderr=str(e), returncode=1, duration=duration)


async def async_run(
    host: str,
    command: str,
    user: Optional[str] = None,
    key_path: Optional[str] = None,
    connect_timeout: Optional[int] = None,
    command_timeout: int = 30,
    htype: str = "linux",
    use_sudo: bool = True,
    cfg=None,
) -> CmdResult:
    """Execute a command on a remote host via SSH (async).

    Uses asyncio.create_subprocess_exec for non-blocking execution.
    """
    ssh_cmd = _build_ssh_cmd(
        host=host,
        command=command,
        user=user,
        key_path=key_path,
        connect_timeout=connect_timeout,
        htype=htype,
        use_sudo=use_sudo,
        cfg=cfg,
    )

    logger.debug(f"async_ssh_start: {host} [{htype}]", command=command[:120])

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=command_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            duration = time.monotonic() - start
            logger.error(f"async_ssh_timeout: {host} [{htype}] after {command_timeout}s", command=command[:120])
            logger.perf("ssh_async", duration, host=host, htype=htype, ok=False, timeout=True)
            return CmdResult(stdout="", stderr=f"Timeout after {command_timeout}s", returncode=124, duration=duration)

        duration = time.monotonic() - start
        rc = proc.returncode or 0
        out = stdout.decode().strip() if stdout else ""
        err = stderr.decode().strip() if stderr else ""

        logger.cmd(f"async_ssh {host}: {command[:80]}", exit_code=rc, duration=duration, htype=htype)
        if rc != 0:
            logger.error(f"async_ssh_failed: {host} [{htype}] rc={rc}", command=command[:120], stderr=err[:200])
        logger.perf("ssh_async", duration, host=host, htype=htype, ok=rc == 0)

        return CmdResult(stdout=out, stderr=err, returncode=rc, duration=duration)
    except OSError as e:
        duration = time.monotonic() - start
        logger.error(f"async_ssh_error: {host} [{htype}]: {e}", command=command[:120])
        logger.perf("ssh_async", duration, host=host, htype=htype, ok=False, error=str(e)[:80])
        return CmdResult(stdout="", stderr=str(e), returncode=1, duration=duration)


async def async_run_many(
    hosts: list,
    command: str,
    key_path: Optional[str] = None,
    connect_timeout: Optional[int] = None,
    command_timeout: int = 30,
    max_parallel: int = 5,
    use_sudo: bool = True,
    cfg=None,
) -> dict:
    """Execute a command across multiple hosts in parallel.

    Uses a semaphore to limit concurrency to max_parallel.
    Returns dict mapping Host -> CmdResult.

    This is the async pipeline that delivered 4x speedup in the Convergence.
    """
    semaphore = asyncio.Semaphore(max_parallel)
    results = {}

    async def _run_one(host: Host) -> None:
        async with semaphore:
            result = await async_run(
                host=host.ip,
                command=command,
                key_path=key_path,
                connect_timeout=connect_timeout,
                command_timeout=command_timeout,
                htype=host.htype,
                use_sudo=use_sudo,
                cfg=cfg,
            )
            if host.label not in results:
                results[host.label] = result
            else:
                results[f"{host.label}@{host.ip}"] = result
            results[host.ip] = result

    tasks = [asyncio.create_task(_run_one(h)) for h in hosts]
    await asyncio.gather(*tasks, return_exceptions=True)

    return results


def run_many(
    hosts: list,
    command: str,
    key_path: Optional[str] = None,
    connect_timeout: Optional[int] = None,
    command_timeout: int = 30,
    max_parallel: int = 5,
    use_sudo: bool = True,
    cfg=None,
) -> dict:
    """Synchronous wrapper for async_run_many.

    Convenience function for non-async callers.
    """
    return asyncio.run(
        async_run_many(
            hosts=hosts,
            command=command,
            key_path=key_path,
            connect_timeout=connect_timeout,
            command_timeout=command_timeout,
            max_parallel=max_parallel,
            use_sudo=use_sudo,
            cfg=cfg,
        )
    )
