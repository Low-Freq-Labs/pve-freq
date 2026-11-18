"""Private supplied structure only. No provider, identity or public authority."""
from dataclasses import dataclass, field, fields
from hashlib import sha256
import json
import re
from .field_profile import PROFILE, FILTERS

RAW_CAP = 1048576
TOKEN_CAP = 32768
TOKEN_STRING_CAP = 49152
TEXT_CAP = 8192
MIN_INT, MAX_INT = -(1 << 63), (1 << 63) - 1


class NetworkListUnavailable(ValueError):
    def __init__(self):
        super().__init__('node_network_list_unavailable')


def need(value):
    if not value:
        raise NetworkListUnavailable()


@dataclass(frozen=True, slots=True)
class NodeScope:
    installation_ref: str
    estate_id: str
    fleet_generation: str
    host_ref: str
    host_incarnation: str
    node_name: str
    observation_ref: str
    profile_ref: str
    query_filter: str | None


@dataclass(frozen=True, slots=True)
class InterfaceRow:
    iface: str
    interface_type: str
    fields: tuple


@dataclass(frozen=True, slots=True)
class ListDocument:
    scope: NodeScope
    raw_sha256: str
    byte_count: int
    rows: tuple
    runtime_qualified: bool = field(default=False, init=False)
    source_qualified: bool = field(default=False, init=False)
    identity_qualified: bool = field(default=False, init=False)
    coverage_complete: bool = field(default=False, init=False)
    current_state_qualified: bool = field(default=False, init=False)
    staged_state_qualified: bool = field(default=False, init=False)
    execution_allowed: bool = field(default=False, init=False)
    persistence_authorized: bool = field(default=False, init=False)
    release_authorized: bool = field(default=False, init=False)


def _scope(scope):
    need(type(scope) is NodeScope)
    for f in fields(NodeScope):
        value = getattr(scope, f.name)
        if f.name == 'query_filter':
            need(value is None or type(value) is str and value in FILTERS)
        else:
            need(type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) is not None)
    need(scope.profile_ref == 'supplied-node-network-list-v1')


def _scan(raw):
    """Count opening containers and each string/primitive, including keys.

    Closing containers and punctuation cost no token. Escaped bytes stay inside
    their original string. This bound precedes the standard JSON grammar check.
    """
    need(type(raw) is bytes and 0 < len(raw) <= RAW_CAP)
    need(not raw.startswith(b'\xef\xbb\xbf'))
    depth = count = i = 0
    while i < len(raw):
        value = raw[i]
        if value in b' \t\r\n,:':
            i += 1
            continue
        if value in b'[{':
            count += 1
            depth += 1
            need(depth <= 4)
            i += 1
        elif value in b']}':
            depth -= 1
            need(depth >= 0)
            i += 1
        elif value == 34:
            count += 1
            i += 1
            start = i
            while i < len(raw) and raw[i] != 34:
                if raw[i] == 92:
                    i += 1
                i += 1
                need(i - start <= TOKEN_STRING_CAP)
            need(i < len(raw))
            i += 1
        else:
            count += 1
            start = i
            while i < len(raw) and raw[i] not in b' \t\r\n,:{}[]':
                i += 1
                need(i - start <= 20)
            token = raw[start:i]
            need(token in (b'true', b'false', b'null') or
                 re.fullmatch(rb'-?(0|[1-9][0-9]*)', token) is not None)
        need(count <= TOKEN_CAP)
    need(depth == 0)
    return count


def _pairs(items):
    result = {}
    for key, value in items:
        need(key not in result)
        result[key] = value
    return result


def _integer(text):
    need(len(text) <= 20)
    value = int(text)
    need(MIN_INT <= value <= MAX_INT)
    return value


def _forbidden(value):
    raise NetworkListUnavailable()


def _text(value):
    need(type(value) is str and len(value) <= TEXT_CAP)
    need(all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in value))
    need(len(value.encode('utf8', 'strict')) <= TEXT_CAP)
    return value


def _value(name, value):
    spec = PROFILE[name]
    kind = spec['type']
    if kind == 'boolean':
        need(type(value) is bool)
    elif kind == 'integer':
        need(type(value) is int and MIN_INT <= value <= MAX_INT)
        if 'minimum' in spec:
            need(value >= spec['minimum'])
        if 'maximum' in spec:
            need(value <= spec['maximum'])
    elif kind == 'string':
        _text(value)
        if 'minLength' in spec:
            need(len(value) >= spec['minLength'])
        if 'maxLength' in spec:
            need(len(value) <= spec['maxLength'])
        if 'enum' in spec:
            need(value in spec['enum'])
    else:
        need(kind == 'array' and type(value) is list)
        if name == 'families':
            need(len(value) <= 2)
            need(all(type(v) is str and v in ('inet', 'inet6') for v in value))
            need(len(set(value)) == len(value))
        else:
            need(name in ('options', 'options6') and len(value) <= 128)
            for item in value:
                _text(item)
        value = tuple(value)
    return value


def decode_list(scope, raw):
    try:
        _scope(scope)
        _scan(raw)
        value = json.loads(raw.decode('utf8', 'strict'), object_pairs_hook=_pairs,
                           parse_int=_integer, parse_float=_forbidden,
                           parse_constant=_forbidden)
        need(type(value) is list and len(value) <= 256)
        rows, seen = [], set()
        for obj in value:
            need(type(obj) is dict and len(obj) <= 64)
            need('iface' in obj and 'type' in obj)
            present = []
            for name, data in obj.items():
                need(type(name) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', name) is not None)
                need(name in PROFILE)
                if 'requires' in PROFILE[name]:
                    need(PROFILE[name]['requires'] in obj)
                present.append((name, _value(name, data)))
            name = obj['iface']
            need(name not in seen)
            seen.add(name)
            rows.append(InterfaceRow(name, obj['type'], tuple(sorted(present))))
        return ListDocument(scope, sha256(raw).hexdigest(), len(raw), tuple(rows))
    except Exception:
        raise NetworkListUnavailable() from None
