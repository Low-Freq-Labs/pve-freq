"""UNEXECUTED original Discovery context gate-custody successor; no scanner or response.

Outside the current immutable candidate. Its unchanged fixed route classifier
has no Discovery operation, and original native currentness remains False.
Exact private types/maps below are refusal filters, not source, auth, network
scope or physical allowance issuers. A captured context is still unqualified
for scheduling. Actual original factory/native child custody remains owed.
"""
import hmac
import math
import threading
import time
from urllib.parse import unquote_to_bytes

from freq.api import auth
from freq.services.cluster_pilot_http import (
    _OriginalPilotHandler, _OriginalPilotServer, _OriginalHTTPRequests,
    _OriginalRequest, _RequestUnavailable,
)
from freq.services.pilot_auth_commit import OriginalAuthCommit
from freq.services.pilot_cluster_read_admission import _ReadGates
from freq.services.discovery_observation_data import DiscoveryPlan, plan_discovery


# A new nonrefundable logical context budget, matching the existing broker's
# 64 retained request limit. It is not a child/physical allowance or capacity
# qualification; pure collector preallocation creates no occupied child or
# target acquisition. Scheduling remains unimplemented. Retirement never
# refunds this retained context namespace.
_CONTEXT_LIMIT = 64
_PREFIX = '/api/discover?subnet='


def _first(first, later):
    # Same Discovery category policy, using actual types only.
    if first is None:
        return later
    if later is None:
        return first
    if not issubclass(type(first), Exception):
        return first
    if not issubclass(type(later), Exception):
        return later
    if issubclass(type(first), MemoryError):
        return first
    if issubclass(type(later), MemoryError):
        return later
    return first


def _retain_duty_failure(duty, error):
    # Exact known partial original only; no guessed holder or foreign dispatch.
    if duty is None:
        return
    if type(duty) is not _DiscoveryContextDuty:
        raise _RequestUnavailable()
    if getattr(duty, 'raw_failure', None) is None:
        duty.raw_failure = error
    duty.failure = _first(getattr(duty, 'failure', None), error)


def _plan_from_retained_target(target):
    """One encoded subnet value from already retained DATA; no permission.

    Preserve the existing backend's explicit /24 or three-octet grammar,
    including equivalent netmask spelling. The narrower future browser entry
    is separate. No default subnet, hostname, config or discovery lookup.
    """
    if (type(target) is not str or not target.isascii() or
            not target.startswith(_PREFIX)):
        raise _RequestUnavailable()
    value = target[len(_PREFIX):]
    if (not 0 < len(value) <= 192 or
            any(char in value for char in ('&', '#', '?', '=')) or
            any(ord(char) < 33 or ord(char) > 126 for char in value)):
        raise _RequestUnavailable()
    index = 0
    while index < len(value):
        if value[index] == '%':
            if (index + 2 >= len(value) or
                    any(char not in '0123456789abcdefABCDEF'
                        for char in value[index+1:index+3])):
                raise _RequestUnavailable()
            index += 3
        else:
            index += 1
    try:
        subnet = unquote_to_bytes(value.replace('+', ' ')).decode('ascii')
        return plan_discovery(subnet)
    except (ValueError, UnicodeError):
        raise _RequestUnavailable() from None


class _DiscoveryContextDuty:
    """Private pure holder; no executor, native receipt or public capability."""
    __slots__ = ('original', 'handler', 'socket', 'token', 'session', 'values',
                 'method', 'target', 'end', 'plan', 'logical', 'retained',
                 'tables', 'state', 'failure', 'raw_failure', 'retirement_started', 'retirement_result',
                 '_storage_started', 'collector_started', 'collector_storage',
                 'collector_anchor', 'collector_retired', 'collector_raw_failure',
                 'collector_genuine_failure', 'collector_allocation_failure',
                 'collector_ordinary_failure')

    def _initialize_storage(self):
        if (type(self) is not _DiscoveryContextDuty or
                hasattr(self, '_storage_started')):
            raise _RequestUnavailable()
        self._storage_started = True  # No reset of original collector roots.
        self.collector_started, self.collector_storage = False, None
        self.collector_anchor, self.collector_retired = None, False
        self.collector_raw_failure = self.collector_genuine_failure = None
        self.collector_allocation_failure = self.collector_ordinary_failure = None
        # Caller already stored this exact blank object on the original
        # request. Even a partially initialized holder remains reachable.
        self.failure = self.raw_failure = None
        self.state = 'allocated'
        self.retirement_started = False
        self.retirement_result = None
        for field in self.__slots__:
            if field in ('failure', 'raw_failure', 'state', 'retirement_started', 'retirement_result',
                         '_storage_started', 'collector_started', 'collector_storage',
                         'collector_anchor', 'collector_retired', 'collector_raw_failure',
                         'collector_genuine_failure', 'collector_allocation_failure',
                         'collector_ordinary_failure'):
                continue
            setattr(self, field, None)

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original Discovery duty cannot be subclassed')

    def __copy__(self):
        raise TypeError('original Discovery duty cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('original Discovery duty cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('original Discovery duty cannot be serialized')


class OriginalDiscoveryRequestContexts:
    """Retain an original request context; never schedule or publish results.

    Actual original pending binder must retain this SAME component before its
    initializer. All original source/principal/writer/generation/physical
    checks remain on that installation. No supplied callback or lease can
    turn a captured context into a scan/dispatch grant.
    """
    __slots__ = ('_initialization_started', '_installation', '_auth', '_broker',
                 '_logical', '_retained', '_tables')

    def __init__(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not OriginalDiscoveryRequestContexts or
                getattr(self, '_initialization_started', None) is not None):
            raise _RequestUnavailable()
        self._initialization_started = True
        if (type(installation) is not OriginalPilotInstallation or
                installation._discovery_contexts is not self or
                type(installation._auth_commit) is not OriginalAuthCommit or
                installation._auth_commit._installation is not installation or
                type(installation._server) is not _OriginalPilotServer or
                installation._server._cluster_pilot_installation is not installation or
                type(installation._auth_commit._broker) is not _OriginalHTTPRequests or
                installation._auth_commit._broker is not installation._server._pilot_requests or
                installation._auth_commit._broker._server is not installation._server or
                installation._original_discovery_tables_current() is not True):
            raise _RequestUnavailable()
        self._installation = installation
        self._auth = installation._auth_commit
        self._broker = self._auth._broker
        self._logical = installation._discovery_attempts
        self._retained = installation._native_discovery_attempts
        self._tables = installation._original_discovery_tables

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original Discovery component cannot be subclassed')

    def __copy__(self):
        raise TypeError('original Discovery component cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('original Discovery component cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('original Discovery component cannot be serialized')

    def _tables_locked(self):
        owner = self._installation
        if (owner._discovery_contexts is not self or
                owner._original_discovery_tables_current() is not True or
                owner._original_discovery_tables is not self._tables or
                owner._discovery_attempts is not self._logical or
                owner._native_discovery_attempts is not self._retained or
                type(self._logical) is not dict or type(self._retained) is not dict or
                self._logical is self._retained or
                len(self._logical) > _CONTEXT_LIMIT or len(self._retained) > _CONTEXT_LIMIT):
            raise _RequestUnavailable()

    def _session_locked(self, original, token, session, values):
        self._auth._current_locked(original, 'ready')
        if (original.thread is not threading.current_thread() or
                type(values) is not tuple or len(values) != 5 or
                type(values[1]) is not str or
                values[1] not in ('operator', 'admin', 'protected') or
                self._auth._same_session_locked(token, session, values, time.time()) is not True):
            raise _RequestUnavailable()

    def _same_captured_locked(self, duty):
        if type(duty) is not _DiscoveryContextDuty:
            raise _RequestUnavailable()
        original = duty.original
        self._session_locked(original, duty.token, duty.session, duty.values)
        self._tables_locked()
        if (original.discovery_started is not True or
                original.discovery_duty is not duty or
                original.handler is not duty.handler or original.socket is not duty.socket or
                original.method is not duty.method or original.target is not duty.target or
                original.operation != 'discovery' or original.body_taken is not True or
                self._logical.get(original) is not duty or
                self._retained.get(original) is not duty or
                duty.tables is not self._tables or duty.logical is not self._logical or
                duty.retained is not self._retained or
                type(duty.plan) is not DiscoveryPlan or
                duty.state != 'captured-unqualified' or
                duty.end != original.end or duty.end != original.write_end or
                not time.monotonic() < duty.end):
            raise _RequestUnavailable()

    def capture_request(self, handler):
        """Retain context once. Return no dispatch token, receipt or response."""
        if (type(self) is not OriginalDiscoveryRequestContexts or
                type(handler) is not _OriginalPilotHandler or
                auth._cluster_pilot_direct_tls(handler) is not True or
                not auth.same_origin_or_absent(handler, require_present=False, is_https=True)):
            raise _RequestUnavailable()
        original, token, source, session, values = self._auth._capture_session(handler, 'discovery')
        if (type(original) is not _OriginalRequest or original.handler is not handler or
                original.socket is not handler.request or
                original.request_line_taken is not True or type(original.method) is not str or
                original.method != 'GET' or type(original.target) is not str or
                type(original.body) is not bytes or original.body != b'' or
                type(source) is not str or source not in ('bearer', 'cookie') or
                type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or
                original.write_end != original.end):
            raise _RequestUnavailable()
        duty = None
        body_failure = body_raw_failure = None
        try:
            with _ReadGates(self._auth, original, original.end):
                try:
                    self._session_locked(original, token, session, values)
                    self._tables_locked()
                    if source != 'bearer':
                        supplied = handler.headers.get('X-Freq-CSRF', '')
                        if (type(supplied) is not str or type(values[4]) is not str or
                                not supplied.isascii() or not values[4].isascii() or
                                not hmac.compare_digest(supplied, values[4])):
                            raise _RequestUnavailable()
                    if (original.discovery_started is not False or
                            original.discovery_duty is not None or original.body_taken is not False or
                            original in self._logical or original in self._retained or
                            len(self._retained) >= _CONTEXT_LIMIT or
                            len(self._logical) >= _CONTEXT_LIMIT):
                        raise _RequestUnavailable()
                    try:
                        # Original input is spent before pure holder allocation.
                        # No child/effect is acquired here, even on a lost return.
                        original.discovery_started = True
                        original.body_taken = True
                        duty = object.__new__(_DiscoveryContextDuty)
                        original.discovery_duty = duty
                        _DiscoveryContextDuty._initialize_storage(duty)
                        duty.original, duty.handler, duty.socket = original, handler, original.socket
                        duty.token, duty.session, duty.values = token, session, values
                        duty.method, duty.target, duty.end = original.method, original.target, original.end
                        duty.logical, duty.retained, duty.tables = self._logical, self._retained, self._tables
                        duty.state = 'capture-pending'
                        # Retirement-only root precedes the removable logical map.
                        self._retained[original] = duty
                        self._logical[original] = duty
                    except BaseException as error:
                        # Original raw precedes the uncertain-instance helper too.
                        if body_raw_failure is None:
                            body_raw_failure = error
                        body_failure = _first(body_failure, error)
                        try:
                            # Raw original precedes the fallible retention helper.
                            if duty is not None and getattr(duty, 'raw_failure', None) is None:
                                duty.raw_failure = body_raw_failure
                            _retain_duty_failure(duty, error)
                        except BaseException as recording_error:
                            # Retain helper failure BEFORE gate exit can replace/suppress it.
                            body_failure = _first(body_failure, recording_error)
                            try:
                                if duty is not None:
                                    duty.failure = _first(getattr(duty, 'failure', None), body_failure)
                            except BaseException as storage_error:
                                body_failure = _first(body_failure, storage_error)
                        try:
                            uncertain = self._auth._uncertain(error)
                        except BaseException as later:
                            uncertain = later
                        body_failure = _first(body_failure, uncertain)
                        try:
                            # Raw original precedes the fallible retention helper.
                            if duty is not None and getattr(duty, 'raw_failure', None) is None:
                                duty.raw_failure = body_raw_failure
                            _retain_duty_failure(duty, uncertain)
                        except BaseException as recording_error:
                            # Retain helper failure BEFORE gate exit can replace/suppress it.
                            body_failure = _first(body_failure, recording_error)
                            try:
                                if duty is not None:
                                    duty.failure = _first(getattr(duty, 'failure', None), body_failure)
                            except BaseException as storage_error:
                                body_failure = _first(body_failure, storage_error)
                        raise body_failure
                except BaseException as escaped_body:
                    if body_raw_failure is None:
                        body_raw_failure = escaped_body
                    body_failure = _first(body_failure, escaped_body)
                    try:
                        # Raw original precedes the fallible retention helper.
                        if duty is not None and getattr(duty, 'raw_failure', None) is None:
                            duty.raw_failure = body_raw_failure
                        _retain_duty_failure(duty, escaped_body)
                    except BaseException as recording_error:
                        # Retain helper failure BEFORE gate exit can replace/suppress it.
                        body_failure = _first(body_failure, recording_error)
                        try:
                            if duty is not None:
                                duty.failure = _first(getattr(duty, 'failure', None), body_failure)
                        except BaseException as storage_error:
                            body_failure = _first(body_failure, storage_error)
                    raise body_failure
            if body_failure is not None:
                raise body_failure  # Gate suppression cannot produce success.
            # Pure bounded parser/254-target DATA allocation outside gates.
            duty.plan = _plan_from_retained_target(duty.target)
            duty.state = 'captured-unqualified'
            with _ReadGates(self._auth, original, duty.end):
                try:
                    self._same_captured_locked(duty)
                except BaseException as escaped_body:
                    if body_raw_failure is None:
                        body_raw_failure = escaped_body
                    body_failure = _first(body_failure, escaped_body)
                    try:
                        # Raw original precedes the fallible retention helper.
                        if duty is not None and getattr(duty, 'raw_failure', None) is None:
                            duty.raw_failure = body_raw_failure
                        _retain_duty_failure(duty, escaped_body)
                    except BaseException as recording_error:
                        # Retain helper failure BEFORE gate exit can replace/suppress it.
                        body_failure = _first(body_failure, recording_error)
                        try:
                            if duty is not None:
                                duty.failure = _first(getattr(duty, 'failure', None), body_failure)
                        except BaseException as storage_error:
                            body_failure = _first(body_failure, storage_error)
                    raise body_failure
            if body_failure is not None:
                raise body_failure  # Gate suppression cannot produce success.
            return None
        except BaseException as error:
            first = _first(body_failure, error)
        if duty is not None:
            try:
                _retain_duty_failure(duty, first)
                first = _first(duty.failure, first)
            except BaseException as error:
                first = _first(first, error)
            # Independent retirement is still attempted if storing the
            # diagnostic failed during a partial pure initialization.
            try:
                self.retire_handler_context(handler)
            except BaseException as error:
                first = _first(first, error)
        raise first

    def retire_handler_context(self, handler):
        """Logical retirement without live/end gates; no physical closure.

        Original dispatcher/factory must call this in its later reviewed
        finally before broker request release. No caller integration exists
        in this draft. Retirement keeps original duty and native-root map;
        it cannot reset once markers or refund the process context budget.
        """
        if (type(self) is not OriginalDiscoveryRequestContexts or
                type(handler) is not _OriginalPilotHandler):
            raise _RequestUnavailable()
        original = self._broker._requests.get(handler.request)
        if (type(original) is not _OriginalRequest or original.handler is not handler or
                original.socket is not handler.request or
                original.thread is not threading.current_thread()):
            raise self._auth._uncertain(_RequestUnavailable())
        duty = original.discovery_duty
        if duty is None:
            return None
        if type(duty) is not _DiscoveryContextDuty:
            raise self._auth._uncertain(_RequestUnavailable())
        started = getattr(duty, 'retirement_started', None)
        if started is True:
            selected = getattr(duty, 'failure', None)
            if selected is not None and (not issubclass(type(selected), Exception) or
                                         issubclass(type(selected), MemoryError)):
                raise selected
            if getattr(duty, 'retirement_result', None) != 'logical-retired':
                raise self._auth._uncertain(_RequestUnavailable())
            return None
        if started is not False:
            # A partially initialized/unknown holder is never treated as a
            # known unattempted cleanup or repaired into a usable context.
            raise self._auth._uncertain(_RequestUnavailable())
        duty.retirement_started = True
        duty.retirement_result = 'retirement-pending'
        # Pure state retirement precedes cleanup lock acquisition. This state
        # says nothing about unimplemented child/physical cleanup.
        duty.state = 'retirement-only'
        body_failure = body_raw_failure = None
        try:
            with _ReadGates(self._auth, original, original.end, cleanup=True):
                try:
                    if (getattr(duty, 'original', None) is not original or
                            duty.handler is not handler or
                            duty.socket is not handler.request or
                            self._installation._discovery_contexts is not self or
                            self._installation._discovery_attempts is not duty.logical or
                            self._installation._native_discovery_attempts is not duty.retained or
                            self._installation._original_discovery_tables is not duty.tables or
                            type(duty.logical) is not dict or type(duty.retained) is not dict or
                            duty.retained.get(original) is not duty):
                        raise _RequestUnavailable()
                    current = duty.logical.get(original)
                    if current is not None and current is not duty:
                        raise _RequestUnavailable()
                    if current is duty:
                        del duty.logical[original]
                except BaseException as escaped_body:
                    if body_raw_failure is None:
                        body_raw_failure = escaped_body
                    body_failure = _first(body_failure, escaped_body)
                    try:
                        # Raw original precedes the fallible retention helper.
                        if duty is not None and getattr(duty, 'raw_failure', None) is None:
                            duty.raw_failure = body_raw_failure
                        _retain_duty_failure(duty, escaped_body)
                    except BaseException as recording_error:
                        # Retain helper failure BEFORE gate exit can replace/suppress it.
                        body_failure = _first(body_failure, recording_error)
                        try:
                            if duty is not None:
                                duty.failure = _first(getattr(duty, 'failure', None), body_failure)
                        except BaseException as storage_error:
                            body_failure = _first(body_failure, storage_error)
                    raise body_failure
            if body_failure is not None:
                raise body_failure  # Gate suppression cannot produce success.
            # SAME duty/request/session/plan and retained root survive.
            # No physical receipt, native operation or release API exists.
            duty.retirement_result = 'logical-retired'
            selected = duty.failure
            if selected is not None and (not issubclass(type(selected), Exception) or
                                         issubclass(type(selected), MemoryError)):
                raise selected
            return None
        except BaseException as error:
            selected = _first(getattr(duty, 'failure', None),
                              _first(body_failure, error))
            try:
                _retain_duty_failure(duty, selected)
            except BaseException as storage_error:
                selected = _first(selected, storage_error)
            try:
                # Preserve a confirmed logical-only result when rethrowing an
                # already retained high-priority failure after gate cleanup.
                if duty.retirement_result != 'logical-retired':
                    duty.retirement_result = 'logical-retirement-unconfirmed'
            except BaseException as storage_error:
                selected = _first(selected, storage_error)
            try:
                uncertain = self._auth._uncertain(selected)
            except BaseException as later:
                uncertain = later
            selected = _first(selected, uncertain)
            try:
                _retain_duty_failure(duty, uncertain)
            except BaseException as later:
                # Final recording is fallible too; never bypass the original
                # body/teardown winner. Do not retry the failed helper.
                selected = _first(selected, later)
                try:
                    # Direct same-original slot update retains a newly winning
                    # protected helper error for repeat retirement as well.
                    duty.failure = _first(getattr(duty, 'failure', None), selected)
                except BaseException as storage_error:
                    selected = _first(selected, storage_error)
            raise selected


# No scheduling, spawn, wait, kill, receipt, observation, frame or route entry.
