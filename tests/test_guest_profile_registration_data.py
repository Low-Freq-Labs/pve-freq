"""UNRUN fictional typed registration/unstarted retirement DATA intentions.

No positive original server, guard acquisition, native attempt or resource.
Local terminal bookkeeping never proves physical closure or refunds a ticket.
"""
from types import SimpleNamespace
import unittest
import threading

from test_guest_profile_continuation_data import ProfileContinuationData
from freq.api import auth
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services import pilot_guest_profile_registration as source
from freq.services import pilot_guest_profile_retirement as cleanup


class ProfileRegistrationData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileContinuationData()
        self.fixture.setUp()
        self.owner, self.begin = self.fixture.owner, self.fixture.begin
        self.owner._guest_profile_attempts = {}
        self.owner._native_guest_profile_attempts = {}
        self.owner._original_guest_profile_tables = (
            self.owner._guest_profile_attempts, self.owner._native_guest_profile_attempts)
        self.store = SimpleNamespace(_installation=self.owner,
            _broker=SimpleNamespace(_requests={}, _gate=object()),
            _references=SimpleNamespace(_lock=object()), _auth=SimpleNamespace())

    def duty(self):
        # Distinct fictional request for count DATA only, same fixture rights.
        # A real original spent guest could not be used across such requests.
        f = ProfileContinuationData()
        f.setUp()
        begin = f.begin
        # Use SAME canonical source/record graph owned by this fixture.
        b = self.begin
        for field in ('session', 'values', 'family_ref', 'guest_ref', 'family',
                      'record', 'source', 'target', 'cohort', 'generation'):
            setattr(begin, field, getattr(b, field))
        original = begin.original
        # This fictional local request must match the original thread predicate.
        original.thread = threading.current_thread()
        plan = source._GuestProfileSubreadsData(self.owner, begin, 112.5)
        duty = source._ProfileAcquisitionDuty(original, begin)
        duty.plan, duty.end = plan, plan.end
        duty.credential_uid, duty.configured_token = 2001, ('fixture@pam', 'fixture-token-name')
        duty.component_tables = self.owner._original_component_tables
        duty.inventory_tables = self.owner._original_guest_inventory_tables
        duty.profile_tables = self.owner._original_guest_profile_tables
        duty.custody = source._ProfileRetirementCustody(self.store, original, object(), duty)
        duty.phase = 'captured'
        return duty

    def test_PR01_three_fixed_distinct_slots_have_no_native_or_acquiring_API(self):
        d = self.duty()
        self.assertEqual(tuple(slot.section for slot in d.slots), source._SECTIONS)
        self.assertEqual(len({id(slot) for slot in d.slots}), 3)
        for slot in d.slots:
            self.assertIsNone(slot.attempt)
            self.assertEqual(slot.phase, 'uninitialized')
            self.assertFalse(hasattr(slot, 'run'))
        self.assertFalse(hasattr(d, 'acquire'))
        self.assertFalse(hasattr(d, 'charge'))  # No invented native allowance.

    def test_PR02_custody_retains_exact31_fields_and_canonical_auth_lock(self):
        d = self.duty()
        items = d.custody.items
        self.assertEqual(len(items), 31)
        self.assertIs(items[13][1], auth._auth_lock)
        self.assertIs(items[14], d)
        self.assertIs(items[19], d.begin.target)
        self.assertIs(items[26], d.slots)
        self.assertIs(items[30], d.plan)
        with self.assertRaises(TypeError): d.custody.items = ()
        with self.assertRaises(TypeError): del d.custody.items

    def test_PR03_registration_retains_same_duty_permanent_then_active(self):
        d = self.duty()
        before = self.owner._guest_capacity._check()[0]
        self.assertTrue(source._register_profile_duty_data(self.owner, d))
        self.assertIs(self.owner._guest_profile_attempts[d.original], d)
        self.assertIs(self.owner._native_guest_profile_attempts[d.original], d)
        self.assertEqual(d.phase, 'registered')
        self.assertEqual(self.owner._guest_capacity._check()[0], before)

    def test_PR04_same_registration_cannot_repeat_or_refund(self):
        d = self.duty()
        source._register_profile_duty_data(self.owner, d)
        with self.assertRaises(source._CorruptProfileSource):
            source._register_profile_duty_data(self.owner, d)
        self.assertEqual(len(self.owner._native_guest_profile_attempts), 1)

    def test_PR05_sixtyfour_typed_count_rows_refuse_sixtyfifth_without_insert(self):
        for _ in range(64):
            self.assertTrue(source._register_profile_duty_data(self.owner, self.duty()))
        d = self.duty()
        self.assertFalse(source._register_profile_duty_data(self.owner, d))
        self.assertNotIn(d.original, self.owner._native_guest_profile_attempts)
        self.assertEqual(d.phase, 'captured')
        self.assertEqual(len(self.owner._guest_profile_attempts), 64)

    def test_PR06_unknown_prior_registration_is_retained_not_repaired(self):
        old = self.duty()
        source._register_profile_duty_data(self.owner, old)
        old.phase = 'registration-pending'  # Fictional state, no observed lost return.
        del self.owner._guest_profile_attempts[old.original]
        with self.assertRaises(source._CorruptProfileSource):
            source._register_profile_duty_data(self.owner, self.duty())
        self.assertIs(self.owner._native_guest_profile_attempts[old.original], old)

    def test_PR07_replaced_or_aliased_maps_refuse_without_adoption(self):
        d = self.duty()
        saved = d.profile_tables
        self.owner._guest_profile_attempts = {}
        with self.assertRaises(source._CorruptProfileSource):
            source._register_profile_duty_data(self.owner, d)
        self.assertIs(self.owner._original_guest_profile_tables, saved)
        self.owner._guest_profile_attempts = saved[0]
        self.owner._original_guest_profile_tables = (saved[0], saved[0])
        with self.assertRaises(source._CorruptProfileSource):
            source._register_profile_duty_data(self.owner, d)

    def test_PR08_wrong_section_or_unknown_native_slot_refuses_without_call(self):
        for field, value in (('section', 'other'), ('attempt', object()), ('phase', 'acquiring')):
            d = self.duty()
            setattr(d.slots[1], field, value)
            with self.assertRaises(source._CorruptProfileSource):
                source._register_profile_duty_data(self.owner, d)
            self.assertEqual(self.owner._guest_profile_attempts, {})

    def test_PR09_foreign_store_refuses_before_handler_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign handler hook')
        with self.assertRaises(_RequestUnavailable): source.register_profile_acquisition(object(), Trap())
        with self.assertRaises(_RequestUnavailable): cleanup.retire_profile_handler_duty(object(), Trap())

    def test_PR10_foreign_duty_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign duty hook')
        with self.assertRaises(source._CorruptProfileSource):
            source._profile_registration_tables_data(self.owner, Trap())

    def test_PR11_unstarted_retirement_marks_guest_only_keeps_shared_ticket(self):
        d = self.duty()
        record, ticket = d.begin.record, d.begin.record._ticket
        before = ticket._remaining
        self.assertIsNone(cleanup._retire_unstarted_profile_holders_data(d, None))
        self.assertTrue(record._retired)
        self.assertTrue(record._spent)
        self.assertEqual(ticket._remaining, before)
        self.assertEqual(ticket._state, 'committed')
        self.assertFalse(self.fixture.fixture.batch.records[1]._retired)

    def test_PR12_earlier_control_preserved_while_known_guest_is_retired(self):
        d = self.duty()
        first = KeyboardInterrupt('fictional control')
        self.assertIs(cleanup._retire_unstarted_profile_holders_data(d, first), first)
        self.assertTrue(d.begin.record._retired)

    def test_PR13_unknown_section_never_cleared_and_guest_still_retired(self):
        d = self.duty()
        marker = object()
        d.slots[0].attempt = marker
        failure = cleanup._retire_unstarted_profile_holders_data(d, None)
        self.assertIsInstance(failure, _RequestUnavailable)
        self.assertTrue(d.begin.record._retired)
        self.assertIs(d.slots[0].attempt, marker)
        self.assertEqual(d.slots[0].phase, 'uninitialized')

    def test_PR14_logical_retirement_removes_only_active_row_preserves_native(self):
        d = self.duty()
        source._register_profile_duty_data(self.owner, d)
        self.assertIsNone(cleanup._retire_unstarted_profile_holders_data(d, None))
        cleanup._retire_profile_registration_data(d)
        self.assertNotIn(d.original, self.owner._guest_profile_attempts)
        self.assertIs(self.owner._native_guest_profile_attempts[d.original], d)
        self.assertEqual(d.phase, 'retired')
        cleanup._retire_profile_registration_data(d)  # Terminal logical idempotence only.
        self.assertIs(self.owner._native_guest_profile_attempts[d.original], d)

    def test_PR15_foreign_selected_rows_are_not_deleted_or_adopted(self):
        d = self.duty()
        source._register_profile_duty_data(self.owner, d)
        other = object()
        self.owner._guest_profile_attempts[d.original] = other
        self.assertIsNone(cleanup._retire_unstarted_profile_holders_data(d, None))
        with self.assertRaises(_RequestUnavailable): cleanup._retire_profile_registration_data(d)
        self.assertIs(self.owner._guest_profile_attempts[d.original], other)
        self.assertIs(self.owner._native_guest_profile_attempts[d.original], d)

    def test_PR16_own_uncertainty_and_unrelated_over_cap_rows_do_not_bar_DATA_cleanup(self):
        d = self.duty()
        source._register_profile_duty_data(self.owner, d)
        self.owner._guest_capacity._uncertain = True
        for i in range(70): self.owner._guest_profile_attempts[('fictional', i)] = object()
        self.assertIsNone(cleanup._retire_unstarted_profile_holders_data(d, None))
        cleanup._retire_profile_registration_data(d)
        self.assertNotIn(d.original, self.owner._guest_profile_attempts)
        self.assertEqual(len(self.owner._guest_profile_attempts), 70)
        self.assertIs(self.owner._native_guest_profile_attempts[d.original], d)
        self.assertTrue(self.owner._guest_capacity._uncertain)

    def test_PR17_known_no_insertion_and_unknown_pending_are_distinct(self):
        d = self.duty()
        d.phase = 'refused'
        cleanup._retire_profile_registration_data(d)
        self.assertEqual(d.phase, 'retired')
        d = self.duty()
        d.phase = 'registration-pending'
        with self.assertRaises(_RequestUnavailable): cleanup._retire_profile_registration_data(d)
        self.assertEqual(d.phase, 'registration-pending')

    def test_PR18_profile_maps_are_separate_from_inventory_maps(self):
        d = self.duty()
        self.assertFalse(any(a is b for a in d.profile_tables
            for b in d.component_tables + d.inventory_tables))
        old = tuple(dict(table) for table in d.inventory_tables)
        source._register_profile_duty_data(self.owner, d)
        cleanup._retire_unstarted_profile_holders_data(d, None)
        cleanup._retire_profile_registration_data(d)
        self.assertEqual(tuple(dict(table) for table in d.inventory_tables), old)
