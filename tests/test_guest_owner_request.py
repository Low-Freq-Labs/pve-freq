"""Proposed v2 grammar intentions only, UNRUN until qualified offline run.

No original installation, native owner, HTTP stream or route is constructed.
These exercise pure byte-to-DATA parsing, not original authority or framing.
"""
import json
import unittest

from freq.services.guest_owner_request import Refused, decode_guest_owner_request


C, F, R = 'a' * 64, 'b' * 64, 'c' * 64
PREFIX = '/api/guest-read/v2/'
ROUTES = (
    ('open', 'guest-owner-open', {'schema': 2, 'open_nonce': C}),
    ('sources', 'guest-owner-sources', {'schema': 2, 'owner_ref': F}),
    ('inventory', 'guest-owner-inventory', {'schema': 2, 'owner_ref': F, 'source_ref': R}),
    ('profile', 'guest-owner-profile', {'schema': 2, 'owner_ref': F, 'guest_ref': R}),
    ('retire', 'guest-owner-retire', {'schema': 2, 'open_nonce': C}),
)


def raw(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True).encode('ascii')


class GuestOwnerRequestData(unittest.TestCase):
    def decode(self, value, route='open'):
        return decode_guest_owner_request('POST', PREFIX + route, value)

    def refuse(self, body, route='open'):
        with self.assertRaises(Refused) as caught:
            self.decode(body, route)
        self.assertEqual(str(caught.exception), 'Guest request unavailable')
        self.assertIsNone(caught.exception.__cause__)

    def test_VR01_all_five_literal_shapes_are_only_builtin_DATA(self):
        for route, expected, body in ROUTES:
            with self.subTest(route=route):
                operation, parsed = self.decode(raw(body), route)
                self.assertEqual(operation, expected)
                self.assertIs(type(parsed), dict)
                self.assertEqual(parsed, body)
                self.assertIs(type(parsed['schema']), int)
                self.assertTrue(all(type(v) is str for k, v in parsed.items() if k != 'schema'))

    def test_VR02_plain_lexical_schema_two_only(self):
        for token in (b'1', b'3', b'2.0', b'2e0', b'2E+0', b'-2', b'+2', b'02', b'"2"', b'true', b'false', b'null', b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(token=token):
                self.refuse(b'{"schema":' + token + b',"open_nonce":"' + C.encode() + b'"}')

    def test_VR03_decoded_duplicate_schema_and_nonce_refuse(self):
        for first, second in ((b'schema', b'schema'), (b'schema', br'sch\u0065ma')):
            self.refuse(b'{"' + first + b'":2,"' + second + b'":2,"open_nonce":"' + C.encode() + b'"}')
        for key in (b'open_nonce', br'open_\u006eonce'):
            self.refuse(b'{"schema":2,"open_nonce":"' + C.encode() + b'","' + key + b'":"' + C.encode() + b'"}')

    def test_VR04_duplicate_owner_and_child_refuse_after_unescape(self):
        for route, field in (('inventory', 'source_ref'), ('profile', 'guest_ref')):
            base = raw({'schema': 2, 'owner_ref': F, field: R})[:-1]
            for key in ('owner_ref', field):
                escaped = key.replace('_', r'\u005f')
                self.refuse(base + b',"' + escaped.encode() + b'":"' + R.encode() + b'"}', route)

    def test_VR05_every_missing_and_extra_key_refuses(self):
        for route, _, body in ROUTES:
            for key in body:
                changed = dict(body); del changed[key]
                self.refuse(raw(changed), route)
            for key in ('url', 'node', 'vmid', 'timestamp', 'kind', 'user', 'source_ref', 'guest_ref', 'owner_ref', 'open_nonce'):
                if key not in body:
                    changed = dict(body); changed[key] = C
                    self.refuse(raw(changed), route)

    def test_VR06_nonce_family_child_fields_cannot_substitute(self):
        for route, _, body in ROUTES:
            for field in tuple(k for k in body if k != 'schema'):
                for wrong in ('open_nonce', 'owner_ref', 'source_ref', 'guest_ref'):
                    if wrong != field:
                        changed = dict(body); del changed[field]; changed[wrong] = C
                        self.refuse(raw(changed), route)

    def test_VR07_selector_lengths_case_and_ASCII_neighbors(self):
        for value in ('', 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64, 'a' * 63 + ' ', 'a' * 63 + '\n', 'ａ' * 64):
            for route, _, body in ROUTES:
                for field in (k for k in body if k != 'schema'):
                    changed = dict(body); changed[field] = value
                    self.refuse(raw(changed), route)

    def test_VR08_non_string_selector_types_refuse(self):
        for value in (None, True, False, 2, 2.0, [], {}, [C], {'key': C}):
            for route, _, body in ROUTES:
                for field in (k for k in body if k != 'schema'):
                    changed = dict(body); changed[field] = value
                    self.refuse(raw(changed), route)

    def test_VR09_scalar_array_nested_and_empty_roots_refuse(self):
        for value in (None, True, False, 2, 2.0, C, [], [ROUTES[0][2]], {}, {'schema': {'schema': 2}, 'open_nonce': C}):
            self.refuse(raw(value))

    def test_VR10_one_complete_document_only(self):
        body = raw(ROUTES[0][2])
        for value in (body + b'{}', body + b'null', b'[]' + body, body + b'x', body + b'\x00', body[:-1], body + b','):
            self.refuse(value)
        self.assertEqual(self.decode(b' \r\n\t' + body + b' \r\n\t')[1], ROUTES[0][2])

    def test_VR11_UTF8_BOM_invalid_encodings_and_surrogates_refuse(self):
        body = raw(ROUTES[0][2])
        for value in (b'\xef\xbb\xbf' + body, b'\xff' + body, body[:-2] + b'\xc0\xaf"}', body[:-2] + br'\ud800"}', body[:-2] + br'\udfff"}', body[:-2] + br'\ud800\udfff"}'):
            self.refuse(value)

    def test_VR12_actual_byte_256_bound_and_257_neighbor(self):
        for route, _, body in ROUTES:
            encoded = raw(body)
            exact = encoded + b' ' * (256 - len(encoded))
            self.assertEqual(len(exact), 256)
            self.assertEqual(self.decode(exact, route)[1], body)
            self.refuse(exact + b' ', route)

    def test_VR13_exact_builtin_body_types_only(self):
        class BytesSubclass(bytes):
            pass
        for value in ('{}', bytearray(b'{}'), memoryview(b'{}'), BytesSubclass(raw(ROUTES[0][2])), None, b''):
            with self.assertRaises(Refused):
                self.decode(value)

    def test_VR14_method_neighbors_and_subclasses_refuse(self):
        class MethodSubclass(str):
            pass
        for method in ('GET', 'HEAD', 'PUT', 'post', 'POST ', ' POST', '', MethodSubclass('POST'), None, b'POST'):
            for route, _, body in ROUTES:
                with self.assertRaises(Refused):
                    decode_guest_owner_request(method, PREFIX + route, raw(body))

    def test_VR15_path_neighbors_are_not_normalized(self):
        class PathSubclass(str):
            pass
        for route, _, body in ROUTES:
            path = PREFIX + route
            for value in (path + '/', path + '?x=1', path + '#x', path.upper(), path.replace('/v2/', '/v1/'), path.replace(route, '%' + format(ord(route[0]), '02x') + route[1:]), path + '\x00', PathSubclass(path), None, b'path', 'x' * 65):
                with self.assertRaises(Refused):
                    decode_guest_owner_request('POST', value, raw(body))

    def test_VR16_same_selector_text_stays_distinct_purpose_DATA(self):
        # Shape cannot prove entropy independence or original purpose ownership.
        # Same text is permitted as DATA; actual fixed owner must check tables.
        for route, field in (('inventory', 'source_ref'), ('profile', 'guest_ref')):
            body = {'schema': 2, 'owner_ref': F, field: F}
            self.assertEqual(self.decode(raw(body), route)[1], body)

    def test_VR17_valid_escaped_keys_and_hex_decode_without_authority(self):
        body = br'{"sch\u0065ma":2,"open_\u006eonce":"' + br'\u0061' * 40 + b'a' * 24 + b'"}'
        # Escaped content exceeds byte cap even though decoded leaf is64hex.
        self.refuse(body)
        shorter = br'{"sch\u0065ma":2,"open_nonce":"\u0061' + b'a' * 63 + b'"}'
        self.assertEqual(self.decode(shorter)[1], ROUTES[0][2])

    def test_VR18_fresh_parsed_results_cannot_rewrite_future_decode(self):
        encoded = raw(ROUTES[0][2])
        first = self.decode(encoded)[1]
        first['open_nonce'] = R
        first['schema'] = 1
        self.assertEqual(self.decode(encoded)[1], ROUTES[0][2])

    def test_VR19_source_profile_minimum_two_selectors_are_required(self):
        for route, field in (('inventory', 'source_ref'), ('profile', 'guest_ref')):
            for body in ({'schema': 2, field: R}, {'schema': 2, 'owner_ref': F}):
                self.refuse(raw(body), route)

    def test_VR20_original_v1_payloads_are_not_v2(self):
        for route, _, body in ROUTES:
            changed = dict(body); changed['schema'] = 1
            self.refuse(raw(changed), route)
        self.refuse(b'', 'sources')
