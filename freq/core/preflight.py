"""Pre-flight environment checks for FREQ.

Provides: check_python_version(), check_platform(), check_disk_space(),
          check_required_binaries(), run_preflight(), get_install_hint()

Reusable validation module used by freq doctor, freq init, and install.sh.
Every check returns (ok, message) or (ok, message, extra). Designed to be
importable from install.sh via `python3 -c "from freq.core.preflight import ..."`.

Replaces: Ad-hoc checks scattered across init scripts

Architecture:
    - Each check is an independent function returning a tuple
    - run_preflight() orchestrates all checks and prints results
    - get_install_hint() provides distro-aware install instructions
    - Parses /etc/os-release for distro detection (shared with platform.py)

Design decisions:
    - Must work standalone — no freq.core imports except types.
    - Python 3.11+ required. MIN_PYTHON enforced here and in compat.py.
    - Install hints cover Debian, Ubuntu, RHEL, Rocky, Alma, openSUSE families.
"""

import os
import platform
import shutil
import sys

from typing import Dict, List, Tuple

MIN_PYTHON = (3, 11)

# Required system binaries — FREQ cannot function without these
REQUIRED_BINARIES = ["ssh", "ssh-keygen"]

# Optional binaries — FREQ works without them but some features are limited
OPTIONAL_BINARIES = ["sshpass", "jq", "curl"]

# Install instructions per distro family
_INSTALL_CMDS = {
    "debian": {"python": "apt install python3", "sshpass": "apt install sshpass"},
    "ubuntu": {"python": "apt install python3", "sshpass": "apt install sshpass"},
    "rhel": {"python": "dnf install python39", "sshpass": "dnf install sshpass"},
    "rocky": {"python": "dnf install python39", "sshpass": "dnf install sshpass"},
    "almalinux": {"python": "dnf install python39", "sshpass": "dnf install sshpass"},
    "opensuse": {"python": "zypper install python39", "sshpass": "zypper install sshpass"},
}


def check_python_version() -> Tuple[bool, str]:
    """Check Python >= 3.7. Returns (ok, message)."""
    ver = sys.version_info
    ver_str = "{}.{}.{}".format(ver.major, ver.minor, ver.micro)
    if ver >= MIN_PYTHON:
        extra = ""
        if ver < (3, 11):
            extra = " (fallback TOML parser)"
        return (True, "Python {}{}".format(ver_str, extra))
    else:
        return (False, "Python {} — need >= {}.{}".format(ver_str, MIN_PYTHON[0], MIN_PYTHON[1]))


def check_platform() -> Tuple[bool, str, Dict[str, str]]:
    """Detect OS and distro. Returns (ok, message, {distro, version, family})."""
    info = {"distro": "", "version": "", "family": "", "pretty_name": ""}
    os_name = platform.system()

    if os_name != "Linux":
        return (False, "Platform: {} (FREQ requires Linux)".format(os_name), info)

    try:
        with open("/etc/os-release") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ID="):
                    info["distro"] = line.split("=", 1)[1].strip('"')
                elif line.startswith("VERSION_ID="):
                    info["version"] = line.split("=", 1)[1].strip('"')
                elif line.startswith("PRETTY_NAME="):
                    info["pretty_name"] = line.split("=", 1)[1].strip('"')
                elif line.startswith("ID_LIKE="):
                    info["family"] = line.split("=", 1)[1].strip('"')
    except FileNotFoundError:
        return (True, "Platform: Linux {} (no /etc/os-release)".format(platform.release()), info)

    # Normalize family
    distro = info["distro"].lower()
    if distro in ("debian", "ubuntu"):
        info["family"] = "debian"
    elif distro in ("rhel", "rocky", "almalinux", "centos", "fedora"):
        info["family"] = "rhel"
    elif "suse" in distro:
        info["family"] = "suse"

    name = info["pretty_name"] or "{} {}".format(info["distro"], info["version"])
    return (True, "Platform: {}".format(name), info)


def check_disk_space(path: str, min_mb: int = 50) -> Tuple[bool, str]:
    """Check available disk space at path. Returns (ok, message)."""
    try:
        stat = os.statvfs(path)
        free_mb = (stat.f_bavail * stat.f_frsize) // (1024 * 1024)
        if free_mb >= min_mb:
            return (True, "Disk: {}MB free at {}".format(free_mb, path))
        else:
            return (False, "Disk: only {}MB free at {} (need {}MB)".format(free_mb, path, min_mb))
    except OSError as e:
        return (False, "Disk: cannot check {} — {}".format(path, e))


def check_required_binaries() -> Tuple[bool, str, List[str]]:
    """Check required system binaries. Returns (ok, message, missing_list)."""
    missing = [b for b in REQUIRED_BINARIES if not shutil.which(b)]
    if missing:
        return (False, "Missing required: {}".format(", ".join(missing)), missing)
    return (True, "Required tools: all found", [])


def check_optional_binaries() -> Tuple[bool, str, List[str]]:
    """Check optional system binaries. Returns (ok, message, missing_list)."""
    missing = [b for b in OPTIONAL_BINARIES if not shutil.which(b)]
    if missing:
        return (True, "Optional tools missing: {}".format(", ".join(missing)), missing)
    return (True, "Optional tools: all found", [])


def get_install_hint(binary: str, family: str = "") -> str:
    """Get distro-specific install command for a binary."""
    if not family:
        _, _, info = check_platform()
        family = info.get("family", "")

    cmds = _INSTALL_CMDS.get(family, {})
    if binary == "python" or binary == "python3":
        return cmds.get("python", "Install Python 3.7+ for your distro")
    return cmds.get(binary, "Install '{}' for your distro".format(binary))


def run_preflight(install_dir: str = "/opt/pve-freq", quiet: bool = False) -> bool:
    """Run all pre-flight checks. Returns True if all critical checks pass.

    If quiet=False, prints results to stdout (for install.sh integration).
    """
    all_ok = True

    checks = [
        ("Python", check_python_version),
        ("Platform", lambda: check_platform()[:2]),
        ("Disk", lambda: check_disk_space(install_dir)),
        ("Required", lambda: check_required_binaries()[:2]),
        ("Optional", lambda: check_optional_binaries()[:2]),
    ]

    for name, fn in checks:
        ok, msg = fn()
        if not quiet:
            status = "  [OK]  " if ok else "  [FAIL]"
            print("{} {}".format(status, msg))
        if not ok and name != "Optional":
            all_ok = False

    return all_ok
