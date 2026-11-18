"""Finite fictional framing witnesses, not network qualification."""
import unittest

from freq.services import node_read_framing as framing


def headers(length=b"2", extra=b"", status=b"HTTP/1.1 200 OK", media=b"application/json"):
    return (status + b"\r\nContent-Length: " + length + b"\r\nContent-Type: "
            + media + b"\r\n" + extra + b"\r\n")


class FramingCases(unittest.TestCase):
    def refuse(self, block):
        with self.assertRaises(ValueError) as caught:
            framing.content_length(block)
        self.assertEqual(str(caught.exception), "node read framing unavailable")

    def test_valid_versions_and_media(self):
        for version in (b"HTTP/1.0 200 OK", b"HTTP/1.1 200 "):
            for media in (b"application/json", b"Application/JSON; charset=utf-8"):
                self.assertEqual(framing.content_length(headers(status=version, media=media)), 2)

    def test_length_boundaries(self):
        self.assertEqual(framing.content_length(headers(b"1")), 1)
        self.assertEqual(framing.content_length(headers(b"1048608")), 1048608)
        for value in (b"0", b"01", b"+2", b"-2", b"2,2", b"2 2", b"1048609", b"99999999"):
            self.refuse(headers(value))

    def test_critical_duplicates_and_encoding(self):
        for extra in (b"content-length: 2\r\n", b"CONTENT-TYPE: application/json\r\n",
                      b"Transfer-Encoding: chunked\r\n", b"Content-Encoding: identity\r\n"):
            self.refuse(headers(extra=extra))

    def test_header_syntax(self):
        for extra in (b" folded: x\r\n", b"missing-colon\r\n", b"Bad Name: x\r\n",
                      b"X: \x00\r\n", b"X: \xff\r\n", b"X: bare\nline\r\n"):
            self.refuse(headers(extra=extra))

    def test_status_refusals(self):
        for status in (b"HTTP/1.1 100 Continue", b"HTTP/1.1 301 Moved", b"HTTP/2 200 OK",
                       b"HTTP/1.1 200", b"HTTP/1.1 200 \x00"):
            self.refuse(headers(status=status))

    def test_status_line_limit(self):
        prefix = b"HTTP/1.1 200 "
        status = prefix + b"x" * (4096 - 2 - len(prefix))
        self.assertEqual(framing.content_length(headers(status=status)), 2)
        self.refuse(headers(status=status + b"x"))

    def test_header_line_limit(self):
        line = b"X: " + b"x" * (8192 - 5) + b"\r\n"
        self.assertEqual(len(line), 8192)
        self.assertEqual(framing.content_length(headers(extra=line)), 2)
        self.refuse(headers(extra=line[:-2] + b"x\r\n"))

    def test_count_limit(self):
        # Two critical fields plus62 other bounded fields.
        self.assertEqual(framing.content_length(headers(extra=b"X: y\r\n" * 62)), 2)
        self.refuse(headers(extra=b"X: y\r\n" * 63))

    def test_total_limit(self):
        # Four padding headers keep individual lines below8192.
        budget = 32768 - len(headers())
        sizes = [8192, 8192, 8192, budget - 3 * 8192]
        extra = b"".join(b"X: " + b"x" * (size - 5) + b"\r\n" for size in sizes)
        block = headers(extra=extra)
        self.assertEqual(len(block), 32768)
        self.assertEqual(framing.content_length(block), 2)
        self.refuse(block[:-4] + b"x" + block[-4:])

    def test_exact_block_only(self):
        class Bytes(bytes):
            pass

        for block in (Bytes(headers()), bytearray(headers()), headers() + b"[]", b"\r\n\r\n",
                      b"HTTP/1.1 200 OK\r\n\r\n", headers()[:-1]):
            self.refuse(block)


if __name__ == "__main__":
    unittest.main()
