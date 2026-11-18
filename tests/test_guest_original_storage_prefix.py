"""Unrun pure pending-prefix/retirement intentions, no original admission.

Importing the canonical source belongs only in a qualified offline worker.
The pending class constructs DATA; these tests never bind native components,
set live/currentness True, fake HTTP/native owners or admit an auth response.
Failure injection tests only the explicitly named DATA cleanup stages.
"""
import unittest
from unittest.mock import patch

from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services import pilot_guest_retirement as retirement


class GuestOriginalStoragePrefix(unittest.TestCase):
    def setUp(self):
        self.owner = OriginalPilotInstallation()
        self.owner._prepare_pending_original()
        self.session, self.other = {}, {}
        self.cohort, self.generation = object(), object()

    def family(self, session, nonce='a' * 64, reference='b' * 64):
        capacity = self.owner._guest_capacity
        ticket = capacity._reserve(session, 'reader', 1)
        family = _GuestFamilyRecord(session, 'reader', nonce, self.cohort,
            self.generation, object(), 100.0, 130.0, ticket)
        self.owner._guest_families_by_nonce[(id(session), nonce)] = family
        capacity._commit(ticket)
        family._bind_once(reference)
        self.owner._guest_families_by_ref[(id(session), reference)] = family
        return family

    def child(self, family):
        capacity = self.owner._guest_capacity
        ticket = capacity._reserve(family._session, 'reader', 1)
        record = _GuestReferenceRecord('c' * 64, 'source', family._session,
            'reader', object(), self.generation, self.cohort, None,
            101.0, 130.0, ticket, family)
        self.owner._guest_reference_records[(id(family._session), 'source',
                                             record._key)] = record
        capacity._commit(ticket)
        return record

    def test_GS33_pending_prefix_owns_nine_distinct_maps_no_native(self):
        maps = self.owner._original_component_tables
        self.assertEqual(len(maps), 9)
        self.assertEqual(len({id(t) for t in maps}), 9)
        self.assertTrue(all(type(t) is dict and not t for t in maps))
        self.assertTrue(self.owner._original_component_tables_current())
        self.assertFalse(self.owner._native_current_locked(object()))
        self.assertFalse(self.owner._live)
        self.assertIsNone(self.owner._server)
        self.assertIsNone(self.owner._gate)

    def test_GS34_replacement_of_each_guest_map_refuses_identity(self):
        for field in ('_guest_families_by_nonce', '_guest_families_by_ref',
                      '_guest_reference_records'):
            with self.subTest(field=field):
                owner = OriginalPilotInstallation()
                owner._prepare_pending_original()
                setattr(owner, field, {})
                self.assertFalse(owner._original_component_tables_current())
                with self.assertRaises(ValueError):
                    retirement.retire_guest_session_data_locked(owner, {})
                self.assertFalse(owner._native_current_locked(object()))

    def test_GS35_capacity_holder_substitution_cannot_copy_authority(self):
        original = self.owner._guest_capacity
        replacement = _GuestCapacity()
        replacement._tickets = original._tickets
        self.owner._guest_capacity = replacement
        self.assertFalse(self.owner._original_component_tables_current())
        self.assertFalse(self.owner._native_current_locked(object()))

    def test_GS36_session_retirement_preserves_unrelated_same_text(self):
        family = self.family(self.session)
        child = self.child(family)
        other_family = self.family(self.other)
        other_child = self.child(other_family)
        old_other_ticket = other_child._ticket
        retirement.retire_guest_session_data_locked(self.owner, self.session)
        self.assertEqual(family._state, 'retired')
        self.assertTrue(child._retired)
        self.assertEqual(family._ref, 'b' * 64)
        self.assertNotIn((id(self.session), family._nonce),
                         self.owner._guest_families_by_nonce)
        self.assertIs(self.owner._guest_families_by_ref[(id(self.other), 'b' * 64)],
                      other_family)
        self.assertIs(self.owner._guest_reference_records[
            (id(self.other), 'source', 'c' * 64)], other_child)
        self.assertIs(self.owner._guest_capacity._tickets[id(old_other_ticket)],
                      old_other_ticket)
        self.assertEqual(self.owner._guest_capacity._check()[0], 2)

    def test_GS37_family_missing_optional_index_can_retire_session(self):
        family = self.family(self.session)
        family._retire()
        del self.owner._guest_families_by_ref[(id(self.session), family._ref)]
        self.assertEqual(family._ref, 'b' * 64)
        self.assertEqual(self.owner._guest_capacity._check()[0], 1)
        retirement.retire_guest_session_data_locked(self.owner, self.session)
        self.assertEqual(self.owner._guest_families_by_nonce, {})
        self.assertEqual(self.owner._guest_capacity._tickets, {})

    def test_GS38_bad_family_row_does_not_skip_children_or_tickets(self):
        family = self.family(self.session)
        child = self.child(family)
        self.owner._guest_families_by_nonce['malformed'] = object()
        with self.assertRaises(ValueError):
            retirement.retire_guest_session_data_locked(self.owner, self.session)
        self.assertTrue(child._retired)
        self.assertEqual(self.owner._guest_reference_records, {})
        self.assertEqual(self.owner._guest_capacity._tickets, {})
        self.assertTrue(self.owner._guest_capacity._uncertain)
        self.assertIn('malformed', self.owner._guest_families_by_nonce)
        self.assertFalse(self.owner._native_current_locked(object()))

    def test_GS39_family_control_still_attempts_children_and_tickets(self):
        class Cancel(BaseException):
            pass
        family = self.family(self.session)
        child = self.child(family)
        control = Cancel('fictional cancellation')
        with patch.object(_GuestFamilyRecord, '_retire', side_effect=control):
            with self.assertRaises(Cancel) as caught:
                retirement.retire_guest_session_data_locked(self.owner, self.session)
        self.assertIs(caught.exception, control)
        self.assertTrue(child._retired)
        self.assertEqual(self.owner._guest_capacity._tickets, {})
        self.assertTrue(self.owner._guest_capacity._uncertain)
        self.assertIs(self.owner._guest_families_by_nonce[
            (id(self.session), family._nonce)], family)

    def test_GS40_first_genuine_control_precedence(self):
        class Cancel(BaseException):
            pass
        ordinary = ValueError('fictional ordinary failure')
        first_control = Cancel('first fictional control')
        later_control = Cancel('later fictional control')
        self.assertIs(retirement._first(None, ordinary), ordinary)
        self.assertIs(retirement._first(ordinary, first_control), first_control)
        self.assertIs(retirement._first(first_control, later_control), first_control)
        self.assertIs(retirement._first(first_control, ordinary), first_control)
        self.assertFalse(self.owner._native_current_locked(object()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
