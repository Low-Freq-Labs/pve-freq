"""Unexecuted registry ownership fixtures; no socket or credentials."""
import unittest

from freq.services.node_read_profile import WireTarget
from freq.services.node_read_registry import (
    LeaseSlot, MAX_GENERATION, NodeReadRegistry, TargetSpec,
)


def spec(key="node"):
    return TargetSpec(key, WireTarget("192.0.2.1", "node.invalid", "node"),
                      "parser-v1", "trust-v1", 0, 0, object(), object(), object())


class RegistryTests(unittest.TestCase):
    def test_original_record_retires_on_equal_replacement(self):
        registry = NodeReadRegistry()
        value = spec()
        registry.publish((value,))
        slot = LeaseSlot()
        registry.acquire_into(slot, "node", "reference")
        original = slot._record
        self.assertTrue(registry.current(slot))
        registry.publish((value,))
        self.assertFalse(registry.current(slot))
        self.assertIs(slot._record, original)
        with self.assertRaises(ValueError):
            registry.publish((value,))
        slot.release()
        registry.publish((value,))

    def test_empty_replacement_retires_availability(self):
        registry = NodeReadRegistry()
        registry.publish((spec(),))
        registry.publish(())
        with self.assertRaises(ValueError):
            registry.acquire_into(LeaseSlot(), "node", "invocation")

    def test_publication_count_and_duplicates(self):
        registry = NodeReadRegistry()
        values = tuple(spec(str(i)) for i in range(1024))
        registry.publish(values)
        with self.assertRaises(ValueError):
            registry.publish(values + (spec("extra"),))
        with self.assertRaises(ValueError):
            registry.publish((values[0], values[0]))
        self.assertFalse(registry._busy)
        self.assertEqual(len(registry._current.records), 1024)
        self.assertIsNone(registry._candidate)

    def test_no_iterator_consumption(self):
        calls = []
        def values():
            calls.append("iterated")
            yield spec()
        with self.assertRaises(ValueError):
            NodeReadRegistry().publish(values())
        self.assertEqual(calls, [])

    def test_reference_cap_and_once_release(self):
        registry = NodeReadRegistry()
        registry.publish((spec(),))
        slots = [LeaseSlot() for _ in range(1024)]
        for slot in slots:
            registry.acquire_into(slot, "node", "reference")
        with self.assertRaises(ValueError):
            registry.acquire_into(LeaseSlot(), "node", "reference")
        for slot in slots:
            slot.release()
            slot.release()
        self.assertEqual(registry._references, 0)
        self.assertEqual(registry._current.leases, 0)

    def test_invocation_cap_independent_of_reference_cap(self):
        registry = NodeReadRegistry()
        registry.publish((spec(),))
        slots = [LeaseSlot() for _ in range(64)]
        for slot in slots:
            registry.acquire_into(slot, "node", "invocation")
        with self.assertRaises(ValueError):
            registry.acquire_into(LeaseSlot(), "node", "invocation")
        reference = LeaseSlot()
        registry.acquire_into(reference, "node", "reference")
        reference.release()
        for slot in slots:
            slot.release()
        self.assertEqual(registry._invocations, 0)

    def test_generation_exhaustion_disables_old_availability(self):
        registry = NodeReadRegistry()
        registry.publish((spec(),))
        slot = LeaseSlot()
        registry.acquire_into(slot, "node", "reference")
        registry._generation = MAX_GENERATION
        with self.assertRaises(ValueError):
            registry.publish(())
        self.assertFalse(registry.current(slot))
        self.assertTrue(registry._disabled)
        slot.release()

    def test_invalid_candidate_keeps_original_table(self):
        registry = NodeReadRegistry()
        registry.publish((spec(),))
        original = registry._current
        with self.assertRaises(ValueError):
            registry.publish((spec(), object()))
        self.assertIs(registry._current, original)
        self.assertIsNone(registry._candidate)
        self.assertFalse(registry._busy)

    def test_slot_already_owned_or_spent_cannot_rebind(self):
        registry = NodeReadRegistry()
        registry.publish((spec(),))
        slot = LeaseSlot()
        registry.acquire_into(slot, "node", "reference")
        with self.assertRaises(ValueError):
            registry.acquire_into(slot, "node", "reference")
        slot.release()
        with self.assertRaises(ValueError):
            registry.acquire_into(slot, "node", "reference")

    def test_target_copy_and_private_representation(self):
        value = spec("PRIVATE_KEY")
        registry = NodeReadRegistry()
        registry.publish((value,))
        record = registry._current.records[0]
        self.assertIsNot(record.spec, value)
        self.assertIsNot(record.spec.wire, value.wire)
        self.assertIs(record.spec.registration, value.registration)
        self.assertNotIn("PRIVATE_KEY", repr(record))
