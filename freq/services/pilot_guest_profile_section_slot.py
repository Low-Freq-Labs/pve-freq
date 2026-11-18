"""WIP original retained slot lifecycle; NO original admission or native grant.

These private functions associate the same exchange with the already retained
registered slot. A real caller must first own aggregate native/physical duties,
revalidate original context/token/trust/firstend, and hold independent duties for
its own unknown returns. Store/dispatcher and positive currentness stay unwired.
The existing unstarted-only positive filter is deliberately not widened here.
"""
import math
import threading

from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.pilot_guest_profile_exchange import _ProfileSectionExchange, _first
from freq.services.pilot_guest_profile_registration import (
    _ProfileAcquisitionDuty, _ProfileSectionSlot, _ProfileRetirementCustody, _SECTIONS,
)
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData


def _slot_context_data(duty, index):
    """Identity-only retained DATA; this must never require positive admission.

    Fixed same-thread ownership is necessary for this local holder cleanup.
    Expiry, global uncertainty, auth validity and unrelated map count are not
    cleanup barriers. No supplied arbitrary object receives a method call.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or type(index) is not int or
            not 0 <= index < 3 or type(duty.original) is not _OriginalRequest or
            duty.original.thread is not threading.current_thread() or
            type(duty.custody) is not _ProfileRetirementCustody or
            type(duty.custody.items) is not tuple or len(duty.custody.items) != 31 or
            duty.custody.items[14] is not duty or duty.custody.items[7] is not duty.original or
            type(duty.slots) is not tuple or len(duty.slots) != 3 or
            duty.custody.items[26] is not duty.slots):
        raise _RequestUnavailable()
    slot = duty.slots[index]
    if (type(slot) is not _ProfileSectionSlot or type(slot.section) is not str or
            slot.section != _SECTIONS[index] or
            any(slot is other for other in duty.slots[:index]) or
            any(slot is other for other in duty.slots[index + 1:])):
        raise _RequestUnavailable()
    return slot


def _cleanup_slot_context_data(duty, index):
    """Select the known captured slot for cleanup only.

    Positive preparation/run keep their separate unchanged alias predicates.
    Expiry/current mutable duty aliases never redirect saved slot selection.
    Original registry/four-guard ownership remains the outer caller's duty.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or type(index) is not int or
            not 0 <= index < 3 or type(duty.original) is not _OriginalRequest or
            duty.original.thread is not threading.current_thread() or
            type(duty.custody) is not _ProfileRetirementCustody or
            type(duty.custody.items) is not tuple or len(duty.custody.items) != 31 or
            duty.custody.items[14] is not duty or duty.custody.items[7] is not duty.original or
            type(duty.custody.items[26]) is not tuple or
            len(duty.custody.items[26]) != 3):
        raise _RequestUnavailable()
    slots = duty.custody.items[26]
    slot = slots[index]
    if (type(slot) is not _ProfileSectionSlot or type(slot.section) is not str or
            slot.section != _SECTIONS[index] or
            any(slot is other for other in slots[:index]) or
            any(slot is other for other in slots[index + 1:])):
        raise _RequestUnavailable()
    return slot


def _prepare_profile_section_slot_data(duty, index):
    """Pre-publish SAME pure holder before its constructor, no native effect.

    This is not the original currentness/native/allowance wrapper. The caller
    must not invoke it from a supplied plan or use its returned flag as proof
    that a lost successful outer return was received. Constructor uncertainty
    never retries; physical duties outside a lost __new__ return remain owed.
    """
    slot = _slot_context_data(duty, index)
    if (duty.phase != 'registered' or
            type(duty.plan) is not _GuestProfileSubreadsData or
            duty.custody.items[30] is not duty.plan or duty.plan.original is not duty.original or
            duty.plan.begin is not duty.begin or type(duty.end) is not float or
            not math.isfinite(duty.end) or type(duty.plan.end) is not float or
            not math.isfinite(duty.plan.end) or duty.end > duty.plan.end or
            type(duty.custody.items[29]) is not float or duty.custody.items[29] != duty.end or
            slot.phase != 'uninitialized' or slot.attempt is not None or
            slot.saved_attempt is not None or slot.result is not None or
            slot.construction != 'unattempted' or slot.execution != 'unattempted' or
            slot.cleanup != 'unattempted' or slot.construction_error is not None or
            slot.run_error is not None or slot.cleanup_error is not None):
        raise _RequestUnavailable()
    slot.phase = 'construction-pending'
    slot.construction = 'constructor-pending'
    try:
        slot.saved_attempt = _ProfileSectionExchange.__new__(_ProfileSectionExchange)
        slot.attempt = slot.saved_attempt
        _ProfileSectionExchange.__init__(slot.saved_attempt, duty.plan, slot.section,
                                         original_deadline=duty.end)
        slot.construction = 'constructor-returned'
        slot.phase = 'prepared'
    except BaseException as error:
        slot.construction_error = error
        raise
    return slot  # Private DATA only, not an original response/native receipt.


def _run_profile_section_slot_data(duty, index, transport, private_credentials, trust_context):
    """Independent slot run-pending across the inner holder's entire return.

    Caller STILL owes actual four-guard original currentness, whole-job native
    ownership/physical allowance, credential/trust acquisition and result duty.
    A local None is not a typed section-unavailable grant. Returned private data
    cannot bypass final current writer/recipient/send/ACK admission.
    """
    slot = _slot_context_data(duty, index)
    original = slot.saved_attempt
    if (duty.phase != 'registered' or slot.phase != 'prepared' or
            slot.construction != 'constructor-returned' or slot.execution != 'unattempted' or
            slot.cleanup != 'unattempted' or type(original) is not _ProfileSectionExchange or
            type(duty.end) is not float or not math.isfinite(duty.end) or
            type(duty.custody.items[29]) is not float or duty.custody.items[29] != duty.end or
            duty.custody.items[30] is not duty.plan or
            slot.attempt is not original or original._plan is not duty.plan or
            original._section != slot.section or original._end != duty.end or
            original._thread is not threading.current_thread()):
        raise _RequestUnavailable()
    slot.phase = 'run-pending'
    slot.execution = 'run-pending'  # BEFORE inner clock, serialization or native work.
    try:
        slot.result = _ProfileSectionExchange.run(original, transport, private_credentials, trust_context)
        slot.execution = 'run-returned'
        if slot.result is not None and type(slot.result) is not bytes:
            raise _RequestUnavailable()
        slot.phase = 'local-failure' if slot.result is None else 'returned-private'
    except BaseException as error:
        slot.run_error = error
        # Never reset run-pending on a lost return, even when inner is prepared.
        raise
    return slot.result


def _retire_profile_section_slot_data(duty, index):
    """One known original close; retain unknown duties, never grant closure.

    Saved holder is visited before checking a replaced public alias. Pending
    constructor/run remains uncertain even after the known socket close returns.
    This does not settle an outside caller's lost successful cleanup return.
    """
    slot = _cleanup_slot_context_data(duty, index)
    original = slot.saved_attempt
    if slot.cleanup in ('close-returned', 'returned-no-attempt'):
        if (slot.attempt is not original or slot.construction not in
                ('unattempted', 'constructor-returned') or slot.execution not in
                ('unattempted', 'run-returned')):
            raise _RequestUnavailable()
        return
    if slot.cleanup != 'unattempted':
        raise _RequestUnavailable()
    slot.cleanup = 'close-pending'
    try:
        if original is None:
            if (slot.attempt is not None or slot.construction != 'unattempted' or
                    slot.execution != 'unattempted' or slot.phase != 'uninitialized'):
                raise _RequestUnavailable()
            slot.cleanup = 'returned-no-attempt'
        else:
            if type(original) is not _ProfileSectionExchange:
                raise _RequestUnavailable()
            _ProfileSectionExchange.retire(original)
            slot.cleanup = 'close-returned'
            if (slot.attempt is not original or slot.construction != 'constructor-returned' or
                    slot.execution not in ('unattempted', 'run-returned')):
                raise _RequestUnavailable()
        slot.phase = 'retired-local'
    except BaseException as error:
        slot.cleanup_error = error
        raise
    # Hold result, credentials/pump/collector/errors and permanent registration.


def _retire_all_profile_sections_data(duty, first=None):
    """Visit all fixed known slots despite any prior body/cleanup control.

    This helper never authenticates or drops a map/guest/ticket. Original cleanup
    wrapper still must capture/hold the SAME four guards and identity graph.
    Local success is not aggregate physical/issuer/lifetime/ACK completion.
    """
    for index in range(3):
        try:
            _retire_profile_section_slot_data(duty, index)
        except BaseException as error:
            first = _first(first, error)
    return first


# WIP: no new store/dispatcher caller, native/currentness grant, positive
# predicate widening, original guarded cleanup join or response integration.
