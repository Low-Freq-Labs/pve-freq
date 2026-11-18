"""Actual original static caller/asset methods with explicit fictional ports."""
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from freq.services import pilot_static_response as static
from freq.services import pilot_fixed_assets as assets
from freq.services import cluster_pilot_http as http
from freq.services.cluster_pilot_startup import OriginalPilotInstallation


RealGates = static._StaticGates


class Control(BaseException):
    pass


class StaticResponseErrorCustodyData(unittest.TestCase):
    @contextmanager
    def fixture(self, *, body_error=None, close_error=None, send_error=None, delete_error=None):
        owner = OriginalPilotInstallation()
        owner._prepare_pending_original()
        server = object.__new__(http._OriginalPilotServer)
        broker = object.__new__(http._OriginalHTTPRequests)
        server._cluster_pilot_installation, server._pilot_requests = owner, broker
        broker._server, broker._live, broker._gate_uncertain = server, True, False
        broker._requests = {}
        owner._server, owner._live, owner._admission_uncertain = server, True, False
        records, closes, sends, gates = [], [], [], []
        owner._asset_attempts = {}
        socket = object()
        handler = SimpleNamespace(server=server, request=socket)
        original = SimpleNamespace(socket=socket, end=100.0, handler=handler,
            thread=threading.current_thread(), phase='ready', asset='app.html',
            operation='app', asset_attempted=False, frame=None)
        broker._requests[socket] = original
        component = static.OriginalPilotStatic(owner)
        owner._static_responder = component
        init_record = static._AssetRecord.__init__
        def record_init(record, *args):
            init_record(record, *args)
            records.append(record)
        def opened(attempt):
            for i in (0, 1, 2):
                attempt._fds[i] = 8000 + i
                attempt._states[i] = 'owned'
            if body_error is not None:
                raise body_error
        def close(fd):
            closes.append(fd)
            if fd == 8001 and close_error is not None:
                raise close_error
        def admit(unused_broker, unused_handler, same, frame):
            self.assertIs(same, original)
            original.phase, original.frame = 'admitted', frame
        def reserve(unused_broker, unused_handler, same, frame):
            self.assertIs(same, original)
            self.assertIs(frame, original.frame)
        def send(unused_broker, unused_handler, frame):
            sends.append(frame)
            if send_error is not None:
                raise send_error
        class Gates:
            def __init__(self, unused, same, phase='ready', cleanup=False):
                self.cleanup = cleanup
                self.phase = phase
            def __enter__(self):
                gates.append((self.phase, self.cleanup))
                if self.cleanup and delete_error is not None:
                    raise delete_error  # Explicit original logical-forget gate port.
                return self
            def __exit__(self, *args):
                return False
        with ExitStack() as stack:
            stack.enter_context(patch.object(static, '_StaticGates', Gates))
            stack.enter_context(patch.object(static._AssetRecord, '__init__', record_init))
            stack.enter_context(patch.object(http._OriginalHTTPRequests, '_owned', return_value=original))
            stack.enter_context(patch.object(http._OriginalHTTPRequests, '_admit_frame_locked', admit))
            stack.enter_context(patch.object(http._OriginalHTTPRequests, '_reserve_write_locked', reserve))
            stack.enter_context(patch.object(http._OriginalHTTPRequests, '_send_reserved', send))
            stack.enter_context(patch.object(assets.FixedPilotAssetAttempt, '_open_all', opened))
            stack.enter_context(patch.object(assets.FixedPilotAssetAttempt, '_recheck', lambda value: None))
            stack.enter_context(patch.object(assets.FixedPilotAssetAttempt, '_read_file', lambda value, i: b'fictional body'))
            stack.enter_context(patch.object(assets.os, 'close', close))
            stack.enter_context(patch.object(assets.time, 'monotonic', return_value=1.0))
            yield SimpleNamespace(owner=owner, broker=broker, component=component,
                original=original, handler=handler, records=records, closes=closes,
                sends=sends, gates=gates)

    def test_SC01_success_keeps_original_frame_and_sends_once_after_known_close(self):
        with self.fixture() as f:
            self.assertIsNone(f.component.serve(f.handler))
            record = f.records[0]
            self.assertEqual(f.closes, [8002, 8001, 8000])
            self.assertEqual(f.sends, [record.frame])
            self.assertIs(f.original.frame, record.frame)
            self.assertTrue(f.original.asset_attempted)
            self.assertEqual(record.errors, [None] * 3)
            self.assertIsNone(record.failure)
            self.assertEqual(f.owner._asset_attempts, {})
            self.assertFalse(f.owner._native_current_locked(f.original))

    def test_SC02_inner_asset_body_memory_reaches_original_static_caller(self):
        body = MemoryError()
        with self.fixture(body_error=body) as f:
            with self.assertRaises(MemoryError) as caught:
                f.component.serve(f.handler)
            record = f.records[0]
            self.assertIs(caught.exception, body)
            self.assertIs(record.attempt._asset_failure, body)
            self.assertIs(record.errors[0], body)
            self.assertIs(record.failure, body)
            self.assertEqual(f.closes, [8002, 8001, 8000])
            self.assertEqual(f.sends, [])
            self.assertEqual(f.owner._asset_attempts, {})

    def test_SC03_close_memory_outranks_ordinary_inner_body_and_retains_record(self):
        body, close = ValueError(), MemoryError()
        with self.fixture(body_error=body, close_error=close) as f:
            with self.assertRaises(MemoryError) as caught:
                f.component.serve(f.handler)
            record = f.records[0]
            self.assertIs(caught.exception, close)
            self.assertIs(record.attempt._asset_errors[0], body)
            self.assertIs(record.attempt._asset_errors[2], close)
            self.assertIs(record.failure, close)
            self.assertIn(record.attempt, f.owner._asset_attempts)
            self.assertTrue(f.owner._admission_uncertain)
            self.assertEqual(f.closes, [8002, 8001, 8000])

    def test_SC04_send_memory_is_same_after_settled_logical_forget(self):
        error = MemoryError()
        with self.fixture(send_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                f.component.serve(f.handler)
            record = f.records[0]
            self.assertIs(caught.exception, error)
            self.assertIs(record.errors[0], error)
            self.assertIs(record.failure, error)
            self.assertEqual(f.owner._asset_attempts, {})
            self.assertEqual(len(f.sends), 1)

    def test_SC05_later_close_observation_memory_outranks_ordinary_body(self):
        body, cleanup = ValueError(), MemoryError()
        close = static.OriginalPilotStatic._close_attempt
        calls = []
        def observed(component, attempt):
            calls.append(attempt)
            if len(calls) == 2:
                raise cleanup  # Explicit completion-observation port.
            return close(component, attempt)
        with self.fixture(send_error=body) as f, patch.object(static.OriginalPilotStatic, '_close_attempt', observed):
            with self.assertRaises(MemoryError) as caught:
                f.component.serve(f.handler)
            record = f.records[0]
            self.assertIs(caught.exception, cleanup)
            self.assertIs(record.errors[0], body)
            self.assertIs(record.errors[1], cleanup)
            self.assertIs(record.failure, cleanup)
            self.assertEqual(f.closes, [8002, 8001, 8000])

    def test_SC06_body_control_stays_first_through_forget_control(self):
        body, later = Control(), Control()
        with self.fixture(send_error=body, delete_error=later) as f:
            with self.assertRaises(Control) as caught:
                f.component.serve(f.handler)
            record = f.records[0]
            self.assertIs(caught.exception, body)
            self.assertIs(record.errors[0], body)
            self.assertIs(record.errors[2], later)
            self.assertIs(record.failure, body)
            self.assertIn(record.attempt, f.owner._asset_attempts)

    def test_SC07_forget_memory_keeps_actual_error_and_uncertain_original_table(self):
        cleanup = MemoryError()
        with self.fixture(delete_error=cleanup) as f:
            with self.assertRaises(MemoryError) as caught:
                f.component.serve(f.handler)
            record = f.records[0]
            self.assertIs(caught.exception, cleanup)
            self.assertIs(record.errors[2], cleanup)
            self.assertIs(record.failure, cleanup)
            self.assertIn(record.attempt, f.owner._asset_attempts)
            self.assertFalse(f.owner._live)

    def test_SC08_ordinary_send_failure_remains_public_generic_and_private_actual(self):
        body = ValueError('fictional private reason')
        with self.fixture(send_error=body) as f:
            with self.assertRaises(http._RequestUnavailable) as caught:
                f.component.serve(f.handler)
            self.assertIs(f.records[0].errors[0], body)
            self.assertIs(f.records[0].failure, body)
            self.assertNotIn('fictional private reason', str(caught.exception))
            self.assertEqual(f.owner._asset_attempts, {})

    def test_SC09_real_gate_release_helper_prioritizes_memory_with_fake_lock(self):
        first, memory = ValueError(), MemoryError()
        gate = object.__new__(RealGates)
        with self.fixture() as f:
            gate._component = f.component
            gate._locks = (SimpleNamespace(release=lambda: (_ for _ in ()).throw(memory)),)
            gate._states = ['owned']
            self.assertIs(gate._release(first), memory)
            self.assertEqual(gate._states, ['uncertain'])
            self.assertTrue(f.owner._admission_uncertain)

    def test_SC10_distinct_original_calls_use_distinct_error_storage(self):
        body = ValueError()
        with self.fixture(send_error=body) as f:
            for unused in range(2):
                f.original.phase, f.original.asset_attempted, f.original.frame = 'ready', False, None
                with self.assertRaises(http._RequestUnavailable):
                    f.component.serve(f.handler)
            self.assertIsNot(f.records[0].errors, f.records[1].errors)
            self.assertIs(f.records[0].failure, body)
            self.assertIs(f.records[1].failure, body)
            self.assertEqual(len(f.closes), 6)

    def test_SC11_real_native_false_predicate_refuses_currentness(self):
        with self.fixture() as f:
            with self.assertRaises(http._RequestUnavailable):
                f.component._current_locked(f.original, 'ready')
            self.assertEqual(f.closes, [])
            self.assertEqual(f.sends, [])
            self.assertFalse(f.owner._native_current_locked(f.original))

    def test_SC12_capacity_refusal_never_acquires_or_closes_unretained_attempt(self):
        with self.fixture() as f:
            f.owner._asset_attempts.update({object(): object() for unused in range(64)})
            with self.assertRaises(http._RequestUnavailable):
                f.component.serve(f.handler)
            self.assertEqual(len(f.owner._asset_attempts), 64)
            self.assertEqual(f.closes, [])
            self.assertEqual(f.sends, [])
            self.assertFalse(f.original.asset_attempted)
            self.assertEqual(f.records[0].attempt._state, 'new')
