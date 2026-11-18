"""Bounded parsing of a native Cluster Status JSON response; DATA ONLY.

Accepts the full fixed /api2/json/cluster/status JSON body with exact data envelope.
Returns internal parsed rows, never the observed browser schema/provenance.
A result is constructible data: it proves no acquisition, TLS, session, source,
identity, permission, cleanup, deadline, admission or authority. Only the future
original installed service may join its actual trusted acquisition to publication.
Supplied-only source and domain remain byte preserved in their own module.
"""
from dataclasses import dataclass, field
import ipaddress
import json
import unicodedata

INGRESS = 1048576
OUTPUT = 2097152
TOKENS = 65536
STRING_TOKEN = 4096
STRING_WIDTH = 512


@dataclass(frozen=True)
class ParsedClusterRows:
    body: bytes


@dataclass(frozen=True)
class ClusterStructureFailure:
    state: str = field(default="unavailable", init=False)
    reason: str = field(default="cluster_structure_unavailable", init=False)


def _need(ok):
    if not ok:
        raise ValueError("unsupported observed structure")


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result)
        result[key] = value
    return result


def _lex(text):
    """Bound construction before the full JSON decoder; JSON checks grammar."""
    at = tokens = depth = 0
    while at < len(text):
        char = text[at]
        if char in " \t\r\n":
            at += 1
            continue
        tokens += 1
        _need(tokens <= TOKENS)
        if char in "[{":
            depth += 1
            _need(depth <= 3)
            at += 1
        elif char in "]}":
            depth -= 1
            _need(depth >= 0)
            at += 1
        elif char in ",:":
            at += 1
        elif char == '"':
            start = at
            at += 1
            escaped = False
            width = 1
            while at < len(text):
                char = text[at]
                at += 1
                width += len(char.encode("utf-8"))
                _need(width <= STRING_TOKEN)
                if not escaped and char == '"':
                    break
                if not escaped and char == "\\":
                    escaped = True
                else:
                    escaped = False
            else:
                raise ValueError("unterminated string")
            value = json.loads(text[start:at])
            _need(type(value) is str and len(value) <= STRING_WIDTH)
            _need(len(value.encode("utf-8")) <= STRING_WIDTH)
        elif "0" <= char <= "9":
            start = at
            while at < len(text) and "0" <= text[at] <= "9":
                at += 1
                _need(at - start <= 20)
            token = text[start:at]
            _need(token == "0" or token[0] != "0")
        else:
            for token in ("true", "false", "null"):
                if text.startswith(token, at):
                    at += len(token)
                    break
            else:
                raise ValueError("unsupported token")
    _need(depth == 0)
    return tokens


def _text(value, limit, empty=False, strip=False):
    _need(type(value) is str)
    _need((empty or bool(value)) and len(value) <= limit)
    _need(len(value.encode("utf-8")) <= limit)
    _need(not any(unicodedata.category(c) in ("Cc", "Cs") for c in value))
    if strip:
        _need(value.strip() == value)
    return value


def _integer(value, low, high):
    _need(type(value) is int and low <= value <= high)
    return value


def _flag(value):
    _need(type(value) is bool or type(value) is int and value in (0, 1))
    return bool(value)


def _ip(value):
    _need(type(value) is str and 0 < len(value) <= 64 and value.isascii())
    _need(value.strip() == value and "%" not in value)
    ipaddress.ip_address(value)
    return value


def _optional(row, key, check):
    return {"present": key in row, "value": check(row[key]) if key in row else None}


def _encode(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(raw) <= OUTPUT)
    return raw


def decode_native_response(raw):
    """Parse exact native envelope and report literal values; no public success."""
    try:
        _need(type(raw) is bytes and 0 < len(raw) <= INGRESS)
        _need(not raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8", "strict")
        _lex(text)
        envelope = json.loads(text, object_pairs_hook=_pairs)
        _need(type(envelope) is dict and set(envelope) == {"data"})
        rows = envelope["data"]
        _need(type(rows) is list and len(rows) <= 1025)
        nodes, cluster, ids, names, local_count = [], None, set(), set(), 0
        for row in rows:
            _need(type(row) is dict)
            _need({"id", "name", "type"} <= row.keys())
            kind = row["type"]
            _need(type(kind) is str and kind in ("node", "cluster"))
            name = _text(row["name"], 256, strip=True)
            ident = _text(row["id"], 256, strip=True)
            _need(ident not in ids)
            ids.add(ident)
            out = {"id": ident, "name": name, "type": kind}
            if kind == "node":
                _need(set(row) <= {"id", "name", "type", "ip", "level", "local", "nodeid", "online"})
                _need(len(nodes) < 1024 and name not in names)
                names.add(name)
                out["ip"] = _optional(row, "ip", _ip)
                out["level"] = _optional(row, "level", lambda v: _text(v, 64, empty=True))
                out["local"] = _optional(row, "local", _flag)
                out["online"] = _optional(row, "online", _flag)
                out["nodeid"] = _optional(row, "nodeid", lambda v: str(_integer(v, 0, 4294967295)))
                local_count += out["local"]["value"] is True
                _need(local_count <= 1)
                nodes.append(out)
            else:
                _need(set(row) <= {"id", "name", "type", "nodes", "quorate", "version"})
                _need(cluster is None)
                out["nodes"] = _optional(row, "nodes", lambda v: str(_integer(v, 0, 1024)))
                out["quorate"] = _optional(row, "quorate", _flag)
                out["version"] = _optional(row, "version", lambda v: str(_integer(v, 0, 9223372036854775807)))
                cluster = out
        relation = "unknown"
        if cluster is not None and cluster["nodes"]["present"]:
            relation = "equal" if int(cluster["nodes"]["value"]) == len(nodes) else "different"
        body = _encode({"schema": "cluster-observation-parsed-v1",
                        "state": "parsed_rows" if rows else "parsed_empty",
                        "cluster": cluster, "nodes": nodes,
                        "reported_count_relation": relation})
        return ParsedClusterRows(body)
    except Exception:
        return ClusterStructureFailure()
