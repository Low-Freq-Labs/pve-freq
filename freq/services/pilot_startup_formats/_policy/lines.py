"""Pure supplied-byte line front end; not a policy decoder or original reader."""


class InvalidDocument(ValueError):
    pass


def _reject():
    raise InvalidDocument("Policy document unavailable")


def _preflight(documents):
    """Validate both byte inputs before any line is returned.

    Physical line bytes include their LF or CRLF terminator. A final nonempty
    unterminated segment counts as a line; a terminal LF adds no phantom line.
    Empty input has zero lines. This conservative counting needs schema review.
    """
    if any(type(raw) is not bytes for raw in documents):
        _reject()
    if any(len(raw) > 1048576 for raw in documents):
        _reject()
    if sum(len(raw) for raw in documents) > 2097152:
        _reject()
    count = 0
    for raw in documents:
        if raw.startswith(b"\xef\xbb\xbf"):
            _reject()
        start = 0
        for index, byte in enumerate(raw):
            if byte == 13:
                if index + 1 == len(raw) or raw[index + 1] != 10:
                    _reject()
            elif byte < 32 and byte not in (9, 10):
                _reject()
            elif byte == 127:
                _reject()
            # Check extent before copying any segment or decoding the input.
            if index - start + 1 > 65536:
                _reject()
            if byte == 10:
                count += 1
                if count > 16384:
                    _reject()
                start = index + 1
        if start < len(raw):
            count += 1
            if count > 16384:
                _reject()
        try:
            # At most one bounded temporary decoded document, discarded here.
            # Strict UTF-8 also rejects encoded surrogate scalar values.
            raw.decode("utf-8", "strict")
        except UnicodeDecodeError:
            _reject()


def _lines(documents):
    for document_index, raw in enumerate(documents):
        start = 0
        number = 0
        while start < len(raw):
            newline = raw.find(b"\n", start)
            end = len(raw) if newline < 0 else newline
            content_end = end
            if newline >= 0 and end > start and raw[end - 1] == 13:
                content_end -= 1
            number += 1
            yield document_index, number, raw[start:content_end].decode("utf-8")
            start = len(raw) if newline < 0 else newline + 1


def supplied_lines(hosts, fleet):
    """Return an iterator only after both immutable byte inputs pass preflight.

    Returned lines are untrusted syntax. Complete grammar/schema validation and
    policy composition must finish before any positive result is published.
    No timing, original file ownership, or interpreter memory qualification.
    """
    documents = (hosts, fleet)
    _preflight(documents)
    return _lines(documents)
