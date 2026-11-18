"""Private logical record once DATA; no guard, index or physical authority.

The fixed original caller already holds its saved guards and selects the same
record from captured identities. This shared per-begin ledger only prevents a
second fixed logical _retire call across saved-begin and registered holders.
Outer caller/guard/section/native/physical successful-return duties stay owed.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_profile_begin import _GuestProfileBeginDuty


def _retire_profile_record_once_data(begin, record):
    """Pending before the one fixed operation; no retry from terminal flags."""
    if type(begin) is not _GuestProfileBeginDuty or type(record) is not _GuestReferenceRecord:
        raise _RequestUnavailable()
    state = begin.record_once_state
    if (type(state) is str and state == 'call-returned' and
            begin.record_once is record and begin.record_once_error is None):
        return  # Only this inner logical return, never an outer cleanup receipt.
    if (type(state) is not str or state != 'unattempted' or
            begin.record_once is not None or begin.record_once_error is not None):
        if isinstance(begin.record_once_error, BaseException):
            raise begin.record_once_error
        raise _RequestUnavailable()
    begin.record_once_state = 'call-pending'
    try:
        begin.record_once = record
        _GuestReferenceRecord._retire(record)
        begin.record_once_state = 'call-returned'
    except BaseException as error:
        begin.record_once_error = error
        raise
