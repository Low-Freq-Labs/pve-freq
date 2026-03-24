"""Async SSH transport — platform-aware, timeout-safe.

Uses sshpass + asyncio subprocess for non-blocking SSH execution.
Platform-specific SSH configuration (crypto, users, sudo) is handled
automatically based on host type.
"""
import asyncio
import shutil
import time
from engine.core.types import Host, CmdResult

# Platform SSH configuration
# Each platform type has: user, extra SSH options, sudo prefix
PLATFORM_SSH = {
    "linux": {
        "user": "svc-admin",
        "extra": [],
        "sudo": "sudo ",
    },
    "pve": {
        "user": "svc-admin",
        "extra": [],
        "sudo": "sudo ",
    },
    "truenas": {
        "user": "svc-admin",
        "extra": [],
        "sudo": "sudo ",
    },
    "pfsense": {
        "user": "root",
        "extra": [],
        "sudo": "",  # Already root
    },
    "idrac": {
        "user": "svc-admin",
        "extra": [
            "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
        ],
        "sudo": "",
    },
    "switch": {
        "user": "jarvis-ai",
        "extra": [
            "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            "-o", "Ciphers=+aes128-cbc,aes256-cbc,3des-cbc",
        ],
        "sudo": "",
    },
}


class SSHTransport:
    """Async SSH transport with platform awareness.

    Features:
    - Platform-specific user, crypto, and sudo handling
    - Timeout on every operation (connect + command)
    - Non-blocking via asyncio subprocess
    - Credential isolation (password passed via sshpass, never in command)
    """

    def __init__(self, password: str = "",
                 connect_timeout: int = 10, command_timeout: int = 30):
        self.password = password
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self._validate_deps()

    def _validate_deps(self):
        """Verify sshpass is available."""
        if not shutil.which("sshpass"):
            raise RuntimeError(
                "sshpass is required for the engine SSH transport. "
                "Install: apt install sshpass"
            )

    async def execute(self, host: Host, command: str,
                      sudo: bool = False) -> CmdResult:
        """Execute command on host via SSH. Platform-aware.

        Args:
            host: Target host object
            command: Shell command to execute
            sudo: Whether to prefix with sudo (platform-aware)

        Returns:
            CmdResult with stdout, stderr, returncode, duration
        """
        plat = PLATFORM_SSH.get(host.htype, PLATFORM_SSH["linux"])

        if sudo and plat["sudo"]:
            command = f"{plat['sudo']}{command}"

        ssh_cmd = [
            "sshpass", "-p", self.password,
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={self.connect_timeout}",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=3",
            "-o", "BatchMode=no",
            "-o", "LogLevel=ERROR",
            *plat["extra"],
            f"{plat['user']}@{host.ip}",
            command,
        ]

        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.command_timeout
            )
            return CmdResult(
                stdout=stdout.decode(errors="replace").strip(),
                stderr=stderr.decode(errors="replace").strip(),
                returncode=proc.returncode or 0,
                duration=time.time() - t0,
            )
        except asyncio.TimeoutError:
            # Kill the hung process
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return CmdResult("", "Command timed out", -1, time.time() - t0)
        except Exception as e:
            return CmdResult("", str(e), -1, time.time() - t0)

    async def ping(self, ip: str) -> bool:
        """Async ping check — verifies host is reachable."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", "2", ip,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5)
            return proc.returncode == 0
        except Exception:
            return False

    async def test_ssh(self, host: Host) -> CmdResult:
        """Test SSH connectivity with a simple echo command."""
        return await self.execute(host, "echo FREQ_OK")
