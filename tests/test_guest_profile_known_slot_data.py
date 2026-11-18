"""UNRUN seeded state/identity DATA only; no socket, TLS or original grant.

Completed states and handles are explicitly seeded opaque objects, not native
acquisition/close receipts. Pure preparation only initializes retained fields.
"""
import unittest

from test_guest_profile_current_data import ProfileCurrentData
from freq.services import pilot_guest_profile_registration as source
from freq.services import pilot_guest_profile_section_slot as slots


class ProfileKnownSlotData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileCurrentData()
        self.fixture.setUp()
        self.owner, self.duty = self.fixture.owner, self.fixture.duty

    def check(self):
        return source._known_profile_slots_data(self.duty)

    def prepare(self):
        return slots._prepare_profile_section_slot_data(self.duty, 0)

    def seeded_complete(self):
        slot = self.prepare()
        inner = slot.saved_attempt
        body = b'private-fictional'
        inner._phase, inner._operation, inner._cleanup = 'prepared', 'finish-returned', 'returned'
        inner._result = body
        owner = inner._original_socket
        owner._socket = object()  # Opaque DATA, no real socket/close method.
        owner._spent, owner._acquisition, owner._closure = True, 'owned', 'returned'
        slot.result, slot.execution, slot.phase = body, 'run-returned', 'returned-private'
        return slot

    def seeded_retired_failure(self, error):
        slot = self.prepare()
        inner = slot.saved_attempt
        inner._phase, inner._cleanup = 'failed', 'returned'
        inner._failure = inner._body_failure = error
        owner = inner._original_socket
        owner._spent, owner._closure = True, 'returned-no-acquisition'
        slot.execution, slot.phase, slot.cleanup = 'run-returned', 'retired-local', 'close-returned'
        self.duty.phase = 'retired'
        return slot

    def test_PK01_wholly_unstarted_context_remains_readonly_DATA(self):
        before = (self.duty.last_clock, self.duty.end, self.duty.begin.record._last_clock,
                  self.duty.begin.record._ticket._remaining)
        self.assertIsNone(self.check())
        self.assertIs(self.fixture.current(), self.duty)
        self.assertEqual((self.duty.last_clock, self.duty.end, self.duty.begin.record._last_clock,
                          self.duty.begin.record._ticket._remaining), before)

    def test_PK02_known_prepared_slot_allows_same_context_without_start_or_renewal(self):
        slot = self.prepare()
        before = (slot.saved_attempt, slot.construction, slot.execution, slot.cleanup,
                  self.duty.end, self.duty.last_clock)
        self.assertIsNone(self.check())
        self.assertIs(self.fixture.current(), self.duty)
        self.assertEqual((slot.saved_attempt, slot.construction, slot.execution, slot.cleanup,
                          self.duty.end, self.duty.last_clock), before)

    def test_PK03_seeded_known_same_result_state_is_DATA_not_native_result_authority(self):
        slot = self.seeded_complete()
        self.assertIsNone(self.check())
        self.assertIs(self.fixture.current(), self.duty)
        self.assertIs(slot.result, slot.saved_attempt._result)
        self.assertEqual(slot.cleanup, 'unattempted')
        self.assertEqual(slot.saved_attempt._cleanup, 'returned')

    def test_PK04_equal_copied_result_is_not_the_retained_original_result(self):
        slot = self.seeded_complete()
        original = slot.result
        slot.result = bytes(bytearray(original))
        self.assertEqual(slot.result, original)
        self.assertIsNot(slot.result, original)
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertIs(slot.saved_attempt._result, original)

    def test_PK05_constructor_pending_never_repaired_or_treated_as_absent(self):
        slot = self.duty.slots[0]
        slot.construction = 'constructor-pending'
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertEqual(slot.construction, 'constructor-pending')
        self.assertIsNone(slot.saved_attempt)

    def test_PK06_outer_run_pending_refuses_even_when_inner_seeded_prepared(self):
        slot = self.seeded_complete()
        slot.execution = 'run-pending'
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertEqual(slot.saved_attempt._phase, 'prepared')
        self.assertEqual(slot.execution, 'run-pending')

    def test_PK07_pending_close_cannot_validate_positive_or_reset_itself(self):
        slot = self.prepare()
        slot.cleanup = 'close-pending'
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertEqual(slot.cleanup, 'close-pending')

    def test_PK08_alias_replacement_refuses_without_adopting_or_discarding_saved_holder(self):
        slot = self.prepare()
        saved = slot.saved_attempt
        slot.attempt = object()
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertIs(slot.saved_attempt, saved)

    def test_PK09_foreign_saved_holder_refuses_before_attribute_hooks(self):
        slot = self.prepare()
        class Trap:
            def __getattribute__(inner, name): raise AssertionError('foreign saved holder')
        slot.attempt = slot.saved_attempt = Trap()
        with self.assertRaises(source._CorruptProfileSource): self.check()

    def test_PK10_changed_plan_end_section_or_thread_never_rebinds_same_slot(self):
        for field, value in (('_plan', object()), ('_end', 115.25),
                             ('_section', 'guest_network'), ('_thread', object())):
            self.setUp()
            slot = self.prepare()
            setattr(slot.saved_attempt, field, value)
            with self.assertRaises(source._CorruptProfileSource): self.check()
            self.assertEqual(self.duty.end, 115.0)

    def test_PK11_retired_known_unstarted_rows_remain_counted_without_refund(self):
        before = self.duty.begin.record._ticket._remaining
        self.assertIsNone(slots._retire_all_profile_sections_data(self.duty))
        self.duty.phase = 'retired'  # Explicit fictional terminal count row.
        self.assertIsNone(self.check())
        self.assertIs(source._profile_registration_tables_data(self.owner, self.duty)[1][self.duty.original], self.duty)
        self.assertEqual(self.duty.begin.record._ticket._remaining, before)

    def test_PK12_retired_prepared_holder_requires_known_local_cleanup(self):
        slot = self.prepare()
        self.duty.phase = 'retired'
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertIsNone(slots._retire_all_profile_sections_data(self.duty))
        self.assertIsNone(self.check())
        self.assertEqual(slot.cleanup, 'close-returned')
        self.assertIsNotNone(slot.saved_attempt)

    def test_PK13_retired_seeded_result_stays_retained_private_count_DATA(self):
        slot = self.seeded_complete()
        original = slot.result
        charge = self.duty.begin.record._ticket._remaining
        self.assertIsNone(slots._retire_all_profile_sections_data(self.duty))
        self.duty.phase = 'retired'
        self.assertIsNone(self.check())
        self.assertIs(slot.result, original)
        self.assertEqual(self.duty.begin.record._ticket._remaining, charge)

    def test_PK14_ordinary_none_failure_only_in_retired_count_row_not_active_currentness(self):
        slot = self.seeded_retired_failure(OSError('fictional ordinary'))
        self.assertIsNone(self.check())
        self.duty.phase, slot.phase, slot.cleanup = 'registered', 'local-failure', 'unattempted'
        with self.assertRaises(source._CorruptProfileSource): self.check()

    def test_PK15_control_or_allocation_failure_never_becomes_positive_count_data(self):
        for error in (KeyboardInterrupt('fictional control'), MemoryError('fictional allocation')):
            self.setUp()
            self.seeded_retired_failure(error)
            with self.assertRaises(source._CorruptProfileSource): self.check()

    def test_PK16_partial_canonical_holder_refuses_named_without_catching_controls(self):
        slot = self.duty.slots[0]
        slot.saved_attempt = slot.attempt = source._ProfileSectionExchange.__new__(source._ProfileSectionExchange)
        slot.construction = 'constructor-returned'  # Deliberately inconsistent DATA.
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertIsNotNone(slot.saved_attempt)

    def test_PK17_replaced_inner_socket_alias_is_not_a_known_original_owner(self):
        slot = self.prepare()
        saved = slot.saved_attempt._original_socket
        slot.saved_attempt._socket_owner = object()
        with self.assertRaises(source._CorruptProfileSource): self.check()
        self.assertIs(slot.saved_attempt._original_socket, saved)

    def test_PK18_nonbuiltin_state_refuses_before_equality_coercion(self):
        class State(str):
            def __eq__(inner, other): raise AssertionError('state equality hook')
        self.duty.slots[0].construction = State('unattempted')
        with self.assertRaises(source._CorruptProfileSource): self.check()

    def test_PK19_new_registration_cannot_insert_pending_slot_as_unstarted(self):
        new = self.fixture.fixture.duty()
        new.slots[0].construction = 'constructor-pending'
        count = len(self.owner._native_guest_profile_attempts)
        with self.assertRaises(source._CorruptProfileSource):
            source._register_profile_duty_data(self.owner, new)
        self.assertNotIn(new.original, self.owner._native_guest_profile_attempts)
        self.assertEqual(len(self.owner._native_guest_profile_attempts), count)

    def test_PK20_same_context_first_end_and_cohort_still_refuse_after_known_prepare(self):
        self.prepare()
        with self.assertRaises(source._RequestUnavailable): self.fixture.current(115.0)
        with self.assertRaises(source._RequestUnavailable): self.fixture.current(cohort=object())
        self.assertEqual((self.duty.end, self.duty.last_clock), (115.0, 112.5))
