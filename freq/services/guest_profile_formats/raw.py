"""Disabled supplied raw-resource decoder; no original acquisition or observation.

Only complete native bytes enter this fixed grammar. No provider, configuration,
stream, deadline, cleanup, generation or route authority follows from decoding.
Unknown scalar metadata is validated and charged before discard. Numbers retain
bounded lexemes until a selected field explicitly interprets them.
"""

import json
import math
from collections import namedtuple

_Number = namedtuple("_Number", "lexeme")
_SELECTED = frozenset(("vmid", "type", "node", "template", "name", "status",
                       "maxcpu", "cpu", "maxmem", "mem", "tags"))


class InvalidRaw(ValueError):
    pass


def _reject():
    raise InvalidRaw("VM List supplied resource sample unavailable")


def _numeric_grammar(token):
    """Standard JSON number, with no conversion or unbounded exponent parsing."""
    size = len(token)
    pos = 0
    if pos < size and token[pos] == "-":
        pos += 1
    if pos == size:
        _reject()
    if token[pos] == "0":
        pos += 1
    elif "1" <= token[pos] <= "9":
        pos += 1
        while pos < size and "0" <= token[pos] <= "9":
            pos += 1
    else:
        _reject()
    if pos < size and token[pos] == ".":
        pos += 1
        start = pos
        while pos < size and "0" <= token[pos] <= "9":
            pos += 1
        if pos == start:
            _reject()
    if pos < size and token[pos] in "eE":
        pos += 1
        if pos < size and token[pos] in "+-":
            pos += 1
        start = pos
        while pos < size and "0" <= token[pos] <= "9":
            pos += 1
        if pos == start:
            _reject()
    if pos != size:
        _reject()


class _Cursor:
    def __init__(self, raw):
        if type(raw) is not bytes or not 1 <= len(raw) <= 1048576:
            _reject()
        if raw.startswith(b"\xef\xbb\xbf"):
            _reject()
        try:
            self.text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError:
            _reject()
        self.pos = self.keys = self.values = self.characters = 0

    def space(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def peek(self, char):
        self.space()
        return self.pos < len(self.text) and self.text[self.pos] == char

    def punctuation(self, char):
        if not self.peek(char):
            _reject()
        self.pos += 1

    def boundary(self):
        if self.pos < len(self.text) and self.text[self.pos] not in " \t\r\n,]}":
            _reject()

    def reserve_value(self):
        if self.values >= 262144:
            _reject()
        self.values += 1

    def string(self, maximum, key=False):
        if key:
            if self.keys >= 262145:
                _reject()
            self.keys += 1
        else:
            self.reserve_value()
        self.space()
        start = self.pos
        if start == len(self.text) or self.text[start] != '"':
            _reject()
        self.pos += 1
        escaped = False
        while self.pos < len(self.text):
            # At most12 source characters per escaped Unicode scalar plus quotes.
            if self.pos - start + 1 > 12 * maximum + 2:
                _reject()
            char = self.text[self.pos]
            self.pos += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                # Only one bounded string token enters the standard decoder.
                try:
                    value = json.loads(self.text[start:self.pos])
                except (ValueError, TypeError):
                    _reject()
                if type(value) is not str or len(value) > maximum:
                    _reject()
                if self.characters + len(value) > 524288:
                    _reject()
                for item in value:
                    if 0xD800 <= ord(item) <= 0xDFFF:
                        _reject()
                self.characters += len(value)
                return value
        _reject()

    def scalar(self):
        if self.peek('"'):
            return self.string(4096)
        self.reserve_value()
        self.space()
        start = self.pos
        for spelling, value in (("true", True), ("false", False), ("null", None)):
            if self.text.startswith(spelling, start):
                self.pos += len(spelling)
                self.boundary()
                return value
        # Nested arrays/objects and non-ASCII numeric spellings cannot match.
        while self.pos < len(self.text) and self.text[self.pos] not in " \t\r\n,]}":
            if self.pos - start >= 64:
                _reject()
            self.pos += 1
        if self.pos == start:
            _reject()
        token = self.text[start:self.pos]
        _numeric_grammar(token)
        return _Number(token)


def _row(cursor):
    cursor.punctuation("{")
    seen = set()
    selected = []
    if cursor.peek("}"):
        cursor.punctuation("}")
        return ()
    while True:
        if len(seen) >= 64:
            _reject()
        key = cursor.string(64, key=True)
        if not key or key in seen:
            _reject()
        seen.add(key)
        cursor.punctuation(":")
        item = cursor.scalar()
        if key in _SELECTED:
            selected.append((key, item))
        if cursor.peek("}"):
            cursor.punctuation("}")
            return tuple(selected)
        cursor.punctuation(",")


def decode_rows(raw):
    """Return ordered immutable selected row pairs after whole wire validation.

    Depth is exactly bounded by the fixed root-object/array/row-object grammar.
    Row partition, selected string control checks, tags and observations belong
    to a separate projector. Malformed/profile excess returns no provisional rows.
    """
    cursor = _Cursor(raw)
    cursor.punctuation("{")
    if cursor.string(64, key=True) != "data":
        _reject()
    cursor.punctuation(":")
    cursor.punctuation("[")
    rows = []
    if not cursor.peek("]"):
        while True:
            if len(rows) >= 4096:
                _reject()
            rows.append(_row(cursor))
            if cursor.peek("]"):
                break
            cursor.punctuation(",")
    cursor.punctuation("]")
    cursor.punctuation("}")
    cursor.space()
    if cursor.pos != len(cursor.text):
        _reject()
    return tuple(rows)


def canonical_integer(token, allow_zero=False):
    """Selected token domain only; bool/float/native int are not numeric tokens."""
    if type(token) is not _Number or type(allow_zero) is not bool:
        return None
    text = token.lexeme
    if (type(text) is not str or not text or len(text) > 16 or any(not "0" <= char <= "9" for char in text)
            or len(text) > 1 and text[0] == "0"):
        return None
    if len(text) == 16 and text > "9007199254740991":
        return None
    if text == "0" and not allow_zero:
        return None
    return int(text)


def cpu_ratio(token):
    """Binary64 finite unit interval or None; distinguish underflow from zero."""
    if type(token) is not _Number:
        return None
    text = token.lexeme
    if type(text) is not str or not 1 <= len(text) <= 64:
        return None
    try:
        _numeric_grammar(text)
    except InvalidRaw:
        return None
    nonzero = False
    for char in text:
        if char in "eE":
            break
        if "1" <= char <= "9":
            nonzero = True
    try:
        result = float(text)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(result) or not 0 <= result <= 1 or nonzero and result == 0:
        return None
    return result
