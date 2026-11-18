"""Bounded, unwired native Cluster HTTP body assembly.

No parsing of JSON or admission to a session occurs here. The caller must
reserve body, header and scratch allowances before constructing the collector.
"""
from .cluster_observation_framing import HEADER_LIMIT, content_length


def _refuse():
    raise ValueError("cluster response unavailable")


class ResponseCollector:
    __slots__ = ("header", "header_used", "body", "body_used", "spent")

    def __init__(self):
        self.header = bytearray(HEADER_LIMIT)
        self.header_used = 0
        self.body = None
        self.body_used = 0
        self.spent = False

    def feed(self, chunk):
        if self.spent or type(chunk) is not bytes or not 1 <= len(chunk) <= 16384:
            _refuse()
        offset = 0
        if self.body is None:
            while offset < len(chunk):
                if self.header_used == HEADER_LIMIT:
                    self.spent = True
                    _refuse()
                self.header[self.header_used] = chunk[offset]
                self.header_used += 1
                offset += 1
                n = self.header_used
                if (n >= 4 and self.header[n - 4] == 13
                        and self.header[n - 3] == 10
                        and self.header[n - 2] == 13
                        and self.header[n - 1] == 10):
                    # Consume before fallible parsing/allocation. Failure cannot
                    # resume this collector or reinterpret a different header.
                    self.spent = True
                    size = content_length(bytes(memoryview(self.header)[:n]))
                    self.body = bytearray(size)
                    self.spent = False
                    break
        if self.body is not None:
            count = len(chunk) - offset
            if count > len(self.body) - self.body_used:
                self.spent = True
                _refuse()
            end = self.body_used + count
            self.body[self.body_used:end] = memoryview(chunk)[offset:]
            self.body_used = end

    def next_read_size(self):
        if self.spent:
            _refuse()
        if self.body is None:
            return 16384
        return min(16384, len(self.body) - self.body_used)

    def finish(self):
        if self.spent:
            _refuse()
        self.spent = True
        if self.body is None or self.body_used != len(self.body):
            _refuse()
        return bytes(self.body)
