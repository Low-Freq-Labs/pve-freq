"""Unwired original inventory source-reference consumption prefix.

No credential, trust, entropy, network, parser, child capacity or response is
acquired here. The return is retained private bookkeeping, never a native read
grant. A later original continuation must retain and revalidate its own exact
outside duties under the same shortened end before acquiring anything.
"""
import math
import re

from freq.api import auth
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _CapacityTicket, _GuestCapacity
from freq.services.guest_reference_state import (
    _GuestReferenceRecord, _Unavailable as _ReferenceUnavailable,
)
from freq.services.pilot_auth_commit import _OrderedAuthGates
from freq.services.pilot_guest_reference_store import _OpeningResponseGates
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_sources_begin import (
    _source_family_data_locked, _ExpiredSourceFamily, _CorruptSourceFamily,
    _configured_sources_data,
)


class _CorruptInventorySource(_RequestUnavailable):
    pass


class _GuestInventoryBeginDuty:
    """Pure retained original context, with no acquisition or refund method."""
    __slots__ = ('original', 'token', 'session', 'values', 'family_ref',
                 'source_ref', 'family', 'record', 'source', 'cohort',
                 'generation', 'created', 'initial_write_end', 'resource_end',
                 'end', 'phase', '_initialization_started',
                 '_initialization_complete')

    def __init__(self, original, token, session, values, family_ref, source_ref):
        # Same original request roots this blank holder BEFORE initialization.
        # Partial initialization stays spent and cannot be restarted.
        if (type(self) is not _GuestInventoryBeginDuty or
                getattr(self, '_initialization_started', None) is not None or
                original.guest_response is not self):
            raise _RequestUnavailable()
        self._initialization_started = True
        self._initialization_complete = False
        if (type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or
                not math.isfinite(original.write_end)):
            raise _RequestUnavailable()
        self.original, self.token, self.session = original, token, session
        self.values, self.family_ref, self.source_ref = values, family_ref, source_ref
        self.family = self.record = self.source = self.cohort = self.generation = None
        self.created = self.resource_end = None
        self.initial_write_end = original.write_end
        self.end = min(original.end, self.initial_write_end)
        self.phase = 'new'
        self._initialization_complete = True  # Final publication marker only.


class _InventoryBeginGates(_OpeningResponseGates):
    def __init__(self, transaction, original, duty, phase='ready'):
        _OrderedAuthGates.__init__(self, transaction, original, phase)
        if (type(duty) is not _GuestInventoryBeginDuty or
                getattr(duty, '_initialization_complete', False) is not True or
                original.guest_response is not duty or
                duty.original is not original or
                any(type(value) is not float or not math.isfinite(value)
                    for value in (duty.end, original.end, original.write_end))):
            raise _RequestUnavailable()
        self._end = min(duty.end, original.end, original.write_end)


def _inventory_source_data_locked(owner, family, session, principal, reference,
                                   cohort, generation, now):
    """Read one purpose/session/family DATA row; authenticates nobody.

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
    if record._spent or record._retired:
        raise _RequestUnavailable()
    return record


def _consume_inventory_source_data(record, now):
    """Pure irreversible state operation, not an original admission grant."""
    if type(record) is not _GuestReferenceRecord:
        raise _RequestUnavailable()
    try:
        record._consume_once(now)
    except _ReferenceUnavailable:
        # Exact helper spends before stale/backward-clock refusal. No revival.
        raise _RequestUnavailable() from None


def begin_inventory(store, handler):
    """Retain first original context, select same F/R, consume source once.

    Unwired prefix only. No successful response/native operation is available.
    No new ledger ticket/child/resource exists, so no ticket/native cleanup is
    invented here. The spent source row remains in original charged storage;
    original family/session retirement owns its eventual logical disposition.
    """
    owner = _owned_store(store)
    original = store._broker._owned(handler)
    if (not auth._cluster_pilot_direct_tls(handler) or
            not auth.same_origin_or_absent(handler, require_present=True, is_https=True) or
            type(original.operation) is not str or
            original.operation != 'guest-owner-inventory' or
            original.guest_response is not None):
        raise _RequestUnavailable()
    data = store._broker._body_json(handler)
    captured, token, source, session, values = store._auth._capture_session(
        handler, 'guest-owner-inventory')
    if captured is not original:
        raise _RequestUnavailable()
    # Allocation has no native/shared duty. Recheck before publishing the
    # known returned pure holder so a foreign/reentered root is never replaced.
    if original.guest_response is not None:
        raise _RequestUnavailable()
    duty = object.__new__(_GuestInventoryBeginDuty)
    if original.guest_response is not None:
        raise _RequestUnavailable()
    original.guest_response = duty
    # Root precedes initializer entry AND its argument indexing. A failed or
    # lost initializer return leaves the SAME partial duty on the request.
    _GuestInventoryBeginDuty.__init__(duty, original, token, session, values,
        data['owner_ref'], data['source_ref'])
    if original.guest_response is not duty:
        raise _RequestUnavailable()
    with _InventoryBeginGates(store._auth, original, duty):
        cohort, generation, now = store._guard_locked(original, token, session, values)
        store._csrf_nonce_locked(handler, source, values, duty.family_ref)
        if original.guest_response is not duty or not now < duty.end:
            raise _RequestUnavailable()
        # Same already-retained complete duty precedes F/R lookup or mutation.
        try:
            family = _source_family_data_locked(owner, session, values[0],
                duty.family_ref, cohort, generation, now)
        except _ExpiredSourceFamily as expired:
            duty.family = expired.family
            store._retire_known_family_locked(expired.family)
            raise _RequestUnavailable() from None
        except _CorruptSourceFamily as error:
            raise store._quarantine(error)
        duty.family, duty.cohort, duty.generation = family, cohort, generation
        try:
            record = _inventory_source_data_locked(owner, family, session,
                values[0], duty.source_ref, cohort, generation, now)
        except _CorruptInventorySource as error:
            raise store._quarantine(error)
        duty.record, duty.source = record, record._source  # Before consume.
        duty.created, duty.resource_end = now, now + 10.0
        duty.end = min(duty.end, duty.resource_end, family._expires, record._expires)
        original.write_end = min(original.write_end, duty.end)
        try:
            duty.phase = 'consume-pending'
            _consume_inventory_source_data(record, now)
            duty.phase = 'spent'
        except _RequestUnavailable:
            duty.phase = 'consumed-refused'
            raise
        except BaseException as error:
            # Lost/unknown consumption return is never unspent or retried.
            raise store._quarantine(error)
        if not now < duty.end:
            raise _RequestUnavailable()
    return duty


# No store delegation, dispatcher branch, original native factory or response.
