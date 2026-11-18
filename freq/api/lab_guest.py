"""Opt-in registered lab routes; internal operation rows never cross HTTP."""

import datetime
import hashlib
import json
import math
import re
import time

from freq.api import auth
from freq.core.config import ConfigurationLoadUnavailable, load_config
from freq.core.read_source_epoch import SourceWriteUnavailable
from freq.services.lab_guest_power import LabPowerError, RegisteredLabPower, validate_request
from freq.services.lab_guest_registration import RegistrationError, load_registration

MAX_BODY = 4096
_OPERATION = re.compile(r"/api/lab/operations/([0-9a-f]{32})\Z")
_TERMINAL = {"succeeded", "failed", "rejected"}


def operation_path(path):
    return type(path) is str and _OPERATION.fullmatch(path) is not None


def _capture(handler, min_role="operator"):
    token, source = auth._extract_session_token_and_source(handler)
    if source != "cookie":
        return None
    with auth._auth_lock:
        original = auth._auth_tokens.get(token)
        if type(original) is not dict:
            return None
        role, user, csrf = (original.get(key) for key in ("role", "user", "csrf_token"))
        levels = {"viewer": 0, "operator": 1, "admin": 2, "protected": 3}
        if (role not in levels or min_role not in levels or levels[role] < levels[min_role]
                or type(csrf) is not str or not csrf):
            return None

    def current():
        with auth._auth_lock:
            session = auth._auth_tokens.get(token)
            if session is not original:
                return False
            last = session.get("last_activity_ts", session.get("ts"))
            return (session.get("user") == user and session.get("role") == role
                    and session.get("csrf_token") == csrf
                    and type(last) in (int, float) and math.isfinite(last)
                    and 0 <= time.time() - last < auth.SESSION_TIMEOUT_SECONDS)

    if not current():
        return None
    handler._lab_captured_role = role
    actor = hashlib.sha256(b"pve-freq-lab-session-v1\x00" + token.encode("utf-8")).hexdigest()
    return actor, current


def _time(value):
    if value is None:
        return None
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _binding(cfg, revision, loader=None):
    try:
        registration = (loader or load_registration)(cfg)
    except MemoryError:
        raise
    except Exception:
        return None
    return registration.registration_id if registration.revision == revision else None


def _operation(row, target_ref):
    task_state = row["task_state"]
    if task_state == "stopped":
        task_state = "succeeded" if row["task_exit"] == "OK" else "failed" if row["task_exit"] == "failed" else "unknown"
    elif task_state != "running":
        task_state = "unknown"
    ack = ("received" if row["upid"] is not None else "not_submitted" if row["phase"] == "rejected"
           else "uncertain" if row["phase"] == "uncertain" else "pending")
    return {"ref": row["id"], "target_ref": target_ref,
            "registration_revision": row["registration_revision"], "retired": target_ref is None,
            "action": row["action"], "expected_state": row["expected_state"], "phase": row["phase"],
            "acknowledgement": ack, "task": {"state": task_state, "exit": row["task_exit"]},
            "observation": {"state": row["observed_state"] or "unknown", "observed_at": _time(row["observed_at"])},
            "error": row["error"], "created_at": _time(row["created_at"]), "updated_at": _time(row["updated_at"])}


def _guest(result):
    reg = result["registration"]
    target = {"ref": reg["registration_id"], "registration_revision": reg["revision"],
              "source": reg["provider"], "kind": reg["guest_type"],
              **{key: reg[key] for key in ("estate", "node", "vmid", "name", "qualified_at", "expires_at")}}
    active = result["operation"]
    recovery = None
    if active is not None:
        ref = target["ref"] if active["registration_revision"] == target["registration_revision"] else None
        recovery = {"ref": active["id"], "target_ref": ref, "registration_revision": active["registration_revision"],
                    "retired": ref is None, "action": active["action"], "phase": active["phase"]}
    return {"schema": "pve-freq-lab-guest-view-v1", "target": target,
            "capabilities": {"lab_only": True, "actions": [action for action in result["capability_scope"]["allowed_actions"]
                                                          if action in ("start", "shutdown")]},
            "observation": {"state": result["observed_state"], "observed_at": _time(result["observed_at"])},
            "busy": result["busy"], "operation": recovery}


def _document(handler):
    from freq.api.pve_read import _pairs
    lengths = handler.headers.get_all("Content-Length", [])
    if (handler.headers.get("Transfer-Encoding") is not None or len(lengths) != 1
            or not lengths[0].isascii() or not lengths[0].isdecimal() or len(lengths[0]) > 4
            or not 0 < int(lengths[0]) <= MAX_BODY
            or handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json"):
        raise ValueError()
    raw = handler.rfile.read(int(lengths[0]))
    if len(raw) != int(lengths[0]):
        raise ValueError()
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(value) is not dict:
        raise ValueError()
    return value


def _body(handler):
    return validate_request(_document(handler))


def _power_service(cfg, actor, current, role):
    """Observe policy removal too; the factory retains strict legacy behavior."""
    from freq.services.lab_power_qualification import LabPowerQualification
    qualification = LabPowerQualification(cfg, still_current=current)

    def loader(_cfg, now=None):
        return qualification.effective_registration(
            actor, can_request=role in ("admin", "protected"), now=now)

    return RegisteredLabPower(cfg, still_current=current, registration_loader=loader), loader


def _publish(handler, document, status=200, current=None):
    # Serialize bounded public data before the final admission check. No auth or
    # store lock spans headers/body I/O; admitted bytes cannot be retracted.
    raw = json.dumps(document, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if current is not None and not current():
        raw, status = b'{"error":"session_retired"}', 403
        handler.close_connection = True
    handler._lab_response_consumed = True
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(raw)))
    handler._send_security_headers()
    handler.end_headers()
    handler.wfile.write(raw)
    if current is not None and not current():
        handler.close_connection = True


def handle(handler):
    # Close every POST connection, including refusals with an unread body.
    if handler.command == "POST":
        handler.close_connection = True
    if getattr(getattr(handler, "server", None), "freq_lab_cockpit", False) is not True:
        _publish(handler, {"error": "not_found"}, 404)
        return
    path = handler.path.split("?", 1)[0]
    expected = "POST" if path == "/api/lab/power" else "GET"
    if "?" in handler.path:
        _publish(handler, {"error": "invalid_request"}, 400)
        return
    if handler.command != expected:
        _publish(handler, {"error": "method_not_allowed"}, 405)
        return
    if not auth.request_is_https(handler):
        _publish(handler, {"error": "https_required"}, 403)
        return
    captured = _capture(handler)
    if captured is None:
        _publish(handler, {"error": "authentication_required"}, 403)
        return
    actor, current = captured
    if expected == "POST":
        if not auth.same_origin_or_absent(handler, require_present=True):
            _publish(handler, {"error": "same_origin_required"}, 403, current)
            return
        if not auth.check_csrf(handler)[0]:
            _publish(handler, {"error": "csrf_required"}, 403, current)
            return
        try:
            body = _body(handler)
        except (ValueError, UnicodeError, RecursionError, LabPowerError):
            _publish(handler, {"error": "invalid_request"}, 400, current)
            return
    try:
        cfg = load_config()
        service, loader = _power_service(cfg, actor, current, handler._lab_captured_role)
        if path == "/api/lab/guest":
            result, status = _guest(service.inspect(actor)), 200
        else:
            row = service.submit(actor, body) if expected == "POST" else service.poll(actor, _OPERATION.fullmatch(path)[1])
            result = {"schema": "pve-freq-lab-operation-view-v1",
                      "operation": _operation(row, _binding(cfg, row["registration_revision"], loader))}
            status = (409 if row["phase"] == "rejected" else 200 if row["phase"] in _TERMINAL else 202) if expected == "POST" else 200
    except (ConfigurationLoadUnavailable, SourceWriteUnavailable):
        result, status = {"error": "configuration_unavailable"}, 503
    except LabPowerError as failure:
        code = failure.code
        status = (400 if code == "invalid_request" else 404 if code == "not_found" else
                  403 if code == "session_retired" else 409 if code in (
                      "registration_changed", "instance_changed", "state_mismatch", "dispatch_rejected",
                      "request_conflict", "target_busy") else 503)
        result = {"error": code}
    except MemoryError:
        raise
    except Exception:
        # A lost internal result never proves that a submitted action did not
        # happen. Publish no exception details; recover through GET guest.
        result, status = {"error": "operation_unavailable"}, 503
    _publish(handler, result, status, current)


def register(routes):
    routes["/api/lab/guest"] = handle
    routes["/api/lab/power"] = handle
