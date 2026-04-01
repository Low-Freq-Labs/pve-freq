"""Package manager abstraction — multi-distro package operations.

Provides platform-aware commands for installing, querying, and managing
packages across apt, dnf, yum, pacman, zypper, apk, xbps, and pkg.

Usage:
    from freq.core.packages import install_cmd, query_installed_cmd, reboot_required_cmd, install_hint

    # Get the command to install a package
    cmd = install_cmd("lldpd", pkg_manager="apt")  # "apt install -y lldpd"

    # Get the command to check if a package is installed
    cmd = query_installed_cmd("openssh-server", pkg_manager="dnf")  # "rpm -q openssh-server"

    # Get a user-facing install hint
    hint = install_hint("sshpass", os_family="rhel")  # "dnf install sshpass"
"""


# ---------------------------------------------------------------------------
# Install commands
# ---------------------------------------------------------------------------

_INSTALL_CMDS = {
    "apt": "apt install -y {pkg}",
    "dnf": "dnf install -y {pkg}",
    "yum": "yum install -y {pkg}",
    "pacman": "pacman -S --noconfirm {pkg}",
    "zypper": "zypper install -y {pkg}",
    "apk": "apk add {pkg}",
    "xbps": "xbps-install -y {pkg}",
    "pkg": "pkg install -y {pkg}",
    "emerge": "emerge {pkg}",
}


def install_cmd(package: str, pkg_manager: str) -> str:
    """Return the shell command to install a package."""
    template = _INSTALL_CMDS.get(pkg_manager)
    if not template:
        return f"echo 'Unknown package manager: {pkg_manager}'"
    return template.format(pkg=package)


# ---------------------------------------------------------------------------
# Query installed
# ---------------------------------------------------------------------------

_QUERY_CMDS = {
    "apt": "dpkg -s {pkg} 2>/dev/null | grep -q 'Status: install ok'",
    "dnf": "rpm -q {pkg} >/dev/null 2>&1",
    "yum": "rpm -q {pkg} >/dev/null 2>&1",
    "pacman": "pacman -Q {pkg} >/dev/null 2>&1",
    "zypper": "rpm -q {pkg} >/dev/null 2>&1",
    "apk": "apk info -e {pkg} >/dev/null 2>&1",
    "xbps": "xbps-query {pkg} >/dev/null 2>&1",
    "pkg": "pkg info {pkg} >/dev/null 2>&1",
    "emerge": "equery list {pkg} >/dev/null 2>&1",
}


def query_installed_cmd(package: str, pkg_manager: str) -> str:
    """Return a shell command that exits 0 if package is installed."""
    template = _QUERY_CMDS.get(pkg_manager)
    if not template:
        return "false"
    return template.format(pkg=package)


# ---------------------------------------------------------------------------
# List installed packages
# ---------------------------------------------------------------------------

_LIST_CMDS = {
    "apt": "dpkg -l | awk '/^ii/ {print $2}'",
    "dnf": "rpm -qa --qf '%{NAME}\\n'",
    "yum": "rpm -qa --qf '%{NAME}\\n'",
    "pacman": "pacman -Qq",
    "zypper": "rpm -qa --qf '%{NAME}\\n'",
    "apk": "apk list --installed -q",
    "xbps": "xbps-query -l | awk '{print $2}' | sed 's/-[0-9].*//'",
    "pkg": "pkg info -q",
    "emerge": "qlist -I",
}


def list_installed_cmd(pkg_manager: str) -> str:
    """Return a shell command that prints one package name per line."""
    return _LIST_CMDS.get(pkg_manager, "echo 'unsupported'")


# ---------------------------------------------------------------------------
# Check for updates
# ---------------------------------------------------------------------------

_UPDATE_CHECK_CMDS = {
    "apt": "apt list --upgradable 2>/dev/null | grep -c upgradable || echo 0",
    "dnf": "dnf check-update -q 2>/dev/null; echo $?",
    "yum": "yum check-update -q 2>/dev/null; echo $?",
    "pacman": "checkupdates 2>/dev/null | wc -l",
    "zypper": "zypper list-updates 2>/dev/null | grep -c '^v' || echo 0",
    "apk": "apk upgrade --simulate 2>/dev/null | grep -c Upgrading || echo 0",
    "xbps": "xbps-install -Sun 2>/dev/null | wc -l",
    "pkg": "pkg upgrade -n 2>/dev/null | grep -c 'to be' || echo 0",
}


def check_updates_cmd(pkg_manager: str) -> str:
    """Return a shell command that shows available updates."""
    return _UPDATE_CHECK_CMDS.get(pkg_manager, "echo 'unsupported'")


# ---------------------------------------------------------------------------
# Reboot required
# ---------------------------------------------------------------------------

_REBOOT_CHECK_CMDS = {
    "apt": "test -f /var/run/reboot-required && echo REBOOT || echo OK",
    "dnf": "dnf needs-restarting -r >/dev/null 2>&1 && echo OK || echo REBOOT",
    "yum": "needs-restarting -r >/dev/null 2>&1 && echo OK || echo REBOOT",
    "zypper": "zypper needs-rebooting >/dev/null 2>&1 && echo REBOOT || echo OK",
    "pacman": "echo OK",  # Arch doesn't have a standard reboot check
    "apk": "echo OK",
}


def reboot_required_cmd(pkg_manager: str) -> str:
    """Return a shell command that prints REBOOT if reboot is needed, OK otherwise."""
    return _REBOOT_CHECK_CMDS.get(pkg_manager, "echo OK")


# ---------------------------------------------------------------------------
# User-facing install hints
# ---------------------------------------------------------------------------

_FAMILY_HINTS = {
    "debian": "apt install {pkg}",
    "rhel": "dnf install {pkg}",
    "arch": "pacman -S {pkg}",
    "suse": "zypper install {pkg}",
    "alpine": "apk add {pkg}",
    "gentoo": "emerge {pkg}",
    "void": "xbps-install {pkg}",
    "freebsd": "pkg install {pkg}",
}


def install_hint(package: str, os_family: str = "") -> str:
    """Return a user-friendly install instruction string."""
    if not os_family:
        from freq.core.platform import Platform
        os_family = Platform.detect().os_family

    template = _FAMILY_HINTS.get(os_family, "Install '{pkg}' using your package manager")
    return template.format(pkg=package)


# ---------------------------------------------------------------------------
# Package name mapping (cross-distro package names)
# ---------------------------------------------------------------------------

# Some packages have different names across distros
_PKG_NAMES = {
    "lldpd": {
        "apt": "lldpd",
        "dnf": "lldpd",
        "pacman": "lldpd",
        "apk": "lldpd",
        "zypper": "lldpd",
    },
    "sshpass": {
        "apt": "sshpass",
        "dnf": "sshpass",
        "pacman": "sshpass",
        "apk": "sshpass",
        "zypper": "sshpass",
    },
    "auditd": {
        "apt": "auditd",
        "dnf": "audit",
        "pacman": "audit",
        "zypper": "audit",
    },
    "openssh-server": {
        "apt": "openssh-server",
        "dnf": "openssh-server",
        "pacman": "openssh",
        "apk": "openssh",
        "zypper": "openssh",
    },
}


def resolve_pkg_name(generic_name: str, pkg_manager: str) -> str:
    """Resolve a generic package name to the distro-specific name."""
    mapping = _PKG_NAMES.get(generic_name)
    if mapping:
        return mapping.get(pkg_manager, generic_name)
    return generic_name
