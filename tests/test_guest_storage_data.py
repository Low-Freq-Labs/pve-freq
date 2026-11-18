"""Fictional DATA only; no original issuer, live owner or native effects.

These tests are authored intentions until a qualified offline invocation runs
them. They never set installation/native currentness, create an HTTP request,
acquire entropy or treat constructed family/record objects as authority.
"""
import unittest

from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_state import _GuestReferenceRecord, _Unavailable


class GuestStorageData(unittest.TestCase):
    def setUp(self):
        self.capacity = _GuestCapacity()
        self.session = {}
        self.cohort, self.generation, self.source = object(), object(), object()

    def family(self, nonce='a' * 64, reference='b' * 64):
        ticket = self.capacity._reserve(self.session, 'reader', 1)
        family = _GuestFamilyRecord(self.session, 'reader', nonce, self.cohort,
            self.generation, object(), 100.0, 130.0, ticket)
        self.capacity._commit(ticket)
        if reference is not None:
            family._bind_once(reference)
        return family

    def record(self, purpose='source', family=None, **overrides):
        if family is None:
            family = self.family()
        ticket = self.capacity._reserve(self.session, 'reader', 1)
        values = dict(key='c' * 64, purpose=purpose, session=self.session,
            principal='reader', source=self.source, generation=self.generation,
            cohort=self.cohort,
            target=None if type(purpose) is str and purpose == 'source' else object(),
            created=101.0, expires=130.0, ticket=ticket, family=family)
        values.update(overrides)
        return _GuestReferenceRecord(**values)

    def test_GS01_full_inventory_and_family_fit_289(self):
        self.family()
        self.capacity._reserve(self.session, 'reader', 32)
        self.capacity._reserve(self.session, 'reader', 256)
        self.assertEqual(self.capacity._check()[0], 289)

    def test_GS02_exact_session_bound_refuses_atomic_overflow(self):
        self.capacity._reserve(self.session, 'reader', 256)
        self.capacity._reserve(self.session, 'reader', 256)
        before = dict(self.capacity._tickets)
        with self.assertRaises(_CapacityUnavailable):
            self.capacity._reserve(self.session, 'reader', 1)
        self.assertEqual(self.capacity._tickets, before)
        self.assertEqual(self.capacity._check()[0], 512)

    def test_GS03_full_owner_bound_preserves_other_sessions(self):
        sessions = [{} for _ in range(8)]
        for session in sessions:
            self.capacity._reserve(session, 'reader', 256)
            self.capacity._reserve(session, 'reader', 256)
        self.assertEqual(self.capacity._check()[0], 4096)
        with self.assertRaises(_CapacityUnavailable):
            self.capacity._reserve({}, 'reader', 1)
        self.capacity._retire_session(sessions[0])
        self.assertEqual(self.capacity._check()[0], 3584)
        self.assertTrue(all(t._session is not sessions[0]
                            for t in self.capacity._tickets.values()))

    def test_GS04_spending_does_not_refund_capacity(self):
        record = self.record()
        record._consume_once(102.0)
        self.assertEqual(self.capacity._check()[0], 2)
        with self.assertRaises(_Unavailable):
            record._consume_once(103.0)
        self.assertEqual(self.capacity._check()[0], 2)

    def test_GS05_exact_expiry_is_terminal(self):
        record = self.record()
        with self.assertRaises(_Unavailable):
            record._consume_once(130.0)
        self.assertTrue(record._spent and record._retired)
        with self.assertRaises(_Unavailable):
            record._consume_once(102.0)

    def test_GS06_backwards_clock_never_revives(self):
        record = self.record()
        with self.assertRaises(_Unavailable):
            record._consume_once(100.0)
        self.assertTrue(record._retired)
        with self.assertRaises(_Unavailable):
            record._consume_once(102.0)

    def test_GS07_nonfinite_clock_consumes_and_retires(self):
        for now in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(now=now):
                record = self.record()
                with self.assertRaises(_Unavailable):
                    record._consume_once(now)
                self.assertTrue(record._spent and record._retired)

    def test_GS08_clock_bool_is_not_float(self):
        record = self.record()
        with self.assertRaises(_Unavailable):
            record._consume_once(True)
        self.assertTrue(record._spent and record._retired)

    def test_GS09_ref_retirement_idempotent_no_counter_proof(self):
        record = self.record()
        record._retire()
        record._retire()
        self.assertEqual(self.capacity._check()[0], 2)
        with self.assertRaises(_Unavailable):
            record._consume_once(102.0)

    def test_GS10_family_retirement_retains_F_and_charge(self):
        family = self.family()
        family._retire()
        self.assertEqual(family._ref, 'b' * 64)
        self.assertEqual(family._nonce, 'a' * 64)
        self.assertEqual(self.capacity._check()[0], 1)

    def test_GS11_retired_family_cannot_bind(self):
        family = self.family(reference=None)
        family._retire()
        with self.assertRaises(_CapacityUnavailable):
            family._bind_once('d' * 64)
        self.assertIsNone(family._ref)

    def test_GS12_second_family_binding_cannot_replace_first(self):
        family = self.family()
        with self.assertRaises(_CapacityUnavailable):
            family._bind_once('d' * 64)
        self.assertEqual(family._ref, 'b' * 64)

    def test_GS13_invalid_F_consumes_binding_without_history_loss(self):
        family = self.family(reference=None)
        with self.assertRaises(_CapacityUnavailable):
            family._bind_once('bad')
        self.assertEqual(family._state, 'retired')
        self.assertTrue(family._binding_attempted)
        self.assertEqual(self.capacity._check()[0], 1)

    def test_GS14_family_exact_ticket_session(self):
        ticket = self.capacity._reserve({}, 'reader', 1)
        with self.assertRaises(_CapacityUnavailable):
            _GuestFamilyRecord(self.session, 'reader', 'a' * 64, self.cohort,
                self.generation, object(), 100.0, 130.0, ticket)

    def test_GS15_record_family_session_identity_not_equal_dict(self):
        family = self.family()
        with self.assertRaises(_Unavailable):
            self.record(family=family, session={})

    def test_GS16_record_original_cohort_identity(self):
        with self.assertRaises(_Unavailable):
            self.record(cohort=object())

    def test_GS17_record_original_generation_identity(self):
        with self.assertRaises(_Unavailable):
            self.record(generation=object())

    def test_GS18_record_family_end_cannot_extend(self):
        with self.assertRaises(_Unavailable):
            self.record(expires=131.0)

    def test_GS19_record_cannot_precede_family_creation(self):
        with self.assertRaises(_Unavailable):
            self.record(created=99.0, expires=120.0)

    def test_GS20_retired_family_cannot_create_descendant(self):
        family = self.family()
        family._retire()
        with self.assertRaises(_Unavailable):
            self.record(family=family)

    def test_GS21_child_retains_exact_family_and_ticket(self):
        family = self.family()
        record = self.record('guest', family=family)
        self.assertIs(record._family, family)
        self.assertIs(self.capacity._tickets[id(record._ticket)], record._ticket)
        self.assertIs(record._session, self.session)

    def test_GS22_purpose_object_equality_is_never_called(self):
        class Hostile:
            def __eq__(self, other):
                raise AssertionError('unexpected equality')
        with self.assertRaises(_Unavailable):
            self.record(purpose=Hostile())

    def test_GS23_empty_committed_ticket_has_explicit_retirement(self):
        ticket = self.capacity._reserve(self.session, 'reader', 0)
        self.capacity._commit(ticket)
        self.capacity._retire_empty_committed(ticket)
        self.assertEqual(ticket._state, 'retired')
        self.assertEqual(self.capacity._tickets, {})

    def test_GS24_nonempty_ticket_cannot_use_empty_cleanup(self):
        ticket = self.capacity._reserve(self.session, 'reader', 1)
        self.capacity._commit(ticket)
        with self.assertRaises(_CapacityUnavailable):
            self.capacity._retire_empty_committed(ticket)
        self.assertEqual(self.capacity._check()[0], 1)

    def test_GS25_lost_reservation_return_stays_retained(self):
        self.capacity._reserve(self.session, 'reader', 256)
        self.assertEqual(self.capacity._check()[0], 256)
        self.assertEqual(len(self.capacity._tickets), 1)

    def test_GS26_unpublished_retirement_does_not_remove_others(self):
        a = self.capacity._reserve(self.session, 'reader', 5)
        b = self.capacity._reserve({}, 'reader', 7)
        self.capacity._retire_unpublished(a)
        self.assertIs(self.capacity._tickets[id(b)], b)
        self.assertEqual(self.capacity._check()[0], 7)

    def test_GS27_committed_is_not_unpublished(self):
        ticket = self.capacity._reserve(self.session, 'reader', 1)
        self.capacity._commit(ticket)
        with self.assertRaises(_CapacityUnavailable):
            self.capacity._retire_unpublished(ticket)
        self.assertEqual(self.capacity._check()[0], 1)

    def test_GS28_wrong_capacity_cannot_release_ticket(self):
        ticket = self.capacity._reserve(self.session, 'reader', 1)
        other = _GuestCapacity()
        with self.assertRaises(_CapacityUnavailable):
            other._retire_unpublished(ticket)
        self.assertEqual(self.capacity._check()[0], 1)

    def test_GS29_zero_tickets_have_physical_count_bound(self):
        for _ in range(512):
            self.capacity._reserve(self.session, 'reader', 0)
        with self.assertRaises(_CapacityUnavailable):
            self.capacity._reserve(self.session, 'reader', 0)
        self.assertEqual(len(self.capacity._tickets), 512)

    def test_GS30_same_session_principal_cannot_change(self):
        self.capacity._reserve(self.session, 'reader', 1)
        with self.assertRaises(_CapacityUnavailable):
            self.capacity._reserve(self.session, 'other', 1)
        self.assertEqual(self.capacity._check()[0], 1)

    def test_GS31_quarantine_prevents_new_capacity(self):
        ticket = self.capacity._reserve(self.session, 'reader', 3)
        self.capacity._uncertain = True
        with self.assertRaises(_CapacityUnavailable):
            self.capacity._reserve(self.session, 'reader', 1)
        self.assertIs(self.capacity._tickets[id(ticket)], ticket)

    def test_GS32_session_retirement_settles_zero_and_pending(self):
        a = self.capacity._reserve(self.session, 'reader', 0)
        b = self.capacity._reserve(self.session, 'reader', 17)
        self.capacity._retire_session(self.session)
        self.assertEqual(self.capacity._tickets, {})
        self.assertEqual((a._state, b._state), ('retired', 'retired'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
