"""Private whole-inventory record preparation DATA, no original issuance.

The future original owner must retain this holder, reserve the WHOLE child
ticket under its same writer before entropy, then acquire one fixed original
entropy batch outside gates. Supplied raw bytes/candidates/tickets here are
only DATA; they cannot prove that original source, reservation, entropy or
recipient. This module never reserves, commits, indexes, publishes or refunds.
No new original guarded caller, native authority or response is implemented.
"""
import math

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _CapacityTicket
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.guest_profile_formats.guest_inventory import decode_guest_inventory
from freq.services.pilot_guest_inventory_begin import _GuestInventoryBeginDuty
from freq.services.pilot_guest_retirement import _first


class _DecodedGuestRowsData:
    """Whole accepted raw grammar, then immutable ordered display/target DATA.

    Construction does not select a provider or grant native parser allowance.
    All unknown fields were charged by the existing complete raw decoder before
    projection. Templates are not silently filtered; no partial list is kept.
    """
    __slots__ = ('rows', 'targets')

    def __init__(self, raw):
        selected = decode_guest_inventory(raw)
        rows = tuple((row['node'], row['guest_kind'], row['vmid'], row['name'])
                     for row in selected)
        targets = tuple((row[0], row[1], row[2]) for row in rows)
        object.__setattr__(self, 'rows', rows)
        object.__setattr__(self, 'targets', targets)

    def __setattr__(self, name, value):
        raise TypeError('Decoded inventory DATA is immutable')

    def __delattr__(self, name):
        raise TypeError('Decoded inventory DATA is immutable')


class _InventoryGuestBatchData:
    """Pure pending holder; not an issuer, reservation or acquisition grant.

    The actual original owner must retain this SAME object before calling any
    preparation step. A lost constructor/append return never licenses retry,
    a new ticket, guessed refund or physical closure. Native parent is owed.
    """
    __slots__ = ('begin', 'decoded', 'ticket', 'created', 'expires',
                 'candidates', 'records', 'phase')

    def __init__(self, begin, decoded, ticket, created):
        if (type(begin) is not _GuestInventoryBeginDuty or
                type(decoded) is not _DecodedGuestRowsData or
                type(ticket) is not _CapacityTicket or
                type(begin.family) is not _GuestFamilyRecord or
                type(begin.record) is not _GuestReferenceRecord or
                type(begin.values) is not tuple or len(begin.values) != 5 or
                type(created) is not float or not math.isfinite(created) or
                any(type(x) is not float or not math.isfinite(x)
                    for x in (begin.end, begin.family._expires, begin.record._expires,
                              begin.record._last_clock)) or
                not begin.record._last_clock <= created < begin.end):
            raise _RequestUnavailable()
        self.begin, self.decoded, self.ticket = begin, decoded, ticket
        self.created = created
        self.expires = min(created + 30.0, begin.family._expires, begin.record._expires)
        self.candidates = None
        self.records = []  # Retain EACH known holder before publication exists.
        self.phase = 'new'


def _whole_inventory_batch_data(batch):
    """Validate complete original-shaped DATA before constructing any child.

    Caller still owes actual same original owner/gates/native/source/clock and
    ticket ledger membership. Ticket identity/count here is never that proof.
    """
    if (type(batch) is not _InventoryGuestBatchData or
            type(batch.begin) is not _GuestInventoryBeginDuty or
            type(batch.decoded) is not _DecodedGuestRowsData or
            type(batch.ticket) is not _CapacityTicket):
        raise _RequestUnavailable()
    begin, decoded, ticket = batch.begin, batch.decoded, batch.ticket
    family, source = begin.family, begin.record
    if (type(family) is not _GuestFamilyRecord or type(source) is not _GuestReferenceRecord or
            type(begin.session) is not dict or type(begin.values) is not tuple or
            len(begin.values) != 5 or source._family is not family or
            source._session is not begin.session or source._principal != begin.values[0] or
            source._purpose != 'source' or source._key != begin.source_ref or
            source._source is not begin.source or source._cohort is not begin.cohort or
            source._generation is not begin.generation or source._target is not None or
            source._spent is not True or source._retired is not False or
            family._session is not begin.session or family._principal != begin.values[0] or
            family._cohort is not begin.cohort or family._generation is not begin.generation or
            family._state != 'live' or family._sources_spent is not True or
            ticket is source._ticket or ticket is family._ticket or
            ticket._session is not begin.session or ticket._principal != begin.values[0] or
            ticket._state != 'reserved' or type(ticket._remaining) is not int or
            type(decoded.rows) is not tuple or len(decoded.rows) > 256 or
            type(decoded.targets) is not tuple or len(decoded.targets) != len(decoded.rows) or
            ticket._remaining != len(decoded.rows) or
            type(batch.records) is not list or len(batch.records) > len(decoded.rows) or
            any(type(x) is not float or not math.isfinite(x)
                for x in (batch.created, batch.expires, begin.end, family._expires,
                          source._expires, source._last_clock)) or
            not source._last_clock <= batch.created < min(begin.end, batch.expires) or
            batch.expires != min(batch.created + 30.0, family._expires, source._expires)):
        raise _RequestUnavailable()
    # Immutable decoder output has no caller mutation API. Exact builtin row
    # and target correspondence still refuses manually corrupted private DATA.
    seen = set()
    for row, target in zip(decoded.rows, decoded.targets):
        if (type(row) is not tuple or len(row) != 4 or
                type(target) is not tuple or len(target) != 3 or
                row[:3] != target or target in seen):
            raise _RequestUnavailable()
        seen.add(target)


def prepare_inventory_guest_records_data(batch, candidates):
    """Prepare every private child or retain the partial failed holder list.

    Candidates are supplied DATA only. Actual original entropy acquisition and
    collisions against the original session/purpose ledger must be checked by
    a future guarded publisher. No prepared child can redeem or publish here.
    """
    _whole_inventory_batch_data(batch)
    if (batch.phase != 'new' or batch.records or type(candidates) is not tuple or
            len(candidates) != len(batch.decoded.rows)):
        raise _RequestUnavailable()
    seen = set()
    for key in candidates:
        if (type(key) is not str or len(key) != 64 or
                any(c not in '0123456789abcdef' for c in key) or key in seen):
            raise _RequestUnavailable()
        seen.add(key)
    # Permanent once state BEFORE first constructor/append, including zero N.
    # No catch/reset: unknown return remains charged by the enclosing ticket.
    batch.candidates = candidates
    batch.phase = 'prepare-attempted'
    begin = batch.begin
    for key, target in zip(candidates, batch.decoded.targets):
        record = _GuestReferenceRecord(key, 'guest', begin.session, begin.values[0],
            begin.source, begin.generation, begin.cohort, target,
            batch.created, batch.expires, batch.ticket, begin.family)
        batch.records.append(record)
    batch.phase = 'prepared'


def prepared_inventory_guest_records_data(batch):
    """Complete prepared consistency only; no original ledger or grant."""
    _whole_inventory_batch_data(batch)
    if (batch.phase != 'prepared' or type(batch.candidates) is not tuple or
            len(batch.candidates) != len(batch.decoded.rows) or
            len(batch.records) != len(batch.decoded.rows)):
        raise _RequestUnavailable()
    for key, target, record in zip(batch.candidates, batch.decoded.targets, batch.records):
        if (type(record) is not _GuestReferenceRecord or record._key != key or
                record._purpose != 'guest' or record._target is not target or
                record._source is not batch.begin.source or
                record._family is not batch.begin.family or
                record._session is not batch.begin.session or
                record._principal != batch.begin.values[0] or
                record._cohort is not batch.begin.cohort or
                record._generation is not batch.begin.generation or
                record._ticket is not batch.ticket or
                record._created != batch.created or record._last_clock != batch.created or
                record._expires != batch.expires or
                record._spent is not False or record._retired is not False):
            raise _RequestUnavailable()


def retire_inventory_guest_records_data(batch, first):
    """Known private holders only, independent of positive capacity/live flags.

    Must run under SAME original retirement custody/gates once integrated.
    Every later known record is attempted after earlier failure/control. Never
    indexes/deletes rows, refunds tickets or declares the partial list whole.
    """
    if (type(batch) is not _InventoryGuestBatchData or
            type(batch.begin) is not _GuestInventoryBeginDuty or
            type(batch.begin.values) is not tuple or len(batch.begin.values) != 5 or
            type(batch.decoded) is not _DecodedGuestRowsData or
            type(batch.records) is not list or len(batch.records) > 256 or
            type(batch.candidates) is not tuple or len(batch.candidates) > 256 or
            len(batch.records) > len(batch.candidates) or
            type(batch.decoded.targets) is not tuple or
            len(batch.records) > len(batch.decoded.targets)):
        return _first(first, _RequestUnavailable())
    for index, record in enumerate(batch.records):
        try:
            if (type(record) is not _GuestReferenceRecord or
                    record._purpose != 'guest' or record._family is not batch.begin.family or
                    record._source is not batch.begin.source or
                    record._session is not batch.begin.session or
                    record._principal != batch.begin.values[0] or
                    record._key != batch.candidates[index] or
                    record._cohort is not batch.begin.cohort or
                    record._generation is not batch.begin.generation or
                    record._ticket is not batch.ticket or
                    record._target is not batch.decoded.targets[index]):
                raise _RequestUnavailable()
            record._retire()
        except BaseException as error:
            first = _first(first, error)
    return first


# No original native result receipt, ticket reservation/commit/refund, entropy,
# source consumption, ledger collision/publication, frame, store or dispatch.
