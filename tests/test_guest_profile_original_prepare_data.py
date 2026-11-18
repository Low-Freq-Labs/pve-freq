"""UNRUN fictional guarded-wrapper ports and pure slot DATA only.

All original owner/auth/guard/custody ports are explicitly patched here; no
case claims actual original admission, native effect, real lock or credential.
"""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from test_guest_profile_current_data import ProfileCurrentData
from freq.services import pilot_guest_profile_prepare as source
from freq.services import pilot_guest_profile_exchange as exchange


class ProfileOriginalPrepareData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileCurrentData()
        self.fixture.setUp()
        self.owner, self.duty = self.fixture.owner, self.fixture.duty
        self.events = []
        self.now = 113.0
        self.cohort = self.duty.begin.cohort
        self.generation = self.duty.begin.generation
        self.native_tables = True  # Fictional patched port, never an authority.
        self.exit_error = None
        self.owner._original_guest_profile_tables_current = lambda: self.native_tables
        self.handler = object()
        self.store = SimpleNamespace(_auth=object(),
            _broker=SimpleNamespace(_owned=self.owned),
            _guard_locked=self.guard, _csrf_nonce_locked=self.csrf,
            _retire_known_family_locked=lambda family: self.events.append('family-retired'),
            _quarantine=lambda error: error)

    def owned(self, handler):
        self.assertIs(handler, self.handler)
        self.events.append('owned')
        return self.duty.original

    def guard(self, *args):
        self.events.append('guard')
        return self.cohort, self.generation, self.now

    def csrf(self, *args):
        self.events.append('csrf')

    def prepare(self, index=0):
        fixture = self
        class FictionalGates:
            def __init__(self, transaction, original, duty):
                fixture.assertIs(original, fixture.duty.original)
                fixture.assertIs(duty, fixture.duty)
            def __enter__(self):
                fixture.events.append('enter')
                return self
            def __exit__(self, kind, error, traceback):
                fixture.events.append('exit')
                if fixture.exit_error is not None:
                    raise fixture.exit_error
        def custody(store, original, handler, duty):
            self.events.append('custody')
            self.assertIs(duty, self.duty)
            return duty.custody
        with ExitStack() as patches:
            patches.enter_context(patch.object(source, '_owned_store', return_value=self.owner))
            patches.enter_context(patch.object(source, '_ProfileCurrentGates', FictionalGates))
            patches.enter_context(patch.object(source, '_profile_retirement_custody_matches', custody))
            return source.prepare_registered_profile_section(self.store, self.handler, index)

    def test_PP01_original_checkpoint_precedes_pure_retained_holder(self):
        slot = self.prepare()
        self.assertIs(slot, self.duty.slots[0])
        self.assertEqual(self.events, ['owned', 'enter', 'guard', 'csrf', 'custody', 'exit'])
        self.assertEqual((slot.phase, slot.construction, slot.execution),
                         ('prepared', 'constructor-returned', 'unattempted'))
        self.assertIsNone(slot.saved_attempt._original_socket._socket)
        self.assertEqual(slot.saved_attempt._original_socket._acquisition, 'unstarted')

    def test_PP02_fictional_native_current_false_prevents_any_preparation(self):
        self.native_tables = False
        with self.assertRaises(source._RequestUnavailable): self.prepare()
        self.assertEqual(self.duty.slots[0].phase, 'uninitialized')
        self.assertNotIn('custody', self.events)

    def test_PP03_boolean_or_out_of_range_index_refuses_before_broker(self):
        for index in (True, False, -1, 3, '0'):
            with self.assertRaises(source._RequestUnavailable): self.prepare(index)
        self.assertEqual(self.events, [])

    def test_PP04_first_end_expiry_never_prepares_or_renews_end(self):
        self.now = self.duty.end
        with self.assertRaises(source._RequestUnavailable): self.prepare()
        self.assertEqual(self.duty.slots[0].phase, 'uninitialized')
        self.assertEqual((self.duty.end, self.duty.plan.end, self.duty.original.write_end),
                         (115.0, 115.0, 115.0))

    def test_PP05_foreign_cohort_refuses_before_constructor(self):
        self.cohort = object()
        with self.assertRaises(source._RequestUnavailable): self.prepare()
        self.assertIsNone(self.duty.slots[0].saved_attempt)

    def test_PP06_duplicate_preparation_cannot_replace_original_holder(self):
        slot = self.prepare()
        saved = slot.saved_attempt
        with self.assertRaises(source._RequestUnavailable): self.prepare()
        self.assertIs(slot.saved_attempt, saved)
        self.assertEqual(slot.execution, 'unattempted')

    def test_PP07_allocation_failure_retains_prepublished_partial_holder(self):
        error = MemoryError('fictional pure constructor')
        with patch.object(exchange._ProfileSectionExchange, '__init__', side_effect=error):
            with self.assertRaises(MemoryError) as caught: self.prepare()
        self.assertIs(caught.exception, error)
        slot = self.duty.slots[0]
        self.assertIsNotNone(slot.saved_attempt)
        self.assertIs(slot.attempt, slot.saved_attempt)
        self.assertIs(slot.construction_error, error)
        self.assertEqual(slot.construction, 'constructor-pending')
        self.assertEqual(slot.execution, 'unattempted')

    def test_PP08_late_guard_control_does_not_erase_known_prepared_duty(self):
        error = KeyboardInterrupt()
        self.exit_error = error
        with self.assertRaises(KeyboardInterrupt) as caught: self.prepare()
        self.assertIs(caught.exception, error)
        slot = self.duty.slots[0]
        self.assertEqual(slot.phase, 'prepared')
        self.assertEqual(slot.execution, 'unattempted')
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)
        self.assertIsNone(slot.saved_attempt._original_socket._socket)
        # Original outside cleanup/control ledger is not supplied by this prefix.

    def test_PP09_copied_target_refuses_without_slot_or_charge_repair(self):
        record = self.duty.begin.record
        before = record._ticket._remaining
        record._target = tuple(list(record._target))
        with self.assertRaises(source._RequestUnavailable): self.prepare()
        self.assertIsNone(self.duty.slots[0].saved_attempt)
        self.assertEqual(record._ticket._remaining, before)

    def test_PP10_foreign_store_refuses_before_any_handler_hook(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign handler')
        with self.assertRaises(source._RequestUnavailable):
            source.prepare_registered_profile_section(object(), Trap(), 0)
