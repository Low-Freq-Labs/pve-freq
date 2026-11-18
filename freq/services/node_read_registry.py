"""Disabled bounded node registry draft, with no application/auth integration.

External registration/trust/credential owners are references only. Their own
resource contracts and publication writer integration are separate gates.
"""
from dataclasses import dataclass, field
import threading

from .node_read_profile import WireTarget, _ascii


MAX_GENERATION = (1 << 63) - 1
TABLE_BYTES = 1048576


def _refuse():
    raise ValueError("node registry unavailable")


def _generation(value):
    if type(value) is not int or not 0 <= value <= MAX_GENERATION:
        _refuse()


@dataclass(frozen=True, slots=True, repr=False)
class TargetSpec:
    key: str = field(repr=False)
    wire: WireTarget = field(repr=False)
    parser_profile: str = field(repr=False)
    trust_profile: str = field(repr=False)
    trust_generation: int = field(repr=False)
    credential_generation: int = field(repr=False)
    registration: object = field(repr=False)
    trust_owner: object = field(repr=False)
    credential_owner: object = field(repr=False)

    def __post_init__(self):
        _ascii(self.key, 1, 128, r"[A-Za-z0-9_-]+")
        _ascii(self.parser_profile, 1, 128, r"[A-Za-z0-9_.-]+")
        _ascii(self.trust_profile, 1, 128, r"[A-Za-z0-9_.-]+")
        _generation(self.trust_generation)
        _generation(self.credential_generation)
        if type(self.wire) is not WireTarget:
            _refuse()
        object.__setattr__(self, "wire", WireTarget(
            self.wire.endpoint, self.wire.tls_name, self.wire.node))


@dataclass(frozen=True, slots=True, repr=False)
class TargetRecord:
    generation: int
    spec: TargetSpec


class _Table:
    __slots__ = ("generation", "records", "leases")

    def __init__(self, generation):
        self.generation = generation
        self.records = ()
        self.leases = 0


class LeaseSlot:
    """Caller allocates before acquisition; no lease is returned unowned."""

    __slots__ = ("_registry", "_table", "_record", "_kind", "_spent")

    def __init__(self):
        self._registry = None
        self._table = None
        self._record = None
        self._kind = None
        self._spent = False

    def release(self):
        registry = self._registry
        if registry is not None:
            registry.release(self)


class NodeReadRegistry:
    """One current, one retired, one candidate table; no historical ledger.

    Identity checks here are only registry association. Authentication and
    participant generation validation must surround final response admission.
    """

    __slots__ = (
        "_lock", "_current", "_retired", "_candidate", "_busy",
        "_generation", "_disabled", "_references", "_invocations",
    )

    def __init__(self):
        self._lock = threading.Lock()
        self._current = None
        self._retired = None
        self._candidate = None
        self._busy = False
        self._generation = 0
        self._disabled = False
        self._references = 0
        self._invocations = 0

    def publish(self, specs):
        # Validate only count/type before reservation. No user iteration/copy.
        if type(specs) is not tuple or len(specs) > 1024:
            _refuse()
        candidate = None
        detached = None
        copied = None
        copy = None
        with self._lock:
            if self._busy or self._retired is not None or self._disabled:
                _refuse()
            if self._generation == MAX_GENERATION:
                self._disabled = True
                _refuse()
            generation = self._generation + 1
            self._busy = True
        try:
            # The busy flag reserves the sole candidate metadata allowance
            # before table/record copying and any external-owner retention.
            candidate = _Table(generation)
            with self._lock:
                self._candidate = candidate
            copied = []
            seen = set()
            for spec in specs:
                if type(spec) is not TargetSpec:
                    _refuse()
                copy = TargetSpec(
                    spec.key, spec.wire, spec.parser_profile, spec.trust_profile,
                    spec.trust_generation, spec.credential_generation,
                    spec.registration, spec.trust_owner, spec.credential_owner,
                )
                if copy.key in seen:
                    _refuse()
                seen.add(copy.key)
                copied.append(TargetRecord(generation, copy))
            candidate.records = tuple(copied)
            with self._lock:
                self._retired = self._current
                self._current = candidate
                self._candidate = None
                self._generation = generation
                if self._retired is not None and self._retired.leases == 0:
                    detached = self._retired
                    self._retired = None
            # Keep busy through dropping old external-owner references. No
            # destructor or external release runs under the registry lock.
            detached = None
            return generation
        finally:
            with self._lock:
                abandoned = self._candidate
                self._candidate = None
            candidate = None
            copied = None
            copy = None
            abandoned = None
            detached = None
            # A concurrent last lease release may have happened while busy.
            # Drain that zero-lease retired table before clearing busy, under
            # the same lock that decides whether release owns the drain.
            while True:
                with self._lock:
                    if self._retired is not None and self._retired.leases == 0:
                        detached = self._retired
                        self._retired = None
                    else:
                        self._busy = False
                        break
                detached = None

    def acquire_into(self, slot, key, kind):
        if type(slot) is not LeaseSlot:
            _refuse()
        _ascii(key, 1, 128, r"[A-Za-z0-9_-]+")
        if type(kind) is not str or kind not in ("reference", "invocation"):
            _refuse()
        with self._lock:
            if self._busy or self._disabled or self._current is None:
                _refuse()
            if slot._spent or slot._registry is not None:
                _refuse()
            if ((kind == "reference" and self._references >= 1024)
                    or (kind == "invocation" and self._invocations >= 64)):
                _refuse()
            table = self._current
            record = next((r for r in table.records if r.spec.key == key), None)
            if record is None:
                _refuse()
            self._acquire_record_locked(slot, record, kind)

    def _acquire_record_locked(self, slot, record, kind):
        """Internal composition seam; original registry lock must be held.

        The reference owner takes registry then store locks, and calls this
        without releasing either. No helper or external callback follows the
        original-record validation before duty publication.
        """
        if (type(slot) is not LeaseSlot or slot._spent
                or slot._registry is not None or type(kind) is not str
                or kind not in ("reference", "invocation")
                or self._busy or self._disabled or self._current is None):
            _refuse()
        table = self._current
        if not any(candidate is record for candidate in table.records):
            _refuse()
        if ((kind == "reference" and self._references >= 1024)
                or (kind == "invocation" and self._invocations >= 64)):
            _refuse()
        leases = table.leases + 1
        references = self._references + (kind == "reference")
        invocations = self._invocations + (kind == "invocation")
        # All potentially allocating arithmetic precedes publishing the duty.
        slot._registry = self
        slot._table = table
        slot._record = record
        slot._kind = kind
        table.leases = leases
        self._references = references
        self._invocations = invocations

    def current(self, slot):
        if type(slot) is not LeaseSlot:
            return False
        with self._lock:
            return (not self._busy and not self._disabled and not slot._spent
                    and slot._registry is self and slot._table is self._current
                    and slot._record is not None)

    def release(self, slot):
        if type(slot) is not LeaseSlot:
            _refuse()
        detached = None
        with self._lock:
            if slot._spent:
                return
            if slot._registry is not self:
                _refuse()
            table = slot._table
            record = slot._record
            leases = table.leases - 1
            references = self._references - (slot._kind == "reference")
            invocations = self._invocations - (slot._kind == "invocation")
            slot._spent = True
            slot._record = None
            slot._table = None
            slot._registry = None
            table.leases = leases
            self._references = references
            self._invocations = invocations
            if table is self._retired and table.leases == 0 and not self._busy:
                self._busy = True
                detached = self._retired
                self._retired = None
        if detached is not None:
            # Drop all our local record/table aliases while publication is
            # busy, outside the lock; no external close authority is implied.
            record = None
            table = None
            detached = None
            with self._lock:
                self._busy = False
