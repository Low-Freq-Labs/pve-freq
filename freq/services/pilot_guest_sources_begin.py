"""Unwired original sources-attempt/reservation prefix; no reference issuer.

No entropy, child records, serialization, provider IO or response follows this
prefix. The native-current operation remains False. A returned private duty is
not a source list, native grant, admitted frame or browser capability. Future
continuation must retain its own exact outside duties before any acquisition.
"""
import math
import re

from freq.api import auth
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_ordering import _family_data
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _CapacityTicket, _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_auth_commit import _OrderedAuthGates
from freq.services.pilot_guest_reference_store import _OpeningCleanupGates, _OpeningResponseGates
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_retirement import _first


class _ExpiredSourceFamily(_RequestUnavailable):
    def __init__(self, family):
        self.family = family
        super().__init__()


class _CorruptSourceFamily(_RequestUnavailable):
    pass


class _GuestSourcesBeginDuty:
    """Pure storage retained on the SAME original request before mutation."""
    __slots__ = ('original', 'token', 'session', 'values', 'family_ref',
                 'family', 'cohort', 'generation', 'sources', 'created',
                 'initial_write_end', 'resource_end', 'end', 'ticket', 'phase')

    def __init__(self, original, token, session, values, family_ref):
        if (type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or
                not math.isfinite(original.write_end)):
            raise _RequestUnavailable()
        self.original, self.token, self.session = original, token, session
        self.values, self.family_ref = values, family_ref
        self.family = self.cohort = self.generation = self.sources = None
        self.created = self.resource_end = self.ticket = None
        self.initial_write_end = original.write_end
        self.end = min(original.end, self.initial_write_end)
        self.phase = 'new'


class _SourcesBeginGates(_OpeningResponseGates):
    """Original four gates, with the same monotonically shortening waits."""
    def __init__(self, transaction, original, duty, phase='ready'):
        _OrderedAuthGates.__init__(self, transaction, original, phase)
        if (type(duty) is not _GuestSourcesBeginDuty or duty.original is not original or
                type(duty.end) is not float or not math.isfinite(duty.end) or
                type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or
                not math.isfinite(original.write_end)):
            raise _RequestUnavailable()
        self._end = min(duty.end, original.end, original.write_end)


def _source_family_data_locked(owner, session, principal, reference,
                               cohort, generation, now):
    """DATA lookup only, never an original authority or right consumption.

    The original caller must first hold its writer and validate its original
    session/cohort/request. No expiry sweep or unrelated mutable lookup occurs.
    Old Cluster32hex tables are never consulted, altered or interchangeable.
    """
    if (type(session) is not dict or type(principal) is not str or not principal or
            type(reference) is not str or re.fullmatch('[0-9a-f]{64}', reference) is None or
            type(now) is not float or not math.isfinite(now) or
            type(owner._guest_families_by_ref) is not dict or
            len(owner._guest_families_by_ref) > 4096 or
            type(owner._guest_families_by_nonce) is not dict or
            len(owner._guest_families_by_nonce) > 4096):
        raise _RequestUnavailable()
    key = (id(session), reference)
    if key not in owner._guest_families_by_ref:
        raise _RequestUnavailable()
    family = owner._guest_families_by_ref[key]
    if type(family) is not _GuestFamilyRecord:
        raise _CorruptSourceFamily()
    try:
        _family_data(owner, (id(session), family._nonce), family)
    except Exception:
        raise _CorruptSourceFamily() from None
    if (owner._guest_families_by_nonce.get((id(session), family._nonce)) is not family or
            family._session is not session or family._principal != principal or
            family._ref != reference or
            type(family._sources_spent) is not bool or
            type(family._created) is not float or not math.isfinite(family._created) or
            type(family._expires) is not float or not math.isfinite(family._expires)):
        raise _CorruptSourceFamily()
    if (family._cohort is not cohort or family._generation is not generation or
            family._state != 'live' or not family._created <= now < family._expires):
        raise _ExpiredSourceFamily(family)
    return family


def _configured_sources_data(cohort, generation):
    """Return the SAME bounded configured rows, not caller target authority."""
    sources = cohort.nodes
    if type(sources) is not tuple or len(sources) > 32:
        raise _RequestUnavailable()
    for row in sources:
        if (type(row) is not tuple or len(row) != 2 or
                type(row[0]) is not str or not row[0] or len(row[0]) > 256 or
                len(row[0].encode('utf-8', 'strict')) > 256 or
                type(row[1]) is not TargetSnapshot or
                row[1].configuration_revision is not generation or
                type(row[1].selection_key) is not str or
                not 0 < len(row[1].selection_key) <= 512 or
                type(row[1].endpoint) is not str or
                not 0 < len(row[1].endpoint) <= 512):
            raise _RequestUnavailable()
    return sources


def _reserve_source_ticket_data_locked(owner, duty):
    """Known-full refusal before mutation; unknown reservation stays charged.

    Caller has already consumed this original family's one sources attempt
    under its original gates. This helper authenticates nobody and gives no
    permission to call entropy, create a child or publish the returned ticket.
    """
    if (type(duty) is not _GuestSourcesBeginDuty or duty.phase != 'spent' or
            duty.ticket is not None or type(duty.sources) is not tuple or
            len(duty.sources) > 32 or type(duty.session) is not dict or
            type(duty.values) is not tuple or len(duty.values) != 5 or
            type(duty.values[0]) is not str or not duty.values[0] or
            type(duty.family) is not _GuestFamilyRecord or
            duty.family._session is not duty.session or
            duty.family._principal != duty.values[0] or
            duty.family._sources_spent is not True or
            type(owner._guest_capacity) is not _GuestCapacity):
        raise _RequestUnavailable()
    count = len(duty.sources)
    capacity = owner._guest_capacity
    total, sessions = capacity._check()
    bucket = sessions.get(id(duty.session))
    used, tickets = (0, 0) if bucket is None else (bucket[2], bucket[3])
    if bucket is not None and (bucket[0] is not duty.session or bucket[1] != duty.values[0]):
        raise _RequestUnavailable()
    if (total + count > 4096 or used + count > 512 or
            len(capacity._tickets) >= 4096 or tickets >= 512):
        return False
    # Assignment loss leaves the ticket in capacity's original owned ledger.
    # Enclosing original caller quarantines any unknown reservation return.
    duty.phase = 'reserve-pending'
    duty.ticket = capacity._reserve(duty.session, duty.values[0], count)
    duty.phase = 'reserved'
    return True


def begin_sources(store, handler):
    """Retain exact request duty, consume family once, reserve the whole list.

    This function is intentionally not wired into dispatch. Native factory,
    original entropy/child finalizer and same immutable frame remain missing.
    An adapter must never treat this private return as a completed source read.
    """
    owner = _owned_store(store)  # Refuse a supplied store before handler hooks.
    original = store._broker._owned(handler)
    first = None
    try:
        if (not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler, require_present=True, is_https=True) or
                type(original.operation) is not str or
                original.operation != 'guest-owner-sources' or
                original.guest_response is not None):
            raise _RequestUnavailable()
        data = store._broker._body_json(handler)
        captured, token, source, session, values = store._auth._capture_session(
            handler, 'guest-owner-sources')
        if captured is not original:
            raise _RequestUnavailable()
        duty = _GuestSourcesBeginDuty(original, token, session, values, data['owner_ref'])
        with _SourcesBeginGates(store._auth, original, duty):
            cohort, generation, now = store._guard_locked(original, token, session, values)
            # Same existing cookie/CSRF policy and exact64hex shape; F is still
            # resolved only in its own purpose table after original guards.
            store._csrf_nonce_locked(handler, source, values, duty.family_ref)
            if original.guest_response is not None or not now < duty.end:
                raise _RequestUnavailable()
            original.guest_response = duty  # Before any F lookup/mutation.
            try:
                family = _source_family_data_locked(owner, session, values[0],
                    duty.family_ref, cohort, generation, now)
            except _ExpiredSourceFamily as expired:
                # Closing stale/expired known rights is irreversible even if a
                # later clock or cohort value is restored. No other F lookup.
                duty.family = expired.family
                store._retire_known_family_locked(expired.family)
                raise _RequestUnavailable() from None
            except _CorruptSourceFamily as error:
                raise store._quarantine(error)
            duty.family, duty.cohort, duty.generation = family, cohort, generation
            if family._sources_spent:
                raise _RequestUnavailable()
            duty.created, duty.resource_end = now, now + 10.0
            duty.end = min(duty.end, family._expires, duty.resource_end)
            original.write_end = min(original.write_end, duty.end)
            # The right is spent even if source projection/capacity later fails.
            # Mutation uncertainty never restores the right or another family.
            try:
                family._sources_spent = True
                duty.phase = 'spent'
                duty.sources = _configured_sources_data(cohort, generation)
                reserved = _reserve_source_ticket_data_locked(owner, duty)
            except BaseException as error:
                raise store._quarantine(error)
            if not reserved:
                raise _RequestUnavailable()  # Known-full, no new ticket.
        return duty
    except BaseException as error:
        first = error
    try:
        abandon_sources_begin(store, handler)
    except BaseException as cleanup:
        first = _first(first, cleanup)
    raise first


def abandon_sources_begin(store, handler):
    """Settle only this exact unpublished reservation; never unspend family.

    No acquisition exists in this prefix. Future outside acquisition must add
    independently retained original cleanup BEFORE using it. This is DATA
    bookkeeping only, never native closure, frame admission or a refund lease.
    """
    owner = _owned_store(store)
    original = store._broker._owned(handler)
    duty = original.guest_response
    if duty is None:
        return
    if (type(duty) is not _GuestSourcesBeginDuty or duty.original is not original or
            type(original.operation) is not str or original.operation != 'guest-owner-sources'):
        raise _RequestUnavailable()
    if duty.phase == 'retired':
        return
    try:
        with _OpeningCleanupGates(store._auth, original):
            if (original.guest_response is not duty or
                    owner._original_component_tables_current() is not True):
                raise _RequestUnavailable()
            ticket = duty.ticket
            if ticket is None:
                if duty.phase == 'reserve-pending' or owner._guest_capacity._uncertain:
                    raise _RequestUnavailable()  # Unknown return stays charged.
                duty.phase = 'retired'
                return
            if (type(ticket) is not _CapacityTicket or ticket._session is not duty.session or
                    ticket._principal != duty.values[0] or type(duty.sources) is not tuple or
                    ticket._remaining != len(duty.sources)):
                raise _RequestUnavailable()
            if (duty.family is not None and
                    store._already_retired_session_family_locked(duty.family) and
                    ticket._state == 'retired' and
                    id(ticket) not in owner._guest_capacity._tickets):
                # Original session retirement already settled this exact ticket.
                # Distinct successor session and its rights remain untouched.
                duty.phase = 'retired'
                return
            if (ticket._state != 'reserved' or
                    owner._guest_capacity._tickets.get(id(ticket)) is not ticket):
                raise _RequestUnavailable()
            records = owner._guest_reference_records
            if type(records) is not dict or len(records) > 4096:
                raise _RequestUnavailable()
            for record in records.values():
                if type(record) is not _GuestReferenceRecord or record._ticket is ticket:
                    raise _RequestUnavailable()  # No published rights may remain.
            owner._guest_capacity._retire_unpublished(ticket)
            duty.phase = 'retired'
    except BaseException as error:
        raise store._quarantine(error)
