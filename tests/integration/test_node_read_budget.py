"""Prepared offline budget fixtures; not evidence of integrated admission."""
import unittest

from freq.services.node_read_budget import ReservationBudget, ReservationSlot


class BudgetTests(unittest.TestCase):
    def test_retained_failures_exhaust_original_service(self):
        budget = ReservationBudget()
        slots = [ReservationSlot() for _ in range(64)]
        for slot in slots:
            budget.reserve_into(slot)
            budget.retain(slot)
            budget.retain(slot)
        with self.assertRaises(ValueError):
            budget.reserve_into(ReservationSlot())

    def test_lost_outer_return_preserves_original_duty(self):
        budget = ReservationBudget()
        slot = ReservationSlot()

        def acquire_then_fail():
            budget.reserve_into(slot)
            raise RuntimeError("fixture outer return lost")

        with self.assertRaises(RuntimeError):
            acquire_then_fail()
        self.assertTrue(budget.current(slot))
        budget.retain(slot)
        self.assertFalse(budget.current(slot))
        with self.assertRaises(ValueError):
            budget.reserve_into(slot)

    def test_copied_identity_cannot_consume_original(self):
        budget = ReservationBudget()
        original = ReservationSlot()
        budget.reserve_into(original)
        copied = ReservationSlot()
        copied._budget = original._budget
        copied._index = original._index
        with self.assertRaises(ValueError):
            budget.retain(copied)
        self.assertTrue(budget.current(original))
        self.assertFalse(budget.current(copied))

    def test_other_ledger_cannot_consume_original(self):
        budget = ReservationBudget()
        other = ReservationBudget()
        slot = ReservationSlot()
        budget.reserve_into(slot)
        with self.assertRaises(ValueError):
            other.retain(slot)
        self.assertTrue(budget.current(slot))

    def test_provisional_success_does_not_free_capacity(self):
        budget = ReservationBudget()
        slots = [ReservationSlot() for _ in range(64)]
        for slot in slots:
            budget.reserve_into(slot)
        self.assertTrue(all(budget.current(slot) for slot in slots))
        with self.assertRaises(ValueError):
            budget.reserve_into(ReservationSlot())
