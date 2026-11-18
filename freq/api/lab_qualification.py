"""Explicit local qualification for the configured lab target, never native power."""

from freq.api import auth
from freq.api.lab_guest import _capture, _document, _publish
from freq.core.config import ConfigurationLoadUnavailable, load_config
from freq.core.read_source_epoch import SourceWriteUnavailable
from freq.services.lab_power_qualification import (
    LabPowerQualification, QualificationError, validate_request,
)


def handle_window(handler):
    if handler.command == "POST":
        handler.close_connection = True
    if getattr(getattr(handler, "server", None), "freq_lab_cockpit", False) is not True:
        _publish(handler, {"error": "not_found"}, 404)
        return
    if handler.path != "/api/lab/window":
        _publish(handler, {"error": "invalid_request"}, 400)
        return
    if handler.command not in ("GET", "POST"):
        _publish(handler, {"error": "method_not_allowed"}, 405)
        return
    if not auth.request_is_https(handler):
        _publish(handler, {"error": "https_required"}, 403)
        return
    captured = _capture(handler, "admin" if handler.command == "POST" else "viewer")
    if captured is None:
        _publish(handler, {"error": "authentication_required"}, 403)
        return
    actor, current = captured
    can_request = handler._lab_captured_role in ("admin", "protected")
    if handler.command == "POST":
        if not auth.same_origin_or_absent(handler, require_present=True):
            _publish(handler, {"error": "same_origin_required"}, 403, current)
            return
        if not auth.check_csrf(handler)[0]:
            _publish(handler, {"error": "csrf_required"}, 403, current)
            return
        try:
            body = validate_request(_document(handler))
        except (ValueError, UnicodeError, RecursionError, QualificationError):
            _publish(handler, {"error": "invalid_request"}, 400, current)
            return
    try:
        cfg = load_config()
        service = LabPowerQualification(cfg, still_current=current)
        if handler.command == "GET":
            result, status = service.inspect(actor, can_request=can_request), 200
        else:
            result, status = service.qualify(actor, body, can_request=can_request)
    except (ConfigurationLoadUnavailable, SourceWriteUnavailable):
        result, status = {"error": "configuration_unavailable"}, 503
    except QualificationError as failure:
        code = failure.code
        status = (400 if code == "invalid_request" else 403 if code in (
            "role_required", "session_retired") else 409 if code in (
                "registration_changed", "policy_changed", "request_conflict",
                "qualification_busy", "target_busy", "state_mismatch", "instance_changed") else 503)
        result = {"error": code}
    except MemoryError:
        raise
    except Exception:
        # A lost local grant result must be recovered by GET, never a new intent.
        result, status = {"error": "qualification_unavailable"}, 503
    _publish(handler, result, status, current)


def register(routes):
    routes["/api/lab/window"] = handle_window
