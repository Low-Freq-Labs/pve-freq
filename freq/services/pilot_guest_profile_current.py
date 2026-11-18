"""Unwired same original registered-profile revalidation; no native grant.

This checkpoint neither constructs nor starts a section. Future original
acquisition must separately preown its native holder and whole-job physical
allowance, retain unknown returns, and revalidate SAME result and recipient.
Repeated checks do not permit repeated consumption or native operations.
"""
import math
import threading

from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.pilot_auth_commit import _OrderedAuthGates
from freq.services.pilot_guest_reference_store import _OpeningResponseGates
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_profile_begin import _GuestProfileBeginDuty, _CorruptProfileSource
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData
from freq.services.pilot_guest_profile_registration import (
    _ProfileAcquisitionDuty, _profile_registration_tables_data,
    _known_profile_slots_data,
)
from freq.services.pilot_guest_profile_retirement import _profile_retirement_custody_matches
from freq.services.pilot_guest_profile_consumed import consumed_profile_guest_data_locked
from freq.services.pilot_guest_sources_begin import (
    _source_family_data_locked, _ExpiredSourceFamily, _CorruptSourceFamily,
)


class _ProfileCurrentGates(_OpeningResponseGates):
    def __init__(self, transaction, original, duty):
        _OrderedAuthGates.__init__(self, transaction, original, 'ready')
        if (type(duty) is not _ProfileAcquisitionDuty or duty.original is not original or
                any(type(value) is not float or not math.isfinite(value)
                    for value in (duty.end, original.end, original.write_end))):
            raise _RequestUnavailable()
        self._end = min(duty.end, original.end, original.write_end)


def _registered_profile_context_data_locked(owner, duty, cohort, generation, now):
    """Read-only exact context DATA; caller still owes original positive gates.

    No new record, consumed bit, reference clock, deadline, plan, native slot,
    ticket or map is changed. This positive predicate MUST NOT gate cleanup.
    Only the original wrapper below authenticates/checks the original graph;
    a supplied owner or duty passing DATA tests conveys no authority.
    """
    if type(duty) is not _ProfileAcquisitionDuty:
        raise _RequestUnavailable()
    original, begin, plan = duty.original, duty.begin, duty.plan
    if (type(original) is not _OriginalRequest or original.guest_response is not duty or
            type(original.operation) is not str or original.operation != 'guest-owner-profile' or
            original.body_taken is not True or type(duty.phase) is not str or duty.phase != 'registered' or
            type(begin) is not _GuestProfileBeginDuty or begin.original is not original or
            type(begin.phase) is not str or begin.phase != 'registration-attempted' or
            type(begin.values) is not tuple or len(begin.values) != 5 or
            type(begin.values[0]) is not str or not begin.values[0] or
            type(plan) is not _GuestProfileSubreadsData or plan.original is not original or
            plan.begin is not begin or plan.record is not begin.record or
            plan.source is not begin.source or plan.target is not begin.target or
            cohort is not begin.cohort or generation is not begin.generation or
            any(type(value) is not float or not math.isfinite(value)
                for value in (now, duty.last_clock, duty.end, plan.end, begin.end,
                    begin.created, original.end, original.write_end)) or
            not begin.created <= duty.last_clock <= now < min(
                duty.end, plan.end, begin.end, original.end, original.write_end) or
            duty.end > plan.end or plan.end > begin.end or original.write_end > duty.end):
        raise _RequestUnavailable()
    active, native = _profile_registration_tables_data(owner, duty)
    if (active.get(original) is not duty or native.get(original) is not duty or
            type(duty.credential_uid) is not int or owner._credential_uid != duty.credential_uid or
            type(owner._credential_uid) is not int or
            not 1 <= owner._credential_uid <= 4294967294 or
            type(duty.configured_token) is not tuple or len(duty.configured_token) != 2 or
            any(type(value) is not str for value in duty.configured_token) or
            not 0 < len(duty.configured_token[0]) <= 257 or
            not 0 < len(duty.configured_token[1]) <= 128 or
            owner._configured_token_id is not duty.configured_token or
            cohort.token_id is not duty.configured_token):
        raise _RequestUnavailable()
    _known_profile_slots_data(duty)
    # Existing canonical helpers validate exact live F/index membership and
    # same spent guest/ticket/configured source. No second consumption/update.
    family = _source_family_data_locked(owner, begin.session, begin.values[0],
        begin.family_ref, cohort, generation, now)
    record = consumed_profile_guest_data_locked(owner, family, begin.session,
        begin.values[0], begin.guest_ref, cohort, generation, now)
    if (family is not begin.family or record is not begin.record or
            record._source is not begin.source or record._target is not begin.target):
        raise _RequestUnavailable()
    return duty


def revalidate_registered_profile_context(store, handler):
    """Same original context checkpoint only; no section admission/operation.

    Original native-current remains False, so no positive original use exists.
    Successful source-shaped validation would update only retained attempt
    clock; it never renews any end or changes the registered phase. The actual
    original parent must perform retirement after any failure/control before
    releasing broker ownership; no store/dispatcher integration is claimed.
    """
    owner = _owned_store(store)
    original = store._broker._owned(handler)
    duty = original.guest_response
    if (type(duty) is not _ProfileAcquisitionDuty or duty.original is not original or
            type(duty.begin) is not _GuestProfileBeginDuty or duty.begin.original is not original):
        raise _RequestUnavailable()
    with _ProfileCurrentGates(store._auth, original, duty):
        begin = duty.begin
        cohort, generation, now = store._guard_locked(original, begin.token, begin.session, begin.values)
        store._csrf_nonce_locked(handler, 'cookie', begin.values, begin.family_ref)
        if (original.thread is not threading.current_thread() or
                owner._original_guest_profile_tables_current() is not True):
            raise _RequestUnavailable()
        _profile_retirement_custody_matches(store, original, handler, duty)
        try:
            same = _registered_profile_context_data_locked(owner, duty, cohort, generation, now)
        except _ExpiredSourceFamily as expired:
            store._retire_known_family_locked(expired.family)
            raise _RequestUnavailable() from None
        except (_CorruptProfileSource, _CorruptSourceFamily) as error:
            raise store._quarantine(error)
        if same is not duty:
            raise _RequestUnavailable()
        duty.last_clock = now
    return duty


# No acquiring native constructor/call/result, end extension, frame or ACK.
