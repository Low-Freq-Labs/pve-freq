"""Strict proposed v2 request DATA grammar; no route or native authority.

This reads no original stream, session, table, URL, entropy or resource. The
unimplemented original body owner still owes framing, one-use acquisition,
authentication/CSRF, source/writer/recipient/end and final response admission.
Accepted v1 guest grammar and its original broker are deliberately unchanged.
"""
import json
import re


class Refused(ValueError):
    pass


def _fail():
    raise Refused("Guest request unavailable") from None


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _fail()
        value[key] = item
    return value


def _schema_integer(token):
    if token != "2":
        _fail()
    return 2


def _not_number(token):
    _fail()


def decode_guest_owner_request(method, path, body):
    """Return (literal future operation, fresh parsed dict), or fixed refusal.

    C, F and R remain parsed text. Their identical wire shape never makes
    their distinct original owner/purpose namespaces interchangeable.
    """
    if (type(method) is not str or method != "POST" or
            type(path) is not str or not 1 <= len(path) <= 64 or
            type(body) is not bytes or not 0 < len(body) <= 256):
        _fail()
    choices = {
        "/api/guest-read/v2/open": ("guest-owner-open", ("open_nonce",)),
        "/api/guest-read/v2/sources": ("guest-owner-sources", ("owner_ref",)),
        "/api/guest-read/v2/inventory": ("guest-owner-inventory", ("owner_ref", "source_ref")),
        "/api/guest-read/v2/profile": ("guest-owner-profile", ("owner_ref", "guest_ref")),
        "/api/guest-read/v2/retire": ("guest-owner-retire", ("open_nonce",)),
    }
    if path not in choices or body.startswith(b"\xef\xbb\xbf"):
        _fail()
    try:
        value = json.loads(body.decode("utf-8", "strict"), object_pairs_hook=_object,
                           parse_int=_schema_integer, parse_float=_not_number,
                           parse_constant=_not_number)
    except (ValueError, UnicodeError, RecursionError):
        _fail()
    operation, fields = choices[path]
    if (type(value) is not dict or set(value) != {"schema", *fields} or
            type(value["schema"]) is not int or value["schema"] != 2):
        _fail()
    for field in fields:
        if type(value[field]) is not str or re.fullmatch("[0-9a-f]{64}", value[field]) is None:
            _fail()
    return operation, value
