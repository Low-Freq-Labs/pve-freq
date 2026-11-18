"""Original observed read transactions; uninstalled source, no factory.

Actual native source/credential/trust/cohort and writer-fence authority must
already belong to the SAME original installation. Constructor/type/data/table
checks are refusal filters. This module neither creates that authority nor
enables an HTTP route; the original handler remains unavailable until joined.
"""
import hmac
import math
import threading
import time

from freq.api import auth
from freq.services.cluster_pilot_http import (
    OriginalPilotResponse, _OriginalRequest, _RequestUnavailable,
)
from freq.services.pilot_auth_commit import OriginalAuthCommit, _OrderedAuthGates
from freq.services.pilot_cluster_selections import OriginalClusterSelections, _SelectionRefused
from freq.services.pilot_cluster_read_attempt import (
    OriginalPrivateClusterRead, NAMED_PAYLOAD_RESERVATION,
)


_READS_LIMIT = 64


def _first(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception) or
            not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


class _ReadGates(_OrderedAuthGates):
    """Same four original gates, with a separately shortened read end.

    The broker's original accepted end is never replaced. Both ends are
    original-owner retained data; the actual parent still owes native custody.
    Cleanup acquires nonblocking and does not require live/eligible participants.
    """
    def __init__(self, transaction, original, read_end, phase='ready', cleanup=False):
        super().__init__(transaction, original, phase)
        if (type(read_end) is not float or not math.isfinite(read_end) or
                read_end > original.end):
            raise _RequestUnavailable()
        self._read_end = read_end
        self._cleanup = cleanup

    def __enter__(self):
        first = None
        try:
            for index, lock in enumerate(self._locks):
                if self._cleanup:
                    self._states[index] = 'acquire-pending'
                    acquired = lock.acquire(blocking=False)
                else:
                    remaining = min(self._read_end, self._original.end) - time.monotonic()
                    if not math.isfinite(remaining) or remaining <= 0:
                        raise _RequestUnavailable()
                    self._states[index] = 'acquire-pending'
                    acquired = lock.acquire(timeout=remaining)
                self._states[index] = 'owned' if acquired else 'not-acquired'
                if not acquired:
                    raise _RequestUnavailable()
                if not self._cleanup and not time.monotonic() < min(
                        self._read_end, self._original.end):
                    raise _RequestUnavailable()
            if not self._cleanup:
                self._transaction._current_locked(self._original, self._phase)
            return self
        except BaseException as error:
            first = error
        if self._cleanup:
            first = self._transaction._uncertain(first)
        raise self._release(first)


class _ReadDuty:
    """Private retained invocation record; construction grants no authority."""
    __slots__ = ('original', 'token', 'session', 'values', 'nodes',
                 'configured_token', 'credential_uid', 'bound',
                 'read_end', 'attempt', 'charge', 'phase', 'response')

    def __init__(self, original, token, session, values, nodes,
                 configured_token, credential_uid, bound,
                 read_end, attempt):
        self.original, self.token, self.session, self.values = original, token, session, values
        self.nodes = nodes
        self.configured_token, self.credential_uid = configured_token, credential_uid
        self.bound, self.read_end = bound, read_end
        self.attempt = attempt
        self.charge = NAMED_PAYLOAD_RESERVATION
        self.phase = 'new'
        self.response = None


class OriginalClusterReads:
    """Consume one original binding and admit one private prepared response.

    The native installation constructor must own _read_attempts (a new private
    dict), a distinct original _native_read_attempts dictionary, actual
    _configured_nodes, _configured_token_id and _credential_uid. The native
    table is retirement-only and must survive logical request/read removal.
    There is no clear/release API; actual outer process retirement is owed.
    The same private read acquires its fixed existing-system CA/context and
    uses the original configured endpoint IP as TLS recipient. Actual native
    source/credential/trust writer-fence/currentness remains original-parent
    duty, not this data representation. Missing native factory still means
    no positive operation.
    """
    def __init__(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(installation) is not OriginalPilotInstallation or
                type(installation._auth_commit) is not OriginalAuthCommit or
                installation._auth_commit._installation is not installation or
                type(installation._cluster_selections) is not OriginalClusterSelections or
                installation._cluster_selections._installation is not installation or
                installation._cluster_selections._auth is not installation._auth_commit or
                type(installation._read_attempts) is not dict or
                type(installation._native_read_attempts) is not dict or
                installation._native_read_attempts is installation._read_attempts):
            raise _SelectionRefused(503)
        self._installation = installation
        self._auth = installation._auth_commit
        self._selections = installation._cluster_selections
        self._broker = self._auth._broker
        self._references = self._auth._references
        self._attempts = installation._read_attempts
        self._native_attempts = installation._native_read_attempts

    def _uncertain(self, first):
        return self._auth._uncertain(first)

    def _session_locked(self, original, token, session, values, phase='ready'):
        self._auth._current_locked(original, phase)
        if (original.thread is not threading.current_thread() or
                not self._auth._same_session_locked(token, session, values, time.time())):
            raise _SelectionRefused(403)

    def _cohort_locked(self):
        owner = self._installation
        nodes = self._selections._cohort_locked()
        token = owner._configured_token_id
        uid = owner._credential_uid
        if (type(token) is not tuple or len(token) != 2 or
                any(type(value) is not str for value in token) or
                type(uid) is not int or not 0 <= uid <= 4294967294):
            raise _SelectionRefused(503)
        return nodes, token, uid

    def _tables_locked(self):
        if (self._installation._read_attempts is not self._attempts or
                self._installation._native_read_attempts is not self._native_attempts or
                self._attempts is self._native_attempts or
                type(self._attempts) is not dict or type(self._native_attempts) is not dict or
                len(self._attempts) > _READS_LIMIT or len(self._native_attempts) > _READS_LIMIT):
            raise _SelectionRefused(503)
        # The native table is the original strong reference, not a cleanup flag.
        # Retired logical requests remain here with SAME attempt/context/native
        # pending allocations until the actual parent physically retires this
        # entire process. Closed local FDs never remove/refund these duties.
        for original, duty in self._native_attempts.items():
            if (type(original) is not _OriginalRequest or type(duty) is not _ReadDuty or
                    duty.original is not original or
                    type(duty.attempt) is not OriginalPrivateClusterRead or
                    duty.attempt._thread is not original.thread or
                    type(duty.read_end) is not float or not math.isfinite(duty.read_end) or
                    duty.read_end > original.end or duty.attempt._end != duty.read_end or
                    type(duty.charge) is not int or duty.charge != NAMED_PAYLOAD_RESERVATION or
                    duty.phase not in ('running', 'prepared', 'admitted', 'write-reserved', 'retired')):
                raise _SelectionRefused(503)
        for original, duty in self._attempts.items():
            if self._native_attempts.get(original) is not duty:
                raise _SelectionRefused(503)

    def _same_locked(self, duty, phase='ready'):
        original = duty.original
        self._session_locked(original, duty.token, duty.session, duty.values, phase)
        self._tables_locked()
        nodes, token, uid = self._cohort_locked()
        if (self._attempts.get(original) is not duty or
                duty.phase != ('prepared' if phase == 'ready' else 'admitted') or
                type(duty.response) is not OriginalPilotResponse or
                duty.attempt._state != 'retired' or duty.attempt._cleanup != 'locally-closed' or
                nodes is not duty.nodes or
                token is not duty.configured_token or uid != duty.credential_uid or
                duty.charge != NAMED_PAYLOAD_RESERVATION or
                not time.monotonic() < duty.read_end):
            raise _SelectionRefused(409)

    def _capture(self, handler, key):
        if (not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler, require_present=True, is_https=True)):
            raise _SelectionRefused(403)
        original, token, source, session, values = self._auth._capture_session(handler, 'read')
        if original.body_taken is not True:
            raise _SelectionRefused(400)
        with _ReadGates(self._auth, original, original.end):
            self._session_locked(original, token, session, values)
            if source != 'bearer':
                supplied = handler.headers.get('X-Freq-CSRF', '')
                if (values is None or type(values[4]) is not str or
                        type(supplied) is not str or not supplied.isascii() or
                        not values[4].isascii() or
                        not hmac.compare_digest(supplied, values[4])):
                    raise _SelectionRefused(403)
            nodes, configured_token, uid = self._cohort_locked()
            now = time.monotonic()
            self._selections._tables_locked(now)
            self._tables_locked()
            bindings = self._references._bindings
            bound = bindings.get(key)
            if (bound is None or bound.session is not session or
                    not now < bound.expires or
                    not any(bound.target is target for label, target in nodes) or
                    len(self._attempts) >= _READS_LIMIT or
                    len(self._native_attempts) >= _READS_LIMIT or
                    original in self._attempts or original in self._native_attempts):
                raise _SelectionRefused(409)
            end = min(original.end, bound.expires)
            try:
                # Binding expiry also bounds every later refusal gate/write,
                # including constructor/prepare/admission failure paths.
                original.write_end = min(original.write_end, end)
            except BaseException as error:
                raise self._uncertain(error)
        return (original, token, session, values, nodes, configured_token,
                uid, bound, end, bindings)

    def admit_read(self, handler):
        # Fixed original parser consumes its <=256B body once; it accepts no
        # caller-selected endpoint, trust, token, source flag or result data.
        key = handler._request_body()['binding_ref']
        if not self._references._valid_reference(key):
            raise _SelectionRefused(400)
        captured = self._capture(handler, key)
        original, token, session, values, nodes, configured_token, uid, bound, end, bindings = captured
        # Constructors allocate obligation holders but perform no native IO.
        attempt = OriginalPrivateClusterRead(uid, bound.target.endpoint,
                                             configured_token, end)
        duty = _ReadDuty(original, token, session, values, nodes,
                         configured_token, uid, bound, end, attempt)
        first = None
        try:
            with _ReadGates(self._auth, original, end):
                self._session_locked(original, token, session, values)
                self._tables_locked()
                current = self._cohort_locked()
                if (current[0] is not nodes or current[1] is not configured_token or
                        current[2] != uid or
                        self._references._bindings is not bindings or
                        bindings.get(key) is not bound or
                        not time.monotonic() < end or
                        len(self._attempts) >= _READS_LIMIT or
                        len(self._native_attempts) >= _READS_LIMIT or
                        original in self._attempts or original in self._native_attempts):
                    raise _SelectionRefused(409)
                try:
                    # Private reservation/retained native duty PRECEDES all
                    # trust/credential/network work. Body and binding cannot replay.
                    self._native_attempts[original] = duty
                    self._attempts[original] = duty
                    duty.phase = 'running'
                    del bindings[key]
                except BaseException as error:
                    raise self._uncertain(error)
            body = attempt.run(key)  # No admission gate held over native work.
            if type(body) is not bytes or attempt._cleanup != 'locally-closed':
                raise _SelectionRefused(503)
            response = OriginalPilotResponse(200, body, 'application/json')
            duty.response = response
            duty.phase = 'prepared'
            with _ReadGates(self._auth, original, end):
                self._same_locked(duty)
                try:
                    self._broker._admit_frame_locked(handler, original, response)
                    duty.phase = 'admitted'
                except BaseException as error:
                    raise self._uncertain(error)
            return response
        except BaseException as error:
            first = error
        try:
            self._retire(duty)
        except BaseException as error:
            first = _first(first, error)
        if first is not None and (not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        if isinstance(first, _SelectionRefused):
            raise first
        raise _SelectionRefused(503) from None

    def write_admitted_response(self, handler, response):
        original = self._broker._owned(handler)
        duty = self._attempts.get(original)
        if (type(duty) is not _ReadDuty or duty.original is not original or
                duty.phase != 'admitted' or duty.response is not response):
            raise _SelectionRefused(503)
        first = None
        try:
            with _ReadGates(self._auth, original, duty.read_end, 'admitted'):
                self._same_locked(duty, 'admitted')
                try:
                    # SAME duty validated above under all original gates. Narrow
                    # retained sender data before reservation; no end argument
                    # crosses into the broker sender and accepted end is intact.
                    original.write_end = min(original.write_end, duty.read_end)
                    self._broker._reserve_write_locked(handler, original, response)
                    duty.phase = 'write-reserved'
                except BaseException as error:
                    raise self._uncertain(error)
            # All four gates released; original broker consumes once-send and
            # releases its own gate BEFORE original socket IO. No second writer.
            self._broker._send_reserved(handler, response)
        except BaseException as error:
            first = error
        try:
            self._retire(duty)
        except BaseException as error:
            first = _first(first, error)
        if first is not None:
            raise first

    def _retire(self, duty):
        # Native obligations first, outside every admission gate. Logical table
        # removal does not release original native strong retention, forgive
        # uncertain acquisition/close or refund/retry
        # a spent invocation. Original broker body_taken remains irreversible.
        if type(duty) is not _ReadDuty or duty.original.thread is not threading.current_thread():
            raise self._uncertain(_SelectionRefused(503))
        first = None
        try:
            duty.attempt.retire()
        except BaseException as error:
            first = self._uncertain(error)
        if first is not None:
            raise first
        try:
            with _ReadGates(self._auth, duty.original, duty.read_end, cleanup=True):
                self._tables_locked()
                current = self._attempts.get(duty.original)
                if current is not None and current is not duty:
                    raise self._uncertain(_SelectionRefused(503))
                try:
                    if duty.response is not None and duty.original.frame is duty.response:
                        duty.original.frame = None
                        if duty.original.phase != 'write-attempted':
                            duty.original.phase = 'read-retired'
                    duty.phase = 'retired'
                    duty.response = None
                    if current is duty:
                        del self._attempts[duty.original]
                    # SAME duty/attempt/context remains in _native_attempts.
                    # Logical cleanup grants no native capacity refund and
                    # provides no method to clear this retirement-only table.
                except BaseException as error:
                    raise self._uncertain(error)
        except BaseException as error:
            raise self._uncertain(error)

    def retire_handler_read(self, handler):
        """Actual original dispatcher finally, BEFORE broker request release.

        This cleanup must also run if dispatch/admission succeeds but write is
        skipped/interrupted. No live/end check may prevent original retirement.
        The actual physical parent remains liable for lost execution.
        """
        original = self._broker._requests.get(handler.request)
        if (original is None or original.handler is not handler or
                handler.server is not self._installation._server or
                original.thread is not threading.current_thread()):
            raise _SelectionRefused(503)
        duty = self._attempts.get(original)
        if duty is not None:
            self._retire(duty)


# No OriginalPilotInstallation issuer, native qualification or route enablement.
