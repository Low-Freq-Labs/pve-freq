"""Authenticated read-only PVE observations and local endpoint configuration.

Configuration stores credentials locally; it never creates provider tokens or
modifies a Proxmox host. Inventory observations confer no action authority.
"""

import json

from freq.api import auth
from freq.core.config import ConfigurationLoadUnavailable, load_config
from freq.core.read_source_epoch import SourceWriteUnavailable
from freq.services.pve_read_inventory import resolve_inventory

MAX_CONFIGURATION_BODY = 128 * 1024


def _admit(handler, role):
    _role, error = auth.check_session_role(handler, role)
    if error:
        handler._json_response({"error": "authentication_required"}, 403)
        return False
    if not auth.request_is_https(handler):
        handler._json_response({"error": "https_required"}, 403)
        return False
    return True


def _method(handler, methods):
    if handler.command in methods:
        return True
    handler._json_response({"error": "method_not_allowed"}, 405)
    return False


def handle_inventory(handler):
    """GET observations, including explicit unsuccessful source outcomes."""
    if not _method(handler, {"GET"}) or not _admit(handler, "viewer"):
        return
    try:
        cfg = load_config()
    except (ConfigurationLoadUnavailable, SourceWriteUnavailable):
        handler._json_response({"error": "configuration_unavailable"}, 503)
        return
    handler._json_response(resolve_inventory(cfg))


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _body(handler):
    if handler.headers.get("Transfer-Encoding") is not None:
        raise ValueError("unsupported framing")
    lengths = handler.headers.get_all("Content-Length", []) if hasattr(handler.headers, "get_all") else [handler.headers.get("Content-Length", "")]
    if len(lengths) != 1:
        raise ValueError("invalid length")
    raw_length = lengths[0]
    if not raw_length.isascii() or not raw_length.isdecimal() or len(raw_length) > 8:
        raise ValueError("invalid length")
    length = int(raw_length)
    if not 0 < length <= MAX_CONFIGURATION_BODY:
        raise ValueError("invalid length")
    media = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if media != "application/json":
        raise ValueError("invalid media type")
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ValueError("truncated body")
    document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid number")))
    if type(document) is not dict:
        raise ValueError("invalid document")
    return document


def handle_endpoints(handler):
    """Admin-only create/read configuration; no provider request occurs here."""
    if not _method(handler, {"GET", "POST"}) or not _admit(handler, "admin"):
        return
    from freq.services.pve_read_configuration import (
        ConfigurationError, configure_pve_read, get_pve_read_configuration,
    )
    if handler.command == "POST":
        if not auth.same_origin_or_absent(handler, require_present=True):
            handler._json_response({"error": "same_origin_required"}, 403)
            return
        accepted, _error = auth.check_csrf(handler)
        if not accepted:
            handler._json_response({"error": "csrf_required"}, 403)
            return
        try:
            body = _body(handler)
        except (ValueError, UnicodeError, RecursionError):
            handler.close_connection = True
            handler._json_response({"error": "invalid_request"}, 400)
            return
    try:
        cfg = load_config()
        if handler.command == "GET":
            response = get_pve_read_configuration(cfg)
        else:
            response = {"ok": True, **configure_pve_read(cfg, body)}
    except (ConfigurationLoadUnavailable, SourceWriteUnavailable):
        handler._json_response({"error": "configuration_unavailable"}, 503)
        return
    except ConfigurationError as failure:
        # Only fixed helper codes are exposed; never raw file/provider errors.
        invalid = {"invalid_request", "invalid_address", "invalid_token", "invalid_ca"}
        code = failure.code if failure.code in invalid | {"already_configured"} else "configuration_unavailable"
        status = 409 if code == "already_configured" else 400 if code in invalid else 503
        handler._json_response({"error": code}, status)
        return
    handler._json_response(response)


def register(routes):
    routes["/api/pve/inventory"] = handle_inventory
    routes["/api/pve/endpoints"] = handle_endpoints
