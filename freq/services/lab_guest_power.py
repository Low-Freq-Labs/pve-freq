"""Single-attempt orchestration for one expiring, server-registered lab QEMU.

This service does not authenticate HTTP requests or grant a provider capability.
The API owner derives the session actor, supplies ``still_current`` (a no-argument
callback returning literal True), and projects internal operation rows. There is
no worker, retry, fallback, inventory write or automatic follow-up action here.
Each poll is one bounded observation pass through the fixed-path transport.
"""

import json
import dataclasses
import math
import re
import time
import uuid

from .lab_guest_registration import load_registration
from .lab_power_store import LabPowerStore, StoreError
from .lab_pve_transport import LabPveTransport, LabTransportError


_REQUEST = {"target_ref", "registration_revision", "action", "expected_state", "request_key"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_TERMINAL = {"succeeded", "failed", "rejected"}
_CODES = {
    "invalid_request", "registration_unavailable", "invalid_registration",
    "registration_expired", "registration_changed", "instance_changed",
    "session_retired", "state_mismatch", "credentials_unavailable",
    "tls_unavailable", "provider_unavailable", "invalid_response",
    "dispatch_rejected", "dispatch_uncertain", "observation_unavailable",
    "task_failed", "task_timeout", "store_unavailable", "request_conflict",
    "target_busy", "capacity_exceeded", "not_found",
}
# Store vocabulary is narrower than admission/manifest validation vocabulary.
_STORED_CODES = _CODES - {
    "invalid_request", "registration_unavailable", "invalid_registration",
    "registration_expired", "request_conflict", "target_busy",
    "capacity_exceeded", "not_found",
}


class LabPowerError(Exception):
    """Fixed public code only, without provider messages, inputs or paths."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in _CODES else "provider_unavailable"
        super().__init__(self.code)


class _Contradiction(LabPowerError):
    """An explicit identity/authority disagreement, not a missing observation."""


def _call(port, *args, fallback, **kwargs):
    try:
        return port(*args, **kwargs)
    except MemoryError:
        raise
    except LabPowerError:
        raise
    except Exception as failure:
        code = getattr(failure, "code", None)
        raise LabPowerError(code if type(code) is str and code in _CODES else fallback) from None


def _target(registration):
    return json.dumps({key: getattr(registration, key) for key in (
        "estate", "provider", "node", "guest_type", "vmid", "instance_uuid")},
        sort_keys=True, separators=(",", ":"), allow_nan=False)


def _actor(actor):
    if type(actor) is not str or not _HASH.fullmatch(actor):
        raise LabPowerError("invalid_request")


def _scope(document, registration):
    if type(document) is not dict:
        raise LabPowerError("invalid_response")
    for key in ("node", "name", "vmid"):
        if key in document and (type(document[key]) is not type(getattr(registration, key))
                                or document[key] != getattr(registration, key)):
            raise _Contradiction("instance_changed")


def _config(document, registration):
    _scope(document, registration)
    if "lock" in document:
        raise LabPowerError("state_mismatch")
    if document.get("name") != registration.name:
        raise _Contradiction("instance_changed")
    smbios = document.get("smbios1")
    if type(smbios) is not str:
        raise _Contradiction("instance_changed")
    values = [item.partition("=")[2] for item in smbios.split(",")
              if item.partition("=")[0].strip().lower() == "uuid"]
    try:
        if len(values) != 1 or str(uuid.UUID(values[0])) != registration.instance_uuid:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise _Contradiction("instance_changed") from None


def _status(document, registration):
    _scope(document, registration)
    status = document.get("status")
    if type(status) is not str or status not in ("running", "stopped"):
        raise LabPowerError("invalid_response")
    return status


def _upid(value, registration, action):
    if (type(value) is not str or len(value) > 512 or re.fullmatch(
            r"UPID:[A-Za-z0-9-]+:[0-9a-fA-F]{8}:[0-9a-fA-F]{8,16}:"
            r"[0-9a-fA-F]{8}:[A-Za-z0-9_-]+:[A-Za-z0-9_.-]*:[A-Za-z0-9_.@!+-]+:", value) is None):
        raise LabPowerError("invalid_response")
    fields = value.split(":")
    if (fields[1] != registration.node or fields[5] != {"start": "qmstart", "shutdown": "qmshutdown"}[action]
            or fields[6] != str(registration.vmid) or fields[7] != registration.token_id):
        raise _Contradiction("invalid_response")
    return value


def _task(document, registration, row):
    if type(document) is not dict:
        raise LabPowerError("invalid_response")
    expected = {"upid": row["upid"], "node": registration.node,
                "type": {"start": "qmstart", "shutdown": "qmshutdown"}[row["action"]],
                "id": str(registration.vmid), "user": registration.token_id.split("!", 1)[0],
                "tokenid": registration.token_id.split("!", 1)[1]}
    for key, value in expected.items():
        if key not in document:
            raise LabPowerError("invalid_response")
        if type(document[key]) is not str or document[key] != value:
            raise _Contradiction("invalid_response")
    state = document.get("status")
    if state == "running" and type(state) is str and "exitstatus" not in document:
        return "running", None
    exit_status = document.get("exitstatus")
    if state == "stopped" and type(state) is str and type(exit_status) is str and exit_status:
        return "stopped", "OK" if exit_status == "OK" else "failed"
    raise LabPowerError("invalid_response")


def validate_request(request):
    if (type(request) is not dict or set(request) != _REQUEST
            or any(type(value) is not str for value in request.values())
            or request["action"] not in ("start", "shutdown")
            or request["expected_state"] not in ("running", "stopped")
            or request["expected_state"] != {"start": "stopped", "shutdown": "running"}.get(request["action"])
            or not 0 < len(request["request_key"]) <= 128
            or not all(33 <= ord(char) <= 126 for char in request["request_key"])):
        raise LabPowerError("invalid_request")
    # Hold a private snapshot across fallible calls; never dispatch an edited draft.
    request = request.copy()
    return request


class RegisteredLabPower:
    def __init__(self, cfg, transport_factory=LabPveTransport,
                 store_factory=LabPowerStore, clock=time.time, still_current=None,
                 registration_loader=None):
        self.cfg = cfg
        self.transport_factory = transport_factory
        self.store_factory = store_factory
        self.clock = clock
        self.still_current = still_current
        self.registration_loader = registration_loader

    def _now(self):
        instant = _call(self.clock, fallback="observation_unavailable")
        if (type(instant) not in (int, float) or not math.isfinite(instant)
                or not 0 <= instant <= 2**53 - 1):
            raise LabPowerError("observation_unavailable")
        return instant

    def _current(self):
        if self.still_current is None:
            raise _Contradiction("session_retired")
        if self.still_current is not None:
            try:
                current = _call(self.still_current, fallback="session_retired")
            except LabPowerError:
                raise _Contradiction("session_retired") from None
            if current is not True:
                raise _Contradiction("session_retired")

    def _registration(self):
        return _call(self.registration_loader or load_registration, self.cfg,
                     now=self._now(), fallback="registration_unavailable")

    def _same(self, registration, *, observation=False):
        try:
            current = self._registration()
        except MemoryError:
            raise
        except LabPowerError:
            raise _Contradiction("registration_changed") from None
        same = current == registration
        if observation and not same:
            # Expiry may withdraw mutation rights while preserving the same
            # original task's diagnostic witness. All other fields stay exact.
            # This exception is never used for submission.
            try:
                same = (current.allowed_actions == ("status",)
                        and dataclasses.replace(current, allowed_actions=registration.allowed_actions) == registration)
            except (TypeError, AttributeError):
                same = False
        if not same:
            raise _Contradiction("registration_changed")
        return current

    def _store(self):
        return _call(self.store_factory, self.cfg.data_dir, fallback="store_unavailable")

    def _transport(self, registration):
        transport = _call(self.transport_factory, registration, fallback="provider_unavailable")
        if isinstance(transport, LabPveTransport):
            def before_submit():
                self._same(registration)
                self._current()
            transport.before_submit = before_submit
        return transport

    def _update(self, store, actor, row, **fields):
        try:
            return store.update(row["id"], actor, row["version"], **fields)
        except MemoryError:
            raise
        except StoreError as failure:
            if failure.code == "stale_version":
                # Do not retry an update based on observations from a stale pass.
                return _call(store.get, row["id"], actor, fallback="store_unavailable")
            raise LabPowerError(failure.code if failure.code in _CODES else "store_unavailable") from None
        except Exception:
            raise LabPowerError("store_unavailable") from None

    def inspect(self, actor):
        _actor(actor)
        self._current()
        registration = self._registration()
        transport = self._transport(registration)
        _config(_call(transport.get_config, fallback="provider_unavailable"), registration)
        observed = _status(_call(transport.get_status, fallback="provider_unavailable"), registration)
        instant = self._now()
        self._same(registration)
        self._current()
        store = self._store()
        active = _call(store.active_for_target, _target(registration), fallback="store_unavailable")
        operation = None
        if active is not None and active["actor"] == actor:
            operation = {key: active[key] for key in (
                "id", "registration_revision", "action", "expected_state", "phase",
                "task_state", "task_exit", "observed_state", "observed_at", "error", "version")}
        self._current()
        return {"registration": registration.public_view(), "observed_state": observed,
                "observed_at": instant, "capability_scope": {
                    "lab_only": True, "allowed_actions": list(registration.allowed_actions)},
                "busy": active is not None, "operation": operation}

    def submit(self, actor, request):
        _actor(actor)
        self._current()
        request = validate_request(request)
        registration = self._registration()
        if (request["target_ref"] != registration.registration_id
                or request["registration_revision"] != registration.revision):
            raise LabPowerError("registration_changed")
        if request["action"] not in registration.allowed_actions:
            raise LabPowerError("dispatch_rejected")
        store = self._store()
        row, dispatch = _call(store.admit, actor, request["request_key"], registration.revision,
                              _target(registration), request["action"], request["expected_state"],
                              fallback="store_unavailable")
        if not dispatch:
            self._current()
            return row
        try:
            transport = self._transport(registration)
            _config(_call(transport.get_config, fallback="provider_unavailable"), registration)
            observed = _status(_call(transport.get_status, fallback="provider_unavailable"), registration)
            instant = self._now()
            if observed != row["expected_state"]:
                raise LabPowerError("state_mismatch")
            self._same(registration)
            self._current()
        except MemoryError:
            raise
        except LabPowerError as failure:
            code = failure.code if failure.code in _STORED_CODES else "registration_changed"
            return self._update(store, actor, row, phase="rejected", error=code)
        try:
            # From this boundary onward, an ordinary exception cannot prove no effect.
            upid = transport.submit(row["action"])
            _upid(upid, registration, row["action"])
        except MemoryError:
            # Keep the original committed pending admission; never pretend cancellation.
            raise
        except LabTransportError as failure:
            uncertain = failure.uncertain is not False
            code = failure.code if failure.code in _STORED_CODES else "dispatch_rejected"
            return self._update(store, actor, row,
                                phase="uncertain" if uncertain else "rejected",
                                error="dispatch_uncertain" if uncertain else code,
                                observed_state=observed, observed_at=instant)
        except Exception:
            return self._update(store, actor, row, phase="uncertain", error="dispatch_uncertain",
                                observed_state=observed, observed_at=instant)
        return self._update(store, actor, row, phase="acknowledged", upid=upid,
                            observed_state=observed, observed_at=instant, error=None)

    def poll(self, actor, operation_id):
        _actor(actor)
        self._current()
        if type(operation_id) is not str or not _ID.fullmatch(operation_id):
            raise LabPowerError("invalid_request")
        store = self._store()
        row = _call(store.get, operation_id, actor, fallback="store_unavailable")
        # Historical terminal facts never become a current provider observation.
        if row["phase"] in _TERMINAL or row["upid"] is None:
            return row
        try:
            registration = self._registration()
        except MemoryError:
            raise
        except LabPowerError:
            return self._update(store, actor, row, phase="uncertain", error="registration_changed",
                                observed_state="unknown", observed_at=None)
        if (registration.revision != row["registration_revision"]
                or _target(registration) != row["target"]):
            return self._update(store, actor, row, phase="uncertain", error="registration_changed",
                                observed_state="unknown", observed_at=None)

        fields = {"observed_state": "unknown", "observed_at": None,
                  "error": "observation_unavailable"}
        try:
            _upid(row["upid"], registration, row["action"])
            transport = self._transport(registration)
            _config(_call(transport.get_config, fallback="observation_unavailable"), registration)
            # Task evidence and guest observation are independent. A failed GET on
            # either axis must not erase a known terminal task or block the other.
            task_failure = observation_failure = None
            try:
                task_state, task_exit = _task(
                    _call(transport.get_task, row["upid"], fallback="observation_unavailable"),
                    registration, row)
                if row["task_state"] == "stopped" and (
                        task_state != "stopped" or task_exit != row["task_exit"]):
                    raise _Contradiction("invalid_response")
                fields.update(task_state=task_state, task_exit=task_exit)
            except _Contradiction:
                raise
            except LabPowerError as failure:
                task_failure = failure
            try:
                fields["observed_state"] = _status(
                    _call(transport.get_status, fallback="observation_unavailable"), registration)
                fields["observed_at"] = self._now()
            except _Contradiction:
                raise
            except LabPowerError as failure:
                observation_failure = failure
            self._same(registration, observation=True)
            self._current()
            task_state = fields.get("task_state", row["task_state"])
            task_exit = fields.get("task_exit", row["task_exit"])
            # Submission uncertainty is sticky. Known-UPID transient GET loss is
            # recoverable by another GET of this same operation, never another POST.
            phase = row["phase"]
            if phase == "uncertain":
                fields["error"] = row["error"]
            if phase != "uncertain":
                if task_state == "running":
                    phase = "running"
                desired = "running" if row["action"] == "start" else "stopped"
                if observation_failure is None and task_state == "stopped":
                    if task_exit == "failed":
                        phase, fields["error"] = "failed", "task_failed"
                    elif task_exit == "OK" and fields["observed_state"] == desired:
                        phase, fields["error"] = "succeeded", None
                    else:
                        fields["error"] = "state_mismatch"
                elif task_failure is None and observation_failure is None:
                    fields["error"] = None
            fields["phase"] = phase
        except MemoryError:
            raise
        except _Contradiction as failure:
            fields.update(phase="uncertain", error=failure.code,
                          observed_state="unknown", observed_at=None)
        except LabPowerError:
            # A missing config/status/task observation is not submission uncertainty.
            pass
        return self._update(store, actor, row, **fields)
