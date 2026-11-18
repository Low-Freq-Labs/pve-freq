"""Private immutable snippet reference/intents, without storage or authority.

Supplied identifiers, revisions, digests, sizes and coverage are DATA only.
No content, path, provider lookup, native owner, write, approval or public wire
serialization is implemented. All referenced content remains potentially
sensitive and executable. A trusted Python caller can access fields; hidden
repr and blocked hash/pickle are not memory secrecy or an authority boundary.
"""
from dataclasses import dataclass
import math
import re

_KINDS = ('user', 'vendor', 'meta', 'network')
_REFERENCE_FIELDS = frozenset(('estate_id', 'storage_id', 'storage_incarnation',
    'volume_id', 'content_kind', 'revision', 'sha256', 'size', 'node_coverage'))
_COVERAGE_FIELDS = frozenset(('node_id', 'node_incarnation', 'storage_incarnation',
    'state', 'source_revision', 'observed_at'))
_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_REFUSAL = 'Invalid private snippet intent'


class InvalidSnippetIntent(ValueError):
    """Fixed diagnostic without submitted reference or content values."""


def _bad():
    raise InvalidSnippetIntent(_REFUSAL) from None


def _shape(value, allowed, required):
    # Check names before accessing even one possibly content-bearing value.
    if (type(value) is not dict or len(value) > len(allowed) or
            any(type(key) is not str for key in value) or
            not required <= value.keys() <= allowed):
        _bad()


def _token(value):
    if type(value) is not str or not 1 <= len(value) <= 128 or _TOKEN.fullmatch(value) is None:
        _bad()
    return value


@dataclass(frozen=True, slots=True, repr=False)
class SnippetCoverageData:
    node_id: str
    node_incarnation: str
    storage_incarnation: str
    state: str
    source_revision: object
    observed_at: object
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private snippet metadata cannot be serialized')


@dataclass(frozen=True, slots=True, repr=False)
class SnippetReferenceData:
    estate_id: str
    storage_id: str
    storage_incarnation: str
    volume_id: str
    content_kind: str
    revision: str
    sha256: str
    size: int
    node_coverage: tuple
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private snippet metadata cannot be serialized')


@dataclass(frozen=True, slots=True, repr=False)
class SnippetFieldPatch:
    action: str
    value: object
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private snippet metadata cannot be serialized')


@dataclass(frozen=True, slots=True, repr=False)
class SnippetPatchData:
    user: SnippetFieldPatch
    vendor: SnippetFieldPatch
    meta: SnippetFieldPatch
    network: SnippetFieldPatch
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private snippet metadata cannot be serialized')


_RETAIN = SnippetFieldPatch('retain', None)


def normalize_snippet_reference_data(value):
    """Detach bounded exact reference metadata; never issue a storage receipt."""
    _shape(value, _REFERENCE_FIELDS, _REFERENCE_FIELDS)
    estate = _token(value['estate_id'])
    storage = _token(value['storage_id'])
    incarnation = _token(value['storage_incarnation'])
    volume = _token(value['volume_id'])
    revision = _token(value['revision'])
    kind, digest, size = value['content_kind'], value['sha256'], value['size']
    if (type(kind) is not str or kind not in _KINDS or
            type(digest) is not str or len(digest) != 64 or _DIGEST.fullmatch(digest) is None or
            type(size) is not int or not 0 <= size <= 2097152):
        _bad()
    rows = value['node_coverage']
    if type(rows) is not list or len(rows) > 64:
        _bad()
    seen, coverage = set(), []
    for row in rows:
        _shape(row, _COVERAGE_FIELDS, _COVERAGE_FIELDS)
        node = _token(row['node_id'])
        node_incarnation = _token(row['node_incarnation'])
        row_storage = _token(row['storage_incarnation'])
        identity = (node, node_incarnation)
        if identity in seen or row_storage != incarnation:
            _bad()
        seen.add(identity)
        state, source, observed = row['state'], row['source_revision'], row['observed_at']
        if type(state) is not str or state not in ('present', 'unavailable', 'unknown'):
            _bad()
        if state == 'unknown':
            if source is not None or observed is not None:
                _bad()
        else:
            source = _token(source)
            if type(observed) is not float or not math.isfinite(observed) or observed <= 0:
                _bad()
        coverage.append(SnippetCoverageData(node, node_incarnation, row_storage,
            state, source, observed))
    return SnippetReferenceData(estate, storage, incarnation, volume, kind,
        revision, digest, size, tuple(coverage))


def normalize_snippet_patch_data(value):
    """Omission retains unobserved prior state; actions grant no write/delete."""
    _shape(value, frozenset(_KINDS), frozenset())
    result = []
    for kind in _KINDS:
        if kind not in value:
            result.append(_RETAIN)
            continue
        field = value[kind]
        _shape(field, frozenset(('action', 'value')), frozenset(('action',)))
        action = field['action']
        if type(action) is not str or action not in ('retain', 'set', 'clear', 'inherit'):
            _bad()
        if action == 'set':
            if 'value' not in field:
                _bad()
            reference = normalize_snippet_reference_data(field['value'])
            if reference.content_kind != kind:
                _bad()
            result.append(SnippetFieldPatch(action, reference))
        else:
            if 'value' in field:
                _bad()
            result.append(_RETAIN if action == 'retain' else SnippetFieldPatch(action, None))
    return SnippetPatchData(*result)


# No generic serializers/loggers or combined network/identity preparation.
# Constructors remain caller-constructible DATA, never evidence of provenance.
