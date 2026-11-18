"""Unwired immutable pre-registration profile cleanup snapshots, DATA only.

Future original begin caller must pre-retain custody before selection/consume,
then selected-record snapshot before the first irreversible consume. These
constructors and readers do not consume, retire, authenticate, acquire a guard,
mutate a table or grant native/response authority. Actual caller integration,
capture-pending/unknown/error duties and same-four-guard retirement are owed.
"""
import threading
from freq.api import auth
from freq.services.cluster_pilot_http import (
    _OriginalRequest, _OriginalHTTPRequests, _OriginalPilotHandler,
    _OriginalPilotServer, _RequestUnavailable,
)
from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityTicket
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_profile_begin import _GuestProfileBeginDuty


class _ProfileBeginCustody:
    """Twenty-one strong original identities; no supplied native owner/grant."""
    __slots__ = ('items',)

    def __init__(self, store, handler, begin):
        owner = _owned_store(store)
        original = store._broker._owned(handler)
        if (type(begin) is not _GuestProfileBeginDuty or begin.original is not original or
                original.guest_response is not begin or type(begin.values) is not tuple or
                len(begin.values) != 5 or type(begin.session) is not dict or
                type(begin.family_ref) is not str or type(begin.guest_ref) is not str):
            raise _RequestUnavailable()
        broker, refs = store._broker, store._references
        locks = (owner._gate, auth._auth_lock, refs._lock, broker._gate)
        object.__setattr__(self, 'items', (
            store, owner, store._auth, broker, refs, owner._server,
            broker._requests, original, handler, original.socket, original.thread,
            owner._original_component_tables, owner._guest_capacity, locks,
            begin, begin.token, begin.session, begin.values,
            begin.family_ref, begin.guest_ref, begin.initial_write_end))
        _begin_custody_matches_data(self, store, handler)

    def __setattr__(self, name, value):
        raise TypeError('Profile begin cleanup custody is immutable')

    def __delattr__(self, name):
        raise TypeError('Profile begin cleanup custody is immutable')


def _begin_custody_matches_data(custody, store, handler):
    """Identity-only graph DATA; no positive auth/time/count/state predicate.

    The captured begin remains owned across later guest_response handoff. This
    read must not use current session validity, deadline, selected row presence,
    native-current or unrelated global table counts as cleanup admission.
    Actual original caller still must acquire/hold captured four guards.
    """
    owner = _owned_store(store)
    if type(custody) is not _ProfileBeginCustody or type(custody.items) is not tuple or len(custody.items) != 21:
        raise _RequestUnavailable()
    (saved_store, saved_owner, transaction, broker, refs, server, requests,
     original, saved_handler, socket, thread, components, capacity, locks,
     begin, token, session, values, family_ref, guest_ref, initial_end) = custody.items
    if (saved_store is not store or saved_owner is not owner or
            transaction is not store._auth or broker is not store._broker or refs is not store._references or
            server is not owner._server or type(server) is not _OriginalPilotServer or
            type(broker) is not _OriginalHTTPRequests or broker._server is not server or
            server._pilot_requests is not broker or type(requests) is not dict or
            requests is not broker._requests or type(original) is not _OriginalRequest or
            requests.get(socket) is not original or type(handler) is not _OriginalPilotHandler or
            saved_handler is not handler or handler.server is not server or handler.request is not socket or
            original.handler is not handler or original.socket is not socket or
            original.thread is not thread or thread is not threading.current_thread() or
            type(original.operation) is not str or original.operation != 'guest-owner-profile' or
            original.body_taken is not True or type(begin) is not _GuestProfileBeginDuty or
            begin.original is not original or type(components) is not tuple or len(components) != 9 or
            components is not owner._original_component_tables or
            any(type(table) is not dict for table in components) or
            any(table is prior for index, table in enumerate(components) for prior in components[:index]) or
            type(capacity) is not _GuestCapacity or capacity is not owner._guest_capacity or
            capacity is not owner._original_guest_capacity or components[8] is not capacity._tickets or
            type(locks) is not tuple or len(locks) != 4 or locks[0] is not owner._gate or
            locks[1] is not auth._auth_lock or locks[2] is not refs._lock or locks[3] is not broker._gate):
        raise _RequestUnavailable()
    current = (owner._auth_attempts, owner._asset_attempts, owner._issued_sessions,
        owner._read_attempts, owner._native_read_attempts, owner._guest_families_by_nonce,
        owner._guest_families_by_ref, owner._guest_reference_records, capacity._tickets)
    if any(saved is not now for saved, now in zip(components, current)):
        raise _RequestUnavailable()
    return begin


class _ProfileBeginSelection:
    """Sixteen immutable selected-record identities, not a reference issuer."""
    __slots__ = ('items',)

    def __init__(self, custody, store, handler):
        begin = _begin_custody_matches_data(custody, store, handler)
        # Selection capture is positive DATA association: retain the initial
        # immutable context, even though later cleanup ignores mutable aliases.
        if (begin.token is not custody.items[15] or begin.session is not custody.items[16] or
                begin.values is not custody.items[17] or begin.family_ref is not custody.items[18] or
                begin.guest_ref is not custody.items[19]):
            raise _RequestUnavailable()
        record, family = begin.record, begin.family
        if (type(record) is not _GuestReferenceRecord or type(family) is not _GuestFamilyRecord or
                record._family is not family or record._session is not begin.session or
                type(begin.values) is not tuple or len(begin.values) != 5 or
                record._principal != begin.values[0] or record._purpose != 'guest' or
                record._key != begin.guest_ref or record._source is not begin.source or
                record._target is not begin.target or record._cohort is not begin.cohort or
                record._generation is not begin.generation or record._spent is not False or
                record._retired is not False or type(record._ticket) is not _CapacityTicket or
                record._ticket._session is not begin.session or
                record._ticket._principal != begin.values[0] or record._ticket._state != 'committed'):
            raise _RequestUnavailable()
        capacity = custody.items[12]
        if (capacity._tickets.get(id(record._ticket)) is not record._ticket or
                custody.items[11][7].get((id(begin.session), 'guest', begin.guest_ref)) is not record):
            raise _RequestUnavailable()
        object.__setattr__(self, 'items', (custody, record, family, record._source,
            record._target, record._cohort, record._generation, record._session,
            begin.values, begin.family_ref, begin.guest_ref, capacity, record._ticket,
            record._key, record._purpose, record._principal))

    def __setattr__(self, name, value):
        raise TypeError('Profile begin selected cleanup custody is immutable')

    def __delattr__(self, name):
        raise TypeError('Profile begin selected cleanup custody is immutable')


def _begin_selected_record_cleanup_data(custody, selection, store, handler):
    """Read saved selected record for FUTURE guarded cleanup; no operation.

    A spent/retired/expired/removed row and changed positive begin fields do not
    erase its original captured cleanup relationship. No replacement row or
    current begin.record alias is adopted. Returns private DATA only; the
    actual captured-guard caller must independently retain and perform retirement.
    """
    _begin_custody_matches_data(custody, store, handler)
    if type(selection) is not _ProfileBeginSelection or type(selection.items) is not tuple or len(selection.items) != 16:
        raise _RequestUnavailable()
    (saved_custody, record, family, source, target, cohort, generation, session,
     values, family_ref, guest_ref, capacity, ticket, key, purpose, principal) = selection.items
    if (saved_custody is not custody or type(record) is not _GuestReferenceRecord or
            type(family) is not _GuestFamilyRecord or record._family is not family or
            record._source is not source or record._target is not target or
            record._cohort is not cohort or record._generation is not generation or
            record._session is not session or record._ticket is not ticket or
            record._key is not key or record._purpose is not purpose or record._principal is not principal or
            capacity is not custody.items[12] or type(ticket) is not _CapacityTicket or
            ticket._session is not session or ticket._principal != principal):
        raise _RequestUnavailable()
    return record


# No begin/consume/store/dispatcher integration, guard acquisition, retirement,
# table deletion/refund/reuse, frame, ACK, native operation or activation.
