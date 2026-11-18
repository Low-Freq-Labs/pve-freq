"""Explicit, session-local qualification; provider GETs only, never power writes.

Immutable base/policy hashes bind each durable request. A ten-second preparation
has both a persisted wall deadline (restart reaping) and a per-call monotonic
deadline. Neither is provider cancellation or protection from wall-clock rollback.
The private operation store arbitrates local commits; no SQL/auth lock spans GETs.
Missing policy preserves manual registration; configured invalid policy fails shut.
Observed owner revocation durably retires all affected session grants. Unobserved
file changes cannot be detected; grant expiry/role loss alone retain read witness.
"""
import contextlib
import dataclasses
import datetime
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid

from .lab_guest_registration import RegistrationError, _protected_read, _utc, load_registration
from .lab_power_store import LabPowerStore, StoreError, _target_slot
from .lab_pve_transport import LabPveTransport

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST = {"target_ref", "configuration_revision", "policy_revision", "request_key"}
_POLICY = {"schema", "enabled", "registration_id", "configuration_revision", "allowed_actions",
           "window_seconds", "credential_expires_at"}
_CODES = {"invalid_request", "role_required", "session_retired", "registration_unavailable",
          "invalid_policy", "policy_disabled", "policy_expired", "registration_changed",
          "policy_changed", "request_conflict", "qualification_busy", "target_busy",
          "qualification_timeout", "qualification_rejected", "permissions_unavailable",
          "credentials_unavailable", "tls_unavailable", "provider_unavailable",
          "invalid_response", "state_mismatch", "instance_changed", "store_unavailable",
          "capacity_exceeded"}
_COLUMNS = ("id", "actor", "request_key", "target_ref", "base_revision", "policy_revision",
            "target_slot", "state", "created_at", "prepare_until", "qualified_at", "expires_at",
            "effective_revision", "error", "version")
_SQL = """CREATE TABLE IF NOT EXISTS qualification_requests (
id TEXT PRIMARY KEY, actor TEXT NOT NULL, request_key TEXT NOT NULL,
target_ref TEXT NOT NULL, base_revision TEXT NOT NULL, policy_revision TEXT NOT NULL,
target_slot TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL,
prepare_until REAL NOT NULL, qualified_at REAL, expires_at REAL,
effective_revision TEXT, error TEXT, version INTEGER NOT NULL,
UNIQUE(actor, request_key))"""


class QualificationError(Exception):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _CODES else "qualification_rejected"
        super().__init__(self.code)


def _need(value, code):
    if not value:
        raise QualificationError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise QualificationError("invalid_policy")
        result[key] = value
    return result


def _number(value):
    return type(value) in (int, float) and 0 <= value <= 2**53 - 1 and math.isfinite(value)


def _stamp(value):
    try:
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    except MemoryError:
        raise
    except Exception:
        raise QualificationError("store_unavailable") from None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _target(base):
    return json.dumps({key: getattr(base, key) for key in (
        "estate", "provider", "node", "guest_type", "vmid", "instance_uuid")}, sort_keys=True, separators=(",", ":"))


def validate_request(request):
    _need(type(request) is dict and set(request) == _REQUEST
          and all(type(value) is str for value in request.values()), "invalid_request")
    _need(0 < len(request["target_ref"]) <= 512
          and not any(ord(char) < 32 for char in request["target_ref"])
          and _HASH.fullmatch(request["configuration_revision"])
          and _HASH.fullmatch(request["policy_revision"])
          and 0 < len(request["request_key"]) <= 128
          and all(33 <= ord(char) <= 126 for char in request["request_key"]), "invalid_request")
    return request.copy()


class LabPowerQualification:
    def __init__(self, cfg, *, still_current, clock=time.time, monotonic=time.monotonic,
                 transport_factory=LabPveTransport):
        self.cfg, self.still_current = cfg, still_current
        self.clock, self.monotonic, self.transport_factory = clock, monotonic, transport_factory

    def _current(self):
        try:
            _need(callable(self.still_current) and self.still_current() is True, "session_retired")
        except MemoryError:
            raise
        except Exception:
            raise QualificationError("session_retired") from None

    def _now(self, supplied=None):
        try:
            value = self.clock() if supplied is None else supplied
            if isinstance(value, datetime.datetime):
                _need(value.tzinfo is not None and value.utcoffset() == datetime.timedelta(0), "store_unavailable")
                value = value.timestamp()
            _need(_number(value), "store_unavailable")
            datetime.datetime.fromtimestamp(value, datetime.timezone.utc)
            return value
        except MemoryError:
            raise
        except Exception:
            raise QualificationError("store_unavailable") from None

    def _mono(self):
        try:
            value = self.monotonic()
            _need(_number(value), "qualification_timeout")
            return value
        except MemoryError:
            raise
        except Exception:
            raise QualificationError("qualification_timeout") from None

    @staticmethod
    def _actor(actor):
        _need(type(actor) is str and _HASH.fullmatch(actor), "invalid_request")

    def _base(self, now, *, strict=False):
        try:
            return load_registration(self.cfg, now=now, allow_expired=not strict)
        except MemoryError:
            raise
        except RegistrationError as error:
            raise QualificationError(error.code if error.code == "credentials_unavailable"
                                     else "registration_unavailable") from None

    def _policy(self, base, now):
        path = os.path.join(self.cfg.conf_dir, "lab-power-policy.json")
        try:
            try:
                os.lstat(path)
            except FileNotFoundError:
                return None
            raw = _protected_read(path, 65536)
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            _need(type(document) is dict and set(document) == _POLICY, "invalid_policy")
            _need(document["schema"] == "pve-freq-lab-power-policy-v1"
                  and type(document["enabled"]) is bool
                  and type(document["window_seconds"]) is int and document["window_seconds"] == 900
                  and document["allowed_actions"] == ["start", "shutdown"]
                  and document["registration_id"] == base.registration_id
                  and type(document["configuration_revision"]) is str
                  and _HASH.fullmatch(document["configuration_revision"])
                  and document["configuration_revision"] == base.revision, "invalid_policy")
            expires = _utc(document["credential_expires_at"]).timestamp()
            _need(expires > now, "policy_expired")
            return {"enabled": document["enabled"], "revision": hashlib.sha256(raw).hexdigest(),
                    "expires": expires}
        except MemoryError:
            raise
        except QualificationError:
            raise
        except Exception:
            raise QualificationError("invalid_policy") from None

    def _read_context(self, now):
        base = policy = None
        error = None
        try:
            base = self._base(now)
            policy = self._policy(base, now)
        except QualificationError as failure:
            error = failure.code
        return base, policy, error

    @staticmethod
    def _retire_observed(connection, base, policy, error=None):
        # One owner configuration governs this database, across every actor.
        # Persist retirement before returning unavailable metadata or authority.
        if error is not None or base is None or policy is None or not policy["enabled"]:
            connection.execute("UPDATE qualification_requests SET state='retired',error=?,version=version+1 WHERE state IN ('active','preparing')",
                               (error or "policy_disabled",))
        else:
            connection.execute("UPDATE qualification_requests SET state='retired',error=CASE WHEN target_ref<>? OR base_revision<>? THEN 'registration_changed' ELSE 'policy_changed' END,version=version+1 WHERE state IN ('active','preparing') AND (target_ref<>? OR base_revision<>? OR policy_revision<>?)",
                               (base.registration_id, base.revision, base.registration_id,
                                base.revision, policy["revision"]))

    def _context(self, now):
        base, policy, error = self._read_context(now)
        with self._database() as connection:
            self._retire_observed(connection, base, policy, error)
        if error is not None:
            raise QualificationError(error)
        return base, policy

    @contextlib.contextmanager
    def _database(self):
        try:
            store = LabPowerStore(self.cfg.data_dir)
            with store._transaction() as connection:
                connection.execute(_SQL)
                expected_sql = _SQL.replace(" IF NOT EXISTS", "")
                actual_sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='qualification_requests' AND type='table'").fetchone()
                _need(actual_sql is not None and actual_sql[0] == expected_sql, "store_unavailable")
                _need(tuple(row[1] for row in connection.execute("PRAGMA table_info(qualification_requests)"))
                      == _COLUMNS, "store_unavailable")
                yield connection
        except MemoryError:
            raise
        except QualificationError:
            raise
        except Exception:
            raise QualificationError("store_unavailable") from None

    @staticmethod
    def _reap(connection, now):
        connection.execute("UPDATE qualification_requests SET state='rejected',error='qualification_timeout',version=version+1 WHERE state='preparing' AND prepare_until<=?", (now,))

    @staticmethod
    def _latest(connection, actor, base):
        row = connection.execute("SELECT * FROM qualification_requests WHERE actor=? AND target_ref=? ORDER BY rowid DESC LIMIT 1",
                                 (actor, base.registration_id)).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _busy(connection, base):
        return connection.execute("SELECT 1 FROM operations WHERE target_slot=? AND active=1",
                                  (_target_slot(_target(base)),)).fetchone() is not None

    @staticmethod
    def _window(row, base, policy, now, can_request):
        if row is None:
            return None
        state, error = row["state"], row["error"]
        if (base is None or policy is None or row["base_revision"] != base.revision
                or row["policy_revision"] != policy["revision"] or not policy["enabled"]
                or can_request is not True):
            state = "retired"
        elif state == "active" and row["expires_at"] <= now:
            state = "expired"
        return {"ref": row["id"], "state": state, "registration_revision": row["effective_revision"],
                "qualified_at": _stamp(row["qualified_at"]) if row["qualified_at"] is not None else None,
                "expires_at": _stamp(row["expires_at"]) if row["expires_at"] is not None else None,
                "error": error}

    def _dto(self, actor, *, can_request, selected=None):
        self._current()
        now = self._now()
        base, policy, reason = self._read_context(now)
        row, busy, at_capacity = None, None, False
        try:
            with self._database() as connection:
                self._retire_observed(connection, base, policy, reason)
                self._reap(connection, now)
                if base is not None:
                    if selected is None:
                        row = self._latest(connection, actor, base)
                    else:
                        saved = connection.execute("SELECT * FROM qualification_requests WHERE id=? AND actor=?",
                                                   (selected["id"], actor)).fetchone()
                        _need(saved is not None, "store_unavailable")
                        row = dict(saved)
                    busy = self._busy(connection, base)
                    at_capacity = connection.execute("SELECT COUNT(*) FROM qualification_requests").fetchone()[0] >= 1024
        except QualificationError:
            reason = "store_unavailable"
            row = None
        window = self._window(row, base, policy, now, can_request)
        permitted = can_request is True and reason is None and policy is not None and policy["enabled"]
        if reason is None:
            if policy is None or not policy["enabled"]:
                reason = "policy_disabled"
            elif can_request is not True:
                reason = "role_required"
            elif busy is True:
                reason = "target_busy"
            elif window is not None and window["state"] in ("active", "preparing"):
                reason = "qualification_busy"
            elif at_capacity:
                reason = "capacity_exceeded"
            elif now + 900 >= policy["expires"]:
                reason = "policy_expired"
        self._current()
        return {"schema": "pve-freq-lab-window-v1", "target": None if base is None else {
                    "ref": base.registration_id, "configuration_revision": base.revision,
                    "estate": base.estate, "source": base.provider, "node": base.node,
                    "kind": base.guest_type, "vmid": base.vmid, "name": base.name},
                "policy": {"enabled": bool(policy and policy["enabled"]),
                           "revision": policy["revision"] if policy else None,
                           "duration_seconds": 900, "audience": "original_session"},
                "window": window, "busy": busy, "can_request": bool(permitted and reason is None),
                "reason": reason}

    def inspect(self, actor, *, can_request=False):
        self._actor(actor)
        return self._dto(actor, can_request=can_request)

    def _guard(self, row, deadline):
        self._current()
        _need(self._mono() < deadline and self._now() < row["prepare_until"], "qualification_timeout")
        return True

    def _verify(self, transport, base, row, deadline):
        transport.deadline = deadline
        transport.current = lambda: self._guard(row, deadline)
        self._guard(row, deadline)
        config = transport.get_config()
        self._guard(row, deadline)
        _need(type(config) is dict, "invalid_response")
        _need(config.get("name") == base.name, "instance_changed")
        _need("lock" not in config, "state_mismatch")
        smbios = config.get("smbios1")
        _need(type(smbios) is str, "instance_changed")
        values = [value.partition("=")[2] for value in smbios.split(",")
                  if value.partition("=")[0].strip().lower() == "uuid"]
        try:
            _need(len(values) == 1 and str(uuid.UUID(values[0])) == base.instance_uuid, "instance_changed")
        except (ValueError, AttributeError):
            raise QualificationError("instance_changed") from None
        for document in (config,):
            for key in ("node", "vmid"):
                _need(key not in document or type(document[key]) is type(getattr(base, key))
                      and document[key] == getattr(base, key), "instance_changed")
        status = transport.get_status()
        self._guard(row, deadline)
        _need(type(status) is dict and type(status.get("status")) is str
              and status["status"] in ("running", "stopped"), "invalid_response")
        for key in ("node", "vmid", "name"):
            _need(key not in status or type(status[key]) is type(getattr(base, key))
                  and status[key] == getattr(base, key), "instance_changed")
        permissions = transport.get_permissions()
        self._guard(row, deadline)
        _need(type(permissions) is dict and type(permissions.get("/vms/" + str(base.vmid))) is dict,
              "permissions_unavailable")
        values = permissions["/vms/" + str(base.vmid)]
        _need(all(name in values and type(values[name]) is int and values[name] in (0, 1)
                  for name in ("VM.Audit", "VM.PowerMgmt")), "permissions_unavailable")

    def _reject(self, actor, row, code):
        with self._database() as connection:
            connection.execute("UPDATE qualification_requests SET state='rejected',error=?,version=version+1 WHERE id=? AND actor=? AND state='preparing' AND version=?",
                               (code, row["id"], actor, row["version"]))
            current = connection.execute("SELECT * FROM qualification_requests WHERE id=? AND actor=?", (row["id"], actor)).fetchone()
            _need(current is not None, "store_unavailable")
            return dict(current)

    def qualify(self, actor, request, *, can_request=False):
        self._actor(actor)
        self._current()
        _need(can_request is True, "role_required")
        request = validate_request(request)
        now, deadline = self._now(), self._mono() + 10
        # Observe owner revocation even for replay/conflict, without provider IO.
        # Exact replay still returns its original durable disposition.
        observed_base, observed_policy, observed_error = self._read_context(now)
        with self._database() as connection:
            self._retire_observed(connection, observed_base, observed_policy, observed_error)
        # Commit retirement independently of a later request-conflict refusal.
        with self._database() as connection:
            self._reap(connection, now)
            saved = connection.execute("SELECT * FROM qualification_requests WHERE actor=? AND request_key=?",
                                       (actor, request["request_key"])).fetchone()
            if saved is not None:
                _need((saved["target_ref"], saved["base_revision"], saved["policy_revision"]) ==
                      (request["target_ref"], request["configuration_revision"], request["policy_revision"]), "request_conflict")
                row = dict(saved)
            else:
                row = None
        if row is not None:
            return self._dto(actor, can_request=can_request, selected=row), 202 if row["state"] == "preparing" else 200
        base, policy = self._context(now)
        _need(policy is not None and policy["enabled"], "policy_disabled")
        _need(request["target_ref"] == base.registration_id and request["configuration_revision"] == base.revision,
              "registration_changed")
        _need(request["policy_revision"] == policy["revision"], "policy_changed")
        _need(now + 900 < policy["expires"], "policy_expired")
        self._current()
        with self._database() as connection:
            self._reap(connection, now)
            # Serialize independent admissions, including a race with identical keys.
            saved = connection.execute("SELECT * FROM qualification_requests WHERE actor=? AND request_key=?", (actor, request["request_key"])).fetchone()
            if saved is not None:
                _need((saved["target_ref"], saved["base_revision"], saved["policy_revision"]) ==
                      (base.registration_id, base.revision, policy["revision"]), "request_conflict")
                row, dispatch = dict(saved), False
            else:
                _need(not self._busy(connection, base), "target_busy")
                active = connection.execute("SELECT 1 FROM qualification_requests WHERE actor=? AND target_ref=? AND base_revision=? AND policy_revision=? AND (state='preparing' OR state='active' AND expires_at>?)",
                                            (actor, base.registration_id, base.revision, policy["revision"], now)).fetchone()
                _need(active is None, "qualification_busy")
                _need(connection.execute("SELECT COUNT(*) FROM qualification_requests").fetchone()[0] < 1024, "capacity_exceeded")
                values = (uuid.uuid4().hex, actor, request["request_key"], base.registration_id,
                          base.revision, policy["revision"], _target_slot(_target(base)), "preparing", now,
                          now + 10, None, None, None, None, 0)
                connection.execute("INSERT INTO qualification_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
                row, dispatch = dict(zip(_COLUMNS, values)), True
        if not dispatch:
            return self._dto(actor, can_request=can_request, selected=row), 202 if row["state"] == "preparing" else 200
        try:
            self._guard(row, deadline)
            self._verify(self.transport_factory(base), base, row, deadline)
            self._guard(row, deadline)
            latest_base, latest_policy = self._context(self._now())
            _need(latest_base == base, "registration_changed")
            _need(latest_policy == policy, "policy_changed")
            self._guard(row, deadline)
            grant_start = self._now()
            _need(grant_start + 900 < policy["expires"], "policy_expired")
            with self._database() as connection:
                self._reap(connection, grant_start)
                self._guard(row, deadline)
                _need(not self._busy(connection, base), "target_busy")
                effective = _hash({"base": base.revision, "policy": policy["revision"], "request": row["id"],
                                   "qualified_at": grant_start, "expires_at": grant_start + 900})
                cursor = connection.execute("UPDATE qualification_requests SET state='active',qualified_at=?,expires_at=?,effective_revision=?,error=NULL,version=version+1 WHERE id=? AND actor=? AND state='preparing' AND version=?",
                                            (grant_start, grant_start + 900, effective, row["id"], actor, row["version"]))
                saved = connection.execute("SELECT * FROM qualification_requests WHERE id=? AND actor=?", (row["id"], actor)).fetchone()
                _need(saved is not None, "store_unavailable")
                row = dict(saved)
                activated = cursor.rowcount == 1
        except MemoryError:
            raise
        except Exception as error:
            # A commit may have succeeded before its return was lost. Never
            # overwrite its disposition or pretend a failed return grants IO.
            if isinstance(error, QualificationError) and error.code == "store_unavailable":
                raise
            try:
                self._guard(row, deadline)
            except QualificationError as guard_error:
                error = guard_error
            code = getattr(error, "code", None)
            code = code if type(code) is str and code in _CODES else "provider_unavailable"
            row = self._reject(actor, row, code)
            return self._dto(actor, can_request=can_request, selected=row), 409
        return self._dto(actor, can_request=can_request, selected=row), 201 if activated else 409

    def effective_registration(self, actor, *, can_request=False, now=None):
        self._actor(actor)
        self._current()
        instant = self._now(now)
        base, policy = self._context(instant)
        if policy is None:
            result = self._base(instant, strict=True)
        else:
            final_base, final_policy = self._context(instant)
            _need(final_base == base, "registration_changed")
            _need(final_policy == policy, "policy_changed")
            # Refresh after the final owner observation: another observer may
            # already have retired this row even if owner bytes were restored.
            with self._database() as connection:
                self._reap(connection, instant)
                row = self._latest(connection, actor, base)
            # The immutable grant also witnesses safe observation of work already
            # dispatched. Expiry/role withdrawal removes actions, not its binding.
            witness = (row is not None and row["state"] == "active"
                       and row["base_revision"] == base.revision
                       and row["policy_revision"] == policy["revision"])
            if witness:
                actions = (("status", "start", "shutdown")
                           if can_request is True and policy["enabled"] and instant < row["expires_at"]
                           else ("status",))
                result = dataclasses.replace(base, allowed_actions=actions,
                                             qualified_at=_stamp(row["qualified_at"]),
                                             expires_at=_stamp(row["expires_at"]),
                                             revision=row["effective_revision"])
            else:
                result = dataclasses.replace(base, allowed_actions=("status",), expires_at=_stamp(policy["expires"]),
                                             revision=_hash({"mode": "diagnostic", "base": base.revision,
                                                             "policy": policy["revision"]}))
        self._current()
        return result
