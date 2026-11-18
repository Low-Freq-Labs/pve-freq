"""Bounded original-store login bookkeeping; SOURCE ONLY, no issuer.

Only actual OriginalPilotInstallation retains this component. Its broker must
retain OriginalLoginRateDuty on the accepted request BEFORE dispatch, pin the
actual accept peer, and bind the claiming thread. These missing joins are not
implemented by constructing a lookalike request or installation for this file.
No admission lock is acquired here. Success bookkeeping never grants a session.
"""
import math
import re
import threading
import time



_USERNAME = re.compile(r'[a-z_][a-z0-9_-]{0,31}', re.ASCII)
_KEYS_PER_MAP = 1024
_EVENTS_PER_KEY = 64
_EVENTS_TOTAL = 8192


def _unavailable():
    # Lazy: the original broker imports OriginalLoginRateDuty at startup.
    # Do not import its partially initialized classes while defining that duty.
    from freq.services.cluster_pilot_http import _RequestUnavailable
    return _RequestUnavailable()


def _first(first, later):
    if first is None or (isinstance(first, Exception)
                         and not isinstance(later, Exception)):
        return later
    return first


class OriginalLoginRateDuty:
    """Preallocated on the ORIGINAL request, not issued by an auth caller.

    The original broker owns request identity/end/peer/thread and retirement.
    States survive failure, expiry and ambiguous lock acquisition/release. The
    actual outer owner must physically retire uncertainty; no local flag proves
    cleanup. Never reset/reuse this holder for another request or retry.
    """
    __slots__ = ('check', 'record', 'lock', 'username', 'peer', 'allowed')

    def __init__(self):
        self.check = self.record = 'unused'
        self.lock = 'unused'
        self.username = self.peer = None
        self.allowed = False


class OriginalPilotLoginRate:
    def __init__(self, installation):
        from freq.api import auth
        from freq.services.cluster_pilot_http import _OriginalPilotServer, _OriginalHTTPRequests
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(installation) is not OriginalPilotInstallation or
                type(installation._server) is not _OriginalPilotServer or
                installation._server._cluster_pilot_installation is not installation or
                type(installation._server._pilot_requests) is not _OriginalHTTPRequests):
            raise _unavailable()
        self._auth = auth
        self._installation = installation
        self._broker = installation._server._pilot_requests
        self._lock = auth._login_lock
        self._ip = auth._login_attempts_ip
        self._user = auth._login_attempts_user

    def _uncertain(self, first):
        # No clock, wait or second lock here; retirement only. Actual supervisor
        # closure remains mandatory when return/ownership cannot be established.
        for target, name, value in ((self._installation, '_admission_uncertain', True),
                                    (self._installation, '_live', False),
                                    (self._broker, '_live', False)):
            try:
                setattr(target, name, value)
            except BaseException as error:
                first = _first(first, error)
        return first

    def _current(self, handler, original):
        owner = self._installation
        if (owner._login_rate is not self or not owner._live or
                owner._admission_uncertain or not self._broker._live or
                self._broker._gate_uncertain or
                self._auth._login_lock is not self._lock or
                self._auth._login_attempts_ip is not self._ip or
                self._auth._login_attempts_user is not self._user or
                self._broker._server is not owner._server or
                owner._server._cluster_pilot_installation is not owner or
                self._broker._requests.get(original.socket) is not original or
                original.socket is not handler.request or original.handler is not handler or
                handler.server is not owner._server or original.operation != 'login' or
                original.phase != 'ready' or original.thread is not threading.current_thread() or
                type(original.end) not in (float, int) or not math.isfinite(original.end) or
                not time.monotonic() < original.end):
            raise _unavailable()

    def _original(self, handler, username):
        from freq.services.cluster_pilot_http import _OriginalRequest
        original = self._broker._owned(handler)
        if type(original) is not _OriginalRequest:
            raise _unavailable()
        self._current(handler, original)
        duty = original.login_rate
        peer = original.peer_ip  # actual accept address, NOT XFF or handler flag
        if (type(duty) is not OriginalLoginRateDuty or type(peer) is not str or
                not 1 <= len(peer) <= 64 or not peer.isascii() or
                type(username) is not str or _USERNAME.fullmatch(username) is None or
                original.body_taken is not True or
                type(original.login_username) is not str or
                original.login_username != username):
            raise _unavailable()
        return original, duty, peer

    def _release(self, duty, first):
        # Independent of deadline/clock. Exactly one release for known ownership;
        # ambiguous ownership is never guessed and release is never retried.
        if duty.lock == 'owned':
            duty.lock = 'release-attempted'
            try:
                self._lock.release()
            except BaseException as error:
                duty.lock = 'uncertain'
                first = self._uncertain(_first(first, error))
            else:
                duty.lock = 'released'
        elif duty.lock in ('acquire-pending', 'release-attempted', 'uncertain'):
            first = self._uncertain(_first(first, _unavailable()))
        return first

    def _inventory(self, now):
        # Validate lengths BEFORE iteration, snapshots, pruning or list growth.
        # Actual frozen original maps only; no substituted caller store.
        total = 0
        for store, key_max in ((self._ip, 64), (self._user, 32)):
            if type(store) is not dict or len(store) > _KEYS_PER_MAP:
                raise _unavailable()
            for key, rows in store.items():
                if (type(key) is not str or not 1 <= len(key) <= key_max or
                        not key.isascii() or type(rows) is not list or
                        len(rows) > _EVENTS_PER_KEY):
                    raise _unavailable()
                total += len(rows)
                if total > _EVENTS_TOTAL:
                    raise _unavailable()
                for row in rows:
                    if (type(row) is not tuple or len(row) != 2 or
                            type(row[0]) not in (float, int) or
                            not math.isfinite(row[0]) or type(row[1]) is not bool):
                        raise _unavailable()
        # In-place expiration is bounded by the validated inventory. Future
        # timestamps on wall-clock rollback remain; active failures are kept.
        total = 0
        for store in (self._ip, self._user):
            empty = []
            for key, rows in store.items():
                removed = False
                for index in range(len(rows) - 1, -1, -1):
                    if now - rows[index][0] >= self._auth._RATE_WINDOW_SECONDS:
                        del rows[index]
                        removed = True
                if removed and not rows:
                    empty.append(key)
                total += len(rows)
            for key in empty:
                del store[key]
        return total

    def _work(self, handler, username, operation, attempt=None):
        original, duty, peer = self._original(handler, username)
        if operation == 'check':
            if duty.check != 'unused' or duty.record != 'unused':
                raise _unavailable()
            duty.username, duty.peer = username, peer
            duty.check = 'pending'  # consumed BEFORE any wait
        else:
            if (duty.check != 'done' or duty.allowed is not True or
                    duty.record != 'unused' or duty.username != username or duty.peer != peer):
                raise _unavailable()
            duty.record = 'pending'  # success/failure share ONE record duty
        first = None
        result = None
        mutating = False
        try:
            remaining = original.end - time.monotonic()
            if not math.isfinite(remaining) or remaining <= 0:
                raise _unavailable()
            duty.lock = 'acquire-pending'
            acquired = self._lock.acquire(timeout=remaining)
            duty.lock = 'owned' if acquired else 'not-acquired'
            if acquired is not True:
                raise _unavailable()
            self._current(handler, original)  # includes clock AFTER lock wait
            now = time.time()
            if not math.isfinite(now):
                raise _unavailable()
            # Expiration is itself a mutation; any interrupted traversal leaves
            # the original instance disabled rather than continuing uncertainly.
            mutating = True
            total = self._inventory(now)
            mutating = False
            ip_rows = self._ip.get(peer)
            user_rows = self._user.get(username)
            if operation == 'check':
                allowed = (sum(not row[1] for row in (ip_rows or ())) < self._auth._RATE_MAX_FAILURES_IP and
                           sum(not row[1] for row in (user_rows or ())) < self._auth._RATE_MAX_FAILURES_USER)
                duty.allowed = allowed
                self._current(handler, original)
                duty.check = 'done'
                result = allowed
            else:
                if operation == 'success':
                    from freq.services.pilot_auth_input_attempt import OriginalAuthInputAttempt
                    if (type(attempt) is not OriginalAuthInputAttempt or
                            self._installation._auth_attempts.get(attempt) is not original or
                            attempt._state != 'verified' or attempt._verified is not True or
                            attempt._user != username or attempt._thread is not original.thread or
                            not time.monotonic() < attempt._end <= original.end):
                        raise _unavailable()
                success = operation == 'success'
                # Check peak capacity BEFORE all allocations/growth, including
                # success's temporary event BEFORE its policy failure clearing.
                if (total + 2 > _EVENTS_TOTAL or
                        (ip_rows is None and len(self._ip) >= _KEYS_PER_MAP) or
                        (user_rows is None and len(self._user) >= _KEYS_PER_MAP) or
                        (ip_rows is not None and len(ip_rows) >= _EVENTS_PER_KEY) or
                        (user_rows is not None and len(user_rows) >= _EVENTS_PER_KEY)):
                    raise _unavailable()
                event = (now, success)
                mutating = True
                if ip_rows is None:
                    ip_rows = []
                    self._ip[peer] = ip_rows
                if user_rows is None:
                    user_rows = []
                    self._user[username] = user_rows
                ip_rows.append(event)
                user_rows.append(event)
                if success:
                    for index in range(len(user_rows) - 1, -1, -1):
                        if not user_rows[index][1]:
                            del user_rows[index]
                self._current(handler, original)
                duty.record = 'done'
                mutating = False
        except BaseException as error:
            first = error
            if mutating:
                first = self._uncertain(first)
        finally:
            first = self._release(duty, first)
        if first is not None:
            raise first
        return result

    def check(self, handler, username):
        return self._work(handler, username, 'check')

    def record_failure(self, handler, username):
        return self._work(handler, username, 'failure')

    def record_success(self, handler, attempt):
        from freq.services.pilot_auth_input_attempt import OriginalAuthInputAttempt
        if type(attempt) is not OriginalAuthInputAttempt:
            raise _unavailable()
        return self._work(handler, attempt._user, 'success', attempt)


# Actual native factory, broker duty/peer/thread join, writer fence and original
# final transaction remain absent. No candidate import/test/install is selected.
