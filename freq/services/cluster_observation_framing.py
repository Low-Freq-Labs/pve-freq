"""Dedicated fixed Cluster response framing; no socket or generic HTTP parser.

The eventual transport must bound incremental retention before calling this
parser. This function accepts the complete header block only, not body bytes.
"""
import re


HEADER_LIMIT = 32768
LINE_LIMIT = 8192
STATUS_LIMIT = 4096
HEADER_COUNT = 64
BODY_LIMIT = 1048576
_TOKEN = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def _refuse():
    raise ValueError("cluster read framing unavailable")


def content_length(header_block):
    """Return a bounded body length, or raise a fixed ordinary error.

    No decoded response fields or provider text leave this boundary. Retained
    exception frames can still contain inputs; this is not an erasure claim.
    """
    if type(header_block) is not bytes or not 4 <= len(header_block) <= HEADER_LIMIT:
        _refuse()
    if not header_block.endswith(b"\r\n\r\n"):
        _refuse()
    lines = header_block[:-4].split(b"\r\n")
    if not lines or len(lines) - 1 > HEADER_COUNT:
        _refuse()
    status = lines[0]
    if len(status) + 2 > STATUS_LIMIT:
        _refuse()
    # Deliberately narrow response profile; no informational response loop.
    if re.fullmatch(rb"HTTP/1\.[01] 200 [\x20-\x7e]*", status) is None:
        _refuse()
    length = None
    media = None
    for line in lines[1:]:
        if not line or len(line) + 2 > LINE_LIMIT:
            _refuse()
        name, separator, value = line.partition(b":")
        if not separator or _TOKEN.fullmatch(name) is None:
            _refuse()
        # No folded fields, controls except horizontal whitespace, or obs-text.
        if any(b != 9 and not 32 <= b <= 126 for b in value):
            _refuse()
        name = name.lower()
        value = value.strip(b" \t")
        if name in (b"transfer-encoding", b"content-encoding"):
            _refuse()
        if name == b"content-length":
            if length is not None or re.fullmatch(rb"[1-9][0-9]{0,6}", value) is None:
                _refuse()
            length = int(value)
            if length > BODY_LIMIT:
                _refuse()
        elif name == b"content-type":
            if media is not None:
                _refuse()
            media = value.lower()
            if re.fullmatch(rb"application/json(?:[ \t]*;[ \t]*charset=utf-8)?", media) is None:
                _refuse()
    if length is None or media is None:
        _refuse()
    return length
