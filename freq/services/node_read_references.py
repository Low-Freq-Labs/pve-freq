"""Unwired node reference leases; application authentication remains external.

Authenticated callers must supply a fresh ReferenceCleanup and drain it only
after releasing their original authentication lock. This store takes registry
then reference locks; it never performs provider effects. Legacy calls without
a cleanup owner must not be made under an external ownership lock.
No browser value is interpreted as a target key or endpoint.
"""
from dataclasses import dataclass, field
import secrets
import threading
import time

from .node_read_registry import NodeReadRegistry, LeaseSlot


def _refuse():
    raise ValueError("node reference unavailable")


def _reference(value):
    return (type(value) is str and len(value) == 32
            and all(c in "0123456789abcdef" for c in value))


class ReferenceCleanup:
    """Caller preallocates before auth locking; drain outside all owner locks.

    One owner per store operation, with1024 fixed original-owner slots.
    Detached entries retain their session references until outside-lock drain.
    The caller must not drain concurrently with the store operation. It is consumed
    before cleanup attempts and cannot be reused, even after uncertain release.
    """
    __slots__ = ("_leases", "_claimed", "_spent")

    def __init__(self):
        self._leases = [None] * 1024
        self._claimed = False
        self._spent = False

    def _claim(self):
        if self._claimed or self._spent:
            _refuse()
        self._claimed = True

    def drain(self):
        if self._spent:
            return
        self._spent = True
        first = None
        for index in range(1024):
            owner = self._leases[index]
            self._leases[index] = None
            lease = owner.lease if type(owner) is _Entry else owner
            if lease is not None:
                try:
                    lease.release()
                except BaseException as error:
                    if first is None or (isinstance(first, Exception)
                                         and not isinstance(error, Exception)):
                        first = error
        if first is not None:
            raise first


def _claim_cleanup(cleanup):
    if cleanup is not None:
        if type(cleanup) is not ReferenceCleanup:
            _refuse()
        cleanup._claim()


@dataclass(frozen=True, slots=True, repr=False)
class _Entry:
    session: object = field(repr=False)
    lease: LeaseSlot = field(repr=False)
    expires: float
    binding: bool


class NodeReadReferences:
    """At most1024 combined entries, each owning its original registry lease.

    Explicit expiry/session retirement detaches entries under locks and then
    releases leases outside both locks. No automatic eviction of live entries.
    Authentication, response admission and registration authority are not
    established by a successful store operation.
    """

    __slots__ = ("_registry", "_lock", "_entries")

    def __init__(self, registry):
        if type(registry) is not NodeReadRegistry:
            _refuse()
        self._registry = registry
        self._lock = threading.Lock()
        self._entries = {}

    def _key_candidates(self):
        # Entropy requests occur before ownership locks, with bounded attempts.
        return tuple(secrets.token_hex(16) for _ in range(4))

    def _key_locked(self, candidates):
        for key in candidates:
            if _reference(key) and key not in self._entries:
                return key
        _refuse()

    def _capacity_locked(self, session, binding):
        if (len(self._entries) >= 1024
                or sum(e.session is session and e.binding is binding
                       for e in self._entries.values()) >= (16 if binding else 64)):
            _refuse()

    def issue_selection(self, session, target_key, *, cleanup=None):
        """Internal inventory issuer only; session identity is not authority."""
        if type(session) is not dict or type(target_key) is not str:
            _refuse()
        if not 1 <= len(target_key) <= 128:
            _refuse()
        _claim_cleanup(cleanup)
        candidates = self._key_candidates()
        lease = LeaseSlot()
        if cleanup is not None:
            cleanup._leases[0] = lease
        published = False
        registry = self._registry
        try:
            with registry._lock:
                with self._lock:
                    now = time.monotonic()
                    self._capacity_locked(session, False)
                    key = self._key_locked(candidates)
                    if registry._current is None:
                        _refuse()
                    record = next((r for r in registry._current.records
                                   if r.spec.key == target_key), None)
                    entry = _Entry(session, lease, now + 30.0, False)
                    registry._acquire_record_locked(lease, record, "reference")
                    self._entries[key] = entry
                    published = True
                    if cleanup is not None:
                        cleanup._leases[0] = None
                    return key
        except BaseException as fault:
            if not published and cleanup is None:
                try:
                    lease.release()
                except BaseException as cleanup:
                    if isinstance(fault, Exception) and not isinstance(cleanup, Exception):
                        raise cleanup
            raise

    def bind(self, session, selection_ref, *, cleanup=None):
        if type(session) is not dict or not _reference(selection_ref):
            _refuse()
        _claim_cleanup(cleanup)
        candidates = self._key_candidates()
        lease = LeaseSlot()
        if cleanup is not None:
            cleanup._leases[0] = lease
        published = False
        registry = self._registry
        try:
            with registry._lock:
                with self._lock:
                    now = time.monotonic()
                    selected = self._entries.get(selection_ref)
                    if (selected is None or selected.binding
                            or selected.session is not session
                            or not now < selected.expires):
                        _refuse()
                    self._capacity_locked(session, True)
                    key = self._key_locked(candidates)
                    # Do not renew selection expiry through binding.
                    remaining = int((selected.expires - now) * 1000)
                    if remaining <= 0:
                        _refuse()
                    entry = _Entry(session, lease, selected.expires, True)
                    registry._acquire_record_locked(
                        lease, selected.lease._record, "reference")
                    self._entries[key] = entry
                    published = True
                    if cleanup is not None:
                        cleanup._leases[0] = None
                    return key, remaining
        except BaseException as fault:
            if not published and cleanup is None:
                try:
                    lease.release()
                except BaseException as cleanup:
                    if isinstance(fault, Exception) and not isinstance(cleanup, Exception):
                        raise cleanup
            raise

    def consume_into(self, session, binding_ref, invocation_lease, *, cleanup=None):
        """Spend owned binding before publishing an original invocation duty.

        The caller preallocates invocation_lease and must release it even if
        this method raises after acquisition. No transport effect occurs here.
        """
        if (type(session) is not dict or not _reference(binding_ref)
                or type(invocation_lease) is not LeaseSlot):
            _refuse()
        _claim_cleanup(cleanup)
        bound = None
        fault = None
        expires = None
        registry = self._registry
        try:
            with registry._lock:
                with self._lock:
                    candidate = self._entries.get(binding_ref)
                    if (candidate is None or not candidate.binding
                            or candidate.session is not session):
                        _refuse()
                    bound = candidate
                    if cleanup is not None:
                        cleanup._leases[0] = bound
                    del self._entries[binding_ref]
                    now = time.monotonic()
                    if not now < bound.expires:
                        _refuse()
                    registry._acquire_record_locked(
                        invocation_lease, bound.lease._record, "invocation")
                    expires = bound.expires
        except BaseException as error:
            fault = error
        finally:
            if bound is not None and cleanup is None:
                try:
                    bound.lease.release()
                except BaseException as error:
                    if fault is None or (isinstance(fault, Exception)
                                         and not isinstance(error, Exception)):
                        fault = error
        if fault is not None:
            raise fault
        return expires

    def retire(self, session=None, *, cleanup=None):
        """Explicitly remove expired entries, or all of one original session."""
        if session is not None and type(session) is not dict:
            _refuse()
        _claim_cleanup(cleanup)
        registry = self._registry
        detached = []
        with registry._lock:
            with self._lock:
                now = time.monotonic()
                keys = [key for key, entry in self._entries.items()
                        if (entry.session is session if session is not None
                            else entry.expires <= now)]
                # Populate bounded custody list before changing the store.
                detached = [self._entries[key] for key in keys]
                if cleanup is not None:
                    for index, entry in enumerate(detached):
                        cleanup._leases[index] = entry
                for key in keys:
                    del self._entries[key]
        if cleanup is not None:
            return
        first = None
        for entry in detached:
            try:
                entry.lease.release()
            except BaseException as error:
                if first is None or (isinstance(first, Exception)
                                     and not isinstance(error, Exception)):
                    first = error
        if first is not None:
            raise first
