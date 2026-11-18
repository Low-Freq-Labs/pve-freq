"""Unrun internal refusal-method DATA projections, not original admission.

Only the original method tail is borrowed. Projection/Broker below are explicit
fictional objects: no original dispatcher constructor, native handler, accepted
socket, authentication gate or current writer is constructed or enabled. No
send occurs. These cases can only check internal branch/order/exception DATA.
"""
import json
from types import SimpleNamespace
import unittest

from freq.services import pilot_cluster_dispatch as dispatch
from freq.services.cluster_pilot_http import _BadRequest, _RequestUnavailable


class Control(BaseException):
    pass


class DataBroker:
    def __init__(self, original):
        self.original = original
        self.replacement = None
        self.on_lock = None
        self.admit_error = None
        self.preflight_error = None
        self.held = False
        self.events = []
        self.sent = []
        self.cleanup_error = None

    def _owned(self, handler):
        assert self.held
        return self.replacement if self.replacement is not None else self.original

    def _write_remaining(self, original):
        assert original is self.original
        self.events.append(('remaining', original.write_end))
        if self.preflight_error is not None:
            raise self.preflight_error

    def _lock(self, end):
        assert not self.held and end == self.original.write_end
        self.held = True
        self.events.append(('lock', end))
        if self.on_lock is not None:
            self.on_lock()

    def _admit_frame_locked(self, handler, original, response):
        assert self.held and original is self.original
        self.events.append(('admit', response))
        if self.admit_error is not None:
            raise self.admit_error
        original.frame = response
        original.phase = 'admitted'

    def _reserve_write_locked(self, handler, original, response):
        assert self.held and original.frame is response
        assert original.phase == 'admitted'
        self.events.append(('reserve', response))
        original.phase = 'write-reserved'

    def _drop_gate(self, error):
        assert self.held
        self.held = False
        self.cleanup_error = error
        self.events.append(('drop', error))

    def _send_reserved(self, handler, response):
        assert not self.held and self.original.frame is response
        assert self.original.phase == 'write-reserved'
        self.sent.append(response)
        self.events.append(('modeled-send-only', response))


class DataProjection:
    _write_refusal = dispatch.OriginalPilotDispatch._write_refusal

    def __init__(self, operation):
        self.original = SimpleNamespace(operation=operation, phase='ready',
                                        frame=None, write_end=17.0, end=23.0)
        self._broker = DataBroker(self.original)

    def _owned(self, handler):
        return self.original


class GuestRefusalDispatchData(unittest.TestCase):
    def frame(self, projection, error):
        projection._write_refusal(object(), error)
        self.assertEqual(len(projection._broker.sent), 1)
        wire = projection._broker.sent[0]._wire
        head, body = wire.split(b'\r\n\r\n', 1)
        self.assertIn(b'Cache-Control: no-store', head)
        self.assertEqual([row[0] for row in projection._broker.events],
                         ['remaining', 'lock', 'admit', 'reserve', 'drop',
                          'modeled-send-only'])
        self.assertEqual(projection.original.write_end, 17.0)
        return head, json.loads(body)

    def test_RD01_five_literal_operations_fixed_failure_shape(self):
        for op in ('guest-owner-open', 'guest-owner-sources',
                   'guest-owner-inventory', 'guest-owner-profile',
                   'guest-owner-retire'):
            with self.subTest(op=op):
                head, payload = self.frame(DataProjection(op), RuntimeError('private-detail'))
                self.assertTrue(head.startswith(b'HTTP/1.1 503 '))
                self.assertIn(b'Content-Type: application/json; charset=utf-8', head)
                self.assertEqual(payload, {'schema': 2, 'kind': 'guest-unavailable'})
                self.assertNotIn(b'private-detail', head)

    def test_RD02_original_auth_status_and_shape_preserved_on_guest_route(self):
        for status, message in sorted(dispatch._AUTH_ERRORS):
            with self.subTest(status=status, message=message):
                head, payload = self.frame(DataProjection('guest-owner-retire'),
                    dispatch.auth._ClusterPilotAuthRefused(status, message))
                self.assertTrue(head.startswith(('HTTP/1.1 ' + str(status) + ' ').encode()))
                self.assertIn(b'Content-Type: application/json\r\n', head)
                self.assertEqual(payload, {'error': message})

    def test_RD03_legacy_and_unknown_prefix_are_not_v2(self):
        for op in ('read', 'guest-owner-open-extra', 'guest-owner', 'login'):
            head, payload = self.frame(DataProjection(op), _BadRequest())
            self.assertTrue(head.startswith(b'HTTP/1.1 400 '))
            self.assertEqual(payload, {'error': 'cluster_observation_unavailable'})
            self.assertIn(b'Content-Type: application/json\r\n', head)

    def test_RD04_replaced_broker_request_refuses_before_admission(self):
        p = DataProjection('guest-owner-open')
        p._broker.replacement = SimpleNamespace(**vars(p.original))
        with self.assertRaises(_RequestUnavailable):
            p._write_refusal(object(), RuntimeError())
        self.assertEqual([e[0] for e in p._broker.events], ['remaining', 'lock', 'drop'])
        self.assertFalse(p._broker.held)
        self.assertIsNone(p.original.frame)
        self.assertEqual(p._broker.sent, [])

    def test_RD05_operation_changed_after_formatting_refuses(self):
        p = DataProjection('guest-owner-open')
        p._broker.on_lock = lambda: setattr(p.original, 'operation', 'guest-owner-retire')
        with self.assertRaises(_RequestUnavailable):
            p._write_refusal(object(), RuntimeError())
        self.assertIsNone(p.original.frame)
        self.assertEqual(p._broker.sent, [])
        self.assertFalse(p._broker.held)

    def test_RD06_admitted_partial_or_existing_frame_cannot_append_response(self):
        for phase, frame in [('admitted', None), ('write-reserved', None),
                             ('write-attempted', None), ('ready', object())]:
            p = DataProjection('guest-owner-retire')
            p.original.phase, p.original.frame = phase, frame
            with self.assertRaises(_RequestUnavailable):
                p._write_refusal(object(), RuntimeError())
            self.assertEqual(p._broker.sent, [])
            self.assertIs(p.original.frame, frame)
            self.assertEqual(p.original.phase, phase)
            self.assertFalse(p._broker.held)

    def test_RD07_first_genuine_control_is_preserved_and_gate_released(self):
        p = DataProjection('guest-owner-profile')
        first = Control()
        p._broker.admit_error = first
        with self.assertRaises(Control) as caught:
            p._write_refusal(object(), RuntimeError())
        self.assertIs(caught.exception, first)
        self.assertIs(p._broker.cleanup_error, first)
        self.assertFalse(p._broker.held)
        self.assertEqual(p._broker.sent, [])
        self.assertIsNone(p.original.frame)

    def test_RD08_expired_write_allowance_cannot_acquire_gate_or_renew(self):
        p = DataProjection('guest-owner-inventory')
        first = _RequestUnavailable()
        p._broker.preflight_error = first
        with self.assertRaises(_RequestUnavailable) as caught:
            p._write_refusal(object(), RuntimeError())
        self.assertIs(caught.exception, first)
        self.assertEqual(p._broker.events, [('remaining', 17.0)])
        self.assertEqual(p.original.write_end, 17.0)
        self.assertIsNone(p.original.frame)
        self.assertEqual(p._broker.sent, [])
        self.assertFalse(p._broker.held)

    def test_RD09_replaced_operation_subclass_never_compares_under_gate(self):
        comparisons = []
        class OperationSubclass(str):
            def __ne__(self, other):
                comparisons.append(other)
                raise Control()
        p = DataProjection('guest-owner-open')
        p._broker.on_lock = lambda: setattr(p.original, 'operation',
                                            OperationSubclass('guest-owner-open'))
        with self.assertRaises(_RequestUnavailable):
            p._write_refusal(object(), RuntimeError())
        self.assertEqual(comparisons, [])
        self.assertIsNone(p.original.frame)
        self.assertEqual(p._broker.sent, [])
        self.assertFalse(p._broker.held)
