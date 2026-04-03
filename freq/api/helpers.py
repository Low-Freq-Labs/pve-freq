"""Shared helpers for API domain handlers.

Provides: json_response(), get_params(), get_json_body(), get_cfg()

Common utilities that every API handler needs. Imported by each
freq/api/<domain>.py module to avoid duplicating HTTP response logic.
"""

import json
from urllib.parse import urlparse, parse_qs

from freq.core.config import load_config


def json_response(handler, data, status=200):
    """Send a JSON response through the HTTP handler."""
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    origin = handler.headers.get("Origin", "")
    if origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        handler.send_header("Vary", "Origin")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.end_headers()
    handler.wfile.write(body)


def get_params(handler) -> dict:
    """Parse query string parameters. Returns {key: [values]}."""
    return parse_qs(urlparse(handler.path).query)


def get_param(handler, key, default="") -> str:
    """Get a single query parameter value."""
    params = get_params(handler)
    values = params.get(key, [default])
    return values[0] if values else default


def get_json_body(handler) -> dict:
    """Read and parse a JSON request body."""
    try:
        length = int(handler.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = handler.rfile.read(length)
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return {}


def get_param_int(handler, key, default=0, min_val=None, max_val=None):
    """Get integer query parameter with bounds checking."""
    raw = get_param(handler, key, str(default))
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return default
    if min_val is not None and val < min_val:
        return default
    if max_val is not None and val > max_val:
        return default
    return val


def require_role(min_role="operator"):
    """Decorator for API handlers that require authentication."""

    def decorator(handler_func):
        def wrapper(handler):
            from freq.api.auth import check_session_role

            role, err = check_session_role(handler, min_role)
            if err:
                json_response(handler, {"error": err}, 403)
                return
            handler_func(handler)

        wrapper.__name__ = handler_func.__name__
        wrapper.__doc__ = handler_func.__doc__
        return wrapper

    return decorator


def get_cfg():
    """Load FREQ config (convenience wrapper)."""
    return load_config()
