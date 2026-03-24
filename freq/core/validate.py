"""Input validation for FREQ.

Gates for user input: IPs, hostnames, usernames, VMIDs, SSH keys.
Every external input passes through here before reaching any module.
"""
import re

# Validation limits
MAX_HOSTNAME_LEN = 253
MAX_USERNAME_LEN = 32
MAX_LABEL_LEN = 64
MIN_VMID = 100
MAX_VMID = 999999999
MAX_VLAN_ID = 4094
MAX_PORT = 65535


def ip(value: str) -> bool:
    """Validate an IPv4 address."""
    parts = value.strip().split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            n = int(part)
            if n < 0 or n > 255:
                return False
        except ValueError:
            return False
    return True


def hostname(value: str) -> bool:
    """Validate a hostname (RFC 1123)."""
    if not value or len(value) > MAX_HOSTNAME_LEN:
        return False
    pattern = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$")
    return bool(pattern.match(value))


def username(value: str) -> bool:
    """Validate a Linux username."""
    if not value or len(value) > MAX_USERNAME_LEN:
        return False
    pattern = re.compile(r"^[a-z_][a-z0-9_-]*[$]?$")
    return bool(pattern.match(value))


def vmid(value) -> bool:
    """Validate a Proxmox VMID (100-999999999)."""
    try:
        n = int(value)
        return MIN_VMID <= n <= MAX_VMID
    except (ValueError, TypeError):
        return False


def label(value: str) -> bool:
    """Validate a host label (alphanumeric + hyphens)."""
    if not value or len(value) > MAX_LABEL_LEN:
        return False
    pattern = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$")
    return bool(pattern.match(value))


def ssh_pubkey(value: str) -> bool:
    """Validate an SSH public key (basic format check)."""
    parts = value.strip().split()
    if len(parts) < 2:
        return False
    valid_types = {"ssh-rsa", "ssh-ed25519", "ecdsa-sha2-nistp256",
                   "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}
    return parts[0] in valid_types


def vlan_id(value) -> bool:
    """Validate a VLAN ID (0-4094)."""
    try:
        n = int(value)
        return 0 <= n <= MAX_VLAN_ID
    except (ValueError, TypeError):
        return False


def port(value) -> bool:
    """Validate a network port (1-65535)."""
    try:
        n = int(value)
        return 1 <= n <= MAX_PORT
    except (ValueError, TypeError):
        return False


def is_protected_vmid(value, protected_ids: list, protected_ranges: list) -> bool:
    """Check if a VMID is in the protected list or ranges."""
    try:
        n = int(value)
    except (ValueError, TypeError):
        return False

    if n in protected_ids:
        return True

    for start, end in protected_ranges:
        if start <= n <= end:
            return True

    return False
