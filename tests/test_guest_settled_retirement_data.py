"""UNRUN cleanup DATA predicates, no original logout or native authority.

Tests construct pure records/tables and manually model their closed state.
True means only that this exact old family has no remaining logical rights.
The original caller must still hold and validate its real cleanup gates.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.api import auth
from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityTicket
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_reference_store import OriginalGuestReferenceStore


class DataProjection:
    _already_retired_session_family_locked = OriginalGuestReferenceStore._already_retired_session_family_locked

    def __init__(self, owner):
        self._installation = owner


class SettledRetirementData(unittest.TestCase):
    def setUp(self):
        self.session = {'user': 'fixture-user'}
        self.token = 'fixture-token'
        self.values = ('fixture-user', 'viewer', 1.0, 1.0, 'fixture-csrf')
        self.owner = SimpleNamespace(_guest_capacity=_GuestCapacity(),
            _guest_families_by_nonce={}, _guest_families_by_ref={},
            _guest_reference_records={}, _issued_sessions={self.token: self.session})
        self.auth_map = {self.token: self.session}
        self.projection = DataProjection(self.owner)
        cohort, generation, original = object(), object(), object()
        ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
        self.family = _GuestFamilyRecord(self.session, 'fixture-user', 'a'*64,
            cohort, generation, original, 100.0, 130.0, ticket,
            token=self.token, auth_values=self.values, opening_end=120.0)
        self.owner._guest_capacity._commit(ticket)
        self.family._bind_once('b'*64)
        self.nonce_key, self.ref_key = (id(self.session), 'a'*64), (id(self.session), 'b'*64)
        self.owner._guest_families_by_nonce[self.nonce_key] = self.family
        self.owner._guest_families_by_ref[self.ref_key] = self.family
        child_ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
        self.child = _GuestReferenceRecord('c'*64, 'source', self.session,
            'fixture-user', object(), generation, cohort, None, 101.0, 130.0,
            child_ticket, self.family)
        self.owner._guest_capacity._commit(child_ticket)
        self.child_key = (id(self.session), 'source', 'c'*64)
        self.owner._guest_reference_records[self.child_key] = self.child

    def close_DATA(self):
        self.family._retire()
        self.child._retire()
        self.owner._guest_capacity._retire_session(self.session)
        self.owner._guest_families_by_nonce.clear()
        self.owner._guest_families_by_ref.clear()
        self.owner._guest_reference_records.clear()
        self.owner._issued_sessions.clear()
        self.auth_map.clear()

    def check(self):
        with patch.object(auth, '_auth_tokens', self.auth_map):
            return self.projection._already_retired_session_family_locked(self.family)

    def test_SR01_all_closed_facts_true_and_no_mutation(self):
        self.close_DATA()
        ticket = self.family._ticket
        before = (ticket._state, ticket._remaining, self.family._state,
                  self.family._ref, id(ticket), dict(self.owner._guest_capacity._tickets))
        self.assertIs(self.check(), True)
        self.assertEqual(before, (ticket._state, ticket._remaining, self.family._state,
            self.family._ref, id(ticket), dict(self.owner._guest_capacity._tickets)))
        self.assertEqual(ticket._remaining, 1)

    def test_SR02_old_session_in_either_auth_map_refuses(self):
        self.close_DATA(); self.owner._issued_sessions[self.token] = self.session
        self.assertIs(self.check(), False)
        self.owner._issued_sessions.clear(); self.auth_map[self.token] = self.session
        self.assertIs(self.check(), False)

    def test_SR03_distinct_new_session_is_untouched(self):
        self.close_DATA(); new = {'user': 'fixture-user'}
        self.owner._issued_sessions[self.token] = new; self.auth_map[self.token] = new
        self.assertIs(self.check(), True)
        self.assertIs(self.owner._issued_sessions[self.token], new)
        self.assertIs(self.auth_map[self.token], new)

    def test_SR04_missing_ticket_with_wrong_state_not_settled(self):
        self.close_DATA(); self.family._ticket._state = 'committed'
        self.assertIs(self.check(), False)

    def test_SR05_retired_ticket_still_in_ledger_not_settled(self):
        self.close_DATA(); ticket = self.family._ticket
        self.owner._guest_capacity._tickets[id(ticket)] = ticket
        self.assertIs(self.check(), False)

    def test_SR06_any_nonce_index_entry_not_settled(self):
        for value in (None, self.family, object()):
            self.close_DATA(); self.owner._guest_families_by_nonce[self.nonce_key] = value
            self.assertIs(self.check(), False)

    def test_SR07_any_F_index_entry_not_settled(self):
        self.close_DATA(); self.owner._guest_families_by_ref[self.ref_key] = self.family
        self.assertIs(self.check(), False)

    def test_SR08_retired_known_child_still_indexed_not_settled(self):
        self.close_DATA(); self.owner._guest_reference_records[self.child_key] = self.child
        self.assertTrue(self.child._retired)
        self.assertIs(self.check(), False)

    def test_SR09_wrong_ticket_session_principal_or_charge_refuses(self):
        self.close_DATA(); ticket = self.family._ticket
        ticket._session = dict(self.session); self.assertIs(self.check(), False)
        ticket._session = self.session; ticket._principal = 'other'
        self.assertIs(self.check(), False)
        ticket._principal = 'fixture-user'; ticket._remaining = 0
        self.assertIs(self.check(), False)

    def test_SR10_family_not_terminal_never_settled(self):
        self.close_DATA(); self.family._state = 'live'
        self.assertIs(self.check(), False)

    def test_SR11_untrusted_selector_or_auth_tuple_types_refuse(self):
        class ForeignText(str):
            def __eq__(self, other):
                raise AssertionError('foreign comparison invoked')
        self.close_DATA(); self.family._session_token = ForeignText(self.token)
        self.assertIs(self.check(), False)
        self.family._session_token = self.token; self.family._auth_values = list(self.values)
        self.assertIs(self.check(), False)

    def test_SR12_unknown_or_unbounded_child_rows_not_settled(self):
        self.close_DATA(); self.owner._guest_reference_records[('bad',)] = object()
        self.assertIs(self.check(), False)
        self.owner._guest_reference_records = {i: object() for i in range(4097)}
        self.assertIs(self.check(), False)

    def test_SR13_sibling_old_session_family_index_not_settled(self):
        self.close_DATA()
        ticket = _CapacityTicket(self.session, 'fixture-user', 1)
        sibling = _GuestFamilyRecord(self.session, 'fixture-user', 'd'*64,
            object(), object(), object(), 100.0, 130.0, ticket,
            token=self.token, auth_values=self.values, opening_end=120.0)
        ticket._state = 'committed'
        sibling._bind_once('e'*64)
        sibling._retire()
        self.owner._guest_families_by_nonce[(id(self.session), sibling._nonce)] = sibling
        self.assertIs(self.check(), False)
        self.owner._guest_families_by_nonce.clear()
        self.owner._guest_families_by_ref[(id(self.session), sibling._ref)] = sibling
        self.assertIs(self.check(), False)

    def test_SR14_unindexed_old_session_ticket_not_settled(self):
        self.close_DATA()
        ticket = _CapacityTicket(self.session, 'fixture-user', 1)
        self.owner._guest_capacity._tickets[id(ticket)] = ticket
        self.assertIs(self.check(), False)
