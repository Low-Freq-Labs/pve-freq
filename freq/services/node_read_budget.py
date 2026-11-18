"""Disabled reservation primitive; no successful-publication refund API yet.

This accounts named payload allowance, not Python/native heap or arbitrary
external references. The service must retain one original ledger for its whole
lifetime. Constructing replacement ledgers is not a recovery mechanism.
"""
import threading


SLOTS = 64
BYTES_PER_SLOT = 9150560
TOTAL_NAMED_BYTES = SLOTS * BYTES_PER_SLOT


class ReservationSlot:
    """Preallocated invocation duty, published before an outer return."""

    __slots__ = ("_budget", "_index", "_spent")

    def __init__(self):
        self._budget = None
        self._index = None
        self._spent = False


class ReservationBudget:
    """Fixed ledger which stores only exact duty objects, never exceptions.

    All acquired charges remain occupied in this initial primitive, including
    provisional successes. An integrated original completion owner is required
    before adding any successful-release operation.
    """

    __slots__ = ("_lock", "_owners")

    def __init__(self):
        self._lock = threading.Lock()
        self._owners = [None] * SLOTS

    def reserve_into(self, slot):
        if type(slot) is not ReservationSlot:
            raise ValueError("node reservation unavailable")
        with self._lock:
            if slot._budget is not None or slot._spent:
                raise ValueError("node reservation unavailable")
            for index, owner in enumerate(self._owners):
                if owner is None:
                    # Slot and ledger are exact internal objects: these writes
                    # invoke no external callback and allocate no payload.
                    self._owners[index] = slot
                    slot._index = index
                    slot._budget = self
                    return
            raise ValueError("node reservation unavailable")

    def current(self, slot):
        if type(slot) is not ReservationSlot:
            return False
        with self._lock:
            return (slot._budget is self and not slot._spent
                    and type(slot._index) is int
                    and 0 <= slot._index < SLOTS
                    and self._owners[slot._index] is slot)

    def retain(self, slot):
        """Consume the original duty without freeing its conservative charge."""
        if type(slot) is not ReservationSlot:
            raise ValueError("node reservation unavailable")
        with self._lock:
            if (slot._budget is not self or type(slot._index) is not int
                    or not 0 <= slot._index < SLOTS
                    or self._owners[slot._index] is not slot):
                raise ValueError("node reservation unavailable")
            slot._spent = True
