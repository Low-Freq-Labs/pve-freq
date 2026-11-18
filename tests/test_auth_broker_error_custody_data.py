"""Original broker and inner methods, with fictional admission/resource ports.

The context gates and positive auth-current check are explicit model ports.
The real permanently-False native predicate is tested separately. No native
gate, socket, source, credential, password, process or session is acquired.
"""
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
import builtins
import threading
import unittest
from unittest.mock import Mock, patch

from freq.services import pilot_auth_attempts as broker
from freq.services import pilot_auth_input_attempt as inner
from freq.services import cluster_pilot_http as http
from freq.services.cluster_pilot_startup import OriginalPilotInstallation


RealAttemptGate = broker._AttemptGate


class Control(BaseException):
    pass


class AuthBrokerErrorCustodyData(unittest.TestCase):
    @contextmanager
    def fixture(self, *, body_error=None, members=(('fixture', 'admin'),),
                cleanup_gate_error=None, quarantine_error=None):
        state = {'body_error': body_error}
        attempts, readers, decryptors, retire_calls, gates, assignments = [], [], [], [], [], []
        owner = OriginalPilotInstallation()
        owner._prepare_pending_original()
        server = object.__new__(broker._OriginalPilotServer)
        requests = object.__new__(http._OriginalHTTPRequests)
        server._cluster_pilot_installation, server._pilot_requests = owner, requests
        requests._server, requests._live = server, True  # Fictional live DATA only.
        requests._gate_uncertain, requests._requests = False, {}
        owner._server, owner._source_uid, owner._credential_uid = server, 1003, 1004
        owner._configured_roles, owner._service_user = {'fixture': 'admin'}, 'fixture-service'
        owner._live, owner._admission_uncertain = True, False

        def request():
            socket = object()
            handler = SimpleNamespace(server=server, request=socket)
            original = SimpleNamespace(operation='login', phase='ready', body_taken=True,
                login_username='fixture', auth_attempted=False, socket=socket,
                handler=handler, thread=threading.current_thread(), end=30.0)
            requests._requests[socket] = original
            return handler, original

        handler, original = request()
        component = broker.OriginalPilotAuthAttempts(owner)

        def make_reader(*args):
            reader = SimpleNamespace(open_fixed=Mock(),
                read_inputs=Mock(return_value=(b'fictional-config', b'fictional-users',
                    b'fictional-roles', b'fictional-cipher', b'fictional-machine'),
                    side_effect=state['body_error']), _recheck=Mock(), close=Mock(),
                cleanup_observations=Mock(return_value=('fictional-reader-only',)))
            readers.append(reader)
            return reader

        def make_decrypt():
            value = SimpleNamespace(run=Mock(return_value=b'fictional-plaintext'),
                cleanup_observations=Mock(return_value=(
                    'unused', 'unused', ('unused', 'unused'),
                    ('unused', 'unused', 'unused'), 'unused', 'unused', 'unused')))
            decryptors.append(value)
            return value

        init = inner.OriginalAuthInputAttempt.__init__
        retire = inner.OriginalAuthInputAttempt.retire

        def record_init(attempt, *args):
            init(attempt, *args)
            attempts.append(attempt)

        def record_retire(attempt):
            retire_calls.append(attempt)
            return retire(attempt)

        class FictionalGate:
            def __init__(self, unused_component, unused_original=None, cleanup=False):
                self.cleanup = cleanup

            def __enter__(self):
                gates.append(self.cleanup)
                if self.cleanup and cleanup_gate_error is not None:
                    raise cleanup_gate_error
                return self

            def __exit__(self, *args):
                return False

        def assignment(target, field, value):
            assignments.append((target is owner, field))
            if target is owner and field == '_live' and quarantine_error is not None:
                raise quarantine_error
            builtins.setattr(target, field, value)

        with ExitStack() as stack:
            stack.enter_context(patch.object(inner, 'FixedOriginalAuthReader', side_effect=make_reader))
            stack.enter_context(patch.object(inner, 'OriginalVaultDecrypt', side_effect=make_decrypt))
            stack.enter_context(patch.object(inner, 'decode_retained_original_inputs',
                return_value=((), members, 'fixture-service', None)))
            stack.enter_context(patch.object(inner, 'exact_original_auth_hash', return_value='fictional-hash'))
            stack.enter_context(patch.object(inner.time, 'monotonic', return_value=1.0))
            stack.enter_context(patch.object(inner.OriginalAuthInputAttempt, '__init__', record_init))
            stack.enter_context(patch.object(inner.OriginalAuthInputAttempt, 'retire', record_retire))
            owned = stack.enter_context(patch.object(http._OriginalHTTPRequests, '_owned', return_value=original))
            stack.enter_context(patch.object(broker, '_AttemptGate', FictionalGate))
            stack.enter_context(patch.object(broker.OriginalPilotAuthAttempts, 'auth_current', return_value=True))
            stack.enter_context(patch.object(broker, 'setattr', assignment, create=True))
            yield SimpleNamespace(owner=owner, server=server, requests=requests,
                original=original, handler=handler, component=component, attempts=attempts,
                readers=readers, decryptors=decryptors, retire_calls=retire_calls,
                gates=gates, assignments=assignments, state=state, request=request, owned=owned)

    def test_AB01_success_retains_then_retires_same_attempt_once(self):
        with self.fixture() as f:
            attempt = f.component.begin_auth(f.handler, 'fixture')
            self.assertIs(attempt, f.attempts[0])
            self.assertIs(f.owner._auth_attempts[attempt], f.original)
            self.assertEqual(attempt._request_errors, [None] * 3)
            self.assertIsNone(attempt._request_failure)
            f.component.retire_auth(attempt)
            self.assertNotIn(attempt, f.owner._auth_attempts)
            self.assertIs(attempt._request_retirement_started, True)
            self.assertEqual(f.retire_calls, [attempt])
            f.readers[0].close.assert_called_once_with()
            self.assertFalse(f.owner._native_current_locked(f.original))

    def test_AB02_inner_body_memory_reaches_original_broker_by_identity(self):
        error = MemoryError()
        with self.fixture(body_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                f.component.begin_auth(f.handler, 'fixture')
            attempt = f.attempts[0]
            self.assertIs(caught.exception, error)
            self.assertIs(attempt._input_errors[0], error)
            self.assertIs(attempt._request_errors[0], error)
            self.assertIs(attempt._request_failure, error)
            self.assertNotIn(attempt, f.owner._auth_attempts)
            f.readers[0].close.assert_called_once_with()

    def test_AB03_cleanup_memory_preserves_actual_inner_ordinary_body(self):
        body, cleanup = ValueError('fictional private body'), MemoryError()
        with self.fixture(body_error=body) as f:
            # Reader exists only after begin construction; inject close fault
            # immediately before its actual inner acquire through a fixed port.
            acquire = inner.OriginalAuthInputAttempt.acquire
            def run(attempt, username):
                attempt._reader.close.side_effect = cleanup
                return acquire(attempt, username)
            with patch.object(inner.OriginalAuthInputAttempt, 'acquire', run):
                with self.assertRaises(MemoryError) as caught:
                    f.component.begin_auth(f.handler, 'fixture')
            attempt = f.attempts[0]
            self.assertIs(caught.exception, cleanup)
            self.assertIs(attempt._input_errors[0], body)
            self.assertIs(attempt._input_errors[1], cleanup)
            self.assertIs(attempt._request_failure, cleanup)
            self.assertIn(attempt, f.owner._auth_attempts)
            self.assertTrue(f.owner._admission_uncertain)
            f.readers[0].close.assert_called_once_with()

    def test_AB04_first_cleanup_control_survives_original_broker(self):
        body, first, later = MemoryError(), Control(), Control()
        with self.fixture(body_error=body) as f:
            acquire = inner.OriginalAuthInputAttempt.acquire
            def run(attempt, username):
                attempt._reader.close.side_effect = first
                attempt._decrypt.cleanup_observations.side_effect = later
                return acquire(attempt, username)
            with patch.object(inner.OriginalAuthInputAttempt, 'acquire', run):
                with self.assertRaises(Control) as caught:
                    f.component.begin_auth(f.handler, 'fixture')
            attempt = f.attempts[0]
            self.assertIs(caught.exception, first)
            self.assertIs(attempt._input_errors[0], body)
            self.assertIs(attempt._input_errors[2], later)
            self.assertIs(attempt._request_failure, first)
            f.readers[0].close.assert_called_once_with()

    def test_AB05_body_control_is_not_replaced_by_cleanup_memory(self):
        body, cleanup = Control(), MemoryError()
        with self.fixture(body_error=body) as f:
            acquire = inner.OriginalAuthInputAttempt.acquire
            def run(attempt, username):
                attempt._reader.close.side_effect = cleanup
                return acquire(attempt, username)
            with patch.object(inner.OriginalAuthInputAttempt, 'acquire', run):
                with self.assertRaises(Control) as caught:
                    f.component.begin_auth(f.handler, 'fixture')
            self.assertIs(caught.exception, body)
            self.assertIs(f.attempts[0]._request_failure, body)
            f.readers[0].close.assert_called_once_with()

    def test_AB06_ordinary_public_refusal_keeps_actual_inner_error_private(self):
        body = OSError('fictional private diagnostic')
        with self.fixture(body_error=body) as f:
            with self.assertRaises(broker._RequestUnavailable) as caught:
                f.component.begin_auth(f.handler, 'fixture')
            self.assertEqual(str(caught.exception), '')
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertIs(f.attempts[0]._input_errors[0], body)
            self.assertIsInstance(f.attempts[0]._request_errors[0], inner.PilotAuthInputUnavailable)
            f.readers[0].close.assert_called_once_with()

    def test_AB07_acquired_none_cleanup_gate_memory_does_not_retry_retirement(self):
        error = MemoryError()
        with self.fixture(members=(), cleanup_gate_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                f.component.begin_auth(f.handler, 'fixture')
            attempt = f.attempts[0]
            self.assertIs(caught.exception, error)
            self.assertIs(attempt._request_errors[1], error)
            self.assertIs(attempt._request_failure, error)
            self.assertIs(attempt._request_retirement_started, True)
            self.assertEqual(f.gates.count(True), 1)
            # One inner finally-retire plus one original broker retirement;
            # no second original broker cleanup after its gate fails.
            self.assertEqual(f.retire_calls, [attempt, attempt])
            self.assertIn(attempt, f.owner._auth_attempts)
            f.readers[0].close.assert_called_once_with()

    def test_AB08_direct_retire_memory_keeps_entry_and_repeat_performs_no_work(self):
        error = MemoryError()
        with self.fixture() as f:
            attempt = f.component.begin_auth(f.handler, 'fixture')
            f.readers[0].close.side_effect = error
            with self.assertRaises(MemoryError) as caught:
                f.component.retire_auth(attempt)
            self.assertIs(caught.exception, error)
            errors = attempt._request_errors
            with self.assertRaises(broker._RequestUnavailable):
                f.component.retire_auth(attempt)
            self.assertIs(attempt._request_errors, errors)
            self.assertIs(errors[1], error)
            self.assertIs(attempt._request_failure, error)
            self.assertEqual(f.retire_calls, [attempt])
            self.assertIn(attempt, f.owner._auth_attempts)
            self.assertFalse(f.owner._live)
            self.assertFalse(f.requests._live)
            f.readers[0].close.assert_called_once_with()

    def test_AB09_quarantine_control_outranks_retire_ordinary_with_actual_retained(self):
        body, control = OSError(), Control()
        with self.fixture(quarantine_error=control) as f:
            attempt = f.component.begin_auth(f.handler, 'fixture')
            f.readers[0].close.side_effect = body
            with self.assertRaises(Control) as caught:
                f.component.retire_auth(attempt)
            self.assertIs(caught.exception, control)
            self.assertIs(attempt._request_errors[1], body)
            self.assertIs(attempt._request_failure, control)
            self.assertEqual(f.assignments, [(True, '_admission_uncertain'),
                (True, '_live'), (False, '_live')])
            self.assertFalse(f.requests._live)
            self.assertTrue(f.owner._admission_uncertain)

    def test_AB10_request_failure_storage_is_separate_within_same_component(self):
        error = MemoryError()
        with self.fixture() as f:
            first = f.component.begin_auth(f.handler, 'fixture')
            handler, original = f.request()
            f.owned.return_value = original
            f.state['body_error'] = error
            with self.assertRaises(MemoryError):
                f.component.begin_auth(handler, 'fixture')
            second = f.attempts[1]
            self.assertIsNot(first._request_errors, second._request_errors)
            self.assertEqual(first._request_errors, [None] * 3)
            self.assertIsNone(first._request_failure)
            self.assertIs(second._request_failure, error)
            self.assertIs(f.owner._auth_attempts[first], f.original)
            self.assertNotIn(second, f.owner._auth_attempts)
            f.component.retire_auth(first)

    def test_AB11_real_gate_release_priority_preserves_body_control(self):
        body, cleanup = Control(), MemoryError()
        with self.fixture() as f:
            release = Mock(side_effect=cleanup)
            f.owner._gate = SimpleNamespace(release=release)
            gate = RealAttemptGate(f.component, f.original)
            gate._state = 'owned'  # Explicit fictional prior acquisition.
            self.assertIs(gate._release(body), body)
            release.assert_called_once_with()
            self.assertEqual(gate._state, 'uncertain')
            self.assertTrue(f.owner._admission_uncertain)
            self.assertFalse(f.requests._live)

    def test_AB12_real_native_false_refuses_positive_currentness_in_model(self):
        with self.fixture() as f:
            with self.assertRaises(broker._RequestUnavailable):
                f.component._current_locked(f.original)
            self.assertFalse(f.owner._native_current_locked(f.original))
            self.assertEqual(f.attempts, [])
            self.assertEqual(f.readers, [])
