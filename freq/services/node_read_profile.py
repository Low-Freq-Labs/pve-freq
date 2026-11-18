"""Disabled node-read wire profile. No resolver, network or startup wiring.

Draft implementation of the reviewed R3 request boundary. A validated request
does not confer registration, credential, session or provider authority.
"""
from dataclasses import dataclass, field
import ipaddress
import re


REQUEST_LIMIT = 4096
RESPONSE_ALLOWANCE = 4194400
INVOCATION_ALLOWANCE = RESPONSE_ALLOWANCE + REQUEST_LIMIT


def _invalid():
    raise ValueError("node read profile unavailable")


def _ascii(value, minimum, maximum, pattern):
    if type(value) is not str or not minimum <= len(value) <= maximum:
        _invalid()
    if not value.isascii() or re.fullmatch(pattern, value, flags=re.ASCII) is None:
        _invalid()
    return value


def _endpoint(value):
    _ascii(value, 1, 45, r"[A-Fa-f0-9:.]+")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        _invalid()
    return address.compressed, address.version


def _tls_name(value):
    # Retain a valid literal IPv6 recipient for SSL's IP identity check.
    # No brackets, zone, URL or DNS resolution; ordinary DNS labels retain
    # the exact prior validation below. A name/value never proves authority.
    if type(value) is str and ':' in value:
        _endpoint(value)
        return value
    _ascii(value, 1, 253, r"[A-Za-z0-9.-]+")
    for label in value.split("."):
        _ascii(label, 1, 63, r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class WireTarget:
    """Copied transport scalars only; original registry owner lives elsewhere."""

    endpoint: str = field(repr=False)
    tls_name: str = field(repr=False)
    node: str = field(repr=False)
    address_version: int = field(init=False, repr=False)

    def __post_init__(self):
        endpoint, version = _endpoint(self.endpoint)
        _tls_name(self.tls_name)
        _ascii(self.node, 1, 128, r"[A-Za-z0-9_-]+")
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "address_version", version)


def serialize_request(target, credentials):
    """Build the sole admitted GET shape before any socket acquisition.

    Caller reserves INVOCATION_ALLOWANCE before resolving credentials. This
    function has no diagnostics or caching. Exceptions and caller-held values
    can retain credentials; no erasure or total-heap bound is claimed.
    """
    if type(target) is not WireTarget:
        _invalid()
    # Recheck every scalar: direct object construction is never authority.
    endpoint, version = _endpoint(target.endpoint)
    _tls_name(target.tls_name)
    node = _ascii(target.node, 1, 128, r"[A-Za-z0-9_-]+")
    if type(credentials) is not tuple or len(credentials) != 3:
        _invalid()
    user_realm, token_id, secret = credentials
    _ascii(user_realm, 3, 257, r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+")
    user, realm = user_realm.split("@")
    _ascii(user, 1, 128, r"[A-Za-z0-9_.-]+")
    _ascii(realm, 1, 128, r"[A-Za-z0-9_.-]+")
    _ascii(token_id, 1, 128, r"[A-Za-z0-9_.-]+")
    _ascii(secret, 1, 512, r"[A-Za-z0-9._~-]+")
    host = ("[" + endpoint + "]" if version == 6 else endpoint) + ":8006"
    request = (
        "GET /api2/json/nodes/" + node + "/network HTTP/1.1\r\n"
        "Host: " + host + "\r\n"
        "Authorization: PVEAPIToken=" + user_realm + "!" + token_id + "=" + secret + "\r\n"
        "Accept: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    if len(request) > REQUEST_LIMIT:
        _invalid()
    return request
