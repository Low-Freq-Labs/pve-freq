"""UNRUN private primitive DATA fixtures; no original-owner positive factory.

Only pure duty storage and cleanup lock seams are tested here. Native
entropy/current-owner success cases require the missing original factory;
these fixtures cannot qualify kernel entropy, admission or publication.
"""
import types
import unittest
from unittest import mock

from freq.services import pilot_guest_reference_store as guest
from freq.services.cluster_pilot_http import _RequestUnavailable


class Control(BaseException):
    pass


class EntropyDataTests(unittest.TestCase):
    def duty(self):
        original = object()
        family = types.SimpleNamespace(_opening_end=110.0, _expires=120.0,
            _open_request=original, _entropy_duty=None)
        duty = guest._OpeningEntropyDuty(object(), original, family)
        family._entropy_duty = duty
        return duty

    def test_GE01_pure_duty_has_no_acquiring_method(self):
        duty = self.duty()
        self.assertFalse(hasattr(duty, '_acquire_once'))
        self.assertIs(duty.family._entropy_duty, duty)
        self.assertEqual(duty.phase, 'armed')
        self.assertIsNone(duty.candidate)

    def test_GE02_duty_retains_original_objects_and_earlier_end(self):
        duty = self.duty()
        self.assertIs(duty.original, duty.family._open_request)
        self.assertEqual(duty.end, 110.0)
        duty.family._opening_end = 130.0
        duty.family._expires = 140.0
        self.assertEqual(duty.end, 110.0)

    def test_GE03_supplied_owner_cannot_construct_original_store(self):
        with self.assertRaises(_RequestUnavailable):
            guest.OriginalGuestReferenceStore(types.SimpleNamespace())


class DataLock:
    def __init__(self, acquire_error=None, release_error=None, acquired=True):
        self.acquire_error, self.release_error = acquire_error, release_error
        self.acquired, self.calls = acquired, []

    def acquire(self, **kwargs):
        self.calls.append(('acquire', kwargs))
        if self.acquire_error is not None:
            raise self.acquire_error
        return self.acquired

    def release(self):
        self.calls.append(('release',))
        if self.release_error is not None:
            raise self.release_error


class CleanupDataTests(unittest.TestCase):
    def gates(self, locks):
        notes = []
        def uncertain(error):
            notes.append(error)
            return error
        tx = types.SimpleNamespace(_installation=types.SimpleNamespace(_gate=locks[0]),
            _references=types.SimpleNamespace(_lock=locks[2]),
            _broker=types.SimpleNamespace(_gate=locks[3]), _uncertain=uncertain)
        with mock.patch.object(guest.auth, '_auth_lock', locks[1]):
            gates = guest._OpeningCleanupGates(tx, object())
        return gates, notes

    def test_GE09_cleanup_uses_only_nonblocking_and_no_current_check(self):
        locks = [DataLock() for _ in range(4)]; gates, notes = self.gates(locks)
        with gates:
            self.assertTrue(all(gates._states[i] == 'owned' for i in range(4)))
        self.assertEqual(notes, [])
        for lock in locks:
            self.assertEqual(lock.calls, [('acquire', {'blocking': False}), ('release',)])

    def test_GE10_unknown_acquire_is_not_blindly_released(self):
        control = Control(); locks = [DataLock(), DataLock(acquire_error=control), DataLock(), DataLock()]
        gates, notes = self.gates(locks)
        with self.assertRaises(Control) as caught:
            with gates:
                self.fail('unknown acquisition entered body')
        self.assertIs(caught.exception, control)
        self.assertEqual(locks[0].calls[-1], ('release',))
        self.assertEqual(locks[1].calls, [('acquire', {'blocking': False})])
        self.assertEqual(locks[2].calls, [])
        self.assertEqual(locks[3].calls, [])
        self.assertTrue(notes)

    def test_GE11_false_acquire_releases_prior_only(self):
        locks = [DataLock(), DataLock(acquired=False), DataLock(), DataLock()]
        gates, notes = self.gates(locks)
        with self.assertRaises(_RequestUnavailable):
            with gates:
                self.fail('failed acquisition entered body')
        self.assertEqual(locks[0].calls[-1], ('release',))
        self.assertEqual(locks[1].calls, [('acquire', {'blocking': False})])
        self.assertTrue(notes)

    def test_GE12_all_releases_attempted_and_first_control_wins(self):
        first, later = Control(), Control()
        locks = [DataLock(), DataLock(release_error=later), DataLock(), DataLock(release_error=RuntimeError())]
        gates, notes = self.gates(locks)
        with self.assertRaises(Control) as caught:
            with gates:
                raise first
        self.assertIs(caught.exception, first)
        self.assertTrue(all(lock.calls[-1] == ('release',) for lock in locks))
        self.assertTrue(notes)
