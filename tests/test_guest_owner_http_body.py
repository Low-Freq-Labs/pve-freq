"""UNRUN original-method HTTP DATA fixtures with fictional sockets/clock.

Private broker DATA is seeded to exercise exact parse/body methods only. No
canonical installation/native owner/authenticator/listener/dispatcher is made.
Setting the component DATA live marker is not original native-current proof.
"""
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services import cluster_pilot_http as http
from freq.services import cluster_pilot_request as routing
from freq.services import guest_owner_request as grammar


PREFIX = '/api/guest-read/v2/'
C, F, R = 'a' * 64, 'b' * 64, 'c' * 64
SHAPES = {
    'open': {'schema': 2, 'open_nonce': C},
    'sources': {'schema': 2, 'owner_ref': F},
    'inventory': {'schema': 2, 'owner_ref': F, 'source_ref': R},
    'profile': {'schema': 2, 'owner_ref': F, 'guest_ref': R},
    'retire': {'schema': 2, 'open_nonce': C},
}


def raw(value):
    return json.dumps(value, separators=(',', ':')).encode('ascii')


class SocketData:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class StreamData(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.body_reads = []

    def read(self, count=-1):
        self.body_reads.append(count)
        return super().read(count)


class Control(BaseException):
    pass


class GuestOwnerHTTPData(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        timer = patch.object(http.time, 'monotonic', side_effect=lambda: self.clock[0])
        timer.start()
        self.addCleanup(timer.stop)

    def request(self, route='open', body=None, path=None, method='POST',
                length=None, extra=b'', mime=b'application/json'):
        if body is None:
            body = raw(SHAPES[route])
        if path is None:
            path = PREFIX + route
        sock, server = SocketData(), object()
        size = str(len(body)).encode() if length is None else length
        head = method.encode() + b' ' + path.encode() + b' HTTP/1.1\r\nHost: fixture\r\n'
        head += b'Content-Length: ' + size + b'\r\nContent-Type: ' + mime + b'\r\n'
        stream = StreamData(head + extra + b'\r\n' + body)
        handler = SimpleNamespace(server=server, request=sock, rfile=stream)
        broker = http._OriginalHTTPRequests(server)
        original = http._OriginalRequest(sock, 101.0, '192.0.2.1')
        original.handler, original.thread, original.phase = handler, threading.current_thread(), 'reading'
        broker._requests[sock] = original
        broker._live = True  # Fictional component DATA only.
        return broker, handler, original, stream

    def parsed(self, **kwargs):
        b, h, o, stream = self.request(**kwargs)
        self.assertTrue(b._parse(h, o))
        return b, h, o, stream

    def test_VH01_all_five_original_operations_acquire_exact_body_once(self):
        for route, shape in SHAPES.items():
            b, h, o, stream = self.parsed(route=route)
            self.assertEqual(o.operation, 'guest-owner-' + route)
            self.assertEqual(b._body_json(h), shape)
            self.assertTrue(o.body_taken)
            self.assertEqual(stream.body_reads, [len(raw(shape))])
            self.assertEqual(o.end, 101.0)

    def test_VH02_public_handler_mutation_cannot_change_private_purpose(self):
        b, h, o, _ = self.parsed(route='inventory')
        h.command, h.path = 'POST', PREFIX + 'profile'
        self.assertEqual(b._body_json(h), SHAPES['inventory'])
        self.assertEqual(o.operation, 'guest-owner-inventory')

    def test_VH03_cross_purpose_child_or_nonce_is_consumed_and_refused(self):
        for route, body in (('profile', SHAPES['inventory']),
                            ('inventory', SHAPES['profile']),
                            ('open', SHAPES['sources']), ('retire', SHAPES['sources'])):
            b, h, o, _ = self.parsed(route=route, body=raw(body))
            with self.assertRaises(http._BadRequest):
                b._body_json(h)
            self.assertTrue(o.body_taken)

    def test_VH04_256_body_positive_and257_refuses_before_read(self):
        for route, shape in SHAPES.items():
            encoded = raw(shape)
            exact = encoded + b' ' * (256 - len(encoded))
            b, h, o, stream = self.parsed(route=route, body=exact)
            self.assertEqual(b._body_json(h), shape)
            self.assertEqual(stream.body_reads, [256])
            b, h, o, stream = self.request(route=route, body=exact + b' ')
            with self.assertRaises(http._BadRequest):
                b._parse(h, o)
            self.assertEqual(stream.body_reads, [])

    def test_VH05_invalid_length_lexemes_refuse_before_acquisition(self):
        for length in (b'0', b'01', b'-1', b'1.0', b'257', b'99999999'):
            b, h, o, stream = self.request(length=length)
            with self.assertRaises(http._BadRequest):
                b._parse(h, o)
            self.assertEqual(stream.body_reads, [])

    def test_VH06_duplicate_framing_and_transfer_controls_refuse(self):
        for extra in (b'Content-Length: 92\r\n', b'Content-Type: application/json\r\n',
                      b'Transfer-Encoding: chunked\r\n', b'Expect: 100-continue\r\n'):
            b, h, o, stream = self.request(extra=extra)
            with self.assertRaises(http._BadRequest):
                b._parse(h, o)
            self.assertEqual(stream.body_reads, [])

    def test_VH07_strict_selected_JSON_mime_before_body(self):
        for mime in (b'text/plain', b'application/json; charset=latin1', b'application/json, text/plain'):
            b, h, o, stream = self.request(mime=mime)
            with self.assertRaises(http._BadRequest):
                b._parse(h, o)
            self.assertEqual(stream.body_reads, [])
        b, h, o, _ = self.parsed(mime=b'application/json; charset=utf-8')
        self.assertEqual(b._body_json(h), SHAPES['open'])

    def test_VH08_truncated_original_body_refuses_and_does_not_mark_ready(self):
        b, h, o, stream = self.request(body=b'{}', length=b'3')
        with self.assertRaises(http._BadRequest):
            b._parse(h, o)
        self.assertEqual(stream.body_reads, [3])
        self.assertEqual(o.phase, 'reading')

    def test_VH09_success_and_invalid_body_both_consume_once(self):
        for body in (raw(SHAPES['open']), b'{}'):
            b, h, o, stream = self.parsed(body=body)
            if body == b'{}':
                with self.assertRaises(http._BadRequest):
                    b._body_json(h)
            else:
                self.assertEqual(b._body_json(h), SHAPES['open'])
            self.assertTrue(o.body_taken)
            with self.assertRaises(http._BadRequest):
                b._body_json(h)
            self.assertEqual(stream.body_reads, [len(body)])

    def test_VH10_original_end_before_decode_is_not_renewed(self):
        b, h, o, _ = self.parsed()
        self.clock[0] = 101.0
        with self.assertRaises(http._RequestUnavailable):
            b._body_json(h)
        self.assertTrue(o.body_taken)
        self.assertEqual(o.end, 101.0)
        self.clock[0] = 100.0
        with self.assertRaises(http._BadRequest):
            b._body_json(h)

    def test_VH11_expiry_after_decoder_withholds_result(self):
        b, h, o, _ = self.parsed()
        decode = grammar.decode_guest_owner_request
        def expire(*args):
            result = decode(*args)
            self.clock[0] = 101.0
            return result
        with patch.object(grammar, 'decode_guest_owner_request', side_effect=expire):
            with self.assertRaises(http._RequestUnavailable):
                b._body_json(h)
        self.assertTrue(o.body_taken)
        self.assertEqual(o.end, 101.0)

    def test_VH12_genuine_decoder_control_is_preserved_and_consumed(self):
        b, h, o, _ = self.parsed()
        control = Control('fixture')
        with patch.object(grammar, 'decode_guest_owner_request', side_effect=control):
            with self.assertRaises(Control) as caught:
                b._body_json(h)
        self.assertIs(caught.exception, control)
        self.assertTrue(o.body_taken)
        with self.assertRaises(http._BadRequest):
            b._body_json(h)

    def test_VH13_wrong_component_owner_or_thread_cannot_consume(self):
        for wrong in ('server', 'thread', 'handler', 'live'):
            b, h, o, _ = self.parsed()
            if wrong == 'server': h.server = object()
            if wrong == 'thread': o.thread = object()
            if wrong == 'handler': o.handler = object()
            if wrong == 'live': b._live = False
            with self.assertRaises(http._RequestUnavailable):
                b._body_json(h)
            self.assertFalse(o.body_taken)

    def test_VH14_literal_path_neighbors_never_acquire_body(self):
        for route in SHAPES:
            path = PREFIX + route
            for neighbor in (path + '/', path + '?x=1', path + '#x', path.replace('/v2/', '/%762/')):
                b, h, o, stream = self.request(path=neighbor)
                self.assertFalse(b._parse(h, o))
                self.assertIsNone(o.operation)
                self.assertEqual(stream.body_reads, [])

    def test_VH15_old25_routes_plus_v2_and_exact_selected_guest_assets(self):
        old = json.loads((Path(__file__).parent / 'v1_routes.json').read_bytes())
        self.assertEqual(len(old), 25)
        # Preserve the inherited nonstatic operation contract. Only the exact
        # selected cohort changes the twelve static selectors; never aliases.
        revision = 'original-guest-workspace-20261024-r50'
        expected = [[method, '/static/' + asset + '?v=' + revision
                     if operation == 'asset' else path, operation, asset]
                    for method, path, operation, asset in old]
        inherited = [list(row) for row in routing._ROUTES
                     if not row[2].startswith('guest-owner-') and
                     row[1] != '/dashboard/pve-firewall' and row[2] != 'fleet-targets']
        self.assertEqual(inherited, expected)
        self.assertEqual(len(routing._ROUTES), 32)
        self.assertEqual([row for row in routing._ROUTES if row[2] == 'fleet-targets'],
                         [('GET', '/api/exec/targets', 'fleet-targets', None)])
        self.assertEqual(routing.SELECTED_ASSET_REVISION, revision)
        self.assertEqual(sum(row[2] == 'asset' for row in expected), 12)
        for method, path, operation, asset in expected:
            self.assertEqual(routing.classify_request(method, path), (operation, asset))
            if operation == 'asset':
                legacy = '/static/' + asset
                for neighbor in (legacy, legacy + '?v=canonical-firewall-20261024-r1',
                                 legacy + '?v=original-guest-workspace-20261024-r13',
                                 legacy + '?v=original-guest-workspace-20261024-r14',
                                 legacy + '?v=original-guest-workspace-20261024-r15',
                                 legacy + '?v=original-guest-workspace-20261024-r16',
                                 legacy + '?v=original-guest-workspace-20261024-r22',
                                 legacy + '?v=original-guest-workspace-20261024-r35-r2',
                                 legacy + '?v=original-guest-workspace-20261024-r34',
                                 legacy + '?v=original-guest-workspace-20261024-r33',
                                 legacy + '?v=original-guest-workspace-20261024-r32',
                                 legacy + '?v=original-guest-workspace-20261024-r31',
                                 legacy + '?v=original-guest-workspace-20261024-r49',
                                 legacy + '?v=original-guest-workspace-20261024-r48',
                                 legacy + '?v=original-guest-workspace-20261024-r47',
                                 legacy + '?v=original-guest-workspace-20261024-r45',
                                 legacy + '?v=original-guest-workspace-20261024-r44',
                                 legacy + '?v=original-guest-workspace-20261024-r43',
                                 legacy + '?v=original-guest-workspace-20261024-r42',
                                 legacy + '?v=original-guest-workspace-20261024-r40',
                                 legacy + '?v=original-guest-workspace-20261024-r41',
                                 legacy + '?v=original-guest-workspace-20261024-r39',
                                 legacy + '?v=original-guest-workspace-20261024-r38',
                                 legacy + '?v=original-guest-workspace-20261024-r37',
                                 legacy + '?v=original-guest-workspace-20261024-r36',
                                 legacy + '?v=original-guest-workspace-20261024-r37',
                                 legacy + '?v=original-guest-workspace-20261024-r30',
                                 legacy + '?v=original-guest-workspace-20261024-r29',
                                 legacy + '?v=original-guest-workspace-20261024-r28',
                                 legacy + '?v=original-guest-workspace-20261024-r27',
                                 legacy + '?v=original-guest-workspace-20261024-r26',
                                 legacy + '?v=original-guest-workspace-20261024-r25',
                                 legacy + '?v=original-guest-workspace-20261024-r23',
                                 legacy + '?v=original-guest-workspace-20261024-r21',
                                 legacy + '?v=original-guest-workspace-20261024-r20',
                                 legacy + '?v=original-guest-workspace-20261024-r19',
                                 legacy + '?v=original-guest-workspace-20261024-r11',
                                 path + '&x=1', path + '#fragment', path + '/'):
                    self.assertIsNone(routing.classify_request(method, neighbor))
                self.assertIsNone(routing.classify_request('POST', path))
        self.assertEqual(routing.classify_request('GET', '/dashboard/pve-firewall'),
                         ('app', 'app.html'))
        for neighbor in ('/dashboard/pve-firewall/', '/dashboard/pve-firewall?x=1',
                         '/dashboard/%70ve-firewall', '/dashboard/pve-firewall#fragment'):
            self.assertIsNone(routing.classify_request('GET', neighbor))
        self.assertIsNone(routing.classify_request('POST', '/dashboard/pve-firewall'))
        for route in SHAPES:
            self.assertEqual(routing.classify_request('POST', PREFIX + route), ('guest-owner-' + route, None))
            self.assertIsNone(routing.classify_request('GET', PREFIX + route))

    def test_VH16_old_v1_and_login_body_contracts_preserved(self):
        for path, method, body, expected in (
                ('/api/guest-read/v1/sources', 'GET', b'', {}),
                ('/api/guest-read/v1/inventory', 'POST', raw({'schema': 1, 'source_ref': R}), {'schema': 1, 'source_ref': R}),
                ('/api/auth/login', 'POST', raw({'username': ' Fixture ', 'password': 'literal'}), {'username': ' Fixture ', 'password': 'literal'})):
            b, h, o, _ = self.parsed(path=path, method=method, body=body)
            self.assertEqual(b._body_json(h), expected)

    def test_VH17_body_decoder_uses_retained_bytes_after_stream_closed(self):
        b, h, o, stream = self.parsed(route='profile')
        stream.close()
        self.assertEqual(b._body_json(h), SHAPES['profile'])
        self.assertEqual(len(stream.body_reads), 1)
        self.assertIsNone(o.frame)
        self.assertEqual(o.phase, 'ready')

    def test_VH18_private_operation_changed_during_decode_refuses(self):
        b, h, o, _ = self.parsed(route='open')
        decode = grammar.decode_guest_owner_request
        def mutate(*args):
            result = decode(*args)
            o.operation = 'guest-owner-retire'
            return result
        with patch.object(grammar, 'decode_guest_owner_request', side_effect=mutate):
            with self.assertRaises(http._BadRequest):
                b._body_json(h)
        self.assertTrue(o.body_taken)
        self.assertIsNone(o.frame)

    def test_VH19_malformed_schema_duplicates_and_BOM_are_consumed(self):
        for body in (raw({'schema': True, 'open_nonce': C}), b'\xef\xbb\xbf' + raw(SHAPES['open']),
                     b'{"schema":2,"schema":2,"open_nonce":"' + C.encode() + b'"}', raw(SHAPES['open']) + b'{}'):
            b, h, o, _ = self.parsed(body=body)
            with self.assertRaises(http._BadRequest):
                b._body_json(h)
            self.assertTrue(o.body_taken)

    def test_VH20_clock_control_never_reopens_body_duty(self):
        b, h, o, _ = self.parsed()
        control = Control('fixture-clock')
        with patch.object(http.time, 'monotonic', side_effect=control):
            with self.assertRaises(Control) as caught:
                b._body_json(h)
        self.assertIs(caught.exception, control)
        self.assertTrue(o.body_taken)
        with self.assertRaises(http._BadRequest):
            b._body_json(h)
