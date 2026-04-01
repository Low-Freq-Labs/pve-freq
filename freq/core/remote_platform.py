"""Remote platform detection — detect OS, package manager, and init system over SSH.

Runs a single SSH command to gather all platform info from a remote host,
then parses it into a RemotePlatform dataclass. Results are cached in memory.

Usage:
    from freq.core.remote_platform import RemotePlatform
    rp = RemotePlatform.detect(host, cfg)
    print(rp.pkg_manager)   # "apt"
    print(rp.init_system)   # "systemd"
"""
import dataclasses
from typing import Optional

from freq.core.types import Host


# Single SSH command that gathers everything we need
_DETECT_SCRIPT = (
    "cat /etc/os-release 2>/dev/null || echo 'ID=unknown';"
    "echo '---FREQ_SEP---';"
    "test -d /run/systemd/system && echo 'INIT=systemd'"
    " || (command -v rc-service >/dev/null 2>&1 && echo 'INIT=openrc')"
    " || (command -v sv >/dev/null 2>&1 && test -d /etc/sv && echo 'INIT=runit')"
    " || echo 'INIT=unknown';"
    "command -v apt >/dev/null 2>&1 && echo 'PKG=apt';"
    "command -v dnf >/dev/null 2>&1 && echo 'PKG=dnf';"
    "command -v yum >/dev/null 2>&1 && echo 'PKG=yum';"
    "command -v pacman >/dev/null 2>&1 && echo 'PKG=pacman';"
    "command -v zypper >/dev/null 2>&1 && echo 'PKG=zypper';"
    "command -v apk >/dev/null 2>&1 && echo 'PKG=apk';"
    "command -v xbps-install >/dev/null 2>&1 && echo 'PKG=xbps';"
    "command -v pkg >/dev/null 2>&1 && echo 'PKG=pkg';"
    "command -v bash >/dev/null 2>&1 && echo 'HAS_BASH=1' || echo 'HAS_BASH=0';"
    "command -v docker >/dev/null 2>&1 && echo 'HAS_DOCKER=1' || echo 'HAS_DOCKER=0';"
    "uname -m 2>/dev/null || echo 'unknown'"
)


@dataclasses.dataclass(frozen=True)
class RemotePlatform:
    """Immutable snapshot of a remote host's platform."""

    host_label: str
    os_id: str
    os_version: str
    os_family: str
    os_pretty: str
    init_system: str
    pkg_manager: str
    arch: str
    has_bash: bool
    has_docker: bool

    @classmethod
    def detect(cls, host: "Host", cfg) -> Optional["RemotePlatform"]:
        """Detect platform of a remote host via SSH. Returns None on failure."""
        cache_key = host.label or host.ip
        if cache_key in _cache:
            return _cache[cache_key]

        from freq.core import ssh

        result = ssh.run(host, _DETECT_SCRIPT, cfg, timeout=10)
        if result.rc != 0:
            return None

        rp = cls._parse(cache_key, result.stdout)
        if rp:
            _cache[cache_key] = rp
        return rp

    @classmethod
    def _parse(cls, label: str, output: str) -> Optional["RemotePlatform"]:
        """Parse the detection script output."""
        parts = output.split("---FREQ_SEP---")
        if len(parts) < 2:
            return None

        os_release_text = parts[0]
        flags_text = parts[1]

        # Parse os-release
        os_id = "unknown"
        os_version = ""
        os_pretty = ""
        id_like = ""
        for line in os_release_text.strip().splitlines():
            line = line.strip()
            if line.startswith("ID="):
                os_id = line.split("=", 1)[1].strip('"').lower()
            elif line.startswith("VERSION_ID="):
                os_version = line.split("=", 1)[1].strip('"')
            elif line.startswith("PRETTY_NAME="):
                os_pretty = line.split("=", 1)[1].strip('"')
            elif line.startswith("ID_LIKE="):
                id_like = line.split("=", 1)[1].strip('"').lower()

        # Resolve family using the same map as local platform
        from freq.core.platform import _FAMILY_MAP
        os_family = _FAMILY_MAP.get(os_id, "")
        if not os_family and id_like:
            for token in id_like.split():
                if token in _FAMILY_MAP:
                    os_family = _FAMILY_MAP[token]
                    break
        if not os_family:
            os_family = os_id

        # Parse flags
        init_system = "unknown"
        pkg_manager = "unknown"
        arch = "unknown"
        has_bash = False
        has_docker = False

        for line in flags_text.strip().splitlines():
            line = line.strip()
            if line.startswith("INIT="):
                init_system = line.split("=", 1)[1]
            elif line.startswith("PKG="):
                if pkg_manager == "unknown":  # first match wins (apt before dnf)
                    pkg_manager = line.split("=", 1)[1]
            elif line.startswith("HAS_BASH="):
                has_bash = line.split("=", 1)[1] == "1"
            elif line.startswith("HAS_DOCKER="):
                has_docker = line.split("=", 1)[1] == "1"
            elif not line.startswith(("INIT=", "PKG=", "HAS_")):
                # Last non-flag line is uname -m output
                if line and line != "unknown":
                    arch = line

        return cls(
            host_label=label,
            os_id=os_id,
            os_version=os_version,
            os_family=os_family,
            os_pretty=os_pretty or f"{os_id} {os_version}",
            init_system=init_system,
            pkg_manager=pkg_manager,
            arch=arch,
            has_bash=has_bash,
            has_docker=has_docker,
        )

    @classmethod
    def clear_cache(cls):
        """Clear the detection cache."""
        _cache.clear()


# Module-level cache: host_label → RemotePlatform
_cache: dict = {}
