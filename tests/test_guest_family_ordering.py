"""Unrun private DATA collision intentions; no entropy/admission/native owner.

Sequential calls model only the required writer order. No test constructs a
positive live/current owner or claims the outside original writer exists.
"""
import unittest

from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _CapacityUnavailable
from freq.services.guest_family_ordering import bind_family_reference_data_locked


class GuestFamilyOrdering(unittest.TestCase):
    def setUp(self):
        self.owner = OriginalPilotInstallation()
        self.owner._prepare_pending_original()
        self.session, self.other = {}, {}
        self.cohort, self.generation = object(), object()

    def opening(self, nonce, session=None):
        if session is None:
            session = self.session
        ticket = self.owner._guest_capacity._reserve(session, 'reader', 1)
        family = _GuestFamilyRecord(session, 'reader', nonce, self.cohort,
            self.generation, object(), 100.0, 130.0, ticket)
        self.owner._guest_families_by_nonce[(id(session), nonce)] = family
        self.owner._guest_capacity._commit(ticket)
        return family

    def bind(self, family, value='f' * 64):
        return bind_family_reference_data_locked(self.owner, family, value)

    def test_FO01_active_collision_retires_new_C_without_refund(self):
        old, new = self.opening('a' * 64), self.opening('b' * 64)
        self.assertTrue(self.bind(old))
        self.assertFalse(self.bind(new))
        self.assertEqual(new._state, 'retired')
        self.assertIsNone(new._ref)
        self.assertEqual(new._ticket._state, 'committed')
        self.assertEqual(self.owner._guest_capacity._check()[0], 2)
        self.assertIs(self.owner._guest_families_by_ref[(id(self.session), 'f' * 64)], old)
        self.assertFalse(old._sources_spent or new._sources_spent)

    def test_FO02_retired_history_survives_optional_index_removal(self):
        old = self.opening('a' * 64)
        self.bind(old)
        old._retire()
        del self.owner._guest_families_by_ref[(id(self.session), old._ref)]
        new = self.opening('b' * 64)
        self.assertFalse(self.bind(new))
        self.assertEqual(old._ref, 'f' * 64)
        self.assertEqual(self.owner._guest_families_by_ref, {})

    def test_FO03_two_openings_at_most_one_in_each_writer_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                self.setUp()
                pair = [self.opening('a' * 64), self.opening('b' * 64)]
                if reverse:
                    pair.reverse()
                self.assertEqual([self.bind(f) for f in pair], [True, False])
                self.assertIs(self.owner._guest_families_by_ref[(id(self.session), 'f' * 64)], pair[0])

    def test_FO04_delayed_old_F_never_selects_new_family(self):
        old = self.opening('a' * 64)
        self.bind(old)
        old._retire()
        del self.owner._guest_families_by_ref[(id(self.session), old._ref)]
        collided = self.opening('b' * 64)
        self.assertFalse(self.bind(collided))
        new = self.opening('c' * 64)
        self.assertTrue(self.bind(new, 'e' * 64))
        self.assertIsNone(self.owner._guest_families_by_ref.get((id(self.session), 'f' * 64)))
        self.assertIs(self.owner._guest_families_by_ref[(id(self.session), 'e' * 64)], new)
        self.assertFalse(new._sources_spent)

    def test_FO05_lost_response_does_not_erase_assigned_F(self):
        old = self.opening('a' * 64)
        self.assertTrue(self.bind(old))
        # No response exists in this DATA model; retire after lost publication.
        old._retire()
        del self.owner._guest_families_by_ref[(id(self.session), old._ref)]
        self.assertFalse(self.bind(self.opening('b' * 64)))

    def test_FO06_same_text_is_distinct_original_session_namespace(self):
        old = self.opening('a' * 64)
        new = self.opening('a' * 64, self.other)
        self.assertTrue(self.bind(old))
        self.assertTrue(self.bind(new))
        self.assertIs(self.owner._guest_families_by_ref[(id(self.session), 'f' * 64)], old)
        self.assertIs(self.owner._guest_families_by_ref[(id(self.other), 'f' * 64)], new)

    def test_FO07_retire_before_entropy_return_cannot_bind(self):
        family = self.opening('a' * 64)
        family._retire()
        with self.assertRaises(_CapacityUnavailable):
            self.bind(family)
        self.assertIsNone(family._ref)
        self.assertEqual(self.owner._guest_families_by_ref, {})

    def test_FO08_repeated_binding_cannot_replace_original_F(self):
        family = self.opening('a' * 64)
        self.bind(family)
        with self.assertRaises(_CapacityUnavailable):
            self.bind(family, 'e' * 64)
        self.assertEqual(family._ref, 'f' * 64)
        self.assertEqual(len(self.owner._guest_families_by_ref), 1)

    def test_FO09_duplicate_family_ticket_is_not_extra_capacity(self):
        old, new = self.opening('a' * 64), self.opening('b' * 64)
        new._ticket = old._ticket  # Explicit corrupt DATA, never native grant.
        with self.assertRaises(_CapacityUnavailable):
            self.bind(new)
        self.assertTrue(self.owner._guest_capacity._uncertain)
        self.assertEqual(self.owner._guest_families_by_ref, {})

    def test_FO10_orphan_optional_index_is_never_overwritten(self):
        family = self.opening('a' * 64)
        orphan = object()
        self.owner._guest_families_by_ref[(id(self.session), 'f' * 64)] = orphan
        with self.assertRaises(_CapacityUnavailable):
            self.bind(family)
        self.assertIs(self.owner._guest_families_by_ref[(id(self.session), 'f' * 64)], orphan)
        self.assertIsNone(family._ref)

    def test_FO11_malformed_candidate_quarantines_without_issuing(self):
        family = self.opening('a' * 64)
        with self.assertRaises(_CapacityUnavailable):
            self.bind(family, 'invalid')
        self.assertTrue(self.owner._guest_capacity._uncertain)
        self.assertIsNone(family._ref)
        self.assertFalse(self.owner._native_current_locked(object()))

    def test_FO12_charged_tombstones_hit_exact_512_bound(self):
        for i in range(512):
            self.opening(format(i, '064x'))._retire()
        self.assertEqual(self.owner._guest_capacity._check()[0], 512)
        with self.assertRaises(_CapacityUnavailable):
            self.opening('f' * 64)
        self.assertEqual(len(self.owner._guest_families_by_nonce), 512)
        self.assertFalse(self.owner._native_current_locked(object()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
