"""Local fixed-call preparation ledger; original service gates are substituted."""
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from test_guest_profile_captured_duty_cleanup_data import ProfileCapturedDutyCleanupData
from freq.services import pilot_guest_profile_preparation_caller as source
from freq.services import pilot_guest_profile_section_slot as slots


class ProfilePreparationCallerData(unittest.TestCase):
    def setUp(self):
        self.f = ProfileCapturedDutyCleanupData(); self.f.setUp()
        self.original, self.store, self.handler = self.f.original, self.f.store, self.f.f.handler
        self.begin, self.acquired = self.f.duty.begin, self.f.duty
        self.original.guest_response = None
        self.original.profile_preparation = None
        self.original.profile_preparation_capture = 'unattempted'
        self.original.profile_preparation_capture_error = None
        self.original.profile_custody_started = False
        self.events = []; self.cleanup_value = object()

    def begin_call(self, store, handler):
        duty = self.original.profile_preparation
        self.assertEqual(duty.states[0], 'call-pending')
        self.assertTrue(self.original.profile_custody_started)
        self.events.append('begin'); self.original.guest_response = self.begin
        return self.begin

    def register_call(self, store, handler):
        duty = self.original.profile_preparation
        self.assertEqual(duty.states[1], 'call-pending')
        self.assertIs(duty.inputs[1], self.begin)
        self.events.append('register'); self.original.guest_response = self.acquired
        return self.acquired

    def section_call(self, store, handler, index):
        duty = self.original.profile_preparation
        self.assertEqual(duty.states[index + 2], 'call-pending')
        self.assertIs(duty.inputs[index + 2], self.acquired)
        self.events.append(index)
        return slots._prepare_profile_section_slot_data(self.acquired, index)

    def cleanup_call(self, store, handler):
        self.assertEqual(self.original.profile_preparation.cleanup_state, 'call-pending')
        self.events.append('cleanup'); return self.cleanup_value

    @contextmanager
    def ports(self):
        with patch.object(source, '_owned_store', return_value=self.f.owner), \
             patch.object(self.store._broker.__class__, '_owned', return_value=self.original), \
             patch.object(source, 'begin_profile', self.begin_call), \
             patch.object(source, 'register_profile_acquisition', self.register_call), \
             patch.object(source, 'prepare_registered_profile_section', self.section_call), \
             patch.object(source, 'retire_profile_request_duty', self.cleanup_call):
            yield

    def call(self):
        return source.prepare_profile_request(self.store, self.handler)

    def test_PP01_fixed_five_returns_and_three_real_pure_holder_constructors(self):
        with self.ports(): duty = self.call()
        self.assertEqual(self.events, ['begin', 'register', 0, 1, 2])
        self.assertEqual(duty.states, ['call-returned'] * 5)
        self.assertIs(duty.returns[0], self.begin); self.assertIs(duty.returns[1], self.acquired)
        self.assertEqual(duty.returns[2:], list(self.acquired.slots))
        self.assertTrue(all(slot.construction == 'constructor-returned' for slot in self.acquired.slots))
        self.assertEqual(duty.phase, 'prepared-private'); self.assertEqual(duty.cleanup_state, 'unattempted')

    def test_PP02_begin_lost_return_retains_pending_and_actual_error_then_cleanup(self):
        error = KeyboardInterrupt()
        def lost(store, handler): self.begin_call(store, handler); raise error
        with self.ports(), patch.object(source, 'begin_profile', lost):
            with self.assertRaises(KeyboardInterrupt) as caught: self.call()
        duty = self.original.profile_preparation
        self.assertIs(caught.exception, error); self.assertIs(duty.errors[0], error)
        self.assertEqual(duty.states, ['call-pending'] + ['unattempted'] * 4)
        self.assertIs(duty.cleanup_return, self.cleanup_value)
        self.assertEqual(self.events, ['begin', 'cleanup'])

    def test_PP03_registration_lost_return_retains_same_acquired_original(self):
        error = MemoryError()
        def lost(store, handler): self.register_call(store, handler); raise error
        with self.ports(), patch.object(source, 'register_profile_acquisition', lost):
            with self.assertRaises(MemoryError) as caught: self.call()
        duty = self.original.profile_preparation
        self.assertIs(caught.exception, error); self.assertIs(self.original.guest_response, self.acquired)
        self.assertEqual(duty.states, ['call-returned', 'call-pending'] + ['unattempted'] * 3)
        self.assertIsNone(duty.returns[1]); self.assertEqual(self.events, ['begin', 'register', 'cleanup'])

    def test_PP04_lost_first_section_return_retains_known_holder_without_next_stage(self):
        error = MemoryError()
        def lost(store, handler, index): self.section_call(store, handler, index); raise error
        with self.ports(), patch.object(source, 'prepare_registered_profile_section', lost):
            with self.assertRaises(MemoryError): self.call()
        duty = self.original.profile_preparation
        self.assertEqual(duty.states[2:], ['call-pending', 'unattempted', 'unattempted'])
        self.assertEqual(self.acquired.slots[0].construction, 'constructor-returned')
        self.assertEqual(self.acquired.slots[1].construction, 'unattempted')
        self.assertIs(duty.errors[2], error)

    def test_PP05_lost_second_section_return_preserves_first_actual_return(self):
        error = KeyboardInterrupt()
        def lost(store, handler, index):
            value = self.section_call(store, handler, index)
            if index == 1: raise error
            return value
        with self.ports(), patch.object(source, 'prepare_registered_profile_section', lost):
            with self.assertRaises(KeyboardInterrupt): self.call()
        duty = self.original.profile_preparation
        self.assertIs(duty.returns[2], self.acquired.slots[0])
        self.assertEqual(duty.states[2:], ['call-returned', 'call-pending', 'unattempted'])

    def test_PP06_cleanup_control_outranks_preparation_allocation_and_both_retained(self):
        allocation, control = MemoryError(), KeyboardInterrupt()
        def body(store, handler): raise allocation
        def clean(store, handler): raise control
        with self.ports(), patch.object(source, 'begin_profile', body), \
             patch.object(source, 'retire_profile_request_duty', clean):
            with self.assertRaises(KeyboardInterrupt) as caught: self.call()
        duty = self.original.profile_preparation
        self.assertIs(caught.exception, control); self.assertIs(duty.errors[0], allocation)
        self.assertIs(duty.cleanup_error, control); self.assertEqual(duty.cleanup_state, 'call-pending')

    def test_PP07_first_control_survives_cleanup_allocation(self):
        control, allocation = KeyboardInterrupt(), MemoryError()
        def body(store, handler): raise control
        def clean(store, handler): raise allocation
        with self.ports(), patch.object(source, 'begin_profile', body), \
             patch.object(source, 'retire_profile_request_duty', clean):
            with self.assertRaises(KeyboardInterrupt) as caught: self.call()
        self.assertIs(caught.exception, control)
        self.assertIs(self.original.profile_preparation.cleanup_error, allocation)

    def test_PP08_foreign_return_retained_without_type_or_property_hooks(self):
        seen = []
        class Trap:
            def __getattribute__(self, name): seen.append(name); raise AssertionError(name)
        foreign = Trap()
        with self.ports(), patch.object(source, 'begin_profile', return_value=foreign):
            with self.assertRaises(source._RequestUnavailable): self.call()
        self.assertIs(self.original.profile_preparation.returns[0], foreign)
        self.assertEqual(self.original.profile_preparation.states[0], 'call-returned')
        self.assertEqual(seen, []); self.assertEqual(self.events, ['cleanup'])

    def test_PP09_distinct_registration_return_cannot_become_current_duty(self):
        other = source._ProfileAcquisitionDuty.__new__(source._ProfileAcquisitionDuty)
        other.original, other.begin = self.original, self.begin
        with self.ports(), patch.object(source, 'register_profile_acquisition', return_value=other):
            with self.assertRaises(source._RequestUnavailable): self.call()
        duty = self.original.profile_preparation
        self.assertIs(duty.returns[1], other); self.assertIs(self.original.guest_response, self.begin)
        self.assertEqual(duty.states[2:], ['unattempted'] * 3)

    def test_PP10_distinct_section_return_never_adopted(self):
        other = source._ProfileSectionSlot('status')
        with self.ports(), patch.object(source, 'prepare_registered_profile_section', return_value=other):
            with self.assertRaises(source._RequestUnavailable): self.call()
        self.assertIs(self.original.profile_preparation.returns[2], other)
        self.assertIsNot(self.acquired.slots[0], other)
        self.assertEqual(self.acquired.slots[0].construction, 'unattempted')

    def test_PP11_changed_last_original_response_cannot_complete_private_preparation(self):
        foreign = object()
        def changed(store, handler, index):
            value = self.section_call(store, handler, index)
            if index == 2: self.original.guest_response = foreign
            return value
        with self.ports(), patch.object(source, 'prepare_registered_profile_section', changed):
            with self.assertRaises(source._RequestUnavailable): self.call()
        duty = self.original.profile_preparation
        self.assertEqual(duty.states, ['call-returned'] * 5)
        self.assertEqual(duty.phase, 'unresolved'); self.assertIs(self.original.guest_response, foreign)

    def test_PP12_successful_private_preparation_never_repeats_or_refunds(self):
        with self.ports():
            duty = self.call()
            with self.assertRaises(source._RequestUnavailable): self.call()
        self.assertIs(self.original.profile_preparation, duty)
        self.assertEqual(self.events, ['begin', 'register', 0, 1, 2])
        self.assertTrue(self.original.profile_custody_started)

    def test_PP13_failed_preparation_rethrows_same_error_without_repeating_cleanup(self):
        error = MemoryError()
        def lost(store, handler): self.begin_call(store, handler); raise error
        with self.ports(), patch.object(source, 'begin_profile', lost):
            for _ in range(2):
                with self.assertRaises(MemoryError) as caught: self.call()
                self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['begin', 'cleanup'])

    def test_PP14_partial_constructor_pre_retained_and_not_retried(self):
        error = MemoryError(); seen = []
        def fail(duty, store, original, handler):
            self.assertIs(original.profile_preparation, duty)
            self.assertTrue(original.profile_custody_started); seen.append(duty)
            duty.original = original; raise error
        with self.ports(), patch.object(source._ProfilePreparationCaller, '__init__', fail):
            for _ in range(2):
                with self.assertRaises(MemoryError): self.call()
        self.assertEqual(seen, [self.original.profile_preparation])
        self.assertEqual(self.original.profile_preparation_capture, 'constructor-pending')
        self.assertIs(self.original.profile_preparation_capture_error, error)
        self.assertEqual(self.events, [])

    def test_PP15_allocation_error_retained_before_any_fixed_call(self):
        error = MemoryError()
        constructor = SimpleNamespace(__new__=lambda cls: (_ for _ in ()).throw(error))
        with self.ports(), patch.object(source, '_ProfilePreparationCaller', constructor):
            with self.assertRaises(MemoryError) as caught: self.call()
        self.assertIs(caught.exception, error); self.assertIsNone(self.original.profile_preparation)
        self.assertIs(self.original.profile_preparation_capture_error, error)
        self.assertTrue(self.original.profile_custody_started); self.assertEqual(self.events, [])

    def test_PP16_existing_response_refuses_before_new_preparation_or_begin(self):
        other = object(); self.original.guest_response = other
        with self.ports():
            with self.assertRaises(source._RequestUnavailable): self.call()
        self.assertIsNone(self.original.profile_preparation)
        self.assertIs(self.original.guest_response, other); self.assertEqual(self.events, [])
