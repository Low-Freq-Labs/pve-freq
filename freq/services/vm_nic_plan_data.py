"""Immutable, lossless validated NIC scalar DATA for future plan input.

The existing guest-config grammar remains the only accepted syntax. Explicit
firewall/link_down/host-tunnel, queues, MTU, rate and trunks are retained rather
than silently dropped. Missing options do not become false/zero/defaults, and
raw rate lexemes have no inferred unit or installed capability claim.

This is not attachment identity, complete/current configuration, an admitted
plan, a provider command or permission to reuse a raw value for mutation.
Original owner/source/coverage/profile/concurrency/disclosure gates are owed.
"""
from dataclasses import dataclass

from freq.services.guest_profile_formats.guest_config import (
    nic as _project_nic, properties as _properties,
)


@dataclass(frozen=True, slots=True, repr=False)
class ObservedNICOptionsData:
    """Private source lexemes and old four-field projection; no authority."""
    raw: str
    options: tuple
    model: str
    mac: object
    bridge: object
    vlan: object


def preserve_observed_nic_options(value):
    """Keep every explicit supported option after the existing validation.

    Native immutable str input is checked by that grammar before projection.
    Two bounded scalar parses (each <=4096 characters) trade small repeated
    parsing for conservation of the independently accepted old parser bytes.
    These logical bounds do not qualify parser/heap/deadline or source custody.
    No effective default, unit, MAC/IP/VLAN relationship or source identity is
    inferred. Both bare-model and model=MAC syntax retain their exact raw value.
    """
    projected = _project_nic(value)
    fields = _properties(value, allow_bare_model=True)
    return ObservedNICOptionsData(value, tuple(fields.items()),
                                  projected['model'], projected['mac'],
                                  projected['bridge'], projected['vlan'])
