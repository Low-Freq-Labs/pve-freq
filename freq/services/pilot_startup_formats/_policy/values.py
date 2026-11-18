"""Partial key/container grammar, without document or policy admission."""
from .lines import InvalidDocument
from .scalars import Budget, scalar


def _reject():
    raise InvalidDocument("Policy document unavailable")


class Counters:
    """Exclusive internal accounting shared across both documents."""
    __slots__ = ("scalars", "assignments", "tables")

    def __init__(self):
        self.scalars = Budget()
        self.assignments = 0
        self.tables = 0

    def assignment(self):
        if self.assignments >= 8192:
            _reject()
        self.assignments += 1

    def declaration(self):
        if self.tables >= 1024:
            _reject()
        self.tables += 1


def _check(text, pos, counters):
    if (type(text) is not str or len(text) > 65536 or type(pos) is not int
            or not 0 <= pos < len(text) or type(counters) is not Counters):
        _reject()


def _space(text, pos):
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return pos


def key(text, pos, counters):
    _check(text, pos, counters)
    start = pos
    while pos < len(text):
        c = text[pos]
        if not ("A" <= c <= "Z" or "a" <= c <= "z"
                or "0" <= c <= "9" or c in "_-"):
            break
        if pos - start >= 64:
            _reject()
        counters.scalars.character()
        pos += 1
    if start == pos:
        _reject()
    return text[start:pos], pos


def _finish(text, pos, result):
    if pos < len(text) and text[pos] not in " \t#,]}":
        _reject()
    return result, pos


def value(text, pos, counters):
    """Parse one bounded scalar, flat array or flat inline table.

    Caller charges the containing assignment separately, requires complete
    statement syntax, and discards all state after any failed parse.
    """
    _check(text, pos, counters)
    if text[pos] == "[":
        pos = _space(text, pos + 1)
        result = []
        kind = None
        if pos < len(text) and text[pos] == "]":
            return _finish(text, pos + 1, result)
        while True:
            if len(result) >= 512:
                _reject()
            item, pos = scalar(text, pos, counters.scalars)
            if kind is None:
                kind = type(item)
            elif type(item) is not kind:
                _reject()
            result.append(item)
            pos = _space(text, pos)
            if pos >= len(text):
                _reject()
            if text[pos] == "]":
                return _finish(text, pos + 1, result)
            if text[pos] != ",":
                _reject()
            pos = _space(text, pos + 1)
            if pos < len(text) and text[pos] == "]":
                return _finish(text, pos + 1, result)
    if text[pos] == "{":
        pos = _space(text, pos + 1)
        result = {}
        if pos < len(text) and text[pos] == "}":
            return _finish(text, pos + 1, result)
        while True:
            if len(result) >= 16:
                _reject()
            counters.assignment()
            name, pos = key(text, pos, counters)
            if name in result:
                _reject()
            pos = _space(text, pos)
            if pos >= len(text) or text[pos] != "=":
                _reject()
            pos = _space(text, pos + 1)
            item, pos = scalar(text, pos, counters.scalars)
            result[name] = item
            pos = _space(text, pos)
            if pos >= len(text):
                _reject()
            if text[pos] == "}":
                return _finish(text, pos + 1, result)
            if text[pos] != ",":
                _reject()
            pos = _space(text, pos + 1)
            # No trailing comma in the restricted inline-table grammar.
            if pos >= len(text) or text[pos] == "}":
                _reject()
    return scalar(text, pos, counters.scalars)
