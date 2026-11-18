"""Complete fixed guest-read request DATA grammar; no reference authority.

Original HTTP framing/body acquisition, authentication/CSRF, original writer
boundary and purpose-specific reference redemption remain the handler's duties.
This function reads no stream, session, table, URL or native resource.
"""
import json
import re


class Refused(ValueError):
    pass


def _fail():
    raise Refused("Guest request unavailable") from None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _schema_integer(token):
    if token != "1":
        _fail()
    return 1


def _not_number(token):
    _fail()


def decode_guest_request(method, path, body):
    """Return (fixed operation, decoded selector or None), or fixed refusal.

    The tuple is parsed request data. Possessing it never authorizes a source,
    principal, session, guest, reference renewal, request retry or native read.
    """
    if (type(method) is not str or not 1 <= len(method) <= 4 or
            type(path) is not str or not 1 <= len(path) <= 64 or
            type(body) is not bytes or len(body) > 256):
        _fail()
    if method == "GET" and path == "/api/guest-read/v1/sources":
        if body != b"":
            _fail()
        return ("guest-sources", None)
    choices = {
        "/api/guest-read/v1/inventory": ("guest-inventory", "source_ref"),
        "/api/guest-read/v1/profile": ("guest-profile", "guest_ref"),
    }
    if method != "POST" or path not in choices or not body:
        _fail()
    if body.startswith(b"\xef\xbb\xbf"):
        _fail()
    try:
        value = json.loads(body.decode("utf-8", "strict"), object_pairs_hook=_object,
                           parse_int=_schema_integer, parse_float=_not_number,
                           parse_constant=_not_number)
    except (ValueError, UnicodeError):
        _fail()
    operation, field = choices[path]
    if (type(value) is not dict or set(value) != {"schema", field} or
            type(value["schema"]) is not int or value["schema"] != 1 or
            type(value[field]) is not str or
            re.fullmatch(r"[0-9a-f]{64}", value[field]) is None):
        _fail()
    return (operation, value[field])
