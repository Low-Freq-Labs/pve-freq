"""Supplied bytes only. Does not acquire a provider or issue capture authority."""
from dataclasses import dataclass
from hashlib import sha256
from . import network_list

MAX_ENVELOPE = 1048608
MAX_ARRAY = 1048576
MAX_ARRAY_DEPTH = 4  # exact pinned network_list._scan limit; wrapper total is five
REFUSED = object()
_WS = b' \t\r\n'


@dataclass(frozen=True, slots=True)
class EnvelopeSlice:
    envelope: bytes
    start: int
    end: int
    envelope_sha256: str
    rows_raw: bytes
    rows_sha256: str
    byte_count: int


def _space(raw, i):
    while i < len(raw) and raw[i] in _WS:
        i += 1
    return i


def _span(raw):
    i = _space(raw, 0)
    if raw[i:i+1] != b'{':
        raise ValueError
    i = _space(raw, i + 1)
    if raw[i:i+6] != b'"data"':
        raise ValueError
    i = _space(raw, i + 6)
    if raw[i:i+1] != b':':
        raise ValueError
    i = _space(raw, i + 1)
    if raw[i:i+1] != b'[':
        raise ValueError
    start = i
    stack = []
    quoted = escaped = False
    while i < len(raw):
        c = raw[i]
        if quoted:
            if c < 32:
                raise ValueError
            if escaped:
                escaped = False
            elif c == 92:
                escaped = True
            elif c == 34:
                quoted = False
        elif c == 34:
            quoted = True
        elif c in (91, 123):
            if len(stack) == MAX_ARRAY_DEPTH:
                raise ValueError
            stack.append(c)
        elif c in (93, 125):
            expected = 91 if c == 93 else 123
            if not stack or stack.pop() != expected:
                raise ValueError
            if not stack:
                end = i + 1
                if end - start > MAX_ARRAY:
                    raise ValueError
                i = _space(raw, end)
                if raw[i:i+1] != b'}' or _space(raw, i + 1) != len(raw):
                    raise ValueError
                return start, end
        i += 1
    raise ValueError


def decode_envelope(scope, raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_ENVELOPE:
        return REFUSED
    try:
        # Whole-envelope UTF8 is checked, including bytes outside the row span.
        raw.decode('utf-8', 'strict')
        start, end = _span(raw)
        rows = raw[start:end]
        document = network_list.decode_list(scope, rows)
        if type(document) is not network_list.ListDocument:
            return REFUSED
        digest = sha256(rows).hexdigest()
        if document.scope is not scope or document.byte_count != len(rows) or document.raw_sha256 != digest:
            return REFUSED
        return EnvelopeSlice(raw, start, end, sha256(raw).hexdigest(), rows, digest, len(rows))
    except Exception:
        return REFUSED
