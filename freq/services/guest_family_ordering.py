"""Private fixed-storage DATA transition, NOT an original issuer/admission.

The original guarded owner is still unfinished. It must hold its SAME writer,
validate original request/session/source/cohort/end and retain entropy duties
before calling this helper. This function checks DATA identity only; it never
acquires entropy, issues a response, grants a read or makes native-current True.
"""
import re

from freq.services.guest_reference_capacity import _CapacityTicket, _refuse
from freq.services.guest_family_state import _GuestFamilyRecord


def _hex(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _family_data(owner, key, family):
    if (type(family) is not _GuestFamilyRecord or
            type(family._session) is not dict or
            type(family._principal) is not str or not family._principal or
            not _hex(family._nonce) or
            type(key) is not tuple or len(key) != 2 or
            type(key[0]) is not int or type(key[1]) is not str or
            key != (id(family._session), family._nonce) or
            (family._ref is not None and not _hex(family._ref))):
        _refuse()
    ticket = family._ticket
    if (type(ticket) is not _CapacityTicket or
            ticket._session is not family._session or
            type(ticket._principal) is not str or
            ticket._principal != family._principal or
            type(ticket._remaining) is not int or ticket._remaining != 1 or
            ticket._state != 'committed' or
            owner._guest_capacity._tickets.get(id(ticket)) is not ticket):
        _refuse()


def bind_family_reference_data_locked(owner, family, candidate):
    """Bind at most one F in the fixed original session DATA namespace.

    True means only a private DATA transition; original owner MUST still
    final-admit its original response under native/recipient/source guards.
    False is an ordinary entropy collision: this C becomes a charged retired
    tombstone. No retry/refund/new history/descendant or public response here.
    Every other failure marks capacity uncertain for the enclosing original
    owner to quarantine, retaining native duties. No cleanup completion claim.
    """
    if owner._original_component_tables_current() is not True:
        _refuse()
    capacity = owner._guest_capacity
    try:
        capacity._check()
        by_nonce = owner._guest_families_by_nonce
        by_ref = owner._guest_families_by_ref
        if len(by_nonce) > 4096 or len(by_ref) > 4096:
            _refuse()
        if type(family) is not _GuestFamilyRecord or not _hex(candidate):
            _refuse()
        key = (id(family._session), family._nonce)
        _family_data(owner, key, family)
        if (by_nonce.get(key) is not family or family._state != 'opening' or
                family._binding_attempted is not False or family._ref is not None):
            _refuse()
        collision = False
        seen = set()
        charged = set()
        for retained_key, retained in by_nonce.items():
            _family_data(owner, retained_key, retained)
            ticket_id = id(retained._ticket)
            if ticket_id in charged:
                _refuse()
            charged.add(ticket_id)
            if retained._session is not family._session:
                continue
            if retained._ref is not None:
                # Retired, expired and uncertain publication records count;
                # never use only the optional live redemption index.
                if retained._ref in seen:
                    _refuse()
                seen.add(retained._ref)
                if retained._ref == candidate:
                    collision = True
        if collision:
            family._retire()
            return False
        ref_key = (id(family._session), candidate)
        if ref_key in by_ref:
            # An index unaccounted for in retained history is corruption, not
            # permission to overwrite or to remove another family's entry.
            _refuse()
        # Retain F on its charged family BEFORE the optional lookup index.
        # Unknown index-assignment return cannot erase this F history.
        family._bind_once(candidate)
        by_ref[ref_key] = family
        return True
    except BaseException as first:
        try:
            capacity._uncertain = True
        except BaseException as later:
            if isinstance(first, Exception) and not isinstance(later, Exception):
                raise later
        raise first
