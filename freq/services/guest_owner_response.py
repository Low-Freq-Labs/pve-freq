"""Fixed proposed guest v2 response-frame DATA, never response admission.

These functions produce UNRETAINED immutable OriginalPilotResponse objects.
They cannot prove an original owner, tombstone, recipient, source, request,
session, entropy result, F issuance or ACK. The proposed original dispatcher
uses only the unavailable frame for ordinary failure; open/retire remain DATA.
The future original owner must serialize outside gates, then final-admit the
same retained original request/family/session/source/recipient/end under its
same writer. A retire-shaped frame is not a confirmed server retirement.
"""
import datetime
import json
import re

from freq.services.cluster_pilot_http import OriginalPilotResponse


class Refused(ValueError):
    pass


def _fail():
    raise Refused('Guest response unavailable') from None


def _selector(value):
    if (type(value) is not str or len(value) != 64 or
            re.fullmatch('[0-9a-f]{64}', value) is None):
        _fail()


def _display_stamp(value):
    # Display DATA only. This never reads or extends any authority clock/end.
    if (type(value) is not str or len(value) != 24 or
            re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[.][0-9]{3}Z', value) is None):
        _fail()
    try:
        datetime.datetime(int(value[:4]), int(value[5:7]), int(value[8:10]),
            int(value[11:13]), int(value[14:16]), int(value[17:19]),
            int(value[20:23]) * 1000, tzinfo=datetime.timezone.utc)
    except ValueError:
        _fail()


def _frame_data(status, payload):
    # Fixed callers construct flat builtin shapes; this helper is not an API
    # accepting arbitrary provider payloads or a grant to write any frame.
    strings = sum(len(key.encode('utf-8')) for key in payload)
    strings += sum(len(value.encode('utf-8')) for value in payload.values()
                   if type(value) is str)
    if strings > 65536:
        _fail()
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')
    if len(body) > 131072:
        _fail()
    return OriginalPilotResponse(status, body, 'application/json; charset=utf-8')


def format_owner_open_data(owner_ref, completed_at):
    """Unretained open-shaped DATA, not a published or authenticated F."""
    _selector(owner_ref)
    _display_stamp(completed_at)
    return _frame_data(200, {'schema': 2, 'kind': 'guest-owner',
        'owner_ref': owner_ref, 'completed_at': completed_at})


def format_owner_retired_data(open_nonce):
    """Unretained retire-shaped DATA, not a tombstone/ACK witness."""
    _selector(open_nonce)
    return _frame_data(200, {'schema': 2, 'kind': 'guest-owner-retired',
                             'open_nonce': open_nonce})


def format_owner_unavailable_data():
    """Only the fixed v2 failure shape; original auth errors stay separate."""
    return _frame_data(503, {'schema': 2, 'kind': 'guest-unavailable'})
