"""One private journal metadata snapshot, without reconciliation authority.

No connection creation, schema installation, provider call or retry. The actual
connector must independently establish database incarnation/profile and retain
its supplied handle. Returned rows are historical DATA, never a resume grant.
"""
from dataclasses import dataclass
import re
import sqlite3
import threading

from freq.services import snippet_journal_sql_attempt as transaction
from freq.services import snippet_authoring_journal_encoding as codec


_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_BLOB = "CASE WHEN typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 65536 THEN payload ELSE NULL END"
_INITIAL = "CASE WHEN typeof(initial_payload)='blob' AND length(initial_payload) BETWEEN 1 AND 65536 THEN initial_payload ELSE NULL END"
_TEXT_FIELDS = ('estate_id', 'storage_id', 'storage_incarnation', 'volume_id', 'content_kind', 'revision')
_CLAIM = ','.join("CASE WHEN typeof(" + name + ")='text' AND length(CAST(" + name + " AS BLOB)) BETWEEN 1 AND 512 THEN " + name + " ELSE NULL END" for name in _TEXT_FIELDS)
_SEQUENCE = "CASE WHEN typeof(sequence)='integer' AND sequence BETWEEN 1 AND 32 THEN sequence ELSE NULL END"
_HEAD = 'SELECT ' + _SEQUENCE + ',' + _BLOB + ' FROM sj_heads WHERE installation_id=? AND operation_id=?'
_HISTORY = 'SELECT ' + _SEQUENCE + ',' + _BLOB + ' FROM sj_history WHERE installation_id=? AND operation_id=? ORDER BY sequence LIMIT 33'
_ROOT = 'SELECT ' + _SEQUENCE + ',' + _BLOB + ' FROM sj_registration_roots WHERE installation_id=? AND operation_id=?'
_VERSION = 'SELECT ' + _CLAIM + ',' + _INITIAL + ' FROM sj_version_claims WHERE installation_id=? AND operation_id=?'


class PrivateJournalReadUnavailable(Exception):
    def __init__(self):
        super().__init__('Private journal read unavailable')


class PrivateJournalReadUnsettled(Exception):
    def __init__(self):
        super().__init__('Private journal read unresolved')


def _bad():
    raise PrivateJournalReadUnavailable() from None


@dataclass(frozen=True, slots=True, repr=False)
class PrivateJournalSnapshotData:
    # Immutable byte tuples, not live authority or a complete database audit.
    installation_id: str
    operation_id: str
    history: tuple
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private journal snapshots cannot be serialized')


def _bounded_text(name, limit):
    return ("CASE WHEN typeof(" + name + ")='text' AND length(CAST(" + name +
            " AS BLOB)) BETWEEN 1 AND " + str(limit) + " THEN " + name + " ELSE NULL END")


# Fixed projection only: invalid SQL NULL must not impersonate a legitimate
# SQLite-owned automatic-index NULL. The separate state retains that distinction.
_SCHEMA_FIELDS = ','.join(_bounded_text(name, 128) for name in ('name','type','tbl_name'))
_SQL_VALID = "typeof(sql)='text' AND length(CAST(sql AS BLOB)) BETWEEN 1 AND 16384"
_SCHEMA_QUERY = ('SELECT ' + _SCHEMA_FIELDS +
    ',CASE WHEN sql IS NULL THEN 0 WHEN ' + _SQL_VALID + ' THEN 1 ELSE 2 END,' +
    _bounded_text('sql', 16384) +
    " FROM sqlite_master WHERE name GLOB 'sj_*' OR tbl_name GLOB 'sj_*' ORDER BY name")


def _verify_bounded_schema(cursor):
    transaction._execute(cursor, _SCHEMA_QUERY)
    rows = []
    for _ in range(64):
        row = transaction._fetch_one(cursor)
        if row is None:
            if tuple(sorted(rows)) != transaction._EXPECTED_SCHEMA:
                _bad()
            return
        if type(row) is not tuple or len(row) != 5:
            _bad()
        name, kind, table, state, statement = row
        if any(type(value) is not str for value in (name,kind,table)) or type(state) is not int:
            _bad()
        if (state == 0 and statement is None and kind == 'index'
                and table in transaction._TABLE_NAMES
                and name.startswith('sqlite_autoindex_' + table + '_')):
            continue
        if state != 1 or type(statement) is not str:
            _bad()
        rows.append((name,kind,table,statement))
    _bad()


def _one(cursor, statement, key):
    transaction._execute(cursor, statement, key)
    row = transaction._fetch_one(cursor)
    if transaction._fetch_one(cursor) is not None:
        _bad()
    return row


def _record(row, sequence, key):
    if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not int
            or row[0] != sequence or type(row[1]) is not bytes):
        _bad()
    record = codec.decode_private_authoring_record(row[1])
    if ((record.installation_id, record.operation_id) != key
            or len(record.events) != sequence):
        _bad()
    return record


def _read_snapshot(cursor, key):
    head = _one(cursor, _HEAD, key)
    transaction._execute(cursor, _HISTORY, key)
    rows = []
    for _ in range(33):
        row = transaction._fetch_one(cursor)
        if row is None:
            break
        rows.append(row)
    root = _one(cursor, _ROOT, key)
    claim = _one(cursor, _VERSION, key)
    if head is None:
        if rows or root is not None or claim is not None:
            _bad()
        return PrivateJournalSnapshotData(*key, ())
    if not 1 <= len(rows) <= 32:
        _bad()
    current = _record(head, len(rows), key)
    previous = None
    payloads = []
    for sequence, row in enumerate(rows, 1):
        record = _record(row, sequence, key)
        if previous is None:
            if record.events[0].event != 'registered':
                _bad()
        else:
            codec.validate_private_encoded_append(previous, row[1])
        previous = row[1]
        payloads.append(previous)
    if head != rows[-1] or root != rows[0]:
        _bad()
    version = current.version
    expected = (version.estate_id, version.storage_id, version.storage_incarnation,
                version.volume_id, version.content_kind, version.revision, rows[0][1])
    if type(claim) is not tuple or claim != expected:
        _bad()
    return PrivateJournalSnapshotData(*key, tuple(payloads))


class PrivateJournalSnapshotAttempt:
    """Retain before run. A failed/unknown read never refunds original duties."""
    __slots__ = ('_connection', '_key', '_thread', '_started', '_state', '_cursor',
                 '_cursor_acquire', '_cursor_close', '_begin', '_end', '_read',
                 '_snapshot', '_failures', '_failure')
    __hash__ = None

    def __init__(self, connection, installation_id, operation_id):
        if (type(self) is not PrivateJournalSnapshotAttempt or hasattr(self, '_connection')
                or type(connection) is not sqlite3.Connection):
            _bad()
        for value in (installation_id, operation_id):
            if type(value) is not str or not _TOKEN.fullmatch(value):
                _bad()
        self._connection = connection
        self._key = (installation_id, operation_id)
        self._thread = threading.get_ident()
        self._started = False
        self._state = 'prepared'
        self._cursor = None
        self._cursor_acquire = self._cursor_close = 'unused'
        self._begin = self._end = self._read = 'unused'
        self._snapshot = None
        self._failures = [None] * 3
        self._failure = None

    def __init_subclass__(cls, **kwargs):
        raise TypeError('Private journal reads cannot be subclassed')

    def __copy__(self):
        raise TypeError('Private journal reads cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('Private journal reads cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('Private journal reads cannot be serialized')

    def _capture(self, index, error):
        self._failures[index] = error
        self._failure = transaction._first(self._failure, error)

    def _emit(self):
        error = self._failure
        if error is not None and (not issubclass(type(error), Exception)
                                  or issubclass(type(error), MemoryError)):
            raise error
        if self._state == 'unsettled':
            raise PrivateJournalReadUnsettled() from None
        raise PrivateJournalReadUnavailable() from None

    def run(self):
        if type(self) is not PrivateJournalSnapshotAttempt:
            _bad()
        if self._started:
            self._emit()
        if threading.get_ident() != self._thread:
            _bad()
        self._started = True
        self._state = 'entered'
        try:
            if (self._connection.in_transaction or self._connection.isolation_level is not None
                    or self._connection.text_factory is not str):
                _bad()
            self._cursor_acquire = 'entered'
            self._cursor = transaction._new_cursor(self._connection)
            self._cursor_acquire = 'returned'
            self._cursor.row_factory = None
            transaction._execute(self._cursor, 'PRAGMA foreign_keys')
            if transaction._fetch_one(self._cursor) != (1,):
                _bad()
            transaction._execute(self._cursor, 'PRAGMA read_uncommitted')
            if transaction._fetch_one(self._cursor) != (0,):
                _bad()
            self._begin = 'entered'
            transaction._execute(self._cursor, 'BEGIN')
            self._begin = 'returned'
            # Schema and rows share this read transaction. This is still no
            # original database incarnation or exclusive-writer profile proof.
            _verify_bounded_schema(self._cursor)
            self._read = 'entered'
            self._snapshot = _read_snapshot(self._cursor, self._key)
            self._read = 'returned'
        except BaseException as error:
            self._capture(0, error)
        if self._begin == 'returned':
            self._end = 'entered'
            try:
                # End the known read-only transaction, never a retry/write.
                transaction._execute(self._cursor, 'ROLLBACK')
                self._end = 'returned'
            except BaseException as error:
                self._capture(1, error)
        if self._cursor is not None:
            self._cursor_close = 'entered'
            try:
                transaction._close_cursor(self._cursor)
                self._cursor_close = 'returned'
            except BaseException as error:
                self._capture(2, error)
        if self._failure is not None:
            self._state = 'unsettled' if ('entered' in (self._cursor_acquire,
                self._begin, self._end, self._cursor_close)) else 'refused'
            self._emit()
        self._state = 'observed'
        return self._snapshot
