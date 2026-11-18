"""Original fixed-asset acquisition to once-response composition, source only.

The actual original installation factory, physical writer/code profile and
native runtime are prerequisites. This component cannot create any of them.
The only asset selector comes from the original broker's parsed fixed route.
No supplied body, path, deadline, manifest, serializer or write callback enters.
"""
import math
import threading
import time

from freq.services.cluster_pilot_http import (
    OriginalPilotResponse, _OriginalPilotServer, _RequestUnavailable,
)
from freq.services.pilot_fixed_assets import FixedPilotAssetAttempt


def _first(first, later):
    if later is None:
        return first
    if (first is None or
            (isinstance(first, Exception) and not isinstance(later, Exception)) or
            (isinstance(first, Exception) and not isinstance(first, MemoryError) and
             isinstance(later, MemoryError))):
        return later
    return first


class _AssetRecord:
    __slots__ = ('original', 'attempt', 'key', 'frame', 'state', 'errors', 'failure')

    def __init__(self, original, attempt, key):
        self.original = original
        self.attempt = attempt
        self.key = key
        self.frame = None
        self.state = 'retained'
        self.errors = [None] * 3
        self.failure = None


class _StaticGates:
    """INSTALLATION then HTTP, a subset of the original global lock order.

    No native acquisition, close, hash, serialization or socket IO is allowed
    in this scope. An ambiguous acquisition/release retires the whole original
    instance and retains its duties for the actual physical supervisor.
    """
    def __init__(self, component, original, phase='ready', cleanup=False):
        if phase not in ('ready', 'admitted'):
            raise _RequestUnavailable()
        self._component, self._original = component, original
        self._phase, self._cleanup = phase, cleanup
        owner = component._installation
        self._locks = ((owner._gate,) if cleanup else
                       (owner._gate, component._broker._gate))
        self._states = ['unused'] * len(self._locks)

    def __enter__(self):
        first = None
        try:
            if self._cleanup and (self._component._installation._admission_uncertain or
                                   self._component._broker._gate_uncertain):
                raise _RequestUnavailable()
            for index, lock in enumerate(self._locks):
                if self._cleanup:
                    self._states[index] = 'acquire-pending'
                    acquired = lock.acquire(blocking=False)
                else:
                    left = self._original.end - time.monotonic()
                    if not math.isfinite(left) or left <= 0:
                        raise _RequestUnavailable()
                    self._states[index] = 'acquire-pending'
                    acquired = lock.acquire(timeout=left)
                self._states[index] = 'owned' if acquired else 'not-acquired'
                if not acquired:
                    raise _RequestUnavailable()
            if not self._cleanup:
                self._component._current_locked(self._original, self._phase)
            return self
        except BaseException as error:
            first = error
        if self._cleanup:
            first = self._component._uncertain(first)
        raise self._release(first)

    def _release(self, first):
        for index in range(len(self._locks) - 1, -1, -1):
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
                first = self._component._uncertain(
                    _first(first, _RequestUnavailable()))
        return first

    def __exit__(self, kind, original_error, traceback):
        chosen = self._release(original_error)
        if chosen is not None and chosen is not original_error:
            raise chosen
        return False


class OriginalPilotStatic:
    """Retain the same original request, native attempt and response frame.

    Original startup owns this component as _static_responder and its private
    _asset_attempts table before any call. Exact types only refuse substitutes;
    they do not establish physical source or installation authority.
    """
    def __init__(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(installation) is not OriginalPilotInstallation or
                type(installation._server) is not _OriginalPilotServer or
                installation._server._cluster_pilot_installation is not installation or
                type(installation._asset_attempts) is not dict):
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

    def _current_locked(self, original, phase):
        owner = self._installation
        if (not owner._live or owner._admission_uncertain or
                owner._static_responder is not self or
                not self._broker._live or self._broker._gate_uncertain or
                self._broker._requests.get(original.socket) is not original or
                original.handler is None or original.phase != phase or
                original.handler.server is not owner._server or
                original.handler.request is not original.socket or
                original.thread is not threading.current_thread() or
                not time.monotonic() < original.end or
                owner._native_current_locked(original) is not True):
            raise _RequestUnavailable()

    def _same_record_locked(self, record):
        attempt, original = record.attempt, record.original
        if (self._installation._asset_attempts.get(attempt) is not record or
                record.key != original.asset or
                attempt._thread is not original.thread or
                attempt._end != original.end or
                attempt._state != 'retired' or
                attempt._cleanup != 'locally-settled' or
                record.state != 'prepared' or
                type(record.frame) is not OriginalPilotResponse):
            raise _RequestUnavailable()

    def _close_attempt(self, attempt):
        # acquire() already attempts retirement on every failed acquisition.
        # Do not issue a second close attempt after an uncertain native result.
        if attempt._cleanup == 'not-attempted':
            attempt.retire()
        if attempt._state != 'retired' or attempt._cleanup != 'locally-settled':
            raise self._uncertain(_RequestUnavailable())

    def _forget_settled(self, record):
        # This is a logical table refund only. No new wait after the original
        # end and no physical cleanup confirmation from deleting an entry.
        with _StaticGates(self, record.original, cleanup=True):
            attempt = record.attempt
            if (self._installation._asset_attempts.get(attempt) is not record or
                    attempt._state != 'retired' or
                    attempt._cleanup != 'locally-settled'):
                raise self._uncertain(_RequestUnavailable())
            try:
                del self._installation._asset_attempts[attempt]
            except BaseException as error:
                raise self._uncertain(error)

    def serve(self, handler):
        original = self._broker._owned(handler)
        if (original.phase != 'ready' or original.operation not in ('app', 'asset') or
                type(original.asset) is not str or
                (original.operation == 'app' and original.asset != 'app.html')):
            raise _RequestUnavailable()
        attempt = FixedPilotAssetAttempt(original.end)
        record = _AssetRecord(original, attempt, original.asset)
        retained = False
        first = None
        try:
            with _StaticGates(self, original):
                if original.asset_attempted or len(self._installation._asset_attempts) >= 64:
                    raise _RequestUnavailable()
                original.asset_attempted = True  # Never reset/refund this duty.
                try:
                    self._installation._asset_attempts[attempt] = record
                except BaseException as error:
                    raise self._uncertain(error)
                retained = True
            # All native file work/hash/MIME and wire serialization occurs
            # outside every admission gate, under the SAME original end.
            if attempt.acquire() is not attempt:
                raise _RequestUnavailable()
            mime, raw = attempt.private_payload(record.key)
            if mime == 'text/html':
                mime = 'text/html; charset=utf-8'
            record.frame = OriginalPilotResponse(200, raw, mime)
            # Settle known native file duties BEFORE final response admission.
            # The original installation still retains the separate physical
            # code/source/writer fence; equal hashes or close cannot create it.
            self._close_attempt(attempt)
            record.state = 'prepared'
            with _StaticGates(self, original):
                self._same_record_locked(record)
                try:
                    self._broker._admit_frame_locked(handler, original, record.frame)
                    record.state = 'admitted'
                except BaseException as error:
                    raise self._uncertain(error)
            with _StaticGates(self, original, phase='admitted'):
                if (self._installation._asset_attempts.get(attempt) is not record or
                        record.state != 'admitted' or original.frame is not record.frame):
                    raise _RequestUnavailable()
                self._broker._reserve_write_locked(handler, original, record.frame)
            # Both gates have been released. The original broker spends the
            # final native-send duty separately before IO; no appended response
            # on partial failure, conditional/Range branch, cache or fallback.
            self._broker._send_reserved(handler, record.frame)
        except BaseException as error:
            record.errors[0] = error
            first = record.failure = _first(record.failure, error)
        finally:
            if retained:
                try:
                    self._close_attempt(attempt)
                except BaseException as cleanup:
                    record.errors[1] = cleanup
                    first = record.failure = self._uncertain(_first(first, cleanup))
                if attempt._cleanup == 'locally-settled':
                    try:
                        self._forget_settled(record)
                    except BaseException as cleanup:
                        record.errors[2] = cleanup
                        first = record.failure = self._uncertain(_first(first, cleanup))
        if first is not None:
            if not isinstance(first, Exception) or isinstance(first, MemoryError):
                raise first
            raise _RequestUnavailable() from None


# No actual original startup factory, host profile or public dispatch is added.
