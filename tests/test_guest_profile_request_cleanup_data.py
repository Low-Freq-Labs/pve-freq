"""Local outside-return fault witnesses; no native original service."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_guest_profile_captured_duty_cleanup_data import ProfileCapturedDutyCleanupData
from freq.services import pilot_guest_profile_request_cleanup as cleanup
from freq.services import pilot_guest_profile_retirement as retirement
from freq.services.cluster_pilot_http import _OriginalRequest


class ProfileRequestCleanupData(unittest.TestCase):
    def setUp(self):
        self.f = ProfileCapturedDutyCleanupData(); self.f.setUp()
        self.store, self.original = self.f.store, self.f.original
        self.handler = self.f.f.handler
        self.original.profile_cleanup = None
        self.original.profile_cleanup_capture = 'unattempted'
        self.original.profile_cleanup_capture_error = None
        self.calls = []

    def call(self):
        with patch.object(retirement, '_owned_store', return_value=self.f.owner):
            return cleanup.retire_profile_request_duty(self.store, self.handler)

    def observe(self, name, value=None, error=None):
        def run(store, handler):
            duty = self.original.profile_cleanup
            index = 0 if name == 'acquisition' else 1
            self.assertEqual(duty.states[index], 'call-pending')
            self.assertIs(store, self.store); self.assertIs(handler, self.handler)
            self.calls.append(name)
            if error is not None:
                raise error
            return value
        return run

    def test_PC01_actual_request_constructor_initializes_retained_ledger_slots(self):
        original = _OriginalRequest(object(), 1.0, '127.0.0.1')
        self.assertIsNone(original.profile_cleanup)
        self.assertEqual(original.profile_cleanup_capture, 'unattempted')
        self.assertIsNone(original.profile_cleanup_capture_error)

    def test_PC02_two_outside_returns_retain_exact_values_and_inputs(self):
        a, b = object(), object()
        with patch.object(cleanup, 'retire_profile_handler_duty', self.observe('acquisition', a)), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin', b)):
            duty = self.call()
        self.assertEqual(self.calls, ['acquisition', 'begin'])
        self.assertEqual(duty.states, ['call-returned'] * 2)
        self.assertIs(duty.inputs[0], self.f.duty); self.assertIs(duty.inputs[1], self.f.duty.begin)
        self.assertIs(duty.returns[0], a); self.assertIs(duty.returns[1], b)
        self.assertEqual(duty.phase, 'calls-returned')

    def test_PC03_begin_only_never_calls_acquisition_retirement(self):
        self.original.guest_response = self.f.duty.begin
        with patch.object(cleanup, 'retire_profile_handler_duty') as acquisition, \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin')):
            duty = self.call()
        acquisition.assert_not_called()
        self.assertEqual(duty.states, ['not-applicable', 'call-returned'])

    def test_PC04_none_retains_no_duty_without_cleanup_or_quarantine(self):
        self.original.guest_response = None
        with patch.object(cleanup, 'retire_profile_handler_duty') as acquisition, \
             patch.object(cleanup, 'retire_profile_begin_handler_duty') as begin:
            duty = self.call()
        acquisition.assert_not_called(); begin.assert_not_called()
        self.assertEqual(duty.states, ['not-applicable'] * 2)
        self.assertEqual(self.f.quarantines, [])

    def test_PC05_control_in_first_cleanup_still_visits_second(self):
        error = KeyboardInterrupt()
        with patch.object(cleanup, 'retire_profile_handler_duty', self.observe('acquisition', error=error)), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin')):
            with self.assertRaises(KeyboardInterrupt) as caught: self.call()
        self.assertIs(caught.exception, error)
        duty = self.original.profile_cleanup
        self.assertEqual(self.calls, ['acquisition', 'begin'])
        self.assertEqual(duty.states, ['call-pending', 'call-returned'])
        self.assertIs(duty.errors[0], error)
        self.assertIs(duty.quarantine_input, error)
        self.assertEqual(duty.quarantine_state, 'call-returned')

    def test_PC06_allocation_outranks_ordinary_but_both_are_retained(self):
        ordinary, allocation = ValueError(), MemoryError()
        with patch.object(cleanup, 'retire_profile_handler_duty', self.observe('acquisition', error=ordinary)), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin', error=allocation)):
            with self.assertRaises(MemoryError) as caught: self.call()
        self.assertIs(caught.exception, allocation)
        self.assertEqual(self.original.profile_cleanup.errors, [ordinary, allocation])

    def test_PC07_first_control_precedes_later_control_and_quarantine_allocation(self):
        first, second, allocation = KeyboardInterrupt(), SystemExit(), MemoryError()
        self.store._quarantine = lambda error: allocation
        with patch.object(cleanup, 'retire_profile_handler_duty', self.observe('acquisition', error=first)), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin', error=second)):
            with self.assertRaises(KeyboardInterrupt) as caught: self.call()
        self.assertIs(caught.exception, first)
        self.assertIs(self.original.profile_cleanup.quarantine_return, allocation)

    def test_PC08_real_inner_retire_then_lost_outer_return_stays_unresolved_no_retry(self):
        error = MemoryError(); seen = []
        def lost(store, handler):
            seen.append(self.f.duty)
            retirement.retire_profile_handler_duty(store, handler)
            raise error
        with patch.object(cleanup, 'retire_profile_handler_duty', lost), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin')):
            for _ in range(2):
                with self.assertRaises(MemoryError) as caught: self.call()
                self.assertIs(caught.exception, error)
        self.assertEqual(seen, [self.f.duty]); self.assertTrue(self.f.record._retired)
        self.assertNotIn(self.original, self.f.active)
        self.assertEqual(self.original.profile_cleanup.states[0], 'call-pending')
        self.assertEqual(self.original.profile_cleanup.phase, 'unresolved')
        self.assertEqual(self.f.quarantines, [error])

    def test_PC09_successful_repeat_refuses_and_never_replays_known_calls(self):
        with patch.object(cleanup, 'retire_profile_handler_duty', self.observe('acquisition')), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin')):
            duty = self.call()
            with self.assertRaises(cleanup._RequestUnavailable): self.call()
        self.assertEqual(self.calls, ['acquisition', 'begin'])
        self.assertIs(self.original.profile_cleanup, duty)

    def test_PC10_partial_constructor_is_pre_retained_and_never_retried(self):
        error = MemoryError(); seen = []
        def fail(duty, store, original, handler):
            self.assertIs(original.profile_cleanup, duty); seen.append(duty)
            duty.store = store
            raise error
        with patch.object(cleanup._ProfileRequestCleanup, '__init__', fail):
            for _ in range(2):
                with self.assertRaises(MemoryError) as caught: self.call()
                self.assertIs(caught.exception, error)
        self.assertEqual(seen, [self.original.profile_cleanup])
        self.assertEqual(self.original.profile_cleanup_capture, 'constructor-pending')

    def test_PC11_allocation_failure_retains_error_without_later_cleanup(self):
        error = MemoryError()
        # Disposable module binding: never patch a canonical inherited __new__.
        constructor = SimpleNamespace(__new__=lambda cls: (_ for _ in ()).throw(error))
        with patch.object(cleanup, '_ProfileRequestCleanup', constructor), \
             patch.object(cleanup, 'retire_profile_handler_duty') as acquisition:
            with self.assertRaises(MemoryError) as caught: self.call()
        self.assertIs(caught.exception, error); acquisition.assert_not_called()
        self.assertIsNone(self.original.profile_cleanup)
        self.assertIs(self.original.profile_cleanup_capture_error, error)

    def test_PC12_foreign_response_has_no_hooks_and_is_not_adopted(self):
        seen = []
        class Trap:
            def __getattribute__(self, name): seen.append(name); raise AssertionError(name)
        foreign = Trap(); self.original.guest_response = foreign
        with self.assertRaises(cleanup._RequestUnavailable): self.call()
        self.assertEqual(seen, []); self.assertIs(self.original.guest_response, foreign)
        self.assertEqual(self.original.profile_cleanup_capture, 'constructor-pending')

    def test_PC13_replacement_after_first_call_cannot_redirect_second_cleanup(self):
        foreign = object()
        def replace(store, handler): self.original.guest_response = foreign
        with patch.object(cleanup, 'retire_profile_handler_duty', replace), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty') as begin:
            with self.assertRaises(cleanup._RequestUnavailable): self.call()
        begin.assert_not_called()
        duty = self.original.profile_cleanup
        self.assertIs(duty.response, self.f.duty)
        self.assertIs(self.original.guest_response, foreign)
        self.assertEqual(duty.states, ['call-returned', 'call-pending'])

    def test_PC14_quarantine_raised_control_retained_without_retry(self):
        ordinary, control = ValueError(), KeyboardInterrupt(); calls = []
        def quarantine(error): calls.append(error); raise control
        self.store._quarantine = quarantine
        with patch.object(cleanup, 'retire_profile_handler_duty', self.observe('acquisition', error=ordinary)), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin')):
            for _ in range(2):
                with self.assertRaises(KeyboardInterrupt) as caught: self.call()
                self.assertIs(caught.exception, control)
        duty = self.original.profile_cleanup
        self.assertEqual(calls, [ordinary]); self.assertEqual(duty.quarantine_state, 'call-pending')
        self.assertIs(duty.quarantine_error, control)

    def test_PC15_quarantine_foreign_return_retained_without_instance_hooks(self):
        seen = []; ordinary = ValueError()
        class Trap:
            def __getattribute__(self, name): seen.append(name); raise AssertionError(name)
        value = Trap(); self.store._quarantine = lambda error: value
        with patch.object(cleanup, 'retire_profile_handler_duty', self.observe('acquisition', error=ordinary)), \
             patch.object(cleanup, 'retire_profile_begin_handler_duty', self.observe('begin')):
            with self.assertRaises(ValueError) as caught: self.call()
        self.assertIs(caught.exception, ordinary)
        duty = self.original.profile_cleanup
        self.assertIs(duty.quarantine_return, value)
        self.assertIsInstance(duty.quarantine_error, cleanup._RequestUnavailable)
        self.assertEqual(seen, [])
