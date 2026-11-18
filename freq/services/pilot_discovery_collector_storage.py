"""UNEXECUTED original Discovery storage/unentered reservation prefix.

The original installation and captured context retain the exact blank holders
before initialization. Reservations never enter an adapter. No closure issuer,
result, supplied executor or positive native admission exists in this module.
"""
import math
import threading
import time

from freq.services.cluster_pilot_http import (
    _OriginalPilotHandler, _OriginalRequest, _RequestUnavailable,
)
from freq.services.discovery_observation_data import DiscoveryPlan, plan_discovery
from freq.services.pilot_cluster_read_admission import _ReadGates
from freq.services.pilot_discovery_request_context import (
    _DiscoveryContextDuty, OriginalDiscoveryRequestContexts,
)


class _PrivateStorage:
    __slots__ = ()

    def __copy__(self):
        raise TypeError('original Discovery storage cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('original Discovery storage cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('original Discovery storage cannot be serialized')


def _failure_priority(earlier, later):
    # New collector policy: genuine control, then Memory, then ordinary;
    # chronology within each category. No instance __class__ substitution.
    if earlier is None:
        return later
    if not issubclass(type(earlier), Exception):
        return earlier
    if not issubclass(type(later), Exception):
        return later
    if issubclass(type(earlier), MemoryError):
        return earlier
    if issubclass(type(later), MemoryError):
        return later
    return earlier


def _retain_context_failure(context, error):
    # The original context exists even when blank request allocation fails.
    if context.collector_raw_failure is None:
        context.collector_raw_failure = error
    if not issubclass(type(error), Exception):
        if context.collector_genuine_failure is None:
            context.collector_genuine_failure = error
    elif issubclass(type(error), MemoryError):
        if context.collector_allocation_failure is None:
            context.collector_allocation_failure = error
    elif context.collector_ordinary_failure is None:
        context.collector_ordinary_failure = error


def _selected_context_failure(context):
    for error in (context.collector_genuine_failure,
                  context.collector_allocation_failure,
                  context.collector_ordinary_failure):
        if error is not None:
            return error
    return None


class _TargetDuty(_PrivateStorage):
    __slots__ = ('request', 'index', 'target', 'state', 'occupancy',
                 'occupancy_generation', 'handle', 'outcome', 'failure',
                 'terminate_started', 'wait_started')

    def _initialize(self, request, index):
        if (type(self) is not _TargetDuty or hasattr(self, 'request') or
                request.targets[index] is not self):
            raise _RequestUnavailable()
        self.request = request  # Once; this duty is never reused for another IP.
        self.index, self.target = index, request.plan.targets[index]
        self.state = 'unused'
        self.occupancy = self.occupancy_generation = None
        self.handle = self.outcome = self.failure = None
        self.terminate_started = self.wait_started = False

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original target duty cannot be subclassed')


class _OccupancySlot(_PrivateStorage):
    __slots__ = ('request', 'index', 'generation', 'duty')

    def _initialize(self, request, index):
        if (type(self) is not _OccupancySlot or hasattr(self, 'request') or
                request.occupancy[index] is not self):
            raise _RequestUnavailable()
        self.request = request
        self.index, self.generation, self.duty = index, 0, None

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original occupancy slot cannot be subclassed')


class _RequestStorage(_PrivateStorage):
    __slots__ = ('_started', '_complete', 'component', 'context', 'original',
                 'session', 'values', 'plan', 'end', 'thread', 'clock',
                 'targets', 'occupancy', '_targets_root', '_occupancy_root',
                 '_target_anchors', '_slot_anchors', 'adapter', 'profile', 'retired',
                 'raw_failure', 'genuine_failure', 'allocation_failure',
                 'ordinary_failure', 'retirement_started', '_issue_cursor',
                 '_reserved_count', '_reserve_busy')

    def _initialize(self, component, context):
        if (type(self) is not _RequestStorage or hasattr(self, '_started') or
                hasattr(self, 'retired') or hasattr(self, 'retirement_started') or
                context.collector_storage is not self or
                context.collector_anchor is not self or
                context.collector_started is not True or
                context.collector_retired is not False):
            raise _RequestUnavailable()
        self._started, self._complete = True, False
        self.component, self.context = component, context
        self.original, self.session, self.values = context.original, context.session, context.values
        self.plan, self.end = context.plan, context.end
        self.thread, self.clock = self.original.thread, time.monotonic
        self.retired, self.retirement_started = False, False
        self.raw_failure = self.genuine_failure = None
        self.allocation_failure = self.ordinary_failure = None
        self.adapter = self.profile = None  # No authority can be substituted.
        self._issue_cursor = self._reserved_count = 0
        self._reserve_busy = False
        targets = self._targets_root = [None] * 254
        self.targets = targets
        occupancy = self._occupancy_root = [None] * 50
        self.occupancy = occupancy
        # Every blank child is retained before any child initializer runs.
        for index in range(254):
            duty = object.__new__(_TargetDuty)
            targets[index] = duty
        for index in range(50):
            slot = object.__new__(_OccupancySlot)
            occupancy[index] = slot
        target_anchors = self._target_anchors = tuple(targets)
        slot_anchors = self._slot_anchors = tuple(occupancy)
        for index, duty in enumerate(target_anchors):
            self._roots_current(component, context, targets, occupancy)
            _TargetDuty._initialize(duty, self, index)
            self._roots_current(component, context, targets, occupancy)
            if targets[index] is not duty:
                raise _RequestUnavailable()
        for index, slot in enumerate(slot_anchors):
            self._roots_current(component, context, targets, occupancy)
            _OccupancySlot._initialize(slot, self, index)
            self._roots_current(component, context, targets, occupancy)
            if occupancy[index] is not slot:
                raise _RequestUnavailable()
        _unissued_graph(self, (targets, target_anchors, occupancy, slot_anchors))
        self._complete = True

    def _roots_current(self, component, context, targets, occupancy):
        component._same_component()
        if (self.component is not component or self.context is not context or
                context.collector_anchor is not self or
                context.collector_storage is not self or
                context.collector_retired is not False or
                context.collector_started is not True or
                self.retired is not False or self.retirement_started is not False or
                self._targets_root is not targets or self._occupancy_root is not occupancy or
                self.targets is not targets or self.occupancy is not occupancy or
                self.plan is not context.plan):
            raise _RequestUnavailable()

    def _retain_failure(self, error):
        # First raw object before category bookkeeping, no formatting/group walk.
        if not issubclass(type(error), BaseException):
            raise TypeError('original escaped exception required')
        if getattr(self, 'raw_failure', None) is None:
            self.raw_failure = error
        if not issubclass(type(error), Exception):
            if getattr(self, 'genuine_failure', None) is None:
                self.genuine_failure = error
        elif issubclass(type(error), MemoryError):
            if getattr(self, 'allocation_failure', None) is None:
                self.allocation_failure = error
        elif getattr(self, 'ordinary_failure', None) is None:
            self.ordinary_failure = error

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original request storage cannot be subclassed')


def _unissued_graph(storage, roots):
    if (storage._issue_cursor != 0 or type(storage._issue_cursor) is not int or
            storage._reserved_count != 0 or type(storage._reserved_count) is not int or
            storage._reserve_busy is not False):
        raise _RequestUnavailable()
    targets, target_anchors, occupancy, slot_anchors = roots
    if (storage._targets_root is not targets or storage._occupancy_root is not occupancy or
            storage._target_anchors is not target_anchors or
            storage._slot_anchors is not slot_anchors or
            storage.targets is not targets or storage.occupancy is not occupancy or
            type(targets) is not list or type(occupancy) is not list or
            type(target_anchors) is not tuple or type(slot_anchors) is not tuple or
            len(targets) != 254 or len(target_anchors) != 254 or
            len(occupancy) != 50 or len(slot_anchors) != 50 or
            len({id(duty) for duty in target_anchors}) != 254 or
            len({id(slot) for slot in slot_anchors}) != 50 or
            type(storage.plan) is not DiscoveryPlan or
            type(storage.plan.targets) is not tuple or len(storage.plan.targets) != 254):
        raise _RequestUnavailable()
    for index, duty in enumerate(target_anchors):
        if (targets[index] is not duty or type(duty) is not _TargetDuty or
                duty.request is not storage or type(duty.index) is not int or
                duty.index != index or duty.target is not storage.plan.targets[index] or
                type(duty.state) is not str or duty.state != 'unused' or
                duty.occupancy is not None or duty.occupancy_generation is not None or
                duty.handle is not None or duty.outcome is not None or
                duty.failure is not None or duty.terminate_started is not False or
                duty.wait_started is not False):
            raise _RequestUnavailable()
    for index, slot in enumerate(slot_anchors):
        if (occupancy[index] is not slot or type(slot) is not _OccupancySlot or
                slot.request is not storage or type(slot.index) is not int or
                slot.index != index or type(slot.generation) is not int or
                slot.generation != 0 or slot.duty is not None):
            raise _RequestUnavailable()


def _unentered_graph(storage, roots):
    # This namespace has no native entry, handle return or closure method.
    # Every reservation stays dispatch-pending and occupies its original slot.
    targets, target_anchors, occupancy, slot_anchors = roots
    if (type(storage._issue_cursor) is not int or
            type(storage._reserved_count) is not int or
            storage._issue_cursor != storage._reserved_count or
            not 0 <= storage._reserved_count <= 50 or
            type(storage._reserve_busy) is not bool):
        raise _RequestUnavailable()
    count = storage._reserved_count
    if (storage._targets_root is not targets or storage._occupancy_root is not occupancy or
            storage._target_anchors is not target_anchors or
            storage._slot_anchors is not slot_anchors or
            storage.targets is not targets or storage.occupancy is not occupancy or
            type(targets) is not list or type(occupancy) is not list or
            type(target_anchors) is not tuple or type(slot_anchors) is not tuple or
            len(targets) != 254 or len(target_anchors) != 254 or
            len(occupancy) != 50 or len(slot_anchors) != 50 or
            len({id(duty) for duty in target_anchors}) != 254 or
            len({id(slot) for slot in slot_anchors}) != 50 or
            type(storage.plan) is not DiscoveryPlan or
            type(storage.plan.targets) is not tuple or len(storage.plan.targets) != 254):
        raise _RequestUnavailable()
    for index, duty in enumerate(target_anchors):
        if (targets[index] is not duty or type(duty) is not _TargetDuty or
                duty.request is not storage or type(duty.index) is not int or
                duty.index != index or duty.target is not storage.plan.targets[index] or
                type(duty.state) is not str or
                duty.state != ('dispatch-pending' if index < count else 'unused') or
                duty.occupancy is not (slot_anchors[index] if index < count else None) or
                (index < count and (type(duty.occupancy_generation) is not int or
                                    duty.occupancy_generation != 1)) or
                (index >= count and duty.occupancy_generation is not None) or
                duty.handle is not None or duty.outcome is not None or
                duty.failure is not None or duty.terminate_started is not False or
                duty.wait_started is not False):
            raise _RequestUnavailable()
    for index, slot in enumerate(slot_anchors):
        if (occupancy[index] is not slot or type(slot) is not _OccupancySlot or
                slot.request is not storage or type(slot.index) is not int or
                slot.index != index or type(slot.generation) is not int or
                slot.generation != (1 if index < count else 0) or
                slot.duty is not (target_anchors[index] if index < count else None)):
            raise _RequestUnavailable()


class _OriginalDiscoveryCollectorStorage(_PrivateStorage):
    __slots__ = ('_started', '_complete', '_installation', '_contexts')

    def _initialize(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not _OriginalDiscoveryCollectorStorage or
                hasattr(self, '_started') or
                type(installation) is not OriginalPilotInstallation or
                installation._discovery_collector_storage is not self):
            raise _RequestUnavailable()
        self._started, self._complete = True, False
        self._installation = installation
        contexts = self._contexts = installation._discovery_contexts
        if (type(contexts) is not OriginalDiscoveryRequestContexts or
                contexts._installation is not installation or
                installation._original_discovery_tables_current() is not True):
            raise _RequestUnavailable()
        if (installation._discovery_collector_storage is not self or
                installation._discovery_contexts is not contexts or
                self._installation is not installation or self._contexts is not contexts or
                contexts._installation is not installation):
            raise _RequestUnavailable()
        self._complete = True

    def _same_component(self):
        owner = self._installation
        if (self._complete is not True or
                owner._discovery_collector_storage is not self or
                owner._discovery_contexts is not self._contexts or
                self._contexts._installation is not owner):
            raise _RequestUnavailable()

    def _context_fields(self, context, identity):
        original, session, values, plan, end, thread, clock = identity
        if (context.original is not original or original.discovery_duty is not context or
                context.session is not session or context.values is not values or
                context.plan is not plan or type(context.end) is not float or
                context.end != end or original.thread is not thread or
                threading.current_thread() is not thread or time.monotonic is not clock):
            raise _RequestUnavailable()

    def _storage_locked(self, context, storage, roots, identity):
        self._same_component()
        self._contexts._same_captured_locked(context)
        self._storage_fields(context, storage, roots, identity)

    def _storage_fields(self, context, storage, roots, identity):
        # No currentness callback here: also guard AFTER gate __exit__ returns.
        self._same_component()
        self._context_fields(context, identity)
        if (type(context) is not _DiscoveryContextDuty or
                context.collector_started is not True or
                context.collector_retired is not False or
                context.collector_anchor is not storage or
                context.collector_storage is not storage or
                type(storage) is not _RequestStorage or storage._complete is not True or
                storage.component is not self or storage.context is not context or
                storage.original is not context.original or
                storage.session is not context.session or storage.values is not context.values or
                storage.plan is not context.plan or storage.end != context.end or
                storage.thread is not context.original.thread or
                storage.clock is not time.monotonic or storage.retired is not False or
                storage.retirement_started is not False or
                storage.adapter is not None or storage.profile is not None):
            raise _RequestUnavailable()
        _unentered_graph(storage, roots)

    def prepare_handler_storage(self, handler):
        """Only preallocate retained unissued storage; return no grant/result."""
        self._same_component()
        original = self._contexts._broker._owned(handler)
        context = original.discovery_duty
        if (type(context) is not _DiscoveryContextDuty or
                context.original is not original or context.handler is not handler):
            raise _RequestUnavailable()
        storage = None
        body_failure = None
        try:
            with _ReadGates(self._contexts._auth, original, context.end):
                try:
                    self._contexts._same_captured_locked(context)
                    self._same_component()
                    if (context.collector_started is not False or
                            context.collector_retired is not False or
                            context.collector_anchor is not None or
                            context.collector_storage is not None or
                            type(context.plan) is not DiscoveryPlan or
                            type(context.end) is not float or not math.isfinite(context.end)):
                        raise _RequestUnavailable()
                    expected_plan = context.plan
                    identity = (original, context.session, context.values, expected_plan,
                                context.end, original.thread, time.monotonic)
                except BaseException as escaped_body:
                    # Keep local selected recorder failures BEFORE original gate exit.
                    # Raw body identity stays separate from the selected category.
                    body_failure = escaped_body
                    try:
                        if context.collector_raw_failure is None:
                            context.collector_raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if storage is not None and getattr(storage, 'raw_failure', None) is None:
                            storage.raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if not issubclass(type(escaped_body), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = escaped_body
                        elif issubclass(type(escaped_body), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = escaped_body
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(escaped_body), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = escaped_body
                            elif issubclass(type(escaped_body), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = escaped_body
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        _retain_context_failure(context, escaped_body)
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                        try:
                            if not issubclass(type(recording), Exception):
                                if getattr(context, 'collector_genuine_failure', None) is None:
                                    context.collector_genuine_failure = recording
                            elif issubclass(type(recording), MemoryError):
                                if getattr(context, 'collector_allocation_failure', None) is None:
                                    context.collector_allocation_failure = recording
                            elif getattr(context, 'collector_ordinary_failure', None) is None:
                                context.collector_ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                        try:
                            if storage is not None:
                                if not issubclass(type(recording), Exception):
                                    if getattr(storage, 'genuine_failure', None) is None:
                                        storage.genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(storage, 'allocation_failure', None) is None:
                                        storage.allocation_failure = recording
                                elif getattr(storage, 'ordinary_failure', None) is None:
                                    storage.ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                    if storage is not None:
                        try:
                            _RequestStorage._retain_failure(storage, escaped_body)
                        except BaseException as recording:
                            body_failure = _failure_priority(body_failure, recording)
                            try:
                                if not issubclass(type(recording), Exception):
                                    if getattr(context, 'collector_genuine_failure', None) is None:
                                        context.collector_genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(context, 'collector_allocation_failure', None) is None:
                                        context.collector_allocation_failure = recording
                                elif getattr(context, 'collector_ordinary_failure', None) is None:
                                    context.collector_ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                            try:
                                if storage is not None:
                                    if not issubclass(type(recording), Exception):
                                        if getattr(storage, 'genuine_failure', None) is None:
                                            storage.genuine_failure = recording
                                    elif issubclass(type(recording), MemoryError):
                                        if getattr(storage, 'allocation_failure', None) is None:
                                            storage.allocation_failure = recording
                                    elif getattr(storage, 'ordinary_failure', None) is None:
                                        storage.ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                    # Direct persistence of the selected local winner is a fixed
                    # bookkeeping stage, not a retry of either recording helper.
                    try:
                        if not issubclass(type(body_failure), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = body_failure
                        elif issubclass(type(body_failure), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = body_failure
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(body_failure), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = body_failure
                            elif issubclass(type(body_failure), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = body_failure
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    raise body_failure
            # A suppressing gate cannot convert a recorded body failure to success.
            if body_failure is not None:
                raise body_failure
            # Existing parser is DATA validation outside gates, never a grant.
            plan = plan_discovery(expected_plan.requested_subnet)
            with _ReadGates(self._contexts._auth, original, context.end):
                try:
                    self._contexts._same_captured_locked(context)
                    self._same_component()
                    self._context_fields(context, identity)
                    if (context.plan is not expected_plan or plan != expected_plan or
                            len(expected_plan.targets) != 254 or
                            context.collector_started is not False or
                            context.collector_retired is not False or
                            context.collector_anchor is not None or
                            context.collector_storage is not None):
                        raise _RequestUnavailable()
                    context.collector_started = True  # Never retried/refunded.
                    storage = object.__new__(_RequestStorage)
                    if (context.collector_anchor is not None or
                            context.collector_storage is not None or
                            context.collector_retired is not False):
                        raise _RequestUnavailable()
                    context.collector_anchor = storage  # Original root FIRST.
                    context.collector_storage = storage  # BEFORE initializer.
                except BaseException as escaped_body:
                    # Keep local selected recorder failures BEFORE original gate exit.
                    # Raw body identity stays separate from the selected category.
                    body_failure = escaped_body
                    try:
                        if context.collector_raw_failure is None:
                            context.collector_raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if storage is not None and getattr(storage, 'raw_failure', None) is None:
                            storage.raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if not issubclass(type(escaped_body), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = escaped_body
                        elif issubclass(type(escaped_body), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = escaped_body
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(escaped_body), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = escaped_body
                            elif issubclass(type(escaped_body), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = escaped_body
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        _retain_context_failure(context, escaped_body)
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                        try:
                            if not issubclass(type(recording), Exception):
                                if getattr(context, 'collector_genuine_failure', None) is None:
                                    context.collector_genuine_failure = recording
                            elif issubclass(type(recording), MemoryError):
                                if getattr(context, 'collector_allocation_failure', None) is None:
                                    context.collector_allocation_failure = recording
                            elif getattr(context, 'collector_ordinary_failure', None) is None:
                                context.collector_ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                        try:
                            if storage is not None:
                                if not issubclass(type(recording), Exception):
                                    if getattr(storage, 'genuine_failure', None) is None:
                                        storage.genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(storage, 'allocation_failure', None) is None:
                                        storage.allocation_failure = recording
                                elif getattr(storage, 'ordinary_failure', None) is None:
                                    storage.ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                    if storage is not None:
                        try:
                            _RequestStorage._retain_failure(storage, escaped_body)
                        except BaseException as recording:
                            body_failure = _failure_priority(body_failure, recording)
                            try:
                                if not issubclass(type(recording), Exception):
                                    if getattr(context, 'collector_genuine_failure', None) is None:
                                        context.collector_genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(context, 'collector_allocation_failure', None) is None:
                                        context.collector_allocation_failure = recording
                                elif getattr(context, 'collector_ordinary_failure', None) is None:
                                    context.collector_ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                            try:
                                if storage is not None:
                                    if not issubclass(type(recording), Exception):
                                        if getattr(storage, 'genuine_failure', None) is None:
                                            storage.genuine_failure = recording
                                    elif issubclass(type(recording), MemoryError):
                                        if getattr(storage, 'allocation_failure', None) is None:
                                            storage.allocation_failure = recording
                                    elif getattr(storage, 'ordinary_failure', None) is None:
                                        storage.ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                    # Direct persistence of the selected local winner is a fixed
                    # bookkeeping stage, not a retry of either recording helper.
                    try:
                        if not issubclass(type(body_failure), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = body_failure
                        elif issubclass(type(body_failure), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = body_failure
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(body_failure), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = body_failure
                            elif issubclass(type(body_failure), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = body_failure
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    raise body_failure
            # A suppressing gate cannot convert a recorded body failure to success.
            if body_failure is not None:
                raise body_failure
            _RequestStorage._initialize(storage, self, context)
            # Capture originals BEFORE any final currentness/gate helper.
            roots = (storage._targets_root, storage._target_anchors,
                     storage._occupancy_root, storage._slot_anchors)
            with _ReadGates(self._contexts._auth, original, context.end):
                try:
                    self._storage_locked(context, storage, roots, identity)
                except BaseException as escaped_body:
                    # Keep local selected recorder failures BEFORE original gate exit.
                    # Raw body identity stays separate from the selected category.
                    body_failure = escaped_body
                    try:
                        if context.collector_raw_failure is None:
                            context.collector_raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if storage is not None and getattr(storage, 'raw_failure', None) is None:
                            storage.raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if not issubclass(type(escaped_body), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = escaped_body
                        elif issubclass(type(escaped_body), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = escaped_body
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(escaped_body), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = escaped_body
                            elif issubclass(type(escaped_body), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = escaped_body
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        _retain_context_failure(context, escaped_body)
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                        try:
                            if not issubclass(type(recording), Exception):
                                if getattr(context, 'collector_genuine_failure', None) is None:
                                    context.collector_genuine_failure = recording
                            elif issubclass(type(recording), MemoryError):
                                if getattr(context, 'collector_allocation_failure', None) is None:
                                    context.collector_allocation_failure = recording
                            elif getattr(context, 'collector_ordinary_failure', None) is None:
                                context.collector_ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                        try:
                            if storage is not None:
                                if not issubclass(type(recording), Exception):
                                    if getattr(storage, 'genuine_failure', None) is None:
                                        storage.genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(storage, 'allocation_failure', None) is None:
                                        storage.allocation_failure = recording
                                elif getattr(storage, 'ordinary_failure', None) is None:
                                    storage.ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                    if storage is not None:
                        try:
                            _RequestStorage._retain_failure(storage, escaped_body)
                        except BaseException as recording:
                            body_failure = _failure_priority(body_failure, recording)
                            try:
                                if not issubclass(type(recording), Exception):
                                    if getattr(context, 'collector_genuine_failure', None) is None:
                                        context.collector_genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(context, 'collector_allocation_failure', None) is None:
                                        context.collector_allocation_failure = recording
                                elif getattr(context, 'collector_ordinary_failure', None) is None:
                                    context.collector_ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                            try:
                                if storage is not None:
                                    if not issubclass(type(recording), Exception):
                                        if getattr(storage, 'genuine_failure', None) is None:
                                            storage.genuine_failure = recording
                                    elif issubclass(type(recording), MemoryError):
                                        if getattr(storage, 'allocation_failure', None) is None:
                                            storage.allocation_failure = recording
                                    elif getattr(storage, 'ordinary_failure', None) is None:
                                        storage.ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                    # Direct persistence of the selected local winner is a fixed
                    # bookkeeping stage, not a retry of either recording helper.
                    try:
                        if not issubclass(type(body_failure), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = body_failure
                        elif issubclass(type(body_failure), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = body_failure
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(body_failure), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = body_failure
                            elif issubclass(type(body_failure), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = body_failure
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    raise body_failure
            # A suppressing gate cannot convert a recorded body failure to success.
            if body_failure is not None:
                raise body_failure
            self._storage_fields(context, storage, roots, identity)
            return None
        except BaseException as error:
            selected = error
            if body_failure is not None:
                # Original body precedes exit failure even when Python's
                # escaping object is the later context-manager exception.
                selected = _failure_priority(body_failure, selected)
                try:
                    _retain_context_failure(context, body_failure)
                except BaseException as later:
                    selected = _failure_priority(selected, later)
                if storage is not None:
                    try:
                        _RequestStorage._retain_failure(storage, body_failure)
                    except BaseException as later:
                        selected = _failure_priority(selected, later)
            try:
                _retain_context_failure(context, error)
                selected = _failure_priority(_selected_context_failure(context), selected)
            except BaseException as later:
                selected = _failure_priority(selected, later)
            try:
                context.collector_retired = True
            except BaseException as later:
                selected = _failure_priority(selected, later)
            if storage is not None:
                try:
                    _RequestStorage._retain_failure(storage, error)
                except BaseException as later:
                    selected = _failure_priority(selected, later)
                try:
                    storage.retired = True
                    storage.retirement_started = True
                except BaseException as later:
                    selected = _failure_priority(selected, later)
            raise selected

    def _reserve_handler_target(self, handler):
        """Pure unentered reservation; return no handle, grant or result.

        Only the same original target and occupancy holders are changed. Native
        acquisition/late return and qualified closure/transfer remain absent.
        """
        self._same_component()
        original = self._contexts._broker._owned(handler)
        context = original.discovery_duty
        if (type(context) is not _DiscoveryContextDuty or
                context.original is not original or context.handler is not handler):
            raise _RequestUnavailable()
        storage = context.collector_anchor
        if (type(storage) is not _RequestStorage or
                storage.component is not self or storage.context is not context):
            raise _RequestUnavailable()
        body_failure = None
        try:
            if storage._reserve_busy is not False:
                raise _RequestUnavailable()
            storage._reserve_busy = True  # Nested entry retires this original.
            # Originals precede gate/currentness helpers, including gate exit.
            roots = (storage._targets_root, storage._target_anchors,
                     storage._occupancy_root, storage._slot_anchors)
            identity = (storage.original, storage.session, storage.values,
                        storage.plan, storage.end, storage.thread, storage.clock)
            with _ReadGates(self._contexts._auth, original, storage.end):
                try:
                    self._storage_locked(context, storage, roots, identity)
                    if storage._reserved_count < 50:
                        at = storage._issue_cursor
                        duty, slot = roots[1][at], roots[3][at]
                        # Both originals were already rooted during preparation.
                        # Consume and associate BEFORE any later helper can run.
                        duty.state = 'dispatch-pending'
                        duty.occupancy, duty.occupancy_generation = slot, 1
                        slot.duty, slot.generation = duty, 1
                        storage._issue_cursor = at + 1
                        storage._reserved_count += 1
                    # Full capacity is observation-only: no later target is spent,
                    # no pending slot released and no original duty is reused.
                    self._storage_locked(context, storage, roots, identity)
                except BaseException as escaped_body:
                    # Keep local selected recorder failures BEFORE original gate exit.
                    # Raw body identity stays separate from the selected category.
                    body_failure = escaped_body
                    try:
                        if context.collector_raw_failure is None:
                            context.collector_raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if storage is not None and getattr(storage, 'raw_failure', None) is None:
                            storage.raw_failure = escaped_body
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                    try:
                        if not issubclass(type(escaped_body), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = escaped_body
                        elif issubclass(type(escaped_body), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = escaped_body
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(escaped_body), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = escaped_body
                            elif issubclass(type(escaped_body), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = escaped_body
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = escaped_body
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        _retain_context_failure(context, escaped_body)
                    except BaseException as recording:
                        body_failure = _failure_priority(body_failure, recording)
                        try:
                            if not issubclass(type(recording), Exception):
                                if getattr(context, 'collector_genuine_failure', None) is None:
                                    context.collector_genuine_failure = recording
                            elif issubclass(type(recording), MemoryError):
                                if getattr(context, 'collector_allocation_failure', None) is None:
                                    context.collector_allocation_failure = recording
                            elif getattr(context, 'collector_ordinary_failure', None) is None:
                                context.collector_ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                        try:
                            if storage is not None:
                                if not issubclass(type(recording), Exception):
                                    if getattr(storage, 'genuine_failure', None) is None:
                                        storage.genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(storage, 'allocation_failure', None) is None:
                                        storage.allocation_failure = recording
                                elif getattr(storage, 'ordinary_failure', None) is None:
                                    storage.ordinary_failure = recording
                        except BaseException as bookkeeping:
                            body_failure = _failure_priority(body_failure, bookkeeping)
                    if storage is not None:
                        try:
                            _RequestStorage._retain_failure(storage, escaped_body)
                        except BaseException as recording:
                            body_failure = _failure_priority(body_failure, recording)
                            try:
                                if not issubclass(type(recording), Exception):
                                    if getattr(context, 'collector_genuine_failure', None) is None:
                                        context.collector_genuine_failure = recording
                                elif issubclass(type(recording), MemoryError):
                                    if getattr(context, 'collector_allocation_failure', None) is None:
                                        context.collector_allocation_failure = recording
                                elif getattr(context, 'collector_ordinary_failure', None) is None:
                                    context.collector_ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                            try:
                                if storage is not None:
                                    if not issubclass(type(recording), Exception):
                                        if getattr(storage, 'genuine_failure', None) is None:
                                            storage.genuine_failure = recording
                                    elif issubclass(type(recording), MemoryError):
                                        if getattr(storage, 'allocation_failure', None) is None:
                                            storage.allocation_failure = recording
                                    elif getattr(storage, 'ordinary_failure', None) is None:
                                        storage.ordinary_failure = recording
                            except BaseException as bookkeeping:
                                body_failure = _failure_priority(body_failure, bookkeeping)
                    # Direct persistence of the selected local winner is a fixed
                    # bookkeeping stage, not a retry of either recording helper.
                    try:
                        if not issubclass(type(body_failure), Exception):
                            if getattr(context, 'collector_genuine_failure', None) is None:
                                context.collector_genuine_failure = body_failure
                        elif issubclass(type(body_failure), MemoryError):
                            if getattr(context, 'collector_allocation_failure', None) is None:
                                context.collector_allocation_failure = body_failure
                        elif getattr(context, 'collector_ordinary_failure', None) is None:
                            context.collector_ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    try:
                        if storage is not None:
                            if not issubclass(type(body_failure), Exception):
                                if getattr(storage, 'genuine_failure', None) is None:
                                    storage.genuine_failure = body_failure
                            elif issubclass(type(body_failure), MemoryError):
                                if getattr(storage, 'allocation_failure', None) is None:
                                    storage.allocation_failure = body_failure
                            elif getattr(storage, 'ordinary_failure', None) is None:
                                storage.ordinary_failure = body_failure
                    except BaseException as bookkeeping:
                        body_failure = _failure_priority(body_failure, bookkeeping)
                    raise body_failure
            # A suppressing gate cannot convert a recorded body failure to success.
            if body_failure is not None:
                raise body_failure
            self._storage_fields(context, storage, roots, identity)
            return None
        except BaseException as error:
            selected = error
            if body_failure is not None:
                # Original body precedes exit failure even when Python's
                # escaping object is the later context-manager exception.
                selected = _failure_priority(body_failure, selected)
                try:
                    _retain_context_failure(context, body_failure)
                except BaseException as later:
                    selected = _failure_priority(selected, later)
                if storage is not None:
                    try:
                        _RequestStorage._retain_failure(storage, body_failure)
                    except BaseException as later:
                        selected = _failure_priority(selected, later)
            try:
                _retain_context_failure(context, error)
                selected = _failure_priority(_selected_context_failure(context), selected)
            except BaseException as later:
                selected = _failure_priority(selected, later)
            try:
                context.collector_retired = True
            except BaseException as later:
                selected = _failure_priority(selected, later)
            if storage is not None:
                try:
                    _RequestStorage._retain_failure(storage, error)
                except BaseException as later:
                    selected = _failure_priority(selected, later)
                try:
                    storage.retired = True
                    storage.retirement_started = True
                except BaseException as later:
                    selected = _failure_priority(selected, later)
            raise selected
        finally:
            storage._reserve_busy = False

    def retire_handler_storage(self, handler):
        """Pure retirement, no live/deadline dependency and no charge refund."""
        self._same_component()
        if type(handler) is not _OriginalPilotHandler:
            raise _RequestUnavailable()
        original = self._contexts._broker._requests.get(handler.request)
        if (type(original) is not _OriginalRequest or original.handler is not handler or
                original.socket is not handler.request or
                original.thread is not threading.current_thread()):
            raise _RequestUnavailable()
        context = original.discovery_duty
        if (type(context) is not _DiscoveryContextDuty or context.original is not original or
                context.handler is not handler or context.socket is not handler.request):
            raise _RequestUnavailable()
        context.collector_retired = True  # Refuse even preallocation reentry.
        storage = context.collector_anchor
        if storage is None:
            if context.collector_storage is not None:
                raise _RequestUnavailable()
            return None
        if type(storage) is not _RequestStorage:
            raise _RequestUnavailable()
        storage.retired = True  # Also valid for a retained partial holder.
        storage.retirement_started = True
        if context.collector_storage is not storage:
            # Retire the retained original; never act on a foreign current view.
            raise _RequestUnavailable()
        # Original context/maps/request and each target/slot remain rooted.
        # No native duty exists here, and no root is cleared or refunded.
        return None

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original collector component cannot be subclassed')


# No native entry, occupancy transfer/release, supplied handle adoption, process
# method, closure receipt, response publisher or positive collector result.
