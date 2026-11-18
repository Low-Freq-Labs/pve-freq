"""Private guest reference DATA states, unfinished original-owner join.

Possessing or constructing this holder grants no session/source/reference
redemption right. Original owner must reserve complete capacity BEFORE creating
records, retain them privately, and validate original session/source/cohort/gates
before calling these operations. No clock callback, map or authority is supplied.
No native or application reference is issued by this module.
"""
import math
import re
from freq.services.guest_reference_capacity import _CapacityTicket
from freq.services.guest_family_state import _GuestFamilyRecord


class _Unavailable(ValueError):
    pass


def _refuse():
    raise _Unavailable('Guest reference unavailable') from None


class _GuestReferenceRecord:
    __slots__ = ('_key', '_purpose', '_session', '_principal', '_source',
                 '_generation', '_cohort', '_target', '_created', '_expires',
                 '_last_clock', '_spent', '_retired', '_ticket', '_family')

    def __init__(self, key, purpose, session, principal, source, generation,
                 cohort, target, created, expires, ticket, family):
        if (type(key) is not str or re.fullmatch('[0-9a-f]{64}', key) is None or
                type(purpose) is not str or purpose not in ('source', 'guest') or
                type(ticket) is not _CapacityTicket or
                type(session) is not dict or source is None or generation is None or cohort is None or
                type(principal) is not str or not principal or
                ticket._session is not session or ticket._principal != principal or
                ticket._state != 'reserved' or ticket._remaining < 1 or
                type(family) is not _GuestFamilyRecord or
                family._session is not session or family._principal != principal or
                family._cohort is not cohort or family._generation is not generation or
                family._state != 'live' or family._ref is None or
                (purpose == 'source' and target is not None) or
                (purpose == 'guest' and target is None) or
                type(created) is not float or type(expires) is not float or
                not math.isfinite(created) or not math.isfinite(expires) or
                not family._created <= created < expires <= min(created + 30.0, family._expires)):
            _refuse()
        self._key, self._purpose = key, purpose
        self._ticket = ticket
        self._family = family
        # Strong original identities, not serialized tuples or copied sessions.
        self._session, self._principal, self._source = session, principal, source
        self._generation, self._cohort, self._target = generation, cohort, target
        self._created, self._expires = created, expires
        self._last_clock = created
        self._spent = self._retired = False

    def _consume_once(self, now):
        # Called only AFTER original owner/session/purpose gates and lookup.
        # Failure/expiry cannot refund this same record's original attempt.
        if self._spent or self._retired:
            _refuse()
        self._spent = True
        if (type(now) is not float or not math.isfinite(now) or
                now < self._last_clock or not now < self._expires):
            self._retired = True
            _refuse()
        self._last_clock = now

    def _retire(self):
        # Idempotent terminal DATA transition, never a resource-cleanup proof.
        self._retired = True
