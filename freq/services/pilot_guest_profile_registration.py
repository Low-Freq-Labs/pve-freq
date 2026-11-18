"""Unwired original profile registration prefix, with no acquiring effect.

Three fixed uninitialized section placeholders retain future outside duties.
They hold no native object and issue no credential/trust/aggregate allowance.
All actual original native/physical/result and recipient work remains owed.
"""
import math
import threading

from freq.api import auth
from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_profile_begin import (
    _GuestProfileBeginDuty, _ProfileBeginGates, _CorruptProfileSource,
    _check_profile_begin_initialization, _retain_profile_begin_failure,
)
from freq.services.pilot_guest_profile_consumed import consumed_profile_guest_data_locked
from freq.services.pilot_guest_profile_subreads_data import _GuestProfileSubreadsData
from freq.services.pilot_guest_profile_exchange import _ProfileSectionExchange
from freq.services.node_read_tls import OriginalSocket
from freq.services.pilot_guest_sources_begin import (
    _source_family_data_locked, _ExpiredSourceFamily, _CorruptSourceFamily,
)


_SECTIONS = ('status', 'configured_network', 'guest_network')


class _ProfileSectionSlot:
    """Retained slot storage only; pending fields do not grant native authority."""
    __slots__ = ('section', 'attempt', 'phase', 'saved_attempt', 'construction',
                 'execution', 'cleanup', 'result', 'construction_error',
                 'run_error', 'cleanup_error')

    def __init__(self, section):
        if type(section) is not str or section not in _SECTIONS:
            raise _RequestUnavailable()
        self.section, self.attempt, self.phase = section, None, 'uninitialized'
        self.saved_attempt = self.result = None
        self.construction, self.execution, self.cleanup = 'unattempted', 'unattempted', 'unattempted'
        self.construction_error = self.run_error = self.cleanup_error = None


class _ProfileAcquisitionDuty:
    __slots__ = ('original', 'begin', 'plan', 'end', 'last_clock',
                 'credential_uid', 'configured_token', 'component_tables',
                 'inventory_tables', 'profile_tables', 'slots', 'custody', 'phase',
                 'plan_capture', 'plan_error', 'custody_capture', 'custody_error',
                 'registration_state', 'registration_return', 'registration_error',
                 'quarantine_inputs', 'quarantine_returns', 'quarantine_errors',
                 'quarantine_repeat_errors', 'quarantine_primary',
                 'preparation_quarantine_inputs', 'preparation_quarantine_returns',
                 'preparation_quarantine_errors', 'preparation_quarantine_repeat_errors',
                 'preparation_quarantine_primary')

    def __init__(self, original, begin):
        _check_profile_begin_initialization(original, begin)
        if (type(original) is not _OriginalRequest or
                type(begin) is not _GuestProfileBeginDuty or begin.original is not original or
                type(begin.end) is not float or not math.isfinite(begin.end)):
            raise _RequestUnavailable()
        self.original, self.begin, self.plan = original, begin, None
        self.plan_capture = self.custody_capture = 'unattempted'
        self.plan_error = self.custody_error = None
        self.registration_state = 'unattempted'
        self.registration_return = self.registration_error = None
        self.quarantine_inputs = [None] * 4
        self.quarantine_returns = [None] * 4
        self.quarantine_errors = [None] * 4
        self.quarantine_repeat_errors = [None] * 4
        self.quarantine_primary = None
        self.preparation_quarantine_inputs = [None] * 3
        self.preparation_quarantine_returns = [None] * 3
        self.preparation_quarantine_errors = [None] * 3
        self.preparation_quarantine_repeat_errors = [None] * 3
        self.preparation_quarantine_primary = None
        self.end, self.last_clock = begin.end, None
        self.credential_uid = self.configured_token = None
        self.component_tables = self.inventory_tables = self.profile_tables = None
        self.slots = tuple(_ProfileSectionSlot(section) for section in _SECTIONS)
        self.custody, self.phase = None, 'new'


class _ProfileRetirementCustody:
    """Immutable captured identities, never a positive admission/close proof."""
    __slots__ = ('items',)

    def __init__(self, store, original, handler, duty):
        owner, broker = store._installation, store._broker
        refs = store._references
        locks = (owner._gate, auth._auth_lock, refs._lock, broker._gate)
        object.__setattr__(self, 'items', (
            store, owner, store._auth, broker, refs, owner._server, broker._requests,
            original, handler, original.socket, original.thread,
            duty.component_tables, owner._guest_capacity, locks,
            duty, duty.begin, duty.begin.record, duty.begin.family,
            duty.begin.source, duty.begin.target, duty.begin.cohort, duty.begin.generation,
            duty.inventory_tables, duty.profile_tables,
            duty.profile_tables[0], duty.profile_tables[1], duty.slots,
            duty.configured_token, duty.credential_uid, duty.end, duty.plan))

    def __setattr__(self, name, value):
        raise TypeError('Original profile retirement custody is immutable')

    def __delattr__(self, name):
        raise TypeError('Original profile retirement custody is immutable')


def _unstarted_profile_slots_data(duty):
    if (type(duty) is not _ProfileAcquisitionDuty or type(duty.slots) is not tuple or
            len(duty.slots) != 3 or
            any(type(slot) is not _ProfileSectionSlot or
                type(slot.section) is not str or slot.section != _SECTIONS[index] or
                any(type(value) is not str for value in
                    (slot.phase, slot.construction, slot.execution, slot.cleanup)) or
                slot.attempt is not None or slot.phase != 'uninitialized' or
                slot.saved_attempt is not None or slot.result is not None or
                slot.construction != 'unattempted' or slot.execution != 'unattempted' or
                slot.cleanup != 'unattempted' or slot.construction_error is not None or
                slot.run_error is not None or slot.cleanup_error is not None
                for index, slot in enumerate(duty.slots)) or
            any(duty.slots[i] is duty.slots[j] for i in range(3) for j in range(i))):
        raise _CorruptProfileSource()


def _known_profile_slots_data(duty):
    """Stable retained slot DATA; never native/result/currentness authority.

    Unknown construction/run/close refuses positive validation. Same known
    prepared or returned private state can be recognized without retrying it.
    Terminal count rows may retain ordinary failure; they are not selected
    active profiles. Positive predicates MUST NEVER bar identity-only cleanup.
    All local returned flags still leave outside successful-return/physical
    duties with the original job. No map, clock, result or deadline is changed.
    """
    if type(duty) is not _ProfileAcquisitionDuty:
        raise _CorruptProfileSource()
    try:
        slots = duty.slots
        if (type(slots) is not tuple or len(slots) != 3 or
                type(duty.plan) is not _GuestProfileSubreadsData or
                type(duty.custody) is not _ProfileRetirementCustody or
                type(duty.custody.items) is not tuple or len(duty.custody.items) != 31 or
                duty.custody.items[14] is not duty or duty.custody.items[26] is not slots or
                duty.custody.items[30] is not duty.plan or
                type(duty.end) is not float or not math.isfinite(duty.end) or
                type(duty.custody.items[29]) is not float or duty.custody.items[29] != duty.end or
                type(duty.original) is not _OriginalRequest or type(duty.phase) is not str or
                duty.phase not in ('registered', 'retired')):
            raise _CorruptProfileSource()
        retired = duty.phase == 'retired'
        for index, slot in enumerate(slots):
            if (type(slot) is not _ProfileSectionSlot or type(slot.section) is not str or
                    slot.section != _SECTIONS[index] or any(slot is prior for prior in slots[:index]) or
                    any(type(value) is not str for value in
                        (slot.phase, slot.construction, slot.execution, slot.cleanup)) or
                    slot.construction_error is not None or slot.run_error is not None or
                    slot.cleanup_error is not None):
                raise _CorruptProfileSource()
            saved = slot.saved_attempt
            if slot.construction == 'unattempted':
                if (saved is not None or slot.attempt is not None or slot.result is not None or
                        slot.execution != 'unattempted' or not (
                            slot.phase == 'uninitialized' and slot.cleanup == 'unattempted' or
                            retired and slot.phase == 'retired-local' and slot.cleanup == 'returned-no-attempt')):
                    raise _CorruptProfileSource()
                continue
            if (slot.construction != 'constructor-returned' or type(saved) is not _ProfileSectionExchange or
                    type(duty.plan.target) is not tuple or len(duty.plan.target) != 3 or
                    type(duty.plan.target[1]) is not str or duty.plan.target[1] != 'qemu' or
                    type(duty.plan.reads) is not tuple or len(duty.plan.reads) != 3 or
                    type(duty.plan.unsupported_sections) is not tuple or duty.plan.unsupported_sections != () or
                    slot.attempt is not saved or saved._plan is not duty.plan or
                    type(saved._section) is not str or saved._section != slot.section or
                    type(saved._end) is not float or saved._end != duty.end or
                    saved._thread is not duty.original.thread or
                    any(type(value) is not str for value in (saved._phase, saved._operation, saved._cleanup)) or
                    type(saved._original_socket) is not OriginalSocket or
                    saved._socket_owner is not saved._original_socket):
                raise _CorruptProfileSource()
            socket_owner = saved._original_socket
            if (type(socket_owner._acquisition) is not str or type(socket_owner._closure) is not str):
                raise _CorruptProfileSource()
            if slot.execution == 'unattempted':
                if slot.result is not None or saved._result is not None:
                    raise _CorruptProfileSource()
                if retired and slot.phase == 'retired-local' and slot.cleanup == 'close-returned':
                    if (saved._phase != 'retired' or saved._cleanup != 'returned' or
                            socket_owner._acquisition != 'unstarted' or
                            socket_owner._closure != 'returned-no-acquisition' or
                            socket_owner._spent is not True or socket_owner._socket is not None):
                        raise _CorruptProfileSource()
                elif (retired or slot.phase != 'prepared' or slot.cleanup != 'unattempted' or
                        saved._phase != 'new' or saved._operation != 'constructor-returned' or
                        saved._cleanup != 'unattempted' or socket_owner._spent is not False or
                        socket_owner._acquisition != 'unstarted' or socket_owner._closure != 'unattempted' or
                        socket_owner._socket is not None):
                    raise _CorruptProfileSource()
                if (saved._failure is not None or saved._body_failure is not None or
                        saved._cleanup_failure is not None or saved._late_failure is not None):
                    raise _CorruptProfileSource()
                continue
            if (slot.execution != 'run-returned' or saved._cleanup != 'returned' or
                    socket_owner._spent is not True or socket_owner._closure not in
                    ('returned', 'returned-no-acquisition') or
                    socket_owner._closure == 'returned' and (
                        socket_owner._acquisition != 'owned' or socket_owner._socket is None) or
                    socket_owner._closure == 'returned-no-acquisition' and (
                        socket_owner._acquisition != 'unstarted' or socket_owner._socket is not None)):
                raise _CorruptProfileSource()
            if retired:
                if slot.phase != 'retired-local' or slot.cleanup != 'close-returned':
                    raise _CorruptProfileSource()
            elif slot.phase != 'returned-private' or slot.cleanup != 'unattempted':
                raise _CorruptProfileSource()
            if slot.result is None:
                # Count-only retired ordinary failure, never active availability.
                if (not retired or saved._phase != 'failed' or not isinstance(saved._failure, Exception) or
                        isinstance(saved._failure, MemoryError) or any(
                            error is not None and (not isinstance(error, Exception) or isinstance(error, MemoryError))
                            for error in (saved._body_failure, saved._cleanup_failure, saved._late_failure))):
                    raise _CorruptProfileSource()
            elif (type(slot.result) is not bytes or not 1 <= len(slot.result) <= 262144 or
                    slot.result is not saved._result or saved._phase != 'prepared' or
                    socket_owner._closure != 'returned' or socket_owner._acquisition != 'owned' or
                    saved._operation != 'finish-returned' or saved._failure is not None or
                    saved._body_failure is not None or saved._cleanup_failure is not None or
                    saved._late_failure is not None):
                raise _CorruptProfileSource()
    except AttributeError:
        raise _CorruptProfileSource() from None


def _profile_registration_tables_data(owner, duty):
    """Positive bounded typed DATA only; MUST NOT be a cleanup barrier."""
    if type(duty) is not _ProfileAcquisitionDuty:
        raise _CorruptProfileSource()
    components, inventory, tables = duty.component_tables, duty.inventory_tables, duty.profile_tables
    if (type(components) is not tuple or len(components) != 9 or
            type(inventory) is not tuple or len(inventory) != 2 or
            type(tables) is not tuple or len(tables) != 2 or
            any(type(table) is not dict for table in components + inventory + tables) or
            any(len(table) > 64 for table in tables) or
            any(table is prior for index, table in enumerate(components + inventory + tables)
                for prior in (components + inventory + tables)[:index]) or
            owner._original_component_tables is not components or
            owner._original_guest_inventory_tables is not inventory or
            owner._original_guest_profile_tables is not tables or
            owner._guest_profile_attempts is not tables[0] or
            owner._native_guest_profile_attempts is not tables[1]):
        raise _CorruptProfileSource()
    active, native = tables
    for original, retained in native.items():
        if (type(original) is not _OriginalRequest or
                type(retained) is not _ProfileAcquisitionDuty or retained.original is not original or
                type(retained.begin) is not _GuestProfileBeginDuty or
                retained.begin.original is not original or
                retained.component_tables is not components or
                retained.inventory_tables is not inventory or retained.profile_tables is not tables or
                type(retained.plan) is not _GuestProfileSubreadsData or
                retained.plan.begin is not retained.begin or retained.plan.original is not original or
                type(retained.custody) is not _ProfileRetirementCustody or
                type(retained.custody.items) is not tuple or len(retained.custody.items) != 31 or
                retained.phase not in ('registered', 'retired')):
            raise _CorruptProfileSource()
        _known_profile_slots_data(retained)
    for original, retained in active.items():
        if original not in native or native[original] is not retained:
            raise _CorruptProfileSource()
    return active, native


def _register_profile_duty_data(owner, duty):
    """Retain SAME duty in permanent namespace first; no acquiring operation.

    Known full returns False without insertion. Unknown insertion return stays
    pending and must not be repaired/retried or count as physical allowance.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or duty.phase != 'captured' or
            type(duty.original) is not _OriginalRequest or
            type(duty.plan) is not _GuestProfileSubreadsData or
            duty.plan.begin is not duty.begin or duty.plan.original is not duty.original or
            type(duty.custody) is not _ProfileRetirementCustody):
        raise _CorruptProfileSource()
    _unstarted_profile_slots_data(duty)
    active, native = _profile_registration_tables_data(owner, duty)
    if duty.original in active or duty.original in native:
        raise _CorruptProfileSource()
    if len(active) >= 64 or len(native) >= 64:
        return False
    duty.phase = 'registration-pending'
    native[duty.original] = duty
    active[duty.original] = duty
    duty.phase = 'registered'
    return True


def _retain_profile_registration_duty_data(begin, original):
    """Retain pure partial constructor; no native, guard or admission grant.

    Same original caller already owns this exact canonical begin. A successful
    local constructor return never licenses registration/read/native work. Any
    pending/failed/returned capture is one attempted original path, not a retry.
    Guard/plan/custody/index/body error ledgers are separately unfinished.
    """
    _check_profile_begin_initialization(original, begin)
    if (type(begin) is not _GuestProfileBeginDuty or
            type(original) is not _OriginalRequest or begin.original is not original):
        raise _RequestUnavailable()
    if (type(begin.registration_capture) is not str or
            begin.registration_capture != 'unattempted' or
            begin.registration_duty is not None or begin.registration_error is not None):
        if isinstance(begin.registration_error, BaseException):
            raise begin.registration_error
        raise _RequestUnavailable()
    begin.registration_capture = 'constructor-pending'
    try:
        begin.registration_duty = _ProfileAcquisitionDuty.__new__(_ProfileAcquisitionDuty)
        _ProfileAcquisitionDuty.__init__(begin.registration_duty, original, begin)
        begin.registration_capture = 'constructor-returned'
    except BaseException as error:
        begin.registration_error = error
        raise
    _check_profile_begin_initialization(original, begin)
    return begin.registration_duty


def _registration_stage_duty_data(duty):
    """Recognize this retained pure duty, never grant original/native admission."""
    if type(duty) is not _ProfileAcquisitionDuty:
        raise _RequestUnavailable()
    _check_profile_begin_initialization(getattr(duty, 'original', None), getattr(duty, 'begin', None))
    if (type(duty) is not _ProfileAcquisitionDuty or
            type(duty.original) is not _OriginalRequest or
            type(duty.begin) is not _GuestProfileBeginDuty or
            duty.begin.original is not duty.original or
            duty.begin.registration_duty is not duty or
            duty.begin.registration_capture != 'constructor-returned' or
            duty.begin.registration_error is not None):
        raise _RequestUnavailable()
    _check_profile_begin_initialization(duty.original, duty.begin)
    return duty.begin


def _retain_profile_plan_data(owner, duty, now):
    begin = _registration_stage_duty_data(duty)
    if duty.original.guest_response is not begin:
        raise _RequestUnavailable()
    if (type(duty.plan_capture) is not str or duty.plan_capture != 'unattempted' or
            duty.plan is not None or duty.plan_error is not None):
        if isinstance(duty.plan_error, BaseException):
            raise duty.plan_error
        raise _RequestUnavailable()
    duty.plan_capture = 'constructor-pending'
    try:
        duty.plan = _GuestProfileSubreadsData.__new__(_GuestProfileSubreadsData)
        _GuestProfileSubreadsData.__init__(duty.plan, owner, begin, now)
        duty.plan_capture = 'constructor-returned'
    except BaseException as error:
        duty.plan_error = error
        raise
    return duty.plan


def _retain_profile_custody_data(store, original, handler, duty):
    _registration_stage_duty_data(duty)
    if original is not duty.original or original.guest_response is not duty:
        raise _RequestUnavailable()
    if (type(duty.custody_capture) is not str or duty.custody_capture != 'unattempted' or
            duty.custody is not None or duty.custody_error is not None):
        if isinstance(duty.custody_error, BaseException):
            raise duty.custody_error
        raise _RequestUnavailable()
    duty.custody_capture = 'constructor-pending'
    try:
        duty.custody = _ProfileRetirementCustody.__new__(_ProfileRetirementCustody)
        _ProfileRetirementCustody.__init__(duty.custody, store, original, handler, duty)
        duty.custody_capture = 'constructor-returned'
    except BaseException as error:
        duty.custody_error = error
        raise
    return duty.custody


def _retain_profile_registration_call_data(owner, duty):
    _registration_stage_duty_data(duty)
    if duty.original.guest_response is not duty:
        raise _RequestUnavailable()
    if (type(duty.registration_state) is not str or duty.registration_state != 'unattempted' or
            duty.registration_return is not None or duty.registration_error is not None):
        if isinstance(duty.registration_error, BaseException):
            raise duty.registration_error
        raise _RequestUnavailable()
    duty.registration_state = 'call-pending'  # BEFORE inner permanent/active insert.
    try:
        duty.registration_return = _register_profile_duty_data(owner, duty)
        if type(duty.registration_return) is not bool:
            raise _CorruptProfileSource()
        duty.registration_state = 'call-returned'
    except BaseException as error:
        duty.registration_error = error
        raise
    return duty.registration_return


def _quarantine_profile_registration_error(store, duty, error, index):
    """Four fixed original body sites; retain actual input/return/raised refs.

    This serialized bounded ledger observes only caught/returned failures.
    One first repeated input per site is retained, with no repeat store call.
    Further distinct repeats are unsupported; refuse using retained primary.
    Store-internal failures and physical/native settlement remain independent.
    """
    if (type(duty) is not _ProfileAcquisitionDuty or type(index) is not int or
            not 0 <= index < 4 or not issubclass(type(error), BaseException)):
        raise _RequestUnavailable()
    if duty.original.profile_begin_capture_error is None:
        duty.original.profile_begin_capture_error = error
    _retain_profile_begin_failure(duty.original, duty.begin, error)
    from freq.services.pilot_guest_profile_begin_admission import _first_begin_error
    if (duty.quarantine_inputs[index] is not None or
            duty.quarantine_returns[index] is not None or
            duty.quarantine_errors[index] is not None):
        previous = duty.quarantine_repeat_errors[index]
        unsupported = previous is not None and previous is not error
        if previous is None:
            duty.quarantine_repeat_errors[index] = error
        selected = duty.quarantine_primary
        for later in (duty.quarantine_inputs[index], duty.quarantine_returns[index],
                      duty.quarantine_errors[index], duty.quarantine_repeat_errors[index]):
            if issubclass(type(later), BaseException):
                selected = _first_begin_error(selected, later)
        duty.quarantine_primary = selected
        if unsupported:
            raise selected
        return selected
    duty.quarantine_inputs[index] = error  # BEFORE invoking existing quarantine.
    duty.quarantine_primary = _first_begin_error(duty.quarantine_primary, error)
    try:
        returned = store._quarantine(error)
        duty.quarantine_returns[index] = returned
        selected = returned
        if not issubclass(type(selected), BaseException):
            selected = _RequestUnavailable()
            duty.quarantine_errors[index] = selected
        duty.quarantine_primary = _first_begin_error(duty.quarantine_primary, selected)
    except BaseException as later:
        duty.quarantine_errors[index] = later
        duty.quarantine_primary = _first_begin_error(duty.quarantine_primary, later)
    return duty.quarantine_primary


def register_profile_acquisition(store, handler):
    """One original registration only; native/currentness gates remain owed.

    Pure fixed plan construction occurs while the original request still
    retains the spent begin duty required by its canonical DATA constructor.
    It has no acquiring API or externally owned resource. Before any table
    mutation the SAME original retains the new pending duty and immutable
    cleanup snapshot. No caller-supplied plan, body, attempt or callback enters.
    """
    owner = _owned_store(store)
    original = store._broker._owned(handler)
    begin = original.profile_begin_original
    try:
        _check_profile_begin_initialization(original, begin)
        if (original.guest_response is not begin or type(begin) is not _GuestProfileBeginDuty or begin.original is not original or
                begin.phase != 'spent' or type(original.operation) is not str or
                original.operation != 'guest-owner-profile' or original.body_taken is not True or
                not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler, require_present=True, is_https=True)):
            raise _RequestUnavailable()
        duty = _retain_profile_registration_duty_data(begin, original)
        from freq.services.pilot_guest_profile_registration_guards import (
            _retain_profile_registration_guards_data, _finish_profile_registration_guard_error,
        )
        guards = _retain_profile_registration_guards_data(store._auth, original, begin)
        try:
            with guards:
                _check_profile_begin_initialization(original, begin)
                cohort, generation, now = store._guard_locked(original, begin.token, begin.session, begin.values)
                _check_profile_begin_initialization(original, begin)
                store._csrf_nonce_locked(handler, 'cookie', begin.values, begin.family_ref)
                _check_profile_begin_initialization(original, begin)
                if (original.guest_response is not begin or begin.phase != 'spent' or
                        original.thread is not threading.current_thread() or not now < begin.end):
                    raise _RequestUnavailable()
                # Only pure plan DATA; original begin remains retained across failures.
                plan = _retain_profile_plan_data(owner, duty, now)
                _check_profile_begin_initialization(original, begin)
                try:
                    begin.phase = 'registration-attempted'
                    original.guest_response = duty  # BEFORE F/R lookup and insertion.
                except BaseException as error:
                    raise _quarantine_profile_registration_error(store, duty, error, 0)
                try:
                    family = _source_family_data_locked(owner, begin.session, begin.values[0],
                        begin.family_ref, cohort, generation, now)
                except _ExpiredSourceFamily as expired:
                    if original.profile_begin_capture_error is None:
                        original.profile_begin_capture_error = expired
                    store._retire_known_family_locked(expired.family)
                    raise _RequestUnavailable() from None
                except _CorruptSourceFamily as error:
                    raise _quarantine_profile_registration_error(store, duty, error, 1)
                _check_profile_begin_initialization(original, begin)
                try:
                    record = consumed_profile_guest_data_locked(owner, family, begin.session,
                        begin.values[0], begin.guest_ref, cohort, generation, now)
                except _CorruptProfileSource as error:
                    raise _quarantine_profile_registration_error(store, duty, error, 2)
                _check_profile_begin_initialization(original, begin)
                if (family is not begin.family or record is not begin.record or
                        record._source is not begin.source or record._target is not begin.target or
                        cohort is not begin.cohort or generation is not begin.generation or
                        owner._original_guest_profile_tables_current() is not True):
                    raise _RequestUnavailable()
                _check_profile_begin_initialization(original, begin)
                uid, token = owner._credential_uid, owner._configured_token_id
                if (type(uid) is not int or not 1 <= uid <= 4294967294 or
                        type(token) is not tuple or len(token) != 2 or
                        any(type(value) is not str for value in token) or
                        not 0 < len(token[0]) <= 257 or not 0 < len(token[1]) <= 128 or
                        cohort.token_id is not token):
                    raise _RequestUnavailable()
                duty.end = min(plan.end, begin.end, original.end, original.write_end,
                               family._expires, record._expires)
                if not now < duty.end:
                    raise _RequestUnavailable()
                duty.last_clock, duty.credential_uid, duty.configured_token = now, uid, token
                duty.component_tables = owner._original_component_tables
                duty.inventory_tables = owner._original_guest_inventory_tables
                duty.profile_tables = owner._original_guest_profile_tables
                try:
                    original.write_end = min(original.write_end, duty.end)
                    _retain_profile_custody_data(store, original, handler, duty)
                    _check_profile_begin_initialization(original, begin)
                    duty.phase = 'captured'
                    registered = _retain_profile_registration_call_data(owner, duty)
                    _check_profile_begin_initialization(original, begin)
                except BaseException as error:
                    raise _quarantine_profile_registration_error(store, duty, error, 3)
                if not registered:
                    duty.phase = 'refused'
                    raise _RequestUnavailable()
            _check_profile_begin_initialization(original, begin)
        except BaseException as error:
            if original.profile_begin_capture_error is None:
                original.profile_begin_capture_error = error
            # Earlier sticky constructor refusal is retained before this escape.
            # Inline policy adds no recorder/helper before known guard finishing.
            first = begin.primary_error
            if first is None or (issubclass(type(first), Exception) and (
                    not issubclass(type(error), Exception) or
                    not issubclass(type(first), MemoryError) and issubclass(type(error), MemoryError))):
                first = error
            raise _finish_profile_registration_guard_error(store, guards, first)
        return duty
    except BaseException as error:
        if original.profile_begin_capture_error is None:
            original.profile_begin_capture_error = error
        raise _retain_profile_begin_failure(original, begin, error)
    finally:
        if type(begin) is _GuestProfileBeginDuty:
            original.profile_begin_original = begin


# No native constructor/run/cleanup, reserve/refund, frame or store/dispatch join.
