"""Pure supplied cluster representation. No acquisition or disclosure authority."""
from dataclasses import dataclass, field
import json
import re
import ipaddress
import unicodedata
from .cluster_status import ClusterStatusAssessment

LIMIT = 2097152
TOKENS = 262144
FLAGS = ('authenticated', 'authoritative', 'fresh', 'visibility_complete',
         'cluster_identity_verified', 'node_identity_verified', 'quorum_verified',
         'action_ready', 'live_effect')


@dataclass(frozen=True)
class ClusterBrowserAssessment:
    body: bytes
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
class ClusterBrowserFailure:
    state: str = field(default='unavailable', init=False)
    reason: str = field(default='cluster_browser_unavailable', init=False)


def _need(ok):
    if not ok:
        raise ValueError('unsupported supplied structure')


def _pairs(items):
    result = {}
    for k, v in items:
        _need(k not in result)
        result[k] = v
    return result


def _lex(text):
    """Bound full construction; the JSON parser still checks grammar."""
    at = tokens = depth = 0
    while at < len(text):
        c = text[at]
        if c in ' \r\n\t':
            at += 1
            continue
        tokens += 1
        _need(tokens <= TOKENS)
        if c in '[{':
            depth += 1
            _need(depth <= 4)
            at += 1
        elif c in ']}':
            depth -= 1
            _need(depth >= 0)
            at += 1
        elif c in ',:':
            at += 1
        elif c == '"':
            start = at
            at += 1
            escaped = False
            width = 1
            while at < len(text):
                c = text[at]
                at += 1
                width += len(c.encode('utf-8'))
                _need(width <= 4096)
                if not escaped and c == '"':
                    break
                if not escaped and c == '\\':
                    escaped = True
                else:
                    escaped = False
            else:
                raise ValueError('unterminated string')
            s = json.loads(text[start:at])
            _need(type(s) is str and len(s) <= 512 and len(s.encode('utf-8')) <= 512)
        elif '0' <= c <= '9':
            start = at
            while at < len(text) and '0' <= text[at] <= '9':
                at += 1
                _need(at - start <= 20)
            _need(at - start == 1 or text[start] != '0')
        else:
            for literal in ('true', 'false', 'null'):
                if text.startswith(literal, at):
                    at += len(literal)
                    break
            else:
                raise ValueError('unsupported token')
    _need(depth == 0)
    return tokens


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _emit(value):
    return _canonical(value)


def _keys(value, names):
    _need(type(value) is dict and set(value) == set(names))


def _text(value, limit, empty=False, strip=False):
    _need(type(value) is str)
    _need((empty or bool(value)) and len(value) <= limit and len(value.encode('utf-8')) <= limit)
    _need(not any(unicodedata.category(c) in ('Cc', 'Cs') for c in value))
    _need(not strip or value.strip() == value)


def _bool(value):
    _need(type(value) is bool)


def _int(value, low, high):
    _need(type(value) is int and low <= value <= high)


def _ip(value):
    _need(type(value) is str and 0 < len(value) <= 64 and value.isascii())
    _need(value.strip() == value and '%' not in value)
    ipaddress.ip_address(value)


def _option(value, validator):
    _keys(value, ('present', 'value'))
    _need(type(value['present']) is bool)
    if value['present']:
        validator(value['value'])
    else:
        _need(value['value'] is None)


def _validate(root, raw_hash):
    _keys(root, ('schema', 'profile', 'capture_ref', 'raw_sha256', 'evidence',
                 'state', 'cluster', 'nodes', 'reported_count_relation', 'authority'))
    for key, expected in (('schema', 'cluster-status-structural-v1'),
                          ('profile', 'pve-cluster-status-supplied-v1'),
                          ('evidence', 'supplied_only'), ('authority', 'none')):
        _need(root[key] == expected)
    _need(type(root['capture_ref']) is str and re.fullmatch('[0-9a-f]{32}', root['capture_ref']))
    _need(type(root['raw_sha256']) is str and root['raw_sha256'] == raw_hash)
    nodes, cluster = root['nodes'], root['cluster']
    _need(type(nodes) is list and len(nodes) <= 1024)
    ids, names, local = set(), set(), 0
    for node in nodes:
        _keys(node, ('id', 'name', 'type', 'ip', 'level', 'local', 'online', 'nodeid'))
        _need(node['type'] == 'node')
        _text(node['id'], 256, strip=True)
        _text(node['name'], 256, strip=True)
        _need(node['id'] not in ids and node['name'] not in names)
        ids.add(node['id']); names.add(node['name'])
        _option(node['ip'], _ip)
        _option(node['level'], lambda v: _text(v, 64, empty=True))
        _option(node['local'], _bool)
        _option(node['online'], _bool)
        _option(node['nodeid'], lambda v: _int(v, 1, 4294967295))
        local += node['local']['value'] is True
        _need(local <= 1)
    relation = 'unknown'
    if cluster is not None:
        _keys(cluster, ('id', 'name', 'type', 'nodes', 'quorate', 'version'))
        _need(cluster['type'] == 'cluster')
        _text(cluster['id'], 256, strip=True)
        _text(cluster['name'], 256, strip=True)
        _need(cluster['id'] not in ids)
        _option(cluster['nodes'], lambda v: _int(v, 0, 1024))
        _option(cluster['quorate'], _bool)
        _option(cluster['version'], lambda v: _int(v, 0, 9223372036854775807))
        if cluster['nodes']['present']:
            relation = 'equal' if cluster['nodes']['value'] == len(nodes) else 'different'
    _need(root['reported_count_relation'] == relation)
    _need(root['state'] == ('supplied_empty' if cluster is None and not nodes else 'supplied_rows'))


def project(assessment):
    try:
        _need(type(assessment) is ClusterStatusAssessment)
        _need(type(assessment.body) is bytes and 0 < len(assessment.body) <= LIMIT)
        _need(type(assessment.raw_sha256) is str and re.fullmatch('[0-9a-f]{64}', assessment.raw_sha256))
        _need(all(getattr(assessment, name) is False for name in FLAGS))
        raw = assessment.body
        _need(not raw.startswith(b'\xef\xbb\xbf'))
        text = raw.decode('utf-8', 'strict')
        _lex(text)
        root = json.loads(text, object_pairs_hook=_pairs)
        _need(_canonical(root) == raw)
        _validate(root, assessment.raw_sha256)
        for node in root['nodes']:
            if node['nodeid']['present']:
                node['nodeid']['value'] = str(node['nodeid']['value'])
        if root['cluster'] is not None:
            for name in ('nodes', 'version'):
                option = root['cluster'][name]
                if option['present']:
                    option['value'] = str(option['value'])
        root['schema'] = 'cluster-status-browser-v1'
        root['capabilities'] = {name: False for name in FLAGS}
        body = _emit(root)
        _need(type(body) is bytes and 0 < len(body) <= LIMIT)
        return ClusterBrowserAssessment(body)
    except Exception:
        return ClusterBrowserFailure()
