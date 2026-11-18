"""Proposed original guest opening component; no native factory.

This draft accepts no supplied native owner, map, source or callback. The
future original factory must retain it on the same installation before use.
The canonical native-current operation remains False, so no opening can pass
its original admission gates. Proposed one-shot entropy acquisition and private
F binding and opening-frame dispatch below remain unqualified inactive source.
Proposed source-list descendant issuance remains unqualified. Retirement-frame
source adds no actual ACK; no positive operation passes native-current False.
"""
import datetime
import hmac
import math
import os
import threading
import re
import time

from freq.api import auth
from freq.services.cluster_pilot_http import OriginalPilotResponse, _RequestUnavailable
from freq.services.cluster_references import ClusterReferences
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_family_ordering import (
    _family_data, bind_family_reference_data_locked,
)
from freq.services.guest_reference_capacity import _CapacityTicket
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_auth_commit import OriginalAuthCommit, _OrderedAuthGates
from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.pilot_guest_retirement import _first
from freq.services.guest_owner_response import format_owner_open_data


class _OpeningCleanupGates(_OrderedAuthGates):
    """Retirement-only nonblocking gates, with inherited duty accounting.

    Expired/retired requests need cleanup too. No eligible/currentness check
    grants a positive operation here. Unknown acquisition/release quarantines
    the same original owner; no uncertain lock is released speculatively.
    """
    def __enter__(self):
        try:
            for index, lock in enumerate(self._locks):
                self._states[index] = 'acquire-pending'
                acquired = lock.acquire(blocking=False)
                self._states[index] = 'owned' if acquired else 'not-acquired'
                if not acquired:
                    raise _RequestUnavailable()
            return self
        except BaseException as error:
            first = self._transaction._uncertain(error)
        raise self._release(first)


class _OpeningEntropyDuty:
    """One private pending acquisition, retained by its charged family.

    Allocation is pure storage. No supplied bytes/callback/entropy source is
    accepted. This record is not proof of original native parent custody.
    """
    __slots__ = ('store', 'original', 'family', 'end', 'thread', 'phase',
                 'candidate')

    def __init__(self, store, original, family):
        self.store, self.original, self.family = store, original, family
        self.end = min(family._opening_end, family._expires)
        self.thread = threading.current_thread()
        self.phase, self.candidate = 'armed', None



class _GuestOpeningResponseDuty:
    """Private original-request response storage, not an admission witness."""
    __slots__ = ('original', 'family', 'family_ref', 'entropy', 'end', 'frame',
                 'phase', 'initial_write_end')

    def __init__(self, original, family):
        self.original, self.family = original, family
        self.family_ref, self.entropy = family._ref, family._entropy_duty
        self.initial_write_end = original.write_end
        self.end = min(original.end, self.initial_write_end,
                       family._opening_end, family._expires)
        self.frame, self.phase = None, 'format-pending'


class _OpeningResponseGates(_OrderedAuthGates):
    """Same ordered gates; waits share the captured earlier response end."""
    def __init__(self, transaction, original, duty, phase='ready'):
        super().__init__(transaction, original, phase)
        if (type(duty) is not _GuestOpeningResponseDuty or
                duty.original is not original or type(duty.end) is not float or
                not math.isfinite(duty.end) or
                type(original.end) is not float or not math.isfinite(original.end) or
                type(original.write_end) is not float or
                not math.isfinite(original.write_end)):
            raise _RequestUnavailable()
        self._end = min(duty.end, original.end, original.write_end)

    def __enter__(self):
        try:
            for index, lock in enumerate(self._locks):
                original = self._original
                if (type(original.end) is not float or not math.isfinite(original.end) or
                        type(original.write_end) is not float or
                        not math.isfinite(original.write_end)):
                    raise _RequestUnavailable()
                self._end = min(self._end, original.end, original.write_end)
                end = self._end
                remaining = end - time.monotonic()
                if not math.isfinite(remaining) or remaining <= 0:
                    raise _RequestUnavailable()
                self._states[index] = 'acquire-pending'
                acquired = lock.acquire(timeout=remaining)
                self._states[index] = 'owned' if acquired else 'not-acquired'
                if not acquired or not time.monotonic() < min(
                        self._end, original.end, original.write_end):
                    raise _RequestUnavailable()
            self._transaction._current_locked(self._original, self._phase)
            return self
        except BaseException as error:
            first = error
        raise self._release(first)


class OriginalGuestReferenceStore:
    __slots__ = ('_installation', '_auth', '_broker', '_references',
                 '_quarantine_targets', '_quarantine_states', '_quarantine_errors',
                 '_quarantine_first_input', '_quarantine_last_input',
                 '_quarantine_first_result', '_quarantine_last_result')

    def __init__(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(installation) is not OriginalPilotInstallation or
                type(installation._auth_commit) is not OriginalAuthCommit or
                installation._auth_commit._installation is not installation or
                type(installation._references) is not ClusterReferences or
                installation._guest_reference_store is not self or
                installation._original_guest_reference_store is not self or
                installation._auth_commit._references is not installation._references):
            raise _RequestUnavailable()
        self._installation = installation
        self._auth = installation._auth_commit
        self._broker = self._auth._broker
        self._references = installation._references
        # Pure fixed cleanup storage before this component can be used.
        # Construction is still inactive and grants no native/source authority.
        self._quarantine_first_input = self._quarantine_last_input = None
        self._quarantine_first_result = self._quarantine_last_result = None
        self._quarantine_states = ['unused'] * 4
        self._quarantine_errors = [None] * 4
        self._quarantine_targets = (
            (installation._guest_capacity, '_uncertain', True),
            (installation, '_admission_uncertain', True),
            (installation, '_live', False),
            (self._broker, '_live', False))

    def _guard_locked(self, original, token, session, values, phase='ready'):
        owner = self._installation
        if (type(self) is not OriginalGuestReferenceStore or
                getattr(owner, '_guest_reference_store', None) is not self or
                getattr(owner, '_original_guest_reference_store', None) is not self or
                owner._auth_commit is not self._auth or
                self._auth._installation is not owner or
                self._auth._broker is not self._broker or
                self._auth._references is not self._references or
                owner._references is not self._references):
            raise _RequestUnavailable()
        # Fixed native/source/writer/current-request/recipient/end operation;
        # absent actual producer always refuses before any guest mutable lookup.
        self._auth._current_locked(original, phase)
        if (not self._auth._same_session_locked(token, session, values, time.time()) or
                owner._original_component_tables_current() is not True):
            raise _RequestUnavailable()
        cohort = owner._configured_data
        if (type(cohort) is not PilotConfiguredData or
                owner._configured_nodes is not cohort.nodes or
                owner._configuration_revision is not cohort.configuration_revision or
                owner._configured_roles is not cohort.roles or
                type(cohort.nodes) is not tuple or len(cohort.nodes) > 32):
            raise _RequestUnavailable()
        now = time.monotonic()
        if (type(now) is not float or not math.isfinite(now) or
                not now < original.end):
            raise _RequestUnavailable()
        return cohort, cohort.configuration_revision, now

    def _quarantine(self, first):
        """Once-only fixed disable writes, every caught write error retained.

        Saved original capacity/owner/broker targets never replaced by current
        aliases. Pending/uncertain calls are never retried from a flag value.
        Every still-unused fixed write is visited after caught error/control.
        Returned markers concern local assignment only, never physical closure.
        Callers retain their received input history; this stores first/latest
        inputs/results and all four once-only caught write errors, not a whole
        cross-request/reentry error history or universal allocation guarantee.
        """
        if type(self) is not OriginalGuestReferenceStore:
            raise _RequestUnavailable()
        if not issubclass(type(first), BaseException):
            first = _RequestUnavailable()
        if self._quarantine_first_input is None:
            self._quarantine_first_input = first
        self._quarantine_last_input = first
        for index in range(4):
            if self._quarantine_states[index] != 'unused':
                continue
            target, field, value = self._quarantine_targets[index]
            self._quarantine_states[index] = 'write-pending'
            try:
                setattr(target, field, value)
            except BaseException as later:
                self._quarantine_errors[index] = later
                self._quarantine_states[index] = 'uncertain'
            else:
                self._quarantine_states[index] = 'write-returned'
        # This invocation's original error precedes cleanup failures. Callers
        # with their own earlier primary combine it before calling this entry.
        selected = first
        for later in self._quarantine_errors:
            if later is None:
                continue
            if (issubclass(type(selected), Exception) and not issubclass(type(later), Exception) or
                    issubclass(type(selected), Exception) and not issubclass(type(selected), MemoryError) and
                    issubclass(type(later), MemoryError)):
                selected = later
        if self._quarantine_first_result is None:
            self._quarantine_first_result = selected
        self._quarantine_last_result = selected
        return selected

    @staticmethod
    def _csrf_nonce_locked(handler, source, values, nonce):
        supplied = handler.headers.get('X-Freq-CSRF', '')
        if (source != 'cookie' or values is None or
                type(values[4]) is not str or not values[4].isascii() or
                type(supplied) is not str or not supplied.isascii() or
                not hmac.compare_digest(values[4], supplied) or
                type(nonce) is not str or re.fullmatch('[0-9a-f]{64}', nonce) is None):
            raise _RequestUnavailable()

    def _retain_family_locked(self, original, token, session, values, nonce,
                              cohort, generation, now, retired):
        owner = self._installation
        principal = values[0]
        key = (id(session), nonce)
        capacity = owner._guest_capacity
        try:
            total, sessions = capacity._check()
        except BaseException as error:
            raise self._quarantine(error)
        bucket = sessions.get(id(session))
        if bucket is not None and (bucket[0] is not session or bucket[1] != principal):
            raise self._quarantine(_RequestUnavailable())
        if (total >= 4096 or len(capacity._tickets) >= 4096 or
                (bucket is not None and (bucket[2] >= 512 or bucket[3] >= 512))):
            # Known full application capacity before mutation is an ordinary
            # fixed refusal. It does not imply global native uncertainty.
            raise _RequestUnavailable()
        try:
            ticket = capacity._reserve(session, principal, 1)
            family = _GuestFamilyRecord(session, principal, nonce, cohort,
                generation, original, now, now + 30.0, ticket,
                token=token, auth_values=values, opening_end=original.end)
            if retired:
                family._retire()
            owner._guest_families_by_nonce[key] = family
            capacity._commit(ticket)
            return family
        except BaseException as error:
            raise self._quarantine(error)

    def begin_opening(self, handler, nonce):
        """Unwired first half only: retain charged C BEFORE future entropy.

        nonce is decoded DATA. A future exact v2 original body owner must parse
        it; this method cannot substitute for framing/duplicate-key/byte gates.
        No native call or public success follows the returned private record.
        """
        if (not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler, require_present=True,
                                              is_https=True)):
            raise _RequestUnavailable()
        # Future literal operation is deliberately absent from the accepted
        # router. No alias to existing v1 sources/profile or Cluster operations.
        original, token, source, session, values = self._auth._capture_session(
            handler, 'guest-owner-open')
        with _OrderedAuthGates(self._auth, original):
            cohort, generation, now = self._guard_locked(original, token, session, values)
            self._csrf_nonce_locked(handler, source, values, nonce)
            owner = self._installation
            key = (id(session), nonce)
            if key in owner._guest_families_by_nonce:
                # Any opening/live/expired/retired C is permanently seen in
                # this original session. No retry, renewal or second grant.
                raise _RequestUnavailable()
            # Reservation/family/original request retained before any future
            # entropy; losing an acquiring return never refunds or reopens C.
            return self._retain_family_locked(original, token, session, values,
                nonce, cohort, generation, now, False)

    def _opening_current_locked(self, original, family):
        """Future native finalizer's guard, not an entropy/response receipt.

        Its fixed caller must already own the original ordered gates and the
        exact retained native entropy attempt. No such caller is provided yet.
        Never recapture a newer auth tuple or extend the original opening end.
        """
        if (type(family) is not _GuestFamilyRecord or
                type(family._session_token) is not str or
                type(family._auth_values) is not tuple or
                len(family._auth_values) != 5):
            raise _RequestUnavailable()
        cohort, generation, now = self._guard_locked(original,
            family._session_token, family._session, family._auth_values)
        owner = self._installation
        key = (id(family._session), family._nonce)
        try:
            _family_data(owner, key, family)
        except BaseException as error:
            raise self._quarantine(error)
        if (owner._guest_families_by_nonce.get(key) is not family or
                family._open_request is not original or
                type(original.operation) is not str or
                original.operation != 'guest-owner-open'):
            # A wrong request/family/purpose is not permission to retire an
            # unrelated family's rights, even in the same original session.
            raise _RequestUnavailable()
        if (family._state != 'opening' or family._binding_attempted is not False or
                family._ref is not None):
            # A duplicate finalizer cannot consume or revoke an issued family.
            raise _RequestUnavailable()
        if (family._cohort is not cohort or family._generation is not generation or
                type(family._opening_end) is not float or
                type(original.end) is not float or original.end != family._opening_end or
                not family._created <= now < min(family._expires, family._opening_end)):
            # Ordinary stale/expired/retired opening cannot be renewed. Actual
            # outside duties remain retained; this guard emits no response.
            try:
                self._retire_known_family_locked(family)
            except BaseException as error:
                raise self._quarantine(error)
            raise _RequestUnavailable()
        return now

    def complete_opening_entropy(self, handler, family):
        """Inactive one-shot entropy and same-opening private F assignment.

        No response, descendant, public dispatch or ACK is produced. The real
        native factory/currentness remains absent and refuses admission. Even
        a private returned live family would still owe original response
        retention, serialization and final admission before publication.
        """
        original = self._broker._owned(handler)
        claimed = False
        first = None
        try:
            with _OrderedAuthGates(self._auth, original):
                self._opening_current_locked(original, family)
                if family._entropy_duty is not None:
                    # A duplicate caller never retires or overwrites another
                    # in-flight finalizer's retained opening duty.
                    raise _RequestUnavailable()
                duty = _OpeningEntropyDuty(self, original, family)
                claimed = True
                family._entropy_duty = duty
            # Every original admission gate has been released. No retry loop,
            # caller entropy function, fallback, serialization or IO under it.
            if (family._entropy_duty is not duty or
                    duty.store is not self or duty.original is not original or
                    duty.family is not family or duty.phase != 'armed' or
                    duty.thread is not threading.current_thread() or
                    duty.candidate is not None or
                    not time.monotonic() < duty.end):
                raise _RequestUnavailable()
            # BEFORE entering native code: a lost/short/failed return cannot
            # retry. This fixed call exists only in the original guarded entry,
            # never on a caller-constructible private DATA holder.
            duty.phase = 'attempted'
            raw = os.getrandom(32, os.GRND_NONBLOCK)
            if (type(raw) is not bytes or len(raw) != 32 or
                    not time.monotonic() < duty.end):
                raise _RequestUnavailable()
            duty.candidate = raw.hex()
            duty.phase = 'received'
            with _OrderedAuthGates(self._auth, original):
                self._opening_current_locked(original, family)
                if (family._entropy_duty is not duty or
                        type(duty) is not _OpeningEntropyDuty or
                        duty.store is not self or duty.original is not original or
                        duty.family is not family or duty.phase != 'received' or
                        duty.thread is not threading.current_thread() or
                        duty.end != min(family._opening_end, family._expires)):
                    raise _RequestUnavailable()
                # The reviewed fixed transition scans all same-session F
                # history, including retired tombstones and removed indexes.
                # It retains F on this charged family BEFORE index insertion.
                if not bind_family_reference_data_locked(
                        self._installation, family, duty.candidate):
                    raise _RequestUnavailable()
                duty.phase = 'bound'
                return family
        except BaseException as error:
            first = error
        if claimed:
            # Logical cleanup is independent of expired positive admission.
            # All known descendants are attempted by the existing retirement
            # method. Failure retains C, F history, the charged duty and outer
            # process obligations; no unknown capacity is refunded here.
            try:
                with _OpeningCleanupGates(self._auth, original):
                    owner = self._installation
                    if (owner._original_component_tables_current() is not True or
                            owner._guest_reference_store is not self or
                            owner._original_guest_reference_store is not self or
                            self._auth._installation is not owner or
                            owner._auth_commit is not self._auth or
                            self._auth._broker is not self._broker or
                            self._auth._references is not self._references or
                            owner._references is not self._references or
                            owner._server._pilot_requests is not self._broker or
                            self._broker._server is not owner._server or
                            family._entropy_duty is not duty or
                            family._open_request is not original):
                        raise _RequestUnavailable()
                    if not self._already_retired_session_family_locked(family):
                        key = (id(family._session), family._nonce)
                        _family_data(owner, key, family)
                        if owner._guest_families_by_nonce.get(key) is not family:
                            raise _RequestUnavailable()
                        self._retire_known_family_locked(family)
                    duty.phase = 'retired'
            except BaseException as cleanup:
                first = _first(first, cleanup)
                first = self._quarantine(first)
        if first is not None:
            raise first
        raise _RequestUnavailable()

    def _opening_response_locked(self, original, duty, phase='ready'):
        if (type(duty) is not _GuestOpeningResponseDuty or
                original.guest_response is not duty or duty.original is not original or
                type(original.operation) is not str or
                original.operation != 'guest-owner-open' or
                original.body_taken is not True):
            raise _RequestUnavailable()
        family = duty.family
        if type(family) is not _GuestFamilyRecord:
            raise _RequestUnavailable()
        cohort, generation, now = self._guard_locked(original,
            family._session_token, family._session, family._auth_values, phase)
        owner = self._installation
        key = (id(family._session), family._nonce)
        _family_data(owner, key, family)
        entropy = duty.entropy
        if (owner._guest_families_by_nonce.get(key) is not family or
                type(duty.family_ref) is not str or
                owner._guest_families_by_ref.get((id(family._session), duty.family_ref)) is not family or
                family._ref != duty.family_ref or family._state != 'live' or
                family._binding_attempted is not True or
                family._open_request is not original or
                family._cohort is not cohort or family._generation is not generation or
                type(entropy) is not _OpeningEntropyDuty or
                family._entropy_duty is not entropy or entropy.store is not self or
                entropy.original is not original or entropy.family is not family or
                type(entropy.phase) is not str or entropy.phase != 'bound' or
                type(entropy.candidate) is not str or entropy.candidate != duty.family_ref or
                entropy.thread is not threading.current_thread() or
                type(duty.end) is not float or not math.isfinite(duty.end) or
                type(original.end) is not float or
                original.end != family._opening_end or
                type(duty.initial_write_end) is not float or
                not math.isfinite(duty.initial_write_end) or
                duty.end != min(original.end, duty.initial_write_end,
                                family._opening_end, family._expires) or
                type(original.write_end) is not float or not math.isfinite(original.write_end) or
                original.write_end > duty.end or
                not family._created <= now < min(duty.end, original.write_end)):
            raise _RequestUnavailable()

    def _already_retired_session_family_locked(self, family):
        """Recognize fully settled old-session DATA under original gates.

        This never grants native currentness, refunds capacity or supplies a
        retirement ACK. The caller has already checked its SAME original
        component/table ownership under the four retirement-only gates.
        """
        if type(family) is not _GuestFamilyRecord:
            return False
        token, values = family._session_token, family._auth_values
        ticket = family._ticket
        if (type(family._session) is not dict or
                type(family._principal) is not str or not family._principal or
                type(token) is not str or not 0 < len(token) <= 512 or
                type(values) is not tuple or len(values) != 5 or
                type(values[0]) is not str or values[0] != family._principal or
                type(family._nonce) is not str or
                re.fullmatch('[0-9a-f]{64}', family._nonce) is None or
                (family._ref is not None and (type(family._ref) is not str or
                 re.fullmatch('[0-9a-f]{64}', family._ref) is None)) or
                type(family._state) is not str or family._state != 'retired' or
                type(ticket) is not _CapacityTicket or
                ticket._session is not family._session or
                type(ticket._principal) is not str or
                ticket._principal != family._principal or
                type(ticket._remaining) is not int or ticket._remaining != 1 or
                type(ticket._state) is not str or ticket._state != 'retired'):
            return False
        owner = self._installation
        if (type(owner._issued_sessions) is not dict or len(owner._issued_sessions) > 1024 or
                type(auth._auth_tokens) is not dict or len(auth._auth_tokens) > 1024):
            return False
        if (owner._issued_sessions.get(token) is family._session or
                auth._auth_tokens.get(token) is family._session or
                id(ticket) in owner._guest_capacity._tickets or
                (id(family._session), family._nonce) in owner._guest_families_by_nonce or
                (family._ref is not None and
                 (id(family._session), family._ref) in owner._guest_families_by_ref)):
            return False
        records = owner._guest_reference_records
        if type(records) is not dict or len(records) > 4096:
            return False
        for record in records.values():
            if (type(record) is not _GuestReferenceRecord or
                    record._family is family or record._session is family._session):
                return False
        # Successful session retirement settles ALL of that old session's
        # graph, not just this one nonce. Retained siblings/tickets mean the
        # proposed fast path cannot call the session fully settled.
        for rows, kind in (
                (owner._guest_families_by_nonce, _GuestFamilyRecord),
                (owner._guest_families_by_ref, _GuestFamilyRecord),
                (owner._guest_capacity._tickets, _CapacityTicket)):
            if type(rows) is not dict or len(rows) > 4096:
                return False
            for row in rows.values():
                if type(row) is not kind or row._session is family._session:
                    return False
        return True

    def _retire_failed_opening(self, original, family, first):
        """Logical failure cleanup only; no response or native closure claim."""
        try:
            with _OpeningCleanupGates(self._auth, original):
                owner = self._installation
                if (owner._original_component_tables_current() is not True or
                        owner._guest_reference_store is not self or
                        owner._original_guest_reference_store is not self or
                        owner._auth_commit is not self._auth or
                        self._auth._installation is not owner or
                        self._auth._broker is not self._broker or
                        self._auth._references is not self._references or
                        owner._references is not self._references or
                        owner._server._pilot_requests is not self._broker or
                        self._broker._server is not owner._server or
                        type(family) is not _GuestFamilyRecord or
                        family._open_request is not original):
                    raise _RequestUnavailable()
                if self._already_retired_session_family_locked(family):
                    # Original logout already retired this exact old family,
                    # removed its indexes/children and settled its ticket.
                    # No mutation, refund, unrelated-session cleanup or ACK.
                    return first
                key = (id(family._session), family._nonce)
                _family_data(owner, key, family)
                if owner._guest_families_by_nonce.get(key) is not family:
                    raise _RequestUnavailable()
                self._retire_known_family_locked(family)
        except BaseException as cleanup:
            first = _first(first, cleanup)
            first = self._quarantine(first)
        return first

    def admit_opening_response(self, handler):
        """Inactive original body -> opening -> entropy -> retained frame.

        This source still has no positive native factory. The original broker
        retains this pending duty before formatting and before admitting its
        immutable frame. No caller nonce/family/frame substitutes are accepted.
        """
        original = self._broker._owned(handler)
        family = None
        first = None
        try:
            if (type(original.operation) is not str or
                    original.operation != 'guest-owner-open' or
                    original.guest_response is not None):
                raise _RequestUnavailable()
            data = self._broker._body_json(handler)
            family = self.begin_opening(handler, data['open_nonce'])
            self.complete_opening_entropy(handler, family)
            with _OrderedAuthGates(self._auth, original):
                # Retain BEFORE formatting. An unknown assignment return
                # cannot permit a second body/entropy/frame attempt.
                duty = _GuestOpeningResponseDuty(original, family)
                if original.guest_response is not None:
                    raise _RequestUnavailable()
                original.guest_response = duty
                original.write_end = min(original.write_end, duty.end)
                self._opening_response_locked(original, duty)
            stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec='milliseconds').replace('+00:00', 'Z')
            # Display wall time never extends the retained monotonic end.
            # Pure formatting and immutable allocation stay outside gates.
            frame = format_owner_open_data(duty.family_ref, stamp)
            duty.frame, duty.phase = frame, 'prepared'
            with _OpeningResponseGates(self._auth, original, duty):
                self._opening_response_locked(original, duty)
                if (duty.phase != 'prepared' or duty.frame is not frame or
                        type(frame) is not OriginalPilotResponse):
                    raise _RequestUnavailable()
                try:
                    self._broker._admit_frame_locked(handler, original, frame)
                    duty.phase = 'admitted'
                except BaseException as error:
                    raise self._quarantine(error)
            return frame
        except BaseException as error:
            first = error
        if family is not None:
            first = self._retire_failed_opening(original, family, first)
        raise first

    def write_opening_response(self, handler, frame):
        """Reserve the same admitted opening frame, then send outside gates."""
        original = self._broker._owned(handler)
        duty = original.guest_response
        if type(duty) is not _GuestOpeningResponseDuty:
            raise _RequestUnavailable()
        first = None
        try:
            with _OpeningResponseGates(self._auth, original, duty, 'admitted'):
                self._opening_response_locked(original, duty, 'admitted')
                if (duty.phase != 'admitted' or duty.frame is not frame or
                        original.frame is not frame or
                        type(frame) is not OriginalPilotResponse):
                    raise _RequestUnavailable()
                try:
                    self._broker._reserve_write_locked(handler, original, frame)
                    duty.phase = 'write-reserved'
                except BaseException as error:
                    raise self._quarantine(error)
            duty.phase = 'write-attempted'
            self._broker._send_reserved(handler, frame)
            duty.phase = 'sent'
            return
        except BaseException as error:
            first = error
        raise self._retire_failed_opening(original, duty.family, first)

    def retire_opening_handler_duty(self, handler):
        """Finally handles an interrupted admission/write return.

        A successful local send leaves the family live; this is not remote
        delivery or ACK confirmation. Every other known duty retires its same
        family logically; cleanup never releases the family charge.
        """
        original = self._broker._owned(handler)
        duty = original.guest_response
        if duty is None:
            # The return from begin_opening may have been lost BEFORE the
            # response duty was retained. Its charged family is still strongly
            # retained in the original table with this exact original request.
            # Visit every known row rather than depending on a returned local.
            first = None
            try:
                with _OpeningCleanupGates(self._auth, original):
                    owner = self._installation
                    if (owner._original_component_tables_current() is not True or
                            owner._guest_reference_store is not self or
                            owner._original_guest_reference_store is not self or
                            owner._auth_commit is not self._auth or
                            self._auth._installation is not owner or
                            self._auth._broker is not self._broker or
                            self._auth._references is not self._references or
                            owner._references is not self._references or
                            owner._server._pilot_requests is not self._broker or
                            self._broker._server is not owner._server):
                        raise _RequestUnavailable()
                    records = owner._guest_families_by_nonce
                    if type(records) is not dict or len(records) > 4096:
                        raise _RequestUnavailable()
                    for key, family in tuple(records.items()):
                        try:
                            _family_data(owner, key, family)
                            if family._open_request is original:
                                self._retire_known_family_locked(family)
                        except BaseException as error:
                            first = _first(first, error)
                    if first is not None:
                        raise first
            except BaseException as cleanup:
                first = _first(first, cleanup)
                first = self._quarantine(first)
            if first is not None:
                raise first
            return
        if (type(duty) is not _GuestOpeningResponseDuty or
                duty.original is not original or type(duty.phase) is not str):
            raise self._quarantine(_RequestUnavailable())
        if duty.phase == 'sent':
            return
        error = self._retire_failed_opening(original, duty.family, None)
        if error is not None:
            raise error

    def _retire_known_family_locked(self, family):
        owner = self._installation
        first = None
        try:
            family._retire()
        except BaseException as error:
            first = _first(first, error)
        try:
            if family._ref is not None:
                key = (id(family._session), family._ref)
                indexed = owner._guest_families_by_ref.get(key)
                if indexed is not None and indexed is not family:
                    raise _RequestUnavailable()
                if indexed is family:
                    del owner._guest_families_by_ref[key]
        except BaseException as error:
            first = _first(first, error)
        try:
            records = owner._guest_reference_records
            if type(records) is not dict or len(records) > 4096:
                raise _RequestUnavailable()
            rows = tuple(records.items())
        except BaseException as error:
            first = _first(first, error)
            rows = ()
        for key, record in rows:
            try:
                if type(record) is not _GuestReferenceRecord:
                    raise _RequestUnavailable()
                if record._family is not family:
                    continue
                ticket = record._ticket
                if (type(key) is not tuple or len(key) != 3 or
                        type(key[0]) is not int or type(key[1]) is not str or
                        type(key[2]) is not str or
                        key != (id(family._session), record._purpose, record._key) or
                        record._session is not family._session or
                        record._principal != family._principal or
                        record._cohort is not family._cohort or
                        record._generation is not family._generation or
                        type(ticket) is not _CapacityTicket or
                        ticket is family._ticket or
                        ticket._session is not family._session or
                        ticket._principal != family._principal or
                        owner._guest_capacity._tickets.get(id(ticket)) is not ticket):
                    raise _RequestUnavailable()
                # Exact record is terminal BEFORE removal/counter settlement.
                # Every later known row is attempted after failure/control.
                record._retire()
                del records[key]
                owner._guest_capacity._release_retired_records(ticket, 1)
            except BaseException as error:
                first = _first(first, error)
        if first is not None:
            raise self._quarantine(first)
        # Keep C, assigned F history and the original one-slot family ticket.
        # Pending/unknown acquisition reservations stay charged under original
        # attempt/session cleanup. This does not settle outside native duties.

    def admit_retirement_response(self, handler):
        from freq.services.pilot_guest_retire_response import admit_retired_response
        return admit_retired_response(self, handler)

    def write_retirement_response(self, handler, frame):
        from freq.services.pilot_guest_retire_response import write_retired_response
        return write_retired_response(self, handler, frame)

    def retire_retirement_handler_duty(self, handler):
        from freq.services.pilot_guest_retire_response import retire_handler_duty
        return retire_handler_duty(self, handler)

    def admit_sources_response(self, handler):
        from freq.services.pilot_guest_sources_response import admit_sources_response
        return admit_sources_response(self, handler)

    def write_sources_response(self, handler, frame):
        from freq.services.pilot_guest_sources_response import write_sources_response
        return write_sources_response(self, handler, frame)

    def retire_sources_handler_duty(self, handler):
        from freq.services.pilot_guest_sources_response import retire_sources_handler_duty
        return retire_sources_handler_duty(self, handler)

    def prepare_profile_request(self, handler):
        from freq.services.pilot_guest_profile_preparation_caller import prepare_profile_request
        return prepare_profile_request(self, handler)

    def retire_profile_request_duty(self, handler):
        from freq.services.pilot_guest_profile_request_cleanup import retire_profile_request_duty
        return retire_profile_request_duty(self, handler)

    def tombstone_nonce(self, handler, nonce):
        """Unwired logical retirement only; no response/ACK is constructed.

        Unknown C is charged and retained as retired before returning. A later
        open sees that same record and refuses, even if F was never known.
        """
        if (not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler, require_present=True,
                                              is_https=True)):
            raise _RequestUnavailable()
        original, token, source, session, values = self._auth._capture_session(
            handler, 'guest-owner-retire')
        with _OrderedAuthGates(self._auth, original):
            cohort, generation, now = self._guard_locked(original, token, session, values)
            self._csrf_nonce_locked(handler, source, values, nonce)
            owner = self._installation
            key = (id(session), nonce)
            family = owner._guest_families_by_nonce.get(key)
            if family is None:
                return self._retain_family_locked(original, token, session, values,
                    nonce, cohort, generation, now, True)
            try:
                _family_data(owner, key, family)
                if family._session is not session or family._principal != values[0]:
                    raise _RequestUnavailable()
                self._retire_known_family_locked(family)
                return family
            except BaseException as error:
                raise self._quarantine(error)


# The proposed dispatcher joins opening and C retirement frames. The original
# inactive construction still has no actual native factory/currentness.
# Proposed retire response functions are joined separately; actual native
# parent custody/qualification, descendants, ACK and complete source-to-browser
# response ownership remain unfinished.
