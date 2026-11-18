"""Private family DATA, not an original issuer or authenticated owner.

Original guarded operations and reservation retention remain unfinished.
Constructing a record or setting its state cannot establish native authority.
"""
import math
import re

from freq.services.guest_reference_capacity import _CapacityTicket, _refuse


class _GuestFamilyRecord:
    __slots__ = ('_session', '_principal', '_nonce', '_ref', '_cohort',
                 '_generation', '_open_request', '_created', '_expires',
                 '_ticket', '_state', '_binding_attempted', '_sources_spent',
                 '_session_token', '_auth_values', '_opening_end', '_entropy_duty')

    def __init__(self, session, principal, nonce, cohort, generation,
                 open_request, created, expires, ticket, token=None,
                 auth_values=None, opening_end=None):
        if (type(session) is not dict or type(principal) is not str or not principal or
                type(nonce) is not str or re.fullmatch('[0-9a-f]{64}', nonce) is None or
                cohort is None or generation is None or
                type(created) is not float or type(expires) is not float or
                not math.isfinite(created) or not math.isfinite(expires) or
                not created < expires <= created + 30.0 or
                type(ticket) is not _CapacityTicket or ticket._session is not session or
                ticket._principal != principal or ticket._remaining != 1 or
                ticket._state != 'reserved'):
            _refuse()
        if ((token is None) != (auth_values is None) or
                (token is None) != (opening_end is None) or
                (token is not None and (type(token) is not str or
                 not 0 < len(token) <= 512 or type(auth_values) is not tuple or
                 len(auth_values) != 5 or type(auth_values[0]) is not str or
                 auth_values[0] != principal or type(opening_end) is not float or
                 not math.isfinite(opening_end) or not created < opening_end))):
            _refuse()
        self._session, self._principal, self._nonce = session, principal, nonce
        self._cohort, self._generation = cohort, generation
        self._open_request = open_request
        # Original guarded creator retains its FIRST accepted auth capture.
        # None in standalone DATA holders grants no auth/native authority.
        # These private values must never be serialized, logged or returned.
        self._session_token, self._auth_values = token, auth_values
        self._opening_end = opening_end
        # One retained original opening duty, before its outside entropy call.
        self._entropy_duty = None
        self._created, self._expires = created, expires
        self._ticket = ticket
        self._ref = None
        self._state = 'opening'
        self._binding_attempted = self._sources_spent = False

    def _bind_once(self, reference):
        # No entropy is generated here. Original owner must prove its retained
        # open request/current writer/family/session/cohort AND uniqueness
        # against every retained family F in that original session. This DATA
        # method performs no uniqueness scan and cannot issue authority.
        if self._state != 'opening' or self._binding_attempted:
            _refuse()
        self._binding_attempted = True
        if type(reference) is not str or re.fullmatch('[0-9a-f]{64}', reference) is None:
            self._state = 'retired'
            _refuse()
        self._ref = reference
        self._state = 'live'

    def _retire(self):
        # Retired nonce tombstone remains charged until original session
        # retirement. Keep _ref even after optional lookup-index removal:
        # it is retained non-reuse history on this same charged family.
        # This alone neither retires descendants nor settles IO.
        self._state = 'retired'
