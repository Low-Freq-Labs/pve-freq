"""Wake-on-LAN — send magic packets to power on machines remotely.

Uses pure Python stdlib socket — no external tools needed.
Magic packet: 6 bytes 0xFF followed by 16 repetitions of target MAC (6 bytes each).
Sent as UDP broadcast to port 9.

Replaces: etherwake, wakeonlan CLI tools (not always installed)

Architecture:
    - Pure stdlib: socket module only, zero dependencies
    - MAC parsing accepts any common format (colon, dash, dot, bare hex)
    - UDP broadcast to port 9 (standard WoL port)
    - Works on any network segment reachable from the sending host

Design decisions:
    - No external tools. etherwake needs root, wakeonlan needs apt install.
      Python socket with SO_BROADCAST works from userspace.
    - Broadcast default is 255.255.255.255 (limited broadcast). For directed
      broadcast across VLANs, pass the subnet broadcast (e.g., 10.25.10.255).
    - Port 9 is the de facto standard. Port 7 (echo) also works but 9 is
      more widely supported by NICs and BIOS implementations.
"""
import re
import socket


def parse_mac(mac_str: str) -> bytes:
    """Parse a MAC address string into 6 raw bytes.

    Accepts common formats:
        - AA:BB:CC:DD:EE:FF  (colon-separated)
        - AA-BB-CC-DD-EE-FF  (dash-separated)
        - AABB.CCDD.EEFF     (Cisco dot notation)
        - AABBCCDDEEFF        (bare hex)

    Args:
        mac_str: MAC address in any common format.

    Returns:
        6-byte bytes object representing the MAC.

    Raises:
        ValueError: If mac_str is not a valid MAC address.
    """
    if not mac_str or not isinstance(mac_str, str):
        raise ValueError(f"Invalid MAC address: {mac_str!r}")

    # Strip whitespace and normalize
    cleaned = mac_str.strip()

    # Remove all common separators to get bare hex
    bare = re.sub(r'[:\-.]', '', cleaned)

    # Validate: must be exactly 12 hex characters
    if len(bare) != 12:
        raise ValueError(
            f"Invalid MAC address: {mac_str!r} "
            f"(expected 12 hex digits, got {len(bare)} after stripping separators)"
        )

    if not re.match(r'^[0-9a-fA-F]{12}$', bare):
        raise ValueError(
            f"Invalid MAC address: {mac_str!r} (contains non-hex characters)"
        )

    return bytes.fromhex(bare)


def build_magic_packet(mac_bytes: bytes) -> bytes:
    """Build a WoL magic packet from raw MAC bytes.

    Magic packet structure:
        - 6 bytes of 0xFF (synchronization stream)
        - 16 repetitions of the target MAC address (6 bytes each)
        - Total: 6 + (16 * 6) = 102 bytes

    Args:
        mac_bytes: 6-byte MAC address (from parse_mac()).

    Returns:
        102-byte magic packet ready to send over UDP.

    Raises:
        ValueError: If mac_bytes is not exactly 6 bytes.
    """
    if len(mac_bytes) != 6:
        raise ValueError(f"MAC must be 6 bytes, got {len(mac_bytes)}")

    # 6 bytes 0xFF + 16 repetitions of target MAC
    return b'\xff' * 6 + mac_bytes * 16


def send_wol(mac_address: str, broadcast: str = "255.255.255.255", port: int = 9) -> bool:
    """Send a Wake-on-LAN magic packet.

    Sends a UDP broadcast containing the magic packet to wake a target
    machine. The target NIC must have WoL enabled in BIOS/firmware.

    Args:
        mac_address: Target MAC in any common format
                     (AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, etc.)
        broadcast: Broadcast address (default: 255.255.255.255).
                   Use subnet broadcast for cross-VLAN WoL
                   (e.g., 10.25.10.255).
        port: WoL port (default: 9).

    Returns:
        True on success.

    Raises:
        ValueError: If MAC address is invalid.
        OSError: If socket operation fails (permissions, network issues).
    """
    # Parse and validate MAC
    mac_bytes = parse_mac(mac_address)

    # Build the magic packet
    packet = build_magic_packet(mac_bytes)

    # Create UDP socket, enable broadcast, send
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    finally:
        sock.close()

    return True


def send_wol_multi(mac_addresses: list, broadcast: str = "255.255.255.255", port: int = 9) -> dict:
    """Send WoL packets to multiple MAC addresses.

    Sends one magic packet per MAC. A single socket is reused for
    efficiency when waking multiple machines.

    Args:
        mac_addresses: List of MAC address strings.
        broadcast: Broadcast address (default: 255.255.255.255).
        port: WoL port (default: 9).

    Returns:
        Dict mapping each MAC to {"ok": True} or {"ok": False, "error": str}.
    """
    results = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for mac in mac_addresses:
            try:
                mac_bytes = parse_mac(mac)
                packet = build_magic_packet(mac_bytes)
                sock.sendto(packet, (broadcast, port))
                results[mac] = {"ok": True}
            except (ValueError, OSError) as e:
                results[mac] = {"ok": False, "error": str(e)}
    finally:
        sock.close()

    return results
