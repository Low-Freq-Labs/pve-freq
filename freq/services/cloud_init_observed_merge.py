"""Pure supplied observation merge, never original source or effect authority.

No host acquisition, command serialization, provider-support/completeness flag,
address allocation or caller admission. Results describe only listed inputs.
See CONTRACT-R1.md for deliberately unresolved provider and transition duties.
"""
import ipaddress
import re
from typing import NamedTuple

from .cloud_init_network_intent import (
    FieldPatch, FamilyPatch, NICPatch, NetworkPatch, normalize_network_patch,
)


class InvalidObservedNetwork(ValueError):
    pass


class Observed(NamedTuple):
    state: str
    value: object


class ObservedFamily(NamedTuple):
    mode: Observed
    address: Observed
    gateway: Observed


class ObservedNIC(NamedTuple):
    slot: int
    attachment_ref: str
    ipv4: ObservedFamily
    ipv6: ObservedFamily
    default_ipv4: ObservedFamily
    default_ipv6: ObservedFamily


class ObservedNetwork(NamedTuple):
    nics: tuple
    dns_servers: Observed
    search_domains: Observed
    default_dns_servers: Observed
    default_search_domains: Observed


class MergedField(NamedTuple):
    state: str
    value: object
    origin: str


class MergedFamily(NamedTuple):
    mode: MergedField
    address: MergedField
    gateway: MergedField


class MergedNIC(NamedTuple):
    slot: int
    attachment_ref: str
    ipv4: MergedFamily
    ipv6: MergedFamily


class MergeIssue(NamedTuple):
    field: str
    slot: object
    family: object
    code: str


class MergeAnalysis(NamedTuple):
    nics: tuple
    dns_servers: MergedField
    search_domains: MergedField
    conflicts: tuple
    uncertainties: tuple
    known_ipv4_gateways: int
    known_ipv6_gateways: int


_REFERENCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')


def _bad():
    raise InvalidObservedNetwork('Cloud-init observation merge unavailable') from None


def _field_patch(value):
    if (type(value) is not FieldPatch or type(value.action) is not str or
            value.action not in ('retain', 'set', 'clear', 'inherit') or
            value.action != 'set' and value.value is not None):
        _bad()
    return {'action': value.action, **({'value': value.value} if value.action == 'set' else {})}


def _family_patch(value):
    if (type(value) is not FamilyPatch or type(value.action) is not str or
            value.action not in ('retain', 'set', 'clear', 'inherit')):
        _bad()
    gateway = _field_patch(value.gateway)
    if value.action != 'set':
        if value.mode is not None or value.address is not None or gateway != {'action': 'retain'}:
            _bad()
        return {'action': value.action}
    if type(value.mode) is not str:
        _bad()
    body = {'mode': value.mode}
    if value.mode == 'static':
        if type(value.address) is not str:
            _bad()
        body['address'] = value.address
    elif value.address is not None:
        _bad()
    if gateway['action'] != 'retain':
        body['gateway'] = gateway
    return {'action': 'set', 'value': body}


def _canonical_patch(patch):
    # Exact DATA type avoids foreign property hooks, never proves authority.
    if type(patch) is not NetworkPatch or type(patch.nics) is not tuple or len(patch.nics) > 64:
        _bad()
    rows = []
    for row in patch.nics:
        if type(row) is not NICPatch:
            _bad()
        rows.append({'slot': row.slot, 'attachment_ref': row.attachment_ref,
                     'ipv4': _family_patch(row.ipv4), 'ipv6': _family_patch(row.ipv6)})
    data = {'nics': rows}
    for name in ('dns_servers', 'search_domains'):
        field = getattr(patch, name)
        value = _field_patch(field)
        if field.action == 'set':
            if type(field.value) is not tuple or not 1 <= len(field.value) <= 16:
                _bad()
            value['value'] = list(field.value)
        data[name] = value
    try:
        rebuilt = normalize_network_patch(data)
    except ValueError:
        _bad()
    if rebuilt != patch:
        _bad()


def _observation(value, kind, version=None):
    if (type(value) is not Observed or type(value.state) is not str or
            value.state not in ('value', 'absent', 'unknown')):
        _bad()
    if value.state != 'value':
        if value.value is not None:
            _bad()
        return
    actual = value.value
    if kind == 'mode':
        modes = ('static', 'dhcp', 'disabled') if version == 4 else ('static', 'dhcp', 'disabled', 'auto')
        if type(actual) is not str or actual not in modes:
            _bad()
    elif kind in ('address', 'gateway'):
        if type(actual) is not str or not 0 < len(actual) <= 68 or '%' in actual:
            _bad()
        try:
            parsed = ipaddress.ip_interface(actual) if kind == 'address' else ipaddress.ip_address(actual)
        except ValueError:
            _bad()
        if parsed.version != version or str(parsed) != actual:
            _bad()
        if kind == 'address' and '/' not in actual:
            _bad()
    else:
        if type(actual) is not tuple or len(actual) > 16:
            _bad()
        if actual:
            try:
                normalized = normalize_network_patch({kind: {'action': 'set', 'value': list(actual)}})
            except ValueError:
                _bad()
            if getattr(normalized, kind).value != actual:
                _bad()


def _observed_family(value, version):
    if type(value) is not ObservedFamily:
        _bad()
    for field in ('mode', 'address', 'gateway'):
        _observation(getattr(value, field), field, version)


def _observations(observed):
    if type(observed) is not ObservedNetwork or type(observed.nics) is not tuple or len(observed.nics) > 64:
        _bad()
    slots, refs = set(), set()
    for row in observed.nics:
        if (type(row) is not ObservedNIC or type(row.slot) is not int or not 0 <= row.slot <= 999 or
                type(row.attachment_ref) is not str or not _REFERENCE.fullmatch(row.attachment_ref) or
                row.slot in slots or row.attachment_ref in refs):
            _bad()
        slots.add(row.slot)
        refs.add(row.attachment_ref)
        for name, version in (('ipv4', 4), ('ipv6', 6), ('default_ipv4', 4), ('default_ipv6', 6)):
            _observed_family(getattr(row, name), version)
    for name in ('dns_servers', 'search_domains', 'default_dns_servers', 'default_search_domains'):
        _observation(getattr(observed, name), name.removeprefix('default_'))


def _from(value, origin):
    return MergedField(value.state, value.value, origin)


def _merge_field(patch, current, default):
    if patch.action == 'retain':
        return _from(current, 'retained')
    if patch.action == 'inherit':
        return _from(default, 'inherited')
    if patch.action == 'clear':
        return MergedField('absent', None, 'cleared')
    return MergedField('value', patch.value, 'set')


def _merge_family(patch, current, default):
    if patch is None or patch.action == 'retain':
        return MergedFamily(*(_from(x, 'retained') for x in current))
    if patch.action == 'inherit':
        return MergedFamily(*(_from(x, 'inherited') for x in default))
    if patch.action == 'clear':
        return MergedFamily(*(MergedField('absent', None, 'cleared') for _ in range(3)))
    mode = MergedField('value', patch.mode, 'set')
    address = (MergedField('value', patch.address, 'set') if patch.mode == 'static'
               else _from(current.address, 'retained'))
    gateway = _merge_field(patch.gateway, current.gateway, default.gateway)
    return MergedFamily(mode, address, gateway)


def _analyze_family(row, version, conflicts, uncertain):
    family = row.ipv4 if version == 4 else row.ipv6
    def issue(bucket, field, code):
        bucket.append(MergeIssue(field, row.slot, version, code))
    for name in ('mode', 'address', 'gateway'):
        if getattr(family, name).state == 'unknown':
            issue(uncertain, name, 'observation_unknown')
    if family.mode.state == 'absent':
        issue(uncertain, 'mode', 'absent_mode_needs_provider_default')
    if family.mode.state != 'value':
        return
    if family.mode.value != 'static':
        for name in ('address', 'gateway'):
            if getattr(family, name).state == 'value':
                issue(conflicts, name, 'nonstatic_mode_retains_static_field')
        return
    if family.address.state == 'absent':
        issue(conflicts, 'address', 'static_mode_without_address')
    if family.address.state != 'value':
        return
    interface = ipaddress.ip_interface(family.address.value)
    if interface.ip.is_unspecified or interface.ip.is_multicast or interface.ip.is_loopback:
        issue(conflicts, 'address', 'unusable_address')
    if version == 4:
        if interface.network.prefixlen >= 31:
            issue(uncertain, 'address', 'point_to_point_profile_required')
        elif interface.ip in (interface.network.network_address, interface.network.broadcast_address):
            issue(conflicts, 'address', 'subnet_boundary_address')
    if family.gateway.state == 'value':
        gateway = ipaddress.ip_address(family.gateway.value)
        if gateway.is_unspecified or gateway.is_multicast or gateway.is_loopback or gateway == interface.ip:
            issue(conflicts, 'gateway', 'unusable_or_self_gateway')
        elif gateway not in interface.network or version == 6 and gateway.is_link_local:
            issue(uncertain, 'gateway', 'qualified_routing_profile_required')
        elif version == 4 and interface.network.prefixlen < 31 and gateway in (
                interface.network.network_address, interface.network.broadcast_address):
            issue(conflicts, 'gateway', 'subnet_boundary_gateway')


def merge_observed_network(patch, observed):
    """Analyze only supplied DATA, without an approval/completeness result."""
    _canonical_patch(patch)
    _observations(observed)
    current = {row.slot: row for row in observed.nics}
    patches = {row.slot: row for row in patch.nics}
    for slot, row in patches.items():
        if slot not in current or current[slot].attachment_ref != row.attachment_ref:
            _bad()
    merged = []
    for slot, row in sorted(current.items()):
        change = patches.get(slot)
        merged.append(MergedNIC(slot, row.attachment_ref,
            _merge_family(change.ipv4 if change else None, row.ipv4, row.default_ipv4),
            _merge_family(change.ipv6 if change else None, row.ipv6, row.default_ipv6)))
    dns = _merge_field(patch.dns_servers, observed.dns_servers, observed.default_dns_servers)
    search = _merge_field(patch.search_domains, observed.search_domains, observed.default_search_domains)
    conflicts, uncertain = [], []
    for row in merged:
        for version in (4, 6):
            _analyze_family(row, version, conflicts, uncertain)
    counts = tuple(sum(getattr(row, name).gateway.state == 'value' for row in merged)
                   for name in ('ipv4', 'ipv6'))
    for version, count in zip((4, 6), counts):
        if count > 1:
            conflicts.append(MergeIssue('gateway', None, version, 'multiple_listed_default_gateways'))
    for name, field in (('dns_servers', dns), ('search_domains', search)):
        if field.state == 'unknown':
            uncertain.append(MergeIssue(name, None, None, 'observation_unknown'))
    return MergeAnalysis(tuple(merged), dns, search, tuple(conflicts), tuple(uncertain), *counts)
