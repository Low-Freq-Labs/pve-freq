"""UNRUN fictional framing/body DATA; patched controls are not native evidence."""
import unittest
from unittest.mock import patch

from freq.services import pilot_guest_profile_response as source


def header(length):
    return (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ' +
            str(length).encode('ascii') + b'\r\n\r\n')


class ProfileResponseData(unittest.TestCase):
    def test_PE01_complete_small_frame_returns_exact_private_body_once(self):
        c = source.ProfileSectionResponseCollector()
        body = b'{"data":{}}'
        c.feed(header(len(body)) + body)
        self.assertEqual(c.finish(), body)
        self.assertTrue(c.spent)
        with self.assertRaises(ValueError): c.finish()

    def test_PE02_split_header_and_body_never_reinterprets_another_header(self):
        c = source.ProfileSectionResponseCollector()
        raw = header(2)
        c.feed(raw[:-1])
        self.assertIsNone(c.body)
        c.feed(raw[-1:] + b'{')
        self.assertEqual(c.next_read_size(), 1)
        c.feed(b'}')
        self.assertEqual(c.finish(), b'{}')

    def test_PE03_exact262144_body_neighbor_is_complete_bounded_DATA(self):
        c = source.ProfileSectionResponseCollector()
        c.feed(header(262144))
        body = b' ' * (262144 - 2) + b'{}'
        for i in range(0, len(body), 8192): c.feed(body[i:i + 8192])
        self.assertEqual(len(c.body), 262144)
        self.assertEqual(c.finish(), body)

    def test_PE04_262145_refuses_before_body_bytearray_constructor(self):
        c = source.ProfileSectionResponseCollector()
        with patch.object(source, 'bytearray', create=True) as allocate:
            with self.assertRaises(ValueError): c.feed(header(262145))
            allocate.assert_not_called()
        self.assertIsNone(c.body)
        self.assertTrue(c.spent)

    def test_PE05_bad_framing_variants_are_terminal_without_body(self):
        variants = [header(0),
            b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n',
            b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n',
            header(2).replace(b'\r\n\r\n', b'\r\nContent-Length: 2\r\n\r\n'),
            header(2).replace(b'\r\n\r\n', b'\r\nTransfer-Encoding: chunked\r\n\r\n'),
            header(2).replace(b'\r\n\r\n', b'\r\nContent-Encoding: gzip\r\n\r\n')]
        for raw in variants:
            c = source.ProfileSectionResponseCollector()
            with self.assertRaises(ValueError): c.feed(raw)
            self.assertTrue(c.spent)
            self.assertIsNone(c.body)
            with self.assertRaises(ValueError): c.feed(header(2))

    def test_PE06_full_header_without_terminator_refuses_before_more_read(self):
        c = source.ProfileSectionResponseCollector()
        for _ in range(source.HEADER_LIMIT // source.CHUNK_LIMIT): c.feed(b'A' * source.CHUNK_LIMIT)
        self.assertEqual(c.header_used, source.HEADER_LIMIT)
        with self.assertRaises(ValueError): c.next_read_size()
        self.assertTrue(c.spent)
        self.assertEqual(len(c.header), source.HEADER_LIMIT)

    def test_PE07_empty_over_chunk_cap_or_nonbytes_feed_is_terminal(self):
        for raw in (b'', b'x' * 16385, bytearray(b'x'), 'x'):
            c = source.ProfileSectionResponseCollector()
            with self.assertRaises(ValueError): c.feed(raw)
            self.assertTrue(c.spent)
            with self.assertRaises(ValueError): c.feed(header(2))

    def test_PE08_extra_body_bytes_are_not_truncated_or_accepted_as_prefix(self):
        c = source.ProfileSectionResponseCollector()
        with self.assertRaises(ValueError): c.feed(header(2) + b'{}extra')
        self.assertTrue(c.spent)
        with self.assertRaises(ValueError): c.finish()

    def test_PE09_incomplete_finish_is_terminal_and_cannot_append(self):
        c = source.ProfileSectionResponseCollector()
        c.feed(header(2) + b'{')
        with self.assertRaises(ValueError): c.finish()
        with self.assertRaises(ValueError): c.feed(b'}')
        self.assertTrue(c.spent)

    def test_PE10_header_parser_control_retains_once_state_and_header_DATA(self):
        c = source.ProfileSectionResponseCollector()
        with patch.object(source, 'content_length', side_effect=KeyboardInterrupt('fictional')):
            with self.assertRaises(KeyboardInterrupt): c.feed(header(2))
        self.assertTrue(c.spent)
        self.assertEqual(bytes(c.header[:c.header_used]), header(2))
        self.assertIsNone(c.body)
        with self.assertRaises(ValueError): c.feed(header(2))

    def test_PE11_body_allocation_failure_retains_terminal_pending_DATA(self):
        c = source.ProfileSectionResponseCollector()
        with patch.object(source, 'bytearray', side_effect=MemoryError('fictional'), create=True):
            with self.assertRaises(MemoryError): c.feed(header(2))
        self.assertTrue(c.spent)
        self.assertIsNone(c.body)
        with self.assertRaises(ValueError): c.finish()

    def test_PE12_finish_copy_control_never_resumes_or_discards_retained_body(self):
        c = source.ProfileSectionResponseCollector()
        c.feed(header(2) + b'{}')
        saved = c.body
        with patch.object(source, 'bytes', side_effect=SystemExit('fictional'), create=True):
            with self.assertRaises(SystemExit): c.finish()
        self.assertTrue(c.spent)
        self.assertIs(c.body, saved)
        with self.assertRaises(ValueError): c.finish()

    def test_PE13_long_header_line_refuses_before_body_allocation(self):
        c = source.ProfileSectionResponseCollector()
        raw = header(2).replace(b'\r\n\r\n', b'\r\nX: ' + b'x' * 8192 + b'\r\n\r\n')
        with self.assertRaises(ValueError): c.feed(raw)
        self.assertTrue(c.spent)
        self.assertIsNone(c.body)

    def test_PE14_non200_and_informational_response_refuse_no_second_status(self):
        for status in (b'HTTP/1.1 401 Denied', b'HTTP/1.1 100 Continue'):
            c = source.ProfileSectionResponseCollector()
            raw = header(2).replace(b'HTTP/1.1 200 OK', status)
            with self.assertRaises(ValueError): c.feed(raw)
            with self.assertRaises(ValueError): c.feed(header(2) + b'{}')

    def test_PE15_read_sizes_shorten_to_exact_remainder_then_zero_before_finish(self):
        c = source.ProfileSectionResponseCollector()
        self.assertEqual(c.next_read_size(), 16384)
        c.feed(header(3) + b'{')
        self.assertEqual(c.next_read_size(), 2)
        c.feed(b' }')
        self.assertEqual(c.next_read_size(), 0)
        self.assertEqual(c.finish(), b'{ }')
        with self.assertRaises(ValueError): c.next_read_size()

    def test_PE16_fixed_refusal_text_excludes_provider_marker_but_not_memory_erasure(self):
        c = source.ProfileSectionResponseCollector()
        raw = header(2).replace(b'200 OK', b'500 provider-marker')
        with self.assertRaises(ValueError) as caught: c.feed(raw)
        self.assertNotIn('provider-marker', str(caught.exception))
        self.assertIn(b'provider-marker', bytes(c.header[:c.header_used]))
