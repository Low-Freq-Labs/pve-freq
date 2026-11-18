"""Private discovery scope/result DATA; contains no probe or callback executor.

Supplied observations do not authenticate a host, establish inventory, reserve
an address or authorize a scan. The current adapter emits unavailable rows.
Actual probe acquisition requires a separate original operation owner with
bounded spawn/wait/cancel/reap and qualified platform/profile correspondence.
"""
import ipaddress
import math
from typing import NamedTuple


class DiscoveryPlan(NamedTuple):
    requested_subnet: str
    network: str
    targets: tuple


class ProbeObservation(NamedTuple):
    ip: str
    status: str


def plan_discovery(subnet):
    """One explicit ASCII IPv4 three-octet prefix or strict network /24."""
    if type(subnet) is not str or len(subnet) > 64 or not subnet.isascii():
        raise ValueError('Expected one explicit IPv4 prefix or network /24')
    requested = subnet.strip()
    if not requested or any(ord(c) < 32 or ord(c) == 127 for c in requested):
        raise ValueError('Expected one explicit IPv4 prefix or network /24')
    candidate = requested
    if len(requested.split('.')) == 3 and '/' not in requested:
        candidate += '.0/24'
    if '/' not in candidate:
        raise ValueError('Expected one explicit IPv4 prefix or network /24')
    try:
        network = ipaddress.ip_network(candidate, strict=True)
    except ValueError:
        raise ValueError('Expected one explicit IPv4 prefix or network /24') from None
    if network.version != 4 or network.prefixlen != 24:
        raise ValueError('Only an explicit IPv4 network /24 is supported')
    targets = tuple(str(ip) for ip in network.hosts())
    assert len(targets) == 254
    return DiscoveryPlan(requested, str(network), targets)


def project_observation(plan, observations, reported_at):
    """Project bounded supplied rows; missing observations remain unavailable.

    This calls no external observer. The timestamp is supplied report metadata,
    not proof that a physical observation occurred. A complete observation set
    still cannot establish complete inventory or authoritative host absence.
    """
    if type(plan) is not DiscoveryPlan or plan_discovery(plan.requested_subnet) != plan:
        raise ValueError('Expected an exact validated discovery plan')
    if type(observations) not in (tuple, list) or len(observations) > 254:
        raise ValueError('Expected bounded supplied observations')
    if (type(reported_at) not in (int, float) or not 0 < reported_at <= 9007199254740991 or
            not math.isfinite(reported_at)):
        raise ValueError('Expected finite positive report metadata')
    targets = set(plan.targets)
    supplied = {}
    for row in observations:
        if type(row) is not ProbeObservation or type(row.ip) is not str or row.ip not in targets or row.ip in supplied:
            raise ValueError('Expected unique in-scope supplied observations')
        if type(row.status) is not str or row.status not in ('responding', 'no_response', 'unavailable'):
            raise ValueError('Expected explicit responding, no_response or unavailable')
        supplied[row.ip] = row.status
    rows = [dict(ip=ip, status=supplied.get(ip, 'unavailable')) for ip in plan.targets]
    observed = sum(row['status'] != 'unavailable' for row in rows)
    responding = sum(row['status'] == 'responding' for row in rows)
    complete = observed == 254
    state = ('observed' if responding else 'no_responses') if complete else ('partial' if observed else 'unavailable')
    return dict(schema='discovery-observation-v1', requested_subnet=plan.requested_subnet,
                scope=dict(network=plan.network, first=plan.targets[0], last=plan.targets[-1], total=254, method='icmp_echo'),
                targets=rows, observed=observed, responding=responding, unavailable=254 - observed,
                complete=complete, status=state, observed_at=reported_at, inventory_complete=False, adopted=False)


def unavailable_discovery(subnet, reported_at):
    """Current adapter: no collector authority or fallback, all rows unavailable."""
    return project_observation(plan_discovery(subnet), (), reported_at)
