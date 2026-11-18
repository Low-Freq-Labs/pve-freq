"""Fixed original-startup parser composition; private DATA, never an issuer.

The actual root source owner must retain its four original acquired byte streams
and the actual auth reader's same-cohort freq/users/roles bytes before calling.
Only native-confirmed absence may be None. Byte agreement here is an integrity
check, not a snapshot, continuing-writer fence, resource/currentness proof or
authority. Do not instantiate an installation, selection or session from a
caller-created result. This module performs no native IO or legacy loading.
"""
from dataclasses import dataclass

from freq.services.pilot_readonly_inputs import (
    PilotInputUnavailable, decode_retained_original_inputs,
)
from freq.services.pilot_startup_formats.postimages import assess_postimage_formats


_MIB = 1048576
_SOURCE_LIMITS = (2 * _MIB, 2 * _MIB, 2 * _MIB, _MIB)


class StartupInputsUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot startup inputs unavailable')


@dataclass(frozen=True, slots=True)
class PilotStartupData:
    """Format/configuration values only; construction grants no authority."""
    nodes: tuple
    configured_users: tuple
    service_user: str
    token_id: tuple | None
    config_supported: bool
    policy_supported: bool


def decode_fixed_startup_inputs(source_bytes, auth_freq, users=None, roles=None):
    """Join the fixed four-source and existing configured-user parser graphs.

    source_bytes order is exactly freq, hosts, vlans, fleet-boundaries. The
    auth reader's freq must agree with the source owner's COMPLETE freq bytes;
    no selecting one source, merging documents, filling defaults or fetching a
    replacement. The auth parser's existing1MiB freq cap is intentionally the
    narrower eligibility limit for this pilot; config's2MiB bound is unchanged.

    The two profile support values remain independent. Unsupported policy must
    never resurrect a previous policy binding. Empty native-present policy
    storage differs from missing storage. Empty nodes/users and missing token
    ID stay empty/None, never a fallback credential or default administrator.

    Fixed parsers run outside every admission gate in an originally supervised
    worker with the inherited end. Input caps are logical byte bounds, not a
    heap/CPU/deadline guarantee. A result does not close the native readers or
    replace their later currentness/retirement or original final admission.
    """
    if type(source_bytes) is not tuple or len(source_bytes) != 4:
        raise StartupInputsUnavailable()
    if any(type(raw) is not bytes for raw in source_bytes):
        raise StartupInputsUnavailable()
    if any(len(raw) > cap for raw, cap in zip(source_bytes, _SOURCE_LIMITS)):
        raise StartupInputsUnavailable()
    if sum(len(raw) for raw in source_bytes[:3]) > 4 * _MIB:
        raise StartupInputsUnavailable()
    freq, hosts, vlans, fleet_boundaries = source_bytes
    if (type(auth_freq) is not bytes or len(auth_freq) > _MIB or
            auth_freq != freq):
        raise StartupInputsUnavailable()
    # Check optional byte inputs before either fixed parser, without invoking
    # supplied object/subclass __len__, equality, iteration or decoding hooks.
    if any(raw is not None and (type(raw) is not bytes or len(raw) > _MIB)
           for raw in (users, roles)):
        raise StartupInputsUnavailable()
    formats = assess_postimage_formats(freq=freq, hosts=hosts, vlans=vlans,
                                       fleet_boundaries=fleet_boundaries)
    refused = False
    try:
        nodes, configured_users, service_user, token_id = (
            decode_retained_original_inputs(freq, users, roles))
    except PilotInputUnavailable:
        refused = True
    if refused:
        # Fixed refusal outside handler; no parser diagnostic/context retained.
        raise StartupInputsUnavailable()
    return PilotStartupData(nodes, configured_users, service_user, token_id,
                            formats.config_supported, formats.policy_supported)


# No entrypoint, original factory, source/credential acquisition or publication.
