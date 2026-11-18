"""Prepared source fixtures only; execution requires runtime qualification."""
import unittest

from freq.services.node_read_response import ResponseCollector


HEADER = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n"


class ResponseTests(unittest.TestCase):
    def test_each_delimiter_split(self):
        for split in range(len(HEADER) - 4, len(HEADER) + 1):
            owner = ResponseCollector()
            owner.feed(HEADER[:split])
            owner.feed((HEADER + b"[]")[split:])
            self.assertEqual(owner.finish(), b"[]")

    def test_one_byte_fragments(self):
        owner = ResponseCollector()
        for value in HEADER + b"[]":
            owner.feed(bytes((value,)))
        self.assertEqual(owner.next_read_size(), 0)
        self.assertEqual(owner.finish(), b"[]")

    def test_short_body_cannot_finish(self):
        owner = ResponseCollector()
        owner.feed(HEADER + b"[")
        self.assertEqual(owner.next_read_size(), 1)
        with self.assertRaises(ValueError):
            owner.finish()

    def test_overrun_permanently_refuses(self):
        owner = ResponseCollector()
        with self.assertRaises(ValueError):
            owner.feed(HEADER + b"[]x")
        with self.assertRaises(ValueError):
            owner.finish()

    def test_finished_collector_cannot_be_reused(self):
        owner = ResponseCollector()
        owner.feed(HEADER + b"[]")
        self.assertEqual(owner.finish(), b"[]")
        with self.assertRaises(ValueError):
            owner.feed(b"x")
        with self.assertRaises(ValueError):
            owner.finish()

    def test_header_capacity_has_no_growth(self):
        owner = ResponseCollector()
        owner.feed(b"x" * 16384)
        owner.feed(b"x" * 16384)
        self.assertEqual(len(owner.header), 32768)
        with self.assertRaises(ValueError):
            owner.feed(b"x")
        self.assertEqual(len(owner.header), 32768)

    def test_invalid_header_cannot_resume(self):
        owner = ResponseCollector()
        with self.assertRaises(ValueError):
            owner.feed(HEADER.replace(b"200", b"302"))
        with self.assertRaises(ValueError):
            owner.feed(b"[]")

    def test_input_chunk_bounds(self):
        class BytesSubclass(bytes):
            pass
        for value in (b"", b"x" * 16385, bytearray(b"x"), BytesSubclass(b"x")):
            with self.assertRaises(ValueError):
                ResponseCollector().feed(value)
