"""Early legacy IPv4 input guards, without admission or provider effects.

Planned attachment references below are parser DATA only. Existing legacy
omission still means DHCP for CLI/provision; this is not a complete portable
intent adapter. API static auto allocation is refused until explicit intent,
current target, installed profile and address reservation are joined.
"""
from freq.services.cloud_init_network_intent import (
    InvalidNetworkIntent, normalize_network_patch,
)

from freq.services.cloud_init_identity_intent import (
    InvalidIdentityIntent, normalize_identity_patch,
)


def legacy_guest_user(value):
    """Validate the configured guest-name subset before legacy effects.

    This preserves literal valid text. It selects no host account, resolves no
    credential and establishes no target/profile or guest application state.
    """
    patch = normalize_identity_patch({
        'ciuser': {'action': 'set', 'value': value},
    })
    return patch.ciuser.value


def legacy_static_ipv4(address, gateway=None):
    """Validate supplied full CIDR and optional on-link gateway; no defaults."""
    family = {'mode': 'static', 'address': address}
    if gateway is not None and gateway != '':
        family['gateway'] = {'action': 'set', 'value': gateway}
    patch = normalize_network_patch({'nics': [{
        'slot': 0, 'attachment_ref': 'planned:0',
        'ipv4': {'action': 'set', 'value': family},
    }]})
    result = patch.nics[0].ipv4
    return result.address, result.gateway.value if result.gateway.action == 'set' else None


_UNREPRESENTED_CREATE_FIELDS = frozenset((
    'ipv4', 'ipv4_mode', 'ipv6', 'ipv6_mode', 'ip6', 'ip6_mode', 'gw6', 'gateway6',
    'dns_servers', 'search_domains', 'identity', 'ciuser', 'public_keys',
    'password_reference', 'cipassword', 'sshkeys', 'citype', 'ciupgrade',
    'cicustom', 'snippets', 'user_data', 'vendor_data', 'meta_data',
    'network_data', 'snippet_reference', 'snippet_references',
))


def _reject_unrepresented_create_fields(value):
    # Inspect names only: do not parse or reflect a supplied secret/key value.
    if (type(value) is not dict or any(type(key) is not str for key in value) or
            any(key in _UNREPRESENTED_CREATE_FIELDS for key in value)):
        raise InvalidNetworkIntent('Cloud-init create fields are unsupported') from None
    # The legacy network field is a VLAN/profile alias, not the new private
    # combined preparation root. Preserve existing scalar alias behavior.
    if 'network' in value and type(value['network']) not in (str, int, float, bool, type(None)):
        raise InvalidNetworkIntent('Cloud-init create fields are unsupported') from None


def validate_legacy_create_network(payload):
    """Reject ambiguous request inputs before discovery or VMID allocation.

Profile/global defaults are still handled by the original planner, not
qualified by this input guard. No supplied address or gateway is inferred.
    """
    if type(payload) is not dict:
        raise InvalidNetworkIntent('Expected an explicit create request') from None
    _reject_unrepresented_create_fields(payload)
    if 'nics' in payload:
        nics = payload['nics']
        if type(nics) is not list or not 1 <= len(nics) <= 64:
            raise InvalidNetworkIntent('Expected a bounded nonempty NIC list') from None
    else:
        nics = [payload]
    # Refuse unsupported fields anywhere before normalizing an earlier NIC.
    for nic in nics:
        if type(nic) is not dict:
            raise InvalidNetworkIntent('Expected an explicit NIC object') from None
        _reject_unrepresented_create_fields(nic)
    # Flat fields are a legacy first-NIC mirror when a list is supplied.
    # Never silently discard contradictory or unrepresented explicit intent.
    # Exact scalar comparisons avoid coercion or inspecting opaque values.
    if 'nics' in payload:
        first = nics[0]
        for key in ('network_profile', 'network_profile_id', 'profile',
                    'vlan', 'vlan_id', 'network', 'ip_mode', 'ip',
                    'gateway', 'gw', 'bridge'):
            if key in payload:
                value = payload[key]
                if (key not in first or
                        type(value) not in (str, int, float, bool, type(None)) or
                        type(first[key]) is not type(value) or value != first[key]):
                    raise InvalidNetworkIntent('Conflicting create NIC representations') from None
    rows = []
    for index, nic in enumerate(nics):
        if type(nic) is not dict:
            raise InvalidNetworkIntent('Expected an explicit NIC object') from None
        mode = nic.get('ip_mode', 'static')
        if type(mode) is not str or mode not in ('static', 'dhcp'):
            raise InvalidNetworkIntent('Expected explicit static or DHCP mode') from None
        if 'gateway' in nic and 'gw' in nic:
            raise InvalidNetworkIntent('Use one gateway field') from None
        gateway = nic.get('gateway', nic.get('gw'))
        address = nic.get('ip')
        if mode == 'static':
            cidr, gateway = legacy_static_ipv4(address, gateway)
            family = {'mode': 'static', 'address': cidr}
            if gateway is not None:
                family['gateway'] = {'action': 'set', 'value': gateway}
        else:
            if not (address is None or type(address) is str and address in ('', 'auto')):
                raise InvalidNetworkIntent('DHCP cannot discard a supplied static address') from None
            if not (gateway is None or type(gateway) is str and gateway == ''):
                raise InvalidNetworkIntent('DHCP cannot discard a supplied gateway') from None
            family = {'mode': 'dhcp'}
        rows.append({'slot': index, 'attachment_ref': 'planned:' + str(index),
                     'ipv4': {'action': 'set', 'value': family}})
    # This checks explicit cross-NIC default routes too. It proves no complete
    # observation, profile/default currentness or actual attachment identity.
    normalize_network_patch({'nics': rows})


def legacy_dns_servers(value):
    """Canonical ordered resolver-address DATA, not an effective DNS policy.

    None or the exact empty string means no explicit resolver in the legacy
    interface. Callers omit the provider option; this never clears a target
    value or claims a qualified inherit/default profile. A nonempty value
    must contain address literals separated by ASCII spaces only.
    """
    if value is None:
        return ''
    if type(value) is not str:
        raise InvalidNetworkIntent('Expected resolver address text') from None
    if value == '':
        return ''
    if (len(value) > 1040 or not value.isascii() or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise InvalidNetworkIntent('Expected bounded resolver address text') from None
    addresses = value.split(' ')
    addresses = [part for part in addresses if part]
    if not addresses:
        raise InvalidNetworkIntent('Nonempty resolver text requires addresses') from None
    patch = normalize_network_patch({'dns_servers': {'action': 'set', 'value': addresses}})
    return ' '.join(patch.dns_servers.value)
