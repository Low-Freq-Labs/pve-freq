"""Unwired retirement-only continuation of the UNSTARTED inventory duty.

No native object is constructed or called by this prefix. It retires only the
known consumed source and logical registration. The permanent native table,
source charge and captured context stay retained. This is neither a physical
close receipt nor an original read grant. Actual parent duties remain owed.
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
from freq.services.pilot_guest_inventory_begin import _GuestInventoryBeginDuty
from freq.services.pilot_guest_inventory_registration import (
    _InventoryAcquisitionDuty, _InventoryNativeSlot, _InventoryChildSlot,
    _InventoryRetirementCustody,
    INVENTORY_EXCHANGE_TRUST_CHARGE,
)
from freq.services.pilot_guest_inventory_child_reservation_data import (
    _InventoryChildReservationData, retire_inventory_child_reservation_data,
)


def _retirement_original(store, handler):
    """Exact original registry lookup without positive broker/live/end gates."""
    _owned_store(store)  # Original graph identity only, no currentness flags.
    broker = store._broker
    if (type(broker) is not _OriginalHTTPRequests or
            type(handler) is not _OriginalPilotHandler or
            type(broker._server) is not _OriginalPilotServer or
            handler.server is not broker._server or
            type(broker._requests) is not dict or len(broker._requests) > 64):
        raise _RequestUnavailable()
    original = broker._requests.get(handler.request)
    if (type(original) is not _OriginalRequest or original.handler is not handler or
            original.socket is not handler.request or
            original.thread is not threading.current_thread() or
            type(original.operation) is not str or
            original.operation != 'guest-owner-inventory' or
            original.body_taken is not True):
        raise _RequestUnavailable()
    return original


def _retirement_custody_matches(store, original, handler, duty):
    """Match captured graph only; own quarantine/expiry cannot erase custody.

    No session/current cohort lookup, native-current, capacity._check(), new
    table currentness predicate, broker._owned(), admission or table repair.
    Replaced graph/locks or unknown custody refuse with outside duties owed.
    """
    owner = _owned_store(store)
    if (type(duty) is not _InventoryAcquisitionDuty or
            duty.original is not original or original.guest_response is not duty or
            type(duty.begin) is not _GuestInventoryBeginDuty or
            duty.begin.original is not original or
            type(duty.custody) is not _InventoryRetirementCustody):
        raise _RequestUnavailable()
    items = duty.custody.items
    if type(items) is not tuple or len(items) != 29:
        raise _RequestUnavailable()
    (saved_store, saved_owner, transaction, broker, references, server, requests,
     request, saved_handler, socket, thread, tables, capacity, locks, saved_duty,
     begin, record, family, source, cohort, generation, inventory, active, native,
     slot, configured_token, credential_uid, end, children) = items
    if (saved_store is not store or saved_owner is not owner or
            transaction is not store._auth or broker is not store._broker or
            references is not store._references or server is not owner._server or
            request is not original or saved_handler is not handler or
            saved_duty is not duty or begin is not duty.begin or
            record is not begin.record or family is not begin.family or
            source is not begin.source or cohort is not begin.cohort or
            generation is not begin.generation or slot is not duty.slot or
            type(children) is not _InventoryChildSlot or children is not duty.children or
            configured_token is not duty.configured_token or
            type(credential_uid) is not int or credential_uid != duty.credential_uid or
            type(duty.charge) is not int or duty.charge != INVENTORY_EXCHANGE_TRUST_CHARGE or
            type(end) is not float or not math.isfinite(end) or duty.end != end or
            any(type(x) is not float or not math.isfinite(x)
                for x in (duty.end, begin.end, original.end, original.write_end)) or
            begin.end > end or original.write_end > end or end > original.end or
            type(original) is not _OriginalRequest or
            type(broker) is not _OriginalHTTPRequests or
            type(server) is not _OriginalPilotServer or
            type(handler) is not _OriginalPilotHandler or handler.server is not server or
            original.handler is not handler or original.socket is not socket or
            handler.request is not socket or original.thread is not thread or
            thread is not threading.current_thread() or
            type(requests) is not dict or requests is not broker._requests or
            len(requests) > 64 or requests.get(socket) is not original or
            type(tables) is not tuple or len(tables) != 9 or
            tables is not duty.component_tables or tables is not owner._original_component_tables or
            any(type(table) is not dict for table in tables) or
            any(tables[i] is tables[j] for i in range(9) for j in range(i)) or
            type(capacity) is not _GuestCapacity or capacity is not owner._guest_capacity or
            capacity is not owner._original_guest_capacity or
            type(locks) is not tuple or len(locks) != 4 or
            type(inventory) is not tuple or len(inventory) != 2 or
            inventory is not duty.inventory_tables or
            inventory is not owner._original_guest_inventory_tables or
            active is not inventory[0] or native is not inventory[1] or
            active is not owner._guest_inventory_attempts or
            native is not owner._native_guest_inventory_attempts or
            type(active) is not dict or type(native) is not dict or
            active is native or len(active) > 64 or len(native) > 64 or
            any(table is previous for table in inventory for previous in tables)):
        raise _RequestUnavailable()
    current = (owner._auth_attempts, owner._asset_attempts, owner._issued_sessions,
        owner._read_attempts, owner._native_read_attempts, owner._guest_families_by_nonce,
        owner._guest_families_by_ref, owner._guest_reference_records, capacity._tickets)
    if (any(a is not b for a, b in zip(tables, current)) or
            any(len(table) > 4096 for table in tables[5:]) or
            locks[0] is not owner._gate or locks[1] is not auth._auth_lock or
            locks[2] is not references._lock or locks[3] is not broker._gate):
        raise _RequestUnavailable()
    return duty.custody


class _InventoryRetirementGates(_OpeningCleanupGates):
    """SAME captured four locks, inherited nonblocking/unknown accounting."""
    def __init__(self, custody):
        if (type(custody) is not _InventoryRetirementCustody or
                type(custody.items) is not tuple or len(custody.items) != 29):
            raise _RequestUnavailable()
        items = custody.items
        self._transaction, self._original = items[2], items[7]
        self._phase, self._locks = 'ready', items[13]
        self._states = ['unused'] * 4


def _retire_unstarted_holders_data(duty, first):
    """Source, native-None and child-counter duties; no physical authority.

    Attempt the known source terminal transition and then verify the retained
    unstarted slot even after the first holder fails. No arbitrary object gets
    a retire/close call. A future native-acquiring successor MUST replace this
    placeholder-only logic with exact retained native cleanup before effects.
    """
    if (type(duty) is not _InventoryAcquisitionDuty or
            type(duty.begin) is not _GuestInventoryBeginDuty or
            duty.begin.original is not duty.original or
            type(duty.custody) is not _InventoryRetirementCustody or
            type(duty.custody.items) is not tuple or len(duty.custody.items) != 29 or
            duty.custody.items[28] is not duty.children):
        return _first(first, _RequestUnavailable())
    begin = duty.begin
    try:
        record, family = begin.record, begin.family
        if (type(record) is not _GuestReferenceRecord or
                type(family) is not _GuestFamilyRecord or
                record._family is not family or record._session is not begin.session or
                type(begin.values) is not tuple or len(begin.values) != 5 or
                record._principal != begin.values[0] or record._purpose != 'source' or
                record._key != begin.source_ref or record._source is not begin.source or
                record._cohort is not begin.cohort or record._generation is not begin.generation or
                record._target is not None or record._spent is not True):
            raise _RequestUnavailable()
        record._retire()  # No deletion, ticket refund or reopening of source R.
    except BaseException as error:
        first = _first(first, error)
    try:
        if (type(duty.slot) is not _InventoryNativeSlot or
                duty.slot.attempt is not None or duty.slot.phase != 'uninitialized'):
            raise _RequestUnavailable()
    except BaseException as error:
        first = _first(first, error)
    try:
        children = duty.children
        if type(children) is not _InventoryChildSlot:
            raise _RequestUnavailable()
        if children.phase == 'uninitialized' and children.reservation is None:
            pass  # No child counter duty was created by this original holder.
        elif (children.phase in ('retained', 'retired') and
                type(children.reservation) is _InventoryChildReservationData and
                children.reservation.acquisition is duty and
                children.reservation.begin is begin):
            # Counter cleanup preserves earlier source/native/body controls
            # while independently settling only exact known unpublished or
            # whole committed child DATA tickets. No native/physical refund.
            first = retire_inventory_child_reservation_data(children.reservation, first)
            if children.reservation.phase in ('retired', 'retired-empty'):
                children.phase = 'retired'
        else:
            # Unknown constructor/slot return cannot be retried or reconstructed.
            raise _RequestUnavailable()
    except BaseException as error:
        first = _first(first, error)
    return first


def _retire_registration_data(duty):
    """Remove only known logical entry; no native insertion/deletion/refund.

    Caller must already have matched original custody under original cleanup
    gates and settled every known unstarted/child holder duty. Unknown partial insertion
    or a foreign selected row leaves the retained state alone and refuses.
    Other map entries are not repaired or used as a retirement barrier.
    """
    if (type(duty) is not _InventoryAcquisitionDuty or
            type(duty.inventory_tables) is not tuple or len(duty.inventory_tables) != 2 or
            type(duty.phase) is not str or duty.phase not in
                ('captured', 'refused', 'registration-pending', 'registered', 'retired')):
        raise _RequestUnavailable()
    active, native = duty.inventory_tables
    if (type(active) is not dict or type(native) is not dict or active is native or
            len(active) > 64 or len(native) > 64):
        raise _RequestUnavailable()
    original = duty.original
    # Membership, not get(None): present None is corruption, never absence.
    if (original in native and native[original] is not duty or
            original in active and active[original] is not duty):
        raise _RequestUnavailable()
    if original not in native:
        if original in active or duty.phase not in ('captured', 'refused'):
            raise _RequestUnavailable()
        # Known no-insertion/count-full prefix only. Original request retains
        # this same duty. Unknown registration-pending never gets this result.
        duty.phase = 'retired'
        return
    duty.phase = 'retired'  # BEFORE logical mutation; no acquiring phase exists.
    if original in active:
        del active[original]
    # native[original] remains SAME duty, custody, slot and named charge.


def retire_inventory_handler_duty(store, handler):
    """Before original broker registry release; never authenticates a read.

    This narrow prefix requires a captured registration duty. Earlier begin or
    pre-capture refusal remains the original family/session retirement duty;
    it is not converted into successful cleanup here. No dispatch join exists.
    """
    _owned_store(store)
    original = _retirement_original(store, handler)
    duty = original.guest_response
    custody = _retirement_custody_matches(store, original, handler, duty)
    first = None
    try:
        with _InventoryRetirementGates(custody):
            if _retirement_custody_matches(store, original, handler, duty) is not custody:
                raise _RequestUnavailable()
            first = _retire_unstarted_holders_data(duty, first)
            if first is None:
                try:
                    _retire_registration_data(duty)
                except BaseException as error:
                    first = _first(first, error)
    except BaseException as error:
        first = _first(first, error)
    if first is not None:
        raise store._quarantine(first)


# No acquiring constructor, native attempt call, physical close, frame, ACK,
# store delegation, dispatch join, native-current change or activation.
