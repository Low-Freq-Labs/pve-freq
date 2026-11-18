"""UNRUN registered-profile revalidation DATA; no actual original authority."""
import unittest

from test_guest_profile_registration_data import ProfileRegistrationData
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services import pilot_guest_profile_current as source
from freq.services import pilot_guest_profile_registration as registration
from freq.services import pilot_guest_profile_retirement as cleanup


class ProfileCurrentData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileRegistrationData()
        self.fixture.setUp()
        self.owner = self.fixture.owner
        self.duty = self.fixture.duty()
        d = self.duty
        b = d.begin
        # Fictional context only: canonical source token and family tables are
        # made explicit here before a new pure custody snapshot is captured.
        d.configured_token = b.cohort.token_id
        self.owner._configured_token_id = d.configured_token
        self.owner._credential_uid = d.credential_uid
        self.owner._guest_families_by_nonce = d.component_tables[5]
        self.owner._guest_families_by_ref = d.component_tables[6]
        self.owner._guest_families_by_nonce[(id(b.session), b.family._nonce)] = b.family
        self.owner._guest_families_by_ref[(id(b.session), b.family_ref)] = b.family
        d.custody = registration._ProfileRetirementCustody(
            self.fixture.store, d.original, object(), d)
        d.last_clock = 112.5
        registration._register_profile_duty_data(self.owner, d)
        b.phase = 'registration-attempted'
        d.original.guest_response = d

    def current(self, now=113.0, cohort=None, generation=None):
        d = self.duty
        return source._registered_profile_context_data_locked(self.owner, d,
            d.begin.cohort if cohort is None else cohort,
            d.begin.generation if generation is None else generation, now)

    def test_PV01_same_context_readonly_without_reference_clock_or_counter_touch(self):
        d = self.duty
        record = d.begin.record
        before = (record._spent, record._retired, record._last_clock,
            record._ticket._remaining, d.last_clock, d.end, d.plan.end,
            d.original.write_end, tuple(slot.phase for slot in d.slots))
        self.assertIs(self.current(), d)
        self.assertEqual((record._spent, record._retired, record._last_clock,
            record._ticket._remaining, d.last_clock, d.end, d.plan.end,
            d.original.write_end, tuple(slot.phase for slot in d.slots)), before)

    def test_PV02_foreign_cohort_or_generation_cannot_rebind_same_duty(self):
        with self.assertRaises(_RequestUnavailable): self.current(cohort=object())
        with self.assertRaises(_RequestUnavailable): self.current(generation=object())
        self.assertEqual(self.duty.phase, 'registered')

    def test_PV03_replaced_original_duty_cannot_be_adopted(self):
        other = object()
        self.duty.original.guest_response = other
        with self.assertRaises(_RequestUnavailable): self.current()
        self.assertIs(self.duty.original.guest_response, other)

    def test_PV04_nonregistered_or_wrong_begin_phase_cannot_continue(self):
        self.duty.phase = 'registration-pending'
        with self.assertRaises(_RequestUnavailable): self.current()
        self.duty.phase = 'registered'
        self.duty.begin.phase = 'spent'
        with self.assertRaises(_RequestUnavailable): self.current()

    def test_PV05_shorter_write_end_is_honored_without_renewal(self):
        d = self.duty
        d.original.write_end = 114.0
        self.assertIs(self.current(113.5), d)
        with self.assertRaises(_RequestUnavailable): self.current(114.0)
        self.assertEqual((d.end, d.plan.end, d.original.write_end), (115.0, 115.0, 114.0))

    def test_PV06_backward_nonfinite_bool_or_integer_clock_refuses(self):
        for now in (112.0, float('nan'), float('inf'), True, 113):
            with self.assertRaises(_RequestUnavailable): self.current(now)
        self.assertEqual(self.duty.last_clock, 112.5)

    def test_PV07_exact_first_end_refuses_without_extending_any_bound(self):
        with self.assertRaises(_RequestUnavailable): self.current(115.0)
        self.assertEqual(self.duty.end, 115.0)
        self.assertEqual(self.duty.begin.resource_end, 122.0)

    def test_PV08_equal_reconstructed_token_is_not_original_configured_identity(self):
        saved = self.owner._configured_token_id
        self.owner._configured_token_id = tuple(list(saved))
        self.assertIsNot(self.owner._configured_token_id, saved)
        with self.assertRaises(_RequestUnavailable): self.current()
        self.owner._configured_token_id = saved
        self.duty.credential_uid = True
        with self.assertRaises(_RequestUnavailable): self.current()

    def test_PV09_missing_or_foreign_selected_registration_refuses_without_repair(self):
        d = self.duty
        del self.owner._guest_profile_attempts[d.original]
        with self.assertRaises(_RequestUnavailable): self.current()
        self.assertNotIn(d.original, self.owner._guest_profile_attempts)
        self.assertIs(self.owner._native_guest_profile_attempts[d.original], d)

    def test_PV10_retired_guest_refuses_without_refund_or_revival(self):
        r = self.duty.begin.record
        before = r._ticket._remaining
        r._retire()
        with self.assertRaises(_RequestUnavailable): self.current()
        self.assertTrue(r._retired)
        self.assertEqual(r._ticket._remaining, before)

    def test_PV11_equal_reconstructed_target_is_not_retained_target_identity(self):
        r = self.duty.begin.record
        r._target = tuple(list(r._target))
        self.assertIsNot(r._target, self.duty.plan.target)
        with self.assertRaises(_RequestUnavailable): self.current()

    def test_PV12_missing_live_family_index_cannot_adopt_retained_pointer(self):
        b = self.duty.begin
        del self.owner._guest_families_by_ref[(id(b.session), b.family_ref)]
        with self.assertRaises(_RequestUnavailable): self.current()
        self.assertIs(self.duty.plan.begin.family, b.family)

    def test_PV13_equal_foreign_configured_row_is_not_an_original_source(self):
        r = self.duty.begin.record
        r._source = tuple(list(r._source))
        with self.assertRaises(_RequestUnavailable): self.current()
        self.assertEqual(self.duty.phase, 'registered')

    def test_PV14_repeat_DATA_validation_never_consumes_or_starts_slots(self):
        self.assertIs(self.current(113.0), self.duty)
        self.assertIs(self.current(113.5), self.duty)
        self.assertEqual(self.duty.last_clock, 112.5)
        self.assertTrue(self.duty.begin.record._spent)
        for slot in self.duty.slots:
            self.assertEqual(slot.phase, 'uninitialized')
            self.assertIsNone(slot.attempt)
            self.assertFalse(hasattr(slot, 'run'))

    def test_PV15_positive_uncertainty_refusal_does_not_bar_known_DATA_cleanup(self):
        self.owner._guest_capacity._uncertain = True
        with self.assertRaises(_RequestUnavailable): self.current()
        self.assertIsNone(cleanup._retire_unstarted_profile_holders_data(self.duty, None))
        cleanup._retire_profile_registration_data(self.duty)
        self.assertIs(self.owner._native_guest_profile_attempts[self.duty.original], self.duty)
        self.assertTrue(self.owner._guest_capacity._uncertain)

    def test_PV16_foreign_store_refused_before_handler_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('foreign handler hook')
        with self.assertRaises(_RequestUnavailable): source.revalidate_registered_profile_context(object(), Trap())
