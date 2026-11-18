"""UNRUN fictional holder/wrapper order, never actual original/native gates.

Wrapper fixtures patch original identity and four-guard admission functions.
They prove no actual guard acquisition or original authority even if later run.
"""
import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_guest_profile_section_slot_data import ProfileSectionSlotData
from freq.services import pilot_guest_profile_section_slot as slot_source
from freq.services import pilot_guest_profile_retirement as source


class ProfileGuardedCleanupData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileSectionSlotData()
        self.fixture.setUp()
        self.duty = self.fixture.duty
        self.owner = self.fixture.fixture.owner
        self.events = []
        self.quarantines = []
        self.enter_error = self.exit_error = None
        fixture = self
        self.store = SimpleNamespace(_quarantine=self.quarantine)

        class FictionalGates:
            def __init__(inner, custody):
                fixture.assertIs(custody, fixture.duty.custody)
            def __enter__(inner):
                fixture.events.append('guards-enter')
                if fixture.enter_error is not None: raise fixture.enter_error
                return inner
            def __exit__(inner, *unused):
                fixture.events.append('guards-exit')
                if fixture.exit_error is not None: raise fixture.exit_error

        self.Gates = FictionalGates

    def quarantine(self, error):
        self.events.append('quarantine')
        self.quarantines.append(error)
        return error

    @contextlib.contextmanager
    def fictional_original(self, *, custody_match=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(source, '_owned_store', return_value=self.owner))
            stack.enter_context(patch.object(source, '_profile_retirement_original', return_value=self.duty.original))
            stack.enter_context(patch.object(source, '_profile_retirement_custody_matches',
                side_effect=custody_match or (lambda *unused: self.duty.custody)))
            stack.enter_context(patch.object(source, '_ProfileRetirementGates', self.Gates))
            yield

    def wrapper(self):
        source.retire_profile_handler_duty(self.store, object())

    def prepared(self):
        return [slot_source._prepare_profile_section_slot_data(self.duty, index) for index in range(3)]

    def test_PG01_guest_and_all_known_unstarted_slots_retire_without_refunding(self):
        ticket = self.duty.begin.record._ticket
        charge = ticket._remaining
        self.assertIsNone(source._retire_profile_holders_data(self.duty, None))
        self.assertTrue(self.duty.begin.record._retired)
        self.assertEqual([slot.cleanup for slot in self.duty.slots], ['returned-no-attempt'] * 3)
        self.assertEqual(ticket._remaining, charge)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)

    def test_PG02_prepared_same_holders_close_locally_while_all_private_graphs_retained(self):
        slots = self.prepared()
        originals = [slot.saved_attempt for slot in slots]
        self.assertIsNone(source._retire_profile_holders_data(self.duty, None))
        self.assertEqual([slot.cleanup for slot in slots], ['close-returned'] * 3)
        self.assertEqual([slot.saved_attempt for slot in slots], originals)
        self.assertTrue(all(inner._original_socket._closure == 'returned-no-acquisition' for inner in originals))

    def test_PG03_guest_retirement_control_does_not_skip_any_known_slot(self):
        control = KeyboardInterrupt('fictional guest retire')
        with patch.object(source._GuestReferenceRecord, '_retire', side_effect=control):
            self.assertIs(source._retire_profile_holders_data(self.duty, None), control)
        self.assertEqual([slot.cleanup for slot in self.duty.slots], ['returned-no-attempt'] * 3)

    def test_PG04_first_slot_control_does_not_skip_guest_or_later_known_slots(self):
        slots = self.prepared()
        seen = []
        control = SystemExit('fictional close')
        def retire(inner):
            seen.append(inner)
            if inner is slots[0].saved_attempt: raise control
        with patch.object(slot_source._ProfileSectionExchange, 'retire', retire):
            self.assertIs(source._retire_profile_holders_data(self.duty, None), control)
        self.assertTrue(self.duty.begin.record._retired)
        self.assertEqual(seen, [slot.saved_attempt for slot in slots])
        self.assertIs(slots[0].cleanup_error, control)
        self.assertEqual([slot.cleanup for slot in slots[1:]], ['close-returned'] * 2)

    def test_PG05_unknown_run_keeps_registration_and_uncertainty_after_known_local_close(self):
        slots = self.prepared()
        slots[0].execution, slots[0].phase = 'run-pending', 'run-pending'
        error = source._retire_profile_holders_data(self.duty, None)
        self.assertIsInstance(error, source._RequestUnavailable)
        self.assertEqual(slots[0].execution, 'run-pending')
        self.assertEqual([slot.cleanup for slot in slots], ['close-returned'] * 3)
        self.assertIs(self.owner._guest_profile_attempts[self.duty.original], self.duty)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)

    def test_PG06_prior_control_preserved_while_guest_and_all_slots_visited(self):
        control = KeyboardInterrupt('fictional prior body')
        self.assertIs(source._retire_profile_holders_data(self.duty, control), control)
        self.assertTrue(self.duty.begin.record._retired)
        self.assertTrue(all(slot.cleanup == 'returned-no-attempt' for slot in self.duty.slots))

    def test_PG07_wrapper_removes_only_known_active_row_after_guarded_local_settlement(self):
        self.prepared()
        charge = self.duty.begin.record._ticket._remaining
        with self.fictional_original(): self.wrapper()
        self.assertNotIn(self.duty.original, self.owner._guest_profile_attempts)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)
        self.assertEqual(self.duty.phase, 'retired')
        self.assertEqual(self.duty.begin.record._ticket._remaining, charge)
        self.assertEqual(self.events, ['guards-enter', 'guards-exit'])

    def test_PG08_wrapper_unknown_slot_quarantines_without_active_or_permanent_delete(self):
        self.duty.slots[0].construction = 'constructor-pending'
        with self.fictional_original():
            with self.assertRaises(source._RequestUnavailable): self.wrapper()
        self.assertEqual(self.events, ['guards-enter', 'guards-exit', 'quarantine'])
        self.assertIs(self.owner._guest_profile_attempts[self.duty.original], self.duty)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)
        self.assertEqual([slot.cleanup for slot in self.duty.slots],
                         ['close-pending', 'returned-no-attempt', 'returned-no-attempt'])

    def test_PG09_guard_entry_failure_cannot_claim_cleanup_or_release_registration(self):
        self.enter_error = KeyboardInterrupt('fictional guard entry')
        with self.fictional_original():
            with self.assertRaises(KeyboardInterrupt): self.wrapper()
        self.assertFalse(self.duty.begin.record._retired)
        self.assertTrue(all(slot.cleanup == 'unattempted' for slot in self.duty.slots))
        self.assertIs(self.owner._guest_profile_attempts[self.duty.original], self.duty)
        self.assertEqual(self.events, ['guards-enter', 'quarantine'])

    def test_PG10_second_captured_identity_check_failure_precedes_any_holder_effect(self):
        calls = []
        def match(*unused):
            calls.append(1)
            if len(calls) == 2: raise source._RequestUnavailable()
            return self.duty.custody
        with self.fictional_original(custody_match=match):
            with self.assertRaises(source._RequestUnavailable): self.wrapper()
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.duty.begin.record._retired)
        self.assertTrue(all(slot.cleanup == 'unattempted' for slot in self.duty.slots))

    def test_PG11_guard_exit_control_supersedes_ordinary_error_after_all_known_visits(self):
        self.duty.slots[0].construction = 'constructor-pending'
        self.exit_error = KeyboardInterrupt('fictional guard exit')
        with self.fictional_original():
            with self.assertRaises(KeyboardInterrupt) as raised: self.wrapper()
        self.assertIs(raised.exception, self.exit_error)
        self.assertEqual([slot.cleanup for slot in self.duty.slots[1:]], ['returned-no-attempt'] * 2)

    def test_PG12_guard_exit_allocation_error_not_masked_by_earlier_ordinary_failure(self):
        self.duty.slots[0].construction = 'constructor-pending'
        self.exit_error = MemoryError('fictional guard exit allocation')
        with self.fictional_original():
            with self.assertRaises(MemoryError) as raised: self.wrapper()
        self.assertIs(raised.exception, self.exit_error)
        self.assertIs(self.quarantines[0], self.exit_error)

    def test_PG13_unrelated_positive_uncertainty_counts_and_expiry_do_not_gate_cleanup(self):
        self.owner._guest_capacity._uncertain = True
        self.owner._guest_profile_attempts.update({object(): object() for _ in range(65)})
        self.duty.begin.record._expires = 0.0
        self.duty.last_clock = float('nan')
        self.assertIsNone(source._retire_profile_holders_data(self.duty, None))
        self.assertTrue(self.duty.begin.record._retired)
        self.assertTrue(all(slot.cleanup == 'returned-no-attempt' for slot in self.duty.slots))

    def test_PG14_foreign_selected_row_never_deleted_despite_known_holder_retirement(self):
        foreign = object()
        self.owner._guest_profile_attempts[self.duty.original] = foreign
        with self.fictional_original():
            with self.assertRaises(source._RequestUnavailable): self.wrapper()
        self.assertTrue(self.duty.begin.record._retired)
        self.assertTrue(all(slot.cleanup == 'returned-no-attempt' for slot in self.duty.slots))
        self.assertIs(self.owner._guest_profile_attempts[self.duty.original], foreign)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)

    def test_PG15_successful_local_removal_then_guard_control_keeps_native_without_reinsert(self):
        slots = self.prepared()
        original_retire = slot_source._ProfileSectionExchange.retire
        visits = []
        def retire(inner):
            visits.append(inner)
            return original_retire(inner)  # Known unstarted pure fields only.
        charge = self.duty.begin.record._ticket._remaining
        self.exit_error = KeyboardInterrupt('fictional guard control after removal')
        with self.fictional_original(), patch.object(slot_source._ProfileSectionExchange, 'retire', retire):
            with self.assertRaises(KeyboardInterrupt) as raised: self.wrapper()
        self.assertIs(raised.exception, self.exit_error)
        self.assertEqual(visits, [slot.saved_attempt for slot in slots])
        self.assertEqual(self.events, ['guards-enter', 'guards-exit', 'quarantine'])
        self.assertEqual(self.quarantines, [self.exit_error])
        self.assertNotIn(self.duty.original, self.owner._guest_profile_attempts)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)
        self.assertEqual(self.duty.phase, 'retired')
        self.assertTrue(self.duty.begin.record._retired)
        self.assertEqual([slot.cleanup for slot in slots], ['close-returned'] * 3)
        self.assertTrue(all(slot.cleanup_error is None for slot in slots))
        self.assertEqual(self.duty.begin.record._ticket._remaining, charge)
        # Do not reenter original guards, repair/reinsert the row or retry any
        # native effect after this unknown guard return. Outside job still owed.

    def test_PG16_successful_local_removal_then_guard_allocation_keeps_native_charge_quarantined(self):
        slots = self.prepared()
        original_retire = slot_source._ProfileSectionExchange.retire
        visits = []
        def retire(inner):
            visits.append(inner)
            return original_retire(inner)
        charge = self.duty.begin.record._ticket._remaining
        self.exit_error = MemoryError('fictional guard allocation after removal')
        with self.fictional_original(), patch.object(slot_source._ProfileSectionExchange, 'retire', retire):
            with self.assertRaises(MemoryError) as raised: self.wrapper()
        self.assertIs(raised.exception, self.exit_error)
        self.assertEqual(visits, [slot.saved_attempt for slot in slots])
        self.assertEqual(self.events, ['guards-enter', 'guards-exit', 'quarantine'])
        self.assertEqual(self.quarantines, [self.exit_error])
        self.assertNotIn(self.duty.original, self.owner._guest_profile_attempts)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)
        self.assertEqual(self.duty.phase, 'retired')
        self.assertTrue(self.duty.begin.record._retired)
        self.assertEqual([slot.cleanup for slot in slots], ['close-returned'] * 3)
        self.assertTrue(all(slot.cleanup_error is None for slot in slots))
        self.assertEqual(self.duty.begin.record._ticket._remaining, charge)
        # One proposed call only; no native recovery/retry/reinsertion or
        # physical completion is inferred from local returned flags.
