"""Proposed original C retirement/frame join; inactive unqualified source.

No native factory or activation is supplied. The original native-current
operation still refuses. A serialized C echo is not an ACK without this same
original session/writer/request/recipient transaction and actual qualification.
"""
import math
import re

from freq.api import auth
from freq.services.cluster_pilot_http import OriginalPilotResponse, _RequestUnavailable
from freq.services.guest_family_ordering import _family_data
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.guest_owner_response import format_owner_retired_data
from freq.services.pilot_auth_commit import _OrderedAuthGates
from freq.services.pilot_guest_reference_store import (
    OriginalGuestReferenceStore, _OpeningCleanupGates, _OpeningResponseGates,
)
from freq.services.pilot_guest_retirement import _first


class _GuestRetireResponseDuty:
    """Original request's retained first auth snapshot and pending response."""
    __slots__ = ('original', 'token', 'session', 'values', 'nonce', 'cohort',
                 'generation', 'family', 'initial_write_end', 'end', 'frame',
                 'phase')

    def __init__(self, original, token, session, values, nonce):
        self.original, self.token, self.session = original, token, session
        self.values, self.nonce = values, nonce
        self.cohort = self.generation = self.family = None
        self.initial_write_end = original.write_end
        self.end = min(original.end, self.initial_write_end)
        self.frame, self.phase = None, 'new'


class _RetireResponseGates(_OpeningResponseGates):
    """Same nonrenewing waits, with an exact distinct retire duty type."""
    def __init__(self, transaction, original, duty, phase='ready'):
        _OrderedAuthGates.__init__(self, transaction, original, phase)
        if (type(duty) is not _GuestRetireResponseDuty or
                duty.original is not original or type(duty.end) is not float or
                not math.isfinite(duty.end) or
                type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or
                not math.isfinite(original.write_end)):
            raise _RequestUnavailable()
        self._end = min(duty.end, original.end, original.write_end)


def _owned_store(store):
    if type(store) is not OriginalGuestReferenceStore:
        raise _RequestUnavailable()
    owner = store._installation
    if (owner._guest_reference_store is not store or
            owner._original_guest_reference_store is not store or
            owner._auth_commit is not store._auth or
            store._auth._installation is not owner or
            store._auth._broker is not store._broker or
            store._auth._references is not store._references or
            owner._references is not store._references or
            owner._server._pilot_requests is not store._broker or
            store._broker._server is not owner._server):
        raise _RequestUnavailable()
    return owner


def _retired_current_locked(store, original, duty, phase='ready'):
    owner = _owned_store(store)
    if (type(duty) is not _GuestRetireResponseDuty or
            original.guest_response is not duty or duty.original is not original or
            type(original.operation) is not str or
            original.operation != 'guest-owner-retire' or original.body_taken is not True):
        raise _RequestUnavailable()
    cohort, generation, now = store._guard_locked(original,
        duty.token, duty.session, duty.values, phase)
    if (cohort is not duty.cohort or generation is not duty.generation or
            type(duty.initial_write_end) is not float or
            not math.isfinite(duty.initial_write_end) or
            type(duty.end) is not float or not math.isfinite(duty.end) or
            duty.end != min(original.end, duty.initial_write_end) or
            type(original.write_end) is not float or
            not math.isfinite(original.write_end) or original.write_end > duty.end or
            not now < min(duty.end, original.write_end)):
        raise _RequestUnavailable()
    _retired_family_data_locked(owner, duty)


def _retired_family_data_locked(owner, duty):
    """Pure closed-rights DATA checks, called only AFTER original guards.

    Returning normally creates no frame/ACK, authenticates no owner and gives
    no native/currentness/recipient grant. Caller-supplied DATA is not authority.
    """
    if (type(duty) is not _GuestRetireResponseDuty or
            type(duty.session) is not dict or type(duty.nonce) is not str or
            re.fullmatch('[0-9a-f]{64}', duty.nonce) is None or
            type(duty.values) is not tuple or len(duty.values) != 5 or
            type(duty.values[0]) is not str or not duty.values[0] or
            type(duty.family) is not _GuestFamilyRecord or
            type(owner._guest_families_by_nonce) is not dict or
            len(owner._guest_families_by_nonce) > 4096):
        raise _RequestUnavailable()
    family = duty.family
    key = (id(duty.session), duty.nonce)
    _family_data(owner, key, family)
    if (owner._guest_families_by_nonce.get(key) is not family or
            family._session is not duty.session or family._principal != duty.values[0] or
            family._nonce != duty.nonce or type(family._state) is not str or
            family._state != 'retired'):
        raise _RequestUnavailable()
    # Any unremoved known descendant/index prevents an ACK. Physical outside
    # work is independent, but logical rights must already be terminal here.
    indexed = owner._guest_families_by_ref
    children = owner._guest_reference_records
    if (type(indexed) is not dict or len(indexed) > 4096 or
            type(children) is not dict or len(children) > 4096):
        raise _RequestUnavailable()
    for retained in indexed.values():
        if type(retained) is not _GuestFamilyRecord or retained is family:
            raise _RequestUnavailable()
    for record in children.values():
        if type(record) is not _GuestReferenceRecord or record._family is family:
            raise _RequestUnavailable()


def _cleanup_failed_retire(store, original, duty, first):
    """Retire known same-C rights without requiring live positive auth.

    An already settled original logout is recognized by the shared F01 check.
    Unknown duty/capacity remains quarantined, never ACKed or refunded here.
    """
    try:
        with _OpeningCleanupGates(store._auth, original):
            owner = _owned_store(store)
            if (owner._original_component_tables_current() is not True or
                    type(duty) is not _GuestRetireResponseDuty or
                    original.guest_response is not duty or duty.original is not original):
                raise _RequestUnavailable()
            family = duty.family
            if family is None:
                # Lost unseen tombstone-creation return cannot publish an ACK.
                # The original table/committed ticket, if any, remain retained.
                return first
            if (type(family) is not _GuestFamilyRecord or
                    family._session is not duty.session or
                    type(duty.values) is not tuple or len(duty.values) != 5 or
                    type(duty.values[0]) is not str or
                    family._principal != duty.values[0] or family._nonce != duty.nonce):
                raise _RequestUnavailable()
            if store._already_retired_session_family_locked(family):
                return first
            key = (id(duty.session), duty.nonce)
            _family_data(owner, key, family)
            if owner._guest_families_by_nonce.get(key) is not family:
                raise _RequestUnavailable()
            store._retire_known_family_locked(family)
    except BaseException as cleanup:
        first = _first(first, cleanup)
        first = store._quarantine(first)
    return first


def admit_retired_response(store, handler):
    """Tombstone the same session C before formatting/admitting its frame."""
    _owned_store(store)
    original = store._broker._owned(handler)
    duty = None
    first = None
    try:
        if (not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler, require_present=True, is_https=True) or
                type(original.operation) is not str or
                original.operation != 'guest-owner-retire' or
                original.guest_response is not None):
            raise _RequestUnavailable()
        data = store._broker._body_json(handler)
        captured, token, source, session, values = store._auth._capture_session(
            handler, 'guest-owner-retire')
        if captured is not original:
            raise _RequestUnavailable()
        duty = _GuestRetireResponseDuty(original, token, session, values, data['open_nonce'])
        with _RetireResponseGates(store._auth, original, duty):
            cohort, generation, now = store._guard_locked(original, token, session, values)
            store._csrf_nonce_locked(handler, source, values, duty.nonce)
            owner = _owned_store(store)
            if original.guest_response is not None:
                raise _RequestUnavailable()
            # Retain before lookup/allocation/tombstoning and later formatting.
            original.guest_response = duty
            original.write_end = min(original.write_end, duty.end)
            duty.cohort, duty.generation = cohort, generation
            duty.phase = 'tombstoning'
            key = (id(session), duty.nonce)
            if key not in owner._guest_families_by_nonce:
                family = store._retain_family_locked(original, token, session, values,
                    duty.nonce, cohort, generation, now, True)
                duty.family = family
            else:
                family = owner._guest_families_by_nonce[key]
                try:
                    _family_data(owner, key, family)
                    if family._session is not session or family._principal != values[0]:
                        raise _RequestUnavailable()
                except BaseException as error:
                    # Present-but-malformed is not an unseen C to overwrite.
                    raise store._quarantine(error)
                duty.family = family
                store._retire_known_family_locked(family)
            duty.phase = 'tombstoned'
            _retired_current_locked(store, original, duty)
        # C echo is unretained DATA until the SAME original final transaction.
        frame = format_owner_retired_data(duty.nonce)
        duty.frame, duty.phase = frame, 'prepared'
        with _RetireResponseGates(store._auth, original, duty):
            _retired_current_locked(store, original, duty)
            if duty.phase != 'prepared' or duty.frame is not frame or type(frame) is not OriginalPilotResponse:
                raise _RequestUnavailable()
            try:
                store._broker._admit_frame_locked(handler, original, frame)
                duty.phase = 'admitted'
            except BaseException as error:
                raise store._quarantine(error)
        return frame
    except BaseException as error:
        first = error
    if duty is not None and original.guest_response is duty:
        first = _cleanup_failed_retire(store, original, duty, first)
    raise first


def write_retired_response(store, handler, frame):
    _owned_store(store)
    original = store._broker._owned(handler)
    duty = original.guest_response
    if type(duty) is not _GuestRetireResponseDuty:
        raise _RequestUnavailable()
    try:
        with _RetireResponseGates(store._auth, original, duty, 'admitted'):
            _retired_current_locked(store, original, duty, 'admitted')
            if (duty.phase != 'admitted' or duty.frame is not frame or
                    original.frame is not frame or type(frame) is not OriginalPilotResponse):
                raise _RequestUnavailable()
            try:
                store._broker._reserve_write_locked(handler, original, frame)
                duty.phase = 'write-reserved'
            except BaseException as error:
                raise store._quarantine(error)
        duty.phase = 'write-attempted'
        store._broker._send_reserved(handler, frame)
        duty.phase = 'sent'
        return
    except BaseException as error:
        first = error
    raise _cleanup_failed_retire(store, original, duty, first)


def retire_handler_duty(store, handler):
    _owned_store(store)
    original = store._broker._owned(handler)
    duty = original.guest_response
    if duty is None:
        return
    if (type(duty) is not _GuestRetireResponseDuty or duty.original is not original or
            type(duty.phase) is not str):
        raise store._quarantine(_RequestUnavailable())
    if duty.phase == 'sent':
        return
    first = _cleanup_failed_retire(store, original, duty, None)
    if first is not None:
        raise first
