"""Original request-to-auth-input custody composition; uninstalled source.

This is not the native installation factory. The SAME original installation
must already own its process/principal/source/writer fence, server, gate and
tables. Exact classes are refusal filters. No supplied map, UID, deadline,
clock, verifier or cleanup callback is accepted by this component.
"""
import math
import threading
import time

from freq.services.cluster_pilot_http import _OriginalPilotServer, _RequestUnavailable
from freq.services.pilot_auth_input_attempt import OriginalAuthInputAttempt


def _first(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception) or
            not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


class _AttemptGate:
    def __init__(self, attempts, original=None, cleanup=False):
        self._attempts, self._original, self._cleanup = attempts, original, cleanup
        self._state = 'unused'

    def __enter__(self):
        first = None
        try:
            if self._cleanup:
                self._state = 'acquire-pending'
                acquired = self._attempts._installation._gate.acquire(blocking=False)
            else:
                left = self._original.end - time.monotonic()
                if not math.isfinite(left) or left <= 0:
                    self._state = 'not-acquired'
                    raise _RequestUnavailable()
                self._state = 'acquire-pending'
                acquired = self._attempts._installation._gate.acquire(timeout=left)
            self._state = 'owned' if acquired else 'not-acquired'
            if not acquired:
                raise _RequestUnavailable()
            if not self._cleanup:
                self._attempts._current_locked(self._original)
            return self
        except BaseException as error:
            first = error
        if self._state == 'acquire-pending' or self._cleanup:
            first = self._attempts._uncertain(first)
        raise self._release(first)

    def _release(self, first):
        if self._state == 'owned':
            self._state = 'release-attempted'
            try:
                self._attempts._installation._gate.release()
            except BaseException as error:
                self._state = 'uncertain'
                first = self._attempts._uncertain(_first(first, error))
            else:
                self._state = 'released'
        return first

    def __exit__(self, kind, original_error, traceback):
        chosen = self._release(original_error)
        if chosen is not None and chosen is not original_error:
            raise chosen
        return False


class OriginalPilotAuthAttempts:
    def __init__(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(installation) is not OriginalPilotInstallation or
                type(installation._server) is not _OriginalPilotServer or
                installation._server._cluster_pilot_installation is not installation or
                type(installation._auth_attempts) is not dict):
            raise _RequestUnavailable()
        self._installation = installation
        self._broker = installation._server._pilot_requests

    def _uncertain(self, first):
        for target, field, value in ((self._installation, '_admission_uncertain', True),
                                     (self._installation, '_live', False),
                                     (self._broker, '_live', False)):
            try:
                setattr(target, field, value)
            except BaseException as error:
                first = _first(first, error)
        return first

    def _current_locked(self, original):
        owner = self._installation
        if (not owner._live or owner._admission_uncertain or not self._broker._live or
                self._broker._gate_uncertain or
                self._broker._requests.get(original.socket) is not original or
                original.handler is None or original.phase != 'ready' or
                original.handler.server is not owner._server or
                original.handler.request is not original.socket or
                original.thread is not threading.current_thread() or
                not time.monotonic() < original.end or
                owner._native_current_locked(original) is not True):
            raise _RequestUnavailable()

    def _retained_locked(self, attempt, original):
        self._current_locked(original)
        owner = self._installation
        if (owner._auth_attempts.get(attempt) is not original or
                attempt._thread is not original.thread or
                attempt._end != original.end or
                attempt._state not in ('retained', 'verified') or
                attempt._cleanup != 'not-attempted' or
                attempt._user != original.login_username or
                owner._configured_roles.get(attempt._user) != attempt._role or
                attempt._user == owner._service_user):
            raise _RequestUnavailable()

    def begin_auth(self, handler, username):
        original = self._broker._owned(handler)
        if (original.operation != 'login' or original.phase != 'ready' or
                original.body_taken is not True or
                type(username) is not str or username != original.login_username):
            raise _RequestUnavailable()
        owner = self._installation
        # Constructor allocates actual reader/decrypt duty holders only. Native
        # acquisition starts AFTER this SAME object is in the original table.
        attempt = OriginalAuthInputAttempt(owner._source_uid, owner._credential_uid,
                                           original.end)
        retained = False
        first = None
        try:
            with _AttemptGate(self, original):
                if original.auth_attempted or len(owner._auth_attempts) >= 64:
                    raise _RequestUnavailable()
                original.auth_attempted = True  # Permanent even after retirement.
                try:
                    owner._auth_attempts[attempt] = original
                except BaseException as error:
                    raise self._uncertain(error)
                retained = True
            acquired = attempt.acquire(username)  # No admission gate is held.
            if acquired is None:
                self.retire_auth(attempt)
                retained = False
                return None
            if acquired is not attempt or self.auth_current(attempt) is not True:
                raise _RequestUnavailable()
            return attempt
        except BaseException as error:
            attempt._request_errors[0] = error
            first = error
        # retire_auth spends the same attempt before its first cleanup effect.
        # A failed acquired-None retirement must not be attempted again here.
        if retained and attempt._request_retirement_started is False:
            try:
                self.retire_auth(attempt)
            except BaseException as cleanup:
                attempt._request_errors[2] = cleanup
                first = _first(first, cleanup)
        first = attempt._request_failure = _first(attempt._request_failure, first)
        if first is not None and (not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        raise _RequestUnavailable() from None

    def auth_current(self, attempt):
        if type(attempt) is not OriginalAuthInputAttempt:
            raise _RequestUnavailable()
        original = self._installation._auth_attempts.get(attempt)
        if original is None:
            raise _RequestUnavailable()
        with _AttemptGate(self, original):
            self._retained_locked(attempt, original)
        # Actual held/named file diagnostics are outside every admission lock.
        # They do not replace the original physical writer/currentness fence.
        attempt._current_data()
        with _AttemptGate(self, original):
            self._retained_locked(attempt, original)
        return True  # Diagnostic only; final original commit remains mandatory.

    def retire_auth(self, attempt):
        if type(attempt) is not OriginalAuthInputAttempt:
            raise _RequestUnavailable()
        owner = self._installation
        original = owner._auth_attempts.get(attempt)
        if original is None or attempt._thread is not threading.current_thread():
            raise _RequestUnavailable()
        if attempt._request_retirement_started is not False:
            raise _RequestUnavailable()
        # Once only, before native input retirement or cleanup-gate acquisition.
        # An unresolved table entry and native duties remain for the parent.
        attempt._request_retirement_started = True
        first = None
        try:
            attempt.retire()  # Independent native close, outside every gate.
        except BaseException as error:
            attempt._request_errors[1] = error
            first = self._uncertain(error)
        if first is None:
            try:
                if owner._admission_uncertain or self._broker._gate_uncertain:
                    raise _RequestUnavailable()
                # Never wait beyond the original end to refund table capacity.
                # Failed/ambiguous cleanup locking keeps the original entry and
                # disables new work; outer actual supervisor still owes closure.
                with _AttemptGate(self, cleanup=True):
                    if (owner._auth_attempts.get(attempt) is not original or
                            attempt._state != 'retired' or
                            attempt._cleanup != 'locally-settled'):
                        raise _RequestUnavailable()
                    try:
                        del owner._auth_attempts[attempt]
                    except BaseException as error:
                        raise self._uncertain(error)
            except BaseException as error:
                attempt._request_errors[1] = error
                first = self._uncertain(error)
        if first is not None:
            first = attempt._request_failure = _first(attempt._request_failure, first)
            if not isinstance(first, Exception) or isinstance(first, MemoryError):
                raise first
            raise _RequestUnavailable() from None


# No native factory, source/profile or credential rights are supplied here.
