"""Fixed postimage format checks for the dormant installation coordinator.

These functions accept bytes, not source authority. They perform no acquisition,
write, generation publication or admission. An original installation adapter must
retain the actual source cohort before calling them and retain its own end,
currentness, cancellation and cleanup obligations afterward. A successful check
does not satisfy those obligations or prove persistence/all-writer exclusion.

The two existing restricted profiles deliberately differ. A document supported
by configuration export may be unsupported by policy, and vice versa. Never
repair that difference by reusing an old binding or rewriting source bytes.
"""
from dataclasses import dataclass

from ._config.projection import ProjectionRefused, project as _project_config
from ._policy.decoder import decode_policy as _decode_policy
from ._policy.lines import InvalidDocument
from ._policy.policy import InvalidPolicy, _Snapshot


_CONFIG_FILE_LIMIT = 2 * 1024 * 1024
_CONFIG_TOTAL_LIMIT = 4 * 1024 * 1024
_POLICY_FILE_LIMIT = 1024 * 1024
_POLICY_TOTAL_LIMIT = 2 * 1024 * 1024
_REFUSAL = "Installation postimage format unavailable"


class PostimageRefused(ValueError):
    """Fixed format refusal; never a resource or authorization verdict."""


def _require(condition):
    if not condition:
        raise PostimageRefused(_REFUSAL)


def validate_config_postimage(freq, hosts, vlans):
    """Validate the exact three-file metadata profile without loader defaults.

The accepted projection checks required keys/types, explicit empty forms and
codec payload compatibility. Its output is discarded, never used as rewritten
input or an export artifact. Included metadata is not guaranteed secret-free.
"""
    originals = (freq, hosts, vlans)
    _require(all(type(raw) is bytes for raw in originals))
    _require(all(0 < len(raw) <= _CONFIG_FILE_LIMIT for raw in originals))
    _require(sum(map(len, originals)) <= _CONFIG_TOTAL_LIMIT)
    refused = False
    try:
        _project_config(dict(zip(("freq.toml", "hosts.toml", "vlans.toml"), originals)))
    except ProjectionRefused:
        refused = True
    # Raise outside the handler so the outward exception does not keep the
    # parser's exception context/traceback. This is not a physical-release proof.
    if refused:
        raise PostimageRefused(_REFUSAL)


def validate_policy_postimage(hosts, fleet_boundaries):
    """Exhaust the selected strict full-policy pair, preserving its empty syntax.

Zero-byte documents are valid syntax for this profile. The actual original
adapter must separately prove successful acquisition: missing storage cannot be
converted to empty bytes. Unsupported TOML dialects refuse without rewriting.
"""
    originals = (hosts, fleet_boundaries)
    _require(all(type(raw) is bytes for raw in originals))
    _require(all(len(raw) <= _POLICY_FILE_LIMIT for raw in originals))
    _require(sum(map(len, originals)) <= _POLICY_TOTAL_LIMIT)
    refused = False
    try:
        projected = _decode_policy(hosts, fleet_boundaries)
    except (InvalidDocument, InvalidPolicy):
        refused = True
    if refused:
        raise PostimageRefused(_REFUSAL)
    _require(type(projected) is _Snapshot and type(projected.encoded) is bytes)
    _require(0 < len(projected.encoded) <= _POLICY_FILE_LIMIT)


@dataclass(frozen=True, slots=True)
class PostimageFormats:
    """Data-only support summary; not a binding, receipt, grant or release."""

    config_supported: bool
    policy_supported: bool


def assess_postimage_formats(*, freq, hosts, vlans, fleet_boundaries):
    """Check both fixed profiles against the same supplied immutable hosts bytes.

There is no supplied validator, successful flag, parsed object, path, descriptor
or callback. Only fixed-parser format refusals become unsupported. Unexpected
errors and control interruptions propagate, so no completed summary is returned.
The coordinator must not accept a caller-constructed summary as original proof.
"""
    config_supported = policy_supported = True
    try:
        validate_config_postimage(freq, hosts, vlans)
    except PostimageRefused:
        config_supported = False
    try:
        validate_policy_postimage(hosts, fleet_boundaries)
    except PostimageRefused:
        policy_supported = False
    return PostimageFormats(config_supported, policy_supported)
