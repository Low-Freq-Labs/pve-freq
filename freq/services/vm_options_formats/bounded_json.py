"""Private supplied-byte parser draft. No acquisition, credentials or route access.

Bounds constrain this parser's input and constructed tree, not caller retention,
tracebacks, allocator overhead or the future acquisition owner's physical memory.
"""
import json
from collections import namedtuple
import math
import re

MAX_BYTES = 1048576
MAX_DEPTH = 8
MAX_ENTRIES = 8192
MAX_STRING = 4096
MAX_INTEGER = 9007199254740991
# Preserve fractional/exponent spelling; field codecs must never validate a
# rounded floating value as an integer. Unknown provider fields may discard it.
JSONDecimal = namedtuple('JSONDecimal', 'token')
_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')


class Refused(ValueError):
    """Fixed diagnostic: never includes supplied bytes or parser exceptions."""


class CapacityExceeded(Refused):
    """Whole-response capacity refusal; never downgrade to invalid source."""


def parse(raw, *, byte_limit):
    """Parse exact bytes into an ordinary JSON tree under the fixed profile.

    byte_limit is the narrower source budget (provider 262144, config1048576).
    Caller owns cumulative source accounting; this function accepts no callbacks.
    """
    if type(raw) is not bytes or type(byte_limit) is not int:
        raise Refused('Supplied JSON unavailable')
    if not 1 <= byte_limit <= MAX_BYTES:
        raise Refused('Supplied JSON unavailable')
    if len(raw) > byte_limit:
        raise CapacityExceeded('Supplied JSON unavailable')
    try:
        text = raw.decode('utf-8', errors='strict')
    except UnicodeError:
        raise Refused('Supplied JSON unavailable') from None
    parser = _Parser(text)
    try:
        value = parser.value(0)
        parser.space()
        if parser.position != len(text):
            parser.refuse()
        return value
    except CapacityExceeded:
        raise
    except (ValueError, OverflowError, RecursionError):
        raise Refused('Supplied JSON unavailable') from None


class _Parser:
    __slots__ = ('text', 'position', 'entries')

    def __init__(self, text):
        self.text = text
        self.position = 0
        self.entries = 0

    @staticmethod
    def refuse():
        raise Refused('Supplied JSON unavailable')

    @staticmethod
    def capacity():
        raise CapacityExceeded('Supplied JSON unavailable')

    def space(self):
        while self.position < len(self.text) and self.text[self.position] in ' \t\r\n':
            self.position += 1

    def entry(self):
        # Charge before parsing either an object key/value or array element.
        if self.entries >= MAX_ENTRIES:
            self.capacity()
        self.entries += 1

    def string(self):
        start = self.position
        self.position += 1
        while self.position < len(self.text):
            ch = self.text[self.position]
            if ch == '"':
                self.position += 1
                token = self.text[start:self.position]
                value = json.loads(token)
                if len(value) > MAX_STRING:
                    self.capacity()
                if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
                    self.refuse()
                return value
            if ch == '\\':
                # Skip the escaped character; json.loads validates escape syntax.
                self.position += 2
            else:
                if ord(ch) < 32:
                    self.refuse()
                self.position += 1
            # A scalar uses at most12 ASCII characters (escaped surrogate pair).
            # This preallocation bound admits every <=4096-scalar JSON string.
            if self.position - start > 12 * MAX_STRING + 1:
                self.capacity()
        self.refuse()

    def value(self, depth):
        self.space()
        if self.position >= len(self.text):
            self.refuse()
        ch = self.text[self.position]
        if ch == '"':
            return self.string()
        if ch in '[{':
            if depth >= MAX_DEPTH:
                self.capacity()
            return self.container(ch, depth + 1)
        for word, result in (('true', True), ('false', False), ('null', None)):
            if self.text.startswith(word, self.position):
                self.position += len(word)
                return result
        match = _NUMBER.match(self.text, self.position)
        if not match:
            self.refuse()
        token = match.group(0)
        self.position = match.end()
        if '.' not in token and 'e' not in token.lower():
            # Reject long integer tokens before int conversion, including -0 only.
            if len(token.lstrip('-')) > 16:
                self.refuse()
            value = int(token)
            if abs(value) > MAX_INTEGER:
                self.refuse()
        else:
            if not math.isfinite(float(token)):
                self.refuse()
            value = JSONDecimal(token)
        return value

    def container(self, opening, depth):
        mapping = opening == '{'
        closing = '}' if mapping else ']'
        result = {} if mapping else []
        self.position += 1
        self.space()
        if self.position < len(self.text) and self.text[self.position] == closing:
            self.position += 1
            return result
        while True:
            self.entry()
            self.space()
            if mapping:
                if self.position >= len(self.text) or self.text[self.position] != '"':
                    self.refuse()
                key = self.string()
                if key in result:
                    self.refuse()
                self.space()
                if self.position >= len(self.text) or self.text[self.position] != ':':
                    self.refuse()
                self.position += 1
                item = self.value(depth)
                result[key] = item
            else:
                result.append(self.value(depth))
            self.space()
            if self.position >= len(self.text):
                self.refuse()
            ch = self.text[self.position]
            self.position += 1
            if ch == closing:
                return result
            if ch != ',':
                self.refuse()
