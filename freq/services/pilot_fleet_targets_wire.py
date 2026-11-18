"""Proposed retained Fleet pair wire DATA; contract and original join pending.

Only a pure prebuilt document is produced. No source reader, request, session,
deadline, native owner, listener or write right is created here. The original
component must retain the SAME DATA across its real final admission before any
response is sent. The v1 legacy-loader contract stays unchanged elsewhere.
"""
import hashlib
import json

from freq.services.pilot_fleet_targets_data import (
    ConfiguredFleetTargetsData, FleetTargetDataUnavailable, _identity,
    TARGET_LIMIT,
)


TARGET_WIRE_LIMIT = 2 * 1024 * 1024


def format_retained_fleet_targets_data(data):
    """Validate and serialize the complete private projection outside gates.

    Exact types and a recomputed digest are format/correlation checks only.
    They cannot establish original source, session, writer, target incarnation,
    transport custody or mutation authority. Unknown failures produce no value.
    The cap is a logical output bound, not physical CPU/heap supervision.
    """
    if type(data) is not ConfiguredFleetTargetsData:
        raise FleetTargetDataUnavailable()
    pairs, expected = data.pairs, data.target_set_sha256
    if (type(pairs) is not tuple or len(pairs) > TARGET_LIMIT or
            type(expected) is not str or len(expected) != 64 or
            any(c not in '0123456789abcdef' for c in expected)):
        raise FleetTargetDataUnavailable()
    aliases, rows = {}, []
    for index, pair in enumerate(pairs):
        if type(pair) is not tuple or len(pair) != 2:
            raise FleetTargetDataUnavailable()
        invalid_unicode = False
        try:
            label, address = _identity(pair[0]), _identity(pair[1])
        except UnicodeError:
            invalid_unicode = True
        if invalid_unicode:
            raise FleetTargetDataUnavailable()
        for alias in (label, address):
            if alias in aliases and aliases[alias] != index:
                raise FleetTargetDataUnavailable()
            aliases[alias] = index
        rows.append({'label': label, 'ip': address})
    canonical = json.dumps(sorted(pairs), ensure_ascii=True,
                           separators=(',', ':')).encode('ascii')
    actual = hashlib.sha256(canonical).hexdigest()
    if actual != expected:
        raise FleetTargetDataUnavailable()
    document = {
        'schema': 'fleet-exec-targets-v2',
        'ok': True,
        'source': 'retained_hosts_bytes',
        'scope': 'configured_host_pairs',
        'complete': True,
        'hosts': rows,
        'target_set_sha256': actual,
        'raw_config_verified': False,
        'loader_may_bootstrap_or_migrate': False,
        'estate_complete': False,
        'adoption_verified': False,
        'reachability_verified': False,
    }
    body = json.dumps(document, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':')).encode('ascii')
    if len(body) > TARGET_WIRE_LIMIT:
        raise FleetTargetDataUnavailable()
    return body


# No original component, endpoint, command operation or response write binding.
