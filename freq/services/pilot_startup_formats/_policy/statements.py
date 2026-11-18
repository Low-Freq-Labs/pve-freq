"""One complete restricted statement; no document-state or policy admission."""
from .lines import InvalidDocument
from .values import Counters, key, value


def _reject():
    raise InvalidDocument("Policy document unavailable")


def _space(text, pos):
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return pos


def _tail(text, pos):
    pos = _space(text, pos)
    if pos < len(text) and text[pos] != "#":
        _reject()


def statement(text, document, counters):
    """Return None, ('header', path), or ('assignment', key, value).

    document=0 is hosts, document=1 is fleet. Headers use compact bracket/key
    syntax, without internal whitespace. Leading/trailing space and comments
    are allowed. This explicit restricted-header detail requires source review.
    Caller supplies preflighted lines and one exclusive pair-wide Counters.
    """
    if (type(text) is not str or len(text) > 65536
            or type(document) is not int or document not in (0, 1)
            or type(counters) is not Counters):
        _reject()
    pos = _space(text, 0)
    if pos == len(text) or text[pos] == "#":
        return None
    if text[pos] == "[":
        counters.declaration()
        array = text.startswith("[[", pos)
        pos += 2 if array else 1
        first, pos = key(text, pos, counters)
        path = (first,)
        if pos < len(text) and text[pos] == ".":
            second, pos = key(text, pos + 1, counters)
            path = (first, second)
        closer = "]]" if array else "]"
        if not text.startswith(closer, pos):
            _reject()
        pos += len(closer)
        _tail(text, pos)
        if document == 0:
            if not array or path != ("host",):
                _reject()
        elif array or not (
                path == ("tiers",)
                or path in (("physical",), ("pve_nodes",))
                or len(path) == 2 and path[0] in ("categories", "physical", "pve_nodes")):
            _reject()
        return "header", path
    counters.assignment()
    name, pos = key(text, pos, counters)
    pos = _space(text, pos)
    if pos == len(text) or text[pos] != "=":
        _reject()
    pos = _space(text, pos + 1)
    item, pos = value(text, pos, counters)
    _tail(text, pos)
    return "assignment", name, item
