"""Bounded, API-only observations of configured Proxmox sources.

These observations confer no management authority or durable identity. More
than eight configured sources (or invalid configuration) returns unavailable
with no source attempts; an empty configuration returns unconfigured.
Socket operations respect the remaining deadline; synchronous OS DNS resolution
cannot be forcibly cancelled, and results arriving after the deadline are refused.
"""

import datetime
import http.client
import ipaddress
import json
import math
import re
import ssl
import time

from freq.services.pve_transport import _pve_api_credentials


MAX_SOURCES = 8
MAX_BODY = 2 * 1024 * 1024
MAX_ROWS = 4096
MAX_NUMBER = 2 ** 53 - 1
TOTAL_TIMEOUT = 15.0
SOURCE_TIMEOUT = 3.0
_PATH = "/api2/json/cluster/resources"
_NODE_FIELDS = ("node", "name", "status", "cpu", "mem", "maxmem", "disk", "maxdisk", "uptime")
_GUEST_FIELDS = ("type", "node", "vmid", "name", "status", "template",
                 "cpu", "mem", "maxmem", "maxcpu", "disk", "maxdisk", "uptime")
_STRINGS = frozenset(("type", "node", "name", "status"))


class _Unavailable(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _source_valid(source):
    if (type(source) is not str or not source or len(source) > 253
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", source)):
        return False
    try:
        ipaddress.ip_address(source)
        return True
    except ValueError:
        return bool(re.fullmatch(
            r"(?=.{1,253}\Z)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", source
        )) and all(0 < len(part) <= 63 and not part.startswith("-")
                   and not part.endswith("-") for part in source.split("."))


def _remaining(end, now):
    value = end - now()
    if value <= 0:
        raise _Unavailable("provider_unavailable")
    return min(SOURCE_TIMEOUT, value)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise _Unavailable("invalid_response")
        result[key] = value
    return result


def _fetch(cfg, source, timeout, *, deadline, now):
    end = min(deadline, now() + timeout)
    try:
        token_id, secret = _pve_api_credentials(cfg, source)
    except MemoryError:
        raise
    except Exception:
        raise _Unavailable("credentials_unavailable") from None
    if (type(token_id) is not str or type(secret) is not str
            or not token_id or not secret
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in token_id + secret)):
        raise _Unavailable("credentials_unavailable")
    try:
        context = ssl.create_default_context(
            cafile=getattr(cfg, "pve_api_ca_file", "") or None
        )
    except MemoryError:
        raise
    except Exception:
        raise _Unavailable("tls_unavailable") from None
    connection = http.client.HTTPSConnection(
        source, 8006, timeout=_remaining(end, now), context=context
    )
    try:
        connection.connect()
        transport = connection.sock
        transport.settimeout(_remaining(end, now))
        connection.request("GET", _PATH, headers={
            "Authorization": "PVEAPIToken=" + token_id + "=" + secret,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        transport.settimeout(_remaining(end, now))
        response = connection.getresponse()
        if response.status != 200:
            raise _Unavailable("provider_unavailable")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise _Unavailable("invalid_response")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isascii() or not length.isdecimal()
                                   or len(length) > 10 or int(length) > MAX_BODY):
            raise _Unavailable("invalid_response")
        body = bytearray()
        while True:
            transport.settimeout(_remaining(end, now))
            chunk = response.read1(min(65536, MAX_BODY + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise _Unavailable("invalid_response")
            if response.isclosed():
                break
        _remaining(end, now)
        if length is not None and len(body) != int(length):
            raise _Unavailable("invalid_response")
        try:
            document = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs)
        except (ValueError, UnicodeError, RecursionError):
            raise _Unavailable("invalid_response") from None
        if type(document) is not dict or "data" not in document:
            raise _Unavailable("invalid_response")
        return document["data"]
    except MemoryError:
        raise
    except http.client.IncompleteRead:
        raise _Unavailable("invalid_response") from None
    except ssl.SSLError:
        raise _Unavailable("tls_unavailable") from None
    except (OSError, http.client.HTTPException):
        raise _Unavailable("provider_unavailable") from None
    finally:
        connection.close()


def _scalar(field, value):
    if value is None:
        return None
    if field in _STRINGS:
        if (type(value) is not str or len(value) > 256
                or any(ord(char) < 32 or 127 <= ord(char) <= 159
                       or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
            raise _Unavailable("invalid_response")
        return value
    if field == "template":
        if type(value) is bool:
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise _Unavailable("invalid_response")
    if (type(value) not in (int, float) or value < 0 or value > MAX_NUMBER
            or (type(value) is float and not math.isfinite(value))
            or (field == "vmid" and (type(value) is not int or value == 0))):
        raise _Unavailable("invalid_response")
    return value


def _project(rows):
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise _Unavailable("invalid_response")
    nodes, guests, identities = [], [], set()
    for row in rows:
        if type(row) is not dict:
            raise _Unavailable("invalid_response")
        kind = row.get("type")
        if kind in ("node", "qemu", "lxc"):
            fields = _NODE_FIELDS if kind == "node" else _GUEST_FIELDS
            projected = {key: _scalar(key, row.get(key)) for key in fields}
            if not projected["node"] or not projected["node"].strip():
                raise _Unavailable("invalid_response")
            if kind != "node" and projected["vmid"] is None:
                raise _Unavailable("invalid_response")
            identity = (kind, projected["node"], projected.get("vmid"))
            if identity in identities:
                raise _Unavailable("invalid_response")
            identities.add(identity)
            (nodes if kind == "node" else guests).append(projected)
        # Other Proxmox resource families are outside this observation.
    return nodes, guests


def resolve_inventory(cfg, *, fetch=None, now=None):
    """Return safe observations; injected fetch(cfg, source, timeout) returns rows.

    Every configured source is reported separately, without cluster deduplication.
    Missing fields remain null. Failure never publishes a partial source payload.
    """
    clock = time.monotonic if now is None else now
    deadline = clock() + TOTAL_TIMEOUT
    result = {
        "schema": 1, "read_only": True,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "state": "unavailable", "sources": [],
    }
    configured = getattr(cfg, "pve_nodes", [])
    if (type(configured) not in (list, tuple) or len(configured) > MAX_SOURCES
            or any(not _source_valid(source) for source in configured)
            or len(set(configured)) != len(configured)):
        return result
    if not configured:
        result["state"] = "unconfigured"
        return result
    # Snapshot validated targets before any injected or provider operation.
    configured = tuple(configured)
    for source in configured:
        observation = {"source": source, "state": "unavailable",
                       "error": "provider_unavailable", "nodes": [], "guests": []}
        result["sources"].append(observation)
        try:
            timeout = _remaining(deadline, clock)
            if fetch is None:
                rows = _fetch(cfg, source, timeout, deadline=deadline, now=clock)
            else:
                rows = fetch(cfg, source, timeout)
            _remaining(deadline, clock)
            nodes, guests = _project(rows)
            _remaining(deadline, clock)
        except MemoryError:
            raise
        except _Unavailable as failure:
            observation["error"] = failure.code
        except Exception:
            # Neither provider errors nor injected errors are public payloads.
            observation["error"] = "provider_unavailable"
        else:
            observation.update(state="ok", error=None, nodes=nodes, guests=guests)
    successful = sum(item["state"] == "ok" for item in result["sources"])
    result["state"] = ("ok" if successful == len(configured) else
                       "partial" if successful else "unavailable")
    return result
