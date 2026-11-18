"""Whole inventory index commit DATA; no original publication authority.

The future original caller must retain this exact child reservation, validate
the original complete native result, session/source/cohort/recipient/end and
whole-job allowances, and hold its SAME writer before calling this helper.
No such caller is joined here. Supplied objects, keys or a returned phase are
never a native receipt, frame admission or browser capability.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.pilot_guest_inventory_child_reservation_data import (
    _reservation_context_data,
)
from freq.services.pilot_guest_inventory_children_data import _InventoryGuestBatchData
from freq.services.pilot_guest_inventory_publication_data import inventory_publication_keys_data
from freq.services.pilot_guest_retirement import _first


def commit_inventory_children_data(duty):
    """Preflight the WHOLE batch, then spend this exact commit once.

    Same original writer makes the multi-assignment transition indivisible to
    other admitted callers; Python dictionaries alone do not provide that.
    Every collision/shape check precedes the first mutation. Once mutation may
    have started, no retry, rollback, partial success or inferred refund is
    allowed. Known records and ticket remain retained for independent cleanup.
    Actual original quarantine and physical parent custody remain owed by the
    enclosing caller even when this local capacity flag could not be written.
    """
    _reservation_context_data(duty)  # Reject foreign type before any hooks.
    batch = duty.batch
    if (duty.phase != 'batch-retained' or
            type(batch) is not _InventoryGuestBatchData or
            batch.begin is not duty.begin or batch.decoded is not duty.decoded or
            batch.ticket is not duty.ticket or batch.created != duty.created or
            len(batch.records) != duty.count):
        raise _RequestUnavailable()
    owner, capacity = duty.owner, duty.capacity
    keys = inventory_publication_keys_data(owner, batch)
    rows = duty.component_tables[7]
    if len(keys) != duty.count or rows is not owner._guest_reference_records:
        raise _RequestUnavailable()
    try:
        # Existing committed-retirement path recognizes this permanent state.
        # Retain SAME records/ticket before the first unknown commit return.
        duty.phase = 'publication-pending'
        capacity._commit(duty.ticket)
        for key, record in zip(keys, batch.records):
            rows[key] = record
        if not keys:
            capacity._retire_empty_committed(duty.ticket)
        duty.phase = 'issued'
    except BaseException as error:
        first = error
        try:
            capacity._uncertain = True
        except BaseException as later:
            first = _first(first, later)
        raise first


# No entropy, network, clock, original guards, native-current, frame/send/ACK,
# store delegation or dispatch join. Physical/native charges are never cleared.
