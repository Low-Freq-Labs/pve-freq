"""Private capacity DATA, unfinished original guest owner integration.

Every method requires the enclosing original owner to hold its original gates.
This module acquires no lock, authenticates nobody and issues no reference.
Physical allocation/native cleanup duties are independent of these counters.
"""


class _CapacityUnavailable(ValueError):
    pass


def _refuse():
    raise _CapacityUnavailable('Guest reference unavailable') from None


class _CapacityTicket:
    __slots__ = ('_session', '_principal', '_remaining', '_state')

    def __init__(self, session, principal, count):
        self._session, self._principal = session, principal
        self._remaining = count
        self._state = 'reserved'


class _GuestCapacity:
    __slots__ = ('_tickets', '_uncertain')

    def __init__(self):
        # Own bounded storage, never a caller-supplied mapping.
        self._tickets = {}
        self._uncertain = False

    def _check(self):
        if (self._uncertain or type(self._tickets) is not dict or
                len(self._tickets) > 4096):
            _refuse()
        total = 0
        per_session = {}
        for identity, ticket in self._tickets.items():
            if (type(ticket) is not _CapacityTicket or identity != id(ticket) or
                    type(ticket._session) is not dict or
                    type(ticket._principal) is not str or not ticket._principal or
                    type(ticket._remaining) is not int or
                    not 0 <= ticket._remaining <= 256 or
                    ticket._state not in ('reserved', 'committed')):
                _refuse()
            key = id(ticket._session)
            prior = per_session.get(key)
            if prior is None:
                prior = [ticket._session, ticket._principal, 0, 0]
                per_session[key] = prior
            if prior[0] is not ticket._session or prior[1] != ticket._principal:
                _refuse()
            prior[2] += ticket._remaining
            prior[3] += 1
            if prior[2] > 512 or prior[3] > 512:
                _refuse()
            total += ticket._remaining
        if total > 4096:
            _refuse()
        return total, per_session

    def _reserve(self, session, principal, count):
        """Retain the full reservation before any record creation/publication.

        Losing the return does not refund capacity: the ledger retains this
        same ticket for original attempt/session retirement to settle later.
        The caller must already have consumed the original source attempt.
        """
        if (type(session) is not dict or type(principal) is not str or
                not principal or type(count) is not int or not 0 <= count <= 256):
            _refuse()
        total, sessions = self._check()
        bucket = sessions.get(id(session))
        used, tickets = (0, 0) if bucket is None else (bucket[2], bucket[3])
        if (bucket is not None and (bucket[0] is not session or bucket[1] != principal)):
            _refuse()
        if total + count > 4096 or used + count > 512 or tickets >= 512 or len(self._tickets) >= 4096:
            _refuse()
        ticket = _CapacityTicket(session, principal, count)
        try:
            self._tickets[id(ticket)] = ticket
        except BaseException:
            self._uncertain = True
            raise
        return ticket

    def _owned(self, ticket):
        self._check()
        if type(ticket) is not _CapacityTicket or self._tickets.get(id(ticket)) is not ticket:
            _refuse()
        return ticket

    def _commit(self, ticket):
        ticket = self._owned(ticket)
        if ticket._state != 'reserved':
            _refuse()
        try:
            ticket._state = 'committed'
        except BaseException:
            self._uncertain = True
            raise
        # Spent and committed references remain charged until actual record
        # retirement. No publication, reference creation or authority here.

    def _release_retired_records(self, ticket, count):
        """Bookkeeping AFTER original owner retires those exact records.

        An integer argument is not retirement proof. The unfinished enclosing
        owner must bind each removed original record to this retained ticket.
        """
        ticket = self._owned(ticket)
        if (ticket._state != 'committed' or type(count) is not int or
                not 0 < count <= ticket._remaining):
            _refuse()
        try:
            ticket._remaining -= count
            if ticket._remaining == 0:
                ticket._state = 'retired'
                del self._tickets[id(ticket)]
        except BaseException:
            self._uncertain = True
            raise

    def _retire_empty_committed(self, ticket):
        # Empty valid inventory has no issued records, but its original
        # retained attempt still owes this explicit DATA ticket retirement.
        ticket = self._owned(ticket)
        if ticket._state != 'committed' or ticket._remaining != 0:
            _refuse()
        try:
            ticket._state = 'retired'
            del self._tickets[id(ticket)]
        except BaseException:
            self._uncertain = True
            raise

    def _retire_unpublished(self, ticket):
        ticket = self._owned(ticket)
        if ticket._state != 'reserved':
            _refuse()
        try:
            ticket._state = 'retired'
            del self._tickets[id(ticket)]
        except BaseException:
            self._uncertain = True
            raise

    def _retire_session(self, session):
        # Called from original auth retirement under the original reference
        # gate. This changes DATA only; native duties remain retained outside.
        self._check()
        if type(session) is not dict:
            _refuse()
        try:
            for identity, ticket in tuple(self._tickets.items()):
                if ticket._session is session:
                    ticket._state = 'retired'
                    del self._tickets[identity]
        except BaseException:
            self._uncertain = True
            raise
