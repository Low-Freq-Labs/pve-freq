"""Bounded cloud-init network patch DATA shared by future interface adapters.

No caller, target, attachment reference, normalized value or mode here grants
permission, currentness, provider representability, address reservation or guest
application. This module performs no IO and emits no provider command. Actual
API/CLI/provisioning joins remain absent; accepted mutation handlers are intact.

Bare addresses and off-link/scoped gateway profiles are deliberately refused
until a genuine installed profile resolver exists. Numeric limits below bound
this DATA parser; they are not claims about installed PVE device capabilities.
"""
import ipaddress
import re
from typing import NamedTuple


class InvalidNetworkIntent(ValueError):
    """Fixed nonsensitive validation errors; never echo submitted values."""


class FieldPatch(NamedTuple):
    action: str
    value: object


class FamilyPatch(NamedTuple):
    action: str
    mode: object
    address: object
    gateway: FieldPatch


class NICPatch(NamedTuple):
    slot: int
    attachment_ref: str
    ipv4: FamilyPatch
    ipv6: FamilyPatch


class NetworkPatch(NamedTuple):
    nics: tuple
    dns_servers: FieldPatch
    search_domains: FieldPatch


_RETAIN = FieldPatch('retain', None)
_UNCHANGED = FamilyPatch('retain', None, None, _RETAIN)
_DOMAIN_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
_REFERENCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')


def _bad(reason):
    raise InvalidNetworkIntent(reason) from None


def _shape(value, allowed, required=()):
    if type(value) is not dict:
        _bad('Expected an explicit patch object')
    if (len(value) > len(allowed) or any(type(key) is not str for key in value) or
            not set(required) <= value.keys() <= set(allowed)):
        _bad('Unknown or missing patch field')


def _action(value):
    _shape(value, ('action', 'value'), ('action',))
    action = value['action']
    if type(action) is not str or action not in ('retain', 'set', 'clear', 'inherit'):
        _bad('Unknown patch action')
    if (action == 'set') != ('value' in value):
        _bad('Only set requires a value')
    return action


def _address(value, version):
    if type(value) is not str or not 0 < len(value) <= 64 or '%' in value:
        _bad('Expected an unscoped address')
    try:
        result = ipaddress.ip_address(value)
    except ValueError:
        _bad('Invalid address')
    if result.version != version:
        _bad('Address family mismatch')
    if result.is_unspecified or result.is_multicast or result.is_loopback:
        _bad('Unusable guest or resolver address')
    return result


def _gateway(value, interface):
    if value is None:
        return _RETAIN
    action = _action(value)
    if action != 'set':
        return FieldPatch(action, None)
    gateway = _address(value['value'], interface.version)
    if gateway == interface.ip:
        _bad('Gateway equals guest address')
    if gateway not in interface.network:
        _bad('Off-link gateway requires a qualified routing profile')
    if gateway.version == 6 and gateway.is_link_local:
        _bad('Scoped gateway requires a qualified routing profile')
    if gateway.version == 4 and gateway in (interface.network.network_address,
                                            interface.network.broadcast_address):
        _bad('Gateway is a subnet boundary address')
    return FieldPatch('set', str(gateway))


def _family(value, version):
    action = _action(value)
    if action != 'set':
        return FamilyPatch(action, None, None, _RETAIN)
    body = value['value']
    _shape(body, ('mode', 'address', 'gateway'), ('mode',))
    mode = body['mode']
    modes = ('disabled', 'dhcp', 'static') if version == 4 else ('disabled', 'dhcp', 'auto', 'static')
    if type(mode) is not str or mode not in modes:
        _bad('Unsupported address intent mode')
    if mode != 'static':
        if set(body) != {'mode'}:
            _bad('Only static intent accepts address or gateway')
        return FamilyPatch('set', mode, None, _RETAIN)
    value = body.get('address')
    if (type(value) is not str or not 0 < len(value) <= 68 or
            value.count('/') != 1 or '%' in value):
        _bad('Static addressing requires an explicit full CIDR')
    address, prefix = value.split('/')
    if not prefix.isascii() or not prefix.isdecimal() or (len(prefix) > 1 and prefix[0] == '0'):
        _bad('CIDR prefix must be an explicit decimal length')
    parsed = _address(address, version)
    try:
        interface = ipaddress.ip_interface(value)
    except ValueError:
        _bad('Invalid full CIDR')
    if interface.version != version or interface.ip != parsed:
        _bad('Address family mismatch')
    if version == 4:
        if interface.network.prefixlen >= 31:
            _bad('Point-to-point or host prefix requires a qualified profile')
        if interface.ip in (interface.network.network_address, interface.network.broadcast_address):
            _bad('Guest address is a subnet boundary address')
    gateway = _gateway(body.get('gateway'), interface)
    # An explicit null gateway is not omission/retain, clear or inherit.
    if 'gateway' in body and body['gateway'] is None:
        _bad('Gateway changes require explicit patch intent')
    return FamilyPatch('set', 'static', str(interface), gateway)


def _list_patch(value, kind):
    action = _action(value)
    if action != 'set':
        return FieldPatch(action, None)
    items = value['value']
    if type(items) is not list or not 1 <= len(items) <= 16:
        _bad('Set requires a bounded nonempty list; use clear for removal')
    result = []
    for item in items:
        if kind == 'resolver':
            if type(item) is not str or not 0 < len(item) <= 64 or '/' in item:
                _bad('Resolver must be an address')
            try:
                version = ipaddress.ip_address(item).version
            except ValueError:
                _bad('Invalid resolver address')
            normalized = str(_address(item, version))
            if version == 6 and ipaddress.ip_address(normalized).is_link_local:
                _bad('Scoped resolver requires a qualified profile')
        else:
            if type(item) is not str or not 1 <= len(item) <= 253 or not item.isascii():
                _bad('Domain requires explicit ASCII syntax; IDNA profile unsupported')
            normalized = item.lower()
            if normalized.endswith('.'):
                normalized = normalized[:-1]
            if not normalized or any(not _DOMAIN_LABEL.fullmatch(label) for label in normalized.split('.')):
                _bad('Invalid search domain')
        if normalized in result:
            _bad('Duplicate list entry')
        result.append(normalized)
    return FieldPatch('set', tuple(result))


def normalize_network_patch(value):
    """Return immutable normalized product intents; never effective settings.

    Omission is retain. Clear and inherit remain distinct. Family disabled/auto
    labels survive as product intents and require actual installed capability
    checks before a future compiler can represent them. No missing IPv4 value
    is serialized as implicit DHCP. Gateway/DNS defaults are never inferred.
    """
    _shape(value, ('nics', 'dns_servers', 'search_domains'))
    nics = value.get('nics', [])
    if type(nics) is not list or len(nics) > 64:
        _bad('NIC patch list exceeds DATA bound')
    rows, slots, references = [], set(), set()
    for nic in nics:
        _shape(nic, ('slot', 'attachment_ref', 'ipv4', 'ipv6'), ('slot', 'attachment_ref'))
        slot, reference = nic['slot'], nic['attachment_ref']
        if type(slot) is not int or not 0 <= slot <= 999:
            _bad('Invalid original NIC slot')
        if type(reference) is not str or not _REFERENCE.fullmatch(reference):
            _bad('Invalid attachment reference DATA')
        if slot in slots or reference in references:
            _bad('Duplicate original attachment or slot')
        slots.add(slot)
        references.add(reference)
        rows.append(NICPatch(slot, reference,
            _family(nic['ipv4'], 4) if 'ipv4' in nic else _UNCHANGED,
            _family(nic['ipv6'], 6) if 'ipv6' in nic else _UNCHANGED))
    # Explicit default gateways across NICs need an actual routing policy.
    for family in ('ipv4', 'ipv6'):
        if sum(getattr(row, family).gateway.action == 'set' for row in rows) > 1:
            _bad('Multiple default gateways require a qualified routing policy')
    return NetworkPatch(tuple(sorted(rows, key=lambda row: row.slot)),
        _list_patch(value['dns_servers'], 'resolver') if 'dns_servers' in value else _RETAIN,
        _list_patch(value['search_domains'], 'domain') if 'search_domains' in value else _RETAIN)
