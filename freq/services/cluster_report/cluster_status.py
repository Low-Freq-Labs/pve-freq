"""Strict supplied structural observations; no provider or identity authority."""
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import re
import unicodedata

INGRESS = 1048576
OUTPUT = 2097152
TOKENS = 65536
STRING_TOKEN = 4096
STRING_WIDTH = 512
PROFILE = "pve-cluster-status-supplied-v1"
FLAGS = ("authenticated", "authoritative", "fresh", "visibility_complete",
         "cluster_identity_verified", "node_identity_verified", "quorum_verified",
         "action_ready", "live_effect")


@dataclass(frozen=True)
class ClusterStatusAssessment:
    body: bytes
    raw_sha256: str
    authenticated: bool = field(default=False, init=False)
    authoritative: bool = field(default=False, init=False)
    fresh: bool = field(default=False, init=False)
    visibility_complete: bool = field(default=False, init=False)
    cluster_identity_verified: bool = field(default=False, init=False)
    node_identity_verified: bool = field(default=False, init=False)
    quorum_verified: bool = field(default=False, init=False)
    action_ready: bool = field(default=False, init=False)
    live_effect: bool = field(default=False, init=False)


@dataclass(frozen=True)
class ClusterStatusFailure:
    state: str = field(default="unavailable", init=False)
    reason: str = field(default="cluster_status_unavailable", init=False)


def _need(ok):
    if not ok:
        raise ValueError("unsupported supplied structure")


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
            _need(depth <= 2)
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


def decode(raw, capture_ref, profile):
    try:
        _need(type(raw) is bytes and 0 < len(raw) <= INGRESS)
        _need(type(capture_ref) is str and re.fullmatch(r"[0-9a-f]{32}", capture_ref))
        _need(type(profile) is str and profile == PROFILE)
        _need(not raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8", "strict")
        _lex(text)
        rows = json.loads(text, object_pairs_hook=_pairs)
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
                out["nodeid"] = _optional(row, "nodeid", lambda v: _integer(v, 1, 4294967295))
                local_count += out["local"]["value"] is True
                _need(local_count <= 1)
                nodes.append(out)
            else:
                _need(set(row) <= {"id", "name", "type", "nodes", "quorate", "version"})
                _need(cluster is None)
                out["nodes"] = _optional(row, "nodes", lambda v: _integer(v, 0, 1024))
                out["quorate"] = _optional(row, "quorate", _flag)
                out["version"] = _optional(row, "version", lambda v: _integer(v, 0, 9223372036854775807))
                cluster = out
        relation = "unknown"
        if cluster is not None and cluster["nodes"]["present"]:
            relation = "equal" if cluster["nodes"]["value"] == len(nodes) else "different"
        digest = hashlib.sha256(raw).hexdigest()
        body = _encode({"schema": "cluster-status-structural-v1", "profile": profile,
                        "capture_ref": capture_ref, "raw_sha256": digest,
                        "evidence": "supplied_only", "state": "supplied_rows" if rows else "supplied_empty",
                        "cluster": cluster, "nodes": nodes,
                        "reported_count_relation": relation, "authority": "none"})
        return ClusterStatusAssessment(body, digest)
    except Exception:
        return ClusterStatusFailure()
