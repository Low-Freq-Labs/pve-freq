"""UNRUN fictional DATA integration. Every proposed socket/TLS effect patched.

No current original admission, actual native fault, physical closure, outside
return receipt or execution qualification is established by these intentions.
"""
import contextlib
import unittest
from unittest.mock import patch

from test_guest_profile_continuation_data import ProfileContinuationData
from freq.services.node_read_profile import WireTarget
from freq.services import node_read_tls
from freq.services import pilot_guest_profile_exchange as source


class ProfileExchangeData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileContinuationData()
        self.fixture.setUp()
        self.plan = self.fixture.plan()
        self.transport = WireTarget('192.0.2.1', 'fixture.example', 'transport-node')
        self.credentials = ('fixture@pam', 'fixture-token', 'fictional-secret')
        self.trust = object()  # Only passed to fictional pump, never real TLS.
        self.body = b'{"data":{}}'
        self.frame = (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                      b'Content-Length: ' + str(len(self.body)).encode() + b'\r\n\r\n' + self.body)
        self.events = []
        self.close_error = self.connect_error = self.pump_init_error = None
        self.write_error = self.read_error = None
        self.close_calls = self.factory_calls = 0
        fixture = self

        class FictionalSocket:
            def close(inner):
                fixture.close_calls += 1
                fixture.events.append('close')
                if fixture.close_error is not None:
                    raise fixture.close_error

        self.handle = FictionalSocket()

        class FictionalPump:
            def __init__(inner, owner, trust, transport, deadline):
                fixture.assertIs(fixture.exchange._pump, inner)
                fixture.assertIs(owner, fixture.exchange._original_socket)
                fixture.assertIs(trust, fixture.trust)
                fixture.assertIs(transport, fixture.transport)
                fixture.assertEqual(deadline, 115.0)
                inner.owner, inner.remaining = owner, fixture.frame
                if fixture.pump_init_error is not None:
                    raise fixture.pump_init_error

            def connect(inner):
                inner.owner.acquire(4)  # Original method, patched stdlib factory.
                if fixture.connect_error is not None:
                    raise fixture.connect_error

            def write_request(inner, wire):
                fixture.assertIs(wire, fixture.exchange._request)
                fixture.events.append('write')
                if fixture.write_error is not None:
                    raise fixture.write_error

            def read(inner, maximum):
                if fixture.read_error is not None:
                    raise fixture.read_error
                value, inner.remaining = inner.remaining[:maximum], inner.remaining[maximum:]
                return value

        self.Pump = FictionalPump
        self.exchange = source._ProfileSectionExchange(self.plan, 'status', original_deadline=115.0)

    def factory(self, family, kind):
        self.factory_calls += 1
        self.assertEqual((family, kind), (node_read_tls.socket.AF_INET, node_read_tls.socket.SOCK_STREAM))
        self.assertEqual(self.exchange._original_socket._acquisition, 'acquire-pending')
        return self.handle

    @contextlib.contextmanager
    def effects(self, *, collector=None, clock=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(node_read_tls.socket, 'socket', self.factory))
            stack.enter_context(patch.object(source, 'TLSPump', self.Pump))
            stack.enter_context(patch.object(source.time, 'monotonic', clock or (lambda: 113.0)))
            if collector is not None:
                stack.enter_context(patch.object(source, 'ProfileSectionResponseCollector', collector))
            yield

    def run_once(self):
        return self.exchange.run(self.transport, self.credentials, self.trust)

    def assert_no_repeat(self):
        before = (self.factory_calls, self.close_calls)
        with self.assertRaises(ValueError): self.run_once()
        self.assertEqual((self.factory_calls, self.close_calls), before)

    def test_PX01_provisional_body_retained_after_one_known_close_and_no_repeat(self):
        with self.effects():
            result = self.run_once()
            self.assertEqual(result, self.body)
            self.assertIs(result, self.exchange._result)
            self.assertEqual(self.exchange._phase, 'prepared')
            self.assertEqual(self.exchange._cleanup, 'returned')
            self.assertIs(self.exchange._original_socket._socket, self.handle)
            self.assertEqual((self.factory_calls, self.close_calls), (1, 1))
            self.assertIn(b'/nodes/fixture-node/qemu/100/status/current ', self.exchange._request)
            self.exchange.retire()
            self.assert_no_repeat()

    def test_PX02_connect_error_closes_known_handle_before_returning_local_failure(self):
        self.connect_error = OSError('fictional connect')
        with self.effects():
            self.assertIsNone(self.run_once())
            self.assertIs(self.exchange._body_failure, self.connect_error)
            self.assertEqual(self.exchange._operation, 'connect-pending')
            self.assertEqual(self.close_calls, 1)
            self.assert_no_repeat()

    def test_PX03_connect_control_propagates_after_independent_close(self):
        self.connect_error = KeyboardInterrupt('fictional connect control')
        with self.effects():
            with self.assertRaises(KeyboardInterrupt) as raised: self.run_once()
            self.assertIs(raised.exception, self.connect_error)
            self.assertEqual(self.close_calls, 1)
            self.assert_no_repeat()

    def test_PX04_write_and_read_errors_never_publish_body_or_retry(self):
        for operation in ('write_error', 'read_error'):
            self.setUp()
            setattr(self, operation, OSError('fictional transport'))
            with self.effects():
                self.assertIsNone(self.run_once())
                self.assertIsNone(self.exchange._result)
                self.assertEqual(self.close_calls, 1)
                self.assert_no_repeat()

    def test_PX05_lost_successful_feed_return_stays_outer_pending_even_local_unspent(self):
        base = source.ProfileSectionResponseCollector
        class LostFeed(base):
            def feed(inner, chunk):
                super().feed(chunk)
                raise KeyboardInterrupt('fictional lost successful feed return')
        with self.effects(collector=LostFeed):
            with self.assertRaises(KeyboardInterrupt): self.run_once()
            self.assertIs(self.exchange._collector.spent, False)
            self.assertEqual(self.exchange._operation, 'feed-pending')
            self.assertEqual(self.exchange._phase, 'failed')
            self.assertEqual(self.close_calls, 1)
            self.assert_no_repeat()

    def test_PX06_collector_constructor_allocation_failure_keeps_partial_holder(self):
        fixture = self
        class NoHeader:
            def __init__(inner):
                fixture.assertIs(fixture.exchange._collector, inner)
                raise MemoryError('fictional header allocation')
        with self.effects(collector=NoHeader):
            with self.assertRaises(MemoryError): self.run_once()
            self.assertIsInstance(self.exchange._collector, NoHeader)
            self.assertIsNone(self.exchange._pump)
            self.assertEqual(self.exchange._operation, 'collector-constructor-pending')
            self.assertEqual((self.factory_calls, self.close_calls), (0, 0))
            self.assertEqual(self.exchange._original_socket._closure, 'returned-no-acquisition')
            self.assert_no_repeat()

    def test_PX07_pump_constructor_control_keeps_partial_pump_and_no_native_socket(self):
        self.pump_init_error = SystemExit('fictional BIO init')
        with self.effects():
            with self.assertRaises(SystemExit): self.run_once()
            self.assertIsInstance(self.exchange._pump, self.Pump)
            self.assertEqual(self.exchange._operation, 'pump-constructor-pending')
            self.assertEqual((self.factory_calls, self.close_calls), (0, 0))
            self.assert_no_repeat()

    def test_PX08_finish_control_retains_body_and_pending_result_copy(self):
        base = source.ProfileSectionResponseCollector
        class LostCopy(base):
            def finish(inner):
                super().finish()
                raise MemoryError('fictional lost immutable copy')
        with self.effects(collector=LostCopy):
            with self.assertRaises(MemoryError): self.run_once()
            self.assertEqual(bytes(self.exchange._collector.body), self.body)
            self.assertTrue(self.exchange._collector.spent)
            self.assertIsNone(self.exchange._result)
            self.assertEqual(self.exchange._operation, 'finish-pending')
            self.assertEqual(self.close_calls, 1)

    def test_PX09_late_clock_control_cannot_skip_close_or_publish_retained_result(self):
        def clock():
            if self.close_calls:
                self.events.append('late-clock')
                raise KeyboardInterrupt('fictional late clock')
            return 113.0
        with self.effects(clock=clock):
            with self.assertRaises(KeyboardInterrupt): self.run_once()
            self.assertEqual(self.exchange._result, self.body)
            self.assertEqual(self.events[-2:], ['close', 'late-clock'])
            self.assertEqual(self.exchange._phase, 'failed')
            self.assert_no_repeat()

    def test_PX10_first_genuine_control_preserved_and_close_control_also_retained(self):
        self.connect_error = KeyboardInterrupt('fictional first')
        self.close_error = SystemExit('fictional later')
        with self.effects():
            with self.assertRaises(KeyboardInterrupt) as raised: self.run_once()
            self.assertIs(raised.exception, self.connect_error)
            self.assertIs(self.exchange._cleanup_failure, self.close_error)
            self.assertEqual(self.exchange._cleanup, 'close-pending')
            self.assertIs(self.exchange._original_socket._socket, self.handle)
            with self.assertRaises(ValueError): self.exchange.retire()
            self.assertEqual(self.close_calls, 1)

    def test_PX11_close_control_overrides_ordinary_error_but_retains_both(self):
        self.connect_error = OSError('fictional body')
        self.close_error = KeyboardInterrupt('fictional close')
        with self.effects():
            with self.assertRaises(KeyboardInterrupt) as raised: self.run_once()
            self.assertIs(raised.exception, self.close_error)
            self.assertIs(self.exchange._body_failure, self.connect_error)
            self.assertIs(self.exchange._cleanup_failure, self.close_error)

    def test_PX12_body_allocation_failure_survives_ordinary_close_error(self):
        self.read_error = MemoryError('fictional body allocation')
        self.close_error = OSError('fictional close error')
        with self.effects():
            with self.assertRaises(MemoryError) as raised: self.run_once()
            self.assertIs(raised.exception, self.read_error)
            self.assertIs(self.exchange._cleanup_failure, self.close_error)
            self.assertEqual(self.close_calls, 1)

    def test_PX13_replaced_alias_cannot_redirect_known_original_close(self):
        original_read = self.Pump.read
        def replace_alias(pump, maximum):
            value = original_read(pump, maximum)
            self.exchange._socket_owner = object()
            return value
        with self.effects(), patch.object(self.Pump, 'read', replace_alias):
            self.assertIsNone(self.run_once())
            self.assertEqual(self.close_calls, 1)
            self.assertIs(self.exchange._original_socket._socket, self.handle)
            self.assertIsNotNone(self.exchange._cleanup_failure)
            self.assert_no_repeat()

    def test_PX14_bad_clock_before_effects_is_terminal_without_deadline_renewal(self):
        for now in (115.0, float('nan'), 113, True, 100.0):
            self.setUp()
            with self.effects(clock=lambda: now):
                self.assertIsNone(self.run_once())
                self.assertEqual(self.exchange._end, 115.0)
                self.assertEqual((self.factory_calls, self.close_calls), (0, 0))
                self.assert_no_repeat()

    def test_PX15_backward_clock_after_feed_denies_body_and_still_closes(self):
        def clock():
            return 112.0 if self.exchange._collector is not None and self.exchange._collector.body is not None else 113.0
        with self.effects(clock=clock):
            self.assertIsNone(self.run_once())
            self.assertEqual(self.close_calls, 1)
            self.assertEqual(self.exchange._end, 115.0)
            self.assert_no_repeat()

    def test_PX16_lxc_and_foreign_plans_refuse_before_any_transport(self):
        self.fixture.record._target = self.fixture.begin.target = ('fixture-node', 'lxc', 100)
        lxc = self.fixture.plan()
        class Trap:
            def __getattribute__(inner, name): raise AssertionError('foreign plan hook')
        for plan in (lxc, Trap()):
            with self.assertRaises(ValueError):
                source._ProfileSectionExchange(plan, 'status', original_deadline=115.0)
        self.assertEqual(self.factory_calls, 0)

    def test_PX17_oversized_body_refuses_before_private_body_allocation(self):
        self.frame = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 262145\r\n\r\n'
        with self.effects():
            self.assertIsNone(self.run_once())
            self.assertIsNone(self.exchange._collector.body)
            self.assertEqual(self.close_calls, 1)
            self.assert_no_repeat()

    def test_PX18_known_unstarted_retirement_prevents_run_without_native_effect(self):
        with self.effects():
            self.exchange.retire()
            self.assertEqual(self.exchange._phase, 'retired')
            self.assertEqual((self.factory_calls, self.close_calls), (0, 0))
            self.assert_no_repeat()
