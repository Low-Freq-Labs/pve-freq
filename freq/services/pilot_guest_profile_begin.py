"""Unwired original profile guest-reference consumption prefix.

Target tuple is source/node/kind/VMID DATA, never stable incarnation or native
read authority. No credential, trust, entropy, network, parser, child capacity or response is
acquired here. The return is retained private bookkeeping, never a native read
grant. A later original continuation must retain and revalidate its own exact
outside duties under the same shortened end before acquiring anything.
"""
import math
import re

from freq.api import auth
from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.cluster_references import TargetSnapshot
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _CapacityTicket, _GuestCapacity
from freq.services.guest_reference_state import (
    _GuestReferenceRecord, _Unavailable as _ReferenceUnavailable,
)
from freq.services.pilot_auth_commit import _OrderedAuthGates
from freq.services.pilot_guest_reference_store import _OpeningResponseGates
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_sources_begin import (
    _source_family_data_locked, _ExpiredSourceFamily, _CorruptSourceFamily,
    _configured_sources_data,
)


class _CorruptProfileSource(_RequestUnavailable):
    pass


class _GuestProfileBeginDuty:
    """Pure retained original context, with no acquisition or refund method."""
    __slots__ = ('original', 'token', 'session', 'values', 'family_ref',
                 'guest_ref', 'family', 'record', 'source', 'target', 'cohort',
                 'generation', 'created', 'initial_write_end', 'resource_end',
                 'end', 'phase', 'cleanup_custody', 'cleanup_selection',
                 'cleanup_capture', 'cleanup_selection_capture',
                 'cleanup_capture_error', 'cleanup_selection_error',
                 'cleanup_retirement', 'cleanup_retirement_capture',
                 'cleanup_retirement_capture_error', 'admission', 'admission_capture', 'admission_error',
                 'body_error', 'primary_error', 'guard_inspection_error', 'quarantine_inputs',
                 'quarantine_returns', 'quarantine_errors', 'quarantine_repeat_errors',
                 'record_once', 'record_once_state', 'record_once_error',
                 'registration_duty', 'registration_capture', 'registration_error',
                 'registration_guards', 'registration_guard_capture', 'registration_guard_error',
                 '_init_entered', '_init_complete', '_init_refused')

    def __init__(self, original, token, session, values, family_ref, guest_ref):
        if type(self) is not _GuestProfileBeginDuty:
            raise _RequestUnavailable()
        if hasattr(self, '_init_entered'):
            self._init_refused = True  # BEFORE even refusal allocation.
            try:
                raise _RequestUnavailable()
            except BaseException as error:
                # Same first original, never the new initializer argument.
                saved = self.original
                if saved.profile_begin_capture_error is None:
                    saved.profile_begin_capture_error = error
                raise _retain_profile_begin_failure(saved, self, error)
        self._init_entered = True
        self._init_complete = self._init_refused = False
        self.original = original  # BEFORE deadline inspection or list allocation.
        self.primary_error = None  # Never reset after a swallowed first refusal.
        try:
            if (type(original.end) is not float or not math.isfinite(original.end) or
                    type(original.write_end) is not float or
                    not math.isfinite(original.write_end)):
                raise _RequestUnavailable()
            self.original, self.token, self.session = original, token, session
            self.values, self.family_ref, self.guest_ref = values, family_ref, guest_ref
            self.family = self.record = self.source = self.target = self.cohort = self.generation = None
            self.created = self.resource_end = None
            self.initial_write_end = original.write_end
            self.end = min(original.end, self.initial_write_end)
            self.phase = 'new'
            self.cleanup_custody = self.cleanup_selection = None
            self.cleanup_capture = self.cleanup_selection_capture = 'unattempted'
            self.cleanup_capture_error = self.cleanup_selection_error = None
            self.cleanup_retirement = self.cleanup_retirement_capture_error = None
            self.cleanup_retirement_capture = 'unattempted'
            self.admission = self.admission_error = self.body_error = None
            self.admission_capture = 'unattempted'
            self.guard_inspection_error = None
            self.quarantine_inputs = [None] * 6
            self.quarantine_returns = [None] * 6
            self.quarantine_errors = [None] * 6
            self.quarantine_repeat_errors = [None] * 6
            self.record_once = self.record_once_error = None
            self.record_once_state = 'unattempted'
            self.registration_duty = self.registration_error = None
            self.registration_capture = 'unattempted'
            self.registration_guards = self.registration_guard_error = None
            self.registration_guard_capture = 'unattempted'
            self._init_complete = True
        except BaseException as error:
            # A partial holder may not yet have primary_error or any list.
            if type(original) is _OriginalRequest and original.profile_begin_capture_error is None:
                original.profile_begin_capture_error = error
            raise _retain_profile_begin_failure(original, self, error)


def _retain_profile_begin_failure(original, begin, error):
    """Fixed raw/selected storage only; no outside recorder or cleanup call.

    First received raw remains distinct from the selected profile winner.
    No partially initialized field is assumed to exist. Caller retains the
    original frame identities; mutable current views never choose another duty.
    """
    if type(original) is _OriginalRequest:
        if original.profile_begin_capture_error is None:
            original.profile_begin_capture_error = error
    first = getattr(begin, 'primary_error', None) if type(begin) is _GuestProfileBeginDuty else None
    if first is not None and not issubclass(type(first), BaseException):
        first = None
    if error is not None and issubclass(type(error), BaseException):
        if first is None or (issubclass(type(first), Exception) and (
                not issubclass(type(error), Exception) or
                not issubclass(type(first), MemoryError) and issubclass(type(error), MemoryError))):
            first = error
    if type(begin) is _GuestProfileBeginDuty:
        begin.primary_error = first
    return first


def _check_profile_begin_initialization(original, begin):
    """Positive continuation restriction; never physical or auth authority."""
    if (type(original) is _OriginalRequest and type(begin) is _GuestProfileBeginDuty
            and original.profile_begin_original is begin
            and original.profile_begin_capture == 'constructor-returned'
            and type(original.profile_begin_capture) is str
            and original.profile_begin_capture_error is None
            and getattr(begin, 'original', None) is original
            and getattr(begin, '_init_entered', None) is True
            and getattr(begin, '_init_complete', None) is True
            and getattr(begin, '_init_refused', None) is False):
        phase = begin.phase
        view = original.guest_response
        if type(phase) is str and phase in ('new', 'consume-pending', 'spent'):
            if view is begin:
                return
        elif type(phase) is str and phase == 'registration-attempted':
            # Only the retained constructor-returned acquisition can be the
            # normal view after handoff. No foreign view is followed/repaired.
            from freq.services.pilot_guest_profile_registration import _ProfileAcquisitionDuty
            acquired = begin.registration_duty
            if (type(acquired) is _ProfileAcquisitionDuty and view is acquired
                    and type(begin.registration_capture) is str
                    and begin.registration_capture == 'constructor-returned'
                    and begin.registration_error is None
                    and acquired.original is original and acquired.begin is begin):
                return
    # Failed/partial continuation surfaces retained identity before allocation.
    selected = getattr(begin, 'primary_error', None) if type(begin) is _GuestProfileBeginDuty else None
    if selected is not None and issubclass(type(selected), BaseException):
        raise selected
    raw = original.profile_begin_capture_error if type(original) is _OriginalRequest else None
    if raw is not None and issubclass(type(raw), BaseException):
        raise raw
    error = _RequestUnavailable()
    raise _retain_profile_begin_failure(original, begin, error)


def _completed_profile_begin_cleanup_data(original):
    """Canonical completed storage for owed cleanup, not positive admission.

    Refused/body-failed completed storage still owns known duties. No fresh
    deadline/currentness check may skip them. A partial blank is never passed
    to a helper which reads complete-only fields. Foreign current views are
    neither followed nor repaired by this saved-root lookup.
    """
    if type(original) is not _OriginalRequest:
        raise _RequestUnavailable()
    begin = original.profile_begin_original
    if (type(begin) is not _GuestProfileBeginDuty
            or getattr(begin, 'original', None) is not original
            or getattr(begin, '_init_entered', None) is not True
            or getattr(begin, '_init_complete', None) is not True
            or type(original.profile_begin_capture) is not str
            or original.profile_begin_capture != 'constructor-returned'):
        raise _RequestUnavailable()
    return begin


class _ProfileBeginGates(_OpeningResponseGates):
    def __init__(self, transaction, original, duty, phase='ready'):
        _check_profile_begin_initialization(original, duty)
        _OrderedAuthGates.__init__(self, transaction, original, phase)
        _check_profile_begin_initialization(original, duty)
        if (type(duty) is not _GuestProfileBeginDuty or
                duty.original is not original or
                any(type(value) is not float or not math.isfinite(value)
                    for value in (duty.end, original.end, original.write_end))):
            raise _RequestUnavailable()
        self._end = min(duty.end, original.end, original.write_end)


def _profile_guest_data_locked(owner, family, session, principal, reference,
                                   cohort, generation, now):
    """Read one purpose/session/family DATA row; authenticates nobody.

    Original caller must already hold its same writer and positive native,
    auth, session, family, cohort and recipient guards. Missing or other-family
    rights are ordinary refusals; a malformed selected ledger row is corrupt.
    No sweep, other-purpose fallback, reference consumption or native IO.
    """
    if (type(session) is not dict or type(principal) is not str or not principal or
            type(reference) is not str or re.fullmatch('[0-9a-f]{64}', reference) is None or
            type(now) is not float or not math.isfinite(now) or
            type(family) is not _GuestFamilyRecord or
            family._session is not session or family._principal != principal or
            family._cohort is not cohort or family._generation is not generation or
            family._state != 'live' or family._sources_spent is not True):
        raise _RequestUnavailable()
    rows, capacity = owner._guest_reference_records, owner._guest_capacity
    if (type(rows) is not dict or len(rows) > 4096 or
            type(capacity) is not _GuestCapacity):
        raise _CorruptProfileSource()
    key = (id(session), 'guest', reference)
    if key not in rows:
        raise _RequestUnavailable()
    record = rows[key]
    if type(record) is not _GuestReferenceRecord:
        raise _CorruptProfileSource()
    # A genuine row belonging to another live F must never be consumed as the
    # requested F. No corruption or attempt is inferred from that ordinary mix.
    if type(record._family) is not _GuestFamilyRecord:
        raise _CorruptProfileSource()
    if record._family is not family:
        raise _RequestUnavailable()
    ticket = record._ticket
    if (type(record._key) is not str or record._key != reference or
            type(record._purpose) is not str or record._purpose != 'guest' or
            record._session is not session or record._principal != principal or
            record._cohort is not cohort or record._generation is not generation or
            type(record._target) is not tuple or len(record._target) != 3 or
            type(record._target[0]) is not str or
            re.fullmatch('[A-Za-z0-9][A-Za-z0-9.-]{0,63}', record._target[0]) is None or
            type(record._target[1]) is not str or record._target[1] not in ('qemu', 'lxc') or
            type(record._target[2]) is not int or not 100 <= record._target[2] <= 999999999 or
            type(record._spent) is not bool or type(record._retired) is not bool or
            type(ticket) is not _CapacityTicket or ticket._state != 'committed' or
            ticket._session is not session or ticket._principal != principal or
            type(ticket._remaining) is not int or ticket._remaining < 1 or
            capacity._tickets.get(id(ticket)) is not ticket or
            any(type(value) is not float or not math.isfinite(value)
                for value in (record._created, record._expires, record._last_clock)) or
            not family._created <= record._created < record._expires <=
                min(record._created + 30.0, family._expires) or
            not record._created <= record._last_clock < record._expires):
        raise _CorruptProfileSource()
    try:
        capacity._check()
        configured = _configured_sources_data(cohort, generation)
    except MemoryError:
        raise
    except Exception:
        raise _CorruptProfileSource() from None
    if ticket._remaining > 256:
        raise _CorruptProfileSource()
    source = record._source
    if (type(source) is not tuple or len(source) != 2 or
            type(source[1]) is not TargetSnapshot or
            source[1].configuration_revision is not generation or
            not any(row is source for row in configured)):
        raise _CorruptProfileSource()
    if record._spent or record._retired:
        raise _RequestUnavailable()
    return record


def _consume_profile_guest_data(record, now):
    """Pure irreversible state operation, not an original admission grant."""
    if (type(record) is not _GuestReferenceRecord or
            type(record._purpose) is not str or record._purpose != 'guest'):
        raise _RequestUnavailable()
    try:
        record._consume_once(now)
    except _ReferenceUnavailable:
        # Exact helper spends before stale/backward-clock refusal. No revival.
        raise _RequestUnavailable() from None


def begin_profile(store, handler):
    """One retained original begin; initialization is not positive authority."""
    owner = _owned_store(store)
    original = store._broker._owned(handler)
    if type(original) is not _OriginalRequest:
        raise _RequestUnavailable()
    if (type(original.profile_begin_capture) is not str
            or original.profile_begin_capture != 'unattempted'
            or original.profile_begin_original is not None
            or original.profile_begin_capture_error is not None):
        previous = original.profile_begin_original
        if type(previous) is _GuestProfileBeginDuty:
            previous._init_refused = True
        raw = original.profile_begin_capture_error
        selected = getattr(previous, 'primary_error', None) if type(previous) is _GuestProfileBeginDuty else None
        if selected is not None and issubclass(type(selected), BaseException):
            raise selected
        if raw is not None and issubclass(type(raw), BaseException):
            raise raw
        try:
            raise _RequestUnavailable()
        except BaseException as error:
            if original.profile_begin_capture_error is None:
                original.profile_begin_capture_error = error
            if type(previous) is _GuestProfileBeginDuty:
                previous.primary_error = error
            raise
    if (not auth._cluster_pilot_direct_tls(handler) or
            not auth.same_origin_or_absent(handler, require_present=True, is_https=True) or
            type(original.operation) is not str or
            original.operation != 'guest-owner-profile' or
            original.guest_response is not None):
        raise _RequestUnavailable()
    data = store._broker._body_json(handler)
    captured, token, source, session, values = store._auth._capture_session(
        handler, 'guest-owner-profile')
    if captured is not original:
        raise _RequestUnavailable()
    original.profile_begin_capture = 'constructor-pending'
    original.profile_custody_started = True
    duty = None
    try:
        try:
            duty = _GuestProfileBeginDuty.__new__(_GuestProfileBeginDuty)
            original.profile_begin_original = duty  # BEFORE either payload index.
            _GuestProfileBeginDuty.__init__(duty, original, token, session, values,
                data['owner_ref'], data['guest_ref'])
            # Direct final correspondence/publication: no project helper here.
            if (original.profile_begin_original is not duty
                    or original.profile_begin_capture != 'constructor-pending'
                    or type(original.profile_begin_capture) is not str
                    or original.profile_begin_capture_error is not None
                    or original.guest_response is not None
                    or getattr(duty, 'original', None) is not original
                    or getattr(duty, '_init_entered', None) is not True
                    or getattr(duty, '_init_complete', None) is not True
                    or getattr(duty, '_init_refused', None) is not False):
                raise _RequestUnavailable()
            original.guest_response = duty
            original.profile_begin_capture = 'constructor-returned'
        except BaseException as error:
            if original.profile_begin_capture_error is None:
                original.profile_begin_capture_error = error
            if type(duty) is _GuestProfileBeginDuty and getattr(duty, 'primary_error', None) is None:
                duty.primary_error = original.profile_begin_capture_error
            raise _retain_profile_begin_failure(original, duty, error)
        try:
            from freq.services.pilot_guest_profile_begin_capture import (
                _capture_begin_custody_data, _capture_begin_selection_data,
            )
            from freq.services.pilot_guest_profile_begin_admission import (
                _ProfileBeginAdmissionGates, _first_begin_error,
                _quarantine_begin_error, _begin_guard_uncertain_data,
            )
        except BaseException as error:
            _retain_profile_begin_failure(original, duty, error)
            raise
        try:
            duty.admission_capture = 'constructor-pending'
            try:
                duty.admission = _ProfileBeginAdmissionGates.__new__(_ProfileBeginAdmissionGates)
                _ProfileBeginAdmissionGates.__init__(duty.admission, store._auth, original, duty)
                duty.admission_capture = 'constructor-returned'
            except BaseException as error:
                duty.admission_error = error
                raise
            with duty.admission:
                _check_profile_begin_initialization(original, duty)
                cohort, generation, now = store._guard_locked(original, token, session, values)
                _check_profile_begin_initialization(original, duty)
                store._csrf_nonce_locked(handler, source, values, duty.family_ref)
                _check_profile_begin_initialization(original, duty)
                if original.guest_response is not duty or not now < duty.end:
                    raise _RequestUnavailable()
                try:
                    _capture_begin_custody_data(store, handler, duty)
                    _check_profile_begin_initialization(original, duty)
                except BaseException as error:
                    # Unknown/failed capture never resumes through a fresh request.
                    # The same retained private holder/error remains with this begin.
                    _retain_profile_begin_failure(original, duty, error)
                    raise _quarantine_begin_error(store, duty, error, 0)
                try:
                    family = _source_family_data_locked(owner, session, values[0],
                        duty.family_ref, cohort, generation, now)
                except _ExpiredSourceFamily as expired:
                    if original.profile_begin_capture_error is None:
                        original.profile_begin_capture_error = expired
                    duty.family = expired.family
                    store._retire_known_family_locked(expired.family)
                    raise _RequestUnavailable() from None
                except _CorruptSourceFamily as error:
                    _retain_profile_begin_failure(original, duty, error)
                    raise _quarantine_begin_error(store, duty, error, 1)
                _check_profile_begin_initialization(original, duty)
                duty.family, duty.cohort, duty.generation = family, cohort, generation
                try:
                    record = _profile_guest_data_locked(owner, family, session,
                        values[0], duty.guest_ref, cohort, generation, now)
                except _CorruptProfileSource as error:
                    _retain_profile_begin_failure(original, duty, error)
                    raise _quarantine_begin_error(store, duty, error, 2)
                _check_profile_begin_initialization(original, duty)
                duty.record, duty.source, duty.target = record, record._source, record._target  # Before consume.
                duty.created, duty.resource_end = now, now + 10.0
                duty.end = min(duty.end, duty.resource_end, family._expires, record._expires)
                original.write_end = min(original.write_end, duty.end)
                try:
                    _capture_begin_selection_data(store, handler, duty)
                    _check_profile_begin_initialization(original, duty)
                except BaseException as error:
                    _retain_profile_begin_failure(original, duty, error)
                    raise _quarantine_begin_error(store, duty, error, 3)
                try:
                    _check_profile_begin_initialization(original, duty)
                    duty.phase = 'consume-pending'
                    _consume_profile_guest_data(record, now)
                    duty.phase = 'spent'
                    _check_profile_begin_initialization(original, duty)
                except _RequestUnavailable:
                    duty.phase = 'consumed-refused'
                    raise
                except BaseException as error:
                    # Lost/unknown consumption return is never unspent or retried.
                    _retain_profile_begin_failure(original, duty, error)
                    raise _quarantine_begin_error(store, duty, error, 4)
                if not now < duty.end:
                    raise _RequestUnavailable()
            _check_profile_begin_initialization(original, duty)
        except BaseException as error:
            _retain_profile_begin_failure(original, duty, error)
            duty.primary_error = _first_begin_error(duty.primary_error, error)
            uncertain = False
            try:
                if duty.admission_capture == 'constructor-returned':
                    uncertain = _begin_guard_uncertain_data(duty.admission)
            except BaseException as later:
                duty.guard_inspection_error = later
                _retain_profile_begin_failure(original, duty, later)
                duty.primary_error = _first_begin_error(duty.primary_error, later)
                uncertain = True
            if uncertain:
                duty.primary_error = _quarantine_begin_error(store, duty, duty.primary_error, 5)
            raise duty.primary_error
        return duty
    finally:
        if duty is not None:
            original.profile_begin_original = duty


# No store delegation, dispatcher branch, original native factory or response.
