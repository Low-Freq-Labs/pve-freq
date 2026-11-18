"""Unwired read-only consumed-source DATA filter; not acquisition authority."""
import math
import re
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _CapacityTicket, _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_inventory_begin import _CorruptInventorySource
from freq.services.pilot_guest_sources_begin import _configured_sources_data


def consumed_inventory_source_data_locked(owner, family, session, principal, reference,
                                   cohort, generation, now):
    """Read-only already-spent SAME source DATA for original continuation.

    Does not consume again, update a clock, repair/refund a row, authenticate
    an original owner or permit acquisition. Actual original gates/context
    must precede it; expiry/backwards time refuses without reviving rights.
    """
    if (type(session) is not dict or type(principal) is not str or not principal or
            type(reference) is not str or re.fullmatch('[0-9a-f]{64}', reference) is None or
            type(now) is not float or not math.isfinite(now) or
            type(family) is not _GuestFamilyRecord or
            family._session is not session or family._principal != principal or
            family._cohort is not cohort or family._generation is not generation or
            family._state != 'live' or family._sources_spent is not True):
        raise _RequestUnavailable()
    rows, capacity = owner._guest_reference_records, owner._guest_capacity
    if (type(rows) is not dict or len(rows) > 4096 or
            type(capacity) is not _GuestCapacity):
        raise _CorruptInventorySource()
    key = (id(session), 'source', reference)
    if key not in rows:
        raise _RequestUnavailable()
    record = rows[key]
    if type(record) is not _GuestReferenceRecord:
        raise _CorruptInventorySource()
    # A genuine row belonging to another live F must never be consumed as the
    # requested F. No corruption or attempt is inferred from that ordinary mix.
    if type(record._family) is not _GuestFamilyRecord:
        raise _CorruptInventorySource()
    if record._family is not family:
        raise _RequestUnavailable()
    ticket = record._ticket
    if (record._key != reference or record._purpose != 'source' or
            record._session is not session or record._principal != principal or
            record._cohort is not cohort or record._generation is not generation or
            record._target is not None or
            type(record._spent) is not bool or type(record._retired) is not bool or
            type(ticket) is not _CapacityTicket or ticket._state != 'committed' or
            ticket._session is not session or ticket._principal != principal or
            type(ticket._remaining) is not int or ticket._remaining < 1 or
            capacity._tickets.get(id(ticket)) is not ticket or
            any(type(value) is not float or not math.isfinite(value)
                for value in (record._created, record._expires, record._last_clock)) or
            not family._created <= record._created < record._expires <=
                min(record._created + 30.0, family._expires) or
            not record._created <= record._last_clock < record._expires):
        raise _CorruptInventorySource()
    try:
        capacity._check()
        configured = _configured_sources_data(cohort, generation)
    except Exception:
        raise _CorruptInventorySource() from None
    if ticket._remaining > len(configured):
        raise _CorruptInventorySource()
    source = record._source
    if (type(source) is not tuple or len(source) != 2 or
            type(source[1]) is not TargetSnapshot or
            source[1].configuration_revision is not generation or
            not any(row is source for row in configured)):
        raise _CorruptInventorySource()
    if record._spent is not True or record._retired:
        raise _RequestUnavailable()
    if now < record._last_clock or not now < record._expires:
        raise _RequestUnavailable()
    return record
