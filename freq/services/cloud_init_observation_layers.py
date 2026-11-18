"""Private supplied field-observation DATA; no effective/guest inference.

Configured/current/pending/generated are separate named inputs, never fallback
sources. No endpoint, provider parser, observation issuer, operation, target,
profile, permission, source coverage, mounted-media or guest result is supplied
by these caller-constructible records. Per-NIC merging is a separate module.
"""
import base64
import binascii
from dataclasses import dataclass
import math
import re

from freq.services.cloud_init_identity_intent import (
    InvalidIdentityIntent, normalize_identity_patch,
)
from freq.services.cloud_init_network_intent import (
    InvalidNetworkIntent, normalize_network_patch,
)


class InvalidObservationData(ValueError):
    """Fixed diagnostic without converting or reflecting submitted values."""


@dataclass(frozen=True, slots=True, repr=False)
class ObservedValueData:
    state: str
    value: object
    revision: object
    observed_at: object


@dataclass(frozen=True, slots=True, repr=False)
class FieldObservationData:
    key: str
    source_kind: str
    source_revision: object
    sensitive: bool
    configured: ObservedValueData
    current: ObservedValueData
    pending: ObservedValueData
    generated: ObservedValueData


_FIELDS = ('dns_servers', 'search_domains', 'ciuser',
           'public_key_fingerprints', 'password', 'citype', 'ciupgrade')
_LAYERS = ('configured', 'current', 'pending', 'generated')
_SOURCES = ('explicit', 'inherited', 'provider_default', 'image_default', 'custom', 'unknown')
_STATES = ('value', 'absent', 'redacted', 'unknown')
_REVISION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_FINGERPRINT = re.compile(r'SHA256:[A-Za-z0-9+/]{43}\Z')


def _bad():
    raise InvalidObservationData('Invalid or unsupported cloud-init observation DATA') from None


def _shape(value, allowed, required=()):
    if (type(value) is not dict or len(value) > len(allowed) or
            any(type(key) is not str for key in value) or
            not set(required) <= value.keys() <= set(allowed)):
        _bad()


def _revision(value):
    if value is not None and (type(value) is not str or not _REVISION.fullmatch(value)):
        _bad()
    return value


def _observed_at(value):
    if value is not None and (type(value) is not float or
            not 0 < value <= 9007199254740991 or not math.isfinite(value)):
        _bad()
    return value


def _fingerprints(value):
    # Public digest DATA only. No wire key/private material or trust inference.
    if type(value) is not list or len(value) > 32:
        _bad()
    result = []
    for text in value:
        if type(text) is not str or not _FINGERPRINT.fullmatch(text):
            _bad()
        try:
            decoded = base64.b64decode(text[7:] + '=', validate=True)
        except (ValueError, binascii.Error):
            _bad()
        if (len(decoded) != 32 or
                base64.b64encode(decoded).decode('ascii').rstrip('=') != text[7:] or
                text in result):
            _bad()
        result.append(text)
    return tuple(result)


def _nonsecret_value(key, value):
    if key == 'password':
        # Reject even a supplied redaction-looking string or reference. Never
        # inspect, convert, hash or retain a password/hash in an output record.
        _bad()
    if key == 'public_key_fingerprints':
        return _fingerprints(value)
    if key in ('dns_servers', 'search_domains'):
        if type(value) is not list or len(value) > 16:
            _bad()
        if not value:
            # Observed empty is distinct from absent or patch-action clear.
            return ()
        try:
            patch = normalize_network_patch({key: {'action': 'set', 'value': value}})
        except InvalidNetworkIntent:
            _bad()
        return getattr(patch, key).value
    try:
        patch = normalize_identity_patch({key: {'action': 'set', 'value': value}})
    except InvalidIdentityIntent:
        _bad()
    return getattr(patch, key).value


def _observation(key, value):
    _shape(value, ('state', 'value', 'revision', 'observed_at'), ('state',))
    state = value['state']
    if type(state) is not str or state not in _STATES:
        _bad()
    if state == 'value':
        if 'value' not in value:
            _bad()
        normalized = _nonsecret_value(key, value['value'])
    else:
        if 'value' in value:
            # Even null is not a hidden payload channel or presence default.
            _bad()
        normalized = None
    return ObservedValueData(state, normalized, _revision(value.get('revision')),
                             _observed_at(value.get('observed_at')))


def prepare_field_observations_data(fields):
    """Detach at most seven supplied DNS/identity fields without layer merging.

    Missing layer means unknown, never configured/current fallback or absence.
    An explicit empty observed list survives as a value. Missing whole fields
    are not claimed absent/complete. Provenance/revision/time remain supplied
    metadata, not original read/currentness/permission or guest-application proof.
    Password supports only absent/redacted/unknown; no raw sensitive value.
    """
    if type(fields) is not list or len(fields) > len(_FIELDS):
        _bad()
    rows, seen = [], set()
    for field in fields:
        _shape(field, ('key', 'source', *_LAYERS), ('key',))
        key = field['key']
        if type(key) is not str or key not in _FIELDS or key in seen:
            _bad()
        seen.add(key)
        source_kind, source_revision = 'unknown', None
        if 'source' in field:
            source = field['source']
            _shape(source, ('kind', 'revision'), ('kind',))
            source_kind = source['kind']
            if type(source_kind) is not str or source_kind not in _SOURCES:
                _bad()
            source_revision = _revision(source.get('revision'))
        layers = tuple(_observation(key, field[name]) if name in field else
                       ObservedValueData('unknown', None, None, None)
                       for name in _LAYERS)
        rows.append(FieldObservationData(key, source_kind, source_revision,
                                         key == 'password', *layers))
    # Fixed order helps consumers compare the same supplied subset. There is
    # no status, coverage, approval, effective value or publication predicate.
    return tuple(sorted(rows, key=lambda row: _FIELDS.index(row.key)))
