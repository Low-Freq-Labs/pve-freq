"""Unwired original guarded pure profile-section preparation prefix.

No credential, trust, socket, child, native operation or result is acquired.
The actual original caller must pre-retain independent outside-return duties,
perform retirement on failure and freshly admit every later native stage.
A prepared holder is private DATA only, never section availability or a grant.
"""
import threading

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_profile_begin import _GuestProfileBeginDuty, _CorruptProfileSource
from freq.services.pilot_guest_profile_registration import _ProfileAcquisitionDuty
from freq.services.pilot_guest_profile_current import (
    _ProfileCurrentGates, _registered_profile_context_data_locked,
)
from freq.services.pilot_guest_profile_retirement import _profile_retirement_custody_matches
from freq.services.pilot_guest_profile_section_slot import _prepare_profile_section_slot_data
from freq.services.pilot_guest_sources_begin import _ExpiredSourceFamily, _CorruptSourceFamily


def _quarantine_profile_preparation_error(store, duty, error, index):
    """Three fixed original preparation indices; retain actual input/return/raised refs.

    This serialized bounded ledger observes only caught/returned failures.
    One first repeated input per site is retained, with no repeat store call.
    Further distinct repeats are unsupported; refuse using retained primary.
    Store-internal failures and physical/native settlement remain independent.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or type(index) is not int or
            not 0 <= index < 3 or not issubclass(type(error), BaseException)):
        raise _RequestUnavailable()
    from freq.services.pilot_guest_profile_begin_admission import _first_begin_error
    if (duty.preparation_quarantine_inputs[index] is not None or
            duty.preparation_quarantine_returns[index] is not None or
            duty.preparation_quarantine_errors[index] is not None):
        previous = duty.preparation_quarantine_repeat_errors[index]
        unsupported = previous is not None and previous is not error
        if previous is None:
            duty.preparation_quarantine_repeat_errors[index] = error
        selected = duty.preparation_quarantine_primary
        for later in (duty.preparation_quarantine_inputs[index], duty.preparation_quarantine_returns[index],
                      duty.preparation_quarantine_errors[index], duty.preparation_quarantine_repeat_errors[index]):
            if issubclass(type(later), BaseException):
                selected = _first_begin_error(selected, later)
        duty.preparation_quarantine_primary = selected
        if unsupported:
            raise selected
        return selected
    duty.preparation_quarantine_inputs[index] = error  # BEFORE invoking existing quarantine.
    duty.preparation_quarantine_primary = _first_begin_error(duty.preparation_quarantine_primary, error)
    try:
        returned = store._quarantine(error)
        duty.preparation_quarantine_returns[index] = returned
        selected = returned
        if not issubclass(type(selected), BaseException):
            selected = _RequestUnavailable()
            duty.preparation_quarantine_errors[index] = selected
        duty.preparation_quarantine_primary = _first_begin_error(duty.preparation_quarantine_primary, selected)
    except BaseException as later:
        duty.preparation_quarantine_errors[index] = later
        duty.preparation_quarantine_primary = _first_begin_error(duty.preparation_quarantine_primary, later)
    return duty.preparation_quarantine_primary



def prepare_registered_profile_section(store, handler, index):
    """Same four-guard original checkpoint then only pure holder preparation.

    Fixed index selects one of the existing three plan duties, never a path or
    callback from a request. No store delegation or dispatcher join is added.
    The guard/auth/cohort/context/31-capture checks are the existing original
    currentness wrapper's checks, not a supplied successful predicate.

    A guard-exit or outer successful-return loss does not undo constructor
    state, settle outside duties or authorize native continuation. Original
    parent must retain the same duty and independently retire known holders on
    any failure/control, without requiring this positive predicate for cleanup.
    This prefix does not allocate a native/physical holder, run a section or
    establish a complete parent error ledger. It never renews the first end.
    """
    owner = _owned_store(store)
    if type(index) is not int or not 0 <= index < 3:
        raise _RequestUnavailable()
    original = store._broker._owned(handler)
    duty = original.guest_response
    if (type(duty) is not _ProfileAcquisitionDuty or duty.original is not original or
            type(duty.begin) is not _GuestProfileBeginDuty or duty.begin.original is not original):
        raise _RequestUnavailable()
    with _ProfileCurrentGates(store._auth, original, duty):
        begin = duty.begin
        cohort, generation, now = store._guard_locked(original, begin.token, begin.session, begin.values)
        store._csrf_nonce_locked(handler, 'cookie', begin.values, begin.family_ref)
        if (original.thread is not threading.current_thread() or
                owner._original_guest_profile_tables_current() is not True):
            raise _RequestUnavailable()
        _profile_retirement_custody_matches(store, original, handler, duty)
        try:
            same = _registered_profile_context_data_locked(owner, duty, cohort, generation, now)
        except _ExpiredSourceFamily as expired:
            store._retire_known_family_locked(expired.family)
            raise _RequestUnavailable() from None
        except (_CorruptProfileSource, _CorruptSourceFamily) as error:
            raise _quarantine_profile_preparation_error(store, duty, error, index)
        if same is not duty:
            raise _RequestUnavailable()
        duty.last_clock = now
        slot = _prepare_profile_section_slot_data(duty, index)
    return slot  # Same retained private slot only; no native/result receipt.


# Actual acquiring caller/store/dispatch/result/send/retireACK integration stays owed.
