"""Private authoring journal DATA; no journal, IO, CAS transaction or issuer.

Confirmed/observed classifications are supplied facts, not receipts or grants.
This validator cannot prove original provenance, persistence, currentness,
concurrency, content custody, readback, delivery or physical closure. It neither
serializes restricted metadata nor selects a database/adapter/clock/resource.
"""
from dataclasses import dataclass
import re

from freq.services.cloud_init_snippet_intent import normalize_snippet_reference_data


_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_BINDINGS = frozenset(('installation', 'actor', 'storage', 'target', 'writer',
                       'source', 'lifetime', 'recipient'))
_FIELDS = frozenset(('kind', 'installation_id', 'operation_id', 'snapshot_id',
                     'bindings', 'version', 'events'))
_KIND = 'new-content-authoring'
_MAX_EVENTS = 32  # Private DATA bound, never a reserved journal/storage quota.
_NEXT = {
    None: ('registered',),
    'registered': ('write-intent',),
    'write-intent': ('write-observed', 'write-failed', 'write-unknown'),
    'write-observed': ('readback-intent',),
    'readback-intent': ('readback-verified', 'readback-failed', 'readback-unknown'),
    'readback-verified': ('publication-intent',),
    'publication-intent': ('published', 'publication-failed', 'publication-unknown'),
    'published': ('reply-intent',),
    'reply-intent': ('reply-observed', 'reply-unknown'),
}
_INTENTS = {'write-intent': 'write', 'readback-intent': 'readback',
            'publication-intent': 'publication', 'reply-intent': 'reply'}
_TERMINAL_UNCERTAIN = frozenset(('write-unknown', 'readback-unknown',
                               'publication-unknown', 'reply-unknown'))


class InvalidSnippetJournalData(ValueError):
    """Fixed error; contains no submitted metadata or exception formatting."""


def _bad():
    raise InvalidSnippetJournalData('Invalid private authoring journal data') from None


def _shape(value, fields):
    if (type(value) is not dict or len(value) != len(fields) or
            any(type(key) is not str for key in value) or set(value) != fields):
        _bad()


def _token(value):
    if type(value) is not str or not 1 <= len(value) <= 128 or not _TOKEN.fullmatch(value):
        _bad()
    return value


@dataclass(frozen=True, slots=True, repr=False)
class JournalEventData:
    event: str
    persistence: str
    boundary: object = None
    outcome: object = None
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private journal data cannot be serialized')


@dataclass(frozen=True, slots=True, repr=False)
class AuthoringJournalRecordData:
    kind: str
    installation_id: str
    operation_id: str
    snapshot_id: str
    bindings: tuple
    version: object
    events: tuple
    phase: object
    retired: bool
    recovery_only: bool
    uncertain: bool
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private journal data cannot be serialized')


def _event(value):
    if type(value) is not dict:
        _bad()
    # Validate keys before reading any possibly sensitive extra value.
    if (len(value) not in (2, 4) or any(type(key) is not str for key in value)):
        _bad()
    keys = set(value)
    if keys not in ({'event', 'persistence'}, {'event', 'persistence', 'boundary', 'outcome'}):
        _bad()
    name, persistence = value['event'], value['persistence']
    if type(name) is not str or len(name) > 32 or type(persistence) is not str:
        _bad()
    if persistence not in ('confirmed', 'unknown'):
        _bad()
    if name == 'late-outcome':
        if len(value) != 4:
            _bad()
        boundary, outcome = value['boundary'], value['outcome']
        if (type(boundary) is not str or boundary not in ('write', 'readback', 'publication', 'reply') or
                type(outcome) is not str or outcome not in ('observed', 'ordinary-failure', 'unknown')):
            _bad()
        return JournalEventData(name, persistence, boundary, outcome)
    if len(value) != 2 or name not in frozenset(_NEXT) | frozenset(
            item for values in _NEXT.values() for item in values) | {'retire', 'restart'}:
        _bad()
    return JournalEventData(name, persistence)


def _history(values):
    if type(values) is not list or not 1 <= len(values) <= _MAX_EVENTS:
        _bad()
    result = []
    phase = None
    retired = recovery = uncertain = False
    intents, late_facts = set(), set()
    for raw in values:
        fact = _event(raw)
        name = fact.event
        if name == 'retire':
            if not result or retired:
                _bad()
            retired = True
        elif name == 'restart':
            if not result or recovery:
                _bad()
            recovery = True
        elif name == 'late-outcome':
            if (not (retired or recovery or uncertain) or fact.boundary not in intents or
                    (fact.boundary, fact.outcome) in late_facts):
                _bad()
            # Preserve distinct late classifications; never erase the original
            # unknown/retired state or turn a late fact into phase progress.
            late_facts.add((fact.boundary, fact.outcome))
        else:
            if retired or recovery or uncertain or name not in _NEXT.get(phase, ()):
                _bad()
            # An unknown commit records intent/uncertainty only, not completion
            # of the proposed phase or a permission to repeat it.
            if fact.persistence == 'confirmed':
                phase = name
                if name in _INTENTS:
                    intents.add(_INTENTS[name])
                if name in _TERMINAL_UNCERTAIN:
                    uncertain = True
        if fact.persistence == 'unknown':
            uncertain = True
        result.append(fact)
    return tuple(result), phase, retired, recovery, uncertain


def normalize_authoring_journal_record_data(value):
    """Detach one bounded history; all classified facts remain untrusted DATA.

    Callers cannot pass a constructed dataclass to bypass normalization. This
    is not an original record loader, persistent registry or recovery executor.
    Exceptions from the fixed reference normalizer propagate without fallback.
    """
    _shape(value, _FIELDS)
    kind = value['kind']
    if type(kind) is not str or kind != _KIND:
        _bad()  # Selection/recovery refused before phase or nested values.
    installation = _token(value['installation_id'])
    operation = _token(value['operation_id'])
    snapshot = _token(value['snapshot_id'])
    bindings = value['bindings']
    _shape(bindings, _BINDINGS)
    detached_bindings = tuple((key, _token(bindings[key])) for key in sorted(_BINDINGS))
    version = normalize_snippet_reference_data(value['version'])
    events, phase, retired, recovery, uncertain = _history(value['events'])
    return AuthoringJournalRecordData(kind, installation, operation, snapshot,
        detached_bindings, version, events, phase, retired, recovery, uncertain)


def validate_authoring_journal_append_data(previous, proposed):
    """Require one exact append and unchanged immutable metadata, without IO.

    Complete predecessor comparison is a DATA consistency check, not an atomic
    transaction or proof that the predecessor is the current durable record.
    Actual original journal must separately enforce compare-and-append under
    its selected concurrency/durability/custody profile. No effect grant returns.
    """
    before = normalize_authoring_journal_record_data(previous)
    after = normalize_authoring_journal_record_data(proposed)
    if (before.kind != after.kind or before.installation_id != after.installation_id or
            before.operation_id != after.operation_id or before.snapshot_id != after.snapshot_id or
            before.bindings != after.bindings or before.version != after.version or
            len(after.events) != len(before.events) + 1 or after.events[:-1] != before.events):
        _bad()
    return after


# No database/schema/connection, serialization, content, clock, callback,
# original authority/currentness, reference issuance, IO or effect operation.
