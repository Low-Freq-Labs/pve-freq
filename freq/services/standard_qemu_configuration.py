"""Pure private configured-source projection for the standard read owner.

This reuses the accepted retained-input decoder as DATA, without its retired
native worker/profile. No file/config loader, credential, principal lookup,
installation/view/reference issuer or provider operation runs here. The future
original caller must bind complete retained bytes, source gates and currentness;
a successful tuple does not establish that binding or grant read authority.
"""
import ipaddress

from freq.core.config import is_managed_service_account_name
from freq.services.pilot_readonly_inputs import (
    PilotInputUnavailable, decode_retained_original_inputs,
)


class ConfigurationUnavailable(Exception):
    def __init__(self):
        super().__init__('Read configuration unavailable')


def decode_private_configuration(config_raw, users_raw=None, roles_raw=None):
    """Return the four original fields plus the original configured token ID.

    Each node is (literal label, original endpoint spelling, canonical IP).
    Preserve the original spelling for the existing node-scoped secret filename;
    transport normalization cannot select another node's credential. No shared
    secret/path is returned. The fifth field retains the exact original
    (principal, configured-name) tuple as private metadata for the original
    node credential owner; it never selects that shared token name for IO.
    The first four positions are conserved; missing token/principal stay None.
    Original users precedence and strict ambiguity refusal are conserved. This
    function does not resolve an OS account or authenticate any configured user.
    """
    try:
        nodes, users, service, token = decode_retained_original_inputs(
            config_raw, users_raw, roles_raw)
    except PilotInputUnavailable:
        raise ConfigurationUnavailable() from None
    if not is_managed_service_account_name(service):
        raise ConfigurationUnavailable()
    projected = []
    for label, original in nodes:
        address = ipaddress.ip_address(original)
        if address.is_unspecified or address.is_multicast:
            raise ConfigurationUnavailable()
        projected.append((label, original, str(address)))
    return (tuple(projected), users, service,
            None if token is None else token[0], token)
