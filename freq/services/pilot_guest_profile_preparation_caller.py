"""Fixed original profile preparation caller, still without native acquisition.

Five outside call states cover begin, registration and three pure section
preparations. Private returned holders are never credentials, native allowance,
available sections or an admitted response. No HTTP dispatch activation here.
"""
from freq.services.cluster_pilot_http import _OriginalRequest, _RequestUnavailable
from freq.services.pilot_guest_retire_response import _owned_store
from freq.services.pilot_guest_profile_begin import (
    begin_profile, _GuestProfileBeginDuty,
    _check_profile_begin_initialization,
)
from freq.services.pilot_guest_profile_registration import (
    register_profile_acquisition, _ProfileAcquisitionDuty, _ProfileSectionSlot,
)
from freq.services.pilot_guest_profile_prepare import prepare_registered_profile_section
from freq.services.pilot_guest_profile_request_cleanup import (
    retire_profile_request_duty, _first, _error,
)


class _ProfilePreparationCaller:
    __slots__ = ('store', 'original', 'handler', 'states', 'inputs', 'returns',
                 'errors', 'primary', 'phase', 'cleanup_state',
                 'cleanup_return', 'cleanup_error', '_init_entered',
                 '_init_returned', '_init_refused', '_init_error')

    def __init__(self, store, original, handler):
        if type(self) is not _ProfilePreparationCaller:
            raise _RequestUnavailable()
        if hasattr(self, '_init_entered'):
            # Refuse before changing ANY first initialization observation.
            # Sticky before even refusal allocation, including swallowed errors.
            self._init_refused = True
            try:
                raise _RequestUnavailable()
            except BaseException as error:
                if self._init_error is None:
                    self._init_error = error
                first = self.primary
                # Same existing cleanup priority, inline to avoid a selector
                # helper between the first retained failure and outward escape.
                if first is None or (issubclass(type(first), Exception) and (
                        not issubclass(type(error), Exception) or
                        not issubclass(type(first), MemoryError) and
                        issubclass(type(error), MemoryError))):
                    self.primary = error
                raise self.primary
        self._init_entered = True
        self._init_returned = self._init_refused = False
        self._init_error = self.primary = None
        try:
            self.store, self.original, self.handler = store, original, handler
            self.phase = 'retained'
            self.cleanup_state = 'unattempted'
            self.cleanup_return = self.cleanup_error = None
            # Each original list is retained before the next allocation. A partial
            # initializer is spent too; a second initializer cannot fill or reset it.
            self.states = ['unattempted'] * 5
            self.inputs = [None] * 5
            self.returns = [None] * 5
            self.errors = [None] * 5
            self._init_returned = True
        except BaseException as error:
            # Partial first construction keeps its original failure and every
            # already stored list. A later original initializer cannot reset it.
            self._init_error = self.primary = error
            raise


def _check_caller_initialization(duty):
    if type(duty) is not _ProfilePreparationCaller:
        raise _RequestUnavailable()
    if duty._init_returned is not True or duty._init_refused is not False:
        if _error(duty.primary):
            raise duty.primary
        if _error(duty._init_error):
            raise duty._init_error
        raise _RequestUnavailable()


def _same_context(duty, stage):
    _check_caller_initialization(duty)
    if stage != 0:
        _check_profile_begin_initialization(duty.original, duty.returns[0])
    _owned_store(duty.store)
    _check_caller_initialization(duty)
    if stage != 0:
        _check_profile_begin_initialization(duty.original, duty.returns[0])
    original = duty.store._broker._owned(duty.handler)
    _check_caller_initialization(duty)
    if stage != 0:
        _check_profile_begin_initialization(duty.original, duty.returns[0])
    if (original is not duty.original or original.profile_preparation is not duty or
            type(original.operation) is not str or original.operation != 'guest-owner-profile'):
        raise _RequestUnavailable()
    expected = None if stage == 0 else duty.returns[0 if stage == 1 else 1]
    if original.guest_response is not expected:
        raise _RequestUnavailable()


def _stage(duty, index):
    _check_caller_initialization(duty)
    duty.inputs[index] = duty.original.guest_response
    duty.states[index] = 'call-pending'
    try:
        _same_context(duty, index)
        if index == 0:
            value = begin_profile(duty.store, duty.handler)
        elif index == 1:
            value = register_profile_acquisition(duty.store, duty.handler)
        else:
            value = prepare_registered_profile_section(duty.store, duty.handler, index - 2)
        duty.returns[index] = value
        duty.states[index] = 'call-returned'
        _check_caller_initialization(duty)
        original = duty.original
        _check_profile_begin_initialization(original, duty.returns[0])
        if index == 0:
            if (type(value) is not _GuestProfileBeginDuty or value.original is not original or
                    original.guest_response is not value):
                raise _RequestUnavailable()
        elif index == 1:
            if (type(value) is not _ProfileAcquisitionDuty or value.original is not original or
                    value.begin is not duty.returns[0] or original.guest_response is not value):
                raise _RequestUnavailable()
        else:
            acquired = duty.returns[1]
            if (type(value) is not _ProfileSectionSlot or type(acquired.slots) is not tuple or
                    len(acquired.slots) != 3 or acquired.slots[index - 2] is not value):
                raise _RequestUnavailable()
        _same_context(duty, index + 1)
    except BaseException as error:
        original = duty.original
        if original.profile_begin_capture_error is None and original.profile_begin_capture != 'unattempted':
            original.profile_begin_capture_error = error
        duty.errors[index] = error
        duty.primary = _first(duty.primary, error)
        begin = original.profile_begin_original
        if type(begin) is _GuestProfileBeginDuty:
            first = getattr(begin, 'primary_error', None)
            if first is None or (issubclass(type(first), Exception) and (
                    not issubclass(type(error), Exception) or
                    not issubclass(type(first), MemoryError) and issubclass(type(error), MemoryError))):
                begin.primary_error = error
        raise


def prepare_profile_request(store, handler):
    """One original preparation only; caller still owes every native boundary.

    Same original request retains each actual return/error. Partial failure
    invokes the fixed original cleanup entry once and retains that outside
    return/error too. No rollback, resumption, new deadline or positive frame.
    """
    _owned_store(store)
    original = store._broker._owned(handler)
    if (type(original) is not _OriginalRequest or type(original.operation) is not str or
            original.operation != 'guest-owner-profile'):
        raise _RequestUnavailable()
    if (type(original.profile_preparation_capture) is not str or
            original.profile_preparation_capture != 'unattempted' or
            original.profile_preparation is not None or original.profile_preparation_capture_error is not None):
        if _error(original.profile_preparation_capture_error):
            raise original.profile_preparation_capture_error
        previous = original.profile_preparation
        if type(previous) is _ProfilePreparationCaller:
            try:
                primary = previous.primary
            except AttributeError:
                primary = None
            if _error(primary):
                raise primary
        raise _RequestUnavailable()
    if original.guest_response is not None:
        raise _RequestUnavailable()
    original.profile_custody_started = True
    original.profile_preparation_capture = 'constructor-pending'
    try:
        original.profile_preparation = _ProfilePreparationCaller.__new__(_ProfilePreparationCaller)
        _ProfilePreparationCaller.__init__(original.profile_preparation, store, original, handler)
        _check_caller_initialization(original.profile_preparation)
        original.profile_preparation_capture = 'constructor-returned'
    except BaseException as error:
        original.profile_preparation_capture_error = error
        raise
    duty = original.profile_preparation
    try:
        for index in range(5):
            _stage(duty, index)
        _check_caller_initialization(duty)
    except BaseException as error:
        duty.primary = _first(duty.primary, error)
        duty.phase = 'unresolved'
        duty.cleanup_state = 'call-pending'
        try:
            duty.cleanup_return = retire_profile_request_duty(store, handler)
            duty.cleanup_state = 'call-returned'
        except BaseException as cleanup:
            duty.cleanup_error = cleanup
            duty.primary = _first(duty.primary, cleanup)
        # Keep actual cleanup return/error observations above separate from
        # this caller's sticky constructor refusal. No second cleanup effect.
        _check_caller_initialization(duty)
        raise duty.primary
    duty.phase = 'prepared-private'
    return duty


# No actual native job/credential/trust/current writer/recipient, section run,
# aggregate result, final response/frame/sendACK or physical parent retirement.
