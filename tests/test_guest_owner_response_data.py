"""UNRUN immutable frame DATA only; no broker or server is constructed."""
import json
import unittest

from freq.services.cluster_pilot_http import OriginalPilotResponse, _RequestUnavailable
from freq.services.guest_owner_response import (
    Refused, format_owner_open_data, format_owner_retired_data,
    format_owner_unavailable_data,
)


REF = 'a' * 64
STAMP = '2026-10-24T09:00:00.123Z'


def parts(frame):
    headers, body = frame._wire.split(b'\r\n\r\n', 1)
    return headers, body, json.loads(body)


class GuestOwnerResponseData(unittest.TestCase):
    def test_RF01_open_shape_and_exact_charset_no_store(self):
        frame = format_owner_open_data(REF, STAMP)
        self.assertIs(type(frame), OriginalPilotResponse)
        headers, body, value = parts(frame)
        self.assertTrue(headers.startswith(b'HTTP/1.1 200 OK\r\n'))
        self.assertIn(b'\r\nContent-Type: application/json; charset=utf-8\r\n', headers)
        self.assertIn(b'\r\nCache-Control: no-store\r\n', headers)
        self.assertIn(b'\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n', headers)
        self.assertNotIn(b'Set-Cookie:', headers)
        self.assertEqual(value, {'schema': 2, 'kind': 'guest-owner', 'owner_ref': REF, 'completed_at': STAMP})

    def test_RF02_retire_shape_is_only_unretained_nonce_DATA(self):
        headers, _, value = parts(format_owner_retired_data(REF))
        self.assertTrue(headers.startswith(b'HTTP/1.1 200 OK\r\n'))
        self.assertEqual(value, {'schema': 2, 'kind': 'guest-owner-retired', 'open_nonce': REF})
        self.assertNotIn('owner_ref', value)
        self.assertNotIn('confirmed', value)

    def test_RF03_fixed_unavailable_has_no_native_details(self):
        headers, _, value = parts(format_owner_unavailable_data())
        self.assertTrue(headers.startswith(b'HTTP/1.1 503 Service Unavailable\r\n'))
        self.assertEqual(value, {'schema': 2, 'kind': 'guest-unavailable'})

    def test_RF04_selector_shapes_and_types_refuse(self):
        for value in (None, True, 2, b'a' * 64, '', 'a' * 63, 'a' * 65,
                      'A' * 64, 'g' * 64, 'a' * 63 + '\n', 'ａ' * 64):
            for formatter in (lambda: format_owner_open_data(value, STAMP),
                              lambda: format_owner_retired_data(value)):
                with self.assertRaises(Refused) as caught:
                    formatter()
                self.assertEqual(str(caught.exception), 'Guest response unavailable')
                self.assertIsNone(caught.exception.__cause__)

    def test_RF05_canonical_calendar_stamps_are_display_DATA(self):
        for stamp in ('2000-02-29T00:00:00.000Z', '0001-01-01T00:00:00.000Z',
                      '9999-12-31T23:59:59.999Z'):
            self.assertEqual(parts(format_owner_open_data(REF, stamp))[2]['completed_at'], stamp)

    def test_RF06_invalid_calendar_or_precision_never_normalizes(self):
        for stamp in ('1900-02-29T00:00:00.000Z', '2026-02-29T00:00:00.000Z',
                      '0000-01-01T00:00:00.000Z', '2026-13-01T00:00:00.000Z',
                      '2026-10-24T24:00:00.000Z', '2026-10-24T00:00:60.000Z',
                      '2026-10-24T09:00:00.12Z', '2026-10-24T09:00:00.1230Z',
                      '2026-10-24T09:00:00.123+00:00', '2026-10-24t09:00:00.123z',
                      STAMP + ' ', ' ' + STAMP, STAMP.replace('.', 'x')):
            with self.assertRaises(Refused):
                format_owner_open_data(REF, stamp)

    def test_RF07_nonbuiltin_stamp_and_selector_subclasses_refuse(self):
        class Text(str):
            pass
        for selector, stamp in ((Text(REF), STAMP), (REF, Text(STAMP)),
                                (REF, None), (REF, STAMP.encode())):
            with self.assertRaises(Refused):
                format_owner_open_data(selector, stamp)
        with self.assertRaises(Refused):
            format_owner_retired_data(Text(REF))

    def test_RF08_identical_text_does_not_merge_nonce_and_family_purposes(self):
        opened = parts(format_owner_open_data(REF, STAMP))[2]
        retired = parts(format_owner_retired_data(REF))[2]
        self.assertEqual(opened['owner_ref'], retired['open_nonce'])
        self.assertNotEqual(opened['kind'], retired['kind'])
        self.assertNotIn('open_nonce', opened)
        self.assertNotIn('owner_ref', retired)

    def test_RF09_schema_is_builtin_integer_two_only_in_fixed_shapes(self):
        for frame in (format_owner_open_data(REF, STAMP),
                      format_owner_retired_data(REF), format_owner_unavailable_data()):
            schema = parts(frame)[2]['schema']
            self.assertIs(type(schema), int)
            self.assertEqual(schema, 2)

    def test_RF10_frame_bytes_are_immutable(self):
        frame = format_owner_retired_data(REF)
        before = frame._wire
        with self.assertRaises(TypeError):
            frame._wire = b'changed'
        with self.assertRaises(TypeError):
            del frame._wire
        self.assertEqual(frame._wire, before)

    def test_RF11_existing_JSON_and_static_mimes_unchanged(self):
        for mime in ('application/json', 'application/javascript', 'text/css', 'text/html; charset=utf-8'):
            frame = OriginalPilotResponse(200, b'fixture', mime)
            self.assertIn(b'Content-Type: ' + mime.encode() + b'\r\n', frame._wire)
        for mime in ('application/json;charset=utf-8', 'application/json; charset=latin1',
                     'application/json; charset=utf-8\r\nInjected: yes'):
            with self.assertRaises(_RequestUnavailable):
                OriginalPilotResponse(200, b'fixture', mime)

    def test_RF12_fixed_bodies_count_new_keys_inside_guest_wire_budgets(self):
        for frame in (format_owner_open_data(REF, STAMP),
                      format_owner_retired_data(REF), format_owner_unavailable_data()):
            _, body, value = parts(frame)
            strings = sum(len(key.encode()) for key in value)
            strings += sum(len(item.encode()) for item in value.values() if type(item) is str)
            self.assertLessEqual(len(body), 131072)
            self.assertLessEqual(strings, 65536)
            self.assertLess(len(body), 256)  # Fixed three shapes, not arbitrary profile DATA.
            self.assertNotIn(b'\\u', body)
