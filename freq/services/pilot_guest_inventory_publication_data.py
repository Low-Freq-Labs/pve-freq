"""Read-only whole inventory index preflight DATA, no original publication.

The original caller must hold its SAME writer and validate native whole-result,
recipient, session/cohort/source, retained child duty, first end and aggregate
allowances before using this helper. Returned keys are DATA, never admission,
ledger membership receipts, an issuer or a lock. This code commits nothing.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityTicket
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_inventory_children_data import (
    prepared_inventory_guest_records_data,
)


def inventory_publication_keys_data(owner, batch):
    """Refuse any collision or malformed existing row before any whole commit.

    Same-session guest-purpose keys remain occupied even when spent/retired.
    Other purposes and other sessions have distinct original index domains.
    No row is removed, overwritten, adopted, retried or rekeyed. Existing
    row/ticket consistency is a refusal filter, not original writer authority
    or a complete proof of family/ticket/reference accounting.
    """
    prepared_inventory_guest_records_data(batch)
    capacity, rows, tables = (owner._guest_capacity,
        owner._guest_reference_records, owner._original_component_tables)
    ticket, begin = batch.ticket, batch.begin
    if (type(capacity) is not _GuestCapacity or
            capacity is not owner._original_guest_capacity or
            type(rows) is not dict or len(rows) + len(batch.records) > 4096 or
            type(tables) is not tuple or len(tables) != 9 or
            any(type(table) is not dict for table in tables) or
            any(tables[i] is tables[j] for i in range(9) for j in range(i)) or
            tables[7] is not rows or tables[8] is not capacity._tickets or
            type(capacity._tickets) is not dict or
            capacity._tickets.get(id(ticket)) is not ticket or
            ticket._state != 'reserved' or ticket._remaining != len(batch.records)):
        raise _RequestUnavailable()
    capacity._check()  # Existing counters only; does not reserve or authenticate.
    if any(type(candidate) is not str or len(candidate) != 64 or
            any(c not in '0123456789abcdef' for c in candidate)
            for candidate in batch.candidates):
        raise _RequestUnavailable()
    for key, record in rows.items():
        if (type(record) is not _GuestReferenceRecord or
                type(key) is not tuple or len(key) != 3 or
                type(key[0]) is not int or type(key[1]) is not str or
                key[1] not in ('source', 'guest') or
                type(key[2]) is not str or len(key[2]) != 64 or
                any(c not in '0123456789abcdef' for c in key[2]) or
                type(record._session) is not dict or
                key != (id(record._session), record._purpose, record._key) or
                type(record._principal) is not str or not record._principal or
                type(record._ticket) is not _CapacityTicket or
                record._ticket is ticket or
                record._ticket._session is not record._session or
                record._ticket._principal != record._principal or
                record._ticket._state != 'committed' or
                capacity._tickets.get(id(record._ticket)) is not record._ticket):
            raise _RequestUnavailable()
    keys = tuple((id(begin.session), 'guest', record._key) for record in batch.records)
    if (len(set(keys)) != len(keys) or
            any(key in rows for key in keys)):
        raise _RequestUnavailable()
    return keys


# No counter mutation, clock, entropy, record creation, original guards,
# acquiring work, publication/frame retention, HTTP admission, send or ACK.
