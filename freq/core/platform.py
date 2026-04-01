"""Local platform detection — detect OS, package manager, init system, and capabilities.

Used by all FREQ modules that need platform-aware behavior instead of
hardcoding apt/systemctl/bash assumptions.

Usage:
    from freq.core.platform import Platform
    plat = Platform.detect()
    print(plat.pkg_manager)   # "apt"
    print(plat.init_system)   # "systemd"
    print(plat.os_family)     # "debian"
"""
import dataclasses
import os
import platform as _platform
import shutil
import sys


@dataclasses.dataclass(frozen=True)
class Platform:
    """Immutable snapshot of the local platform."""

    # OS identity
    os_id: str          # "debian", "ubuntu", "rocky", "arch", "alpine", "freebsd"
    os_version: str     # "13", "24.04", "9.5"
    os_family: str      # "debian", "rhel", "arch", "alpine", "suse", "gentoo", "void", "freebsd"
    os_pretty: str      # "Debian GNU/Linux 13 (trixie)"

    # Python
    python_version: tuple  # (3, 11, 2)

    # Init system
    init_system: str    # "systemd", "openrc", "runit", "sysvinit", "rc.d", "unknown"

    # Package manager
    pkg_manager: str    # "apt", "dnf", "yum", "pacman", "zypper", "apk", "xbps", "pkg", "emerge", "unknown"

    # Privilege escalation
    sudo_group: str     # "sudo" or "wheel"

    # Architecture
    arch: str           # "x86_64", "aarch64", "armv7l"

    # Key capabilities
    has_bash: bool
    has_docker: bool
    has_systemd: bool

    @classmethod
    def detect(cls) -> "Platform":
        """Detect the local platform. Cached after first call."""
        if not hasattr(cls, "_cached"):
            cls._cached = cls._do_detect()
        return cls._cached

    @classmethod
    def _do_detect(cls) -> "Platform":
        os_id, os_version, os_family, os_pretty = _detect_os()
        init_system = _detect_init()
        pkg_manager = _detect_pkg_manager()
        sudo_group = "wheel" if os_family in ("rhel", "arch", "freebsd", "suse", "gentoo", "void") else "sudo"
        arch = _platform.machine() or "unknown"
        has_bash = shutil.which("bash") is not None
        has_docker = shutil.which("docker") is not None
        has_systemd = init_system == "systemd"

        return cls(
            os_id=os_id,
            os_version=os_version,
            os_family=os_family,
            os_pretty=os_pretty,
            python_version=sys.version_info[:3],
            init_system=init_system,
            pkg_manager=pkg_manager,
            sudo_group=sudo_group,
            arch=arch,
            has_bash=has_bash,
            has_docker=has_docker,
            has_systemd=has_systemd,
        )

    @classmethod
    def clear_cache(cls):
        """Clear the cached platform detection (for testing)."""
        if hasattr(cls, "_cached"):
            del cls._cached


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

# Family normalization: distro ID → family
_FAMILY_MAP = {
    "debian": "debian",
    "ubuntu": "debian",
    "linuxmint": "debian",
    "pop": "debian",
    "raspbian": "debian",
    "kali": "debian",
    "proxmox": "debian",
    "rhel": "rhel",
    "rocky": "rhel",
    "almalinux": "rhel",
    "centos": "rhel",
    "fedora": "rhel",
    "amzn": "rhel",
    "ol": "rhel",
    "arch": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "opensuse-leap": "suse",
    "opensuse-tumbleweed": "suse",
    "sles": "suse",
    "alpine": "alpine",
    "gentoo": "gentoo",
    "void": "void",
    "freebsd": "freebsd",
    "opnsense": "freebsd",
    "pfsense": "freebsd",
    "nixos": "nix",
    "slackware": "slackware",
}


def _detect_os() -> tuple:
    """Parse /etc/os-release (Linux) or uname (FreeBSD). Returns (id, version, family, pretty)."""
    os_name = _platform.system()

    if os_name == "FreeBSD":
        version = _platform.release()
        return ("freebsd", version, "freebsd", f"FreeBSD {version}")

    # Linux — parse /etc/os-release
    os_id = "linux"
    os_version = ""
    os_pretty = f"Linux {_platform.release()}"
    id_like = ""

    try:
        with open("/etc/os-release") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ID="):
                    os_id = line.split("=", 1)[1].strip('"').lower()
                elif line.startswith("VERSION_ID="):
                    os_version = line.split("=", 1)[1].strip('"')
                elif line.startswith("PRETTY_NAME="):
                    os_pretty = line.split("=", 1)[1].strip('"')
                elif line.startswith("ID_LIKE="):
                    id_like = line.split("=", 1)[1].strip('"').lower()
    except FileNotFoundError:
        pass

    # Resolve family
    os_family = _FAMILY_MAP.get(os_id, "")
    if not os_family and id_like:
        # Try ID_LIKE tokens (e.g. "rhel centos fedora" → "rhel")
        for token in id_like.split():
            if token in _FAMILY_MAP:
                os_family = _FAMILY_MAP[token]
                break
    if not os_family:
        os_family = os_id  # fallback: family = distro id

    return (os_id, os_version, os_family, os_pretty)


def _detect_init() -> str:
    """Detect the init system."""
    # systemd: PID 1 is systemd, or systemctl exists
    if os.path.isdir("/run/systemd/system"):
        return "systemd"
    if shutil.which("systemctl"):
        return "systemd"
    # OpenRC
    if shutil.which("rc-service") or os.path.isdir("/etc/init.d") and os.path.exists("/sbin/openrc"):
        return "openrc"
    # runit
    if shutil.which("sv") and os.path.isdir("/etc/sv"):
        return "runit"
    # FreeBSD rc.d
    if os.path.isdir("/etc/rc.d") and _platform.system() == "FreeBSD":
        return "rc.d"
    # sysvinit fallback
    if os.path.isdir("/etc/init.d"):
        return "sysvinit"
    return "unknown"


def _detect_pkg_manager() -> str:
    """Detect the primary package manager."""
    # Order matters: more specific first
    checks = [
        ("apt", "apt"),
        ("dnf", "dnf"),
        ("yum", "yum"),
        ("pacman", "pacman"),
        ("zypper", "zypper"),
        ("apk", "apk"),
        ("xbps-install", "xbps"),
        ("emerge", "emerge"),
        ("pkg", "pkg"),
    ]
    for binary, name in checks:
        if shutil.which(binary):
            return name
    return "unknown"
