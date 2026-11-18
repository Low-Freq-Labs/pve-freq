"""WIP original sources issuance/frame continuation, unqualified and unwired.

The original native factory remains absent/current False. No imported object,
supplied holder, entropy bytes or private return grants original authority.
Candidate calls, native work and every fixture remain UNRUN.
"""
import datetime
import math
import os
import threading
import time

from freq.api import auth
from freq.services.cluster_pilot_http import (
    OriginalPilotResponse, _RequestUnavailable, _OriginalRequest,
    _OriginalHTTPRequests, _OriginalPilotHandler, _OriginalPilotServer,
)
from freq.services.guest_reference_capacity import _CapacityTicket, _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_profile_formats.guest_owner_wire import project_guest_owner_wire
from freq.services.pilot_auth_commit import _OrderedAuthGates
from freq.services.pilot_guest_reference_store import _OpeningCleanupGates, _OpeningResponseGates
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_retirement import _first
from freq.services.pilot_guest_sources_begin import (
    _GuestSourcesBeginDuty, _source_family_data_locked,
    _ExpiredSourceFamily, _CorruptSourceFamily,
    begin_sources, abandon_sources_begin,
)


class _SourcesIssueDuty:
    """Pure retained holder, deliberately without an acquiring method."""
    __slots__ = ('store', 'original', 'begin', 'end', 'thread', 'last_clock',
                 'native_phase', 'candidates', 'records', 'frame', 'phase', 'custody')

    def __init__(self, store, original, begin):
        self.store, self.original, self.begin = store, original, begin
        self.end = begin.end
        self.thread = threading.current_thread()
        self.last_clock = begin.created
        self.native_phase, self.candidates = 'armed', None
        self.records, self.frame, self.phase = [], None, 'new'
        self.custody = None


class _SourcesRetirementCustody:
    """Immutable original identity snapshot, not positive admission authority.

    Constructed and retained ONLY inside the same original positive transaction
    before any source entropy/record construction. The retirement entry checks
    exact canonical types, original request registry, handler/thread and every
    captured table/lock identity again. Supplied DATA is not original custody.
    """
    __slots__ = ('_items',)

    def __init__(self, store, original, handler, duty):
        owner, auth_owner, broker = store._installation, store._auth, store._broker
        references, server = store._references, owner._server
        locks = (owner._gate, auth._auth_lock,
                 references._lock, broker._gate)
        object.__setattr__(self, '_items', (store, owner, auth_owner, broker,
            references, server, broker._requests, original, handler,
            original.socket, threading.current_thread(), owner._original_component_tables,
            owner._guest_capacity, locks, duty, duty.begin, duty.records))

    def __setattr__(self, name, value):
        raise TypeError('Original source retirement custody is immutable')

    def __delattr__(self, name):
        raise TypeError('Original source retirement custody is immutable')


def _retirement_original(store, handler):
    """Retirement-only registry lookup; never checks or restores broker live."""
    _owned_store(store)
    broker = store._broker
    if (type(broker) is not _OriginalHTTPRequests or
            type(handler) is not _OriginalPilotHandler or
            type(broker._server) is not _OriginalPilotServer or
            handler.server is not broker._server or
            type(broker._requests) is not dict or len(broker._requests) > 64):
        raise _RequestUnavailable()
    original = broker._requests.get(handler.request)
    if (type(original) is not _OriginalRequest or original.handler is not handler or
            original.socket is not handler.request or
            original.thread is not threading.current_thread() or
            type(original.operation) is not str or original.operation != 'guest-owner-sources'):
        raise _RequestUnavailable()
    return original


def _retirement_custody_matches(store, original, handler, duty):
    """Exact identity only, deliberately independent of positive live/flags.

    Does not authenticate a session, make a native-current check succeed,
    reserve/refund capacity, repair tables, or permit any frame/read/send.
    Missing/replaced graph refuses; own quarantine flags alone do not.
    """
    owner = _owned_store(store)
    if (type(duty) is not _SourcesIssueDuty or duty.store is not store or
            duty.original is not original or type(duty.custody) is not _SourcesRetirementCustody or
            original.guest_response is not duty or type(duty.begin) is not _GuestSourcesBeginDuty or
            duty.begin.original is not original):
        raise _RequestUnavailable()
    items = duty.custody._items
    if type(items) is not tuple or len(items) != 17:
        raise _RequestUnavailable()
    (saved_store, saved_owner, auth_owner, broker, references, server, requests,
     request, saved_handler, socket, thread, tables, capacity, locks, saved_duty,
     saved_begin, saved_records) = items
    if (saved_store is not store or saved_owner is not owner or
            auth_owner is not store._auth or broker is not store._broker or
            references is not store._references or server is not owner._server or
            request is not original or saved_handler is not handler or saved_duty is not duty or
            saved_begin is not duty.begin or saved_records is not duty.records or
            type(saved_records) is not list or len(saved_records) > 32 or
            type(original) is not _OriginalRequest or
            type(broker) is not _OriginalHTTPRequests or type(server) is not _OriginalPilotServer or
            type(handler) is not _OriginalPilotHandler or handler.server is not server or
            original.handler is not handler or original.socket is not socket or
            handler.request is not socket or original.thread is not thread or
            thread is not duty.thread or thread is not threading.current_thread() or
            type(requests) is not dict or requests is not broker._requests or
            len(requests) > 64 or requests.get(socket) is not original or
            type(tables) is not tuple or len(tables) != 9 or
            tables is not owner._original_component_tables or
            any(type(table) is not dict for table in tables) or
            any(tables[i] is tables[j] for i in range(9) for j in range(i)) or
            type(capacity) is not _GuestCapacity or
            capacity is not owner._guest_capacity or capacity is not owner._original_guest_capacity or
            type(locks) is not tuple or len(locks) != 4):
        raise _RequestUnavailable()
    current_tables = (owner._auth_attempts, owner._asset_attempts, owner._issued_sessions,
        owner._read_attempts, owner._native_read_attempts, owner._guest_families_by_nonce,
        owner._guest_families_by_ref, owner._guest_reference_records, capacity._tickets)
    if (any(a is not b for a, b in zip(tables, current_tables)) or
            any(len(table) > 4096 for table in tables[5:]) or
            locks[0] is not owner._gate or
            locks[1] is not auth._auth_lock or
            locks[2] is not references._lock or locks[3] is not broker._gate):
        raise _RequestUnavailable()
    return duty.custody


class _SourcesRetirementGates(_OpeningCleanupGates):
    """Use only SAME captured four nonblocking locks, no positive currentness."""
    def __init__(self, custody):
        if type(custody) is not _SourcesRetirementCustody:
            raise _RequestUnavailable()
        items = custody._items
        self._transaction, self._original = items[2], items[7]
        self._phase, self._locks = 'ready', items[13]
        self._states = ['unused'] * 4


def _retire_retained_records_data(duty, first):
    """Pure known-holder loop, only after enclosing original custody/gates.

    A failure/control in one known holder never skips a later known holder.
    DATA transition gives no native close receipt, counter refund or grant.
    """
    if (type(duty) is not _SourcesIssueDuty or type(duty.records) is not list or
            len(duty.records) > 32 or type(duty.begin) is not _GuestSourcesBeginDuty):
        return _first(first, _RequestUnavailable())
    for record in duty.records:
        try:
            if (type(record) is not _GuestReferenceRecord or
                    record._family is not duty.begin.family or record._ticket is not duty.begin.ticket):
                raise _RequestUnavailable()
            record._retire()
        except BaseException as error:
            first = _first(first, error)
    return first


class _SourcesIssueGates(_OpeningResponseGates):
    def __init__(self, transaction, original, duty, phase='ready'):
        _OrderedAuthGates.__init__(self, transaction, original, phase)
        if (type(duty) is not _SourcesIssueDuty or duty.original is not original or
                type(duty.end) is not float or not math.isfinite(duty.end) or
                type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or
                not math.isfinite(original.write_end)):
            raise _RequestUnavailable()
        self._end = min(duty.end, original.end, original.write_end)


def _earlier_clock(duty):
    now = time.monotonic()
    if (type(now) is not float or not math.isfinite(now) or
            type(duty.last_clock) is not float or not math.isfinite(duty.last_clock) or
            now < duty.last_clock or not now < duty.end):
        raise _RequestUnavailable()
    duty.last_clock = now
    return now


def _prepared_records_data(duty):
    """Only private DATA consistency, not publication or an original issuer."""
    begin = duty.begin
    if (type(begin) is not _GuestSourcesBeginDuty or type(begin.sources) is not tuple or
            len(begin.sources) > 32 or type(duty.candidates) is not tuple or
            len(duty.candidates) != len(begin.sources) or
            type(duty.records) is not list or len(duty.records) != len(begin.sources)):
        raise _RequestUnavailable()
    seen = set()
    for row, key, record in zip(begin.sources, duty.candidates, duty.records):
        if (type(key) is not str or len(key) != 64 or
                any(c not in '0123456789abcdef' for c in key) or key in seen or
                type(record) is not _GuestReferenceRecord or
                record._key != key or record._purpose != 'source' or
                record._source is not row or record._target is not None or
                record._family is not begin.family or record._session is not begin.session or
                record._principal != begin.values[0] or record._cohort is not begin.cohort or
                record._generation is not begin.generation or record._ticket is not begin.ticket or
                record._created != begin.created or record._last_clock != begin.created or
                record._expires != min(begin.created + 30.0, begin.family._expires) or
                record._spent is not False or record._retired is not False):
            raise _RequestUnavailable()
        seen.add(key)


def _current_locked(store, original, duty, phase='ready', retained=True):
    owner = _owned_store(store)
    if (type(duty) is not _SourcesIssueDuty or duty.store is not store or
            duty.original is not original or duty.thread is not threading.current_thread() or
            type(duty.begin) is not _GuestSourcesBeginDuty or
            duty.begin.original is not original or
            original.guest_response is not (duty if retained else duty.begin) or
            type(original.operation) is not str or original.operation != 'guest-owner-sources' or
            original.body_taken is not True):
        raise _RequestUnavailable()
    begin = duty.begin
    cohort, generation, now = store._guard_locked(original,
        begin.token, begin.session, begin.values, phase)
    if retained:
        _retirement_custody_matches(store, original, original.handler, duty)
    if (cohort is not begin.cohort or generation is not begin.generation or
            begin.sources is not cohort.nodes or type(begin.family) is not _GuestFamilyRecord or
            type(begin.created) is not float or not math.isfinite(begin.created) or
            type(begin.resource_end) is not float or
            begin.resource_end != begin.created + 10.0 or
            type(begin.initial_write_end) is not float or
            not math.isfinite(begin.initial_write_end) or
            type(duty.end) is not float or not math.isfinite(duty.end) or
            begin.end != duty.end or
            duty.end != min(original.end, begin.initial_write_end,
                            begin.family._expires, begin.resource_end) or
            type(original.write_end) is not float or not math.isfinite(original.write_end) or
            original.write_end > duty.end or type(duty.last_clock) is not float or
            not math.isfinite(duty.last_clock) or
            now < duty.last_clock or not begin.created <= now < min(duty.end, original.write_end)):
        raise _RequestUnavailable()
    try:
        selected = _source_family_data_locked(owner, begin.session, begin.values[0],
            begin.family_ref, cohort, generation, now)
    except _ExpiredSourceFamily as expired:
        store._retire_known_family_locked(expired.family)
        raise _RequestUnavailable() from None
    except _CorruptSourceFamily as error:
        raise store._quarantine(error)
    if selected is not begin.family or selected._sources_spent is not True:
        raise _RequestUnavailable()
    duty.last_clock = now
    capacity, ticket = owner._guest_capacity, begin.ticket
    capacity._check()
    if (type(ticket) is not _CapacityTicket or ticket._session is not begin.session or
            ticket._principal != begin.values[0]):
        raise _RequestUnavailable()
    issued = duty.phase in ('issued', 'prepared', 'admitted', 'write-attempted', 'sent')
    if issued:
        if duty.native_phase != ('returned' if begin.sources else 'empty'):
            raise _RequestUnavailable()
        _prepared_records_data(duty)
        if not duty.records:
            if (ticket._state != 'retired' or ticket._remaining != 0 or
                    id(ticket) in capacity._tickets):
                raise _RequestUnavailable()
        else:
            if (ticket._state != 'committed' or ticket._remaining != len(duty.records) or
                    capacity._tickets.get(id(ticket)) is not ticket):
                raise _RequestUnavailable()
            for record in duty.records:
                if owner._guest_reference_records.get(
                        (id(begin.session), 'source', record._key)) is not record:
                    raise _RequestUnavailable()
    elif (ticket._state != 'reserved' or ticket._remaining != len(begin.sources) or
            capacity._tickets.get(id(ticket)) is not ticket or begin.phase != 'reserved'):
        raise _RequestUnavailable()
    return owner


def _existing_source_keys_data(owner, duty):
    rows = owner._guest_reference_records
    if type(rows) is not dict or len(rows) > 4096:
        raise _RequestUnavailable()
    for key, record in rows.items():
        if (type(record) is not _GuestReferenceRecord or
                type(key) is not tuple or len(key) != 3 or
                type(key[0]) is not int or type(key[1]) is not str or
                type(key[2]) is not str or
                key != (id(record._session), record._purpose, record._key) or
                type(record._ticket) is not _CapacityTicket or
                record._ticket._state != 'committed' or
                owner._guest_capacity._tickets.get(id(record._ticket)) is not record._ticket):
            raise _RequestUnavailable()
    return any((id(duty.begin.session), 'source', candidate) in rows
               for candidate in duty.candidates)


def _acquire_and_prepare(store, handler, duty):
    """Only original guarded caller can reach the one fixed entropy call."""
    original, begin = duty.original, duty.begin
    with _SourcesIssueGates(store._auth, original, duty):
        _current_locked(store, original, duty)
        if duty.phase != 'new' or duty.native_phase != 'armed':
            raise _RequestUnavailable()
        duty.phase = 'working'
    _earlier_clock(duty)
    count = len(begin.sources)
    if count:
        # The SAME request retains this duty BEFORE the single bounded call.
        # No supplied bytes/entropy callback, collision retry or explicit retry.
        duty.native_phase = 'attempted'
        raw = os.getrandom(count * 32, os.GRND_NONBLOCK)
        if type(raw) is not bytes or len(raw) != count * 32:
            raise _RequestUnavailable()
        duty.candidates = tuple(raw[i*32:(i+1)*32].hex() for i in range(count))
        raw = None
        duty.native_phase = 'returned'
    else:
        duty.candidates = ()
        duty.native_phase = 'empty'
    _earlier_clock(duty)
    if len(set(duty.candidates)) != count:
        raise _RequestUnavailable()  # No partial publication or second entropy.
    for row, candidate in zip(begin.sources, duty.candidates):
        # These pure holders confer no right until same original final writer.
        # Concurrent family/session retirement can make construction refuse.
        record = _GuestReferenceRecord(candidate, 'source', begin.session,
            begin.values[0], row, begin.generation, begin.cohort, None,
            begin.created, min(begin.created + 30.0, begin.family._expires),
            begin.ticket, begin.family)
        duty.records.append(record)  # Strong retention before indexing.
    with _SourcesIssueGates(store._auth, original, duty):
        owner = _current_locked(store, original, duty)
        _prepared_records_data(duty)
        try:
            collision = _existing_source_keys_data(owner, duty)
        except BaseException as error:
            raise store._quarantine(error)
        if collision:
            raise _RequestUnavailable()
        duty.phase = 'publication-pending'
        try:
            owner._guest_capacity._commit(begin.ticket)
            for record in duty.records:
                key = (id(begin.session), 'source', record._key)
                owner._guest_reference_records[key] = record
            if not duty.records:
                owner._guest_capacity._retire_empty_committed(begin.ticket)
            duty.phase = 'issued'
            _current_locked(store, original, duty)
        except BaseException as error:
            raise store._quarantine(error)


def admit_sources_response(store, handler):
    """Proposed exact original sources finalizer, not yet a dispatch branch."""
    _owned_store(store)
    original = store._broker._owned(handler)
    first = None
    try:
        begin = begin_sources(store, handler)
        duty = _SourcesIssueDuty(store, original, begin)
        with _SourcesIssueGates(store._auth, original, duty):
            _current_locked(store, original, duty, retained=False)
            # Immutable cleanup-only graph before ANY entropy/child work. Own
            # later quarantine cannot invalidate this original retirement duty.
            duty.custody = _SourcesRetirementCustody(store, original, handler, duty)
            # Preserve the begin/reservation holder inside this outer holder.
            # Assignment loss still leaves both in the same original request.
            original.guest_response = duty
        _acquire_and_prepare(store, handler, duty)
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec='milliseconds').replace('+00:00', 'Z')
        payload = {'schema':2, 'kind':'guest-sources', 'owner_ref':begin.family_ref,
            'sources':[{'source_ref':record._key, 'label':row[0]}
                       for row, record in zip(begin.sources, duty.records)],
            'completed_at':stamp}
        body = project_guest_owner_wire(payload)
        frame = OriginalPilotResponse(200, body, 'application/json; charset=utf-8')
        duty.frame, duty.phase = frame, 'prepared'
        with _SourcesIssueGates(store._auth, original, duty):
            _current_locked(store, original, duty)
            if duty.frame is not frame or type(frame) is not OriginalPilotResponse:
                raise _RequestUnavailable()
            try:
                store._broker._admit_frame_locked(handler, original, frame)
                duty.phase = 'admitted'
            except BaseException as error:
                raise store._quarantine(error)
        return frame
    except BaseException as error:
        first = error
    try:
        retire_sources_handler_duty(store, handler)
    except BaseException as cleanup:
        first = _first(first, cleanup)
    raise first


def write_sources_response(store, handler, frame):
    _owned_store(store)
    original = store._broker._owned(handler)
    duty = original.guest_response
    with _SourcesIssueGates(store._auth, original, duty, 'admitted'):
        _current_locked(store, original, duty, 'admitted')
        if (duty.phase != 'admitted' or duty.frame is not frame or
                type(frame) is not OriginalPilotResponse):
            raise _RequestUnavailable()
        try:
            store._broker._reserve_write_locked(handler, original, frame)
            duty.phase = 'write-attempted'
        except BaseException as error:
            raise store._quarantine(error)
    # Native IO outside every admission gate, with SAME retained write end.
    # A local return never proves browser uptake or original physical closure.
    store._broker._send_reserved(handler, frame)
    duty.phase = 'sent'


def retire_sources_handler_duty(store, handler):
    """Logical retirement only; retain outside duties for original parent."""
    owner = _owned_store(store)
    original = _retirement_original(store, handler)
    duty = original.guest_response
    if duty is None:
        return
    if type(duty) is _GuestSourcesBeginDuty:
        return abandon_sources_begin(store, handler)
    if (type(duty) is not _SourcesIssueDuty or duty.store is not store or
            duty.original is not original or type(duty.begin) is not _GuestSourcesBeginDuty or
            duty.begin.original is not original):
        raise _RequestUnavailable()
    custody = _retirement_custody_matches(store, original, handler, duty)
    if duty.phase in ('sent', 'retired'):
        return
    first = None
    try:
        with _SourcesRetirementGates(custody):
            if _retirement_custody_matches(store, original, handler, duty) is not custody:
                raise _RequestUnavailable()
            begin, ticket = duty.begin, duty.begin.ticket
            if (type(ticket) is not _CapacityTicket or
                    ticket._session is not begin.session or
                    ticket._principal != begin.values[0] or
                    type(duty.records) is not list or len(duty.records) > 32):
                raise _RequestUnavailable()
            settled = store._already_retired_session_family_locked(begin.family)
            if settled:
                if ticket._state != 'retired' or id(ticket) in owner._guest_capacity._tickets:
                    raise _RequestUnavailable()
            # Revoke family and every known published child FIRST. This keeps
            # its charged C/F tombstone; malformed/partial rows quarantine.
            if not settled:
                try:
                    store._retire_known_family_locked(begin.family)
                except BaseException as error:
                    first = _first(first, error)
            # Retire all known retained pure holders even if one fails. A lost
            # holder return before indexing created no redemption table entry.
            first = _retire_retained_records_data(duty, first)
            try:
                if first is not None:
                    raise first
                if settled:
                    # Even settled original logout must not skip known retained
                    # pure holders. They were all independently retired above.
                    duty.phase = 'retired'
                    return
                rows = owner._guest_reference_records
                if type(rows) is not dict or len(rows) > 4096:
                    raise _RequestUnavailable()
                for record in rows.values():
                    if type(record) is not _GuestReferenceRecord or record._ticket is ticket:
                        raise _RequestUnavailable()
                if ticket._state == 'reserved':
                    if (owner._guest_capacity._tickets.get(id(ticket)) is not ticket or
                            ticket._remaining != len(begin.sources)):
                        raise _RequestUnavailable()
                    owner._guest_capacity._retire_unpublished(ticket)
                elif (ticket._state != 'retired' or ticket._remaining != 0 or
                      id(ticket) in owner._guest_capacity._tickets):
                    # Unknown partial publication leaves remaining committed
                    # charge for original session retirement, never an integer
                    # refund guessed from missing rows.
                    raise _RequestUnavailable()
                duty.phase = 'retired'
            except BaseException as error:
                first = _first(first, error)
    except BaseException as error:
        first = _first(first, error)
    if first is not None:
        raise store._quarantine(first)


# No caller/dispatch/delegation/activation or positive native installation here.
