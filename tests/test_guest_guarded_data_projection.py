"""Unrun negative DATA projections of exact R8 internal methods.

DataProjection is intentionally NOT OriginalGuestReferenceStore or an original
installation. Its fixed fake guard returns only fictional DATA so selected
refusal/cleanup tails can be tested; it grants no native admission. No original
auth/native guard is enabled, patched or qualified. Every finalizer test below
must refuse; cleanup-only calls cannot issue an F, response or ACK. Constructor
tests use only non-original objects and must refuse. Tokens are literal fixture
strings, never real credentials. Qualified offline execution is still required.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityUnavailable
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services.pilot_guest_reference_store import OriginalGuestReferenceStore


class Control(BaseException):
    pass


class DataProjection:
    _opening_current_locked = OriginalGuestReferenceStore._opening_current_locked
    _retire_known_family_locked = OriginalGuestReferenceStore._retire_known_family_locked

    def __init__(self, owner, cohort, generation):
        self._installation = owner
        self.cohort, self.generation, self.now = cohort, generation, 101.0
        self.guard_inputs, self.errors = [], []
        self.guard_refuses = False

    def _guard_locked(self, original, token, session, values):
        # Explicit fictional tail projection, NOT actual original gate proof.
        self.guard_inputs.append((original, token, session, values))
        if self.guard_refuses:
            raise _RequestUnavailable()
        return self.cohort, self.generation, self.now

    def _quarantine(self, first):
        # Only projected reporting. Actual auth/broker quarantine is untested.
        self.errors.append(first)
        self._installation._guest_capacity._uncertain = True
        return first


class GuardedGuestData(unittest.TestCase):
    def setUp(self):
        self.session = {'role': 'reader'}
        self.values = ('fixture-user', 'reader', 1.0, 1.0, 'fixture-csrf')
        self.cohort, self.generation = object(), object()
        self.owner = SimpleNamespace(_guest_capacity=_GuestCapacity(),
            _guest_families_by_nonce={}, _guest_families_by_ref={},
            _guest_reference_records={})
        self.projection = DataProjection(self.owner, self.cohort, self.generation)
        self.original = SimpleNamespace(operation='guest-owner-open', end=200.0)
        self.family = self.make_family('a' * 64, self.original)

    def make_family(self, nonce, original):
        ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
        family = _GuestFamilyRecord(self.session, 'fixture-user', nonce,
            self.cohort, self.generation, original, 100.0, 130.0, ticket,
            token='fixture-token', auth_values=self.values, opening_end=200.0)
        self.owner._guest_families_by_nonce[(id(self.session), nonce)] = family
        self.owner._guest_capacity._commit(ticket)
        return family

    def child(self, key, family=None):
        family = self.family if family is None else family
        # Exact pure record constructor requires live family DATA. This local
        # transition issues no original F or authority and enables no gate.
        if family._state == 'opening':
            family._bind_once('b' * 64)
            self.owner._guest_families_by_ref[(id(self.session), family._ref)] = family
        ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
        record = _GuestReferenceRecord(key, 'source', self.session,
            'fixture-user', object(), self.generation, self.cohort, None,
            101.0, 130.0, ticket, family)
        self.owner._guest_capacity._commit(ticket)
        self.owner._guest_reference_records[(id(self.session), 'source', key)] = record
        return record

    def finalizer_refuses(self, original=None, family=None):
        with self.assertRaises(_RequestUnavailable):
            self.projection._opening_current_locked(
                self.original if original is None else original,
                self.family if family is None else family)

    def test_GD01_equal_foreign_request_cannot_retire_opening(self):
        wrong = SimpleNamespace(operation=self.original.operation, end=200.0)
        self.assertEqual(vars(wrong), vars(self.original))
        self.finalizer_refuses(original=wrong)
        self.assertEqual(self.family._state, 'opening')
        self.assertFalse(self.family._sources_spent)
        self.assertFalse(self.owner._guest_capacity._uncertain)

    def test_GD02_wrong_purpose_refuses_without_mutation(self):
        self.original.operation = 'guest-owner-retire'
        self.finalizer_refuses()
        self.assertEqual(self.family._state, 'opening')
        self.assertIsNone(self.family._ref)
        self.assertFalse(self.owner._guest_capacity._uncertain)

    def test_GD03_duplicate_finalizer_cannot_retire_live_F(self):
        self.family._bind_once('b' * 64)
        self.finalizer_refuses()
        self.assertEqual((self.family._state, self.family._ref), ('live', 'b' * 64))
        self.assertFalse(self.family._sources_spent)
        self.assertEqual(self.owner._guest_capacity._check()[0], 1)

    def test_GD04_retired_opening_stays_terminal_and_charged(self):
        self.family._retire()
        self.finalizer_refuses()
        self.assertEqual(self.family._state, 'retired')
        self.assertIsNone(self.family._ref)
        self.assertEqual(self.owner._guest_capacity._check()[0], 1)

    def test_GD05_same_opening_exact_expiry_retires_only_it(self):
        other = self.make_family('b' * 64, object())
        self.projection.now = 130.0
        self.finalizer_refuses()
        self.assertEqual(self.family._state, 'retired')
        self.assertEqual(other._state, 'opening')
        self.assertEqual(self.owner._guest_capacity._check()[0], 2)

    def test_GD06_backwards_clock_cannot_renew_opening(self):
        self.projection.now = 99.0
        self.finalizer_refuses()
        self.assertEqual(self.family._state, 'retired')
        self.projection.now = 101.0
        self.finalizer_refuses()
        self.assertIsNone(self.family._ref)

    def test_GD07_changed_cohort_retires_own_lifetime(self):
        self.projection.cohort = object()
        self.finalizer_refuses()
        self.assertEqual(self.family._state, 'retired')
        self.assertIs(self.family._cohort, self.cohort)

    def test_GD08_original_end_renewal_is_refused(self):
        self.original.end = 201.0
        self.finalizer_refuses()
        self.assertEqual(self.family._state, 'retired')
        self.assertEqual(self.family._opening_end, 200.0)

    def test_GD09_earlier_guard_failure_does_not_mutate_family(self):
        self.projection.guard_refuses = True
        self.projection.now = 130.0
        self.finalizer_refuses()
        self.assertEqual(self.family._state, 'opening')
        self.assertFalse(self.owner._guest_capacity._uncertain)

    def test_GD10_first_snapshot_is_passed_not_recaptured(self):
        self.session['role'] = 'changed-fixture-data'
        wrong = SimpleNamespace(operation='guest-owner-open', end=200.0)
        self.finalizer_refuses(original=wrong)
        original, token, session, values = self.projection.guard_inputs[-1]
        self.assertIs(original, wrong)
        self.assertEqual(token, 'fixture-token')
        self.assertIs(session, self.session)
        self.assertIs(values, self.values)
        self.assertEqual(values[1], 'reader')
        self.assertEqual(self.family._state, 'opening')

    def test_GD11_foreign_index_failure_still_retires_known_child(self):
        self.family._bind_once('b' * 64)
        other = self.make_family('c' * 64, object())
        key = (id(self.session), 'b' * 64)
        self.owner._guest_families_by_ref[key] = other
        child = self.child('d' * 64)
        with self.assertRaises(_RequestUnavailable):
            self.projection._retire_known_family_locked(self.family)
        self.assertEqual(self.family._state, 'retired')
        self.assertIs(self.owner._guest_families_by_ref[key], other)
        self.assertEqual(other._state, 'opening')
        self.assertTrue(child._retired)
        self.assertEqual(self.owner._guest_reference_records, {})
        self.assertEqual(child._ticket._remaining, 0)
        self.assertTrue(self.owner._guest_capacity._uncertain)

    def test_GD12_malformed_first_row_does_not_skip_later_known_child(self):
        bad = (id(self.session), 'source', 'c' * 64)
        self.owner._guest_reference_records[bad] = object()
        child = self.child('d' * 64)
        with self.assertRaises(_RequestUnavailable):
            self.projection._retire_known_family_locked(self.family)
        self.assertIn(bad, self.owner._guest_reference_records)
        self.assertTrue(child._retired)
        self.assertEqual(child._ticket._remaining, 0)
        self.assertEqual(len(self.owner._guest_reference_records), 1)

    def test_GD13_first_child_control_preserved_and_later_child_attempted(self):
        first, later = self.child('c' * 64), self.child('d' * 64)
        real_retire = _GuestReferenceRecord._retire
        control, calls = Control('fixture-first'), []
        def retire(record):
            calls.append(record)
            if record is first:
                raise control
            return real_retire(record)
        with patch.object(_GuestReferenceRecord, '_retire', retire):
            with self.assertRaises(Control) as caught:
                self.projection._retire_known_family_locked(self.family)
        self.assertIs(caught.exception, control)
        self.assertEqual(calls, [first, later])
        self.assertFalse(first._retired)
        self.assertTrue(later._retired)
        self.assertEqual(first._ticket._remaining, 1)
        self.assertEqual(later._ticket._remaining, 0)

    def test_GD14_child_control_outranks_ordinary_index_failure(self):
        self.family._bind_once('b' * 64)
        self.owner._guest_families_by_ref[(id(self.session), 'b' * 64)] = object()
        child = self.child('d' * 64)
        control = Control('fixture-after-index')
        with patch.object(_GuestReferenceRecord, '_retire', side_effect=control):
            with self.assertRaises(Control) as caught:
                self.projection._retire_known_family_locked(self.family)
        self.assertIs(caught.exception, control)
        self.assertEqual(child._ticket._remaining, 1)
        self.assertEqual(self.family._ref, 'b' * 64)

    def test_GD15_original_control_wins_over_later_control(self):
        first, second, last = self.child('c' * 64), self.child('d' * 64), self.child('e' * 64)
        one, two, calls = Control('fixture-one'), Control('fixture-two'), []
        real_retire = _GuestReferenceRecord._retire
        def retire(record):
            calls.append(record)
            if record is first:
                raise one
            if record is second:
                raise two
            return real_retire(record)
        with patch.object(_GuestReferenceRecord, '_retire', retire):
            with self.assertRaises(Control) as caught:
                self.projection._retire_known_family_locked(self.family)
        self.assertIs(caught.exception, one)
        self.assertEqual(calls, [first, second, last])
        self.assertTrue(last._retired)
        self.assertEqual(last._ticket._remaining, 0)

    def test_GD16_nonoriginal_owner_constructor_always_refuses(self):
        for value in (self.owner, self.projection, object(), None, {}):
            with self.assertRaises(_RequestUnavailable):
                OriginalGuestReferenceStore(value)

    def test_GD17_standalone_family_has_no_auth_snapshot(self):
        ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
        family = _GuestFamilyRecord(self.session, 'fixture-user', 'f' * 64,
            self.cohort, self.generation, object(), 100.0, 130.0, ticket)
        self.assertIsNone(family._session_token)
        self.assertIsNone(family._auth_values)
        self.assertIsNone(family._opening_end)
        self.finalizer_refuses(family=family)
        self.assertEqual(family._state, 'opening')

    def test_GD18_incomplete_auth_snapshot_refuses_without_refund(self):
        for fields in ({'token': 'fixture'}, {'auth_values': self.values},
                       {'opening_end': 200.0}, {'token': 'fixture', 'auth_values': self.values}):
            ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
            with self.assertRaises(_CapacityUnavailable):
                _GuestFamilyRecord(self.session, 'fixture-user', 'f' * 64,
                    self.cohort, self.generation, object(), 100.0, 130.0,
                    ticket, **fields)
            self.assertIs(self.owner._guest_capacity._tickets[id(ticket)], ticket)
            self.assertEqual((ticket._state, ticket._remaining), ('reserved', 1))

    def test_GD19_first_auth_tuple_retained_by_identity(self):
        self.assertIs(self.family._auth_values, self.values)
        self.assertIs(self.family._session, self.session)
        self.assertIs(self.family._open_request, self.original)
        self.assertEqual(self.family._opening_end, 200.0)
        wrong = SimpleNamespace(operation='guest-owner-open', end=200.0)
        self.finalizer_refuses(original=wrong)
        self.assertIs(self.family._auth_values, self.values)

    def test_GD20_invalid_original_opening_end_refuses(self):
        for end in (True, 200, 100.0, 99.0, float('nan'), float('inf')):
            ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
            with self.assertRaises(_CapacityUnavailable):
                _GuestFamilyRecord(self.session, 'fixture-user', 'f' * 64,
                    self.cohort, self.generation, object(), 100.0, 130.0,
                    ticket, token='fixture-token', auth_values=self.values,
                    opening_end=end)
            self.assertEqual((ticket._state, ticket._remaining), ('reserved', 1))
