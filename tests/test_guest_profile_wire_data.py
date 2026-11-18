"""UNRUN fixed request-byte DATA with fictional credentials only."""
import unittest

from test_guest_profile_continuation_data import ProfileContinuationData
from freq.services.node_read_profile import WireTarget
from freq.services import pilot_guest_profile_wire as source


class ProfileWireData(unittest.TestCase):
    def setUp(self):
        self.fixture = ProfileContinuationData()
        self.fixture.setUp()
        self.plan = self.fixture.plan()
        self.transport = WireTarget('192.0.2.1', 'fixture.example', 'transport-node')
        self.credentials = ('fixture@pam', 'fixture-token', 'fictional-secret')

    def wire(self, section='status', credentials=None, transport=None):
        return source.serialize_profile_section_request(self.plan, section,
            self.transport if transport is None else transport,
            self.credentials if credentials is None else credentials)

    def test_PW01_exact_status_GET_and_private_fixed_headers(self):
        self.assertEqual(self.wire(), (
            b'GET /api2/json/nodes/fixture-node/qemu/100/status/current HTTP/1.1\r\n'
            b'Host: 192.0.2.1:8006\r\n'
            b'Authorization: PVEAPIToken=fixture@pam!fixture-token=fictional-secret\r\n'
            b'Accept: application/json\r\nConnection: close\r\n\r\n'))

    def test_PW02_only_three_fixed_distinct_section_paths(self):
        for section, suffix in source._SUFFIXES:
            wire = self.wire(section)
            first = wire.split(b'\r\n', 1)[0]
            self.assertEqual(first, ('GET /api2/json/nodes/fixture-node/qemu/100' + suffix + ' HTTP/1.1').encode())
            self.assertNotIn(b'?', first)
            self.assertNotIn(b'#', first)
            self.assertEqual(wire.count(b'Authorization:'), 1)

    def test_PW03_transport_node_is_never_used_as_guest_path(self):
        wire = self.wire()
        self.assertNotIn(b'transport-node', wire)
        self.assertIn(b'/nodes/fixture-node/qemu/100/', wire)

    def test_PW04_ipv6_host_is_canonical_bracketed_literal(self):
        target = WireTarget('2001:0db8::1', '2001:db8::1', 'transport-node')
        self.assertIn(b'Host: [2001:db8::1]:8006\r\n', self.wire(transport=target))

    def test_PW05_lxc_zero_read_plan_refuses_before_credential_hooks(self):
        self.fixture.record._target = self.fixture.begin.target = ('fixture-node', 'lxc', 100)
        self.plan = self.fixture.plan()
        class Trap:
            def __getattribute__(self, name): raise AssertionError('credential hook')
        with self.assertRaises(ValueError): self.wire(credentials=Trap())

    def test_PW06_unknown_or_nonbuiltin_section_refuses_before_credentials(self):
        class Section(str): pass
        class Trap:
            def __getattribute__(self, name): raise AssertionError('credential hook')
        for section in ('other', '/status/current', 'status?x', Section('status'), True):
            with self.assertRaises(ValueError): self.wire(section, credentials=Trap())

    def test_PW07_bool_or_out_of_range_vmid_tampered_DATA_refuses(self):
        for vmid in (True, 99, 1000000000, '100'):
            object.__setattr__(self.plan, 'target', ('fixture-node', 'qemu', vmid))
            with self.assertRaises(ValueError): self.wire()

    def test_PW08_target_path_injection_or_noncanonical_node_refuses(self):
        for node in ('n/other', 'n?x', 'n\r\nX: y', '-node', 'n_' , 'n' * 65):
            object.__setattr__(self.plan, 'target', (node, 'qemu', 100))
            with self.assertRaises(ValueError): self.wire()

    def test_PW09_tampered_path_method_bodycap_or_row_type_is_not_accepted(self):
        class Row(tuple): pass
        original = self.plan.reads
        for row in ((original[0][0], 'POST', original[0][2], 262144),
                    (original[0][0], 'GET', original[0][2] + '?other', 262144),
                    (original[0][0], 'GET', original[0][2], 262145),
                    (original[0][0], 'GET', original[0][2], True), Row(original[0])):
            object.__setattr__(self.plan, 'reads', (row,) + original[1:])
            with self.assertRaises(ValueError): self.wire()

    def test_PW10_principal_CRLF_or_second_realm_separator_refuses(self):
        for principal in ('fixture@pam\r\nX: y', 'fixture@@pam', '@pam', 'fixture@'):
            with self.assertRaises(ValueError): self.wire(credentials=(principal, 'token', 'fictional'))

    def test_PW11_token_CRLF_delimiters_or_unicode_refuses(self):
        for token in ('x\r\nX: y', 'x!other', 'x=other', 'tökén', ''):
            with self.assertRaises(ValueError): self.wire(credentials=('fixture@pam', token, 'fictional'))

    def test_PW12_secret512_neighbor513_and_header_delimiters(self):
        self.assertIn(b'=' + b's' * 512 + b'\r\n', self.wire(credentials=('fixture@pam', 'token', 's' * 512)))
        for secret in ('s' * 513, 'x\r\nX: y', 'x!other', 'x=other', ''):
            with self.assertRaises(ValueError): self.wire(credentials=('fixture@pam', 'token', secret))

    def test_PW13_user128_realm128_positive_and_each_neighbor129(self):
        principal = 'u' * 128 + '@' + 'r' * 128
        self.assertIn(principal.encode(), self.wire(credentials=(principal, 'token', 'fictional')))
        for principal in ('u' * 129 + '@r', 'u@' + 'r' * 129):
            with self.assertRaises(ValueError): self.wire(credentials=(principal, 'token', 'fictional'))

    def test_PW14_foreign_transport_refuses_before_attribute_hooks(self):
        class Trap:
            def __getattribute__(self, name): raise AssertionError('transport hook')
        with self.assertRaises(ValueError): self.wire(transport=Trap())

    def test_PW15_maximum_fields_still_bounded_complete_ASCII_request(self):
        credentials = ('u' * 128 + '@' + 'r' * 128, 't' * 128, 's' * 512)
        wire = self.wire(credentials=credentials)
        self.assertLessEqual(len(wire), source.REQUEST_LIMIT)
        self.assertTrue(wire.endswith(b'\r\n\r\n'))
        self.assertEqual(wire.count(b'\r\n'), 6)
        self.assertEqual(wire.decode('ascii').encode('ascii'), wire)

    def test_PW16_repeat_serialization_DATA_never_consumes_or_starts_an_attempt(self):
        begin, record = self.fixture.begin, self.fixture.record
        before = (begin.phase, record._spent, record._retired, record._last_clock,
            record._ticket._remaining, self.plan.end, begin.original.write_end)
        self.assertEqual(self.wire(), self.wire())
        self.assertEqual((begin.phase, record._spent, record._retired, record._last_clock,
            record._ticket._remaining, self.plan.end, begin.original.write_end), before)
