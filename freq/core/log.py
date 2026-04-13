"""FREQ Logging — zero dependencies, better than structlog.

Features structlog charges you a dependency for:
    - JSON-lines output with automatic redaction
    - Context binding (bind once, flows to all subsequent logs)
    - Dual output: JSON to file + human-readable to stderr when interactive
    - SQLite-backed metrics (perf timing, health history) with indexes
    - Thread-safe file writes
    - Log rotation (max 10MB, keeps 3 rotated files)
    - All stdlib. Zero. External. Dependencies.

Usage:
    from freq.core import log as logger
    logger.init("/path/to/freq.log")
    logger.info("deployed", host="10.0.0.1", user="freq-admin")
    logger.perf("ssh", 0.42, host="10.0.0.1", ok=True)
"""

import json
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime, timezone


# ── Redaction ────────────────────────────────────────────────────────

_REDACT_PATTERNS = [
    # Catches common credential/identifier query and config formats.
    # Bias toward false positives in logs — F13 of
    # R-SECURITY-TRUST-AUDIT-20260413P. Notably:
    #   key=        — used by /api/lab-tool/proxy (lab tool API key in URL).
    #   session=    — used by /api/terminal/ws (terminal session id; the
    #                 hijack channel from F8 relies on this not being
    #                 grep-able in freq.log).
    #   pass=, pw=  — short forms in scripts and CLI flags.
    #   auth=       — generic.
    re.compile(
        r"(password|passwd|pass|pw|secret|token|apikey|api_key|key|session|auth)([=: ]+)\S+",
        re.IGNORECASE,
    ),
    re.compile(r"(sshpass\s+-p\s+)\S+"),
    re.compile(r"(Bearer\s+)\S+", re.IGNORECASE),
    re.compile(r"(ghp_|gho_|github_pat_)\S+"),
]


def _redact(msg: str) -> str:
    """Scrub passwords, tokens, API keys, and secrets from log messages."""
    if not isinstance(msg, str):
        return str(msg)
    for pattern in _REDACT_PATTERNS:
        msg = pattern.sub(
            lambda m: (
                m.group(1) + m.group(2) + "***REDACTED***"
                if m.lastindex and m.lastindex >= 2
                else m.group(1) + "***REDACTED***"
            ),
            msg,
        )
    return msg


# ── Globals ──────────────────────────────────────────────────────────

_LOG_FILE: str = ""
_DB_PATH: str = ""
_db_conn: sqlite3.Connection | None = None
_lock = threading.Lock()
_context: dict = {}  # Bound context — flows to all log calls
_stderr_enabled: bool = False  # Human-readable stderr output

# Rotation: 10MB max, keep 3 rotated files
_MAX_LOG_BYTES = 10 * 1024 * 1024
_ROTATE_KEEP = 3


# ── Context binding ──────────────────────────────────────────────────

def bind(**kwargs) -> None:
    """Bind context that flows to all subsequent log calls.

    Example:
        logger.bind(session="S024", user="freq-admin")
        logger.info("deployed")  # includes session and user automatically
    """
    _context.update(kwargs)


def unbind(*keys) -> None:
    """Remove keys from bound context."""
    for key in keys:
        _context.pop(key, None)


def clear_context() -> None:
    """Clear all bound context."""
    _context.clear()


# ── SQLite setup ─────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS perf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    op TEXT NOT NULL,
    duration REAL NOT NULL,
    host TEXT,
    htype TEXT,
    ok INTEGER,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_perf_ts ON perf(ts);
CREATE INDEX IF NOT EXISTS idx_perf_host ON perf(host);

CREATE TABLE IF NOT EXISTS health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    warnings INTEGER NOT NULL,
    total INTEGER NOT NULL,
    duration REAL,
    checks TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health(ts);
"""


def _init_db(log_dir: str) -> None:
    """Initialize SQLite database for perf/health data."""
    global _DB_PATH, _db_conn
    os.makedirs(log_dir, exist_ok=True)
    _DB_PATH = os.path.join(log_dir, "freq.db")
    try:
        _db_conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _db_conn.execute("PRAGMA journal_mode=WAL")
        _db_conn.execute("PRAGMA synchronous=NORMAL")
        _db_conn.executescript(_SCHEMA)
        _db_conn.commit()
    except (sqlite3.Error, OSError) as e:
        print(f"  WARNING: Cannot initialize metrics DB: {e}", file=sys.stderr)
        _db_conn = None


def _get_db() -> sqlite3.Connection | None:
    """Get the SQLite connection, reconnecting if needed."""
    global _db_conn
    if _db_conn is None and _DB_PATH:
        try:
            _db_conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        except sqlite3.Error:
            pass
    return _db_conn


def shutdown() -> None:
    """Close the metrics DB connection cleanly.

    Called automatically via atexit, or explicitly during test teardown.
    Safe to call multiple times.
    """
    global _db_conn
    if _db_conn is not None:
        try:
            _db_conn.close()
        except sqlite3.Error:
            pass
        _db_conn = None


import atexit as _atexit
_atexit.register(shutdown)


# ── Log rotation ─────────────────────────────────────────────────────

def _maybe_rotate() -> None:
    """Rotate log file if it exceeds _MAX_LOG_BYTES."""
    if not _LOG_FILE:
        return
    try:
        size = os.path.getsize(_LOG_FILE)
    except OSError:
        return
    if size < _MAX_LOG_BYTES:
        return

    # Rotate: freq.log -> freq.log.1 -> freq.log.2 -> freq.log.3 (deleted)
    for i in range(_ROTATE_KEEP, 0, -1):
        src = f"{_LOG_FILE}.{i}" if i > 1 else (f"{_LOG_FILE}.1" if i == 1 else _LOG_FILE)
        dst = f"{_LOG_FILE}.{i + 1}" if i < _ROTATE_KEEP else None

        if i == _ROTATE_KEEP:
            # Delete oldest
            try:
                os.unlink(f"{_LOG_FILE}.{i}")
            except OSError:
                pass
        elif os.path.isfile(src):
            try:
                os.rename(src, f"{_LOG_FILE}.{i + 1}")
            except OSError:
                pass

    # Rename current to .1
    try:
        os.rename(_LOG_FILE, f"{_LOG_FILE}.1")
    except OSError:
        pass


# ── Init ─────────────────────────────────────────────────────────────

def init(log_file: str, stderr: bool = False) -> None:
    """Initialize the logger with a file path.

    Args:
        log_file: Path to the JSON-lines log file
        stderr: If True, also output human-readable logs to stderr
    """
    global _LOG_FILE, _stderr_enabled
    _stderr_enabled = stderr or (hasattr(sys.stderr, "isatty") and sys.stderr.isatty())

    log_dir = os.path.dirname(log_file)
    try:
        os.makedirs(log_dir, exist_ok=True)
        test_path = os.path.join(log_dir, ".write-test")
        try:
            with open(test_path, "w") as f:
                f.write("")
            os.unlink(test_path)
        except (OSError, PermissionError):
            raise PermissionError(f"Cannot write to log directory: {log_dir}")
        _LOG_FILE = log_file
    except (OSError, PermissionError):
        import tempfile
        fallback_dir = os.path.join(os.environ.get("HOME", tempfile.gettempdir()), ".freq", "log")
        os.makedirs(fallback_dir, exist_ok=True)
        _LOG_FILE = os.path.join(fallback_dir, "freq.log")
        # Only warn if running interactively — don't spam operator commands
        if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
            print(f"  WARNING: Cannot write to {log_dir}, logging to {_LOG_FILE}", file=sys.stderr)

    # Initialize SQLite for metrics
    _init_db(os.path.dirname(_LOG_FILE))


def init_perf(log_dir: str) -> None:
    """Initialize performance tracking. Uses SQLite via init()."""
    if not _db_conn:
        _init_db(log_dir)


# ── Core writer (thread-safe, rotating, dual-output) ─────────────────

_LEVEL_COLORS = {
    "DEBUG": "\033[36m",   # Cyan
    "INFO": "\033[32m",    # Green
    "WARN": "\033[33m",    # Yellow
    "ERROR": "\033[31m",   # Red
    "CMD": "\033[35m",     # Magenta
}
_RESET = "\033[0m"


def _write(level: str, msg: str, **extra) -> None:
    """Write a JSON log line. Thread-safe with rotation."""
    if not _LOG_FILE:
        return

    # Merge bound context
    merged = {}
    merged.update(_context)
    merged.update(extra)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "msg": _redact(msg),
    }
    entry.update(merged)

    with _lock:
        try:
            _maybe_rotate()
            with open(_LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except (OSError, PermissionError):
            pass  # Logging should never crash the tool


# ── Logging functions ────────────────────────────────────────────────

def debug(msg: str, **extra) -> None:
    _write("DEBUG", msg, **extra)


def info(msg: str, **extra) -> None:
    _write("INFO", msg, **extra)


def warn(msg: str, **extra) -> None:
    _write("WARN", msg, **extra)


# Alias: some modules use log.warning() (stdlib convention)
warning = warn


def error(msg: str, **extra) -> None:
    _write("ERROR", msg, **extra)


def cmd(command: str, exit_code: int, duration: float = 0.0, **extra) -> None:
    """Log a command execution."""
    _write("CMD", _redact(command), exit_code=exit_code, duration=round(duration, 3), **extra)


# ── Performance logging (SQLite) ─────────────────────────────────────

def perf(op: str, duration: float, **extra) -> None:
    """Record a performance metric to SQLite."""
    db = _get_db()
    if not db:
        return

    host = extra.pop("host", None)
    htype = extra.pop("htype", None)
    ok = extra.pop("ok", None)
    extra_json = json.dumps(extra) if extra else None

    ts = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            "INSERT INTO perf (ts, op, duration, host, htype, ok, extra) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, op, round(duration, 4), host, htype, 1 if ok else 0 if ok is not None else None, extra_json),
        )
        db.commit()
    except sqlite3.Error:
        pass


def read_perf(path: str = "", last: int = 0) -> list:
    """Read performance entries from SQLite."""
    db = _get_db()
    if not db:
        return []

    try:
        limit = f"LIMIT {last}" if last > 0 else ""
        rows = db.execute(
            f"SELECT ts, op, duration, host, htype, ok, extra FROM perf ORDER BY id DESC {limit}"
        ).fetchall()
        entries = []
        for ts, op, duration, host, htype, ok, extra_json in reversed(rows):
            entry = {"ts": ts, "op": op, "duration": duration}
            if host:
                entry["host"] = host
            if htype:
                entry["htype"] = htype
            if ok is not None:
                entry["ok"] = bool(ok)
            if extra_json:
                try:
                    entry.update(json.loads(extra_json))
                except json.JSONDecodeError:
                    pass
            entries.append(entry)
        return entries
    except sqlite3.Error:
        return []


# ── Health history (SQLite) ──────────────────────────────────────────

def save_health(passed: int, failed: int, warnings: int, duration: float, checks: list = None) -> None:
    """Save a doctor run result to SQLite."""
    db = _get_db()
    if not db:
        return

    checks_json = json.dumps(checks) if checks else None

    ts = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            "INSERT INTO health (ts, passed, failed, warnings, total, duration, checks) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, passed, failed, warnings, passed + failed + warnings, round(duration, 2), checks_json),
        )
        db.execute("DELETE FROM health WHERE id NOT IN (SELECT id FROM health ORDER BY id DESC LIMIT 90)")
        db.commit()
    except sqlite3.Error:
        pass


def read_health(last: int = 20) -> list:
    """Read health history from SQLite."""
    db = _get_db()
    if not db:
        return []

    try:
        rows = db.execute(
            "SELECT ts, passed, failed, warnings, total, duration FROM health ORDER BY id DESC LIMIT ?",
            (last,),
        ).fetchall()
        return [
            {"ts": ts, "passed": p, "failed": f, "warnings": w, "total": t, "duration": d}
            for ts, p, f, w, t, d in reversed(rows)
        ]
    except sqlite3.Error:
        return []
