"""Known whole committed child retirement DATA, no original cleanup authority.

Unwired: a future original caller MUST first match captured child custody and
enter SAME four retirement gates. Native/physical duties remain with original
outside parent. This helper never repairs unknown mutation/return or grants
reference publication, native currentness, capacity reuse or a response ACK.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_capacity import _CapacityTicket
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_inventory_children_data import (
    _InventoryGuestBatchData, retire_inventory_guest_records_data,
)
from freq.services.pilot_guest_inventory_child_reservation_data import (
    _reservation_retirement_context_data,
)
from freq.services.pilot_guest_retirement import _first


def _whole_retired_children_data(duty):
    """Complete exact known holders, independent of positive/live clocks."""
    batch, ticket = duty.batch, duty.ticket
    if (type(batch) is not _InventoryGuestBatchData or
            batch.begin is not duty.begin or batch.decoded is not duty.decoded or
            batch.ticket is not ticket or type(ticket) is not _CapacityTicket or
            ticket is duty.begin.family._ticket or ticket is duty.begin.record._ticket or
            ticket._session is not duty.begin.session or
            ticket._principal != duty.begin.values[0] or
            type(batch.candidates) is not tuple or
            len(batch.candidates) != duty.count or type(batch.records) is not list or
            len(batch.records) != duty.count or
            type(batch.decoded.targets) is not tuple or
            len(batch.decoded.targets) != duty.count or
            len(batch.decoded.rows) != duty.count or
            any(type(key) is not str or len(key) != 64 or
                any(c not in '0123456789abcdef' for c in key)
                for key in batch.candidates) or
            len(set(batch.candidates)) != duty.count):
        raise _RequestUnavailable()
    keys = []
    for index, record in enumerate(batch.records):
        if (type(record) is not _GuestReferenceRecord or
                record._retired is not True or record._purpose != 'guest' or
                record._key != batch.candidates[index] or record._ticket is not ticket or
                record._session is not duty.begin.session or
                record._principal != duty.begin.values[0] or
                record._family is not duty.begin.family or
                record._source is not duty.begin.source or
                record._cohort is not duty.begin.cohort or
                record._generation is not duty.begin.generation or
                record._target is not batch.decoded.targets[index]):
            raise _RequestUnavailable()
        keys.append((id(record._session), 'guest', record._key))
    return tuple(keys)


def retire_inventory_committed_children_data(duty, first):
    """Retire all known holders, remove only exact rows, settle whole ticket.

    Earlier body/control errors do not skip independently known cleanup. All
    private records must be known and terminal before any index mutation. A
    partial publication may have indexed any subset of this SAME whole batch;
    an absent row alone never proves a refund. The whole exact record set,
    same ticket/ledger and absence of other indexed holders are required.
    Unknown mutation leaves once state pending, charge held, no retry/repair.
    """
    try:
        _reservation_retirement_context_data(duty)
        batch = duty.batch
        if (type(batch) is not _InventoryGuestBatchData or
                batch.begin is not duty.begin or batch.ticket is not duty.ticket or
                batch.decoded is not duty.decoded):
            raise _RequestUnavailable()
    except BaseException as error:
        return _first(first, error)
    # The complete-set check below must not skip later known private holders
    # after a first holder failure, an incomplete batch or earlier body error.
    try:
        holder_error = retire_inventory_guest_records_data(batch, None)
    except BaseException as error:
        holder_error = error
    if holder_error is not None:
        return _first(first, holder_error)
    try:
        keys = _whole_retired_children_data(duty)
        rows, ledger, ticket = duty.component_tables[7], duty.ledger, duty.ticket
        if (type(ticket._remaining) is not int or
                not 0 <= ticket._remaining <= duty.count or
                duty.phase not in ('batch-retained', 'publication-pending', 'issued', 'retired')):
            raise _RequestUnavailable()
        # Recognize only completely settled same known ticket/holders. This
        # can follow original family cleanup without reviving its capacity.
        if (ticket._state == 'retired' and ticket._remaining == 0 and
                id(ticket) not in ledger):
            if (any(key in rows for key in keys) or
                    any(type(record) is not _GuestReferenceRecord or
                        record._ticket is ticket for record in rows.values())):
                raise _RequestUnavailable()
            duty.phase = 'retired'
            return first
        if (duty.phase not in ('batch-retained', 'publication-pending', 'issued') or
                ticket._state != 'committed' or ledger.get(id(ticket)) is not ticket or
                duty.count > 0 and ticket._remaining == 0):
            raise _RequestUnavailable()
        indexed = sum(rows.get(key) is record
                      for key, record in zip(keys, batch.records))
        if indexed > ticket._remaining:
            raise _RequestUnavailable()
        duty.phase = 'indexed-retire-attempted'  # BEFORE first index mutation.
        mutation_error = None
        for key, record in zip(keys, batch.records):
            try:
                if key not in rows:
                    continue  # Full known set still owes whole ticket below.
                if rows[key] is not record:
                    raise _RequestUnavailable()  # Never delete a replacement.
                del rows[key]  # SAME retired exact holder only.
            except BaseException as error:
                mutation_error = _first(mutation_error, error)
        # A hidden/unexpected same-ticket row or malformed unknown entry keeps
        # the ticket charged even after independent known-row cleanup.
        try:
            if any(type(record) is not _GuestReferenceRecord or
                    record._ticket is ticket for record in rows.values()):
                raise _RequestUnavailable()
        except BaseException as error:
            mutation_error = _first(mutation_error, error)
        if mutation_error is not None:
            raise mutation_error
        # All exact known holders terminal, every known row removed, no other
        # index holder uses this SAME ticket. Not an integer refund receipt.
        ticket._remaining = 0
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


# No existing original caller/counter retirement entry is changed or joined.
# No native duty/map/custody/charge is cleared, reset or declared physically closed.
