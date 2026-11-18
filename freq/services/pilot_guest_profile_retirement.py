"""Unwired original retained profile retirement, not physical closure.

Match captured original identities under the SAME four nonblocking guards.
Positive currentness, expiry, capacity checks and unrelated table counts never
bar this local cleanup. Permanent native entry and shared guest charge remain.
Known same-slot local cleanup is joined; actual native/wholejob closure remains owed.
"""
import math
import threading

from freq.api import auth
from freq.services.cluster_pilot_http import (
    _RequestUnavailable, _OriginalRequest, _OriginalHTTPRequests,
    _OriginalPilotHandler, _OriginalPilotServer,
)
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.pilot_guest_reference_store import _OpeningCleanupGates
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_retirement import _first
from freq.services.pilot_guest_profile_section_slot import _retire_all_profile_sections_data
from freq.services.pilot_guest_profile_exchange import _first as _section_first
from freq.services.pilot_guest_profile_begin import (
    _GuestProfileBeginDuty, _completed_profile_begin_cleanup_data,
)
from freq.services.pilot_guest_profile_record_retirement import _retire_profile_record_once_data
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData
from freq.services.pilot_guest_profile_registration import (
    _ProfileAcquisitionDuty, _ProfileSectionSlot, _ProfileRetirementCustody,
    _SECTIONS,
)


def _profile_retirement_original(store, handler):
    _owned_store(store)
    broker = store._broker
    if (type(broker) is not _OriginalHTTPRequests or
            type(handler) is not _OriginalPilotHandler or
            type(broker._server) is not _OriginalPilotServer or
            handler.server is not broker._server or type(broker._requests) is not dict):
        raise _RequestUnavailable()
    original = broker._requests.get(handler.request)
    if (type(original) is not _OriginalRequest or original.handler is not handler or
            original.socket is not handler.request or
            original.thread is not threading.current_thread() or
            type(original.operation) is not str or original.operation != 'guest-owner-profile' or
            original.body_taken is not True):
        raise _RequestUnavailable()
    return original


def _captured_profile_cleanup_record_data(duty):
    """Use the original retained31 identity, never current positive begin aliases.

    Original identity/four-guard admission is the caller's independent duty.
    This only selects the canonical captured record for terminal local retire;
    no currentness/credential/read or arbitrary record callback is introduced.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or
            type(duty.original) is not _OriginalRequest or
            type(duty.begin) is not _GuestProfileBeginDuty or
            duty.begin.original is not duty.original or
            type(duty.custody) is not _ProfileRetirementCustody):
        raise _RequestUnavailable()
    items = duty.custody.items
    if (type(items) is not tuple or len(items) != 31 or
            items[7] is not duty.original or items[14] is not duty or
            items[15] is not duty.begin or type(items[16]) is not _GuestReferenceRecord):
        raise _RequestUnavailable()
    return items[16]


def _canonical_profile_acquisition_cleanup_data(original):
    """Same retained completed registration, independent of mutable response."""
    begin = _completed_profile_begin_cleanup_data(original)
    duty = begin.registration_duty
    if (type(begin.registration_capture) is not str
            or begin.registration_capture != 'constructor-returned'
            or begin.registration_error is not None
            or type(duty) is not _ProfileAcquisitionDuty
            or duty.original is not original or duty.begin is not begin):
        raise _RequestUnavailable()
    return duty


def _profile_retirement_custody_matches(store, original, handler, duty):
    """Identity-only cleanup predicate; never reauthenticate or grant a read."""
    owner = _owned_store(store)
    if (type(duty) is not _ProfileAcquisitionDuty or duty.original is not original or
            _canonical_profile_acquisition_cleanup_data(original) is not duty or
            type(duty.begin) is not _GuestProfileBeginDuty or duty.begin.original is not original or
            type(duty.custody) is not _ProfileRetirementCustody):
        raise _RequestUnavailable()
    items = duty.custody.items
    if type(items) is not tuple or len(items) != 31:
        raise _RequestUnavailable()
    (saved_store, saved_owner, transaction, broker, refs, server, requests,
     request, saved_handler, socket, thread, components, capacity, locks,
     saved_duty, begin, record, family, source, target, cohort, generation,
     inventory, profiles, active, native, slots, token, uid, end, plan) = items
    if (saved_store is not store or saved_owner is not owner or transaction is not store._auth or
            broker is not store._broker or refs is not store._references or server is not owner._server or
            request is not original or saved_handler is not handler or saved_duty is not duty or
            begin is not duty.begin or
            type(slots) is not tuple or len(slots) != 3 or
            type(uid) is not int or
            type(plan) is not _GuestProfileSubreadsData or
            plan.begin is not begin or plan.original is not original or
            plan.record is not record or plan.source is not source or plan.target is not target or
            type(end) is not float or not math.isfinite(end) or
            type(plan.end) is not float or not math.isfinite(plan.end) or end > plan.end or
            type(original) is not _OriginalRequest or
            type(broker) is not _OriginalHTTPRequests or type(server) is not _OriginalPilotServer or
            type(handler) is not _OriginalPilotHandler or handler.server is not server or
            original.handler is not handler or original.socket is not socket or handler.request is not socket or
            original.thread is not thread or thread is not threading.current_thread() or
            type(requests) is not dict or requests is not broker._requests or requests.get(socket) is not original or
            type(components) is not tuple or len(components) != 9 or
            type(inventory) is not tuple or len(inventory) != 2 or
            type(profiles) is not tuple or len(profiles) != 2 or
            components is not owner._original_component_tables or
            inventory is not owner._original_guest_inventory_tables or
            profiles is not owner._original_guest_profile_tables or
            active is not profiles[0] or native is not profiles[1] or
            active is not owner._guest_profile_attempts or native is not owner._native_guest_profile_attempts or
            any(type(table) is not dict for table in components + inventory + profiles) or
            any(table is prior for index, table in enumerate(components + inventory + profiles)
                for prior in (components + inventory + profiles)[:index]) or
            type(capacity) is not _GuestCapacity or capacity is not owner._guest_capacity or
            capacity is not owner._original_guest_capacity or type(locks) is not tuple or len(locks) != 4):
        raise _RequestUnavailable()
    current = (owner._auth_attempts, owner._asset_attempts, owner._issued_sessions,
        owner._read_attempts, owner._native_read_attempts, owner._guest_families_by_nonce,
        owner._guest_families_by_ref, owner._guest_reference_records, capacity._tickets,
        owner._guest_inventory_attempts, owner._native_guest_inventory_attempts,
        owner._guest_profile_attempts, owner._native_guest_profile_attempts)
    if (any(a is not b for a, b in zip(components + inventory + profiles, current)) or
            locks[0] is not owner._gate or locks[1] is not auth._auth_lock or
            locks[2] is not refs._lock or locks[3] is not broker._gate):
        raise _RequestUnavailable()
    return duty.custody


class _ProfileRetirementGates(_OpeningCleanupGates):
    def __init__(self, custody):
        if (type(custody) is not _ProfileRetirementCustody or
                type(custody.items) is not tuple or len(custody.items) != 31):
            raise _RequestUnavailable()
        self._transaction, self._original = custody.items[2], custody.items[7]
        self._phase, self._locks = 'ready', custody.items[13]
        self._states = ['unused'] * 4


def _retire_registered_profile_record_data(begin, record):
    """Retain prior saved-begin uncertainty before visiting known sections.

    Callers catch this error and STILL visit every known slot. A prior outer
    failure cannot be settled by the inner logical record-return marker or
    record._retired. Local imports only avoid a new top-level back edge; actual
    imports remain unqualified. Private exact types are DATA, not authority.
    """
    from freq.services.pilot_guest_profile_begin_retirement import _ProfileBeginRetirementDuty
    if type(begin) is not _GuestProfileBeginDuty:
        raise _RequestUnavailable()
    capture = begin.cleanup_retirement_capture
    previous = begin.cleanup_retirement
    error = begin.cleanup_retirement_capture_error
    if isinstance(error, BaseException):
        raise error
    if (type(capture) is str and capture == 'unattempted' and
            previous is None and error is None):
        pass  # Registered entry may be the first inner logical retire caller.
    elif (type(capture) is str and capture == 'constructor-returned' and
            type(previous) is _ProfileBeginRetirementDuty and previous.begin is begin and
            error is None):
        first = None
        for field in ('primary', 'body_error', 'guard_capture_error', 'guard_error',
                      'record_error', 'quarantine_error', 'quarantine_return'):
            retained = getattr(previous, field)
            if retained is not None:
                if not isinstance(retained, BaseException):
                    retained = _RequestUnavailable()
                first = _section_first(first, retained)
        if first is not None:
            raise first
        if (type(previous.phase) is not str or previous.phase != 'returned' or
                type(previous.record_retirement) is not str or
                previous.record_retirement != 'call-returned' or previous.record is not record):
            raise _RequestUnavailable()
    else:
        raise _RequestUnavailable()
    _retire_profile_record_once_data(begin, record)


def _retire_unstarted_profile_holders_data(duty, first):
    """Try known guest and every placeholder after earlier errors/controls.

    No arbitrary slot object receives a method call. Any started/foreign/unknown
    slot refuses without clearing it; original outside native duties stay owed.
    Guest retirement only marks terminal: no index or shared ticket mutation.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or
            type(duty.begin) is not _GuestProfileBeginDuty or duty.begin.original is not duty.original or
            type(duty.custody) is not _ProfileRetirementCustody or
            type(duty.custody.items) is not tuple or len(duty.custody.items) != 31 or
            type(duty.custody.items[26]) is not tuple or len(duty.custody.items[26]) != 3):
        return _first(first, _RequestUnavailable())
    begin = duty.begin
    try:
        record = _captured_profile_cleanup_record_data(duty)
        _retire_registered_profile_record_data(begin, record)
    except BaseException as error:
        first = _first(first, error)
    slots = duty.custody.items[26]
    if type(slots) is not tuple or len(slots) != 3:
        return _first(first, _RequestUnavailable())
    for index, slot in enumerate(slots):
        try:
            if (type(slot) is not _ProfileSectionSlot or
                    type(slot.section) is not str or slot.section != _SECTIONS[index] or
                    slot.attempt is not None or slot.phase != 'uninitialized' or
                    any(slot is other for other in slots[:index])):
                raise _RequestUnavailable()
        except BaseException as error:
            first = _first(first, error)
    return first


def _retire_profile_holders_data(duty, first):
    """Known guest plus every retained section despite earlier error/control.

    Captured four-guard caller establishes original identities only, never
    positive admission. Native/physical/outside-return duties remain owed.
    Legacy placeholder-only helper above is preserved for prior DATA callers.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or
            type(duty.begin) is not _GuestProfileBeginDuty or duty.begin.original is not duty.original or
            type(duty.custody) is not _ProfileRetirementCustody or
            type(duty.custody.items) is not tuple or len(duty.custody.items) != 31 or
            type(duty.custody.items[26]) is not tuple or len(duty.custody.items[26]) != 3):
        return _section_first(first, _RequestUnavailable())
    begin = duty.begin
    try:
        record = _captured_profile_cleanup_record_data(duty)
        _retire_registered_profile_record_data(begin, record)
    except BaseException as error:
        first = _section_first(first, error)
    return _retire_all_profile_sections_data(duty, first)


def _retire_profile_registration_data(duty):
    """Remove only SAME active row; permanent duty and all charges stay held.

    Identity/count positive filters are deliberately absent. Foreign selected
    rows and unknown partial insertion cannot be adopted, cleared or retried.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or
            type(duty.custody) is not _ProfileRetirementCustody or
            type(duty.custody.items) is not tuple or len(duty.custody.items) != 31 or
            duty.custody.items[14] is not duty or duty.custody.items[7] is not duty.original or
            type(duty.custody.items[23]) is not tuple or len(duty.custody.items[23]) != 2 or
            type(duty.phase) is not str or duty.phase not in
                ('captured', 'refused', 'registration-pending', 'registered', 'retired')):
        raise _RequestUnavailable()
    active, native = duty.custody.items[23]
    if type(active) is not dict or type(native) is not dict or active is native:
        raise _RequestUnavailable()
    original = duty.original
    if (original in native and native[original] is not duty or
            original in active and active[original] is not duty):
        raise _RequestUnavailable()
    if original not in native:
        if original in active or duty.phase not in ('captured', 'refused'):
            raise _RequestUnavailable()
        duty.phase = 'retired'
        return
    duty.phase = 'retired'
    if original in active:
        del active[original]
    # Native entry, custody, slots, plan, record and shared ticket remain held.


def retire_profile_handler_duty(store, handler):
    """Before broker registry release; no dispatch join or positive grant.

    Captured registration may retain known started section duties. Earlier begin or
    pre-capture refusal stays original family/session/outside-parent work.
    """
    _owned_store(store)
    original = _profile_retirement_original(store, handler)
    duty = _canonical_profile_acquisition_cleanup_data(original)
    custody = _profile_retirement_custody_matches(store, original, handler, duty)
    first = None
    try:
        with _ProfileRetirementGates(custody):
            if _profile_retirement_custody_matches(store, original, handler, duty) is not custody:
                raise _RequestUnavailable()
            first = _retire_profile_holders_data(duty, first)
            if first is None:
                try:
                    _retire_profile_registration_data(duty)
                except BaseException as error:
                    first = _section_first(first, error)
    except BaseException as error:
        first = _section_first(first, error)
    if first is not None:
        raise store._quarantine(first)


# No actual acquired caller, physical close/refund, response admission/send/ACK or activation.
