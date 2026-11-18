"""Original-store ordered auth/response transaction component, WIP SOURCE.

No installation factory is provided here. The actual constructor-owned
OriginalPilotInstallation must retain its source/credential/process/writer
fence, original server, request/attempt and issued-session tables first. Its
fixed _native_current_locked operation must do NO native IO, hashing,
serialization, callback or new acquisition under these admission gates.

An absent actual owner refuses; no configuration flag, supplied map/lock,
serializer, predicate or fixture owner can initialize this component. Source
alone does not establish original native authority or qualify execution.
"""
import hmac
import json
import math
import secrets
import sys
import time

from freq.api import auth
from freq.services.cluster_pilot_http import (
    OriginalPilotResponse, _OriginalPilotServer, _RequestUnavailable,
)
from freq.services.cluster_references import ClusterReferences, _Reference
from freq.services.pilot_auth_input_attempt import OriginalAuthInputAttempt
from freq.services.pilot_guest_retirement import retire_guest_session_data_locked


_ROLES = ('viewer', 'operator', 'admin', 'protected')
_SESSION_FIELDS = ('user', 'role', 'ts', 'last_activity_ts', 'csrf_token')
_SESSION_LIMIT = 1024


def _first(first, later):
    # Stable control > allocation failure > ordinary failure priority.
    # Cleanup never hides a MemoryError behind an earlier ordinary error.
    if first is None or (issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception) or
            not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError))):
        return later
    return first


def _json_response(status, value, cookie=None):
    # Only fixed callers below select these values. Build BEFORE all gates.
    return OriginalPilotResponse(status, json.dumps(value, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('ascii'),
        'application/json', cookie)


def _cookie(token, clear=False):
    return ('freq_session=' + token + '; HttpOnly; SameSite=Strict; Path=/; '
            'Max-Age=' + ('0' if clear else str(auth.SESSION_TIMEOUT_SECONDS)) + '; Secure')


class _OrderedAuthGates:
    """Retain known AND pending gate duties, with one original shortened end.

    Unknown lock acquisition/release disables this entire original instance;
    no raw release of an ambiguously acquired lock or continuation is allowed.
    The actual outer owner still owes physical retirement of lost execution.
    """
    def __init__(self, transaction, original, phase='ready'):
        if phase not in ('ready', 'admitted'):
            raise _RequestUnavailable()
        self._transaction = transaction
        self._original = original
        self._phase = phase
        self._locks = (transaction._installation._gate, auth._auth_lock,
                       transaction._references._lock, transaction._broker._gate)
        self._states = ['unused'] * 4

    def __enter__(self):
        first = None
        try:
            for index, lock in enumerate(self._locks):
                remaining = self._original.end - time.monotonic()
                if not math.isfinite(remaining) or remaining <= 0:
                    raise _RequestUnavailable()
                self._states[index] = 'acquire-pending'
                acquired = lock.acquire(timeout=remaining)
                self._states[index] = 'owned' if acquired else 'not-acquired'
                if not acquired or not time.monotonic() < self._original.end:
                    raise _RequestUnavailable()
            self._transaction._current_locked(self._original, self._phase)
            return self
        except BaseException as error:
            first = error
        first = self._release(first)
        raise first

    def _release(self, first):
        for index in range(3, -1, -1):
            if self._states[index] == 'owned':
                self._states[index] = 'release-attempted'
                try:
                    self._locks[index].release()
                except BaseException as error:
                    self._states[index] = 'uncertain'
                    first = _first(first, error)
                    first = self._transaction._uncertain(first)
                else:
                    self._states[index] = 'released'
            elif self._states[index] == 'acquire-pending':
                first = _first(first, _RequestUnavailable())
                first = self._transaction._uncertain(first)
        return first

    def __exit__(self, kind, original_error, traceback):
        selected = self._release(original_error)
        if selected is not None and selected is not original_error:
            raise selected
        return False


class OriginalAuthCommit:
    """Use the actual original auth map and original reference/request tables.

    Constructor exact-type checks are refusal filters, not source authority.
    The actual installation/native factory is still unfinished and may not be
    substituted by a supplied positive object merely to execute these methods.
    """
    def __init__(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(installation) is not OriginalPilotInstallation or
                type(installation._server) is not _OriginalPilotServer or
                installation._server._cluster_pilot_installation is not installation or
                type(installation._references) is not ClusterReferences):
            raise _RequestUnavailable()
        self._installation = installation
        self._broker = installation._server._pilot_requests
        self._references = installation._references

    def _uncertain(self, first):
        # Retirement-only, never a grant or cleanup confirmation. No wait or
        # native work: the original outer supervisor must settle the instance.
        for target, field, value in ((self._installation, '_admission_uncertain', True),
                                     (self._installation, '_live', False),
                                     (self._broker, '_live', False)):
            try:
                setattr(target, field, value)
            except BaseException as error:
                first = _first(first, error)
        return first

    def _current_locked(self, original, phase):
        owner = self._installation
        if (not owner._live or owner._admission_uncertain or not self._broker._live or
                self._broker._gate_uncertain or
                self._broker._requests.get(original.socket) is not original or
                original.handler is None or original.phase != phase or
                original.handler.server is not owner._server or
                original.handler.request is not original.socket or
                not time.monotonic() < original.end or
                owner._native_current_locked(original) is not True):
            raise _RequestUnavailable()

    def _original(self, handler, operation):
        original = self._broker._owned(handler)
        if original.operation != operation or original.phase != 'ready':
            raise _RequestUnavailable()
        return original

    def _retire_session_locked(self, token, session):
        # Original ordered auth caller already holds the SAME installation,
        # auth, references and HTTP gates. Cleanup itself grants no authority.
        if (type(token) is not str or not 0 < len(token) <= 512 or
                type(session) is not dict or self._installation._auth_commit is not self):
            raise _RequestUnavailable()
        first = None
        try:
            retire_guest_session_data_locked(self._installation, session)
        except BaseException as error:
            first = _first(first, error)
            first = self._uncertain(first)
        # Every independent original table/session duty is still attempted
        # after a guest cleanup failure. No replacement map or silent refund.
        for records in (self._references._selections, self._references._bindings):
            try:
                if type(records) is not dict or len(records) > ClusterReferences.PROCESS_LIMIT:
                    raise _RequestUnavailable()
                rows = tuple(records.items())
            except BaseException as error:
                first = _first(first, error)
                first = self._uncertain(first)
                rows = ()
            for key, record in rows:
                try:
                    # Independent known-row duty. Never let an early bad
                    # row or interrupted deletion skip later original rows.
                    # Snapshot identity refuses a changed/replaced entry.
                    if (type(records) is not dict or
                            type(key) is not str or
                            not ClusterReferences._valid_reference(key) or
                            records.get(key) is not record or
                            type(record) is not _Reference):
                        raise _RequestUnavailable()
                    if record.session is session:
                        del records[key]
                except BaseException as error:
                    first = _first(first, error)
                    first = self._uncertain(first)
        for sessions in (auth._auth_tokens, self._installation._issued_sessions):
            try:
                if sessions.get(token) is session:
                    del sessions[token]
            except BaseException as error:
                first = _first(first, error)
                first = self._uncertain(first)
        if first is not None:
            raise first

    def _capture_session(self, handler, operation):
        original = self._original(handler, operation)
        token, source = auth._extract_session_token_and_source(handler)
        if type(token) is not str or len(token) > 512:
            raise _RequestUnavailable()
        with _OrderedAuthGates(self, original):
            session = auth._auth_tokens.get(token)
            if (type(session) is not dict or
                    self._installation._issued_sessions.get(token) is not session):
                return original, token, source, None, None
            values = tuple(session.get(key) for key in _SESSION_FIELDS)
        return original, token, source, session, values

    def _same_session_locked(self, token, session, values, now):
        if (type(session) is not dict or values is None or
                auth._auth_tokens.get(token) is not session or
                self._installation._issued_sessions.get(token) is not session or
                tuple(session.get(key) for key in _SESSION_FIELDS) != values):
            return False
        user, role, issued, last, csrf = values
        return (type(user) is str and type(role) is str and role in _ROLES and type(csrf) is str and
                self._installation._configured_roles.get(user) == role and
                user != self._installation._service_user and
                type(issued) in (float, int) and type(last) in (float, int) and
                math.isfinite(issued) and math.isfinite(last) and
                0 <= now - issued and 0 <= now - last < auth.SESSION_TIMEOUT_SECONDS)

    def admit_login(self, handler, attempt):
        original = self._original(handler, 'login')
        if type(attempt) is not OriginalAuthInputAttempt:
            raise _RequestUnavailable()
        user, role = attempt._user, attempt._role
        if type(user) is not str or type(role) is not str or role not in _ROLES:
            raise _RequestUnavailable()
        # Actual randomness/hash/serialization are OUTSIDE every gate.
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), time.time()
        if not math.isfinite(now):
            raise _RequestUnavailable()
        session = dict(user=user, role=role, ts=now, last_activity_ts=now, csrf_token=csrf)
        frame = _json_response(200, {'ok': True, 'token': token, 'csrf_token': csrf,
            'auth_mode': 'cookie', 'user': user, 'role': role}, _cookie(token))
        # Exact bounded-rate implementation is Finn's current source join.
        # Missing component refuses; never fall back to the legacy unbounded
        # _login_lock path. This rate update is not final session admission.
        from freq.services.pilot_login_rate import OriginalPilotLoginRate
        rate = self._installation._login_rate
        if type(rate) is not OriginalPilotLoginRate:
            raise _RequestUnavailable()
        rate.record_success(handler, attempt)
        with _OrderedAuthGates(self, original):
            if (self._installation._auth_attempts.get(attempt) is not original or
                    attempt._state != 'verified' or attempt._verified is not True or
                    not time.monotonic() < attempt._end <= original.end or
                    attempt._user != user or attempt._role != role or
                    self._installation._configured_roles.get(user) != role or
                    user == self._installation._service_user or
                    token in auth._auth_tokens or
                    len(auth._auth_tokens) >= _SESSION_LIMIT):
                raise _RequestUnavailable()
            try:
                # Admit original frame first while all gates exclude writers.
                # If any later Python mutation is interrupted, disable the
                # complete instance BEFORE release, so its frame cannot write.
                self._broker._admit_frame_locked(handler, original, frame)
                auth._auth_tokens[token] = session
                self._installation._issued_sessions[token] = session
                # Keep the original attempt in its cleanup table until actual
                # owner retirement settles its descriptors. The spent native
                # request/frame already prevents a second admission.
            except BaseException as error:
                raise self._uncertain(error)
        return frame

    def admit_verify(self, handler):
        original, token, source, session, values = self._capture_session(handler, 'verify')
        now = time.time()
        if not math.isfinite(now):
            raise _RequestUnavailable()
        invalid = _json_response(401, {'error': 'Authentication required'})
        stale = _json_response(503, {'error': 'Cluster authentication unavailable'})
        touch = auth._session_touch_requested(handler)
        frame = invalid
        if values is not None:
            user, role, issued, last, csrf = values
            # Data validation precedes any arithmetic/serialization. Final
            # identity/currentness is checked again in the ordered transaction.
            if (type(user) is str and type(role) is str and role in _ROLES and type(csrf) is str and
                    type(issued) in (float, int) and type(last) in (float, int) and
                    math.isfinite(issued) and math.isfinite(last)):
                idle = 0 if touch else max(0, int(now - last))
                frame = _json_response(200, {'valid': True, 'user': user, 'role': role,
                    'session_age_s': max(0, int(now - issued)), 'session_idle_s': idle,
                    'session_ttl_s': max(0, auth.SESSION_TIMEOUT_SECONDS - idle),
                    'session_timeout_s': auth.SESSION_TIMEOUT_SECONDS, 'csrf_token': csrf,
                    'auth_mode': 'cookie'},
                    _cookie(token) if touch else None)
        with _OrderedAuthGates(self, original):
            current = self._same_session_locked(token, session, values, time.time())
            changed = (session is not None and auth._auth_tokens.get(token) is session and
                       tuple(session.get(key) for key in _SESSION_FIELDS) != values)
            chosen = stale if changed else frame if current and frame is not invalid else invalid
            try:
                self._broker._admit_frame_locked(handler, original, chosen)
                if current and touch:
                    session['last_activity_ts'] = now
                elif (not current and not changed and session is not None and
                      auth._auth_tokens.get(token) is session):
                    self._retire_session_locked(token, session)
            except BaseException as error:
                raise self._uncertain(error)
        return chosen

    def admit_logout(self, handler):
        original, token, source, session, values = self._capture_session(handler, 'logout')
        supplied = handler.headers.get('X-Freq-CSRF', '')
        csrf_ok = (source == 'bearer' or (values is not None and
            type(values[4]) is str and type(supplied) is str and
            supplied.isascii() and values[4].isascii() and
            hmac.compare_digest(supplied, values[4])))
        invalid = _json_response(401, {'error': 'Authentication required'})
        stale = _json_response(503, {'error': 'Cluster authentication unavailable'})
        denied = _json_response(403, {'error': 'CSRF token missing or invalid'})
        success = _json_response(200, {'ok': True, 'revocation_confirmed': True}, _cookie('', True))
        with _OrderedAuthGates(self, original):
            current = self._same_session_locked(token, session, values, time.time())
            changed = (session is not None and auth._auth_tokens.get(token) is session and
                       tuple(session.get(key) for key in _SESSION_FIELDS) != values)
            chosen = stale if changed else success if current and csrf_ok else denied if current else invalid
            try:
                self._broker._admit_frame_locked(handler, original, chosen)
                if current and csrf_ok:
                    self._retire_session_locked(token, session)
            except BaseException as error:
                raise self._uncertain(error)
        return chosen

    def write_admitted_response(self, handler, response):
        original = self._broker._owned(handler)
        with _OrderedAuthGates(self, original, 'admitted'):
            self._broker._reserve_write_locked(handler, original, response)
        # Every installation/auth/reference gate is released. Fixed original
        # broker spends the final native-send attempt under its own gate and
        # releases that too before socket IO. Partial/spent/expired attempts
        # cannot append bytes or reissue the original frame.
        return self._broker._send_reserved(handler, response)


# Missing actual native factory stays missing; never fabricate a fixture owner.
