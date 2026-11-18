"""Original asset acquire/retire; explicit fake read/close ports, no file access."""
import threading
import unittest
from unittest.mock import patch

from freq.services import pilot_fixed_assets as assets


class Control(BaseException):
    pass


class AssetErrorHolderCustodyData(unittest.TestCase):
    def attempt(self):
        return assets.FixedPilotAssetAttempt(100.0)

    def own(self, attempt, indices):
        for i in indices:
            attempt._fds[i] = 7000 + i  # Fictional DATA identifiers only.
            attempt._states[i] = 'owned'

    def fail_acquire(self, attempt, body, closes=None):
        seen = []
        def opened(value):
            self.own(value, (0, 1, 2))
            raise body
        def close(fd):
            seen.append(fd)
            error = (closes or {}).get(fd)
            if error is not None:
                raise error
        with patch.object(assets.FixedPilotAssetAttempt, '_open_all', opened), patch.object(assets.os, 'close', close):
            try:
                attempt.acquire()
            except BaseException as error:
                return error, seen
        self.fail('failed original acquisition unexpectedly succeeded')

    def test_FA01_success_retains_payloads_and_retires_known_handles_in_reverse(self):
        value = self.attempt()
        seen = []
        holders = value._fds, value._states, value._identities
        def opened(attempt):
            self.own(attempt, range(len(assets._NODES)))
        with patch.object(assets.time, 'monotonic', return_value=1.0), patch.object(assets.FixedPilotAssetAttempt, '_open_all', opened), patch.object(assets.FixedPilotAssetAttempt, '_recheck', lambda attempt: None), patch.object(assets.FixedPilotAssetAttempt, '_read_file', lambda attempt, i: b'fictional-' + str(i).encode()), patch.object(assets.os, 'close', seen.append):
            self.assertIs(value.acquire(), value)
            mime, body = value.private_payload('app.html')
            self.assertEqual((mime, body), ('text/html', b'fictional-11'))
            value.retire()
            value.retire()
        self.assertEqual(seen, [7000 + i for i in reversed(range(len(assets._NODES)))])
        self.assertTrue(all(a is b for a, b in zip(holders, (value._fds, value._states, value._identities))))
        self.assertEqual(value._cleanup, 'locally-settled')
        self.assertIsNone(value._asset_failure)
        self.assertEqual(value._asset_errors, [None] * (len(assets._NODES) + 2))

    def test_FA02_body_memory_survives_successful_known_cleanup_by_identity(self):
        value, body = self.attempt(), MemoryError('fictional body')
        error, seen = self.fail_acquire(value, body)
        self.assertIs(error, body)
        self.assertIs(value._asset_errors[0], body)
        self.assertIs(value._asset_failure, body)
        self.assertEqual(seen, [7002, 7001, 7000])
        self.assertEqual(value._cleanup, 'locally-settled')

    def test_FA03_close_memory_outranks_ordinary_body_without_losing_either(self):
        value, body, close = self.attempt(), ValueError('fictional body'), MemoryError('fictional close')
        error, seen = self.fail_acquire(value, body, {7001: close})
        self.assertIs(error, close)
        self.assertIs(value._asset_errors[0], body)
        self.assertIs(value._asset_errors[2], close)
        self.assertIs(value._asset_errors[-1], close)
        self.assertIs(value._asset_failure, close)
        self.assertEqual(seen, [7002, 7001, 7000])
        self.assertEqual(value._states[1], 'uncertain')

    def test_FA04_first_close_control_outranks_body_memory_and_later_control(self):
        value, body, first, later = self.attempt(), MemoryError(), Control(), Control()
        error, seen = self.fail_acquire(value, body, {7002: first, 7000: later})
        self.assertIs(error, first)
        self.assertIs(value._asset_errors[3], first)
        self.assertIs(value._asset_errors[1], later)
        self.assertIs(value._asset_errors[0], body)
        self.assertIs(value._asset_failure, first)
        self.assertEqual(seen, [7002, 7001, 7000])

    def test_FA05_body_control_stays_first_through_close_control_and_memory(self):
        value, body, later, memory = self.attempt(), Control(), Control(), MemoryError()
        error, seen = self.fail_acquire(value, body, {7002: memory, 7001: later})
        self.assertIs(error, body)
        self.assertIs(value._asset_failure, body)
        self.assertIs(value._asset_errors[3], memory)
        self.assertIs(value._asset_errors[2], later)
        self.assertEqual(seen, [7002, 7001, 7000])

    def test_FA06_all_close_failures_retained_and_first_memory_selected(self):
        value = self.attempt()
        self.own(value, (0, 1, 2))
        ordinary, first, later = ValueError(), MemoryError(), MemoryError()
        failures = {7002: ordinary, 7001: first, 7000: later}
        seen = []
        def close(fd):
            seen.append(fd)
            raise failures[fd]
        with patch.object(assets.os, 'close', close):
            with self.assertRaises(MemoryError) as raised:
                value.retire()
        self.assertIs(raised.exception, first)
        self.assertIs(value._asset_failure, first)
        self.assertEqual(value._asset_errors[1:4], [later, first, ordinary])
        self.assertEqual(seen, [7002, 7001, 7000])

    def test_FA07_ordinary_body_is_generic_outward_and_private_actual_error_retained(self):
        value, body = self.attempt(), ValueError('private fictional detail')
        error, seen = self.fail_acquire(value, body)
        self.assertIs(type(error), assets.PilotAssetsUnavailable)
        self.assertNotIn('private fictional detail', str(error))
        self.assertIs(value._asset_failure, body)
        self.assertIs(value._asset_errors[0], body)
        self.assertEqual(seen, [7002, 7001, 7000])

    def test_FA08_pending_unknown_handle_is_not_closed_or_declared_settled(self):
        value = self.attempt()
        value._states[2] = 'acquire-pending'
        self.own(value, (0, 1))
        seen = []
        with patch.object(assets.os, 'close', seen.append):
            with self.assertRaises(assets.PilotAssetsClosureUncertain):
                value.retire()
        self.assertEqual(seen, [7001, 7000])
        self.assertEqual(value._states[2], 'acquire-pending')
        self.assertEqual(value._cleanup, 'uncertain')

    def test_FA09_reinitialization_cannot_replace_retained_holders_or_end(self):
        value = self.attempt()
        self.own(value, (0,))
        value._state = 'retained'
        holders = value._fds, value._states, value._identities, value._asset_errors
        with self.assertRaises(assets.PilotAssetsUnavailable):
            value.__init__(200.0)
        self.assertEqual(value._end, 100.0)
        self.assertEqual(value._state, 'retained')
        self.assertTrue(all(a is b for a, b in zip(holders, (value._fds, value._states, value._identities, value._asset_errors))))

    def test_FA10_partial_constructor_failure_spends_initialization_before_thread_holder(self):
        value = object.__new__(assets.FixedPilotAssetAttempt)
        body = MemoryError('fictional thread observation')
        with patch.object(assets.threading, 'current_thread', side_effect=body):
            with self.assertRaises(MemoryError) as raised:
                value.__init__(100.0)
        self.assertIs(raised.exception, body)
        self.assertEqual(value._state, 'constructing')
        errors = value._asset_errors
        with self.assertRaises(assets.PilotAssetsUnavailable):
            value.__init__(200.0)
        self.assertEqual(value._end, 100.0)
        self.assertIs(value._asset_errors, errors)
        self.assertFalse(hasattr(value, '_fds'))

    def test_FA11_foreign_self_refuses_before_attributes_or_thread_observation(self):
        class Foreign:
            def __getattribute__(self, name):
                raise AssertionError('foreign attribute access')
        with patch.object(assets.threading, 'current_thread', side_effect=AssertionError('thread lookup')):
            with self.assertRaises(assets.PilotAssetsUnavailable):
                assets.FixedPilotAssetAttempt.__init__(Foreign(), 100.0)

    def test_FA12_uncertain_retirement_cannot_retry_or_erase_first_error(self):
        value = self.attempt()
        self.own(value, (0,))
        original = MemoryError()
        seen = []
        def close(fd):
            seen.append(fd)
            raise original
        with patch.object(assets.os, 'close', close):
            with self.assertRaises(MemoryError) as raised:
                value.retire()
            with self.assertRaises(assets.PilotAssetsClosureUncertain):
                value.retire()
        self.assertIs(raised.exception, original)
        self.assertIs(value._asset_failure, original)
        self.assertIs(value._asset_errors[1], original)
        self.assertEqual(seen, [7000])

    def test_FA13_ordinary_close_is_private_while_public_closure_stays_generic(self):
        value = self.attempt()
        self.own(value, (0,))
        error = OSError('private fictional error')
        with patch.object(assets.os, 'close', side_effect=error):
            with self.assertRaises(assets.PilotAssetsClosureUncertain) as raised:
                value.retire()
        self.assertIs(value._asset_failure, error)
        self.assertIs(value._asset_errors[1], error)
        self.assertNotIn('private fictional error', str(raised.exception))

    def test_FA14_foreign_thread_refuses_without_cleanup_or_error_replacement(self):
        value = self.attempt()
        self.own(value, (0,))
        seen = []
        with patch.object(assets.threading, 'current_thread', return_value=object()), patch.object(assets.os, 'close', seen.append):
            with self.assertRaises(assets.PilotAssetsUnavailable):
                value.retire()
        self.assertEqual(seen, [])
        self.assertEqual(value._states[0], 'owned')
        self.assertEqual(value._cleanup, 'not-attempted')
        self.assertIsNone(value._asset_failure)
