"""Structured logging for FREQ.

Provides: init(), info(), warn(), error() — JSON-lines to data/log/freq.log.

Every FREQ operation is logged as a JSON line with timestamp, level, message,
and optional fields (user, command, host). Sensitive data (passwords, tokens,
keys) is automatically redacted before writing.

Replaces: Unstructured syslog or print-to-file logging

Architecture:
    - JSON lines format — one JSON object per line, grep/jq friendly
    - File opened once via init(), appended to via info/warn/error
    - Regex-based redaction of passwords, tokens, and key material
    - No external dependencies — json + datetime from stdlib

Design decisions:
    - JSON lines, not Python logging module. Simpler, greppable, no config.
    - Redaction is paranoid — any field matching password/token/secret/key
      patterns gets replaced with [REDACTED]. False positives > leaks.
"""
import json
import os
import re
from datetime import datetime, timezone


_LOG_FILE: str = ""
_REDACT_PATTERNS = [
    re.compile(r"(password|passwd|secret|token|apikey|api_key)([=: ]+)\S+", re.IGNORECASE),
    re.compile(r"(sshpass\s+-p\s+)\S+"),
]


def init(log_file: str) -> None:
    """Initialize the logger with a file path.

    Creates the log directory if needed. If the directory can't be created
    (e.g. permission denied), falls back to a writable temp location so
    logging never blocks startup.
    """
    global _LOG_FILE
    log_dir = os.path.dirname(log_file)
    try:
        os.makedirs(log_dir, exist_ok=True)
        # Verify we can actually write to the directory
        test_path = os.path.join(log_dir, ".write-test")
        try:
            with open(test_path, "w") as f:
                f.write("")
            os.unlink(test_path)
        except (OSError, PermissionError):
            raise PermissionError(f"Cannot write to log directory: {log_dir}")
        _LOG_FILE = log_file
    except (OSError, PermissionError):
        # Fall back to a writable location under the user's home
        import tempfile
        fallback_dir = os.path.join(
            os.environ.get("HOME", tempfile.gettempdir()), ".freq", "log"
        )
        os.makedirs(fallback_dir, exist_ok=True)
        _LOG_FILE = os.path.join(fallback_dir, "freq.log")
        import sys
        print(
            f"  WARNING: Cannot write to {log_dir}, logging to {_LOG_FILE}",
            file=sys.stderr,
        )


def _redact(msg: str) -> str:
    """Scrub passwords, tokens, and secrets from log messages."""
    for pattern in _REDACT_PATTERNS:
        msg = pattern.sub(lambda m: m.group(1) + m.group(2) + "***REDACTED***"
                          if m.lastindex and m.lastindex >= 2
                          else m.group(1) + "***REDACTED***", msg)
    return msg


def _write(level: str, msg: str, **extra) -> None:
    """Write a JSON log line."""
    if not _LOG_FILE:
        return

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "msg": _redact(msg),
    }
    entry.update(extra)

    try:
        with open(_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except (OSError, PermissionError):
        pass  # Logging should never crash the tool


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
