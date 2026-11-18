"""Original saved-begin profile retirement SOURCE, not physical closure.

Only saved original request/21 identities and16 selected identities are used.
The same four captured guards are attempted nonblocking, and every known owned
release is visited once after failure/control/allocation. Unknown capture,
guard or retire returns stay retained and quarantine; no retry/repair/refund.
This entry is not joined to store/dispatch and cannot issue a positive grant.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_reference_store import _OpeningCleanupGates
from freq.services.pilot_guest_profile_begin import (
    _GuestProfileBeginDuty, _completed_profile_begin_cleanup_data,
)
from freq.services.pilot_guest_profile_begin_custody import (
    _ProfileBeginCustody, _ProfileBeginSelection,
    _begin_custody_matches_data, _begin_selected_record_cleanup_data,
)
from freq.services.pilot_guest_profile_retirement import _profile_retirement_original
from freq.services.pilot_guest_profile_registration import _ProfileAcquisitionDuty
from freq.services.pilot_guest_profile_record_retirement import _retire_profile_record_once_data


def _first_begin_cleanup(first, later):
    """First genuine control, then first allocation, then first ordinary error."""
    if later is None:
        return first
    if first is None or (issubclass(type(first), Exception) and not issubclass(type(later), Exception)):
        return later
    if issubclass(type(first), Exception) and not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError):
        return later
    return first


class _ProfileBeginRetirementDuty:
    """Pre-retained private caught-error ledger; no physical receipt."""
    __slots__ = ('begin', 'custody', 'selection', 'phase', 'guards',
        'guard_capture', 'guard_capture_error', 'guard_error', 'body_error',
        'record', 'record_retirement', 'record_error', 'selection_outcome',
        'quarantine_error', 'quarantine_return', 'primary')

    def __init__(self, begin):
        self.begin, self.custody, self.selection = begin, begin.cleanup_custody, begin.cleanup_selection
        self.phase = 'retained'
        self.guards = self.guard_capture_error = self.guard_error = self.body_error = None
        self.guard_capture = 'unattempted'
        self.record, self.record_error = None, None
        self.record_retirement = 'unattempted'
        self.selection_outcome = 'unresolved'
        self.quarantine_error = self.quarantine_return = self.primary = None


class _ProfileBeginRetirementGates(_OpeningCleanupGates):
    """Captured guards only, with every caught acquire/release error retained.

    Unknown acquire is never released speculatively. Quarantine is done by the
    retained outer caller after every known release, not inside that loop.
    Positive currentness/clock/count predicates are deliberately absent.
    """
    def __init__(self, custody):
        if (type(custody) is not _ProfileBeginCustody or
                type(custody.items) is not tuple or len(custody.items) != 21 or
                type(custody.items[13]) is not tuple or len(custody.items[13]) != 4):
            raise _RequestUnavailable()
        self._transaction, self._original = custody.items[2], custody.items[7]
        self._phase, self._locks = 'ready', custody.items[13]
        self._states = ['unused'] * 4
        self.acquire_errors = [None] * 4
        self.release_errors = [None] * 4
        self.body_error = None

    def __enter__(self):
        first = None
        try:
            for index, lock in enumerate(self._locks):
                self._states[index] = 'acquire-pending'
                try:
                    acquired = lock.acquire(blocking=False)
                    if type(acquired) is not bool:
                        raise _RequestUnavailable()
                    self._states[index] = 'owned' if acquired else 'not-acquired'
                    if not acquired:
                        raise _RequestUnavailable()
                except BaseException as error:
                    self.acquire_errors[index] = error
                    raise
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
                    self.release_errors[index] = error
                    self._states[index] = 'uncertain'
                    first = _first_begin_cleanup(first, error)
                else:
                    self._states[index] = 'released'
        return first

    def __exit__(self, kind, body_error, traceback):
        self.body_error = body_error
        selected = self._release(body_error)
        if selected is not None and selected is not body_error:
            raise selected
        return False


def _retire_saved_begin_selection_data(store, handler, duty):
    """Guarded caller must hold same captured guards; no live admission here."""
    begin = duty.begin
    if (_begin_custody_matches_data(duty.custody, store, handler) is not begin or
            begin.cleanup_custody is not duty.custody or
            type(begin.cleanup_capture) is not str or begin.cleanup_capture != 'constructor-returned' or
            begin.cleanup_capture_error is not None):
        raise _RequestUnavailable()
    if (type(begin.cleanup_selection_capture) is str and
            begin.cleanup_selection_capture == 'unattempted' and
            duty.selection is None and begin.cleanup_selection is None and
            begin.cleanup_selection_error is None and type(begin.phase) is str and begin.phase == 'new'):
        # No consumption stage was entered. This is not native/resource closure.
        duty.selection_outcome = 'not-selected-before-consume'
        return
    if (type(begin.cleanup_selection_capture) is not str or
            begin.cleanup_selection_capture != 'constructor-returned' or
            begin.cleanup_selection_error is not None or
            type(duty.selection) is not _ProfileBeginSelection or
            begin.cleanup_selection is not duty.selection):
        raise _RequestUnavailable()
    record = _begin_selected_record_cleanup_data(duty.custody, duty.selection, store, handler)
    if duty.record_retirement != 'unattempted' or duty.record is not None:
        raise _RequestUnavailable()
    duty.record = record
    duty.record_retirement = 'call-pending'  # BEFORE fixed same-record operation.
    try:
        _retire_profile_record_once_data(begin, record)
        duty.record_retirement = 'call-returned'
    except BaseException as error:
        duty.record_error = error
        raise
    duty.selection_outcome = 'same-selected-record-retired'


def _quarantine_begin_retirement(store, duty, first):
    """Retain what quarantine returns/raises; never let it replace control/Memory."""
    duty.primary = first
    try:
        selected = store._quarantine(first)
        duty.quarantine_return = selected
        if not isinstance(selected, BaseException):
            selected = _RequestUnavailable()
            duty.quarantine_error = selected
        first = _first_begin_cleanup(first, selected)
    except BaseException as error:
        duty.quarantine_error = error
        first = _first_begin_cleanup(first, error)
    duty.primary = first
    return first


def _original_retained_profile_begin_data(original):
    """Select only canonical completed storage for already owed cleanup.

    Mutable response/phase cannot select a replacement or erase this root.
    No fresh positive deadline/refusal/body-success gate skips known cleanup.
    Partial construction is handled by the unresolved request cleanup ledger.
    """
    return _completed_profile_begin_cleanup_data(original)


def retire_profile_begin_handler_duty(store, handler):
    """Fixed original saved-begin entry, before broker registry release.

    No argument supplies a begin/custody/map/lock/callback/native owner. A
    canonical acquisition handoff may retain this SAME earlier begin; only its
    saved selected-record cleanup is handled here. Registered sections/index/
    native duties and outer failure accounting remain separate owed work.
    Store/dispatcher join is absent; no physical closure follows this entry.
    """
    original = _profile_retirement_original(store, handler)
    begin = _original_retained_profile_begin_data(original)
    if (type(begin.cleanup_retirement_capture) is not str or
            begin.cleanup_retirement_capture != 'unattempted' or
            begin.cleanup_retirement is not None or begin.cleanup_retirement_capture_error is not None):
        # Pending, failed and returned entries are never run a second time.
        if isinstance(begin.cleanup_retirement_capture_error, BaseException):
            raise begin.cleanup_retirement_capture_error
        previous = begin.cleanup_retirement
        if (begin.cleanup_retirement_capture == 'constructor-returned' and
                type(previous) is _ProfileBeginRetirementDuty and isinstance(previous.primary, BaseException)):
            raise previous.primary
        raise _RequestUnavailable()
    begin.cleanup_retirement_capture = 'constructor-pending'
    try:
        begin.cleanup_retirement = _ProfileBeginRetirementDuty.__new__(_ProfileBeginRetirementDuty)
        _ProfileBeginRetirementDuty.__init__(begin.cleanup_retirement, begin)
        begin.cleanup_retirement_capture = 'constructor-returned'
    except BaseException as error:
        begin.cleanup_retirement_capture_error = error
        # Partial ledger remains retained. No guard/retire call was made.
        raise
    duty = begin.cleanup_retirement
    first = _first_begin_cleanup(begin.cleanup_capture_error, begin.cleanup_selection_error)
    try:
        if (type(begin.cleanup_capture) is not str or begin.cleanup_capture != 'constructor-returned' or
                begin.cleanup_capture_error is not None or type(duty.custody) is not _ProfileBeginCustody):
            raise _RequestUnavailable()
        duty.guard_capture = 'constructor-pending'
        try:
            duty.guards = _ProfileBeginRetirementGates.__new__(_ProfileBeginRetirementGates)
            _ProfileBeginRetirementGates.__init__(duty.guards, duty.custody)
            duty.guard_capture = 'constructor-returned'
        except BaseException as error:
            duty.guard_capture_error = error
            raise
        duty.phase = 'guards-pending'
        try:
            with duty.guards:
                duty.phase = 'inside-captured-guards'
                try:
                    _retire_saved_begin_selection_data(store, handler, duty)
                except BaseException as error:
                    duty.body_error = error
                    raise
        except BaseException as error:
            duty.guard_error = error
            raise
        duty.phase = 'returned'
    except BaseException as error:
        first = _first_begin_cleanup(first, error)
    if first is not None:
        duty.phase = 'uncertain'
        raise _quarantine_begin_retirement(store, duty, first)
    return duty


# No active row deletion, refund, unspend, capacity check, auth/clock/currentness,
# credential, native IO/job, frame, send/retire ACK, store/dispatch or activation.
