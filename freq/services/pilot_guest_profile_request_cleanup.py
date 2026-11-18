"""Original request's outside-return ledger for profile cleanup only.

This entry is exposed on the original store but not dispatched or activated.
Inner retired/local-close flags never discharge an unknown outer return.
The original broker must retain the request and all native duties afterwards.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.pilot_guest_profile_begin import (
    _GuestProfileBeginDuty, _completed_profile_begin_cleanup_data,
)
from freq.services.pilot_guest_profile_registration import _ProfileAcquisitionDuty
from freq.services.pilot_guest_profile_retirement import (
    _profile_retirement_original, retire_profile_handler_duty,
)
from freq.services.pilot_guest_profile_begin_retirement import retire_profile_begin_handler_duty


def _error(value):
    return issubclass(type(value), BaseException)


def _first(first, later):
    if later is None:
        return first
    if first is None or (issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception) or
            not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError))):
        return later
    return first


class _ProfileRequestCleanup:
    """Retained before initialization; no caller supplied callbacks or owners."""
    __slots__ = ('store', 'original', 'handler', 'response', 'begin', 'acquisition', 'kind',
                 'phase', 'states', 'inputs', 'returns', 'errors', 'context_errors', 'primary',
                 'quarantine_state', 'quarantine_input', 'quarantine_return',
                 'quarantine_error')

    def __init__(self, store, original, handler):
        self.store, self.original, self.handler = store, original, handler
        response = original.guest_response
        self.response, self.begin = response, None
        self.acquisition = None
        self.kind = 'none'
        self.phase = 'retained'
        self.states = ['unattempted', 'unattempted']
        self.inputs, self.returns, self.errors = [None, None], [None, None], [None, None]
        # Post-call context observations never replace an actual helper error.
        self.context_errors = [None, None]
        self.primary = None
        self.quarantine_state = 'unattempted'
        self.quarantine_input = self.quarantine_return = self.quarantine_error = None
        capture = original.profile_begin_capture
        begin = original.profile_begin_original
        raw = original.profile_begin_capture_error
        if (capture == 'unattempted' and type(capture) is str
                and begin is None and raw is None and response is None):
            return
        # Keep the actual known blank even when no complete-only field exists.
        self.begin = begin
        if (type(begin) is not _GuestProfileBeginDuty
                or getattr(begin, 'original', None) is not original
                or getattr(begin, '_init_complete', None) is not True
                or type(capture) is not str or capture != 'constructor-returned'):
            self.kind = 'begin-unresolved'
            selected = getattr(begin, 'primary_error', None) if type(begin) is _GuestProfileBeginDuty else None
            self.primary = selected if _error(selected) else raw if _error(raw) else _RequestUnavailable()
            return
        _completed_profile_begin_cleanup_data(original)
        selected = getattr(begin, 'primary_error', None)
        guards = getattr(begin, 'registration_guards', None)
        guard_selected = getattr(guards, 'primary', None)
        if _error(selected):
            self.primary = selected
        if _error(guard_selected):
            self.primary = _first(self.primary, guard_selected)
        if self.primary is None and _error(raw):
            self.primary = raw
        self.kind = 'begin'
        acquired = begin.registration_duty
        self.acquisition = acquired
        if (type(begin.registration_capture) is str
                and begin.registration_capture == 'unattempted'
                and acquired is None and begin.registration_error is None):
            return
        if (type(begin.registration_capture) is str
                and begin.registration_capture == 'constructor-returned'
                and begin.registration_error is None
                and type(acquired) is _ProfileAcquisitionDuty
                and acquired.original is original and acquired.begin is begin):
            self.kind = 'acquisition'
        else:
            self.kind = 'acquisition-unresolved'
            later = begin.registration_error if _error(begin.registration_error) else _RequestUnavailable()
            self.primary = _first(self.primary, later)
        # A foreign current view is retained as an observation, never followed
        # or repaired. The canonical completed begin still owes its own cleanup.


def _same_original_context(duty, index):
    original = _profile_retirement_original(duty.store, duty.handler)
    if original is not duty.original or original.profile_begin_original is not duty.begin:
        raise _RequestUnavailable()
    # The known begin has its own canonical cleanup lookup. Its entry must
    # not depend on acquisition sibling links after that earlier attempt.
    if index == 0 and duty.kind == 'acquisition' and (duty.acquisition.begin is not duty.begin
            or duty.begin.registration_duty is not duty.acquisition):
        raise _RequestUnavailable()
    return original


def _cleanup_once(duty, index):
    # Only fixed original entries. No generic callback can become authority.
    duty.inputs[index] = duty.acquisition if index == 0 else duty.begin
    duty.states[index] = 'call-pending'
    entered = False
    try:
        _same_original_context(duty, index)
        entered = True
        if index == 0:
            value = retire_profile_handler_duty(duty.store, duty.handler)
        else:
            value = retire_profile_begin_handler_duty(duty.store, duty.handler)
        duty.returns[index] = value
        duty.states[index] = 'call-returned'
    except BaseException as error:
        duty.errors[index] = error
        # Pending is deliberately retained even if inner flags say retired.
        duty.primary = _first(duty.primary, error)
    finally:
        if type(duty.begin) is _GuestProfileBeginDuty:
            duty.original.profile_begin_original = duty.begin
    if index == 0 and entered:
        # Inspect the retained acquisition after its actual call, keeping
        # return/error and later mismatch in independent fixed slots.
        # This cannot discharge or gate the separate known begin entry.
        try:
            _same_original_context(duty, 0)
        except BaseException as error:
            duty.context_errors[0] = error
            duty.primary = _first(duty.primary, error)
        finally:
            if type(duty.begin) is _GuestProfileBeginDuty:
                duty.original.profile_begin_original = duty.begin


def _quarantine_once(duty):
    duty.quarantine_input = duty.primary
    duty.quarantine_state = 'call-pending'
    try:
        value = duty.store._quarantine(duty.primary)
        duty.quarantine_return = value
        duty.quarantine_state = 'call-returned'
        if not _error(value):
            error = _RequestUnavailable()
            duty.quarantine_error = error
            duty.primary = _first(duty.primary, error)
        else:
            duty.primary = _first(duty.primary, value)
    except BaseException as error:
        duty.quarantine_error = error
        duty.primary = _first(duty.primary, error)


def retire_profile_request_duty(store, handler):
    """One original request call; every repeat refuses without another effect.

    Acquisition cleanup and saved-begin cleanup have independent outside call
    states, and the later known duty is visited after an earlier caught error.
    Returning this ledger reports local call observations, never physical ACK.
    """
    original = _profile_retirement_original(store, handler)
    if (type(original.profile_cleanup_capture) is not str or
            original.profile_cleanup_capture != 'unattempted' or
            original.profile_cleanup is not None or original.profile_cleanup_capture_error is not None):
        if _error(original.profile_cleanup_capture_error):
            raise original.profile_cleanup_capture_error
        previous = original.profile_cleanup
        if type(previous) is _ProfileRequestCleanup:
            try:
                primary = previous.primary
            except AttributeError:
                primary = None
            if _error(primary):
                raise primary
        raise _RequestUnavailable()
    original.profile_custody_started = True
    original.profile_cleanup_capture = 'constructor-pending'
    try:
        original.profile_cleanup = _ProfileRequestCleanup.__new__(_ProfileRequestCleanup)
        _ProfileRequestCleanup.__init__(original.profile_cleanup, store, original, handler)
        original.profile_cleanup_capture = 'constructor-returned'
    except BaseException as error:
        original.profile_cleanup_capture_error = error
        raise
    duty = original.profile_cleanup
    try:
        if duty.kind == 'acquisition':
            _cleanup_once(duty, 0)
        elif duty.kind == 'acquisition-unresolved':
            duty.states[0] = 'construction-unresolved'
        else:
            duty.states[0] = 'not-applicable'
        if duty.kind == 'begin-unresolved':
            duty.states[1] = 'construction-unresolved'
        elif duty.begin is not None:
            _cleanup_once(duty, 1)
        else:
            duty.states[1] = 'not-applicable'
        if duty.primary is not None:
            duty.phase = 'unresolved'
            _quarantine_once(duty)
            raise duty.primary
        duty.phase = 'calls-returned'
        return duty
    finally:
        if type(duty.begin) is _GuestProfileBeginDuty:
            original.profile_begin_original = duty.begin


# Dispatch, acquisition, response construction/admission, physical/native
# retirement, request registry release and unknown outer return remain owed.
