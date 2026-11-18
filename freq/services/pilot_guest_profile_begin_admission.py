"""Retained original profile admission guards and received failure ledger.

Same positive admission and captured earlier end; no new source/native grant.
Known releases continue after every caught failure. Pending/unknown guard
outcomes quarantine after known releases and remain retained, never retried.
This records received errors, not unseen inner/outside execution outcomes.
"""
import math
import time
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.pilot_guest_profile_begin import (
    _ProfileBeginGates, _GuestProfileBeginDuty,
    _check_profile_begin_initialization, _retain_profile_begin_failure,
)


def _first_begin_error(first, later):
    if later is None:
        return first
    if first is None or (issubclass(type(first), Exception) and not issubclass(type(later), Exception)):
        return later
    if issubclass(type(first), Exception) and not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError):
        return later
    return first


class _ProfileBeginAdmissionGates(_ProfileBeginGates):
    """Exact original timed admission, with retained per-guard caught errors."""
    def __init__(self, transaction, original, begin):
        self.begin = begin
        # Existing constructor selects SAME four locks and earlier first end.
        _ProfileBeginGates.__init__(self, transaction, original, begin)
        self.acquire_errors = [None] * 4
        self.release_errors = [None] * 4
        self.currentness_error = None
        self.body_error = None

    def __enter__(self):
        first = None
        try:
            for index, lock in enumerate(self._locks):
                try:
                    _check_profile_begin_initialization(self._original, self.begin)
                    original = self._original
                    if (type(original.end) is not float or not math.isfinite(original.end) or
                            type(original.write_end) is not float or
                            not math.isfinite(original.write_end)):
                        raise _RequestUnavailable()
                    self._end = min(self._end, original.end, original.write_end)
                    remaining = self._end - time.monotonic()
                    if not math.isfinite(remaining) or remaining <= 0:
                        raise _RequestUnavailable()
                    self._states[index] = 'acquire-pending'
                    acquired = lock.acquire(timeout=remaining)
                    if type(acquired) is not bool:
                        raise _RequestUnavailable()
                    self._states[index] = 'owned' if acquired else 'not-acquired'
                    _check_profile_begin_initialization(self._original, self.begin)
                    if not acquired or not time.monotonic() < min(
                            self._end, original.end, original.write_end):
                        raise _RequestUnavailable()
                except BaseException as error:
                    self.acquire_errors[index] = error
                    raise
            try:
                _check_profile_begin_initialization(self._original, self.begin)
                self._transaction._current_locked(self._original, self._phase)
                _check_profile_begin_initialization(self._original, self.begin)
            except BaseException as error:
                self.currentness_error = error
                raise
            return self
        except BaseException as error:
            if self._original.profile_begin_capture_error is None:
                self._original.profile_begin_capture_error = error
            first = error
        raise self._release(first)

    def _release(self, first):
        if first is not None:
            if self._original.profile_begin_capture_error is None:
                self._original.profile_begin_capture_error = first
            selected = self.begin.primary_error
            if selected is None or (issubclass(type(selected), Exception) and (
                    not issubclass(type(first), Exception) or
                    not issubclass(type(selected), MemoryError) and issubclass(type(first), MemoryError))):
                self.begin.primary_error = first
        for index in range(3, -1, -1):
            if self._states[index] == 'owned':
                self._states[index] = 'release-attempted'
                try:
                    self._locks[index].release()
                except BaseException as error:
                    self.release_errors[index] = error
                    if self._original.profile_begin_capture_error is None:
                        self._original.profile_begin_capture_error = error
                    selected = self.begin.primary_error
                    if selected is None or (issubclass(type(selected), Exception) and (
                            not issubclass(type(error), Exception) or
                            not issubclass(type(selected), MemoryError) and issubclass(type(error), MemoryError))):
                        self.begin.primary_error = error
                    self._states[index] = 'uncertain'
                    first = _first_begin_error(first, error)
                else:
                    self._states[index] = 'released'
        return first

    def __exit__(self, kind, body_error, traceback):
        self.body_error = self.begin.body_error = body_error
        if body_error is not None and self._original.profile_begin_capture_error is None:
            self._original.profile_begin_capture_error = body_error
        selected = self._release(body_error)
        if selected is not None and selected is not body_error:
            raise selected
        return False


def _begin_guard_uncertain_data(guards):
    if type(guards) is not _ProfileBeginAdmissionGates:
        raise _RequestUnavailable()
    return any(state in ('acquire-pending', 'release-attempted', 'uncertain') for state in guards._states)


def _quarantine_begin_error(store, begin, error, index):
    """Six fixed source sites; preserve input/return/raised secondary by identity.

    This cannot observe failures suppressed INSIDE original store._quarantine;
    that helper is separate owed source work. This never issues a positive grant.
    """
    if (type(begin) is not _GuestProfileBeginDuty or type(index) is not int or
            not 0 <= index < 6 or not isinstance(error, BaseException)):
        raise _RequestUnavailable()
    if (begin.quarantine_inputs[index] is not None or
            begin.quarantine_returns[index] is not None or begin.quarantine_errors[index] is not None):
        # One supported repeat retains its received error BEFORE selection.
        # Never repeat the underlying quarantine call. Global primary is first
        # in chronological priority; then saved site input/return/error, then
        # the first received repeat. Same-priority later controls/Memory lose.
        held_repeat = begin.quarantine_repeat_errors[index]
        unsupported = held_repeat is not None and held_repeat is not error
        if held_repeat is None:
            begin.quarantine_repeat_errors[index] = error
        selected = begin.primary_error
        for later in (begin.quarantine_inputs[index], begin.quarantine_returns[index],
                      begin.quarantine_errors[index], begin.quarantine_repeat_errors[index]):
            if isinstance(later, BaseException):
                selected = _first_begin_error(selected, later)
        begin.primary_error = selected
        if unsupported:
            # Further DISTINCT invocation is unsupported, no new operation and
            # no claim to account its new argument in this bounded ledger.
            # Preserve retained errors/primary and refuse by that same object.
            raise selected
        return selected
    begin.quarantine_inputs[index] = error  # BEFORE call; retained pending duty.
    first = error
    try:
        selected = store._quarantine(error)
        begin.quarantine_returns[index] = selected
        if not isinstance(selected, BaseException):
            selected = _RequestUnavailable()
            begin.quarantine_errors[index] = selected
        first = _first_begin_error(first, selected)
    except BaseException as later:
        begin.quarantine_errors[index] = later
        first = _first_begin_error(first, later)
    begin.primary_error = _first_begin_error(begin.primary_error, first)
    return begin.primary_error


# No new native factory/credential/source reader/issuer/recipient/frame/ACK.
