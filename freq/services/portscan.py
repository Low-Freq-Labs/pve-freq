"""Bounded TCP port probing below dashboard HTTP transport."""

import re
import socket


def scan_ports(host, ports_str):
    """Validate one host/port list and return its ordered probe results."""
    if not host or not ports_str:
        return {"error": "host and ports required"}, 400
    if not re.match(r"^[a-zA-Z0-9._-]+$", host):
        return {"error": "Invalid hostname"}, 400

    results = []
    for raw_port in ports_str.split(","):
        try:
            port = int(raw_port.strip())
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(2)
            is_open = probe.connect_ex((host, port)) == 0
            probe.close()
            results.append({"port": port, "open": is_open})
        except (ValueError, OSError):
            results.append(
                {"port": raw_port.strip(), "open": False, "error": "invalid"}
            )
    return {"host": host, "results": results}, None
