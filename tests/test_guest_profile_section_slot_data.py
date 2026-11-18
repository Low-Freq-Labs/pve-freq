"""UNRUN original-slot DATA intentions; no native calls or authority.

Inner run/retire controls below are patched fictional callbacks by definition.
Pure construction may only initialize fields; no socket/TLS/context is created.
"""
import unittest
from unittest.mock import patch

from test_guest_profile_registration_data import ProfileRegistrationData
from freq.services import pilot_guest_profile_registration as registration
from freq.services import pilot_guest_profile_section_slot as source


class ProfileSectionSlotData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileRegistrationData()
        self.fixture.setUp()
        self.duty = self.fixture.duty()
        registration._register_profile_duty_data(self.fixture.owner, self.duty)
        self.duty.original.guest_response = self.duty
        self.duty.begin.phase = 'registration-attempted'

    def prepare(self, index=0):
        return source._prepare_profile_section_slot_data(self.duty, index)

    def run_data(self, index=0):
        # These opaque fictional values enter ONLY the patched inner run.
        return source._run_profile_section_slot_data(self.duty, index, object(), object(), object())

    def test_PL01_pure_constructor_prepublishes_same_known_holder_and_first_end(self):
        real_init = source._ProfileSectionExchange.__init__
        def observed(inner, plan, section, *, original_deadline):
            slot = self.duty.slots[0]
            self.assertIs(slot.saved_attempt, inner)
            self.assertIs(slot.attempt, inner)
            self.assertEqual(slot.construction, 'constructor-pending')
            self.assertEqual(slot.phase, 'construction-pending')
            real_init(inner, plan, section, original_deadline=original_deadline)
        with patch.object(source._ProfileSectionExchange, '__init__', observed):
            slot = self.prepare()
        self.assertIs(slot, self.duty.slots[0])
        self.assertEqual(slot.construction, 'constructor-returned')
        self.assertEqual(slot.saved_attempt._end, self.duty.end)
        self.assertEqual(slot.execution, 'unattempted')

    def test_PL02_constructor_allocation_failure_retains_partial_holder_no_retry(self):
        failure = MemoryError('fictional constructor')
        with patch.object(source._ProfileSectionExchange, '__init__', side_effect=failure):
            with self.assertRaises(MemoryError): self.prepare()
        slot = self.duty.slots[0]
        saved = slot.saved_attempt
        self.assertIs(type(saved), source._ProfileSectionExchange)
        self.assertIs(slot.construction_error, failure)
        self.assertEqual(slot.construction, 'constructor-pending')
        with self.assertRaises(source._RequestUnavailable): self.prepare()
        self.assertIs(slot.saved_attempt, saved)

    def test_PL03_lost_inner_success_return_remains_outer_run_pending(self):
        slot = self.prepare()
        control = KeyboardInterrupt('fictional lost inner return')
        def lost(inner, *unused):
            self.assertEqual(slot.execution, 'run-pending')
            inner._phase, inner._result = 'prepared', b'private-fictional'
            raise control
        with patch.object(source._ProfileSectionExchange, 'run', lost):
            with self.assertRaises(KeyboardInterrupt): self.run_data()
        self.assertEqual(slot.execution, 'run-pending')
        self.assertIs(slot.run_error, control)
        self.assertEqual(slot.saved_attempt._phase, 'prepared')
        self.assertIsNone(slot.result)
        with self.assertRaises(source._RequestUnavailable): self.run_data()

    def test_PL04_known_inner_bytes_retained_once_without_public_result_grant(self):
        slot = self.prepare()
        private = b'private-fictional'
        def returned(inner, *unused):
            self.assertEqual(slot.execution, 'run-pending')
            return private
        with patch.object(source._ProfileSectionExchange, 'run', returned) as mocked:
            self.assertIs(self.run_data(), private)
        self.assertIs(slot.result, private)
        self.assertEqual(slot.execution, 'run-returned')
        self.assertEqual(slot.phase, 'returned-private')
        with self.assertRaises(source._RequestUnavailable): self.run_data()

    def test_PL05_known_none_stays_local_failure_no_section_unavailable_authority(self):
        slot = self.prepare()
        with patch.object(source._ProfileSectionExchange, 'run', return_value=None):
            self.assertIsNone(self.run_data())
        self.assertEqual(slot.phase, 'local-failure')
        self.assertEqual(slot.execution, 'run-returned')

    def test_PL06_memory_error_propagates_and_keeps_independent_pending(self):
        slot = self.prepare()
        failure = MemoryError('fictional inner allocation')
        with patch.object(source._ProfileSectionExchange, 'run', side_effect=failure):
            with self.assertRaises(MemoryError): self.run_data()
        self.assertIs(slot.run_error, failure)
        self.assertEqual(slot.execution, 'run-pending')

    def test_PL07_known_unstarted_slots_retire_without_dropping_maps_or_ticket(self):
        d, owner = self.duty, self.fixture.owner
        before = (d.begin.record._ticket._remaining, len(owner._native_guest_profile_attempts))
        self.assertIsNone(source._retire_all_profile_sections_data(d))
        self.assertEqual([slot.cleanup for slot in d.slots], ['returned-no-attempt'] * 3)
        self.assertEqual((d.begin.record._ticket._remaining, len(owner._native_guest_profile_attempts)), before)
        self.assertIs(owner._guest_profile_attempts[d.original], d)
        self.assertEqual(d.phase, 'registered')

    def test_PL08_unknown_run_can_close_known_local_owner_but_stays_uncertain(self):
        slot = self.prepare()
        slot.execution, slot.phase = 'run-pending', 'run-pending'
        with self.assertRaises(source._RequestUnavailable):
            source._retire_profile_section_slot_data(self.duty, 0)
        self.assertEqual(slot.cleanup, 'close-returned')
        self.assertEqual(slot.execution, 'run-pending')
        self.assertEqual(slot.saved_attempt._original_socket._closure, 'returned-no-acquisition')
        with self.assertRaises(source._RequestUnavailable):
            source._retire_profile_section_slot_data(self.duty, 0)

    def test_PL09_constructor_pending_no_known_holder_never_means_no_resource(self):
        slot = self.duty.slots[0]
        slot.phase, slot.construction = 'construction-pending', 'constructor-pending'
        with self.assertRaises(source._RequestUnavailable):
            source._retire_profile_section_slot_data(self.duty, 0)
        self.assertEqual(slot.cleanup, 'close-pending')
        self.assertIsNone(slot.saved_attempt)
        with self.assertRaises(source._RequestUnavailable): self.prepare()

    def test_PL10_alias_replacement_does_not_redirect_saved_holder_cleanup(self):
        slot = self.prepare()
        saved = slot.saved_attempt
        slot.attempt = object()
        with self.assertRaises(source._RequestUnavailable):
            source._retire_profile_section_slot_data(self.duty, 0)
        self.assertIs(slot.saved_attempt, saved)
        self.assertEqual(saved._cleanup, 'returned')
        self.assertEqual(slot.cleanup, 'close-returned')

    def test_PL11_foreign_saved_holder_never_gets_arbitrary_retire_callback(self):
        class Trap:
            def retire(inner): raise AssertionError('foreign callback')
        slot = self.duty.slots[0]
        slot.saved_attempt = slot.attempt = Trap()
        slot.construction = 'constructor-pending'
        with self.assertRaises(source._RequestUnavailable):
            source._retire_profile_section_slot_data(self.duty, 0)
        self.assertEqual(slot.cleanup, 'close-pending')

    def test_PL12_first_cleanup_control_preserved_while_later_known_slots_visited(self):
        slots = [self.prepare(index) for index in range(3)]
        seen = []
        control = KeyboardInterrupt('fictional first cleanup')
        def retire(inner):
            seen.append(inner)
            if inner is slots[0].saved_attempt: raise control
        with patch.object(source._ProfileSectionExchange, 'retire', retire):
            result = source._retire_all_profile_sections_data(self.duty)
        self.assertIs(result, control)
        self.assertEqual(seen, [slot.saved_attempt for slot in slots])
        self.assertEqual(slots[0].cleanup, 'close-pending')
        self.assertEqual([slot.cleanup for slot in slots[1:]], ['close-returned'] * 2)
        self.assertIs(slots[0].cleanup_error, control)

    def test_PL13_prior_control_does_not_skip_known_unstarted_slot_retirement(self):
        control = SystemExit('fictional prior body')
        self.assertIs(source._retire_all_profile_sections_data(self.duty, control), control)
        self.assertEqual([slot.cleanup for slot in self.duty.slots], ['returned-no-attempt'] * 3)

    def test_PL14_unknown_first_slot_does_not_skip_remaining_known_slots(self):
        self.duty.slots[0].construction = 'constructor-pending'
        first = source._retire_all_profile_sections_data(self.duty)
        self.assertIsInstance(first, source._RequestUnavailable)
        self.assertEqual([slot.cleanup for slot in self.duty.slots],
                         ['close-pending', 'returned-no-attempt', 'returned-no-attempt'])

    def test_PL15_positive_uncertainty_expiry_and_unrelated_counts_never_bar_cleanup(self):
        self.duty.last_clock = float('nan')
        self.fixture.owner._guest_profile_attempts.update({object(): object() for _ in range(65)})
        self.fixture.owner._guest_capacity._uncertain = True
        self.duty.begin.record._expires = 0.0
        self.assertIsNone(source._retire_all_profile_sections_data(self.duty))
        self.assertTrue(all(slot.cleanup == 'returned-no-attempt' for slot in self.duty.slots))

    def test_PL16_changed_captured_deadline_prevents_prepare_without_renewing_it(self):
        self.duty.end += 0.25
        with self.assertRaises(source._RequestUnavailable): self.prepare()
        self.assertEqual(self.duty.slots[0].construction, 'unattempted')

    def test_PL17_known_prepared_filter_recognizes_DATA_without_native_authority(self):
        slot = self.prepare()
        active, native = registration._profile_registration_tables_data(self.fixture.owner, self.duty)
        self.assertIs(active, self.duty.profile_tables[0])
        self.assertIs(native, self.duty.profile_tables[1])
        self.assertIs(self.duty.slots[0], slot)
        self.assertEqual(slot.construction, 'constructor-returned')
        self.assertEqual(slot.execution, 'unattempted')
        self.assertFalse(hasattr(slot, 'acquire'))  # DATA recognition is no native grant.

    def test_PL18_foreign_duty_and_boolean_index_refuse_without_attribute_hooks(self):
        class Trap:
            def __getattribute__(inner, name): raise AssertionError('foreign duty hook')
        for duty, index in ((Trap(), 0), (self.duty, True), (self.duty, -1), (self.duty, 3)):
            with self.assertRaises(source._RequestUnavailable):
                source._retire_profile_section_slot_data(duty, index)
