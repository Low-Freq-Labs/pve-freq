"""Injected ownership fixtures, unexecuted; not physical TLS evidence."""
import unittest
from unittest.mock import patch

from freq.services import node_read_exchange as m


TARGET = m.WireTarget("192.0.2.1", "node.invalid", "node")
CREDENTIALS = ("fictional@realm", "fixture", "not-a-real-secret")
WIRE = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n[]"


class FakeSocket:
    def __init__(self, action=None):
        self.calls = 0
        self.action = action

    def close(self):
        self.calls += 1
        if self.action is not None:
            self.action()


class FakePump:
    error = None
    close_action = None
    sockets = None

    def __init__(self, owner, context, target, deadline):
        self.owner = owner

    def connect(self):
        sock = FakeSocket(type(self).close_action)
        type(self).sockets.append(sock)
        self.owner._socket = sock
        if type(self).error is not None:
            raise type(self).error

    def write_request(self, request):
        pass

    def read(self, maximum):
        return WIRE


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        FakePump.error = None
        FakePump.close_action = None
        FakePump.sockets = []
        self.owner = m.OriginalExchange()

    def run_exchange(self):
        with patch.object(m, "TLSPump", FakePump), patch.object(m.time, "monotonic", return_value=0.0):
            return self.owner.run(TARGET, CREDENTIALS, object())

    def test_success_still_closes_original(self):
        self.assertEqual(self.run_exchange(), b"[]")
        self.assertEqual(FakePump.sockets[0].calls, 1)
        self.owner._socket_owner.close()
        self.assertEqual(FakePump.sockets[0].calls, 1)

    def test_lost_connect_return_preserves_original_cleanup(self):
        FakePump.error = ValueError("fictional injected failure")
        self.assertIsNone(self.run_exchange())
        self.assertEqual(FakePump.sockets[0].calls, 1)

    def test_ordinary_close_failure_suppresses_provisional_success(self):
        def fail():
            raise ValueError("fixture close failure")
        FakePump.close_action = fail
        self.assertIsNone(self.run_exchange())
        self.owner._socket_owner.close()
        self.assertEqual(FakePump.sockets[0].calls, 1)

    def test_first_genuine_identity_survives_later_cleanup_failure(self):
        class Stop(BaseException):
            pass
        original = Stop()
        later = Stop()
        FakePump.error = original
        def fail():
            raise later
        FakePump.close_action = fail
        with self.assertRaises(Stop) as caught:
            self.run_exchange()
        self.assertIs(caught.exception, original)
        self.assertEqual(FakePump.sockets[0].calls, 1)

    def test_genuine_cleanup_failure_propagates_by_identity(self):
        class Stop(BaseException):
            pass
        error = Stop()
        def fail():
            raise error
        FakePump.close_action = fail
        with self.assertRaises(Stop) as caught:
            self.run_exchange()
        self.assertIs(caught.exception, error)

    def test_close_reentry_irreversibly_retires_provisional_result(self):
        nested = []
        def reenter():
            nested.append(self.owner.run(TARGET, CREDENTIALS, object()))
        FakePump.close_action = reenter
        self.assertIsNone(self.run_exchange())
        self.assertEqual(nested, [None])
        self.assertTrue(self.owner._retired)
        self.assertEqual(len(FakePump.sockets), 1)

    def test_outgoing_credential_refusal_has_no_socket(self):
        with patch.object(m, "TLSPump", FakePump):
            self.assertIsNone(self.owner.run(TARGET, ("a@b", "id", "x\r\ny"), object()))
        self.assertEqual(FakePump.sockets, [])
        self.assertTrue(self.owner._socket_owner._spent)

    def test_post_close_deadline_suppresses_result(self):
        with patch.object(m, "TLSPump", FakePump), patch.object(m.time, "monotonic", side_effect=[0.0, 1.0, 10.0]):
            self.assertIsNone(self.owner.run(TARGET, CREDENTIALS, object()))
        self.assertEqual(FakePump.sockets[0].calls, 1)

    def test_original_deadline_is_passed_without_renewal(self):
        deadlines = []
        class RecordingPump(FakePump):
            def __init__(self, owner, context, target, deadline):
                super().__init__(owner, context, target, deadline)
                deadlines.append(deadline)
        with patch.object(m, "TLSPump", RecordingPump), patch.object(m.time, "monotonic", return_value=9.0):
            self.assertEqual(self.owner.run(TARGET, CREDENTIALS, object(), original_deadline=10.0), b"[]")
        self.assertEqual(deadlines, [10.0])

    def test_expired_or_extended_original_deadline_has_no_effect(self):
        for deadline in (0.0, 11.0, float("nan"), float("inf"), True):
            owner = m.OriginalExchange()
            with patch.object(m, "TLSPump", FakePump), patch.object(m.time, "monotonic", return_value=0.0):
                self.assertIsNone(owner.run(TARGET, CREDENTIALS, object(), original_deadline=deadline))
        self.assertEqual(FakePump.sockets, [])

    def test_replaced_cleanup_owner_never_receives_original_duty(self):
        outer = self.owner
        original_owner = outer._socket_owner
        replacement = m.OriginalSocket()
        class ReplacingPump(FakePump):
            def connect(self):
                super().connect()
                outer._socket_owner = replacement
        with patch.object(m, "TLSPump", ReplacingPump), patch.object(m.time, "monotonic", return_value=0.0):
            self.assertIsNone(outer.run(TARGET, CREDENTIALS, object()))
        self.assertTrue(original_owner._spent)
        self.assertFalse(replacement._spent)
        self.assertEqual(FakePump.sockets[0].calls, 1)
