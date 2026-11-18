"""UNRUN negative DATA tails, never an original factory or response success.

The guard returns fictional shapes only. Every response-currentness invocation
must refuse; no auth/native gate, frame admission, send or entropy is called.
Cleanup projections exercise logical table retirement, not original custody.
"""
from types import SimpleNamespace
import unittest

from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.guest_family_state import _GuestFamilyRecord
from freq.services.guest_reference_capacity import _GuestCapacity
from freq.services.pilot_guest_reference_store import (
    OriginalGuestReferenceStore, _OpeningEntropyDuty, _GuestOpeningResponseDuty,
)


class DataProjection:
    _opening_response_locked = OriginalGuestReferenceStore._opening_response_locked

    def __init__(self, owner, cohort, generation):
        self._installation = owner
        self.cohort, self.generation, self.now = cohort, generation, 101.0
        self.captures = []

    def _guard_locked(self, original, token, session, values, phase='ready'):
        self.captures.append((original, token, session, values, phase))
        return self.cohort, self.generation, self.now


class OpeningResponseNegativeData(unittest.TestCase):
    def setUp(self):
        session = {'role': 'fixture-role'}
        cohort, generation = object(), object()
        self.owner = SimpleNamespace(_guest_capacity=_GuestCapacity(),
            _guest_families_by_nonce={}, _guest_families_by_ref={})
        self.projection = DataProjection(self.owner, cohort, generation)
        self.original = SimpleNamespace(operation='guest-owner-open', body_taken=True,
            end=120.0, write_end=120.0, guest_response=None)
        self.values = ('fixture-user', 'viewer', 1.0, 1.0, 'fixture-csrf')
        ticket = self.owner._guest_capacity._reserve(session, 'fixture-user', 1)
        self.family = _GuestFamilyRecord(session, 'fixture-user', 'a'*64,
            cohort, generation, self.original, 100.0, 130.0, ticket,
            token='fixture-token', auth_values=self.values, opening_end=120.0)
        self.owner._guest_capacity._commit(ticket)
        self.owner._guest_families_by_nonce[(id(session), self.family._nonce)] = self.family
        # Pure local bind DATA, not unpredictable original F issuance.
        self.family._bind_once('b'*64)
        self.owner._guest_families_by_ref[(id(session), self.family._ref)] = self.family
        entropy = _OpeningEntropyDuty(self.projection, self.original, self.family)
        entropy.phase, entropy.candidate = 'bound', self.family._ref
        self.family._entropy_duty = entropy
        self.duty = _GuestOpeningResponseDuty(self.original, self.family)
        self.original.guest_response = self.duty

    def refuses(self, original=None, duty=None):
        with self.assertRaises(_RequestUnavailable):
            self.projection._opening_response_locked(
                self.original if original is None else original,
                self.duty if duty is None else duty)

    def test_GR01_equal_foreign_original_refuses(self):
        self.refuses(original=SimpleNamespace(**vars(self.original)))

    def test_GR02_replaced_original_duty_refuses(self):
        other = _GuestOpeningResponseDuty(self.original, self.family)
        self.refuses(duty=other)

    def test_GR03_wrong_operation_and_untaken_body_refuse(self):
        self.original.operation = 'guest-owner-retire'; self.refuses()
        self.original.operation = 'guest-owner-open'
        self.original.body_taken = False; self.refuses()

    def test_GR04_retire_before_publication_refuses(self):
        self.family._retire(); self.refuses()
        self.assertEqual(self.family._ref, 'b'*64)
        self.assertEqual(self.family._ticket._remaining, 1)

    def test_GR05_removed_F_index_refuses(self):
        del self.owner._guest_families_by_ref[(id(self.family._session), self.family._ref)]
        self.refuses()

    def test_GR06_other_family_under_same_nonce_refuses(self):
        self.owner._guest_families_by_nonce[(id(self.family._session), self.family._nonce)] = object()
        self.refuses()

    def test_GR07_replaced_cohort_or_generation_refuses(self):
        old = self.projection.cohort
        self.projection.cohort = object(); self.refuses()
        self.projection.cohort = old
        self.projection.generation = object(); self.refuses()

    def test_GR08_unbound_or_replaced_entropy_refuses(self):
        entropy = self.family._entropy_duty
        entropy.phase = 'received'; self.refuses()
        entropy.phase = 'bound'
        self.family._entropy_duty = object(); self.refuses()

    def test_GR09_changed_F_or_foreign_thread_refuses(self):
        entropy = self.family._entropy_duty
        entropy.candidate = 'c'*64; self.refuses()
        entropy.candidate = self.family._ref
        entropy.thread = object(); self.refuses()

    def test_GR10_original_end_extension_or_expiry_refuses(self):
        self.original.end = 121.0; self.refuses()
        self.original.end = 120.0
        self.projection.now = 120.0; self.refuses()
        self.projection.now = 99.0; self.refuses()

    def test_GR11_write_end_cannot_renew_or_be_nonfinite(self):
        self.original.write_end = 121.0; self.refuses()
        self.original.write_end = float('nan'); self.refuses()

    def test_GR12_retained_end_not_recomputed_to_later_allowance(self):
        self.duty.end = 121.0; self.refuses()
        self.assertEqual(self.family._opening_end, 120.0)
        self.assertEqual(self.original.end, 120.0)
