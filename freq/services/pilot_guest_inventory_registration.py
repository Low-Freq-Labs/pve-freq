"""Unwired original inventory duty registration; no acquiring operation.

This prefix retains a SAME original private context and named logical charge.
It constructs no credential/trust/socket/native attempt, grants no acquisition
right and enforces no physical/RSS/aggregate Cluster+inventory allowance. The
actual original parent must retain/enforce those before any acquiring effect.
Native-current remains False. No store/dispatcher or acquisition join exists.
"""
import math
import threading

from freq.api import auth
from freq.services.cluster_pilot_http import _RequestUnavailable, _OriginalRequest
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_inventory_begin import (
    _GuestInventoryBeginDuty, _InventoryBeginGates, _CorruptInventorySource,
)
from freq.services.pilot_guest_sources_begin import (
    _source_family_data_locked, _ExpiredSourceFamily, _CorruptSourceFamily,
)


# Same fixed source-adopted private exchange/trust logical allowance. This is
# an obligation recorded before future effects, never an allowance authority.
INVENTORY_EXCHANGE_TRUST_CHARGE = 15442019


class _InventoryNativeSlot:
    """Retained pure placeholder; no constructor callback or acquire method."""
    __slots__ = ('attempt', 'phase')

    def __init__(self):
        self.attempt = None
        self.phase = 'uninitialized'


class _InventoryChildSlot:
    """One retained pure child-counter holder; no reserve/acquiring method."""
    __slots__ = ('reservation', 'phase')

    def __init__(self):
        self.reservation = None
        self.phase = 'uninitialized'


class _InventoryAcquisitionDuty:
    __slots__ = ('original', 'begin', 'end', 'last_clock', 'charge',
                 'credential_uid', 'configured_token', 'component_tables',
                 'inventory_tables', 'slot', 'children', 'custody', 'phase')

    def __init__(self, original, begin):
        if (type(begin) is not _GuestInventoryBeginDuty or begin.original is not original or
                type(begin.end) is not float or not math.isfinite(begin.end)):
            raise _RequestUnavailable()
        self.original, self.begin = original, begin
        self.end, self.last_clock = begin.end, None
        self.charge = INVENTORY_EXCHANGE_TRUST_CHARGE
        self.credential_uid = self.configured_token = None
        self.component_tables = self.inventory_tables = None
        self.slot = _InventoryNativeSlot()  # No native object or resource.
        self.children = _InventoryChildSlot()  # Before any future child effect.
        self.custody = None
        self.phase = 'new'


class _InventoryRetirementCustody:
    """Immutable retained identities only; not authority or cleanup proof.

    Future cleanup must independently validate this snapshot and nonblocking
    SAME original gates without positive live/currentness flags. This prefix
    implements neither cleanup nor a positive native admission predicate.
    """
    __slots__ = ('items',)

    def __init__(self, store, original, handler, duty):
        owner, broker = store._installation, store._broker
        refs, server = store._references, owner._server
        locks = (owner._gate, auth._auth_lock, refs._lock, broker._gate)
        object.__setattr__(self, 'items', (
            store, owner, store._auth, broker, refs, server, broker._requests,
            original, handler, original.socket, original.thread,
            duty.component_tables, owner._guest_capacity, locks,
            duty, duty.begin, duty.begin.record, duty.begin.family,
            duty.begin.source, duty.begin.cohort, duty.begin.generation,
            duty.inventory_tables, duty.inventory_tables[0], duty.inventory_tables[1],
            duty.slot, duty.configured_token, duty.credential_uid, duty.end,
            duty.children))

    def __setattr__(self, name, value):
        raise TypeError('Original inventory retirement custody is immutable')

    def __delattr__(self, name):
        raise TypeError('Original inventory retirement custody is immutable')


def _inventory_registration_tables_data(owner, duty):
    """Check bounded typed pending DATA, never original/native authority.

    The actual original writer/currentness must precede this helper. Existing
    entries are retained logical obligations, not successful read evidence.
    This prefix has no acquiring phase yet; other native slot shapes refuse.
    """
    if type(duty) is not _InventoryAcquisitionDuty:
        raise _CorruptInventorySource()
    tables, components = duty.inventory_tables, duty.component_tables
    if (type(components) is not tuple or len(components) != 9 or
            any(type(x) is not dict for x in components) or
            owner._original_component_tables is not components or
            type(tables) is not tuple or
            len(tables) != 2 or any(type(x) is not dict or len(x) > 64 for x in tables) or
            tables[0] is tables[1] or
            owner._original_guest_inventory_tables is not tables or
            owner._guest_inventory_attempts is not tables[0] or
            owner._native_guest_inventory_attempts is not tables[1] or
            any(x is prior for x in tables for prior in components)):
        raise _CorruptInventorySource()
    active, native = tables
    for original, retained in native.items():
        if (type(original) is not _OriginalRequest or
                type(retained) is not _InventoryAcquisitionDuty or
                retained.original is not original or
                type(retained.begin) is not _GuestInventoryBeginDuty or
                retained.begin.original is not original or
                retained.component_tables is not duty.component_tables or
                retained.inventory_tables is not tables or
                type(retained.charge) is not int or
                retained.charge != INVENTORY_EXCHANGE_TRUST_CHARGE or
                type(retained.slot) is not _InventoryNativeSlot or
                retained.slot.attempt is not None or retained.slot.phase != 'uninitialized' or
                type(retained.custody) is not _InventoryRetirementCustody or
                type(retained.custody.items) is not tuple or len(retained.custody.items) != 29 or
                retained.phase not in ('registered', 'retired')):
            raise _CorruptInventorySource()
        _inventory_child_slot_data(owner, retained)
    for original, retained in active.items():
        if native.get(original) is not retained:
            raise _CorruptInventorySource()
    return active, native


def _inventory_child_slot_data(owner, duty):
    """Fixed private child shape only; never source/body/writer authority."""
    if type(duty) is not _InventoryAcquisitionDuty or type(duty.children) is not _InventoryChildSlot:
        raise _CorruptInventorySource()
    slot = duty.children
    if slot.phase == 'uninitialized' and slot.reservation is None:
        return
    # Canonical late import avoids registration/counter module initialization
    # cycle. Import setup is not claimed resource-free/native-parent coverage.
    from freq.services.pilot_guest_inventory_child_reservation_data import _InventoryChildReservationData
    reservation = slot.reservation
    if (type(reservation) is not _InventoryChildReservationData or
            reservation.owner is not owner or reservation.acquisition is not duty or
            reservation.begin is not duty.begin or
            slot.phase not in ('retained', 'retired') or
            slot.phase == 'retired' and reservation.phase not in ('retired', 'retired-empty')):
        raise _CorruptInventorySource()


def _register_inventory_duty_data(owner, duty):
    """Whole named DATA charge before mutation; no rollback on lost return.

    Known full returns False without inserting anything. No native resource
    exists in this prefix. Unknown insertion return stays retained/charged
    where known and must quarantine the original owner without retry.
    """
    if (type(duty) is not _InventoryAcquisitionDuty or duty.phase != 'captured' or
            type(duty.original) is not _OriginalRequest or
            type(duty.charge) is not int or
            duty.charge != INVENTORY_EXCHANGE_TRUST_CHARGE or
            type(duty.slot) is not _InventoryNativeSlot or
            duty.slot.attempt is not None or duty.slot.phase != 'uninitialized' or
            type(duty.children) is not _InventoryChildSlot or
            duty.children.reservation is not None or duty.children.phase != 'uninitialized' or
            type(duty.custody) is not _InventoryRetirementCustody):
        raise _CorruptInventorySource()
    active, native = _inventory_registration_tables_data(owner, duty)
    if duty.original in active or duty.original in native:
        raise _CorruptInventorySource()
    if len(active) >= 64 or len(native) >= 64:
        return False
    duty.phase = 'registration-pending'  # BEFORE either namespace mutation.
    native[duty.original] = duty  # Permanent same-duty retention first.
    active[duty.original] = duty
    duty.phase = 'registered'
    return True


def register_inventory_acquisition(store, handler):
    """Spend this SAME original registration once; no acquisition follows.

    Actual future acquisition must separately validate/retain original parent,
    aggregate allowances and SAME fixed native holder before construction/run.
    No returned tuple, class or placeholder permits that work by itself.
    """
    owner = _owned_store(store)  # Refuse substitutes before handler hooks.
    original = store._broker._owned(handler)
    begin = original.guest_response
    if (type(begin) is not _GuestInventoryBeginDuty or begin.original is not original or
            begin.phase != 'spent' or type(original.operation) is not str or
            original.operation != 'guest-owner-inventory' or
            original.body_taken is not True or
            not auth._cluster_pilot_direct_tls(handler) or
            not auth.same_origin_or_absent(handler, require_present=True, is_https=True)):
        raise _RequestUnavailable()
    duty = _InventoryAcquisitionDuty(original, begin)
    with _InventoryBeginGates(store._auth, original, begin):
        cohort, generation, now = store._guard_locked(original,
            begin.token, begin.session, begin.values)
        store._csrf_nonce_locked(handler, 'cookie', begin.values, begin.family_ref)
        if (original.guest_response is not begin or begin.phase != 'spent' or
                original.thread is not threading.current_thread() or
                not now < begin.end):
            raise _RequestUnavailable()
        try:
            # Before any further F/R lookup, count or unknown registration return.
            # Even known full cannot license retrying this same original duty.
            begin.phase = 'registration-attempted'
            original.guest_response = duty
        except BaseException as error:
            raise store._quarantine(error)
        try:
            family = _source_family_data_locked(owner, begin.session, begin.values[0],
                begin.family_ref, cohort, generation, now)
        except _ExpiredSourceFamily as expired:
            store._retire_known_family_locked(expired.family)
            raise _RequestUnavailable() from None
        except _CorruptSourceFamily as error:
            raise store._quarantine(error)
        # This separate read-only predicate requires already-spent SAME source.
        # It must never call the begin helper, which deliberately refuses spent R.
        from freq.services.pilot_guest_inventory_consumed import consumed_inventory_source_data_locked
        try:
            record = consumed_inventory_source_data_locked(owner, family,
                begin.session, begin.values[0], begin.source_ref, cohort, generation, now)
        except _CorruptInventorySource as error:
            raise store._quarantine(error)
        if (family is not begin.family or record is not begin.record or
                record._source is not begin.source or cohort is not begin.cohort or
                generation is not begin.generation or
                owner._original_guest_inventory_tables_current() is not True):
            raise _RequestUnavailable()
        uid, token = owner._credential_uid, owner._configured_token_id
        if (type(uid) is not int or not 1 <= uid <= 4294967294 or
                type(token) is not tuple or len(token) != 2 or
                any(type(x) is not str for x in token) or
                not 0 < len(token[0]) <= 257 or not 0 < len(token[1]) <= 128 or
                cohort.token_id is not token):
            raise _RequestUnavailable()
        duty.end = min(begin.end, original.end, original.write_end,
            family._expires, record._expires)
        if not now < duty.end:
            raise _RequestUnavailable()
        duty.last_clock, duty.credential_uid, duty.configured_token = now, uid, token
        duty.component_tables = owner._original_component_tables
        duty.inventory_tables = owner._original_guest_inventory_tables
        try:
            begin.end = min(begin.end, duty.end)
            original.write_end = min(original.write_end, duty.end)
            duty.custody = _InventoryRetirementCustody(store, original, handler, duty)
            duty.phase = 'captured'
            registered = _register_inventory_duty_data(owner, duty)
        except BaseException as error:
            raise store._quarantine(error)
        if not registered:
            duty.phase = 'refused'  # Known full: no new entry or acquiring work.
            raise _RequestUnavailable()
    return duty


# No native attempt constructor/run, cleanup/clear/refund, store or dispatch join.
