"""UNRUN fictional patched-reader failure priority, no credential/native IO."""
import contextlib
import unittest
from unittest.mock import patch

from freq.services import pilot_node_credential_attempt as source


class NodeCredentialFailureData(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.open_error = self.read_error = self.close_error = None
        self.opens = self.reads = self.closes = 0
        self.attempt = None
        fixture = self

        class FictionalReader:
            def __init__(inner, uid, endpoint, end):
                fixture.assertEqual((uid, endpoint, end), (2001, '192.0.2.1', 115.0))
                inner.node_token_name = 'fixture-node-token'
            def open_fixed(inner):
                fixture.opens += 1
                fixture.events.append('open')
                if fixture.open_error is not None: raise fixture.open_error
            def read_private_secret(inner):
                fixture.reads += 1
                fixture.events.append('read')
                if fixture.read_error is not None: raise fixture.read_error
                return b'12345678-1234-1234-1234-123456789abc'
            def _recheck(inner):
                fixture.events.append('recheck')
            def close(inner):
                fixture.closes += 1
                fixture.events.append('close')
                if fixture.close_error is not None: raise fixture.close_error

        self.Reader = FictionalReader

    @contextlib.contextmanager
    def fictional_effects(self, *, clock=None):
        with patch.object(source, 'FixedNodeTokenReader', self.Reader), \
                patch.object(source.time, 'monotonic', clock or (lambda: 113.0)):
            self.attempt = source.OriginalNodeCredentialAttempt(2001, '192.0.2.1',
                ('fixture@pam', 'fixture-configured-name'), 115.0)
            yield

    def assert_no_acquire_retry(self):
        before = (self.opens, self.reads, self.closes)
        with self.assertRaises(source.PilotCredentialUnavailable): self.attempt.acquire()
        self.assertEqual((self.opens, self.reads, self.closes), before)

    def test_NC01_read_allocation_failure_propagates_after_known_local_retirement(self):
        self.read_error = MemoryError('fictional read allocation')
        with self.fictional_effects():
            with self.assertRaises(MemoryError) as raised: self.attempt.acquire()
            self.assertIs(raised.exception, self.read_error)
            self.assertIs(self.attempt._body_failure, self.read_error)
            self.assertIs(self.attempt._failure, self.read_error)
            self.assertIsNone(self.attempt._cleanup_failure)
            self.assertEqual(self.closes, 1)
            self.assert_no_acquire_retry()

    def test_NC02_body_allocation_survives_ordinary_cleanup_error_with_both_retained(self):
        self.open_error = MemoryError('fictional open allocation')
        self.close_error = OSError('fictional close')
        with self.fictional_effects():
            with self.assertRaises(MemoryError) as raised: self.attempt.acquire()
            self.assertIs(raised.exception, self.open_error)
            self.assertIs(self.attempt._body_failure, self.open_error)
            self.assertIs(self.attempt._cleanup_failure, self.close_error)
            self.assertEqual(self.attempt._cleanup, 'uncertain')
            self.assertEqual(self.closes, 1)
            with self.assertRaises(source.PilotCredentialClosureUncertain): self.attempt.retire()
            self.assertEqual(self.closes, 1)

    def test_NC03_cleanup_allocation_overrides_ordinary_body_without_losing_body_reference(self):
        self.open_error = OSError('fictional open')
        self.close_error = MemoryError('fictional cleanup allocation')
        with self.fictional_effects():
            with self.assertRaises(MemoryError) as raised: self.attempt.acquire()
            self.assertIs(raised.exception, self.close_error)
            self.assertIs(self.attempt._body_failure, self.open_error)
            self.assertIs(self.attempt._cleanup_failure, self.close_error)
            self.assertIs(self.attempt._failure, self.close_error)
            self.assertEqual(self.closes, 1)

    def test_NC04_first_genuine_control_preserved_while_second_control_also_retained(self):
        self.open_error = KeyboardInterrupt('fictional first control')
        self.close_error = SystemExit('fictional later control')
        with self.fictional_effects():
            with self.assertRaises(KeyboardInterrupt) as raised: self.attempt.acquire()
            self.assertIs(raised.exception, self.open_error)
            self.assertIs(self.attempt._body_failure, self.open_error)
            self.assertIs(self.attempt._cleanup_failure, self.close_error)
            self.assertEqual(self.closes, 1)

    def test_NC05_cleanup_control_supersedes_allocation_but_retains_original_allocation(self):
        self.read_error = MemoryError('fictional first allocation')
        self.close_error = KeyboardInterrupt('fictional cleanup control')
        with self.fictional_effects():
            with self.assertRaises(KeyboardInterrupt) as raised: self.attempt.acquire()
            self.assertIs(raised.exception, self.close_error)
            self.assertIs(self.attempt._failure, self.close_error)
            self.assertIs(self.attempt._body_failure, self.read_error)
            self.assertIs(self.attempt._cleanup_failure, self.close_error)

    def test_NC06_ordinary_refusal_allocated_only_after_cleanup_and_retains_first_failure(self):
        self.open_error = OSError('fictional body')
        self.close_error = OSError('fictional cleanup')
        fixture = self
        class FictionalUnavailable(Exception):
            def __init__(inner):
                fixture.events.append('refusal-constructed')
        with self.fictional_effects(), patch.object(source, 'PilotCredentialUnavailable', FictionalUnavailable):
            with self.assertRaises(FictionalUnavailable): self.attempt.acquire()
            self.assertEqual(self.events, ['open', 'close', 'refusal-constructed'])
            self.assertIs(self.attempt._failure, self.open_error)
            self.assertIs(self.attempt._body_failure, self.open_error)
            self.assertIs(self.attempt._cleanup_failure, self.close_error)

    def test_NC07_ordinary_body_known_cleanup_stays_unavailable_without_any_fallback_or_retry(self):
        self.open_error = OSError('fictional missing')
        with self.fictional_effects():
            with self.assertRaises(source.PilotCredentialUnavailable): self.attempt.acquire()
            self.assertIs(self.attempt._body_failure, self.open_error)
            self.assertIsNone(self.attempt._cleanup_failure)
            self.assertEqual((self.opens, self.reads, self.closes), (1, 0, 1))
            self.assertEqual(self.attempt._end, 115.0)
            self.assert_no_acquire_retry()

    def test_NC08_late_clock_allocation_after_private_decode_does_not_skip_retirement(self):
        failure = MemoryError('fictional late private clock')
        def clock():
            if self.attempt is not None and self.attempt._secret is not None:
                raise failure
            return 113.0
        with self.fictional_effects(clock=clock):
            with self.assertRaises(MemoryError) as raised: self.attempt.acquire()
            self.assertIs(raised.exception, failure)
            self.assertIs(self.attempt._body_failure, failure)
            self.assertEqual(self.closes, 1)
            self.assertEqual(self.attempt._cleanup, 'locally-closed')
            self.assertIsNone(self.attempt._secret)  # No physical erasure claim.

    def test_NC09_body_control_survives_cleanup_allocation_and_both_are_private(self):
        self.open_error = KeyboardInterrupt('fictional body control')
        self.close_error = MemoryError('fictional cleanup allocation')
        with self.fictional_effects():
            with self.assertRaises(KeyboardInterrupt) as raised: self.attempt.acquire()
            self.assertIs(raised.exception, self.open_error)
            self.assertIs(self.attempt._body_failure, self.open_error)
            self.assertIs(self.attempt._cleanup_failure, self.close_error)

    def test_NC10_successful_private_transfer_once_keeps_end_and_does_not_invent_failure(self):
        with self.fictional_effects():
            self.assertIs(self.attempt.acquire(), self.attempt)
            private = self.attempt.take_private_wire_components()
            self.assertEqual(private, ('fixture@pam', 'fixture-node-token',
                                      '12345678-1234-1234-1234-123456789abc'))
            with self.assertRaises(source.PilotCredentialUnavailable):
                self.attempt.take_private_wire_components()
            self.assertEqual(self.closes, 0)
            self.assertEqual(self.attempt._end, 115.0)
            self.assertIsNone(self.attempt._failure)
            self.assertIsNone(self.attempt._body_failure)
            self.assertIsNone(self.attempt._cleanup_failure)
            self.attempt.retire()
            self.attempt.retire()
            self.assertEqual(self.closes, 1)
            # Private scalar tuple stays caller-retained; no real secret/erasure.
