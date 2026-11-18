"""Bounded pure QEMU guest-network body decoder; no acquisition or authority.

The caller owns transport/framing, original deadline, source/version/identity,
cleanup and final admission. Input is one complete already bounded JSON body.
No observation time, source reference or action target is issued here.
"""

import ipaddress
import re


class Refused(ValueError):
    pass


def need(condition):
    if not condition:
        raise Refused("Guest network unavailable")


class Number(str):
    """A validated JSON numeric lexeme, before any numeric conversion."""


class Reader:
    def __init__(self, body):
        need(type(body) is bytes and len(body) <= 262144)
        try:
            self.text = body.decode("utf-8", "strict")
        except UnicodeDecodeError:
            raise Refused("Guest network unavailable") from None
        need(not self.text.startswith("\ufeff"))
        self.i = self.members = self.scalars = self.string_bytes = 0

    def whitespace(self):
        while self.i < len(self.text) and self.text[self.i] in " \t\n\r":
            self.i += 1

    def take(self, expected):
        self.whitespace()
        need(self.i < len(self.text) and self.text[self.i] == expected)
        self.i += 1

    def string(self, limit):
        self.take('"')
        output, size = [], 0
        while self.i < len(self.text):
            char = self.text[self.i]
            self.i += 1
            if char == '"':
                return "".join(output)
            if char == "\\":
                need(self.i < len(self.text))
                escape = self.text[self.i]
                self.i += 1
                fixed = {'"': '"', "\\": "\\", "/": "/", "b": "\b",
                         "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
                if escape == "u":
                    code = self.hex4()
                    if 0xD800 <= code <= 0xDBFF:
                        need(self.text[self.i:self.i + 2] == "\\u")
                        self.i += 2
                        low = self.hex4()
                        need(0xDC00 <= low <= 0xDFFF)
                        code = 0x10000 + (code - 0xD800) * 1024 + low - 0xDC00
                    else:
                        need(not 0xDC00 <= code <= 0xDFFF)
                    char = chr(code)
                else:
                    need(escape in fixed)
                    char = fixed[escape]
            else:
                need(ord(char) >= 0x20)
            code = ord(char)
            count = 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4
            # Charge before growing the decoded token or aggregate storage.
            need(size + count <= limit and self.string_bytes + count <= 65536)
            size += count
            self.string_bytes += count
            output.append(char)
        raise Refused("Guest network unavailable")

    def hex4(self):
        raw = self.text[self.i:self.i + 4]
        need(len(raw) == 4 and all(c in "0123456789abcdefABCDEF" for c in raw))
        self.i += 4
        return int(raw, 16)

    def value(self, depth=0):
        self.whitespace()
        need(self.i < len(self.text))
        char = self.text[self.i]
        if char == "{":
            need(depth < 6)
            self.i += 1
            output = {}
            self.whitespace()
            if self.i < len(self.text) and self.text[self.i] == "}":
                self.i += 1
                return output
            while True:
                need(len(output) < 128 and self.members < 4096)
                key = self.string(64)
                need(key.isascii() and key not in output)
                self.members += 1
                self.take(":")
                item = self.value(depth + 1)
                output[key] = item
                self.whitespace()
                need(self.i < len(self.text))
                end = self.text[self.i]
                self.i += 1
                if end == "}":
                    return output
                need(end == ",")
        if char == "[":
            need(depth < 6)
            self.i += 1
            output = []
            self.whitespace()
            if self.i < len(self.text) and self.text[self.i] == "]":
                self.i += 1
                return output
            while True:
                need(len(output) < 4096)
                item = self.value(depth + 1)
                output.append(item)
                self.whitespace()
                need(self.i < len(self.text))
                end = self.text[self.i]
                self.i += 1
                if end == "]":
                    return output
                need(end == ",")
        need(self.scalars < 4096)
        self.scalars += 1
        if char == '"':
            return self.string(4096)
        for literal, value in (("true", True), ("false", False), ("null", None)):
            if self.text.startswith(literal, self.i):
                self.i += len(literal)
                return value
        start = self.i
        while self.i < len(self.text) and self.text[self.i] not in " \t\n\r,]}":
            need(self.i - start < 64)
            self.i += 1
        raw = self.text[start:self.i]
        need(re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", raw) is not None)
        return Number(raw)

    def read(self):
        result = self.value()
        self.whitespace()
        need(self.i == len(self.text))
        return result


def fields(value, required, optional=()):
    need(type(value) is dict and set(required).issubset(value))
    known = set(required) | set(optional)
    for key, item in value.items():
        if key not in known:
            # Unknown provider scalars were fully validated and charged by the
            # reader; unknown containers never silently become compatibility.
            need(type(item) not in (dict, list))
    return value


def text(value, limit, nonempty=False):
    need(type(value) is str and len(value.encode("utf-8")) <= limit)
    need(not nonempty or value != "")
    return value


def unsigned(value, maximum):
    need(type(value) is Number)
    need(re.fullmatch(r"0|[1-9][0-9]*", value) is not None)
    bound = str(maximum)
    need(len(value) < len(bound) or (len(value) == len(bound) and value <= bound))
    return int(value)


def decode_guest_network(body):
    """Return validated internal interface rows or fixed Refused.

    No raw statistics/unknown fields, provider errors, times, authority flags or
    references escape. This does not make a QGA result a current observation.
    """
    root = fields(Reader(body).read(), ("data",))
    # Application transport wrapper is deliberately exact. Provider extension
    # scalars are allowed only inside the known result schema, below.
    need(set(root) == {"data"})
    data = fields(root["data"], ("result",))
    need(set(data) == {"result"})
    interfaces = data["result"]
    need(type(interfaces) is list and len(interfaces) <= 64)
    result = []
    stats_keys = ("rx-bytes", "rx-packets", "rx-errs", "rx-dropped",
                  "tx-bytes", "tx-packets", "tx-errs", "tx-dropped")
    for row in interfaces:
        fields(row, ("name",), ("hardware-address", "ip-addresses", "statistics"))
        name = text(row["name"], 128, True)
        mac = text(row["hardware-address"], 128) if "hardware-address" in row else None
        if "statistics" in row:
            stats = fields(row["statistics"], stats_keys)
            for key in stats_keys:
                unsigned(stats[key], 18446744073709551615)
        addresses = row.get("ip-addresses", [])
        need(type(addresses) is list and len(addresses) <= 16)
        projected = []
        for address in addresses:
            fields(address, ("ip-address", "ip-address-type", "prefix"))
            family = text(address["ip-address-type"], 4)
            need(family in ("ipv4", "ipv6"))
            literal = text(address["ip-address"], 45, True)
            need(literal.isascii() and "%" not in literal and "/" not in literal)
            try:
                parsed = ipaddress.ip_address(literal)
            except ValueError:
                raise Refused("Guest network unavailable") from None
            need(parsed.version == (4 if family == "ipv4" else 6))
            prefix = unsigned(address["prefix"], 32 if family == "ipv4" else 128)
            projected.append({"family": family, "address": literal, "prefix": prefix})
        result.append({"name": name, "mac": mac, "addresses": projected})
    return result
