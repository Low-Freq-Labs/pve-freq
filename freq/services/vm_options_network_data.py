"""Private network pieces from three retained PRESENT byte inputs, DATA only.

No acquisition, native absence/inline-source selection, path, provider, key,
route or issuer. Original owner still owes same retained freq source for all
pieces, code/principal/writer/purpose/generation/end/native physical custody.
This narrow profile intentionally refuses nonempty inline configuration.
"""
from dataclasses import dataclass
import ipaddress
import json
import tomllib

from freq.services.node_read_profile import _endpoint
from freq.services.vm_options_formats.bounded_json import CapacityExceeded, Refused
from freq.services.vm_options_formats.options_fields import grammar, token
from freq.services.vm_options_formats.wire_schema import SCHEMA


class OptionsNetworkUnavailable(ValueError):
    def __init__(self):
        super().__init__('VM options network unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class OptionsNetworkData:
    """Copied scalar tuples/three canonical pieces, never complete options."""
    vlans: tuple
    profiles: tuple
    field_bytes: tuple


def _need(condition):
    if not condition:
        raise OptionsNetworkUnavailable()


def _table(parent, key):
    value = parent[key]
    _need(type(value) is dict)
    return value


def _literal_gateway(value):
    _need(type(value) is str)
    if value:
        _endpoint(value)
        return ipaddress.ip_address(value)
    return None


def _policy_ids(values, ids):
    _need(type(values) is list)
    if len(values) > 128:
        raise CapacityExceeded('VM options unavailable')
    seen = set()
    for value in values:
        _need(type(value) is str and 1 <= len(value) <= 4 and value.isascii() and value.isdecimal())
        identity = int(value)
        _need(1 <= identity <= 4094 and str(identity) == value and identity in ids and value not in seen)
        seen.add(value)
    return sorted(seen)


def _project_network_values(f, v, profiles):
    """Internal parsed/selected DATA only; canonical validation, no issuer."""
    vm, nic = _table(f, 'vm'), _table(f, 'nic')
    defaults, rules = _table(vm, 'defaults'), _table(vm, 'gateway_rules')
    global_gateway = defaults['gateway']
    _literal_gateway(global_gateway)
    global_bridge = token(nic['bridge'])
    _need(not any(alias in rules for alias in ('egress_vlans', 'no_gateway_vlans', 'default_gateway_mode')))
    mode = rules['mode']
    _need(type(mode) is str and mode in ('single_egress', 'vlan_then_global'))
    declarations = v.get('vlan', {})
    _need(type(declarations) is dict and type(profiles) is list)
    if len(declarations) > 128 or len(profiles) > 128:
        raise CapacityExceeded('VM options unavailable')
    vlans, by_id = [], {}
    vlan_schema = SCHEMA['$defs']['vlan']['properties']
    for info in declarations.values():
        _need(type(info) is dict)
        identity = info['id']
        grammar(identity, vlan_schema['id'])
        _need(identity not in by_id)
        for field in ('name', 'subnet', 'prefix', 'gateway'):
            grammar(info[field], vlan_schema[field])
        explicit_gateway = info['gateway']
        _literal_gateway(explicit_gateway)
        selected = explicit_gateway or global_gateway
        address = _literal_gateway(selected)
        subnet = info['subnet']
        _need('%' not in subnet)
        net = ipaddress.ip_network(subnet, strict=True) if subnet else None
        _need(address is None or net is not None)
        member = address is None or address in net
        row = dict(id=identity, name=info['name'], subnet=subnet, prefix=info['prefix'],
                   gateway=selected, gateway_source='vlan' if explicit_gateway else 'global' if global_gateway else '',
                   gateway_in_subnet=member,
                   gateway_warning='' if member else 'Configured gateway is outside advertised subnet.',
                   bridge=global_bridge, network_profile='')
        vlans.append(row)
        by_id[identity] = row
    internet = _policy_ids(rules['internet_vlans'], by_id)
    no_default = _policy_ids(rules['no_default_gateway_vlans'], by_id)
    _need(not (set(internet) & set(no_default)))
    output_profiles, seen, associated = [], set(), set()
    for info in profiles:
        _need(type(info) is dict)
        identity = token(info['id'])
        vlan_id = info['vlan']
        _need(type(vlan_id) is int and vlan_id in by_id)
        _need(identity not in seen and vlan_id not in associated)
        if 'key' in info:
            _need(type(info['key']) is str and info['key'] == identity)
        if 'vlan_id' in info:
            _need(type(info['vlan_id']) is int and info['vlan_id'] == vlan_id)
        bridge = token(info['bridge'])
        row = by_id[vlan_id]
        public = dict(id=identity, name=info['name'], purpose=info['purpose'],
                      description=info['description'], vlan_id=vlan_id, vlan_name=row['name'],
                      subnet=row['subnet'], prefix=row['prefix'], gateway=row['gateway'],
                      gateway_role=info['gateway_role'], bridge=bridge, tag=str(vlan_id),
                      advanced_label=bridge + ' tag ' + str(vlan_id))
        grammar(public, SCHEMA['$defs']['profile'])
        seen.add(identity)
        associated.add(vlan_id)
        row['bridge'], row['network_profile'] = bridge, identity
        output_profiles.append(public)
    required = not output_profiles
    policy = dict(default_ip_mode='static', gateway_source=mode,
                  internet_vlans=internet, no_default_gateway_vlans=no_default,
                  host_octet_reservation='global', manual_gateway_default=False, multi_nic=True,
                  primary_input='network_profile', bridge_input='advanced',
                  network_setup_required=required,
                  network_setup_hint='Configure VM Network Profiles before creating static-IP VMs.' if required else '',
                  site_inference=False)
    encoded, total = [], 0
    for field, value in (('vlans', vlans), ('network_profiles', output_profiles), ('network_policy', policy)):
        grammar(value, SCHEMA['properties'][field])
        raw = json.dumps(value, sort_keys=True, ensure_ascii=True,
                         allow_nan=False, separators=(',', ':')).encode('utf-8')
        total += len(raw)
        if total > 1048576:
            raise CapacityExceeded('VM options unavailable')
        encoded.append((field, raw))
    immutable_vlans = tuple(tuple(row[key] for key in SCHEMA['$defs']['vlan']['required']) for row in vlans)
    immutable_profiles = tuple(tuple(row[key] for key in SCHEMA['$defs']['profile']['required']) for row in output_profiles)
    return OptionsNetworkData(immutable_vlans, immutable_profiles, tuple(encoded))


def project_options_network_data(retained_freq_bytes, retained_vlan_bytes, retained_profile_bytes):
    """Validate complete configured network pieces with no partial success.

Present empty profile bytes stay configured empty. None is unavailable, not an
absence certificate. Pure membership of an explicit IP in an explicit subnet
never proves reachability or applied network state. Empty selected gateway's
true membership flag means only no configured membership complaint.

Logical input/row/output caps do not bound TOML parser/runtime/heap or traceback
retention. Original supervised worker/end/resources remain required. Ordinary
diagnostics are fixed outside the handler; memory/control/capacity retain their
whole-response identity/priority. No complete configuration/bootstrap/hash,
wire envelope, currentness, source attachment or native authority is created.
"""
    raws = (retained_freq_bytes, retained_vlan_bytes, retained_profile_bytes)
    if any(type(raw) is not bytes for raw in raws):
        raise OptionsNetworkUnavailable()
    if any(len(raw) > 1048576 for raw in raws) or sum(map(len, raws)) > 3145728:
        raise CapacityExceeded('VM options unavailable')
    failed = False
    try:
        f, v, p = (tomllib.loads(raw.decode('utf-8', 'strict')) for raw in raws)
        inline = _table(f, 'nic').get('profiles', {})
        _need(type(inline) is dict and not inline)
        data = _project_network_values(f, v, p.get('profile', []))
    except CapacityExceeded:
        raise
    except (Refused, ValueError, KeyError, RecursionError):
        failed = True
    if failed:
        raise OptionsNetworkUnavailable()
    return data


# No None-to-absence conversion, inline source fallback, full projection, file
# reader extension, public recipient, request admission, issuer or effect.
