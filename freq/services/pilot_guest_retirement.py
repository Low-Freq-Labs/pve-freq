"""Guest DATA retirement called by original auth under its existing gates.

No lock acquisition, session lookup, entropy, serialization or native IO here.
No live/positive source authority is issued by this cleanup-only operation.
"""
from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityTicket
from freq.services.guest_reference_state import _GuestReferenceRecord, _refuse
from freq.services.guest_family_state import _GuestFamilyRecord


def _first(first, later):
    if first is None or (issubclass(type(first), Exception) and not issubclass(type(later), Exception)):
        return later
    return first


def retire_guest_session_data_locked(installation, session):
    # This SAME original graph was retained before any native construction.
    # Its existing fixed identity filter also checks the installation type.
    if (installation._original_component_tables_current() is not True or
            type(session) is not dict):
        _refuse()
    by_nonce = installation._guest_families_by_nonce
    by_ref = installation._guest_families_by_ref
    records = installation._guest_reference_records
    capacity = installation._guest_capacity
    if (type(capacity) is not _GuestCapacity or
            any(type(table) is not dict or len(table) > 4096
                for table in (by_nonce, by_ref, records))):
        _refuse()
    first = None
    try:
        families = tuple(by_nonce.items())
    except BaseException as error:
        first = _first(first, error)
        families = ()
    for key, family in families:
        try:
            if (type(family) is not _GuestFamilyRecord or type(key) is not tuple or
                    len(key) != 2 or type(key[0]) is not int or
                    type(key[1]) is not str or
                    key[0] != id(family._session) or key[1] != family._nonce):
                _refuse()
            if family._session is not session:
                continue
            ticket = family._ticket
            if (type(ticket) is not _CapacityTicket or ticket._session is not session or
                    ticket._principal != family._principal or
                    capacity._tickets.get(id(ticket)) is not ticket):
                _refuse()
            family._retire()
            if family._ref is not None:
                # Index may already have been removed at family retirement.
                # Absence does not erase history: family._ref remains until
                # this original SESSION retires. Never remove another family.
                ref_key = (id(session), family._ref)
                indexed = by_ref.get(ref_key)
                if indexed is not None and indexed is not family:
                    _refuse()
                if indexed is family:
                    del by_ref[ref_key]
            del by_nonce[key]
        except BaseException as error:
            first = _first(first, error)
    # This stage runs even if family snapshot/iteration/retirement failed.
    try:
        children = tuple(records.items())
    except BaseException as error:
        first = _first(first, error)
        children = ()
    for key, record in children:
        try:
            if (type(record) is not _GuestReferenceRecord or
                    type(key) is not tuple or len(key) != 3 or
                    type(key[0]) is not int or type(key[1]) is not str or
                    type(key[2]) is not str or
                    key != (id(record._session), record._purpose, record._key)):
                _refuse()
            if record._session is not session:
                continue
            ticket = record._ticket
            family = record._family
            if (type(ticket) is not _CapacityTicket or ticket._session is not session or
                    ticket._principal != record._principal or
                    capacity._tickets.get(id(ticket)) is not ticket or
                    type(family) is not _GuestFamilyRecord or
                    family._session is not session or
                    family._principal != record._principal or
                    family._cohort is not record._cohort or
                    family._generation is not record._generation):
                _refuse()
            record._retire()
            del records[key]
        except BaseException as error:
            first = _first(first, error)
    try:
        # Includes pending/zero-count tickets whose acquiring return was lost.
        # Only DATA charge is retired; native parent duties remain independent.
        capacity._retire_session(session)
    except BaseException as error:
        first = _first(first, error)
    if first is not None:
        try:
            capacity._uncertain = True
        except BaseException as error:
            first = _first(first, error)
        raise first
