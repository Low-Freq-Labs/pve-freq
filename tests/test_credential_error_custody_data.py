"""Real cleanup/caller methods over explicit fictional FD/TLS/socket ports.

No OS descriptor, native socket, SSL context, CA or credential is acquired.
The fixed error objects and handle numbers below are test DATA only.
"""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services import pilot_fixed_trust_reader as trust
from freq.services import cluster_observation_exchange as wire
from freq.services import pilot_cluster_read_attempt as caller


class Control(BaseException):
    pass


class HandleData:
    def __init__(self, failure=None):
        self.failure, self.calls = failure, 0

    def close(self):
        self.calls += 1
        if self.failure is not None:
            raise self.failure


class CredentialErrorCustodyData(unittest.TestCase):
    @contextmanager
    def trust_fixture(self, failures=None, unknown=None):
        reader = trust.FixedSystemTrustReader('192.0.2.7', 110.0)
        reader._fds = [101, 102, 103, 104, 105]
        reader._states = ['owned'] * 5
        reader._context_state = 'prepared'
        if unknown is not None:
            reader._states[unknown] = 'acquire-pending'
            reader._fds[unknown] = None
        calls, faults = [], failures or {}
        def close(fd):
            calls.append(fd)
            index = fd - 101
            if index in faults:
                raise faults[index]
        with patch.object(trust, 'os', SimpleNamespace(close=close)):
            yield SimpleNamespace(reader=reader, calls=calls, faults=faults)

    @contextmanager
    def exchange_fixture(self, *, fault_phase=None, body_error=None,
                         close_error=None, clock_error=None):
        exchange = wire.OriginalClusterExchange()
        owner = exchange._socket_owner
        handle = HandleData(close_error)
        owner._socket, owner._acquisition = handle, 'owned'
        events, clock_calls = [], []
        class CollectorData:
            def __init__(self):
                self.remaining = 1
            def next_read_size(self):
                return self.remaining
            def feed(self, piece):
                events.append('feed')
                self.remaining = 0
            def finish(self):
                events.append('finish')
                if fault_phase == 'finish':
                    raise body_error
                return b'{"data":[]}'
        class PumpData:
            def connect(self):
                events.append('connect')
            def write_request(self, data):
                events.append('write')
            def read(self, maximum):
                events.append('read')
                if fault_phase == 'read':
                    raise body_error
                return b'x'
        def serialize(*unused):
            events.append('serialize')
            if fault_phase == 'serialize':
                raise body_error
            return b'fictional-request-data'
        def pump(*unused):
            events.append('pump')
            if fault_phase == 'pump':
                raise body_error
            return PumpData()
        def clock():
            clock_calls.append(len(clock_calls) + 1)
            # A final clock follows either one start clock after a body
            # failure, or start+postbody clocks after a completed body.
            if clock_error is not None and (
                    fault_phase is not None and len(clock_calls) == 2 or
                    fault_phase is None and len(clock_calls) == 3):
                raise clock_error
            return 100.0
        target = wire.WireTarget('192.0.2.7', '192.0.2.7', 'fixture')
        with patch.object(wire, 'serialize_request', serialize), \
                patch.object(wire, 'ResponseCollector', CollectorData), \
                patch.object(wire, 'TLSPump', pump), \
                patch.object(wire, 'time', SimpleNamespace(monotonic=clock)):
            yield SimpleNamespace(exchange=exchange, owner=owner, handle=handle,
                target=target, events=events, clock_calls=clock_calls)

    def run_exchange(self, f):
        return f.exchange.run(f.target, ('fictional',), object(), original_deadline=110.0)

    def test_CT01_all_known_fds_close_in_reverse_once(self):
        with self.trust_fixture() as f:
            f.reader.close()
            self.assertEqual(f.calls, [105, 104, 103, 102, 101])
            self.assertEqual(f.reader._states, ['closed'] * 5)
            self.assertEqual(f.reader._context_state, 'retirement-only')
            f.reader.close()
            self.assertEqual(len(f.calls), 5)

    def test_CT02_actual_memory_is_retained_and_repeated_close_never_retries(self):
        error = MemoryError()
        with self.trust_fixture({4: error}) as f:
            for unused in range(2):
                with self.assertRaises(MemoryError) as caught:
                    f.reader.close()
                self.assertIs(caught.exception, error)
            self.assertIs(f.reader._close_errors[4], error)
            self.assertIs(f.reader._close_failure, error)
            self.assertEqual(len(f.calls), 5)
            self.assertEqual(f.reader._states, ['closed'] * 4 + ['uncertain'])

    def test_CT03_later_memory_outranks_first_ordinary_without_losing_either(self):
        ordinary, allocation = OSError('fictional-private-detail'), MemoryError()
        with self.trust_fixture({4: ordinary, 2: allocation}) as f:
            with self.assertRaises(MemoryError) as caught:
                f.reader.close()
            self.assertIs(caught.exception, allocation)
            self.assertIs(f.reader._close_errors[4], ordinary)
            self.assertIs(f.reader._close_errors[2], allocation)
            self.assertEqual(len(f.calls), 5)

    def test_CT04_first_memory_identity_survives_later_memory(self):
        first, later = MemoryError(), MemoryError()
        with self.trust_fixture({4: first, 0: later}) as f:
            with self.assertRaises(MemoryError) as caught:
                f.reader.close()
            self.assertIs(caught.exception, first)
            self.assertIs(f.reader._close_errors[0], later)
            self.assertEqual(len(f.calls), 5)

    def test_CT05_first_control_outranks_memory_and_later_control(self):
        allocation, first, later = MemoryError(), Control(), Control()
        with self.trust_fixture({4: allocation, 3: first, 0: later}) as f:
            with self.assertRaises(Control) as caught:
                f.reader.close()
            self.assertIs(caught.exception, first)
            self.assertIs(f.reader._close_errors[4], allocation)
            self.assertIs(f.reader._close_errors[0], later)
            self.assertEqual(len(f.calls), 5)

    def test_CT06_ordinary_refusal_is_preallocated_private_and_stable(self):
        ordinary = OSError('fictional-private-detail')
        with self.trust_fixture({4: ordinary}) as f, patch.object(
                trust, 'PilotTrustClosureUncertain', side_effect=MemoryError()):
            for unused in range(2):
                with self.assertRaises(Exception) as caught:
                    f.reader.close()
                self.assertIs(caught.exception, f.reader._close_refusal)
                self.assertNotIn('fictional-private-detail', str(caught.exception))
            self.assertIs(f.reader._close_failure, ordinary)
            self.assertEqual(len(f.calls), 5)

    def test_CT07_unknown_acquisition_is_not_speculatively_closed(self):
        with self.trust_fixture(unknown=2) as f:
            for unused in range(2):
                with self.assertRaises(trust.PilotTrustClosureUncertain) as caught:
                    f.reader.close()
                self.assertIs(caught.exception, f.reader._close_refusal)
            self.assertEqual(f.calls, [105, 104, 102, 101])
            self.assertEqual(f.reader._states[2], 'acquire-pending')

    def test_CT08_wrong_thread_refuses_before_any_close(self):
        with self.trust_fixture() as f, patch.object(
                trust, 'threading', SimpleNamespace(current_thread=lambda: object())):
            with self.assertRaises(trust.PilotTrustUnavailable):
                f.reader.close()
            self.assertEqual(f.calls, [])
            self.assertIs(f.reader._closed, False)

    def test_CE01_normal_exchange_stays_once_only(self):
        with self.exchange_fixture() as f:
            self.assertEqual(self.run_exchange(f), b'{"data":[]}')
            self.assertEqual(f.handle.calls, 1)
            self.assertIsNone(f.exchange._failure)
            self.assertIsNone(self.run_exchange(f))
            self.assertEqual(f.handle.calls, 1)

    def test_CE02_serializer_memory_is_same_after_independent_cleanup(self):
        error = MemoryError()
        with self.exchange_fixture(fault_phase='serialize', body_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, error)
            self.assertIs(f.exchange._body_failure, error)
            self.assertEqual(f.handle.calls, 1)
            self.assertEqual(len(f.clock_calls), 2)
            self.assertFalse(f.exchange._busy)

    def test_CE03_pump_allocation_memory_does_not_skip_close(self):
        error = MemoryError()
        with self.exchange_fixture(fault_phase='pump', body_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, error)
            self.assertEqual(f.handle.calls, 1)

    def test_CE04_read_memory_is_retained_after_request_attempt(self):
        error = MemoryError()
        with self.exchange_fixture(fault_phase='read', body_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, error)
            self.assertIn('write', f.events)
            self.assertIs(f.exchange._failure, error)
            self.assertEqual(f.handle.calls, 1)

    def test_CE05_collector_finish_memory_is_retained(self):
        error = MemoryError()
        with self.exchange_fixture(fault_phase='finish', body_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, error)
            self.assertIs(f.exchange._body_failure, error)
            self.assertEqual(f.handle.calls, 1)

    def test_CE06_socket_close_memory_preserved_and_final_clock_attempted(self):
        error = MemoryError()
        with self.exchange_fixture(close_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, error)
            self.assertIs(f.exchange._close_failure, error)
            self.assertEqual(len(f.clock_calls), 3)
            self.assertEqual(f.handle.calls, 1)
            self.assertEqual(f.owner._closure, 'close-pending')

    def test_CE07_final_clock_memory_preserved_after_known_close(self):
        error = MemoryError()
        with self.exchange_fixture(clock_error=error) as f:
            with self.assertRaises(MemoryError) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, error)
            self.assertIs(f.exchange._clock_failure, error)
            self.assertEqual(f.handle.calls, 1)

    def test_CE08_control_from_clock_outranks_close_memory_and_body_ordinary(self):
        body, close, clock = OSError('fictional'), MemoryError(), Control()
        with self.exchange_fixture(fault_phase='serialize', body_error=body,
                close_error=close, clock_error=clock) as f:
            with self.assertRaises(Control) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, clock)
            self.assertIs(f.exchange._body_failure, body)
            self.assertIs(f.exchange._close_failure, close)
            self.assertIs(f.exchange._clock_failure, clock)

    def test_CE09_close_control_dominates_two_memory_failures_without_retry(self):
        body, close, clock = MemoryError(), Control(), MemoryError()
        with self.exchange_fixture(fault_phase='serialize', body_error=body,
                close_error=close, clock_error=clock) as f:
            with self.assertRaises(Control) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, close)
            self.assertIsNone(self.run_exchange(f))
            self.assertIs(f.exchange._failure, close)
            self.assertIs(f.exchange._clock_failure, clock)
            self.assertEqual(f.handle.calls, 1)

    def test_CE10_ordinary_transport_refusal_still_returns_none_privately(self):
        ordinary = OSError('fictional-private-detail')
        with self.exchange_fixture(fault_phase='serialize', body_error=ordinary) as f:
            self.assertIsNone(self.run_exchange(f))
            self.assertIs(f.exchange._body_failure, ordinary)
            self.assertIs(f.exchange._failure, ordinary)
            self.assertEqual(f.handle.calls, 1)

    def test_CE11_first_control_keeps_priority_over_later_controls(self):
        first, close, clock = Control(), Control(), Control()
        with self.exchange_fixture(fault_phase='serialize', body_error=first,
                close_error=close, clock_error=clock) as f:
            with self.assertRaises(Control) as caught:
                self.run_exchange(f)
            self.assertIs(caught.exception, first)
            self.assertIs(f.exchange._close_failure, close)
            self.assertIs(f.exchange._clock_failure, clock)

    def original_caller(self, f, *, trust_reader=None, credential_error=None):
        # All three constructors are pure storage; acquiring methods below are
        # explicit fictional ports. The actual original run/retire methods run.
        attempt = caller.OriginalPrivateClusterRead(
            1003, '192.0.2.7', ('fixture@pve', 'configured'), 110.0)
        attempt._exchange = f.exchange
        attempt._target = f.target
        events = []
        credential = SimpleNamespace()
        credential.acquire = lambda: credential
        credential.take_private_wire_components = lambda: ('fictional',)
        credential._current_data = lambda: None
        def retire():
            events.append('credential-retire')
            if credential_error is not None:
                raise credential_error
        credential.retire = retire
        attempt._credential = credential
        if trust_reader is None:
            attempt._trust = SimpleNamespace(open_fixed=lambda: None,
                build_private_context=lambda: None,
                private_components=lambda: ('192.0.2.7', object()),
                _recheck=lambda: None, close=lambda: events.append('trust-close'))
        else:
            # No fake native receipt: only private_data preparation methods
            # are substituted. Its corrected real close method executes.
            attempt._trust = trust_reader
        return attempt, events

    def test_CO01_original_parent_retains_actual_trust_memory_and_repeats_no_io(self):
        error = MemoryError()
        with self.trust_fixture({4: error}) as t, self.exchange_fixture() as f:
            attempt, events = self.original_caller(f, trust_reader=t.reader)
            for unused in range(2):
                with self.assertRaises(MemoryError) as caught:
                    attempt.retire()
                self.assertIs(caught.exception, error)
            self.assertIs(attempt._cleanup_failures[2], error)
            self.assertIs(attempt._retirement_failure, error)
            self.assertEqual(events, ['credential-retire'])
            self.assertEqual(f.handle.calls, 1)
            self.assertEqual(len(t.calls), 5)

    def test_CO02_actual_exchange_memory_reaches_original_caller_after_all_cleanup(self):
        error = MemoryError()
        with self.exchange_fixture(fault_phase='read', body_error=error) as f, \
                patch.object(caller, 'time', SimpleNamespace(monotonic=lambda: 100.0)):
            attempt, events = self.original_caller(f)
            with self.assertRaises(MemoryError) as caught:
                attempt.run('a' * 32)
            self.assertIs(caught.exception, error)
            self.assertIs(attempt._body_failure, error)
            self.assertIs(attempt._failure, error)
            self.assertEqual(events, ['credential-retire', 'trust-close'])
            self.assertEqual(f.handle.calls, 1)

    def test_CO03_parent_keeps_socket_memory_and_later_credential_memory_trust_control(self):
        socket_error, credential_error, trust_error = MemoryError(), MemoryError(), Control()
        with self.trust_fixture({3: trust_error}) as t, \
                self.exchange_fixture(close_error=socket_error) as f:
            attempt, events = self.original_caller(
                f, trust_reader=t.reader, credential_error=credential_error)
            # Drive the actual corrected exchange first; then original caller's
            # independent retirement sees its pending socket close without retry.
            with self.assertRaises(MemoryError):
                self.run_exchange(f)
            attempt._exchange_started = True
            with self.assertRaises(Control) as caught:
                attempt.retire()
            self.assertIs(caught.exception, trust_error)
            self.assertIs(f.exchange._close_failure, socket_error)
            self.assertIs(attempt._cleanup_failures[1], credential_error)
            self.assertIs(attempt._cleanup_failures[2], trust_error)
            self.assertIs(attempt._retirement_failure, trust_error)
            self.assertEqual(f.handle.calls, 1)
            self.assertEqual(len(t.calls), 5)
            self.assertEqual(events, ['credential-retire'])
