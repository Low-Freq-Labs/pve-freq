"""Rate-limited DNS lookup behavior below dashboard HTTP transport."""

from __future__ import annotations

import re
import socket
import threading
import time

_DNS_LOOKUP_LOG: dict[str, list[float]] = {}
_DNS_LOOKUP_LOCK = threading.Lock()
_DNS_LOOKUP_WINDOW = 300
_DNS_LOOKUP_MAX = 30
_HOSTNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


def allow_lookup(client_ip: str) -> bool:
    """Return whether one source IP may perform another DNS lookup."""
    now = time.time()
    with _DNS_LOOKUP_LOCK:
        bucket = _DNS_LOOKUP_LOG.get(client_ip, [])
        bucket = [timestamp for timestamp in bucket if now - timestamp < _DNS_LOOKUP_WINDOW]
        if len(bucket) >= _DNS_LOOKUP_MAX:
            _DNS_LOOKUP_LOG[client_ip] = bucket
            return False
        bucket.append(now)
        _DNS_LOOKUP_LOG[client_ip] = bucket
        return True


def resolve_hostname(host: str) -> tuple[str, list[str]]:
    """Validate and resolve one hostname into a transport-neutral outcome."""
    if not host:
        return "host_required", []
    if len(host) > 253:
        return "hostname_too_long", []
    if not _HOSTNAME_PATTERN.match(host):
        return "invalid_hostname", []
    try:
        results = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "resolution_failed", []
    ips = sorted({result[4][0] for result in results})
    return "resolved", ips
