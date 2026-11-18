"""Bounded framing helpers for the dedicated Cluster Status HTTP route."""
import json
import re
import time


REQUEST_LIMIT = 256
RESPONSE_LIMIT = 2 * 1024 * 1024
ERROR_BODY = b'{"error":"cluster_report_unavailable"}'


class InvalidClusterRequest(ValueError):
    pass


def _remaining(handler, deadline):
    remaining = deadline - time.monotonic()
    if not 0 < remaining <= 10.0:
        raise TimeoutError('cluster_report_unavailable')
    handler.connection.settimeout(remaining)
    return remaining


def read_reference(handler, field, deadline):
    """Parse exactly one reference; reject ambiguous framing before reading."""
    if handler.command != 'POST' or field not in ('selection_ref', 'binding_ref'):
        raise InvalidClusterRequest()
    if handler.headers.get_all('Transfer-Encoding'):
        raise InvalidClusterRequest()
    lengths = handler.headers.get_all('Content-Length', [])
    if len(lengths) != 1 or not re.fullmatch(r'[1-9][0-9]{0,2}', lengths[0]):
        raise InvalidClusterRequest()
    length = int(lengths[0])
    if length > REQUEST_LIMIT:
        raise InvalidClusterRequest()
    content_types = handler.headers.get_all('Content-Type', [])
    if len(content_types) != 1 or content_types[0].lower() not in (
            'application/json', 'application/json; charset=utf-8'):
        raise InvalidClusterRequest()
    chunks = []
    received = 0
    while received < length:
        _remaining(handler, deadline)
        chunk = handler.rfile.read1(length - received)
        if type(chunk) is not bytes or not chunk or len(chunk) > length - received:
            raise InvalidClusterRequest()
        chunks.append(chunk)
        received += len(chunk)
    _remaining(handler, deadline)
    raw = b''.join(chunks)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidClusterRequest()
            result[key] = value
        return result
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    except (UnicodeError, ValueError, RecursionError):
        raise InvalidClusterRequest() from None
    if type(data) is not dict or set(data) != {field}:
        raise InvalidClusterRequest()
    value = data[field]
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise InvalidClusterRequest()
    return value


def write_once(handler, body, status=200, *, deadline):
    """Consume publication before calling the handler's first write method.

    The caller owns authentication/publication serialization. This helper never
    retries a failed response, nor turns a partial write into a second response.
    Every route invocation closes the connection, preventing keepalive ambiguity.
    """
    if getattr(handler, '_cluster_response_consumed', False):
        handler.close_connection = True
        return False
    if type(body) is not bytes or not 0 < len(body) <= RESPONSE_LIMIT:
        body, status = ERROR_BODY, 503
    if type(status) is not int or status not in (200, 400, 403, 409, 503, 504):
        body, status = ERROR_BODY, 503
    handler._cluster_response_consumed = True
    handler.close_connection = True
    try:
        _remaining(handler, deadline)
        handler.send_response(status)
        handler.send_header('Content-Type', 'application/json; charset=utf-8')
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Connection', 'close')
        _remaining(handler, deadline)
        handler.end_headers()
        _remaining(handler, deadline)
        written = handler.wfile.write(body)
        if written != len(body):
            return False
        _remaining(handler, deadline)
        handler.wfile.flush()
        return True
    except Exception:
        return False
