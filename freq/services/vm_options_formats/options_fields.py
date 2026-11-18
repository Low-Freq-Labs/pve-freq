"""Supplied field codec draft. No acquisition, configuration reads or routes.

Returned trees are caller-owned ordinary values, not authority/custody objects.
Original source cumulative accounting belongs to the eventual acquisition owner.
"""
import hashlib
import json
import re
from .bounded_json import parse, Refused, CapacityExceeded
from .wire_schema import SCHEMA

CONFIG_KEYS = ('nodes', 'storage', 'distros', 'vlans', 'network_profiles',
               'network_policy', 'cpu', 'memory', 'lifecycle', 'disk', 'bootstrap')
_TOKEN = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
_CONTENT = re.compile(r'[A-Za-z0-9_-]{1,32}')


def need(condition):
    if not condition:
        raise Refused('VM options unavailable')


def exact_equal(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is list:
        return len(a) == len(b) and all(exact_equal(x, y) for x, y in zip(a, b))
    if type(a) is dict:
        return a.keys() == b.keys() and all(exact_equal(a[k], b[k]) for k in a)
    return a == b


def grammar(value, schema):
    """Only trusted embedded schema supported; input is freshly parsed JSON."""
    if '$ref' in schema:
        name = schema['$ref'].removeprefix('#/$defs/')
        return grammar(value, SCHEMA['$defs'][name])
    if 'anyOf' in schema:
        for alternative in schema['anyOf']:
            try:
                grammar(value, alternative)
                return
            except Refused:
                pass
        need(False)
    if 'const' in schema:
        need(exact_equal(value, schema['const']))
    if 'enum' in schema:
        need(any(exact_equal(value, option) for option in schema['enum']))
    kind = schema.get('type')
    if kind == 'object':
        need(type(value) is dict)
        need(len(value) <= schema.get('maxProperties', 8192))
        need(all(k in value for k in schema.get('required', ())))
        for key, item in value.items():
            if 'propertyNames' in schema:
                grammar(key, schema['propertyNames'])
            if key in schema.get('properties', {}):
                grammar(item, schema['properties'][key])
            else:
                additional = schema.get('additionalProperties', True)
                need(additional is not False)
                if type(additional) is dict:
                    grammar(item, additional)
    elif kind == 'array':
        need(type(value) is list)
        need(len(value) <= schema.get('maxItems', 8192))
        if 'items' in schema:
            for item in value:
                grammar(item, schema['items'])
    elif kind == 'string':
        need(type(value) is str)
        need(schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 4096))
        need(not any(0xD800 <= ord(c) <= 0xDFFF for c in value))
        if 'pattern' in schema:
            need(re.fullmatch(schema['pattern'], value) is not None)
    elif kind == 'integer':
        # bool and JSONDecimal are explicitly excluded; never coerce.
        need(type(value) is int)
        need(schema.get('minimum', -9007199254740991) <= value <= schema.get('maximum', 9007199254740991))
    elif kind == 'boolean':
        need(type(value) is bool)
    elif kind == 'null':
        need(value is None)


def unique(rows, key):
    seen = set()
    for row in rows:
        identity = key(row)
        need(identity not in seen)
        seen.add(identity)
    return seen


def decode_configuration(raw):
    config = parse(raw, byte_limit=1048576)
    need(type(config) is dict and set(config) == set(CONFIG_KEYS))
    for key in CONFIG_KEYS:
        grammar(config[key], SCHEMA['properties'][key])
    names = unique(config['nodes'], lambda n: n['name'])
    unique(config['nodes'], lambda n: n['ip'])
    unique(config['storage'], lambda s: (s['node'], s['id']))
    unique(config['distros'], lambda d: d['key'])
    vlans = unique(config['vlans'], lambda v: v['id'])
    unique(config['network_profiles'], lambda p: p['id'])
    need(all(n['default'] is (i == 0) for i, n in enumerate(config['nodes'])))
    need(all(s['node'] in names and s['source'] == 'configured' and
             s['availability'] == 'unknown' for s in config['storage']))
    defaults = config['disk']['default_by_node']
    need(set(defaults) == names)
    for node in config['nodes']:
        pools = [s['id'] for s in config['storage'] if s['node'] == node['name']]
        need(node['storage'] in pools if pools else node['storage'] == '')
        need(defaults[node['name']] == node['storage'])
    need(config['disk']['default_storage'] == (config['storage'][0]['id'] if config['storage'] else None))
    need(all(p['vlan_id'] in vlans and p['tag'] == str(p['vlan_id']) for p in config['network_profiles']))
    need(config['network_policy']['network_setup_required'] is (not config['network_profiles']))
    return config


def configuration_digest(config):
    """Only call with freshly validated config, before any caller mutation.

    Hash is public projection metadata, never generation or admission authority.
    """
    raw = json.dumps(config, sort_keys=True, ensure_ascii=True,
                     allow_nan=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def scalar(value, maximum, minimum=0):
    need(type(value) is str and minimum <= len(value) <= maximum)
    need(not any(0xD800 <= ord(c) <= 0xDFFF for c in value))
    return value


def token(value):
    need(type(value) is str and _TOKEN.fullmatch(value) is not None)
    return value


def flag(value):
    need(type(value) is bool or (type(value) is int and value in (0, 1)))
    return value is True or (type(value) is int and value == 1)


def raw_rows(raw):
    rows = parse(raw, byte_limit=262144)
    need(type(rows) is list)
    if len(rows) > 1024:
        raise CapacityExceeded('VM options unavailable')
    need(all(type(row) is dict for row in rows))
    return rows


def decode_storage(raw, node):
    """Node must originate from validated configuration, never provider labels."""
    token(node)
    rows = raw_rows(raw)
    output, identities = [], set()
    required = {'storage', 'type', 'active', 'enabled', 'content'}
    for row in rows:
        need(required <= row.keys())
        identity = token(row['storage'])
        need(identity not in identities)
        identities.add(identity)
        kind = scalar(row['type'], 64)
        active, enabled = flag(row['active']), flag(row['enabled'])
        content = scalar(row['content'], 256)
        parts = [] if content == '' else [p.strip(' ') for p in content.split(',')]
        need(len(parts) <= 16 and len(set(parts)) == len(parts))
        need(all(_CONTENT.fullmatch(p) is not None for p in parts))
        if active and enabled and 'images' in parts:
            if len(output) >= 256:
                raise CapacityExceeded('VM options unavailable')
            output.append({'id': identity, 'label': identity, 'node': node, 'type': kind,
                           'source': 'observed', 'availability': 'observed_available'})
    # Count every raw row, including excluded inactive/non-images records.
    return output, len(rows)


def decode_templates(raw, configured_names):
    need(type(configured_names) is tuple and len(configured_names) <= 32)
    need(all(type(n) is str and _TOKEN.fullmatch(n) is not None for n in configured_names))
    need(len(set(configured_names)) == len(configured_names))
    rows = raw_rows(raw)
    output, identities = [], set()
    required = {'vmid', 'node', 'type', 'template', 'name', 'status'}
    for row in rows:
        need(required <= row.keys())
        vmid = row['vmid']
        need(type(vmid) is int and 1 <= vmid <= 999999999)
        need(vmid not in identities)
        identities.add(vmid)
        node = token(row['node'])
        need(node in configured_names)
        need(type(row['type']) is str and row['type'] in ('qemu', 'lxc'))
        template = flag(row['template'])
        name, status = scalar(row['name'], 256, 1), scalar(row['status'], 64)
        if template:
            if len(output) >= 256:
                raise CapacityExceeded('VM options unavailable')
            output.append({'vmid': vmid, 'name': name, 'node': node,
                           'status': status, 'source': 'observed'})
    return output, len(rows)
