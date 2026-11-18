"""Fictional patched-close declarations only; all FR cases UNRUN.

No token/file open/read or real descriptor close is permitted by these cases.
Fictional integer descriptors are merely labels consumed by the patched port.
Actual native close and lost successful outer returns remain unqualified.
"""
import unittest
from unittest.mock import patch
from freq.services import pilot_fixed_token_reader as source


class FixedReaderFailureData(unittest.TestCase):
    def setUp(self):
        self.reader = source.FixedNodeTokenReader(1000, '192.0.2.25', 115.0)
        self.reader._fds[:] = [700, 701, 702, 703, 704]
        self.reader._states[:] = ['owned'] * 5
        self.visits = []
        self.failures = {}

    def close_port(self, descriptor):
        self.visits.append(descriptor)
        error = self.failures.get(descriptor)
        if error is not None:
            raise error

    def attempt(self, expected):
        with patch.object(source.os, 'close', self.close_port):
            with self.assertRaises(expected) as caught:
                self.reader.close()
        self.assertEqual(self.visits, [704, 703, 702, 701, 700])
        return caught.exception

    def test_FR01_allocation_preserved_after_all_five_close_visits(self):
        error = MemoryError('fictional close allocation')
        self.failures[704] = error
        self.assertIs(self.attempt(MemoryError), error)
        self.assertIs(self.reader._close_errors[4], error)
        self.assertEqual(self.reader.close_observations(),
                         ('closed', 'closed', 'closed', 'closed', 'uncertain'))

    def test_FR02_first_allocation_overrides_ordinary_without_losing_either(self):
        ordinary, allocation = OSError('fictional ordinary'), MemoryError()
        self.failures.update({704: ordinary, 702: allocation})
        self.assertIs(self.attempt(MemoryError), allocation)
        self.assertIs(self.reader._close_errors[4], ordinary)
        self.assertIs(self.reader._close_errors[2], allocation)

    def test_FR03_later_ordinary_does_not_replace_first_allocation(self):
        allocation, ordinary = MemoryError(), OSError('fictional ordinary')
        self.failures.update({704: allocation, 700: ordinary})
        self.assertIs(self.attempt(MemoryError), allocation)
        self.assertIs(self.reader._close_errors[0], ordinary)

    def test_FR04_first_allocation_wins_between_two_allocations(self):
        first, later = MemoryError('first'), MemoryError('later')
        self.failures.update({703: first, 701: later})
        self.assertIs(self.attempt(MemoryError), first)
        self.assertIs(self.reader._close_errors[1], later)

    def test_FR05_later_genuine_control_overrides_allocation(self):
        allocation, control = MemoryError(), KeyboardInterrupt()
        self.failures.update({704: allocation, 700: control})
        self.assertIs(self.attempt(KeyboardInterrupt), control)
        self.assertIs(self.reader._close_errors[4], allocation)

    def test_FR06_first_control_survives_allocation_and_later_control(self):
        first, allocation, later = KeyboardInterrupt(), MemoryError(), SystemExit()
        self.failures.update({704: first, 702: allocation, 700: later})
        self.assertIs(self.attempt(KeyboardInterrupt), first)
        self.assertIs(self.reader._close_errors[2], allocation)
        self.assertIs(self.reader._close_errors[0], later)

    def test_FR07_all_five_failure_references_remain_private_in_fixed_slots(self):
        errors = [OSError('zero'), SystemExit(), MemoryError(), KeyboardInterrupt(), OSError('four')]
        self.failures.update(zip(self.reader._fds, errors))
        self.assertIs(self.attempt(KeyboardInterrupt), errors[3])
        self.assertEqual(len(self.reader._close_errors), 5)
        for retained, original in zip(self.reader._close_errors, errors):
            self.assertIs(retained, original)
        self.assertEqual(self.reader.close_observations(), ('uncertain',) * 5)

    def test_FR08_ordinary_close_failure_remains_uncertain_with_original_retained(self):
        error = OSError('fictional ordinary')
        self.failures[702] = error
        self.attempt(source.PilotCredentialClosureUncertain)
        self.assertIs(self.reader._close_errors[2], error)
        self.assertIs(self.reader._close_failure, error)

    def test_FR09_repeat_allocation_close_preserves_identity_without_retry(self):
        error = MemoryError()
        self.failures[703] = error
        self.assertIs(self.attempt(MemoryError), error)
        with patch.object(source.os, 'close', self.close_port):
            with self.assertRaises(MemoryError) as caught:
                self.reader.close()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.visits, [704, 703, 702, 701, 700])
        self.assertIs(self.reader._close_errors[3], error)

    def test_FR10_repeat_control_close_keeps_first_control_without_retry(self):
        error = KeyboardInterrupt()
        self.failures[702] = error
        self.assertIs(self.attempt(KeyboardInterrupt), error)
        with patch.object(source.os, 'close', self.close_port):
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.reader.close()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.visits, [704, 703, 702, 701, 700])

    def test_FR11_unknown_acquire_is_not_closed_retried_or_refunded(self):
        self.reader._states[2] = 'acquire-pending'
        with patch.object(source.os, 'close', self.close_port):
            with self.assertRaises(source.PilotCredentialClosureUncertain):
                self.reader.close()
        self.assertEqual(self.visits, [704, 703, 701, 700])
        self.assertEqual(self.reader._fds, [700, 701, 702, 703, 704])
        self.assertEqual(self.reader._states[2], 'acquire-pending')
        self.assertEqual(self.reader._close_errors, [None] * 5)

    def test_FR12_success_and_repeat_make_only_five_original_close_calls(self):
        with patch.object(source.os, 'close', self.close_port):
            self.reader.close()
            self.reader.close()
        self.assertEqual(self.visits, [704, 703, 702, 701, 700])
        self.assertEqual(self.reader._fds, [700, 701, 702, 703, 704])
        self.assertEqual(self.reader._close_errors, [None] * 5)
        self.assertIsNone(self.reader._close_failure)
        self.assertEqual(self.reader.close_observations(), ('closed',) * 5)
