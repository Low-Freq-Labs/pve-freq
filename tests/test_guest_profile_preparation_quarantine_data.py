"""Bounded three-index original preparation quarantine DATA accounting."""
import unittest
from unittest.mock import patch
from test_guest_profile_registration_data import ProfileRegistrationData
from test_guest_profile_original_prepare_data import ProfileOriginalPrepareData
from freq.services import pilot_guest_profile_prepare as source


class ProfilePreparationQuarantineData(unittest.TestCase):
    def setUp(self):
        self.f = ProfileRegistrationData(); self.f.setUp(); self.duty = self.f.duty()
        self.store = self.f.store; self.calls = []
        self.store._quarantine = lambda error: self.calls.append(error) or error

    def call(self, error, index=0):
        return source._quarantine_profile_preparation_error(self.store, self.duty, error, index)

    def test_QP01_each_fixed_index_retains_input_before_existing_call(self):
        errors = [ValueError(), MemoryError(), KeyboardInterrupt()]
        def quarantine(error):
            index = errors.index(error)
            self.assertIs(self.duty.preparation_quarantine_inputs[index], error)
            self.calls.append(error); return error
        self.store._quarantine = quarantine
        for i, error in enumerate(errors): self.assertIs(self.call(error, i), error)
        self.assertEqual(self.calls, errors)
        self.assertEqual(self.duty.preparation_quarantine_returns, errors)

    def test_QP02_raised_allocation_keeps_actual_ordinary_input_and_secondary(self):
        first, later = ValueError(), MemoryError()
        def quarantine(error): self.calls.append(error); raise later
        self.store._quarantine = quarantine
        self.assertIs(self.call(first), later)
        self.assertIs(self.duty.preparation_quarantine_inputs[0], first)
        self.assertIs(self.duty.preparation_quarantine_errors[0], later)
        self.assertIsNone(self.duty.preparation_quarantine_returns[0])

    def test_QP03_foreign_return_kept_without_instance_or_property_hooks(self):
        seen = []; first = MemoryError()
        class Trap:
            def __getattribute__(self, name): seen.append(name); raise AssertionError(name)
        foreign = Trap(); self.store._quarantine = lambda error: foreign
        self.assertIs(self.call(first), first)
        self.assertIs(self.duty.preparation_quarantine_returns[0], foreign)
        self.assertIsInstance(self.duty.preparation_quarantine_errors[0], source._RequestUnavailable)
        self.assertEqual(seen, [])

    def test_QP04_first_control_survives_later_quarantine_control(self):
        first, later = KeyboardInterrupt(), SystemExit()
        self.store._quarantine = lambda error: later
        self.assertIs(self.call(first), first)
        self.assertIs(self.duty.preparation_quarantine_returns[0], later)

    def test_QP05_returned_allocation_becomes_primary_but_keeps_input(self):
        first, later = ValueError(), MemoryError()
        self.store._quarantine = lambda error: later
        self.assertIs(self.call(first), later)
        self.assertIs(self.duty.preparation_quarantine_inputs[0], first)
        self.assertIs(self.duty.preparation_quarantine_returns[0], later)

    def test_QP06_failed_return_cannot_trigger_second_store_call(self):
        first, later = ValueError(), MemoryError()
        def quarantine(error): self.calls.append(error); raise later
        self.store._quarantine = quarantine
        self.assertIs(self.call(first), later); self.assertIs(self.call(first), later)
        self.assertEqual(self.calls, [first])
        self.assertIs(self.duty.preparation_quarantine_repeat_errors[0], first)

    def test_QP07_first_repeat_control_is_retained_without_replaying(self):
        first, later = MemoryError(), KeyboardInterrupt()
        self.assertIs(self.call(first), first); self.assertIs(self.call(later), later)
        self.assertEqual(self.calls, [first])
        self.assertIs(self.duty.preparation_quarantine_repeat_errors[0], later)

    def test_QP08_invalid_fixed_index_or_foreign_error_never_reaches_store(self):
        first = ValueError()
        for index in (True, False, -1, 3, '0'):
            with self.assertRaises(source._RequestUnavailable): self.call(first, index)
        with self.assertRaises(source._RequestUnavailable): self.call(object())
        self.assertEqual(self.calls, [])

    def test_QP09_cross_index_first_control_remains_primary(self):
        first, later = KeyboardInterrupt(), MemoryError()
        self.assertIs(self.call(first, 0), first)
        self.assertIs(self.call(later, 1), first)
        self.assertEqual(self.duty.preparation_quarantine_inputs, [first, later, None])

    def test_QP10_further_distinct_repeat_refuses_without_unbounded_history_claim(self):
        first, later, unsupported = KeyboardInterrupt(), MemoryError(), SystemExit()
        self.assertIs(self.call(first), first); self.assertIs(self.call(later), first)
        with self.assertRaises(KeyboardInterrupt) as caught: self.call(unsupported)
        self.assertIs(caught.exception, first)
        self.assertIs(self.duty.preparation_quarantine_repeat_errors[0], later)
        self.assertEqual(self.calls, [first])

    def test_QP11_actual_prepare_wrapper_retains_corruption_before_quarantine_allocation(self):
        f = ProfileOriginalPrepareData(); f.setUp()
        first, later = source._CorruptProfileSource(), MemoryError()
        def quarantine(error):
            self.assertIs(f.duty.preparation_quarantine_inputs[0], first)
            raise later
        f.store._quarantine = quarantine
        with patch.object(source, '_registered_profile_context_data_locked', side_effect=first):
            with self.assertRaises(MemoryError) as caught: f.prepare()
        self.assertIs(caught.exception, later)
        self.assertIs(f.duty.preparation_quarantine_errors[0], later)
        self.assertEqual(f.events[-1], 'exit')
        self.assertEqual(f.duty.slots[0].construction, 'unattempted')

    def test_QP12_late_guard_control_does_not_erase_body_and_quarantine_references(self):
        f = ProfileOriginalPrepareData(); f.setUp()
        first, later, control = source._CorruptProfileSource(), MemoryError(), KeyboardInterrupt()
        f.exit_error = control
        def quarantine(error): raise later
        f.store._quarantine = quarantine
        with patch.object(source, '_registered_profile_context_data_locked', side_effect=first):
            with self.assertRaises(KeyboardInterrupt) as caught: f.prepare()
        self.assertIs(caught.exception, control)
        self.assertIs(f.duty.preparation_quarantine_inputs[0], first)
        self.assertIs(f.duty.preparation_quarantine_errors[0], later)
        self.assertEqual(f.duty.slots[0].construction, 'unattempted')
