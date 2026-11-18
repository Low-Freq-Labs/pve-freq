"""Serialized dashboard doctor execution below HTTP transport."""

import contextlib
import io
import json
import threading
import time

from freq.core import doctor
from freq.core.config import load_config

_cache = None
_cache_ts = 0
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 15


def run_dashboard_doctor():
    """Return one parsed doctor payload with short serialized caching."""
    global _cache, _cache_ts

    now = time.monotonic()
    cached = _cache
    if cached is not None and now - _cache_ts < _CACHE_TTL:
        return cached

    with _CACHE_LOCK:
        now = time.monotonic()
        cached = _cache
        if cached is not None and now - _cache_ts < _CACHE_TTL:
            return cached

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = doctor.run(load_config(), json_output=True)
        try:
            data = json.loads(output.getvalue())
        except (ValueError, json.JSONDecodeError):
            data = {
                "ok": result == 0,
                "output": output.getvalue(),
                "exit_code": result,
            }
        _cache = data
        _cache_ts = time.monotonic()
    return data
