"""Retained private SQLite utility, not the original journal connector.

The supplied handle stays independently owned. This utility opens no database,
installs no schema and grants no original authority or durable effect receipt.
Exact handle type cannot establish its origin, schema/profile or absence of
ambient SQLite hooks. The actual connector and resource owner remain required.
"""
import sqlite3
import threading

from freq.services import snippet_journal_sql_data as sql


class PrivateJournalTransactionUnavailable(Exception):
    def __init__(self):
        super().__init__('Private journal transaction unavailable')


class PrivateJournalTransactionUnsettled(Exception):
    def __init__(self):
        super().__init__('Private journal transaction unresolved')


def _new_cursor(connection):
    return sqlite3.Connection.cursor(connection, factory=sqlite3.Cursor)


def _execute(cursor, statement, parameters=()):
    return sqlite3.Cursor.execute(cursor, statement, parameters)


def _fetch_one(cursor):
    return sqlite3.Cursor.fetchone(cursor)


def _close_cursor(cursor):
    sqlite3.Cursor.close(cursor)


def _first(first, later):
    # Fixed exception classes inspect the actual type; never consult an
    # exception instance's potentially trapping or spoofed __class__ property.
    if (first is None or
            (issubclass(type(first), Exception) and not issubclass(type(later), Exception)) or
            (issubclass(type(first), Exception) and not issubclass(type(first), MemoryError)
             and issubclass(type(later), MemoryError))):
        return later
    return first


def _expected_schema():
    result = []
    for statement in sql.SCHEMA_STATEMENTS:
        parts = statement.split()
        kind, name = parts[1].lower(), parts[2]
        table = name if kind == 'table' else parts[parts.index('ON') + 1]
        result.append((name, kind, table, statement.strip()))
    return tuple(sorted(result))


_EXPECTED_SCHEMA = _expected_schema()
_TABLE_NAMES = frozenset(row[0] for row in _EXPECTED_SCHEMA if row[1] == 'table')


def _verify_schema(cursor):
    _execute(cursor, "SELECT name,type,tbl_name,sql FROM sqlite_master "
        "WHERE name GLOB 'sj_*' OR tbl_name GLOB 'sj_*' ORDER BY name")
    rows = []
    for _ in range(64):
        row = _fetch_one(cursor)
        if row is None:
            if tuple(sorted(rows)) != _EXPECTED_SCHEMA:
                raise PrivateJournalTransactionUnavailable()
            return
        if type(row) is not tuple or len(row) != 4:
            raise PrivateJournalTransactionUnavailable()
        name, kind, table, statement = row
        if any(type(value) is not str or len(value) > 128 for value in (name, kind, table)):
            raise PrivateJournalTransactionUnavailable()
        if (kind == 'index' and statement is None and table in _TABLE_NAMES
                and name.startswith('sqlite_autoindex_' + table + '_')):
            continue  # SQLite-owned constraint indices, not arbitrary SQL.
        if type(statement) is not str or len(statement) > 16384:
            raise PrivateJournalTransactionUnavailable()
        rows.append(row)
    raise PrivateJournalTransactionUnavailable()


class PrivateJournalSQLiteAttempt:
    """Caller retains this exact pending instance before run; single thread/use.

    Constructor validates fixed inputs and allocates holders only. Imports and
    Python allocation are not asserted resource-free. A lost constructor return
    does not acquire a new SQLite cursor/transaction/connection in this utility.
    """
    __slots__ = ('_connection', '_thread', '_plan', '_started', '_state',
        '_cursor', '_cursor_acquire', '_cursor_close', '_preflight', '_profile',
        '_schema', '_begin', '_writes', '_rowcounts', '_commit', '_rollback', '_failures',
        '_failure')
    __hash__ = None

    def __init__(self, connection, operation, previous, proposed=None):
        if type(self) is not PrivateJournalSQLiteAttempt or hasattr(self, '_connection'):
            raise PrivateJournalTransactionUnavailable()
        if type(connection) is not sqlite3.Connection or type(operation) is not str:
            raise PrivateJournalTransactionUnavailable()
        if operation == 'registration' and proposed is None:
            plan = sql.prepare_registration_sql_data(previous)
        elif operation == 'append' and proposed is not None:
            plan = sql.prepare_append_sql_data(previous, proposed)
        else:
            raise PrivateJournalTransactionUnavailable()
        self._connection = connection
        self._thread = threading.get_ident()
        self._plan = plan
        self._started = False
        self._state = 'prepared'
        self._cursor = None
        self._cursor_acquire = self._cursor_close = 'unused'
        self._preflight = self._profile = self._begin = 'unused'
        self._schema = 'unused'
        self._writes = ['unused'] * len(plan.statements)
        self._rowcounts = [None] * len(plan.statements)
        self._commit = self._rollback = 'unused'
        self._failures = [None] * 3
        self._failure = None

    def __init_subclass__(cls, **kwargs):
        raise TypeError('Private journal attempts cannot be subclassed')

    def __copy__(self):
        raise TypeError('Private journal attempts cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('Private journal attempts cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('Private journal attempts cannot be serialized')

    def _capture(self, index, error):
        self._failures[index] = error
        self._failure = _first(self._failure, error)

    def _emit_failure(self):
        error = self._failure
        if error is not None and (not issubclass(type(error), Exception) or issubclass(type(error), MemoryError)):
            raise error
        if self._state == 'unsettled':
            raise PrivateJournalTransactionUnsettled() from None
        raise PrivateJournalTransactionUnavailable() from None

    def run(self):
        if type(self) is not PrivateJournalSQLiteAttempt:
            raise PrivateJournalTransactionUnavailable()
        if self._started:
            self._emit_failure()  # Never re-enter or replace a retained failure.
        if threading.get_ident() != self._thread:
            raise PrivateJournalTransactionUnavailable()
        self._started = True
        self._state = 'entered'
        try:
            self._preflight = 'entered'
            if (self._connection.in_transaction or self._connection.isolation_level is not None
                    or self._connection.text_factory is not str):
                raise PrivateJournalTransactionUnavailable()
            self._preflight = 'returned'
            self._cursor_acquire = 'entered'
            self._cursor = _new_cursor(self._connection)
            self._cursor_acquire = 'returned'
            # Do not invoke an inherited caller row factory on the PRAGMA read.
            # This does not prove absence of other ambient connection hooks.
            self._cursor.row_factory = None
            self._profile = 'entered'
            _execute(self._cursor, 'PRAGMA foreign_keys')
            if _fetch_one(self._cursor) != (1,):
                raise PrivateJournalTransactionUnavailable()
            self._profile = 'returned'
            self._schema = 'entered'
            _verify_schema(self._cursor)
            self._schema = 'returned'
            self._begin = 'entered'
            _execute(self._cursor, 'BEGIN IMMEDIATE')
            self._begin = 'returned'
            for index, (statement, parameters) in enumerate(self._plan.statements):
                self._writes[index] = 'entered'
                _execute(self._cursor, statement, parameters)
                self._writes[index] = 'returned'
                self._rowcounts[index] = self._cursor.rowcount
                if self._rowcounts[index] != 1:
                    raise PrivateJournalTransactionUnavailable()
            self._commit = 'entered'
            _execute(self._cursor, 'COMMIT')
            self._commit = 'returned'
        except BaseException as error:
            self._capture(0, error)

        # Rollback is one independent cleanup call for a known uncommitted
        # transaction. An entered commit or unobserved begin prohibits it.
        if self._failure is not None and self._begin == 'returned' and self._commit == 'unused':
            self._rollback = 'entered'
            try:
                _execute(self._cursor, 'ROLLBACK')
                self._rollback = 'returned'
            except BaseException as error:
                self._capture(1, error)
        if self._cursor is not None:
            self._cursor_close = 'entered'
            try:
                _close_cursor(self._cursor)
                self._cursor_close = 'returned'
            except BaseException as error:
                self._capture(2, error)

        if self._failure is None:
            self._state = 'committed'
            return None  # Database observation only; no issuer/effect grant.
        unsettled = (self._cursor_acquire == 'entered' or
            self._begin == 'entered' or self._commit == 'entered' or
            self._rollback == 'entered' or self._cursor_close == 'entered')
        self._state = 'unsettled' if unsettled else (
            'committed-with-failure' if self._commit == 'returned' else
            'rolled-back' if self._rollback == 'returned' else 'refused')
        self._emit_failure()


# No connection creation/close, schema installation, callback argument, public
# serializer, provider/content/publication operation or original currentness.
