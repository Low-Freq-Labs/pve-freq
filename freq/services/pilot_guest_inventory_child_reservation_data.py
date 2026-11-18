"""Whole child ticket pending-retention DATA prefix, no original admission.

Caller-supplied owner/request/decoded DATA never creates native source or
original writer authority. A future original caller must authenticate the same
source result/recipient/parent, enter its same writer and retain this holder
BEFORE this once-only counter operation. No original positive reservation
caller is joined here; separate retirement source uses captured child custody.
No entropy, child construction, ticket commit/index/refund or response exists.
"""
import math

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityTicket
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_inventory_registration import (
    _InventoryAcquisitionDuty, _InventoryChildSlot, _inventory_registration_tables_data,
)
from freq.services.pilot_guest_inventory_begin import _GuestInventoryBeginDuty
from freq.services.pilot_guest_inventory_children_data import (
    _DecodedGuestRowsData, _InventoryGuestBatchData,
    retire_inventory_guest_records_data,
)
from freq.services.pilot_guest_retirement import _first


class _InventoryChildReservationData:
    """Pure retained whole reservation obligation, never an authority receipt.

    The actual original owner must retain this SAME object before reserve.
    Missing original guarded reservation/source-result authority cannot be replaced by
    merely constructing this DATA object or returning its ticket.
    """
    __slots__ = ('owner', 'acquisition', 'begin', 'decoded', 'capacity', 'ledger',
                 'component_tables', 'inventory_tables', 'created', 'end',
                 'count', 'ticket', 'batch', 'phase')

    def __init__(self, owner, acquisition, decoded, now):
        if (type(acquisition) is not _InventoryAcquisitionDuty or
                type(decoded) is not _DecodedGuestRowsData or
                type(now) is not float or not math.isfinite(now) or
                type(acquisition.end) is not float or not math.isfinite(acquisition.end) or
                type(acquisition.last_clock) is not float or
                not acquisition.last_clock <= now < acquisition.end):
            raise _RequestUnavailable()
        self.owner, self.acquisition = owner, acquisition
        self.begin, self.decoded = acquisition.begin, decoded
        self.capacity, self.ledger = owner._guest_capacity, owner._guest_capacity._tickets
        self.component_tables, self.inventory_tables = (
            acquisition.component_tables, acquisition.inventory_tables)
        self.created, self.end = now, acquisition.end
        self.count = len(decoded.rows)
        self.ticket = self.batch = None
        self.phase = 'new'


def retain_inventory_child_reservation_data(owner, acquisition, decoded, now):
    """One fixed child DATA holder on SAME acquisition, before counter effects.

    No original native result/receipt, writer or parser allowance follows from
    this shape-only helper. The future original guarded caller is still absent.
    A reconstructed counter object cannot replace the exact retained object.
    """
    if (type(acquisition) is not _InventoryAcquisitionDuty or
            acquisition.phase != 'registered' or
            type(acquisition.children) is not _InventoryChildSlot):
        raise _RequestUnavailable()
    active, native = _inventory_registration_tables_data(owner, acquisition)
    slot = acquisition.children
    if (active.get(acquisition.original) is not acquisition or
            native.get(acquisition.original) is not acquisition or
            slot.phase != 'uninitialized' or slot.reservation is not None):
        raise _RequestUnavailable()
    slot.phase = 'retention-attempted'  # BEFORE unknown pure constructor return.
    slot.reservation = _InventoryChildReservationData(owner, acquisition, decoded, now)
    slot.phase = 'retained'  # Exact object is retained BEFORE any counter call.


def _reservation_context_data(duty):
    """Identity/shape DATA only; never actual original guards or native proof."""
    if type(duty) is not _InventoryChildReservationData:
        raise _RequestUnavailable()
    owner, acquisition, begin = duty.owner, duty.acquisition, duty.begin
    if (type(acquisition) is not _InventoryAcquisitionDuty or
            begin is not acquisition.begin or acquisition.phase != 'registered' or
            type(acquisition.children) is not _InventoryChildSlot or
            acquisition.children.phase != 'retained' or
            acquisition.children.reservation is not duty or
            type(duty.decoded) is not _DecodedGuestRowsData or
            type(duty.decoded.rows) is not tuple or
            type(duty.count) is not int or not 0 <= duty.count <= 256 or
            duty.count != len(duty.decoded.rows) or
            type(duty.capacity) is not _GuestCapacity or
            duty.capacity is not owner._guest_capacity or
            type(duty.ledger) is not dict or duty.ledger is not duty.capacity._tickets or
            duty.component_tables is not acquisition.component_tables or
            duty.component_tables is not owner._original_component_tables or
            type(duty.component_tables) is not tuple or len(duty.component_tables) != 9 or
            duty.component_tables[8] is not duty.ledger or
            duty.inventory_tables is not acquisition.inventory_tables or
            duty.inventory_tables is not owner._original_guest_inventory_tables or
            any(type(x) is not float or not math.isfinite(x)
                for x in (duty.created, duty.end, acquisition.end, acquisition.last_clock)) or
            duty.end != acquisition.end or
            not acquisition.last_clock <= duty.created < duty.end):
        raise _RequestUnavailable()
    active, native = _inventory_registration_tables_data(owner, acquisition)
    if (active.get(acquisition.original) is not acquisition or
            native.get(acquisition.original) is not acquisition or
            begin.record._spent is not True or begin.record._retired is not False or
            begin.family._state != 'live' or begin.family._sources_spent is not True):
        raise _RequestUnavailable()
    # Context-free private preparation validator runs BEFORE reservation,
    # using a pure unretained placeholder ticket, not a ledger reservation.
    # It validates the same entire source/rows/clock with the candidate count.
    # No record is constructed and no ticket is inserted by this constructor.
    from freq.services.pilot_guest_inventory_children_data import _whole_inventory_batch_data
    shape_ticket = _CapacityTicket(begin.session, begin.values[0], duty.count)
    shape_batch = _InventoryGuestBatchData(begin, duty.decoded, shape_ticket, duty.created)
    _whole_inventory_batch_data(shape_batch)


def reserve_inventory_children_data(duty):
    """Whole logical count once; known full is ordinary and inserts nothing.

    No positive operation follows from return. The original enclosing writer
    must already be held. Unknown reservation/batch return stays retained and
    charged in the same ledger; caller must quarantine the original instance
    and retire known holders before any entropy/acquiring work can be joined.
    """
    _reservation_context_data(duty)
    if duty.phase != 'new' or duty.ticket is not None or duty.batch is not None:
        raise _RequestUnavailable()
    capacity = duty.capacity
    total, sessions = capacity._check()
    begin = duty.begin
    bucket = sessions.get(id(begin.session))
    used, tickets = (0, 0) if bucket is None else (bucket[2], bucket[3])
    if bucket is not None and (bucket[0] is not begin.session or bucket[1] != begin.values[0]):
        raise _RequestUnavailable()
    if (total + duty.count > 4096 or used + duty.count > 512 or
            tickets >= 512 or len(duty.ledger) >= 4096):
        duty.phase = 'refused'  # Permanent once result; source R stays spent.
        return
    duty.phase = 'reserve-attempted'  # BEFORE unknown counter insertion return.
    try:
        duty.ticket = capacity._reserve(begin.session, begin.values[0], duty.count)
        duty.phase = 'reserved'  # Retain exact ticket BEFORE pure batch allocation.
        duty.batch = _InventoryGuestBatchData(begin, duty.decoded, duty.ticket, duty.created)
        duty.phase = 'batch-retained'
    except BaseException as error:
        first = error
        try:
            capacity._uncertain = True
        except BaseException as later:
            first = _first(first, later)
        # No reset/delete/scan-and-adopt of a lost return, refund, or retry.
        raise first


def _reservation_retirement_context_data(duty):
    """Captured DATA graph only; no own positive/live/capacity flags.

    Actual enclosing original retirement custody/four guards MUST precede
    this helper once integrated. These tuples are no substitute for them.
    """
    if type(duty) is not _InventoryChildReservationData:
        raise _RequestUnavailable()
    owner, acquisition = duty.owner, duty.acquisition
    if (type(acquisition) is not _InventoryAcquisitionDuty or
            type(acquisition.children) is not _InventoryChildSlot or
            acquisition.children.phase not in ('retained', 'retired') or
            acquisition.children.reservation is not duty or
            type(duty.begin) is not _GuestInventoryBeginDuty or
            duty.begin is not acquisition.begin or
            type(duty.begin.values) is not tuple or len(duty.begin.values) != 5 or
            type(duty.capacity) is not _GuestCapacity or
            duty.capacity is not owner._guest_capacity or
            duty.capacity is not owner._original_guest_capacity or
            type(duty.ledger) is not dict or len(duty.ledger) > 4096 or
            duty.ledger is not duty.capacity._tickets or
            type(duty.component_tables) is not tuple or len(duty.component_tables) != 9 or
            duty.component_tables is not owner._original_component_tables or
            duty.component_tables is not acquisition.component_tables or
            duty.component_tables[8] is not duty.ledger or
            type(duty.inventory_tables) is not tuple or len(duty.inventory_tables) != 2 or
            duty.inventory_tables is not owner._original_guest_inventory_tables or
            duty.inventory_tables is not acquisition.inventory_tables or
            any(type(table) is not dict or len(table) > 64 for table in duty.inventory_tables) or
            duty.inventory_tables[0] is not owner._guest_inventory_attempts or
            duty.inventory_tables[0] is duty.inventory_tables[1] or
            any(table is previous for table in duty.inventory_tables
                for previous in duty.component_tables) or
            duty.inventory_tables[1] is not owner._native_guest_inventory_attempts or
            duty.inventory_tables[1].get(acquisition.original) is not acquisition or
            type(duty.count) is not int or not 0 <= duty.count <= 256):
        raise _RequestUnavailable()
    # No positive original-map validator; own quarantine may have disabled it.
    capacity = duty.capacity
    current = (owner._auth_attempts, owner._asset_attempts, owner._issued_sessions,
        owner._read_attempts, owner._native_read_attempts, owner._guest_families_by_nonce,
        owner._guest_families_by_ref, owner._guest_reference_records, capacity._tickets)
    if (any(a is not b for a, b in zip(duty.component_tables, current)) or
            any(type(table) is not dict for table in current) or
            any(current[i] is current[j] for i in range(9) for j in range(i)) or
            any(len(table) > 4096 for table in current[5:])):
        raise _RequestUnavailable()


def retire_inventory_child_reservation_data(duty, first):
    """Retire known child holders, then settle ONLY their exact known ticket.

    Supplied DATA is not original cleanup authority. Future original caller
    must retain/match duty in retirement-only custody under SAME four gates.
    Native obligations/unknown allocation remain with outside parent. Ledger
    counter settlement cannot establish physical close or native charge refund.
    """
    try:
        _reservation_retirement_context_data(duty)
    except BaseException as error:
        return _first(first, error)
    # Future committed/partly indexed whole batches have a separate exact
    # known-holder retirement path. This late canonical import leaves module
    # setup acyclic. Same enclosing original custody/four gates remain owed;
    # a committed DATA ticket never establishes publication or that authority.
    try:
        ticket, batch = duty.ticket, duty.batch
        committed = type(ticket) is _CapacityTicket and ticket._state == 'committed'
        settled_prepared = (type(ticket) is _CapacityTicket and
            ticket._state == 'retired' and ticket._remaining == 0 and
            type(batch) is _InventoryGuestBatchData and batch.phase == 'prepared')
        if committed or settled_prepared:
            from freq.services.pilot_guest_inventory_committed_retirement_data import retire_inventory_committed_children_data
            return retire_inventory_committed_children_data(duty, first)
    except BaseException as error:
        return _first(first, error)
    # Independently known private records are attempted before any ticket
    # disposition, even when an earlier body/control error already exists.
    holder_error = None
    if duty.batch is not None:
        if (type(duty.batch) is not _InventoryGuestBatchData or
                duty.batch.begin is not duty.begin or duty.batch.ticket is not duty.ticket or
                duty.batch.decoded is not duty.decoded):
            holder_error = _RequestUnavailable()
        else:
            # Before preparation there are no candidates/records; do not pass
            # that state to the helper for retained prepared/partial holders.
            if duty.batch.phase == 'new' and duty.batch.candidates is None and duty.batch.records == []:
                pass
            else:
                holder_error = retire_inventory_guest_records_data(duty.batch, None)
    if holder_error is not None:
        return _first(first, holder_error)  # No refund after unknown holder retirement.
    # A prior body/control error does NOT skip independently known ticket
    # cleanup once every known child holder has settled. Preserve it afterward.
    try:
        ticket, ledger = duty.ticket, duty.ledger
        if ticket is None:
            if duty.phase not in ('new', 'refused', 'retired-empty') or duty.batch is not None:
                raise _RequestUnavailable()  # Lost reserve return: no scan/adopt.
            duty.phase = 'retired-empty'
            return first
        if (type(ticket) is not _CapacityTicket or
                ticket._session is not duty.begin.session or
                ticket._principal != duty.begin.values[0] or
                type(ticket._remaining) is not int or ticket._remaining != duty.count):
            raise _RequestUnavailable()
        rows = duty.component_tables[7]
        for record in rows.values():
            if type(record) is not _GuestReferenceRecord or record._ticket is ticket:
                raise _RequestUnavailable()  # No partial/indexed ticket refund.
        if duty.phase == 'retired':
            if ticket._state != 'retired' or id(ticket) in ledger:
                raise _RequestUnavailable()
            return first
        if (duty.phase not in ('reserved', 'batch-retained') or
                ticket._state != 'reserved' or ledger.get(id(ticket)) is not ticket):
            raise _RequestUnavailable()
        duty.phase = 'retire-attempted'  # BEFORE either terminal ledger mutation.
        ticket._state = 'retired'
        del ledger[id(ticket)]
        duty.phase = 'retired'
    except BaseException as error:
        first = _first(first, error)
        try:
            duty.capacity._uncertain = True
        except BaseException as later:
            first = _first(first, later)
    return first


# Counter DATA prefix only. Original holder storage/custody/four-guard join,
# actual native result receipt, whole entropy/issuer/frame/dispatch unfinished.
