"""Supplied Discovery scheduling DATA; never a native custodian or receipt issuer.

Transitions model bookkeeping before dispatch and after supplied events. They
perform no effects and authenticate no process, operation, clock or result.
The original adapter remains unavailable; no positive collector calls this.
In particular, reported closure here cannot release a real process obligation.
"""
import math
from typing import NamedTuple

from freq.services.discovery_observation_data import DiscoveryPlan, plan_discovery


MAX_OCCUPIED = 50
_OCCUPIED = ('issued', 'owned', 'terminating', 'unknown')
_STATES = ('queued',) + _OCCUPIED + ('reported_closed',)


class ProbeSlot(NamedTuple):
    target: str
    state: str
    reported_status: object


class CollectionData(NamedTuple):
    plan: DiscoveryPlan
    absolute_end: object
    slots: tuple
    retired: bool
    first_failure: object
    first_priority_failure: object


def _time(value):
    if type(value) not in (int, float) or not 0 < value <= 9007199254740991 or not math.isfinite(value):
        raise ValueError('Expected finite positive supplied monotonic metadata')
    return value


def _checked(data):
    if type(data) is not CollectionData or type(data.plan) is not DiscoveryPlan:
        raise ValueError('Expected exact collection DATA')
    if (type(data.plan.requested_subnet) is not str or type(data.plan.network) is not str or
            type(data.plan.targets) is not tuple or len(data.plan.targets) != 254 or
            any(type(target) is not str for target in data.plan.targets)):
        raise ValueError('Expected primitive immutable plan DATA')
    if plan_discovery(data.plan.requested_subnet) != data.plan:
        raise ValueError('Expected exact validated plan')
    _time(data.absolute_end)
    if type(data.slots) is not tuple or len(data.slots) != 254 or type(data.retired) is not bool:
        raise ValueError('Expected complete immutable slot DATA')
    if data.first_failure is not None and not isinstance(data.first_failure, BaseException):
        raise ValueError('Expected retained failure object')
    if data.first_failure is not None and not data.retired:
        raise ValueError('Failure cannot reopen issuance')
    if data.first_priority_failure is not None:
        if (not isinstance(data.first_priority_failure, BaseException) or
                isinstance(data.first_priority_failure, Exception) and not isinstance(data.first_priority_failure, MemoryError)):
            raise ValueError('Expected retained control or allocation failure')
        if data.first_failure is None or not data.retired:
            raise ValueError('Priority failure cannot erase first failure or retirement')
    if (data.first_failure is not None and
            (not isinstance(data.first_failure, Exception) or isinstance(data.first_failure, MemoryError)) and
            data.first_priority_failure is not data.first_failure):
        raise ValueError('Original control must remain the priority failure')
    for target, slot in zip(data.plan.targets, data.slots):
        if (type(slot) is not ProbeSlot or type(slot.target) is not str or slot.target != target or
                type(slot.state) is not str or slot.state not in _STATES):
            raise ValueError('Expected one exact slot per planned target')
        if slot.state == 'reported_closed':
            if type(slot.reported_status) is not str or slot.reported_status not in ('responding', 'no_response', 'unavailable'):
                raise ValueError('Expected explicit supplied closed outcome')
        elif slot.reported_status is not None:
            raise ValueError('Unsettled slots cannot report an outcome')
        if slot.state in ('unknown', 'terminating') and not data.retired:
            raise ValueError('Unknown or terminating custody cannot permit issuance')
    if sum(slot.state in _OCCUPIED for slot in data.slots) > MAX_OCCUPIED:
        raise ValueError('Supplied occupied-slot limit exceeded')
    return data


def new_collection_data(plan, absolute_end):
    """Preallocate all254 slots before any modeled dispatch; no effects."""
    if (type(plan) is not DiscoveryPlan or type(plan.requested_subnet) is not str or
            type(plan.network) is not str or type(plan.targets) is not tuple or len(plan.targets) != 254 or
            any(type(target) is not str for target in plan.targets) or plan_discovery(plan.requested_subnet) != plan):
        raise ValueError('Expected exact validated plan')
    return _checked(CollectionData(plan, _time(absolute_end), tuple(ProbeSlot(ip, 'queued', None) for ip in plan.targets), False, None, None))


def _slot(data, target):
    _checked(data)
    if type(target) is not str or target not in data.plan.targets:
        raise ValueError('Expected exact in-scope target')
    return data.plan.targets.index(target)


def _replace_slot(data, index, state, status=None):
    slots = data.slots[:index] + (ProbeSlot(data.slots[index].target, state, status),) + data.slots[index + 1:]
    return _checked(data._replace(slots=slots))


def retire_collection_data(data, failure=None):
    """Retain first failure plus first control/allocation failure independently.

    The first failure never disappears. A later control or MemoryError also
    remains available for original-caller propagation; nothing is raised here.
    """
    _checked(data)
    if failure is not None and not isinstance(failure, BaseException):
        raise ValueError('Expected exact failure object')
    priority = data.first_priority_failure
    if priority is None and failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
        priority = failure
    return _checked(data._replace(retired=True,
                                 first_failure=data.first_failure if data.first_failure is not None else failure,
                                 first_priority_failure=priority))


def collection_failure_data(data):
    """Select retained control/allocation failure, else first ordinary failure.

    This selects an object only. A future original caller still owes actual
    propagation, all finalizers, and every independently retained native duty.
    """
    _checked(data)
    return data.first_priority_failure if data.first_priority_failure is not None else data.first_failure


def issue_probe_data(data, target, now):
    """Retain an issued slot before a future caller could dispatch it.

    A supplied end crossing returns retired DATA with no new issued slot.
    Neither a validated timestamp nor this transition authorizes dispatch.
    """
    index = _slot(data, target)
    _time(now)
    if data.retired:
        raise ValueError('Retired collection cannot issue')
    if now >= data.absolute_end:
        return retire_collection_data(data, TimeoutError('Original supplied end reached'))
    if data.slots[index].state != 'queued':
        raise ValueError('Each target may be issued only once')
    if sum(slot.state in _OCCUPIED for slot in data.slots) >= MAX_OCCUPIED:
        raise ValueError('All occupied slots must count against capacity')
    return _replace_slot(data, index, 'issued')


def record_owned_data(data, target):
    """Record a supplied return even after retirement, preserving its duty."""
    index = _slot(data, target)
    # A return may arrive after retirement requested termination of an issued
    # dispatch. Keep that request and its occupied slot; never regress to owned.
    # No actual process handle is accepted or released by this DATA model.
    if data.slots[index].state == 'terminating':
        return data
    if data.slots[index].state not in ('issued', 'unknown'):
        raise ValueError('Expected an outstanding dispatch return')
    return _replace_slot(data, index, 'owned')


def request_termination_data(data, target):
    """Model a termination request; never call kill or imply closure."""
    index = _slot(data, target)
    if not data.retired or data.slots[index].state not in ('issued', 'owned', 'terminating', 'unknown'):
        raise ValueError('Expected retired outstanding duty')
    if data.slots[index].state == 'unknown':
        return data
    return _replace_slot(data, index, 'terminating')


def retain_unknown_data(data, target, failure):
    """A lost/failed return retires issuance without freeing occupied DATA."""
    index = _slot(data, target)
    if data.slots[index].state not in _OCCUPIED:
        raise ValueError('Expected outstanding duty')
    if not isinstance(failure, BaseException):
        raise ValueError('Expected exact failure object')
    retired = retire_collection_data(data, failure)
    return _replace_slot(retired, index, 'unknown')


def record_closed_data(data, target, returncode):
    """Record supplied closed-event DATA; this is not a physical receipt.

    A future original custodian must independently verify process/target and
    closure before using such an event. No native adapter is provided here.
    """
    index = _slot(data, target)
    if data.slots[index].state not in _OCCUPIED or type(returncode) is not int:
        raise ValueError('Expected outstanding duty and exact supplied exit code')
    status = {0: 'responding', 1: 'no_response'}.get(returncode, 'unavailable')
    return _replace_slot(data, index, 'reported_closed', status)


def collection_data_summary(data):
    """Only supplied counters; no release, publication or physical authority."""
    _checked(data)
    return dict(queued=sum(s.state == 'queued' for s in data.slots),
                occupied=sum(s.state in _OCCUPIED for s in data.slots),
                unknown=sum(s.state == 'unknown' for s in data.slots),
                reported_closed=sum(s.state == 'reported_closed' for s in data.slots),
                retired=data.retired, physical_closure_verified=False,
                positive_publication_authorized=False)
