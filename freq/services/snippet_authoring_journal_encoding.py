"""Restricted authoring journal storage bytes, never public output or authority.

This explicit format is separate from generic object serialization. It has no
IO, database, connection, transaction, effect or reference issuance operation.
Returned bytes contain private reference metadata: do not log or export them.
Input/encoded bounds do not establish a physical memory or durability profile.
"""
import json

from freq.services.snippet_authoring_journal_data import (
    normalize_authoring_journal_record_data,
    validate_authoring_journal_append_data,
)

_SCHEMA = 'snippet-authoring-journal-v1'
_MAX_BYTES = 65536
_MAX_DEPTH = 8


class InvalidPrivateJournalEncoding(ValueError):
    """Fixed diagnostic with no submitted body or exception text."""


def _bad():
    raise InvalidPrivateJournalEncoding('Invalid private journal encoding') from None


def _record_document(record):
    # Only fixed-normalizer output reaches this explicit field projection.
    # No asdict, __dict__, pickle, repr, user encoder or serializer callback.
    version = record.version
    return dict(kind=record.kind, installation_id=record.installation_id,
        operation_id=record.operation_id, snapshot_id=record.snapshot_id,
        bindings=dict(record.bindings),
        version=dict(estate_id=version.estate_id, storage_id=version.storage_id,
            storage_incarnation=version.storage_incarnation,
            volume_id=version.volume_id, content_kind=version.content_kind,
            revision=version.revision, sha256=version.sha256, size=version.size,
            node_coverage=[dict(node_id=row.node_id,
                node_incarnation=row.node_incarnation,
                storage_incarnation=row.storage_incarnation, state=row.state,
                source_revision=row.source_revision, observed_at=row.observed_at)
                for row in version.node_coverage]),
        events=[dict(event=row.event, persistence=row.persistence,
            **(dict(boundary=row.boundary, outcome=row.outcome)
               if row.event == 'late-outcome' else {})) for row in record.events])


def _encoded(record):
    body = json.dumps(dict(schema=_SCHEMA, record=_record_document(record)),
        ensure_ascii=True, allow_nan=False, sort_keys=True,
        separators=(',', ':')).encode('ascii')
    if len(body) > _MAX_BYTES:
        _bad()
    return body


def encode_private_authoring_record(value):
    """Normalize an exact built-in document and encode restricted metadata.

    Constructed private DATA objects cannot bypass the fixed normalizer. All
    classified facts remain supplied DATA, including confirmed/unknown events.
    No original failure object, credential, content, clock or grant is stored.
    """
    return _encoded(normalize_authoring_journal_record_data(value))


def _check_depth(body):
    depth = 0
    quoted = escaped = False
    for byte in body:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > _MAX_DEPTH:
                _bad()
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                _bad()
    if depth != 0 or quoted:
        _bad()


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            _bad()
        result[key] = value
    return result


def _constant(value):
    _bad()


def _decoded_document(body):
    if type(body) is not bytes or not 1 <= len(body) <= _MAX_BYTES:
        _bad()
    _check_depth(body)
    failed = False
    try:
        value = json.loads(body.decode('ascii'), object_pairs_hook=_pairs,
            parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        failed = True
    # Raise after leaving the parser exception handler: do not retain a JSON
    # error as context with a submitted document in its .doc attribute.
    if failed:
        _bad()
    if (type(value) is not dict or set(value) != {'schema', 'record'} or
            type(value['schema']) is not str or value['schema'] != _SCHEMA):
        _bad()
    record = normalize_authoring_journal_record_data(value['record'])
    if _encoded(record) != body:
        _bad()  # One exact representation; no alternate spelling or version.
    return value['record'], record


def decode_private_authoring_record(body):
    """Return detached historical DATA; restore no live/recovery permission."""
    return _decoded_document(body)[1]


def validate_private_encoded_append(previous, proposed):
    """Check full predecessor/one append, without an atomic database claim."""
    before, _ = _decoded_document(previous)
    after, _ = _decoded_document(proposed)
    return validate_authoring_journal_append_data(before, after)
