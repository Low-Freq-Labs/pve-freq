"""WIP retained registration guards SOURCE; no native or admission grant.

Reuse exact original timed four-lock/currentness/earlier-end operations. This
holder retains received failures; it is not physical closure or full original
plan/custody/index/body/quarantine history. Store/dispatch remains unwired.
"""
from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.pilot_guest_profile_begin import (
    _GuestProfileBeginDuty, _check_profile_begin_initialization,
    _retain_profile_begin_failure,
)
from freq.services.pilot_guest_profile_begin_admission import (
    _ProfileBeginAdmissionGates, _first_begin_error,
)


class _ProfileRegistrationAdmissionGates(_ProfileBeginAdmissionGates):
    """Separate registration history; never overwrite earlier begin history."""
    def __init__(self, transaction, original, begin):
        self.entry_state = 'unattempted'
        self.entry_error = None
        self.outer_error = self.outer_release_error = self.inspection_error = None
        self.failure_state = 'unattempted'
        self.outer_release_state = 'unattempted'
        self.quarantine_input = self.quarantine_return = self.quarantine_error = None
        self.primary = self.repeat_error = None
        _ProfileBeginAdmissionGates.__init__(self, transaction, original, begin)

    def __enter__(self):
        if self.entry_state != 'unattempted':
            if isinstance(self.entry_error, BaseException):
                raise self.entry_error
            raise _RequestUnavailable()
        self.entry_state = 'enter-pending'
        try:
            returned = _ProfileBeginAdmissionGates.__enter__(self)
            self.entry_state = 'enter-returned'
            return returned
        except BaseException as error:
            self.entry_error = error
            raise

    def __exit__(self, kind, body_error, traceback):
        # Preserve previous begin.body_error. This is a separate later duty.
        self.body_error = body_error
        if body_error is not None and self._original.profile_begin_capture_error is None:
            self._original.profile_begin_capture_error = body_error
        selected = self._release(body_error)
        if selected is not None and selected is not body_error:
            raise selected
        return False


def _retain_profile_registration_guards_data(transaction, original, begin):
    """One fixed private original guard holder retained before constructor."""
    _check_profile_begin_initialization(original, begin)
    if (type(begin) is not _GuestProfileBeginDuty or
            type(original) is not _OriginalRequest or begin.original is not original):
        raise _RequestUnavailable()
    if (type(begin.registration_guard_capture) is not str or
            begin.registration_guard_capture != 'unattempted' or
            begin.registration_guards is not None or begin.registration_guard_error is not None):
        if isinstance(begin.registration_guard_error, BaseException):
            raise begin.registration_guard_error
        raise _RequestUnavailable()
    begin.registration_guard_capture = 'constructor-pending'
    try:
        begin.registration_guards = _ProfileRegistrationAdmissionGates.__new__(
            _ProfileRegistrationAdmissionGates)
        _ProfileRegistrationAdmissionGates.__init__(begin.registration_guards,
            transaction, original, begin)
        begin.registration_guard_capture = 'constructor-returned'
    except BaseException as error:
        begin.registration_guard_error = error
        raise
    _check_profile_begin_initialization(original, begin)
    return begin.registration_guards


def _finish_profile_registration_guard_error(store, guards, error):
    """Retain incoming first; finish known releases before unknown quarantine.

    Releasing only states still exactly owned covers a caught failure after an
    inner entry returned its locks, or after incomplete outer exit. Pending
    acquire/release is never raw-released or retried. One first repeated input
    can be retained without repeating cleanup/quarantine; further distinct
    repeats are unsupported and refused by the retained primary, not accounted
    as new history. Serial ordinary source assumptions, not universal async/OOM.
    """
    if type(guards) is not _ProfileRegistrationAdmissionGates or not isinstance(error, BaseException):
        raise _RequestUnavailable()
    if guards.failure_state != 'unattempted':
        previous = guards.repeat_error
        if previous is not None and previous is not error:
            if isinstance(guards.primary, BaseException):
                raise guards.primary
            raise _RequestUnavailable()
        if previous is None:
            guards.repeat_error = error
        guards.primary = _first_begin_error(guards.primary, guards.repeat_error)
        if not isinstance(guards.primary, BaseException):
            raise _RequestUnavailable()
        return guards.primary
    guards.failure_state = 'finish-pending'
    guards.outer_error = guards.primary = error  # BEFORE known cleanup or inspection.
    first = error
    guards.outer_release_state = 'release-pending'
    try:
        selected = guards._release(first)
        if not isinstance(selected, BaseException):
            raise _RequestUnavailable()
        first = _first_begin_error(first, selected)
        guards.outer_release_state = 'release-returned'
    except BaseException as later:
        guards.outer_release_error = later
        first = _first_begin_error(first, later)
    unknown = True
    try:
        states = guards._states
        if type(states) is not list or len(states) != 4:
            raise _RequestUnavailable()
        unknown = any(type(state) is not str or state not in
            ('unused', 'not-acquired', 'released') for state in states)
    except BaseException as later:
        guards.inspection_error = later
        first = _first_begin_error(first, later)
    if unknown:
        guards.quarantine_input = first
        try:
            selected = store._quarantine(first)
            guards.quarantine_return = selected
            if not isinstance(selected, BaseException):
                selected = _RequestUnavailable()
                guards.quarantine_error = selected
            first = _first_begin_error(first, selected)
        except BaseException as later:
            guards.quarantine_error = later
            first = _first_begin_error(first, later)
    guards.primary = first
    guards.failure_state = 'finish-returned'
    return first


# No plan/custody/index insertion ledger, physical settlement, store dispatch,
# credential/native acquire, issuer/currentwriter/recipient/frame/sendACK grant.
