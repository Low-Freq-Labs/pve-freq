"""Partial restricted scalar grammar; no container or policy authority."""
from .lines import InvalidDocument


def _reject():
    raise InvalidDocument("Policy document unavailable")


class Budget:
    """Internal per-pair accounting; never reset between documents.

    Caller owns this exact instance exclusively. It is not a provenance token.
    Failed parses consume reservations; callers must discard failed parsing.
    """
    __slots__ = ("values", "strings")

    def __init__(self):
        self.values = 0
        self.strings = 0

    def value(self):
        if self.values >= 32768:
            _reject()
        self.values += 1

    def character(self):
        if self.strings >= 524288:
            _reject()
        self.strings += 1


_HEX = frozenset("0123456789abcdefABCDEF")
_ESCAPES = {'"': '"', "\\": "\\", "b": "\b", "t": "\t",
            "n": "\n", "f": "\f", "r": "\r"}


def _boundary(text, position):
    return position == len(text) or text[position] in " \t#,]}"


def scalar(text, position, budget):
    """Parse one value and return (value, next position), with no whitespace skip.

    This entry requires a preflighted physical line and internal Budget. It also
    enforces exact argument types and a bounded line length defensively.
    Delimiters belong to the later container/statement grammar.
    """
    if (type(text) is not str or len(text) > 65536
            or type(position) is not int or not 0 <= position < len(text)
            or type(budget) is not Budget):
        _reject()
    budget.value()
    start = position
    if text[position] == '"':
        position += 1
        output = []
        while position < len(text):
            char = text[position]
            position += 1
            if char == '"':
                if not _boundary(text, position):
                    _reject()
                return "".join(output), position
            if char == "\\":
                if position == len(text):
                    _reject()
                escape = text[position]
                position += 1
                if escape in _ESCAPES:
                    char = _ESCAPES[escape]
                elif escape in ("u", "U"):
                    width = 4 if escape == "u" else 8
                    if position + width > len(text):
                        _reject()
                    # Fixed-width slice only after its extent is checked.
                    digits = text[position:position + width]
                    if any(c not in _HEX for c in digits):
                        _reject()
                    code = int(digits, 16)
                    if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                        _reject()
                    char = chr(code)
                    position += width
                else:
                    _reject()
            elif ord(char) < 32 or ord(char) == 127:
                _reject()
            if 0xD800 <= ord(char) <= 0xDFFF:
                _reject()
            if len(output) >= 4096:
                _reject()
            budget.character()
            output.append(char)
        _reject()
    for spelling, value in (("true", True), ("false", False)):
        if text.startswith(spelling, position):
            end = position + len(spelling)
            if not _boundary(text, end):
                _reject()
            return value, end
    while position < len(text) and "0" <= text[position] <= "9":
        if position - start >= 16:
            _reject()
        position += 1
    if position == start or not _boundary(text, position):
        _reject()
    if position - start > 1 and text[start] == "0":
        _reject()
    value = int(text[start:position])
    if value > 9007199254740991:
        _reject()
    return value, position
