"""Input validation for FREQ — trust boundary enforcement.

Provides: is_valid_ip(), is_valid_hostname(), is_valid_vmid(),
          is_valid_username(), is_valid_label(), is_valid_ssh_key()

Gates for user input. Every external value (CLI args, config file entries,
API request parameters) passes through here before reaching any module.
Prevents command injection, path traversal, and invalid state.

Replaces: Scattered regex checks and bare int() casts throughout modules

Architecture:
    - Pure validation functions returning bool — no side effects
    - Regex-based for strings, range-based for numeric inputs
    - Constants for limits (MAX_HOSTNAME_LEN, VMID range, etc.)

Design decisions:
    - Validation is strict. "Close enough" IPs are rejected, not corrected.
    - VMID range 100-999999999 matches Proxmox's actual limits.
    - Hostnames follow RFC 1123. No underscores (DNS doesn't allow them).
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
    pattern = re.compile(
        r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
    )
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


def sanitize_label(name: str) -> str:
    """Convert a PVE VM name to a safe host label.

    Rules: lowercase, alphanumeric + hyphens only, no leading/trailing hyphens,
    no consecutive hyphens, max 64 chars. Strips anything shell-unsafe.
    """
    s = name.lower().strip()
    # Replace underscores and spaces with hyphens
    s = s.replace("_", "-").replace(" ", "-")
    # Remove anything that isn't alphanumeric or hyphen
    s = re.sub(r"[^a-z0-9\-]", "", s)
    # Collapse consecutive hyphens
    s = re.sub(r"-{2,}", "-", s)
    # Strip leading/trailing hyphens
    s = s.strip("-")
    # Truncate
    if len(s) > MAX_LABEL_LEN:
        s = s[:MAX_LABEL_LEN].rstrip("-")
    return s or "unknown"


def ssh_pubkey(value: str) -> bool:
    """Validate an SSH public key (basic format check)."""
    parts = value.strip().split()
    if len(parts) < 2:
        return False
    valid_types = {"ssh-rsa", "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}
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


def shell_safe_name(value: str) -> bool:
    """VM name safe for shell: alphanumeric + hyphens/underscores/dots, max 63."""
    if not value or len(value) > 63:
        return False
    return bool(re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$").match(value))


def bay_device(value: str) -> bool:
    """Block device name (sda, nvme0n1). No slashes, no dots."""
    if not value or len(value) > 32:
        return False
    return bool(re.compile(r"^[a-z][a-z0-9]*$").match(value))


def is_protected_vmid(value, protected_ids: list, protected_ranges: list, vm_tags: list = None) -> bool:
    """Check if a VMID is protected.

    Protection sources (any match = protected):
    1. PVE tag "prod" or "protected" on the VM (preferred — auto-discovery)
    2. Static protected_ids list from freq.toml (fallback)
    3. Static protected_ranges from freq.toml (fallback)

    Args:
        vm_tags: Optional list of PVE tags for this VM. If provided and
                 contains "prod" or "protected", the VM is protected regardless
                 of the static lists.
    """
    try:
        n = int(value)
    except (ValueError, TypeError):
        return False

    # Tag-based protection — PVE tags are source of truth
    if vm_tags:
        if "prod" in vm_tags or "protected" in vm_tags:
            return True

    # Static fallback — freq.toml lists/ranges
    if n in protected_ids:
        return True

    for start, end in protected_ranges:
        if start <= n <= end:
            return True

    return False
