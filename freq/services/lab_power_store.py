"""Private durable admission for the bounded lab start/shutdown workflow.

Admission commits before granting dispatch. Reopening, replaying, timeout and
uncertain observations never grant another dispatch or release an active target.
The server owns actor derivation, target identity and provider orchestration.
Owned runtime directories are trusted against concurrent replacement by their
owner; symlinks, hardlinks and unsafe existing permissions are refused.
"""
import contextlib
import json
import math
import os
import re
import sqlite3
import stat
import sys
import threading
import time
import uuid


MAX_ROWS = 1024
MAX_DATABASE = 8 * 1024 * 1024
_LOCAL_TRANSACTION = threading.Lock()
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_PHASES = {
    "dispatching": {"dispatching", "acknowledged", "uncertain", "rejected"},
    "acknowledged": {"acknowledged", "running", "succeeded", "failed", "uncertain"},
    "running": {"running", "succeeded", "failed", "uncertain"},
    "uncertain": {"uncertain"},
}
_TERMINAL = {"succeeded", "failed", "rejected"}
_ERRORS = {"credentials_unavailable", "tls_unavailable", "provider_unavailable",
           "invalid_response", "dispatch_rejected", "dispatch_uncertain",
           "task_failed", "task_timeout", "observation_unavailable",
           "registration_changed", "instance_changed", "state_mismatch",
           "store_unavailable", "session_retired"}
_UPDATES = {"phase", "upid", "task_state", "task_exit", "observed_state", "observed_at", "error"}
_COLUMNS = ("id", "actor", "request_key", "registration_revision", "target", "target_slot", "action",
            "expected_state", "phase", "active", "upid", "task_state", "task_exit",
            "observed_state", "observed_at", "error", "version", "created_at", "updated_at")
_SCHEMA = """CREATE TABLE IF NOT EXISTS operations (
id TEXT PRIMARY KEY, actor TEXT NOT NULL, request_key TEXT NOT NULL,
registration_revision TEXT NOT NULL, target TEXT NOT NULL, target_slot TEXT NOT NULL, action TEXT NOT NULL,
expected_state TEXT NOT NULL, phase TEXT NOT NULL, active INTEGER NOT NULL,
upid TEXT, task_state TEXT, task_exit TEXT, observed_state TEXT, observed_at REAL,
error TEXT, version INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
UNIQUE(actor, request_key), CHECK(active IN (0,1)), CHECK(version >= 0))"""


class StoreError(Exception):
    """A fixed code only; underlying file, SQL and caller values stay private."""
    def __init__(self, code="store_unavailable"):
        self.code = code
        super().__init__(code)


def _require(condition, code="invalid_request"):
    if not condition:
        raise StoreError(code)


def _text(value, limit):
    return (type(value) is str and 0 < len(value) <= limit
            and all(33 <= ord(char) <= 126 for char in value))


def _epoch(value):
    return (type(value) in (int, float) and 0 <= value <= 2 ** 53 - 1
            and math.isfinite(value))


def _target_slot(target):
    _require(type(target) is str and len(target) <= 2048)
    try:
        decoded = json.loads(target)
        _require(type(decoded) is dict and json.dumps(decoded, sort_keys=True, separators=(",", ":"),
                                                    allow_nan=False) == target)
        return json.dumps({key: value for key, value in decoded.items() if key != "instance_uuid"},
                          sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise StoreError("invalid_request") from None


def _safe(info, directory=False):
    _require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
             and info.st_uid == os.geteuid() and not info.st_mode & 0o077
             and (directory or info.st_nlink == 1), "store_unavailable")


class LabPowerStore:
    def __init__(self, data_dir):
        try:
            base = os.fspath(data_dir)
            _require(type(base) is str and "\x00" not in base and os.path.isabs(base)
                     and os.path.normpath(base) == base
                     and os.path.realpath(base, strict=True) == base, "store_unavailable")
            parent = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                info = os.fstat(parent)
                _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid(), "store_unavailable")
                try:
                    os.mkdir("lab-power", 0o700, dir_fd=parent)
                    os.fsync(parent)
                except FileExistsError:
                    pass
                directory = os.open("lab-power", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    _safe(os.fstat(directory), directory=True)
                finally:
                    os.close(directory)
            finally:
                os.close(parent)
            self.path = os.path.join(base, "lab-power", "operations.sqlite3")
            with self._transaction() as connection:
                connection.execute(_SCHEMA)
                # This unreleased schema never migrates or clears old records.
                _require(tuple(row[1] for row in connection.execute("PRAGMA table_info(operations)"))
                         == _COLUMNS, "store_unavailable")
                connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_target_slot ON operations(target_slot) WHERE active=1")
        except MemoryError:
            raise
        except StoreError:
            raise
        except (OSError, ValueError, TypeError, sqlite3.Error):
            raise StoreError() from None

    @contextlib.contextmanager
    def _transaction(self):
        # SQLite schema/pragma setup can collide before BEGIN IMMEDIATE. Admit
        # one in-process transaction without waiting; another request fails
        # closed, while SQLite still arbitrates independent processes.
        if not _LOCAL_TRANSACTION.acquire(blocking=False):
            raise StoreError()
        try:
            with self._transaction_unlocked() as connection:
                yield connection
        finally:
            _LOCAL_TRANSACTION.release()

    @contextlib.contextmanager
    def _transaction_unlocked(self):
        connection = None
        directory = file_fd = None
        try:
            directory_path = os.path.dirname(self.path)
            _require(os.path.realpath(directory_path, strict=True) == directory_path, "store_unavailable")
            directory = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            _safe(os.fstat(directory), directory=True)
            try:
                file_fd = os.open("operations.sqlite3", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  0o600, dir_fd=directory)
                os.fsync(file_fd)
                os.fsync(directory)
            except FileExistsError:
                file_fd = os.open("operations.sqlite3", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            info = os.fstat(file_fd)
            _safe(info)
            _require(info.st_size <= MAX_DATABASE, "capacity_exceeded")
            for suffix in ("-journal", "-wal", "-shm"):
                try:
                    sidecar = os.stat("operations.sqlite3" + suffix, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                _safe(sidecar)
                _require(sidecar.st_size <= MAX_DATABASE, "capacity_exceeded")
            connection = sqlite3.connect(self.path, timeout=0, isolation_level=None)
            current = os.stat("operations.sqlite3", dir_fd=directory, follow_symlinks=False)
            _require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), "store_unavailable")
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=0")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            _require(connection.execute("PRAGMA page_size").fetchone()[0] == 4096,
                     "store_unavailable")
            connection.execute("PRAGMA max_page_count=2048")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except MemoryError:
            raise
        except StoreError:
            raise
        except (OSError, ValueError, TypeError, sqlite3.Error):
            raise StoreError() from None
        finally:
            pending = sys.exc_info()[0] is not None
            failed = False
            for handle, close in ((connection, lambda value: value.close()),
                                  (file_fd, os.close), (directory, os.close)):
                if handle is not None:
                    try:
                        close(handle)
                    except (OSError, sqlite3.Error):
                        failed = True
            if failed and not pending:
                raise StoreError() from None

    def admit(self, actor, request_key, registration_revision, target, action, expected_state):
        _require(type(actor) is str and _HASH.fullmatch(actor))
        _require(_text(request_key, 128))
        _require(type(registration_revision) is str and _HASH.fullmatch(registration_revision))
        target_slot = _target_slot(target)
        _require(action in ("start", "shutdown") and expected_state in ("running", "stopped"))
        parameters = (registration_revision, target, action, expected_state)
        with self._transaction() as connection:
            previous = connection.execute("SELECT * FROM operations WHERE actor=? AND request_key=?",
                                          (actor, request_key)).fetchone()
            if previous is not None:
                _require(tuple(previous[key] for key in ("registration_revision", "target", "action", "expected_state"))
                         == parameters, "request_conflict")
                result, dispatch = dict(previous), False
            else:
                _require(connection.execute("SELECT 1 FROM operations WHERE target_slot=? AND active=1", (target_slot,)).fetchone()
                         is None, "target_busy")
                _require(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] < MAX_ROWS,
                         "capacity_exceeded")
                timestamp = time.time()
                _require(_epoch(timestamp), "store_unavailable")
                operation_id = uuid.uuid4().hex
                values = (operation_id, actor, request_key, registration_revision, target, target_slot,
                          action, expected_state, "dispatching", 1,
                          None, None, None, None, None, None, 0, timestamp, timestamp)
                connection.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
                result, dispatch = dict(zip(_COLUMNS, values)), True
        return result, dispatch

    def active_for_target(self, target):
        """Trusted internal lookup by logical slot; public callers need projection.

        The returned row may belong to a different actor or an older instance.
        This is busy-state evidence only, never a dispatch or read grant.
        """
        target_slot = _target_slot(target)
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM operations WHERE target_slot=? AND active=1",
                                     (target_slot,)).fetchone()
            result = dict(row) if row is not None else None
        return result

    def get(self, operation_id, actor):
        _require(type(operation_id) is str and _ID.fullmatch(operation_id))
        _require(type(actor) is str and _HASH.fullmatch(actor))
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM operations WHERE id=? AND actor=?", (operation_id, actor)).fetchone()
            _require(row is not None, "not_found")
            result = dict(row)
        return result

    def update(self, operation_id, actor, expected_version, **fields):
        _require(type(operation_id) is str and _ID.fullmatch(operation_id))
        _require(type(actor) is str and _HASH.fullmatch(actor))
        _require(type(expected_version) is int and 0 <= expected_version < 2 ** 53 - 1)
        _require(bool(fields) and not set(fields) - _UPDATES)
        if "upid" in fields:
            _require(fields["upid"] is None or _text(fields["upid"], 512))
        for name in ("task_state", "observed_state"):
            if name in fields:
                _require(fields[name] is None or fields[name] in ("running", "stopped", "unknown"))
        if "task_exit" in fields:
            _require(fields["task_exit"] in (None, "OK", "failed", "unknown"))
        if "error" in fields:
            _require(fields["error"] is None or
                     type(fields["error"]) is str and fields["error"] in _ERRORS)
        if "phase" in fields:
            _require(type(fields["phase"]) is str)
        if "observed_at" in fields:
            _require(fields["observed_at"] is None or _epoch(fields["observed_at"]))
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM operations WHERE id=? AND actor=?", (operation_id, actor)).fetchone()
            _require(row is not None, "not_found")
            _require(row["version"] == expected_version, "stale_version")
            phase = fields.get("phase", row["phase"])
            _require(row["phase"] in _PHASES and phase in _PHASES[row["phase"]], "invalid_transition")
            if row["upid"] is not None and "upid" in fields:
                _require(fields["upid"] == row["upid"], "upid_conflict")
            result = dict(row)
            result.update(fields)
            result.update(active=int(phase not in _TERMINAL), version=expected_version + 1,
                          updated_at=max(row["updated_at"], time.time()))
            _require(_epoch(result["updated_at"]), "store_unavailable")
            connection.execute("UPDATE operations SET phase=?,active=?,upid=?,task_state=?,task_exit=?,observed_state=?,observed_at=?,error=?,version=?,updated_at=? WHERE id=? AND actor=? AND version=?",
                               tuple(result[key] for key in ("phase", "active", "upid", "task_state", "task_exit", "observed_state", "observed_at", "error", "version", "updated_at"))
                               + (operation_id, actor, expected_version))
        return result
