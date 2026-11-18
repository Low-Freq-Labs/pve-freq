"""Dormant affected-profile format/version transition; never an issuer.

All resource classes, persistence outcomes and clock observations are supplied
fixture data. They do not prove original acquisition, a physical effect,
currentness, deadlines, cleanup or writer exclusion. No public method enables
admission. Format versions below are data records, not original bindings or
preview grants. Positive original-resource/startup/writer integration is absent.

Fixed parsing runs under the same local nonblocking gate as transition updates.
An unexpected/control interruption leaves confirmed effects recorded, affected
formats disabled, and known local transition retirement available. This does not
claim arbitrary-interruption containment or a physical parser budget.
"""
from dataclasses import dataclass
from functools import wraps
import math
from threading import Lock

from .postimages import (PostimageRefused, validate_config_postimage,
                        validate_policy_postimage)


class Refused(Exception):
    pass


def _time(value):
    if type(value) is not float or not math.isfinite(value):
        raise Refused()


def _serialized(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        try:
            acquired = self._gate.acquire(blocking=False)
        except BaseException as error:
            self._valid = False
            if self._gate_error is None:
                self._gate_error = error
            # Unknown ownership cannot justify a speculative release.
            raise
        if not acquired:
            raise Refused()
        first = None
        result = None
        try:
            result = method(self, *args, **kwargs)
        except BaseException as error:
            first = error
        try:
            # One release attempt even after body failure; never retry a lost
            # release return or infer original native closure from local data.
            self._gate.release()
        except BaseException as later:
            self._valid = False
            if self._gate_error is None:
                self._gate_error = later
            if (first is None or issubclass(type(first), Exception) and (
                    not issubclass(type(later), Exception) or
                    not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError))):
                first = later
        if first is not None:
            raise first
        return result
    return invoke


@dataclass(slots=True)
class _Mutation:
    token: object
    mask: int
    end: float
    cutoff: float
    phase: str = "reserved"
    outcome: object = None
    late: bool = False


class DormantCoordinator:
    __slots__ = ("_init_started", "_gate", "_gate_error", "_valid", "_version", "_epochs", "_states",
                 "_formats", "_active", "_history", "_count")

    def __init__(self):
        if hasattr(self, "_init_started"):
            raise Refused()
        self._init_started = True
        self._gate = Lock()
        # First caught local gate fault only, not a complete native error log.
        # It remains retained even when an earlier body control takes priority.
        self._gate_error = None
        self._valid = True
        self._version = 1
        self._epochs = [0, 0]
        self._states = ["unbound", "unbound"]
        self._formats = [None, None]
        self._active = None
        self._history = [None] * 32
        self._count = 0

    @staticmethod
    def _profile(profile):
        if type(profile) is not str or profile not in ("config-v1", "policy-documents-v1"):
            raise Refused()
        return 0 if profile == "config-v1" else 1

    @staticmethod
    def _affected(resource_class):
        if type(resource_class) is not str:
            raise Refused()
        if resource_class in ("freq", "hosts", "configured-cluster"):
            return 3
        if resource_class == "vlans":
            return 1
        if resource_class == "fleet-boundaries":
            return 2
        raise Refused()

    def _original(self, token):
        if self._active is None or token is not self._active.token:
            raise Refused()
        return self._active

    def _disable_affected(self, mutation, state):
        for index in range(2):
            if mutation.mask & (1 << index):
                self._formats[index] = None
                self._states[index] = state

    @_serialized
    def begin(self, resource_class, caller_end, now):
        mask = self._affected(resource_class)
        _time(caller_end)
        _time(now)
        if not self._valid or self._active is not None or self._count >= 32:
            raise Refused()
        end = min(caller_end, now + 10.0)
        cutoff = end - 0.5
        if now >= cutoff:
            raise Refused()
        mutation = _Mutation(object(), mask, end, cutoff)
        for index in range(2):
            if mask & (1 << index):
                self._epochs[index] += 1
        # Clear every affected old format before returning the modeled right.
        # Epoch observations are data only; no preview grant is constructed.
        self._disable_affected(mutation, "fenced")
        self._history[self._count] = resource_class
        self._count += 1
        self._active = mutation
        return mutation.token

    @_serialized
    def mark_started(self, token, now):
        mutation = self._original(token)
        _time(now)
        if not self._valid or mutation.phase != "reserved" or now >= mutation.cutoff:
            raise Refused()
        mutation.phase = "started"

    @_serialized
    def finish_without_postimage(self, token, outcome, now):
        mutation = self._original(token)
        _time(now)
        if (mutation.phase != "started" or type(outcome) is not str or
                outcome not in ("known-no-effect", "uncertain")):
            raise Refused()
        mutation.phase = "settled"
        mutation.outcome = outcome
        mutation.late = now >= mutation.end
        state = "uncertain" if outcome == "uncertain" else "unvalidated"
        self._disable_affected(mutation, state if self._valid else "retired")

    @_serialized
    def finish_confirmed_fixture(self, token, now, *, freq, hosts, vlans, fleet_boundaries):
        """Record a modeled confirmation and run fixed affected format checks.

        No supplied formats/success flags/callbacks are accepted. The same exact
        hosts reference is passed to both fixed parsers, which require native
        immutable bytes. This does not establish an acquired resource cohort.
        Late or invalidated effects still advance the installation version but
        do not publish format records. Caller time is not physical timing proof.
        """
        mutation = self._original(token)
        _time(now)
        if mutation.phase != "started":
            raise Refused()
        # Effect accounting precedes parsing. A parser failure must not lose an
        # already modeled effect or make known local retirement impossible.
        mutation.phase = "settled"
        mutation.outcome = "confirmed"
        mutation.late = now >= mutation.end
        self._version += 1
        self._disable_affected(mutation, "unvalidated" if self._valid else "retired")
        if not self._valid or mutation.late:
            return
        pending = [None, None]
        if mutation.mask & 1:
            try:
                validate_config_postimage(freq, hosts, vlans)
            except PostimageRefused:
                pending[0] = False
            else:
                pending[0] = True
        if mutation.mask & 2:
            try:
                validate_policy_postimage(hosts, fleet_boundaries)
            except PostimageRefused:
                pending[1] = False
            else:
                pending[1] = True
        # Publish the whole affected format map together only after both checks
        # complete. An unexpected exception leaves all affected records absent.
        for index in range(2):
            if mutation.mask & (1 << index):
                self._states[index] = "format-supported-dormant" if pending[index] else "unsupported"
                if pending[index]:
                    self._formats[index] = (self._version, self._epochs[index])

    @_serialized
    def cancel_unstarted(self, token):
        mutation = self._original(token)
        if mutation.phase != "reserved":
            raise Refused()
        mutation.phase = "settled"
        mutation.outcome = "known-no-effect"
        self._disable_affected(mutation, "unvalidated" if self._valid else "retired")

    @_serialized
    def retire_transition(self, token):
        mutation = self._original(token)
        if mutation.phase != "settled" or mutation.outcome not in ("confirmed", "known-no-effect"):
            raise Refused()
        self._active = None

    @_serialized
    def invalidate(self):
        self._valid = False
        for index in range(2):
            self._epochs[index] += 1
            self._formats[index] = None
            self._states[index] = "retired"

    @_serialized
    def admission_allowed(self, profile):
        self._profile(profile)
        return False

    @_serialized
    def snapshot(self):
        active = self._active
        return (self._version, tuple(self._epochs), tuple(self._states),
                tuple(self._formats), self._count,
                None if active is None else (active.mask, active.phase, active.outcome,
                                             active.end, active.cutoff, active.late))
