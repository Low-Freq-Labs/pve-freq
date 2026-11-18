"""Private configured-only NIC analysis; no source or effect authority."""
from dataclasses import dataclass
import ipaddress
import re

from freq.services.cloud_init_ipconfig_patch import parse_observed_ipconfig
from freq.services.cloud_init_network_intent import normalize_network_patch
from freq.services.cloud_init_observed_merge import (
    Observed, ObservedFamily, ObservedNIC, ObservedNetwork, merge_observed_network,
)


class InvalidConfiguredNetwork(ValueError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class ConfiguredNetworkAnalysisData:
    patch: object
    configured: object
    listed_options: tuple
    analysis: object


_SLOT = re.compile(r'(net|ipconfig)([0-9]|[12][0-9]|3[01])\Z')
_REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_UNKNOWN = Observed('unknown', None)
_ABSENT = Observed('absent', None)
_DEFAULT = ObservedFamily(_UNKNOWN, _UNKNOWN, _UNKNOWN)


def _bad():
    raise InvalidConfiguredNetwork('Configured network DATA unavailable') from None


def _family(fields, address_key, gateway_key):
    if address_key not in fields:
        return _DEFAULT
    address = fields[address_key]
    if address in ('dhcp', 'auto'):
        return ObservedFamily(Observed('value', address), _ABSENT, _ABSENT)
    gateway = (Observed('value', str(ipaddress.ip_address(fields[gateway_key])))
               if gateway_key in fields else _ABSENT)
    return ObservedFamily(Observed('value', 'static'),
                          Observed('value', str(ipaddress.ip_interface(address))), gateway)


def analyze_configured_network(patch, config, attachments):
    """Analyze only listed configured DATA, preserving exact option text.

    Missing family/default/DNS evidence remains unknown. No fallback source,
    provider serialization, completeness assertion or target authority occurs.
    """
    if type(config) is not dict or len(config) > 4096:
        _bad()
    if type(attachments) is not tuple or len(attachments) > 32:
        _bad()
    labels, references = {}, set()
    for row in attachments:
        if type(row) is not tuple or len(row) != 2:
            _bad()
        slot, ref = row
        if (type(slot) is not int or not 0 <= slot <= 31 or
                type(ref) is not str or not _REF.fullmatch(ref) or
                slot in labels or ref in references):
            _bad()
        labels[slot] = ref
        references.add(ref)
    nets, options, total = set(), {}, 0
    for key, value in config.items():
        if (type(key) is not str or type(value) is not str or
                not 0 < len(key) <= 4096 or len(value) > 4096):
            _bad()
        try:
            total += len(key.encode('utf-8')) + len(value.encode('utf-8'))
        except UnicodeError:
            _bad()
        if total > 1048576 or key == 'cicustom':
            _bad()
        if key.startswith(('net', 'ipconfig')):
            match = _SLOT.fullmatch(key)
            if match is None:
                _bad()
            kind, number = match.groups()
            slot = int(number)
            if kind == 'net':
                if not value:
                    _bad()
                nets.add(slot)
            else:
                # Full parser validation includes both families and all fields.
                options[slot] = (value, parse_observed_ipconfig(value))
    if nets != labels.keys() or not options.keys() <= nets:
        _bad()
    rows, originals = [], []
    for slot, ref in sorted(labels.items()):
        original, fields = options.get(slot, (None, {}))
        rows.append(ObservedNIC(slot, ref, _family(fields, 'ip', 'gw'),
                                _family(fields, 'ip6', 'gw6'), _DEFAULT, _DEFAULT))
        originals.append((slot, original))
    configured = ObservedNetwork(tuple(rows), _UNKNOWN, _UNKNOWN, _UNKNOWN, _UNKNOWN)
    normalized = normalize_network_patch(patch)
    analysis = merge_observed_network(normalized, configured)
    return ConfiguredNetworkAnalysisData(normalized, configured, tuple(originals), analysis)
