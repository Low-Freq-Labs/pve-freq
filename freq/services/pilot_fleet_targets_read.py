"""Unqualified original retained-target read composition; no route or factory.

The actual original installation, source/code/principal/writer fence and hard
whole-job lifetime remain mandatory. Exact types and DATA identities below are
refusal filters; they cannot supply those missing native conditions. The
canonical installation's native-current method remains permanently False.
"""
import math
import threading
import time

from freq.api import auth
from freq.services.cluster_pilot_http import (
    OriginalPilotResponse, _OriginalPilotServer, _OriginalPilotHandler, _OriginalHTTPRequests,
    _OriginalRequest, _RequestUnavailable,
)
from freq.services.pilot_auth_commit import OriginalAuthCommit
from freq.services.pilot_fleet_targets_data import ConfiguredFleetTargetsData
from freq.services.pilot_fleet_targets_wire import format_retained_fleet_targets_data


def _first(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception) or
            not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


class _FleetTargetReadDuty:
    """Pure response preparation retained before formatting; no native grant."""
    __slots__ = ('original', 'data', 'token', 'session', 'values', 'thread',
                 'end', 'frame', 'state')

    def __init__(self, original, data, token, session, values, end):
        if type(self) is not _FleetTargetReadDuty or hasattr(self, 'state'):
            raise _RequestUnavailable()
        self.state = 'constructing'
        self.original, self.data = original, data
        self.token, self.session, self.values = token, session, values
        self.thread, self.end = original.thread, end
        self.frame, self.state = None, 'format-pending'


class _FleetTargetReadGates:
    """Original INSTALLATION→AUTH→REFERENCES→HTTP, same earlier write end.

    No parsing, hashing, serialization, source diagnostic or socket IO here.
    Unknown acquisition/release retires the instance without speculative
    release or retry. The real outside parent still owes physical settlement.
    """
    def __init__(self, component, original, phase, end):
        self._component, self._original, self._phase = component, original, phase
        self._end = end
        transaction = component._auth
        self._locks = (transaction._installation._gate, auth._auth_lock,
                       transaction._references._lock, transaction._broker._gate)
        self._states = ['unused'] * 4

    def __enter__(self):
        first = None
        try:
            for index, lock in enumerate(self._locks):
                self._end = min(self._end, self._component._end(self._original))
                remaining = self._end - time.monotonic()
                if not math.isfinite(remaining) or remaining <= 0:
                    raise _RequestUnavailable()
                self._states[index] = 'acquire-pending'
                acquired = lock.acquire(timeout=remaining)
                self._states[index] = 'owned' if acquired else 'not-acquired'
                if not acquired or not time.monotonic() < self._end:
                    raise _RequestUnavailable()
            self._component._auth._current_locked(self._original, self._phase)
            return self
        except BaseException as error:
            first = error
        raise self._release(first)

    def _release(self, first):
        for index in range(3, -1, -1):
            if self._states[index] == 'owned':
                self._states[index] = 'release-attempted'
                try:
                    self._locks[index].release()
                except BaseException as error:
                    self._states[index] = 'uncertain'
                    first = self._component._uncertain(_first(first, error))
                else:
                    self._states[index] = 'released'
            elif self._states[index] == 'acquire-pending':
                first = self._component._uncertain(_first(first, _RequestUnavailable()))
        return first

    def __exit__(self, kind, original_error, traceback):
        chosen = self._release(original_error)
        if chosen is not None and chosen is not original_error:
            raise chosen
        return False


class OriginalPilotFleetTargets:
    """Fixed original admin-session read, SAME retained DATA and once-frame.

    Future component binding must retain this SAME object before initialization.
    No supplied source, parser, bytes, owner, serializer, clock, lock or write
    callback is accepted. This source does not bind an endpoint or dispatcher.
    """
    __slots__ = ('_state', '_installation', '_auth', '_broker')

    def __init__(self, installation):
        if type(self) is not OriginalPilotFleetTargets or hasattr(self, '_state'):
            raise _RequestUnavailable()
        self._state = 'constructing'
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        try:
            if (type(installation) is not OriginalPilotInstallation or
                    installation._fleet_targets_reader is not self or
                    type(installation._auth_commit) is not OriginalAuthCommit or
                    installation._auth_commit._installation is not installation or
                    type(installation._server) is not _OriginalPilotServer or
                    installation._server._cluster_pilot_installation is not installation or
                    type(installation._server._pilot_requests) is not _OriginalHTTPRequests or
                    installation._auth_commit._broker is not installation._server._pilot_requests):
                raise _RequestUnavailable()
            self._installation = installation
            self._auth = installation._auth_commit
            self._broker = installation._server._pilot_requests
            self._state = 'bound-data'
        except AttributeError:
            raise _RequestUnavailable() from None

    def _uncertain(self, first):
        for target, field, value in ((self._installation, '_admission_uncertain', True),
                                     (self._installation, '_live', False),
                                     (self._broker, '_live', False)):
            try:
                setattr(target, field, value)
            except BaseException as error:
                first = _first(first, error)
        return first

    @staticmethod
    def _end(original):
        if (type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or not math.isfinite(original.write_end) or
                original.write_end > original.end):
            raise _RequestUnavailable()
        return min(original.end, original.write_end)

    def _owned(self, handler, phase):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if type(self) is not OriginalPilotFleetTargets or type(handler) is not _OriginalPilotHandler:
            raise _RequestUnavailable()
        owner = self._installation
        if (type(self._state) is not str or self._state != 'bound-data' or
                type(owner) is not OriginalPilotInstallation or
                owner._fleet_targets_reader is not self or
                owner._auth_commit is not self._auth or
                owner._server._pilot_requests is not self._broker):
            raise _RequestUnavailable()
        original = self._broker._owned(handler)
        if (type(original) is not _OriginalRequest or
                type(original.operation) is not str or original.operation != 'fleet-targets' or
                type(original.phase) is not str or original.phase != phase or
                original.thread is not threading.current_thread()):
            raise _RequestUnavailable()
        return original

    def _session_locked(self, original, token, session, values, phase):
        self._auth._current_locked(original, phase)
        if (type(values) is not tuple or len(values) != 5 or type(values[1]) is not str or
                not self._auth._same_session_locked(token, session, values, time.time()) or
                values[1] not in ('admin', 'protected')):
            raise _RequestUnavailable()

    def _same_duty_locked(self, original, duty, phase, state):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(duty) is not _FleetTargetReadDuty or
                original.fleet_targets_started is not True or
                original.fleet_targets_response is not duty or
                duty.original is not original or duty.thread is not original.thread or
                type(duty.state) is not str or duty.state != state or
                type(duty.end) is not float or not math.isfinite(duty.end) or
                type(duty.data) is not ConfiguredFleetTargetsData or
                not time.monotonic() < min(duty.end, self._end(original)) or
                self._installation._configured_fleet_targets_data is not duty.data or
                OriginalPilotInstallation._original_fleet_targets_data_current(
                    self._installation) is not True):
            raise _RequestUnavailable()
        self._session_locked(original, duty.token, duty.session, duty.values, phase)

    def admit_targets_response(self, handler):
        if type(self) is not OriginalPilotFleetTargets or type(handler) is not _OriginalPilotHandler:
            raise _RequestUnavailable()
        if (not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler, require_present=False, is_https=True)):
            raise _RequestUnavailable()
        original = self._owned(handler, 'ready')
        end = self._end(original)
        captured, token, source, session, values = self._auth._capture_session(
            handler, 'fleet-targets')
        if captured is not original:
            raise _RequestUnavailable()
        duty = None
        try:
            with _FleetTargetReadGates(self, original, 'ready', end):
                self._session_locked(original, token, session, values, 'ready')
                from freq.services.cluster_pilot_startup import OriginalPilotInstallation
                if (original.fleet_targets_started is not False or
                        original.fleet_targets_response is not None or
                        OriginalPilotInstallation._original_fleet_targets_data_current(
                            self._installation) is not True):
                    raise _RequestUnavailable()
                data = self._installation._configured_fleet_targets_data
                # Permanent before allocation; an unknown return cannot retry.
                original.fleet_targets_started = True
                duty = object.__new__(_FleetTargetReadDuty)
                original.fleet_targets_response = duty
                _FleetTargetReadDuty.__init__(duty, original, data, token, session, values,
                                              min(end, self._end(original)))
            # Pure formatting and frame allocation OUTSIDE every gate. Actual
            # hard parent resource/clock supervision is still a prerequisite.
            body = format_retained_fleet_targets_data(duty.data)
            duty.frame = OriginalPilotResponse(200, body, 'application/json')
            duty.state = 'prepared'
            with _FleetTargetReadGates(self, original, 'ready', duty.end):
                self._same_duty_locked(original, duty, 'ready', 'prepared')
                try:
                    self._broker._admit_frame_locked(handler, original, duty.frame)
                    duty.state = 'admitted'
                except BaseException as error:
                    raise self._uncertain(error)
            return duty.frame
        except BaseException as first:
            if duty is not None:
                try:
                    duty.state = 'failed'
                except BaseException as cleanup:
                    first = _first(first, cleanup)
            raise first

    def write_targets_response(self, handler, response):
        original = self._owned(handler, 'admitted')
        duty = original.fleet_targets_response
        if (type(duty) is not _FleetTargetReadDuty or duty.frame is not response or
                original.frame is not response or type(response) is not OriginalPilotResponse):
            raise _RequestUnavailable()
        with _FleetTargetReadGates(self, original, 'admitted', duty.end):
            self._same_duty_locked(original, duty, 'admitted', 'admitted')
            try:
                duty.state = 'write-reserve-pending'
                self._broker._reserve_write_locked(handler, original, response)
                duty.state = 'reserved'
            except BaseException as error:
                raise self._uncertain(error)
        # Original broker spends native send once after all gates release.
        duty.state = 'send-attempted'
        result = self._broker._send_reserved(handler, response)
        duty.state = 'send-returned'
        return result


# No route, dispatcher case, actual factory, native source grant or activation.
