"""Bounded merge of explicitly observed ipconfig fields; no target authority.

This preserves listed IPv6 field bytes during a legacy IPv4 edit. Supplied
configuration is not proof of complete/current observations, reservation,
provider capability, routing policy or effective guest state. Unknown option
syntax is refused rather than forwarded. No defaults, clear intent or commands
are invented here; real source/revision/attachment admission is still owed.
"""
import re

from freq.services.cloud_init_legacy_inputs import legacy_static_ipv4
from freq.services.cloud_init_network_intent import InvalidNetworkIntent, normalize_network_patch


def parse_observed_ipconfig(value):
    """Read only the four bounded documented fields; retain exact value bytes."""
    if value is None:
        return {}
    if type(value) is not str or not 0 < len(value) <= 512 or not value.isascii() or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in value):
        raise InvalidNetworkIntent('Observed address option is unavailable or unsupported')
    fields = {}
    parts = value.split(',')
    if len(parts) > 4:
        raise InvalidNetworkIntent('Observed address option is ambiguous')
    for part in parts:
        key, sep, text = part.partition('=')
        if not sep or key not in ('ip', 'gw', 'ip6', 'gw6') or key in fields or not text or '=' in text:
            raise InvalidNetworkIntent('Observed address option is ambiguous or unsupported')
        fields[key] = text
    for key, gateway, version in (('ip', 'gw', 4), ('ip6', 'gw6', 6)):
        if key not in fields:
            if gateway in fields:
                raise InvalidNetworkIntent('Observed gateway has no explicit address family')
            continue
        address = fields[key]
        if address in (('dhcp',) if version == 4 else ('dhcp', 'auto')):
            family = {'mode': address}
            if gateway in fields:
                raise InvalidNetworkIntent('Observed dynamic family has an explicit gateway')
        else:
            family = {'mode': 'static', 'address': address}
            if gateway in fields:
                family['gateway'] = {'action': 'set', 'value': fields[gateway]}
        normalize_network_patch({'nics': [{'slot': 0, 'attachment_ref': 'observed:0',
            'ipv4' if version == 4 else 'ipv6': {'action': 'set', 'value': family}}]})
    return fields


def merge_ipv4_option(observed, address, gateway=None):
    """Replace IPv4 address; omission retains observed gateway and IPv6 fields.

    None/exact empty gateway is legacy omission, never an intentional clear.
    A retained gateway incompatible with the new CIDR refuses before effects.
    Explicit clear/inherit requires a future typed interface/installed adapter.
    """
    fields = parse_observed_ipconfig(observed)
    if gateway is None or type(gateway) is str and gateway == '':
        gateway = fields.get('gw')
    cidr, gateway = legacy_static_ipv4(address, gateway)
    result = ['ip='+cidr]
    if gateway is not None:
        result.append('gw='+gateway)
    for name in ('ip6', 'gw6'):
        if name in fields:
            result.append(name+'='+fields[name])
    return ','.join(result)


def plan_ipv4_option(config, index, address, gateway=None):
    """Check listed retained-plus-new routes, not physical inventory coverage."""
    if type(config) is not dict or len(config)>4096 or type(index) is not int or not 0<=index<=31:
        raise InvalidNetworkIntent('Expected bounded observed configuration and NIC index')
    target = 'ipconfig'+str(index)
    observed = {}
    for key, value in config.items():
        if type(key) is not str or type(value) is not str:
            raise InvalidNetworkIntent('Expected explicit observed configuration fields')
        if key.startswith('ipconfig'):
            if not re.fullmatch(r'ipconfig([0-9]|[12][0-9]|3[01])', key):
                raise InvalidNetworkIntent('Observed NIC slot is unsupported')
            observed[key] = parse_observed_ipconfig(value)
    merged = merge_ipv4_option(config.get(target), address, gateway)
    observed[target] = parse_observed_ipconfig(merged)
    for name in ('gw', 'gw6'):
        if sum(name in fields for fields in observed.values()) > 1:
            raise InvalidNetworkIntent('Retained and proposed default routes require an explicit routing policy')
    return merged
