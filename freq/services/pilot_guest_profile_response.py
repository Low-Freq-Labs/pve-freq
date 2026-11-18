"""Bounded private section body DATA, no socket, JSON or response grant.

Actual original parent must preown aggregate header/body/scratch/retainedcopy
and native duties before construction/feed/finish. Logical byte limits do not
prove physical heap/RSS or whole-job enforcement. Returned bytes remain private.
"""
from freq.services.cluster_observation_framing import HEADER_LIMIT, content_length


BODY_LIMIT = 262144
CHUNK_LIMIT = 16384


def _refuse():
    raise ValueError('Guest profile section response unavailable')


class ProfileSectionResponseCollector:
    """Once failure is terminal, including parser/allocation/control failure.

    This class owns only supplied private byte DATA. No supplied collector,
    full body or valid framing proves original source/result/native authority.
    Native caller must separately retain this SAME collector before IO.
    """
    __slots__ = ('header', 'header_used', 'body', 'body_used', 'spent')

    def __init__(self):
        self.header = bytearray(HEADER_LIMIT)
        self.header_used, self.body, self.body_used, self.spent = 0, None, 0, False

    def feed(self, chunk):
        if self.spent:
            _refuse()
        self.spent = True  # BEFORE validation, parsing or fallible mutation.
        if type(chunk) is not bytes or not 1 <= len(chunk) <= CHUNK_LIMIT:
            _refuse()
        offset = 0
        if self.body is None:
            while offset < len(chunk):
                if self.header_used == HEADER_LIMIT:
                    _refuse()
                self.header[self.header_used] = chunk[offset]
                self.header_used += 1
                offset += 1
                n = self.header_used
                if (n >= 4 and self.header[n - 4] == 13 and self.header[n - 3] == 10
                        and self.header[n - 2] == 13 and self.header[n - 1] == 10):
                    size = content_length(bytes(memoryview(self.header)[:n]))
                    # Existing strict fixed framing accepts a larger Cluster
                    # body. The section cap MUST precede body bytearray growth.
                    if type(size) is not int or not 1 <= size <= BODY_LIMIT:
                        _refuse()
                    self.body = bytearray(size)
                    break
        if self.body is not None:
            count = len(chunk) - offset
            if count > len(self.body) - self.body_used:
                _refuse()
            end = self.body_used + count
            self.body[self.body_used:end] = memoryview(chunk)[offset:]
            self.body_used = end
        self.spent = False  # Only a completely returned successful feed resumes.

    def next_read_size(self):
        if self.spent:
            _refuse()
        if self.body is None:
            remaining = HEADER_LIMIT - self.header_used
            if remaining <= 0:
                self.spent = True
                _refuse()
            return min(CHUNK_LIMIT, remaining)
        return min(CHUNK_LIMIT, len(self.body) - self.body_used)

    def finish(self):
        if self.spent:
            _refuse()
        self.spent = True  # BEFORE complete body check and immutable copy.
        if self.body is None or self.body_used != len(self.body):
            _refuse()
        return bytes(self.body)


# No credential/trust/native/clock/decoder/formatter/frame/store/dispatch APIs.
