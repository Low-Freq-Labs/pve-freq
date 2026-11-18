"""Local actual private-read/admission control flow; native ports are fictional."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import contextmanager
from freq.services import pilot_cluster_read_attempt as private
from freq.services import pilot_cluster_read_admission as admission


class PrivateReadAllocationData(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.acquire_error = self.credential_close_error = self.trust_close_error = None
        self.socket_close_error = self.exchange_error = self.parse_error = None
        self.a = private.OriginalPrivateClusterRead.__new__(private.OriginalPrivateClusterRead)
        self.a._thread, self.a._end = threading.current_thread(), 10.0
        self.a._state, self.a._cleanup = 'new', 'not-attempted'
        self.a._recipient, self.a._context, self.a._target = '192.0.2.1', None, object()
        self.a._exchange_started = self.a._exchange_clean_return = False
        self.a._body_failure = self.a._retirement_failure = None
        self.a._finish_failure = self.a._failure = self.a._closure_failure = None
        self.a._cleanup_states = ['unused'] * 3
        self.a._cleanup_returns = [None] * 3
        self.a._cleanup_failures = [None] * 3
        credential = SimpleNamespace(acquire=self.acquire, take_private_wire_components=lambda: ('fixture', 'node', 'not-a-secret'),
                                     _current_data=lambda: None, retire=self.credential_close)
        trust = SimpleNamespace(open_fixed=lambda: None, build_private_context=lambda: None,
                                private_components=lambda: (self.a._recipient, object()),
                                _recheck=lambda: None, close=self.trust_close)
        exchange = SimpleNamespace(run=self.exchange, _busy=False, _retired=False,
                                   _socket_owner=SimpleNamespace(close=self.socket_close))
        self.a._credential, self.a._trust, self.a._exchange = credential, trust, exchange

    def acquire(self):
        self.events.append('acquire')
        if self.acquire_error is not None: raise self.acquire_error
        return self.a._credential

    def exchange(self, *args, **kwargs):
        self.events.append('exchange')
        if self.exchange_error is not None: raise self.exchange_error
        return b'{}'

    def parse(self, *args):
        self.events.append('parse')
        if self.parse_error is not None: raise self.parse_error
        return b'{"fixture":true}'

    def socket_close(self):
        self.events.append('socket-close')
        if self.socket_close_error is not None: raise self.socket_close_error

    def credential_close(self):
        self.events.append('credential-close')
        if self.credential_close_error is not None: raise self.credential_close_error

    def trust_close(self):
        self.events.append('trust-close')
        if self.trust_close_error is not None: raise self.trust_close_error

    def execute(self):
        with patch.object(private.time, 'monotonic', return_value=1.0), \
             patch.object(private, 'prepare_private_observation', self.parse):
            return self.a.run('a' * 32)

    def closed(self):
        self.assertEqual(self.events[-3:], ['socket-close', 'credential-close', 'trust-close'])

    def test_PA01_credential_allocation_propagates_after_every_independent_close(self):
        error = self.acquire_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.execute()
        self.assertIs(caught.exception, error); self.closed()

    def test_PA02_cleanup_allocation_outranks_ordinary_acquisition_failure(self):
        self.acquire_error = OSError()
        error = self.trust_close_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.execute()
        self.assertIs(caught.exception, error); self.closed()

    def test_PA03_parser_allocation_propagates_after_successful_fixed_exchange(self):
        error = self.parse_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.execute()
        self.assertIs(caught.exception, error); self.closed()

    def test_PA04_body_control_remains_first_over_cleanup_allocation(self):
        error = self.acquire_error = KeyboardInterrupt()
        self.credential_close_error = MemoryError()
        with self.assertRaises(KeyboardInterrupt) as caught: self.execute()
        self.assertIs(caught.exception, error); self.closed()

    def test_PA05_cleanup_control_outranks_body_allocation(self):
        self.acquire_error = MemoryError()
        error = self.trust_close_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt) as caught: self.execute()
        self.assertIs(caught.exception, error); self.closed()

    def test_PA06_first_allocation_survives_later_allocation(self):
        error = self.acquire_error = MemoryError('first')
        self.credential_close_error = MemoryError('later')
        with self.assertRaises(MemoryError) as caught: self.execute()
        self.assertIs(caught.exception, error); self.closed()

    def test_PA07_ordinary_failure_still_returns_unavailable_after_cleanup(self):
        self.acquire_error = OSError()
        self.assertIsNone(self.execute()); self.closed()

    def test_PA08_clean_private_bytes_still_return_after_cleanup(self):
        self.assertEqual(self.execute(), b'{"fixture":true}'); self.closed()


class ReadAdmissionAllocationData(unittest.TestCase):
    def setUp(self):
        self.events = []; self.body_error = self.cleanup_error = None
        self.original = admission._OriginalRequest(object(), 10.0, '127.0.0.1')
        self.original.thread = threading.current_thread()
        self.bound = SimpleNamespace(target=SimpleNamespace(endpoint='192.0.2.1'))
        self.nodes, self.token = (), ('fixture', 'name')
        self.attempt = SimpleNamespace(run=self.body)
        self.reader = admission.OriginalClusterReads.__new__(admission.OriginalClusterReads)
        self.reader._auth = object()
        self.reader._references = SimpleNamespace(_valid_reference=lambda key: True, _bindings={'a' * 32: self.bound})
        self.reader._attempts, self.reader._native_attempts = {}, {}
        self.reader._session_locked = lambda *args: None
        self.reader._tables_locked = lambda: None
        self.reader._cohort_locked = lambda: (self.nodes, self.token, 2001)
        self.reader._capture = lambda handler, key: (self.original, None, None, None, self.nodes, self.token, 2001,
                                                     self.bound, 10.0, self.reader._references._bindings)
        self.reader._retire = self.retire
        self.handler = SimpleNamespace(_request_body=lambda: {'binding_ref': 'a' * 32})

    def body(self, key):
        self.events.append('body')
        self.assertIs(self.reader._native_attempts[self.original].attempt, self.attempt)
        self.assertNotIn(key, self.reader._references._bindings)
        if self.body_error is not None: raise self.body_error
        return None

    def retire(self, duty):
        self.events.append('cleanup')
        if self.cleanup_error is not None: raise self.cleanup_error

    def execute(self):
        class Gates:
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch.object(admission, '_ReadGates', Gates), \
             patch.object(admission, 'OriginalPrivateClusterRead', return_value=self.attempt), \
             patch.object(admission.time, 'monotonic', return_value=1.0):
            return self.reader.admit_read(self.handler)

    def test_RA01_body_allocation_propagates_after_cleanup(self):
        error = self.body_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.execute()
        self.assertIs(caught.exception, error); self.assertEqual(self.events, ['body', 'cleanup'])

    def test_RA02_cleanup_allocation_outranks_ordinary_body_refusal(self):
        self.body_error = admission._SelectionRefused(409)
        error = self.cleanup_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.execute()
        self.assertIs(caught.exception, error); self.assertEqual(self.events, ['body', 'cleanup'])

    def test_RA03_body_allocation_is_not_replaced_by_ordinary_cleanup(self):
        error = self.body_error = MemoryError()
        self.cleanup_error = OSError()
        with self.assertRaises(MemoryError) as caught: self.execute()
        self.assertIs(caught.exception, error); self.assertEqual(self.events, ['body', 'cleanup'])

    def test_RA04_first_control_survives_cleanup_allocation(self):
        error = self.body_error = KeyboardInterrupt()
        self.cleanup_error = MemoryError()
        with self.assertRaises(KeyboardInterrupt) as caught: self.execute()
        self.assertIs(caught.exception, error); self.assertEqual(self.events, ['body', 'cleanup'])

    def test_RA05_cleanup_control_outranks_body_allocation(self):
        self.body_error = MemoryError()
        error = self.cleanup_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt) as caught: self.execute()
        self.assertIs(caught.exception, error); self.assertEqual(self.events, ['body', 'cleanup'])
