"""Actual private read/retirement with fictional ports; no credential IO."""
import unittest
from unittest.mock import patch
from test_cluster_read_allocation_data import PrivateReadAllocationData
from freq.services import pilot_cluster_read_attempt as private


class PrivateReadRetentionData(unittest.TestCase):
    def setUp(self):
        self.f = PrivateReadAllocationData('test_PA08_clean_private_bytes_still_return_after_cleanup')
        self.f.setUp()
        self.a = self.f.a

    def test_PR01_all_three_cleanup_failures_remain_after_priority_selection(self):
        body = self.f.acquire_error = OSError('body')
        socket = self.f.socket_close_error = ValueError('socket')
        credential = self.f.credential_close_error = MemoryError('credential')
        trust = self.f.trust_close_error = KeyboardInterrupt('trust')
        with self.assertRaises(KeyboardInterrupt) as caught: self.f.execute()
        self.assertIs(caught.exception, trust)
        self.assertIs(self.a._body_failure, body)
        for actual, expected in zip(self.a._cleanup_failures, (socket, credential, trust)):
            self.assertIs(actual, expected)
        self.assertEqual(self.a._cleanup_states, ['raised'] * 3)
        self.assertIs(self.a._retirement_failure, trust)
        self.assertIs(self.a._failure, trust)
        self.f.closed()

    def test_PR02_repeat_uncertain_retirement_preserves_failure_without_close(self):
        error = self.f.credential_close_error = MemoryError()
        with self.assertRaises(MemoryError): self.f.execute()
        events = list(self.f.events)
        with self.assertRaises(MemoryError) as caught: self.a.retire()
        self.assertIs(caught.exception, error)
        self.assertIs(self.a._cleanup_failures[1], error)
        self.assertEqual(self.f.events, events)

    def test_PR03_clean_returns_are_retained_without_becoming_authority(self):
        returns = [object(), object(), object()]
        self.a._exchange._socket_owner.close = lambda: returns[0]
        self.a._credential.retire = lambda: returns[1]
        self.a._trust.close = lambda: returns[2]
        self.assertEqual(self.f.execute(), b'{"fixture":true}')
        self.assertEqual(self.a._cleanup_states, ['returned'] * 3)
        for actual, expected in zip(self.a._cleanup_returns, returns):
            self.assertIs(actual, expected)
        self.assertEqual(self.a._cleanup_failures, [None] * 3)
        self.assertIsNone(self.a._failure)
        # Existing locally-closed label is only local known-call completion.
        self.assertEqual(self.a._cleanup, 'locally-closed')

    def test_PR04_post_cleanup_clock_failure_is_separately_retained(self):
        error = MemoryError('late clock')
        def now():
            if self.a._state == 'retired': raise error
            return 1.0
        with patch.object(private.time, 'monotonic', now), \
             patch.object(private, 'prepare_private_observation', self.f.parse):
            with self.assertRaises(MemoryError) as caught: self.a.run('a' * 32)
        self.assertIs(caught.exception, error)
        self.assertIs(self.a._finish_failure, error)
        self.assertIs(self.a._failure, error)
        self.assertIsNone(self.a._body_failure)
        self.assertIsNone(self.a._retirement_failure)
        self.f.closed()

    def test_PR05_body_control_and_later_clock_control_are_both_retained(self):
        body = self.f.acquire_error = KeyboardInterrupt('body')
        late = SystemExit('late')
        def now():
            if self.a._state == 'retired': raise late
            return 1.0
        with patch.object(private.time, 'monotonic', now):
            with self.assertRaises(KeyboardInterrupt) as caught: self.a.run('a' * 32)
        self.assertIs(caught.exception, body)
        self.assertIs(self.a._body_failure, body)
        self.assertIs(self.a._finish_failure, late)
        self.assertIs(self.a._failure, body)
        self.f.closed()

    def test_PR06_ordinary_body_remains_retained_when_unavailable_returns(self):
        error = self.f.parse_error = ValueError('parser')
        self.assertIsNone(self.f.execute())
        self.assertIs(self.a._body_failure, error)
        self.assertIs(self.a._failure, error)
        self.assertEqual(self.a._cleanup_states, ['returned'] * 3)

    def test_PR07_pending_unknown_call_refuses_repeat_without_erasing_records(self):
        self.a._cleanup = 'uncertain'
        self.a._cleanup_states[0] = 'pending'
        retained = self.a._cleanup_returns
        with self.assertRaises(private.PilotPrivateReadClosureUncertain): self.a.retire()
        self.assertEqual(self.a._cleanup_states, ['pending', 'unused', 'unused'])
        self.assertIs(self.a._cleanup_returns, retained)
        self.assertEqual(self.f.events, [])

    def test_PR08_clean_retirement_repeat_does_not_repeat_known_closes(self):
        self.f.execute(); events = list(self.f.events)
        self.a.retire()
        self.assertEqual(self.f.events, events)
        self.assertEqual(self.a._cleanup_states, ['returned'] * 3)

    def test_PR09_failed_exchange_and_cleanup_error_keep_distinct_references(self):
        body = self.f.exchange_error = OSError('exchange')
        close = self.f.socket_close_error = ValueError('close')
        self.assertIsNone(self.f.execute())
        self.assertIs(self.a._body_failure, body)
        self.assertIs(self.a._cleanup_failures[0], close)
        self.assertIsInstance(self.a._closure_failure, private.PilotPrivateReadClosureUncertain)
        self.assertIs(self.a._retirement_failure, self.a._closure_failure)
        self.assertIs(self.a._failure, body)
        self.f.closed()

    def test_PR10_busy_exchange_retains_closure_failure_after_known_closes(self):
        self.a._exchange._busy = True
        self.assertIsNone(self.f.execute())
        self.assertIs(self.a._retirement_failure, self.a._closure_failure)
        self.assertEqual(self.a._cleanup_states, ['returned'] * 3)
        self.assertEqual(self.a._cleanup, 'uncertain')
        self.f.closed()

    def test_PR11_repeated_run_preserves_original_failures_and_never_reacquires(self):
        error = self.f.acquire_error = MemoryError()
        with self.assertRaises(MemoryError): self.f.execute()
        events = list(self.f.events)
        with self.assertRaises(private.PilotPrivateReadUnavailable): self.f.execute()
        self.assertIs(self.a._body_failure, error)
        self.assertIs(self.a._failure, error)
        self.assertEqual(self.f.events, events)

    def test_PR12_constructor_creates_independent_empty_records_before_io(self):
        with patch.object(private, 'FixedSystemTrustReader') as trust, \
             patch.object(private, 'OriginalNodeCredentialAttempt') as credential, \
             patch.object(private, 'OriginalClusterExchange') as exchange:
            attempt = private.OriginalPrivateClusterRead(2001, '192.0.2.1', ('fixture@pve', 'configured'), 10.0)
        self.assertEqual(attempt._cleanup_states, ['unused'] * 3)
        self.assertEqual(attempt._cleanup_returns, [None] * 3)
        self.assertEqual(attempt._cleanup_failures, [None] * 3)
        self.assertIsNot(attempt._cleanup_returns, attempt._cleanup_failures)
        self.assertIsNot(attempt._cleanup_states, attempt._cleanup_returns)
        self.assertEqual(trust.return_value.method_calls, [])
        self.assertEqual(credential.return_value.method_calls, [])
        self.assertEqual(exchange.return_value.method_calls, [])
