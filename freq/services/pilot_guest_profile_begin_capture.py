"""Private once-only pure snapshot construction for the original begin prefix.

No guard/native/read/consume/retire operation occurs here. The original begin
caller invokes these inside existing same-four-guard admission and retains
itself before either call. Constructor/selection errors and pending holders
stay private; no returned state proves outside successful-return/physical duty.
"""
import threading
from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.pilot_guest_profile_begin import (
    _GuestProfileBeginDuty, _check_profile_begin_initialization,
)
from freq.services.pilot_guest_profile_begin_custody import (
    _ProfileBeginCustody, _ProfileBeginSelection,
)


def _begin_capture_context_data(begin):
    _check_profile_begin_initialization(getattr(begin, 'original', None), begin)
    if (type(begin) is not _GuestProfileBeginDuty or type(begin.original) is not _OriginalRequest or
            begin.original.guest_response is not begin or
            begin.original.thread is not threading.current_thread() or
            type(begin.phase) is not str or begin.phase != 'new'):
        raise _RequestUnavailable()
    return begin


def _capture_begin_custody_data(store, handler, begin):
    _begin_capture_context_data(begin)
    if (type(begin.cleanup_capture) is not str or begin.cleanup_capture != 'unattempted' or
            begin.cleanup_custody is not None or begin.cleanup_capture_error is not None):
        raise _RequestUnavailable()
    begin.cleanup_capture = 'constructor-pending'  # BEFORE __new__/__init__.
    try:
        begin.cleanup_custody = _ProfileBeginCustody.__new__(_ProfileBeginCustody)
        _ProfileBeginCustody.__init__(begin.cleanup_custody, store, handler, begin)
        begin.cleanup_capture = 'constructor-returned'
    except BaseException as error:
        begin.cleanup_capture_error = error
        raise
    return begin.cleanup_custody


def _capture_begin_selection_data(store, handler, begin):
    _begin_capture_context_data(begin)
    if (type(begin.cleanup_capture) is not str or begin.cleanup_capture != 'constructor-returned' or
            type(begin.cleanup_custody) is not _ProfileBeginCustody or
            begin.cleanup_capture_error is not None or
            type(begin.cleanup_selection_capture) is not str or
            begin.cleanup_selection_capture != 'unattempted' or
            begin.cleanup_selection is not None or begin.cleanup_selection_error is not None):
        raise _RequestUnavailable()
    begin.cleanup_selection_capture = 'constructor-pending'
    try:
        begin.cleanup_selection = _ProfileBeginSelection.__new__(_ProfileBeginSelection)
        _ProfileBeginSelection.__init__(begin.cleanup_selection, begin.cleanup_custody, store, handler)
        begin.cleanup_selection_capture = 'constructor-returned'
    except BaseException as error:
        begin.cleanup_selection_error = error
        raise
    return begin.cleanup_selection


# Retain all holders/errors; never clear, retry, consume, refund or issue a grant.
