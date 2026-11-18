"""UNRUN pure closed-rights and refusal tails; no original retire ACK proof.

No successful original owner is constructed, enabled or patched. DATA predicates
and fake-lock deadline refusals cannot qualify native/auth/recipient admission.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_reference_capacity import _GuestCapacity, _CapacityUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_state import _GuestReferenceRecord
from freq.services import pilot_guest_retire_response as retire
from freq.services import pilot_guest_reference_store as opening


class RetireResponseData(unittest.TestCase):
    def setUp(self):
        self.build()

    def build(self, reference='b'*64):
        self.session = {'user': 'fixture-user'}
        self.values = ('fixture-user', 'viewer', 1.0, 1.0, 'fixture-csrf')
        self.original = SimpleNamespace(end=120.0, write_end=120.0)
        self.owner = SimpleNamespace(_guest_capacity=_GuestCapacity(),
            _guest_families_by_nonce={}, _guest_families_by_ref={},
            _guest_reference_records={})
        ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
        cohort, generation = object(), object()
        self.family = _GuestFamilyRecord(self.session, 'fixture-user', 'a'*64,
            cohort, generation, object(), 100.0, 130.0, ticket,
            token='fixture-token', auth_values=self.values, opening_end=120.0)
        self.owner._guest_capacity._commit(ticket)
        self.child = None
        if reference is not None:
            self.family._bind_once(reference)
            child_ticket = self.owner._guest_capacity._reserve(self.session, 'fixture-user', 1)
            self.child = _GuestReferenceRecord('c'*64, 'source', self.session,
                'fixture-user', object(), generation, cohort, None, 101.0, 130.0,
                child_ticket, self.family)
            self.owner._guest_capacity._commit(child_ticket)
            self.child._retire()
            self.owner._guest_capacity._release_retired_records(child_ticket, 1)
        self.family._retire()
        self.key = (id(self.session), 'a'*64)
        self.owner._guest_families_by_nonce[self.key] = self.family
        self.duty = retire._GuestRetireResponseDuty(self.original, 'fixture-token',
            self.session, self.values, 'a'*64)
        self.duty.family = self.family

    def check(self):
        return retire._retired_family_data_locked(self.owner, self.duty)

    def refuses(self):
        with self.assertRaises((_RequestUnavailable, _CapacityUnavailable)):
            self.check()

    def test_RT01_known_retired_family_has_no_frame_result(self):
        self.assertIsNone(self.check())
        self.assertEqual(self.family._ref, 'b'*64)
        self.assertIsNone(self.duty.frame)

    def test_RT02_unseen_nonce_retired_without_F_stays_charged(self):
        self.build(reference=None)
        self.assertIsNone(self.check())
        self.assertIsNone(self.family._ref)
        self.assertEqual(self.family._ticket._remaining, 1)
        self.assertEqual(len(self.owner._guest_capacity._tickets), 1)

    def test_RT03_live_or_opening_family_cannot_ack(self):
        for state in ('opening', 'live'):
            self.family._state = state; self.refuses()

    def test_RT04_other_nonce_or_equal_foreign_family_refuses(self):
        self.duty.nonce = 'd'*64; self.refuses()
        self.duty.nonce = 'a'*64
        self.owner._guest_families_by_nonce[self.key] = object()
        self.refuses()

    def test_RT05_equal_foreign_session_does_not_substitute(self):
        self.duty.session = dict(self.session)
        self.refuses()

    def test_RT06_different_principal_refuses(self):
        self.duty.values = ('other',) + self.values[1:]
        self.refuses()

    def test_RT07_removed_nonce_index_refuses(self):
        self.owner._guest_families_by_nonce.clear()
        self.refuses()

    def test_RT08_remaining_F_index_prevents_ack(self):
        self.owner._guest_families_by_ref[(id(self.session), self.family._ref)] = self.family
        self.refuses()

    def test_RT09_remaining_retired_descendant_prevents_ack(self):
        self.assertTrue(self.child._retired)
        self.owner._guest_reference_records[(id(self.session), 'source', self.child._key)] = self.child
        self.refuses()

    def test_RT10_unknown_index_or_child_row_prevents_ack(self):
        self.owner._guest_families_by_ref['bad'] = object()
        self.refuses()
        self.owner._guest_families_by_ref.clear()
        self.owner._guest_reference_records['bad'] = object()
        self.refuses()

    def test_RT11_foreign_duty_and_auth_snapshot_types_refuse(self):
        self.duty = SimpleNamespace(**{slot: getattr(self.duty, slot)
            for slot in retire._GuestRetireResponseDuty.__slots__})
        self.refuses()

    def test_RT12_nonce_and_snapshot_shapes_refuse(self):
        for value in ('a'*63, 'A'*64, b'a'*64, None):
            self.duty.nonce = value; self.refuses()
        self.duty.nonce = 'a'*64
        self.duty.values = list(self.values); self.refuses()

    def test_RT13_repeat_predicate_cannot_renew_refund_or_ack(self):
        before = (self.family._created, self.family._expires,
            self.family._ticket._remaining, len(self.owner._guest_capacity._tickets))
        self.assertIsNone(self.check()); self.assertIsNone(self.check())
        self.assertEqual(before, (self.family._created, self.family._expires,
            self.family._ticket._remaining, len(self.owner._guest_capacity._tickets)))
        self.assertIsNone(self.duty.frame)

    def test_RT14_retired_missing_ticket_is_not_current_ack(self):
        # Completed session logout belongs to ordinary cleanup, not positive
        # authenticated retirement response admission for this old session.
        self.owner._guest_capacity._retire_session(self.session)
        self.refuses()

    def test_RT15_public_entries_refuse_nonoriginal_store_without_hooks(self):
        class Foreign:
            def __getattribute__(self, name):
                raise AssertionError('foreign store hook called')
        for function, arguments in ((retire.admit_retired_response, (Foreign(), object())),
                (retire.write_retired_response, (Foreign(), object(), object())),
                (retire.retire_handler_duty, (Foreign(), object()))):
            with self.assertRaises(_RequestUnavailable):
                function(*arguments)

    def test_RT16_first_write_end_cannot_be_recaptured_later(self):
        self.original.write_end = 110.0
        duty = retire._GuestRetireResponseDuty(self.original, 'fixture-token',
            self.session, self.values, 'a'*64)
        self.original.write_end = 119.0
        self.assertEqual(duty.initial_write_end, 110.0)
        self.assertEqual(duty.end, 110.0)

    def gates(self, locks):
        tx = SimpleNamespace(_installation=SimpleNamespace(_gate=locks[0]),
            _references=SimpleNamespace(_lock=locks[2]), _broker=SimpleNamespace(_gate=locks[3]),
            _uncertain=lambda error: error,
            _current_locked=lambda *args: self.fail('positive currentness reached'))
        with patch.object(retire.auth, '_auth_lock', locks[1]):
            return retire._RetireResponseGates(tx, self.original, self.duty)

    def test_RT17_expired_end_refuses_before_lock_acquisition(self):
        locks = [DataLock() for _ in range(4)]
        gates = self.gates(locks)
        with patch.object(opening.time, 'monotonic', return_value=120.0):
            with self.assertRaises(_RequestUnavailable):
                with gates:
                    self.fail('expired gate entered')
        self.assertTrue(all(lock.calls == [] for lock in locks))

    def test_RT18_shortening_after_first_acquire_releases_before_next(self):
        locks = [DataLock() for _ in range(4)]
        locks[0].on_acquire = lambda: setattr(self.original, 'write_end', 100.0)
        gates = self.gates(locks)
        with patch.object(opening.time, 'monotonic', return_value=100.0):
            with self.assertRaises(_RequestUnavailable):
                with gates:
                    self.fail('shortened gate entered')
        self.assertEqual(locks[0].calls, ['acquire', 'release'])
        self.assertTrue(all(lock.calls == [] for lock in locks[1:]))


class DataLock:
    def __init__(self):
        self.calls, self.on_acquire = [], None

    def acquire(self, **kwargs):
        self.calls.append('acquire')
        if self.on_acquire:
            self.on_acquire()
        return True

    def release(self):
        self.calls.append('release')
