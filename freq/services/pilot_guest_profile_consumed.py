"""Unwired read-only consumed guest DATA, never a second consumption/grant.

Actual original writer/auth/family/currentness/recipient/first end must precede
this helper. It never updates record clocks, repairs/refunds rows, authenticates
an owner, acquires anything or permits a native continuation by its return.
"""
import math
import re
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _CapacityTicket, _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_profile_begin import _CorruptProfileSource
from freq.services.pilot_guest_sources_begin import _configured_sources_data


def consumed_profile_guest_data_locked(owner, family, session, principal, reference,
                                   cohort, generation, now):
    """Read-only already-spent SAME guest DATA; authenticates nobody.

    Original caller must already hold its same writer and positive native,
    auth, session, family, cohort and recipient guards. Missing or other-family
    rights are ordinary refusals; a malformed selected ledger row is corrupt.
    No sweep, other-purpose fallback, reference consumption or native IO.
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
        raise _CorruptProfileSource()
    key = (id(session), 'guest', reference)
    if key not in rows:
        raise _RequestUnavailable()
    record = rows[key]
    if type(record) is not _GuestReferenceRecord:
        raise _CorruptProfileSource()
    # A genuine row belonging to another live F must never be consumed as the
    # requested F. No corruption or attempt is inferred from that ordinary mix.
    if type(record._family) is not _GuestFamilyRecord:
        raise _CorruptProfileSource()
    if record._family is not family:
        raise _RequestUnavailable()
    ticket = record._ticket
    if (type(record._key) is not str or record._key != reference or
            type(record._purpose) is not str or record._purpose != 'guest' or
            record._session is not session or record._principal != principal or
            record._cohort is not cohort or record._generation is not generation or
            type(record._target) is not tuple or len(record._target) != 3 or
            type(record._target[0]) is not str or
            re.fullmatch('[A-Za-z0-9][A-Za-z0-9.-]{0,63}', record._target[0]) is None or
            type(record._target[1]) is not str or record._target[1] not in ('qemu', 'lxc') or
            type(record._target[2]) is not int or not 100 <= record._target[2] <= 999999999 or
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
        raise _CorruptProfileSource()
    try:
        capacity._check()
        configured = _configured_sources_data(cohort, generation)
    except MemoryError:
        raise
    except Exception:
        raise _CorruptProfileSource() from None
    if ticket._remaining > 256:
        raise _CorruptProfileSource()
    source = record._source
    if (type(source) is not tuple or len(source) != 2 or
            type(source[1]) is not TargetSnapshot or
            source[1].configuration_revision is not generation or
            not any(row is source for row in configured)):
        raise _CorruptProfileSource()
    if record._spent is not True or record._retired:
        raise _RequestUnavailable()
    if now < record._last_clock or not now < record._expires:
        raise _RequestUnavailable()
    return record
