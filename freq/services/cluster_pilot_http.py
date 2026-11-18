"""Original pilot HTTP custody, SOURCE WORK IN PROGRESS, not installed.

One actual accepted TLS connection, one bounded request, one response attempt.
This module deliberately imports no legacy server, configuration loader, auth
module, provider, or service. It cannot issue a configured source/auth lease or
publish an observation. The actual startup/cohort owner must be implemented
before connecting the fixed dispatch below. It is not supplied as a callback.

Native IO and scheduler waits still require actual qualified workload evidence.
Socket timeouts and clock checks are not a hard wall-time/containment proof.
"""

import email.message
import ipaddress
import json
import math
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from freq.services.pilot_login_rate import OriginalLoginRateDuty


_BUDGET = 10.0
_MAX_HEADER_BYTES = 16384
_MAX_HEADER_LINES = 64
_MAX_LOGIN_BODY = 1048576
_MAX_REFERENCE_BODY = 256
_MAX_RESPONSE_BODY = 3 * 1048576
_REASONS = {200: b'OK', 400: b'Bad Request', 401: b'Unauthorized', 403: b'Forbidden',
            404: b'Not Found', 405: b'Method Not Allowed',
            409: b'Conflict', 429: b'Too Many Requests',
            503: b'Service Unavailable', 504: b'Gateway Timeout'}
_SECURITY_HEADERS = (
    b'X-Content-Type-Options: nosniff\r\n'
    b'X-Frame-Options: DENY\r\n'
    b'Referrer-Policy: strict-origin-when-cross-origin\r\n'
    b'Permissions-Policy: geolocation=(), microphone=(), camera=(), '
    b'usb=(), payment=(), accelerometer=(), gyroscope=(), magnetometer=(), '
    b'interest-cohort=()\r\n'
    b"Content-Security-Policy: default-src 'self'; script-src 'self'; "
    b"style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    b"connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
    b"base-uri 'none'; form-action 'self'; object-src 'none'\r\n"
    b'Strict-Transport-Security: max-age=31536000; includeSubDomains\r\n'
)


class _RequestUnavailable(Exception):
    """No public native exception detail or secret fields."""


class _BadRequest(Exception):
    pass


def _first_control(first, later):
    """First genuine control object, never a stringified native error."""
    if first is not None and not isinstance(first, Exception):
        return first
    if later is not None and not isinstance(later, Exception):
        return later
    return None


class OriginalPilotResponse:
    """Prebuilt response data. Construction alone grants no write right.

    Only a frame retained by the original broker for that exact native
    request can be written. Its serialization occurs outside admission gates.
    """
    __slots__ = ('_wire',)

    def __init__(self, status, body, mime, cookie=None):
        if type(status) is not int or status not in _REASONS:
            raise _RequestUnavailable()
        if type(body) is not bytes or len(body) > _MAX_RESPONSE_BODY:
            raise _RequestUnavailable()
        if type(mime) is not str or mime not in ('application/json', 'application/json; charset=utf-8', 'application/javascript',
                        'text/css', 'text/html; charset=utf-8'):
            raise _RequestUnavailable()
        headers = (b'HTTP/1.1 ' + str(status).encode('ascii') + b' ' +
                   _REASONS[status] + b'\r\nContent-Type: ' +
                   mime.encode('ascii') + b'\r\nContent-Length: ' +
                   str(len(body)).encode('ascii') +
                   b'\r\nCache-Control: no-store\r\nConnection: close\r\n' +
                   _SECURITY_HEADERS)
        if cookie is not None:
            # Only the fixed original session owner may select cookie values.
            # An otherwise valid caller-created response is still unretained.
            if (type(cookie) is not str or len(cookie) > 512 or
                    not cookie.isascii() or any(ord(c) < 32 or ord(c) > 126
                                               for c in cookie)):
                raise _RequestUnavailable()
            headers += b'Set-Cookie: ' + cookie.encode('ascii') + b'\r\n'
        object.__setattr__(self, '_wire', headers + b'\r\n' + body)

    def __setattr__(self, name, value):
        raise TypeError('Original response data is immutable')

    def __delattr__(self, name):
        raise TypeError('Original response data is immutable')


class _OriginalRequest:
    __slots__ = ('socket', 'end', 'write_end', 'handler', 'phase', 'frame', 'body',
                 'request_line_taken', 'method', 'target',
                 'discovery_started', 'discovery_duty',
                 'operation', 'asset', 'header_bytes', 'body_taken', 'guest_response',
                 'fleet_targets_started', 'fleet_targets_response',
                 'peer_ip', 'thread', 'login_rate', 'login_username', 'auth_attempted', 'asset_attempted',
                 'profile_cleanup', 'profile_cleanup_capture', 'profile_cleanup_capture_error',
                 'profile_custody_started', 'profile_preparation',
                 'profile_preparation_capture', 'profile_preparation_capture_error',
                 'profile_begin_original', 'profile_begin_capture',
                 'profile_begin_capture_error')

    def __init__(self, accepted, original_end, peer_ip):
        self.socket = accepted
        self.end = original_end
        self.write_end = original_end
        self.handler = None
        self.phase = 'accepted'
        self.frame = None
        self.body = None
        self.request_line_taken = False
        self.method = self.target = None
        self.discovery_started = False
        self.discovery_duty = None
        self.operation = self.asset = None
        self.header_bytes = 0
        self.body_taken = False
        self.guest_response = None
        self.fleet_targets_started = False
        self.fleet_targets_response = None
        self.profile_cleanup = None
        self.profile_cleanup_capture = 'unattempted'
        self.profile_cleanup_capture_error = None
        self.profile_custody_started = False
        self.profile_preparation = None
        self.profile_preparation_capture = 'unattempted'
        self.profile_preparation_capture_error = None
        # Canonical partial-begin storage, before fallible login-rate setup.
        self.profile_begin_original = None
        self.profile_begin_capture = 'unattempted'
        self.profile_begin_capture_error = None
        self.peer_ip = peer_ip
        self.thread = None
        self.login_rate = OriginalLoginRateDuty()
        self.login_username = None
        self.auth_attempted = False
        self.asset_attempted = False


class _OriginalHTTPRequests:
    """Owned by the actual server, never by request data or config flags.

    This is only original native HTTP custody. It is not source/current cohort
    or authenticated principal authority. Actual startup must keep its fixed
    installation gate before this gate in final admission transactions.
    """
    def __init__(self, server):
        self._server = server
        self._gate = threading.Lock()
        self._requests = {}
        self._uncertain_connections = []
        # Construction is inactive. Only a future qualified original startup
        # transaction may enable this SAME broker after complete ownership.
        self._live = False
        self._gate_uncertain = False

    def _drop_gate(self, original_error):
        # The owning invocation passes its local body outcome explicitly.
        # An earlier caller exception is never this release duty's outcome.
        try:
            self._gate.release()
        except BaseException as cleanup:
            self._live = False
            self._gate_uncertain = True
            control = _first_control(original_error, cleanup)
            if control is not None:
                raise control
            if original_error is not None:
                raise original_error
            raise

    def _lock(self, original_end):
        if not self._live or self._gate_uncertain:
            raise _RequestUnavailable()
        left = original_end - time.monotonic()
        if not math.isfinite(left) or left <= 0 or not self._gate.acquire(timeout=left):
            raise _RequestUnavailable()
        try:
            if (not self._live or self._gate_uncertain or
                    not time.monotonic() < original_end):
                raise _RequestUnavailable()
        except BaseException as original_error:
            # Custody begins at successful acquire, before a fallible sample.
            # Caller acquires release duty only after this method returns.
            self._drop_gate(original_error)
            raise

    def _accept(self, accepted, original_end, peer_ip):
        if type(accepted) is not ssl.SSLSocket or type(peer_ip) is not str:
            raise _RequestUnavailable()
        self._lock(original_end)
        original_error = None
        try:
            if not self._live or accepted in self._requests or len(self._requests) >= 64:
                raise _RequestUnavailable()
            self._requests[accepted] = _OriginalRequest(accepted, original_end, peer_ip)
        except BaseException as error:
            original_error = error
            raise
        finally:
            self._drop_gate(original_error)

    def _quarantine_unsettled_connection(self, accepted):
        # Native object retained even if TLS/accept registration failed before
        # a request existed. The actual outer owner must physically retire the
        # instance. No descriptor number is retried or capacity refunded.
        self._live = False
        # Retirement-only list, never a source of grants. The server also
        # retains the original object in its preallocated pending-accept slot
        # BEFORE this potentially fallible append. No lock wait in quarantine.
        self._uncertain_connections.append(accepted)

    def _claim(self, handler):
        # Exact class is a filter. The native accepted socket must ALSO be in
        # this original server's table and unclaimed. Arbitrary handlers fail.
        if type(handler) is not _OriginalPilotHandler or handler.server is not self._server:
            raise _RequestUnavailable()
        original = self._requests.get(handler.request)
        if original is None:
            raise _RequestUnavailable()
        self._lock(original.end)
        original_error = None
        try:
            if (not self._live or self._requests.get(original.socket) is not original
                    or original.socket is not handler.request or original.handler is not None
                    or original.phase != 'accepted'):
                raise _RequestUnavailable()
            original.handler = handler
            original.thread = threading.current_thread()
            original.phase = 'reading'
            return original
        except BaseException as error:
            original_error = error
            raise
        finally:
            self._drop_gate(original_error)

    def _owned(self, handler):
        original = self._requests.get(handler.request)
        if (original is None or original.handler is not handler or
                handler.server is not self._server or not self._live or
                original.thread is not threading.current_thread()):
            raise _RequestUnavailable()
        return original

    def _remaining(self, original):
        # The accepted request's stored end is never replaced or renewed.
        left = original.end - time.monotonic()
        if not math.isfinite(left) or left <= 0:
            raise _RequestUnavailable()
        return left

    def _write_remaining(self, original):
        # Only original-owner retained data, never a caller-supplied send end.
        end = original.write_end
        if (type(end) is not float or not math.isfinite(end) or
                end > original.end):
            raise _RequestUnavailable()
        left = min(end, original.end) - time.monotonic()
        if not math.isfinite(left) or left <= 0:
            raise _RequestUnavailable()
        return left

    def _readline(self, original, stream, maximum):
        original.socket.settimeout(self._remaining(original))
        raw = stream.readline(maximum + 1)
        self._remaining(original)
        if len(raw) > maximum or not raw.endswith(b'\r\n'):
            raise _BadRequest()
        return raw

    def _parse(self, handler, original):
        if (type(original) is not _OriginalRequest or original.phase != 'reading' or
                original.request_line_taken is not False):
            raise _BadRequest()
        # Once-only original input duty precedes the first read/allocation.
        # A failed or lost read never permits replay on this same request.
        original.request_line_taken = True
        raw = self._readline(original, handler.rfile, 4096)
        parts = raw[:-2].split(b' ')
        if len(parts) != 3 or parts[2] != b'HTTP/1.1':
            raise _BadRequest()
        method, target = parts[:2]
        if (not method or not method.isalpha() or not method.isupper() or
                not 0 < len(target) <= 1024 or
                any(c < 33 or c > 126 for c in target)):
            raise _BadRequest()
        request_method = method.decode('ascii')
        request_target = target.decode('ascii')
        handler.command = request_method
        handler.path = request_target
        handler.request_version = 'HTTP/1.1'
        handler.requestline = ''  # Never retain a credential-bearing URL log.
        headers = email.message.Message()
        seen = set()
        total = len(raw)
        for _ in range(_MAX_HEADER_LINES + 1):
            line = self._readline(original, handler.rfile,
                                  min(4096, _MAX_HEADER_BYTES - total))
            total += len(line)
            if total > _MAX_HEADER_BYTES:
                raise _BadRequest()
            if line == b'\r\n':
                break
            name, separator, value = line[:-2].partition(b':')
            if (not separator or not name or
                    any(c not in b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                        for c in name) or
                    any(c < 32 or c > 126 for c in value)):
                raise _BadRequest()
            key = name.decode('ascii').lower()
            if key in seen:
                raise _BadRequest()
            seen.add(key)
            headers[name.decode('ascii')] = value.decode('ascii').strip(' ')
        else:
            raise _BadRequest()
        if not headers.get('Host') or 'Transfer-Encoding' in headers or 'Expect' in headers:
            raise _BadRequest()
        handler.headers = headers
        original.header_bytes = total
        # Classification occurs before body decoding and every legacy hook.
        # Exact literal source data; no generic static/API/SPA fallback.
        from freq.services.cluster_pilot_request import classify_request
        route = classify_request(request_method, request_target)
        if route is None:
            original.phase = 'ready'
            return False
        # Keep only fixed-classifier accepted source values. Unknown URLs,
        # including arbitrary credential-bearing queries, remain unretained.
        original.method = request_method
        original.target = request_target
        original.operation, original.asset = route
        length = headers.get('Content-Length')
        if request_method == 'GET':
            if length not in (None, '0'):
                raise _BadRequest()
            original.body = b''
        else:
            if (length is None or not length.isascii() or not length.isdecimal()
                    or length[0] == '0' or len(length) > 7):
                raise _BadRequest()
            count = int(length)
            limit = _MAX_LOGIN_BODY if original.operation == 'login' else _MAX_REFERENCE_BODY
            if not 0 < count <= limit:
                raise _BadRequest()
            content_type = headers.get('Content-Type', '').lower()
            if content_type not in ('application/json', 'application/json; charset=utf-8'):
                raise _BadRequest()
            handler.request.settimeout(self._remaining(original))
            body = handler.rfile.read(count)
            self._remaining(original)
            if len(body) != count:
                raise _BadRequest()
            original.body = body
        original.phase = 'ready'
        return True

    def _body_json(self, handler):
        original = self._owned(handler)
        if original.phase != 'ready' or original.body_taken:
            raise _BadRequest()
        original.body_taken = True
        self._remaining(original)
        if original.operation in ('guest-owner-open', 'guest-owner-sources',
                'guest-owner-inventory', 'guest-owner-profile', 'guest-owner-retire'):
            # Original private classifier purpose; never mutable public path.
            # Parsed DATA only, not original auth/session/reference admission.
            from freq.services.guest_owner_request import Refused, decode_guest_owner_request
            expected = original.operation
            path = {
                'guest-owner-open': '/api/guest-read/v2/open',
                'guest-owner-sources': '/api/guest-read/v2/sources',
                'guest-owner-inventory': '/api/guest-read/v2/inventory',
                'guest-owner-profile': '/api/guest-read/v2/profile',
                'guest-owner-retire': '/api/guest-read/v2/retire',
            }[expected]
            try:
                operation, data = decode_guest_owner_request('POST', path, original.body)
            except Refused:
                raise _BadRequest() from None
            if operation != expected or original.operation != expected:
                raise _BadRequest()
            self._remaining(original)
            return data
        if original.operation in ('guest-sources', 'guest-inventory', 'guest-profile'):
            # Purpose comes from the original private classifier result. A
            # changed public handler.command/path cannot redeem another kind.
            from freq.services.guest_read_request import Refused, decode_guest_request
            method, path, field = {
                'guest-sources': ('GET', '/api/guest-read/v1/sources', None),
                'guest-inventory': ('POST', '/api/guest-read/v1/inventory', 'source_ref'),
                'guest-profile': ('POST', '/api/guest-read/v1/profile', 'guest_ref'),
            }[original.operation]
            try:
                operation, reference = decode_guest_request(method, path, original.body)
            except Refused:
                raise _BadRequest() from None
            if operation != original.operation:
                raise _BadRequest()
            self._remaining(original)
            # Parsed DATA only: no original auth, CSRF or reference lookup.
            return {} if field is None else {'schema': 1, field: reference}
        def pairs(rows):
            result = {}
            for key, value in rows:
                if key in result:
                    raise _BadRequest()
                result[key] = value
            return result
        # Login's selected input has only string leaves; references likewise.
        # Refuse nested/scalar types after lexically bounding JSON depth first.
        raw = original.body
        depth = 0
        string = escaped = False
        for byte in raw:
            if string:
                if escaped:
                    escaped = False
                elif byte == 92:
                    escaped = True
                elif byte == 34:
                    string = False
            elif byte == 34:
                string = True
            elif byte in (91, 123):
                depth += 1
                if depth > 1:
                    raise _BadRequest()
            elif byte in (93, 125):
                depth -= 1
                if depth < 0:
                    raise _BadRequest()
        if depth or string:
            raise _BadRequest()
        try:
            data = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(_BadRequest()))
        except (ValueError, UnicodeError, RecursionError):
            raise _BadRequest() from None
        expected = {'username', 'password'} if original.operation == 'login' else {
            'selection_ref' if original.operation == 'bind' else 'binding_ref'}
        if type(data) is not dict or set(data) != expected or any(type(v) is not str for v in data.values()):
            raise _BadRequest()
        if original.operation == 'login':
            # Fixed selected auth helper uses exactly this normalization. Keep
            # the parser-derived original username privately, not a handler
            # field/caller copy that could choose a different rate bucket.
            original.login_username = data['username'].strip().lower()
        self._remaining(original)
        return data

    def _admit_frame_locked(self, handler, original, response):
        """Called only in original ordered final transaction with gate HELD.

        For positive responses the installation owns earlier source/auth/ref
        gates and must revalidate all participants in that same transaction.
        This operation consumes only this native HTTP request's response duty.
        """
        if (not self._live or type(response) is not OriginalPilotResponse or
                self._requests.get(original.socket) is not original or
                original.handler is not handler or original.phase != 'ready' or
                original.thread is not threading.current_thread() or
                original.socket is not handler.request or not time.monotonic() < original.end):
            raise _RequestUnavailable()
        original.frame = response
        original.phase = 'admitted'

    def _refuse(self, handler, status):
        # Fixed refusal only. No caller-controlled error/native detail.
        response = OriginalPilotResponse(status, b'{"error":"cluster_observation_unavailable"}',
                                         'application/json')
        original = self._owned(handler)
        self._lock(original.end)
        original_error = None
        try:
            if original.phase == 'reading':
                original.phase = 'ready'
            self._admit_frame_locked(handler, original, response)
        except BaseException as error:
            original_error = error
            raise
        finally:
            self._drop_gate(original_error)
        return self._write_admitted(handler, response)

    def _reserve_write_locked(self, handler, original, response):
        """Reserve retained once-write under the caller's ordered gates.

        Native socket IO happens only in _send_reserved AFTER every admission
        gate is released. Retained original frame identity is mandatory; caller
        bytes or a copied response cannot claim this right.
        """
        if (not self._live or self._gate_uncertain or
                self._requests.get(original.socket) is not original or
                original.handler is not handler or original.socket is not handler.request or
                original.thread is not threading.current_thread() or
                handler.server is not self._server or
                original.phase != 'admitted' or original.frame is not response or
                type(response) is not OriginalPilotResponse or
                not time.monotonic() < original.end):
            raise _RequestUnavailable()
        original.phase = 'write-reserved'

    def _send_reserved(self, handler, response):
        original = self._owned(handler)
        self._write_remaining(original)
        self._lock(original.write_end)
        original_error = None
        try:
            if (original.phase != 'write-reserved' or original.frame is not response or
                    type(response) is not OriginalPilotResponse):
                raise _RequestUnavailable()
            original.phase = 'write-attempted'
            wire = response._wire
        except BaseException as error:
            original_error = error
            raise
        finally:
            self._drop_gate(original_error)
        # No admission/auth/reference gate is held across socket operations.
        try:
            original.socket.settimeout(self._write_remaining(original))
            self._write_remaining(original)
            original.socket.sendall(wire)
            self._write_remaining(original)
        finally:
            # Even a partial/unknown write consumes the original attempt.
            handler.close_connection = True

    def _write_admitted(self, handler, response):
        original = self._owned(handler)
        self._lock(original.end)
        original_error = None
        try:
            self._reserve_write_locked(handler, original, response)
        except BaseException as error:
            original_error = error
            raise
        finally:
            self._drop_gate(original_error)
        return self._send_reserved(handler, response)

    def _release(self, accepted, close_returned):
        # Called by the original server shutdown path, never an HTTP route.
        if not self._gate.acquire(blocking=False):
            # No unbounded cleanup wait or new timeout. Original table already
            # retains this native request. Refuse future work until the outer
            # actual owner physically retires this instance; no capacity refund.
            self._live = False
            return False
        original_error = None
        try:
            original = self._requests.get(accepted)
            if original is not None:
                # A closed HTTP socket is not a profile/native job receipt.
                # Retain the original identities before clearing any fields.
                # This marker can only refuse release, never grant admission.
                capture = getattr(original, 'profile_cleanup_capture', None)
                begin_capture = getattr(original, 'profile_begin_capture', None)
                # Every retained guest response can hold original outside-call
                # or logical retirement obligations. A socket close alone may
                # not discard it, even after its mutable operation label changes.
                # Actual outer retirement/acknowledgment remains separate work.
                if (getattr(original, 'profile_begin_original', None) is not None or
                        type(begin_capture) is not str or begin_capture != 'unattempted' or
                        getattr(original, 'profile_begin_capture_error', None) is not None or
                        getattr(original, 'guest_response', None) is not None or
                        getattr(original, 'profile_custody_started', None) is not False or
                        getattr(original, 'profile_cleanup', None) is not None or
                        type(capture) is not str or capture != 'unattempted' or
                        getattr(original, 'profile_cleanup_capture_error', None) is not None or
                        type(original.operation) is str and
                        original.operation == 'guest-owner-profile' and
                        original.guest_response is not None):
                    self._live = False
                    return False
                original.phase = 'retired' if close_returned else 'closure-uncertain'
                original.body = original.frame = original.handler = None
                if close_returned:
                    del self._requests[accepted]
                else:
                    # The parent must physically retire this native server;
                    # an unknown close cannot free capacity or issue again.
                    self._live = False
            return True
        except BaseException as error:
            original_error = error
            raise
        finally:
            self._drop_gate(original_error)


class _OriginalPilotHandler(BaseHTTPRequestHandler):
    """Fixed private handler. No legacy do_GET/do_POST/automatic error writer."""
    protocol_version = 'HTTP/1.1'
    rbufsize = 8192
    wbufsize = 0

    def handle(self):
        self.close_connection = True
        broker = self.server._pilot_requests
        original = None
        try:
            original = broker._claim(self)
            if not broker._parse(self, original):
                broker._refuse(self, 404)
                return
            # Only the actual original factory can retain this fixed component.
            # Missing factory/dispatcher still refuses; no legacy fallback.
            from freq.services.pilot_cluster_dispatch import OriginalPilotDispatch
            owner = getattr(self.server, '_cluster_pilot_installation', None)
            dispatcher = getattr(owner, '_dispatcher', None)
            if (type(dispatcher) is not OriginalPilotDispatch or
                    dispatcher._installation is not owner):
                broker._refuse(self, 503)
                return
            dispatcher.run(self)
        except _BadRequest:
            if original is not None and original.phase in ('reading', 'ready'):
                try:
                    broker._refuse(self, 400)
                except Exception:
                    pass
        except (OSError, _RequestUnavailable):
            # Expired/spent/partial response: close, never append a status.
            pass
        finally:
            self.close_connection = True

    def _request_body(self):
        return self.server._pilot_requests._body_json(self)

    def log_message(self, format, *args):
        # No request path, Cookie, Authorization, password or native exception.
        return


class _OriginalPilotServer(ThreadingMixIn, HTTPServer):
    """Concrete native listener source; startup/credentials remain UNJOINED.

    Caller-provided ssl context/listener tuples are not installation authority.
    Actual startup must acquire and retain its fixed cert/key/source resources,
    TLS context and writer fence before constructing this private listener.
    Never call this class merely because an HTTP/config flag asks for pilot.
    """
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, address, context):
        if type(context) is not ssl.SSLContext or context.protocol != ssl.PROTOCOL_TLS_SERVER:
            raise _RequestUnavailable()
        self._pilot_context = context
        self._pilot_requests = _OriginalHTTPRequests(self)
        self._pilot_pending_connection = None
        self._pilot_pending_close_state = 'unused'
        # Allocate an UNBOUND original socket only. TCPServer's default would
        # bind and listen here before the component/cohort transaction exists.
        # This remains native construction: the actual outer owner must retain
        # this instance before calling __init__ and own lost native returns.
        self._pilot_listener_state = 'construction-pending'
        super().__init__(address, _OriginalPilotHandler, bind_and_activate=False)
        self._pilot_listener_state = 'constructed-unbound'
        # No activation method is supplied. The still-absent original factory
        # owes separately reviewed fixed bind/listen/currentness and physical
        # lifetime before enabling this same broker. A state string is DATA.

    def get_request(self):
        if not self._pilot_requests._live:
            raise OSError('Pilot listener retired')
        accepted, address = self.socket.accept()
        wrapped = None
        try:
            # All fallible post-accept work is now inside original cleanup.
            # The local accepted object is retained before the first clock.
            self._pilot_pending_connection = accepted
            self._pilot_pending_close_state = 'owned'
            end = time.monotonic() + _BUDGET
            # Actual accepted direct peer, never XFF/handler/caller metadata.
            if (type(address) is not tuple or len(address) not in (2, 4) or
                    type(address[0]) is not str or not 0 < len(address[0]) <= 45 or
                    not address[0].isascii() or '%' in address[0]):
                raise _RequestUnavailable()
            peer_ip = address[0]
            try:
                ipaddress.ip_address(peer_ip)
            except ValueError:
                raise _RequestUnavailable() from None
            accepted.settimeout(max(0.001, end - time.monotonic()))
            wrapped = self._pilot_context.wrap_socket(
                accepted, server_side=True, do_handshake_on_connect=False)
            self._pilot_pending_connection = wrapped
            # Preserve the accepted end through TLS handshake, header/body
            # parsing, authentication, provider IO, locks and response writes.
            left = end - time.monotonic()
            if left <= 0:
                raise _RequestUnavailable()
            wrapped.settimeout(left)
            wrapped.do_handshake()
            if not time.monotonic() < end:
                raise _RequestUnavailable()
            self._pilot_requests._accept(wrapped, end, peer_ip)
            self._pilot_pending_close_state = 'transferred'
            self._pilot_pending_connection = None
            return wrapped, address
        except BaseException as first:
            control = _first_control(first, None)
            original = wrapped if wrapped is not None else accepted
            self._pilot_pending_connection = original
            self._pilot_pending_close_state = 'close-attempted'
            closed = False
            # Only original objects; no descriptor-number retry after close.
            try:
                original.close()
                closed = True
                self._pilot_pending_close_state = 'closed'
            except BaseException as close_error:
                control = _first_control(control, close_error)
                self._pilot_pending_close_state = 'uncertain'
                # Actual parent retirement is required; do not continue with
                # an unrecorded native close or retry a descriptor number.
                self._pilot_requests._live = False
                try:
                    self._pilot_requests._quarantine_unsettled_connection(original)
                except BaseException as quarantine_error:
                    control = _first_control(control, quarantine_error)
                    # Pending slot retains exact unsettled native object even
                    # if quarantine bookkeeping failed. Acceptance stays off.
            try:
                settled = self._pilot_requests._release(original, closed)
                if not settled:
                    self._pilot_requests._live = False
            except BaseException as release_error:
                self._pilot_requests._live = False
                control = _first_control(control, release_error)
            if control is not None:
                raise control
            # Fixed original accept loop handles OSError; never log raw native
            # request errors. Known ordinary close may continue accepting.
            raise OSError('Pilot connection unavailable') from None

    def shutdown_request(self, request):
        closed = False
        first = None
        control = None
        try:
            # Only the original owned TLS socket returned by get_request.
            # HTTPServer performs shutdown/close; no second application writer.
            super().shutdown_request(request)
            closed = True
        except BaseException as native_error:
            first = native_error
            control = _first_control(None, native_error)
            # Exact request remains in the original broker table. Retire
            # acceptance before later potentially failing bookkeeping.
            self._pilot_requests._live = False
        try:
            self._pilot_requests._release(request, closed)
        except BaseException as release_error:
            self._pilot_requests._live = False
            control = _first_control(control, release_error)
            if first is None:
                first = release_error
        if control is not None:
            raise control
        if first is not None:
            raise first

    def handle_error(self, request, client_address):
        # Default traceback could expose native/request/credential values.
        return


# No entry point, CLI activation, environment/config switch, live start, auth
# issuer or original installation factory is provided by this partial source.
