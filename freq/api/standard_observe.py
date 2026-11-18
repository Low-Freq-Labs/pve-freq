"""Original standard read request entry; positive source admission is unfinished.

Called directly by FreqHandler before legacy auth/error dispatch. The only
current responses are fixed refusals. This stage neither opens a credential nor
issues a view/reference nor contacts a provider. Existing session registry
membership is necessary, not proof of the remaining installation, writer,
source/incarnation and final publication requirements.
"""
import json
import math
import re
import secrets
import ssl
import threading
import time
from contextlib import contextmanager

from freq.api import auth
from freq.core import read_source_epoch
from freq.services import standard_qemu_sources, standard_qemu_configuration
from freq.services import standard_qemu_runtime_identity
from freq.services import standard_qemu_private_files


PREFIX = '/api/observe/v1/'
_KEYS = {
    PREFIX + 'open': frozenset(('previous_view_ref',)),
    PREFIX + 'node': frozenset(('view_ref', 'node_ref', 'read_ref')),
    PREFIX + 'qemu': frozenset(('view_ref', 'node_ref', 'vm_ref', 'read_ref')),
    PREFIX + 'retire': frozenset(('view_ref',)),
}
_REF = re.compile(r'[0-9a-f]{64}')
_TOKEN = re.compile(r'[A-Za-z0-9_-]{32,128}')
_BODIES = {
    400: b'{"schema":3,"kind":"refusal","error":"read-refused"}',
    401: b'{"schema":3,"kind":"refusal","error":"authentication-required"}',
    403: b'{"schema":3,"kind":"refusal","error":"read-refused"}',
    503: b'{"schema":3,"kind":"refusal","error":"read-unavailable"}',
}

# Original request holders, separate from future view/provider admission.
# A settled tombstone can be replaced; pending duties cannot be evicted.
_ENTRY_GATE = threading.Lock()
_ENTRIES = [None] * 16

# Unissued opening reservations only. No reference or provider authority exists.
_VIEW_GATE = threading.Lock()
_VIEW_OPENINGS = [None] * 128
_PROVIDER_PREPARATIONS = [None] * 2  # Same original view gate; no entered IO yet.
# Fixed original candidate history, never rewound/evicted within this process.
_REFERENCE_HISTORY = [None] * 4096
_REFERENCE_INDEX = iter(tuple(range(4096)))
_REFERENCE_PENDING = object()


class _Refused(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__('Read unavailable')


class _Entry:
    """Private retained original request stages, never an issuer or grant."""
    __slots__ = ('handler', 'end', 'stage', 'failure', 'response_started',
                 'registry', 'lock', 'token', 'session', 'user', 'role', 'csrf',
                 'auth_failures', 'auth_stages', 'body_stage',
                 'response_stage', 'retention_stage', 'server', 'transport',
                 'transport_stage', 'transport_failure', 'streams',
                 'stream_stages', 'stream_failures', 'source_contexts',
                 'configuration', 'final_configuration', 'configuration_data', 'runtime_identity',
                 'final_runtime_identity', 'request_data', 'view_opening',
                 'dispatch_failure', 'settlement_failure', 'recipient_preparation',
                 'initialization_pending', 'initialization_returned',
                 'initialization_return', 'initialization_failure',
                 'initialization_complete')

    def __init__(self, handler):
        self.handler = handler
        now = time.monotonic()
        started = getattr(handler, '_request_started', now)
        if (type(started) not in (int, float) or not math.isfinite(started)
                or not 0 <= started <= now):
            raise _Refused(503)
        self.end = started + 10.0
        self.stage = 'retained'
        self.failure = None
        self.dispatch_failure = self.settlement_failure = None
        # Capture body/release, final body/release: fixed storage before locks.
        self.auth_failures = [None] * 4
        self.configuration = None  # Retain original file attempt before run.
        self.final_configuration = None
        self.configuration_data = None
        self.request_data = self.view_opening = None
        self.recipient_preparation = None
        self.runtime_identity = self.final_runtime_identity = None
        self.source_contexts = [None, None]  # capture and final original source gate
        # Response progress cannot overwrite unresolved authentication duties.
        self.auth_stages = ['unused', 'unused']
        self.body_stage = self.response_stage = 'unused'
        self.retention_stage = 'unreserved'
        self.server = getattr(handler, 'server', None)
        self.transport = handler.connection
        self.transport_stage = 'owned-by-http-server'
        self.transport_failure = None
        # Original handler wrappers are independent of its socket. Prepare
        # fixed close/failure holders before the first auth/body/send operation.
        self.streams = (handler.wfile, handler.rfile)
        self.stream_stages = ['owned', 'owned']
        self.stream_failures = [None, None, None]  # flush, write close, read close
        self.response_started = False
        self.registry = self.lock = self.session = None
        self.token = self.user = self.role = self.csrf = None

    def remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise _Refused(503)
        return remaining


def _retain_entry(entry):
    """Reserve before auth/body/response calls, with no admission wait.

    Rejected entries acquire no auth gate, body or response-write duty. The
    original HTTP handler still owns its pre-existing transport and closure.
    This finite table is not an installation/view/provider grant or a bound
    on threads allocated by the enclosing legacy HTTP server.
    """
    if not _ENTRY_GATE.acquire(blocking=False):
        return False
    retained = False
    try:
        for index, current in enumerate(_ENTRIES):
            if current is None or current.retention_stage == 'settled':
                _ENTRIES[index] = entry
                entry.retention_stage = 'table-release-pending'
                retained = True
                break
    except BaseException as failure:
        _remember(entry, failure)
    try:
        _ENTRY_GATE.release()
    except BaseException as failure:
        _remember(entry, failure)
    else:
        if retained:
            entry.retention_stage = 'retained'
    if entry.failure is not None:
        raise entry.failure from None
    return retained


def _settle_entry(entry):
    # Original request thread alone settles its own holder. No cleanup/native
    # call occurs here, and no other thread can revive this entry. The table
    # retains even settled tombstones until a later admission replaces one.
    recipient = entry.recipient_preparation
    if recipient is not None and (type(recipient) is not _UnissuedRecipient
            or not _UnissuedRecipient.known_unissued(recipient, entry)):
        return
    if (entry.view_opening is not None and entry.view_opening.stage
            not in ('prepared', 'not-acquired', 'refused', 'retired-unissued')):
        return
    for configuration in (entry.configuration, entry.final_configuration):
        if configuration is not None and configuration._state not in ('prepared', 'closed'):
            return
    for runtime in (entry.runtime_identity, entry.final_runtime_identity):
        if runtime is not None and runtime._state not in ('prepared', 'closed'):
            return
    for context in entry.source_contexts:
        if context is not None and (context._retained
                or context.stage not in ('unused', 'not-acquired', 'returned')
                or context.release_failure is not None
                or context.forget_failure is not None):
            return
    if (entry.retention_stage == 'retained'
            and entry.auth_stages[0] in ('unused', 'returned', 'not-acquired')
            and entry.auth_stages[1] in ('unused', 'returned', 'not-acquired')
            and entry.stream_stages[0] == 'closed'
            and entry.stream_stages[1] == 'closed'
            and entry.transport_stage == 'closed-by-http-server'):
        entry.retention_stage = 'settled'


def _begin_http_close(server, transport):
    """Called only by the original server's close_request implementation.

    A matching original pending transport is retained before its close. The
    fixed array is not resized; a pending entry cannot be replaced by admission.
    This records cleanup ownership only and cannot issue or release read DATA.
    """
    for entry in _ENTRIES:
        if (entry is not None and entry.server is server
                and entry.transport is transport):
            if entry.transport_stage != 'owned-by-http-server':
                return entry, False
            entry.transport_stage = 'http-close-pending'
            return entry, True
    return None, True  # Preserve original closure for unrelated HTTP requests.


def _end_http_close(entry, failure):
    if entry is None:
        return failure
    if failure is not None:
        entry.transport_stage = 'http-close-uncertain'
        entry.transport_failure = failure
        _remember(entry, failure)
        return entry.failure
    entry.transport_stage = 'closed-by-http-server'
    # The original server calls close_request after finish_request has left the
    # original handler, including its finish path. This is not a timer/abort,
    # supplied receipt or permission to resume a failed read/send. Preserve
    # those pending-stage observations and first failure after transport ends.
    _settle_entry(entry)
    return None


def _one(headers, name, *, required=False):
    values = headers.get_all(name, [])
    if len(values) > 1 or required and len(values) != 1:
        raise _Refused(400)
    return values[0] if values else None


def _headers(handler):
    pairs = list(handler.headers.raw_items())
    if len(pairs) > 64 or sum(len(k) + len(v) + 4 for k, v in pairs) > 16384:
        raise _Refused(400)
    for key, value in pairs:
        if not key.isascii() or not value.isascii() or any(
                ord(c) < 32 or ord(c) == 127 for c in key + value):
            raise _Refused(400)
    # Duplicate fields, even unrelated ones, have no interpretation here.
    names = [k.lower() for k, _ in pairs]
    if len(names) != len(set(names)):
        raise _Refused(400)
    for name in ('Transfer-Encoding', 'Content-Encoding', 'Expect',
                 'Authorization', 'Trailer'):
        if _one(handler.headers, name) is not None:
            raise _Refused(400)


def _direct_tls(handler):
    # No forwarded-header, reverse-proxy, HTTP or environment fallback.
    return type(handler.connection) is ssl.SSLSocket


def _capture(entry):
    entry.remaining()  # Original cutoff; no new source acquisition after expiry.
    context = object.__new__(read_source_epoch.source_read)
    entry.source_contexts[0] = context
    read_source_epoch.source_read.__init__(context)
    with context:
        _capture_under_source(entry)


def _capture_under_source(entry):
    handler = entry.handler
    if not _direct_tls(handler):
        raise _Refused(403)
    host = _one(handler.headers, 'Host', required=True)
    origin = _one(handler.headers, 'Origin', required=True)
    if (not host or len(host) > 255 or host != host.strip()
            or any(c in host for c in '/\\@?# ,')
            or origin.lower() != 'https://' + host.lower()):
        raise _Refused(403)
    site = _one(handler.headers, 'Sec-Fetch-Site')
    if site is not None and site != 'same-origin':
        raise _Refused(403)
    cookies = _one(handler.headers, 'Cookie') or ''
    tokens = [part.strip()[len('freq_session='):]
              for part in cookies.split(';')
              if part.strip().startswith('freq_session=')]
    if len(tokens) != 1 or not _TOKEN.fullmatch(tokens[0]):
        raise _Refused(401)
    supplied = _one(handler.headers, 'X-Freq-CSRF')
    entry.lock = auth._auth_lock
    with _auth_gate(entry, final=False):
        if auth._auth_lock is not entry.lock:
            raise _Refused(503)
        entry.registry = auth._auth_tokens
        entry.token = tokens[0]
        entry.session = entry.registry.get(entry.token)
        if type(entry.session) is not dict:
            raise _Refused(401)
        entry.user = entry.session.get('user')
        entry.role = entry.session.get('role')
        entry.csrf = entry.session.get('csrf_token')
        if not _current_locked(entry):
            raise _Refused(401)
        if (type(supplied) is not str or not _TOKEN.fullmatch(supplied)
                or not secrets.compare_digest(entry.csrf, supplied)):
            raise _Refused(403)
        entry.remaining()
    # Authentication has returned its gate. The lexical original source gate
    # remains owned, so participating writers cannot change these files during
    # capture. No provider or HTTP IO occurs under it, and positive admission
    # still refuses independently of this private raw configuration result.
    entry.remaining()
    capture = object.__new__(standard_qemu_sources.ConfigurationCapture)
    entry.configuration = capture
    standard_qemu_sources.ConfigurationCapture.__init__(
        capture, entry.source_contexts[0], entry.end)
    raw = capture.run()
    entry.remaining()
    entry.configuration_data = standard_qemu_configuration.decode_private_configuration(*raw)
    if (entry.user, entry.role) not in entry.configuration_data[1]:
        raise _Refused(401)
    entry.remaining()
    runtime = object.__new__(standard_qemu_runtime_identity.RuntimeIdentityCapture)
    entry.runtime_identity = runtime
    standard_qemu_runtime_identity.RuntimeIdentityCapture.__init__(
        runtime, entry.source_contexts[0], entry.end, entry.configuration_data[2])
    runtime.run()


def _current_locked(entry):
    current = auth._auth_tokens.get(entry.token)
    if (auth._auth_lock is not entry.lock or auth._auth_tokens is not entry.registry
            or current is not entry.session or type(current) is not dict
            or current.get('user') != entry.user
            or current.get('role') != entry.role
            or current.get('csrf_token') != entry.csrf
            or type(entry.user) is not str or not 0 < len(entry.user) <= 128
            or entry.role not in ('viewer', 'operator', 'admin', 'protected')
            or type(entry.csrf) is not str or not _TOKEN.fullmatch(entry.csrf)):
        return False
    last = current.get('last_activity_ts', current.get('ts'))
    return (type(last) in (int, float) and math.isfinite(last)
            and 0 <= time.time() - last < auth.SESSION_TIMEOUT_SECONDS)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise _Refused(400)
        result[key] = value
    return result


def _request(entry):
    handler = entry.handler
    if handler.command != 'POST' or handler.path not in _KEYS:
        raise _Refused(400)
    media = _one(handler.headers, 'Content-Type', required=True)
    if media.lower() not in ('application/json', 'application/json; charset=utf-8'):
        raise _Refused(400)
    size = _one(handler.headers, 'Content-Length', required=True)
    if not re.fullmatch(r'[1-9][0-9]{0,3}', size) or int(size) > 2048:
        raise _Refused(400)
    remaining = int(size)
    raw = bytearray()
    while remaining:
        entry.stage = 'body-read-pending'
        entry.body_stage = 'pending'
        handler.connection.settimeout(entry.remaining())
        piece = handler.rfile.read1(remaining)
        entry.stage = 'body-read-returned'
        entry.body_stage = 'returned'
        entry.remaining()
        if type(piece) is not bytes or not 0 < len(piece) <= remaining:
            raise _Refused(400)
        raw.extend(piece)
        remaining -= len(piece)
    # The request grammar is a flat object of refs/null. Bound structure BEFORE
    # json.loads; the 2048-byte cap alone does not bound recursive nesting.
    depth = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char == 91 or char == 93:
            raise _Refused(400)
        elif char == 123:
            depth += 1
            if depth > 1:
                raise _Refused(400)
        elif char == 125:
            depth -= 1
            if depth < 0:
                raise _Refused(400)
    try:
        body = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=_pairs)
    except (UnicodeError, ValueError):
        raise _Refused(400) from None
    if type(body) is not dict or frozenset(body) != _KEYS[handler.path]:
        raise _Refused(400)
    for key, value in body.items():
        if key == 'previous_view_ref' and value is None:
            continue
        if type(value) is not str or not _REF.fullmatch(value):
            raise _Refused(400)
    entry.remaining()
    entry.request_data = body
    return body


def _final_auth(entry):
    entry.remaining()  # Original cutoff; no new source acquisition after expiry.
    context = object.__new__(read_source_epoch.source_read)
    entry.source_contexts[1] = context
    read_source_epoch.source_read.__init__(context)
    with context:
        # Necessary participating-writer refusal only. This does not acquire
        # configuration/trust/credentials or create a source/view/read grant.
        if not context.same_epoch(entry.source_contexts[0]):
            raise _Refused(503)
        entry.remaining()
        # Fresh original bytes/descriptor observations are an additional
        # refusal filter only, never external-writer exclusion or provenance.
        capture = object.__new__(standard_qemu_sources.ConfigurationCapture)
        entry.final_configuration = capture
        standard_qemu_sources.ConfigurationCapture.__init__(capture, context, entry.end)
        capture.run()
        previous = entry.configuration
        if (capture._root != previous._root or capture._parts != previous._parts
                or capture._directory_count != previous._directory_count
                or capture._ids != previous._ids or capture._result != previous._result):
            raise _Refused(503)
        entry.remaining()
        runtime = object.__new__(standard_qemu_runtime_identity.RuntimeIdentityCapture)
        entry.final_runtime_identity = runtime
        standard_qemu_runtime_identity.RuntimeIdentityCapture.__init__(
            runtime, context, entry.end, entry.configuration_data[2])
        runtime.run()
        # Necessary fresh process/NSS observation only. Equality cannot prove
        # atomic NSS provenance, external-writer exclusion or a read grant.
        if runtime._result != entry.runtime_identity._result:
            raise _Refused(503)
        with _auth_gate(entry, final=True):
            if not _current_locked(entry):
                raise _Refused(401)
            entry.remaining()
            _prepare_unissued_opening(entry)



class _ViewOpening:
    """Original unissued capacity holder; cannot create a usable view/ref.

    Retain on the exact original entry before the nonqueued view gate. Its
    known cancellation retires only its own unissued placeholder. Unknown
    acquire/release keeps the request and reservation; no timeout eviction.
    """
    __slots__ = ('entry', 'thread', 'session', 'registry', 'token', 'source',
                 'end', 'stage', 'slot', 'used', 'body_failure',
                 'release_failure', 'failure', 'cancel_failure', 'provider_preparation', 'reference_candidate',
                 'configuration_data')

    def __init__(self, entry):
        self.entry = entry
        self.thread = threading.current_thread()
        self.session, self.registry, self.token = entry.session, entry.registry, entry.token
        self.source = entry.source_contexts[1]
        # Same original capture projection, including original endpoint spelling
        # and configured principal metadata. This unissued view grants no IO.
        self.configuration_data = entry.configuration_data
        self.end = time.monotonic() + 30.0
        self.stage, self.slot, self.used = 'preparing', None, False
        self.body_failure = self.release_failure = self.failure = self.cancel_failure = None
        # Retain each known pure descendant before its initializer can fail.
        # A partial holder grants no readiness, acquisition or cancellation.
        provider = object.__new__(_ProviderPreparation)
        self.provider_preparation = provider
        _ProviderPreparation.__init__(provider, self)
        reference = object.__new__(_ViewReferenceCandidate)
        self.reference_candidate = reference
        _ViewReferenceCandidate.__init__(reference, self)
        self.stage = 'prepared'

    def _current(self):
        e, c = self.entry, self.source
        e.remaining()
        if (type(e) is not _Entry or not any(item is e for item in _ENTRIES)
                or e.retention_stage != 'retained' or e.view_opening is not self
                or threading.current_thread() is not self.thread
                or e.auth_stages[1] != 'owned' or not _current_locked(e)
                or c is not e.source_contexts[1] or c.thread is not self.thread
                or c.stage != 'captured' or c.rejected or not c._retained
                or read_source_epoch._readers.get(id(c)) is not c
                or c.epoch is not read_source_epoch._epoch
                or self.configuration_data is not e.configuration_data
                or self.session is not e.session or self.registry is not e.registry
                or self.token != e.token or not time.monotonic() < self.end):
            raise _Refused(503)

    def run(self):
        if self.used or threading.current_thread() is not self.thread:
            raise _Refused(503)
        self.used = True
        self._current()
        # Source reads serialize this original path. Uncertain view duties in
        # a retained original request prevent a new opening even if the native
        # lock was actually released before its return was lost.
        for e in _ENTRIES:
            other = e.view_opening if e is not None else None
            if (other is not None and other is not self
                    and other.stage not in ('prepared', 'not-acquired', 'refused', 'retired-unissued')):
                self.stage = 'refused'
                raise _Refused(503)
        self.stage = 'acquire-pending'
        try:
            acquired = _VIEW_GATE.acquire(blocking=False)
        except BaseException as failure:
            self.failure = failure
            raise
        if not acquired:
            self.stage = 'not-acquired'
            raise _Refused(503)
        self.stage = 'owned'
        try:
            self._current()
            same_session = 0
            available = None
            for index, current in enumerate(_VIEW_OPENINGS):
                if current is None or current.stage == 'retired-unissued':
                    if available is None:
                        available = index
                elif (current.session is self.session
                        and current.registry is self.registry
                        and current.token == self.token):
                    same_session += 1
            if available is None or same_session >= 16:
                raise _Refused(503)
            # Root the exact holder before any future issuer/provider work.
            # This prefix deliberately has neither: there is no ref, target,
            # credential, attempt dispatch or positive readiness flag.
            self.slot = available
            _VIEW_OPENINGS[available] = self
            self.stage = 'reserved-unissued'
            self._current()
            self.provider_preparation.reserve()
            self.reference_candidate.prepare()
        except BaseException as failure:
            self.body_failure = self.failure = failure
        # No issued descendants/resources exist. Logical cancellation is local
        # to this exact unissued placeholder, independent of body failure. The
        # slot is reusable only AFTER a known view-gate release below.
        self.stage = 'release-pending'
        try:
            _VIEW_GATE.release()
        except BaseException as failure:
            self.release_failure = failure
        else:
            # No entered credential/provider duty exists in this prefix. Known
            # release permits only this exact never-entered descendant to
            # cancel; a future entered/uncertain duty cannot be refunded here.
            self.stage = 'release-returned'
            try:
                cancelled = self.provider_preparation.cancel_unentered()
                reference_known = self.reference_candidate.known_unissued() if cancelled else False
            except BaseException as failure:
                self.cancel_failure = failure
                self.stage = 'provider-unsettled'
            else:
                if not cancelled:
                    self.stage = 'provider-unsettled'
                elif reference_known:
                    self.stage = 'retired-unissued'
                else:
                    self.stage = 'reference-unsettled'
        self.failure = _first_failure(self.failure, self.release_failure)
        self.failure = _first_failure(self.failure, self.cancel_failure)
        if self.failure is not None:
            raise self.failure from None



class _ProviderPreparation:
    """Finite unentered provider capacity; no secret or transport acquisition.

    This original descendant is prepared before view-gate acquisition. Capacity
    reservation does not authorize its future entry. Neither an issued view nor
    source/incarnation/provider admission exists in the current original path.
    """
    __slots__ = ('opening', 'thread', 'end', 'stage', 'slot', 'used', 'failure',
                 'runtime_identity', 'system_trust', 'node_token', 'transport',
                 'configuration_data')

    def __init__(self, opening):
        self.opening = opening
        self.configuration_data = opening.configuration_data
        self.thread = threading.current_thread()
        self.end = min(opening.entry.end, opening.end)
        self.stage, self.slot, self.used = 'prepared', None, False
        self.failure = None
        # Root each future independent obligation BEFORE any acquisition.
        # They remain absent; this prefix never opens a secret or provider.
        self.runtime_identity = self.system_trust = self.node_token = self.transport = None
        trust = object.__new__(standard_qemu_private_files.SystemTrustCapture)
        self.system_trust = trust
        standard_qemu_private_files.SystemTrustCapture.__init__(
            trust, opening.source, self.end)

    def _current(self):
        o = self.opening
        o._current()
        if (type(o) is not _ViewOpening or o.provider_preparation is not self
                or self.configuration_data is not o.configuration_data
                or threading.current_thread() is not self.thread
                or o.stage != 'reserved-unissued' or o.slot is None
                or _VIEW_OPENINGS[o.slot] is not o
                or self.end != min(o.entry.end, o.end)
                or not time.monotonic() < self.end):
            raise _Refused(503)

    def reserve(self):
        if self.used or threading.current_thread() is not self.thread:
            raise _Refused(503)
        self.used = True
        try:
            self._current()
            available = None
            for index, current in enumerate(_PROVIDER_PREPARATIONS):
                if current is None or current.stage == 'cancelled-unentered':
                    if available is None:
                        available = index
                elif current.opening is self.opening:
                    raise _Refused(503)  # One outstanding preparation per view.
            if available is None:
                raise _Refused(503)
            self.slot = available
            _PROVIDER_PREPARATIONS[available] = self
            self.stage = 'reserved-unentered'
            self._current()
        except BaseException as failure:
            self.failure = failure
            raise

    def cancel_unentered(self):
        # Called only by this exact original opening after known view-gate
        # release. Do not infer closure from a wrapper, expiry or HTTP finish.
        if (self.opening.provider_preparation is not self
                or self.opening.stage != 'release-returned'
                or self.slot is not None and _PROVIDER_PREPARATIONS[self.slot] is not self
                or threading.current_thread() is not self.thread
                or self.stage not in ('prepared', 'reserved-unentered')
                or any(value is not None for value in (self.runtime_identity,
                    self.node_token, self.transport))):
            return False
        trust = self.system_trust
        if (type(trust) is not standard_qemu_private_files.SystemTrustCapture
                or trust._context is not self.opening.source or trust._end != self.end
                or trust._thread is not self.thread or trust._used is not False
                or trust._state != 'prepared'
                or type(trust._fds) is not list or len(trust._fds) != 5
                or any(fd is not None for fd in trust._fds)
                or type(trust._stages) is not list or len(trust._stages) != 5
                or any(type(stage) is not str or stage != 'unused' for stage in trust._stages)):
            return False
        # Only this original never-entered pure holder can be spent locally.
        # No open/close, success, native closure or resource refund is inferred.
        trust._used = True
        trust._state = 'cancelled-unentered'
        self.stage = 'cancelled-unentered'
        return True



class _ViewReferenceCandidate:
    """Original private random candidate, never an issued view or read grant.

    A bounded monotonically consumed history index precedes entropy. Unknown
    entropy return keeps the original opening; known candidates remain in the
    process history even after cancellation and can never be accepted twice.
    No caller supplies entropy, a reference, eligibility or a history owner.
    """
    __slots__ = ('opening', 'thread', 'end', 'used', 'stage', 'index', 'value',
                 'failure')

    def __init__(self, opening):
        self.opening = opening
        self.thread = threading.current_thread()
        self.end = min(opening.entry.end, opening.end)
        self.used, self.stage, self.index = False, 'prepared', None
        self.value = self.failure = None

    def _current(self):
        o = self.opening
        o._current()
        p = o.provider_preparation
        if (type(o) is not _ViewOpening or o.reference_candidate is not self
                or threading.current_thread() is not self.thread
                or o.stage != 'reserved-unissued' or o.slot is None
                or _VIEW_OPENINGS[o.slot] is not o
                or type(p) is not _ProviderPreparation
                or p.stage != 'reserved-unentered' or p.slot is None
                or _PROVIDER_PREPARATIONS[p.slot] is not p
                or self.end != min(o.entry.end, o.end)
                or not time.monotonic() < self.end):
            raise _Refused(503)

    def prepare(self):
        if self.used or threading.current_thread() is not self.thread:
            raise _Refused(503)
        self.used = True
        try:
            self._current()
            self.stage = 'history-pending'
            try:
                index = next(_REFERENCE_INDEX)
            except StopIteration:
                self.stage = 'history-exhausted'
                raise _Refused(503) from None
            self.index = index
            _REFERENCE_HISTORY[index] = _REFERENCE_PENDING
            self.stage = 'entropy-pending'
            value = secrets.token_hex(32)
            self.value = value
            self.stage = 'entropy-returned'
            if type(value) is not str or not _REF.fullmatch(value):
                self.stage = 'invalid-return'
                raise _Refused(503)
            # Preserve every valid returned candidate before validation/current
            # checks. Never remove it when this unissued opening is cancelled.
            _REFERENCE_HISTORY[index] = value
            self.stage = 'recorded-unissued'
            for previous in _REFERENCE_HISTORY[:index]:
                if type(previous) is str and previous == value:
                    raise _Refused(503)  # Collision consumes; no entropy retry.
            self._current()
            self.stage = 'candidate-unissued'
            return value  # Private original caller DATA only; never HTTP/ref grant.
        except BaseException as failure:
            self.failure = failure
            raise

    def known_unissued(self):
        return self.stage in ('prepared', 'history-exhausted', 'invalid-return',
                              'recorded-unissued', 'candidate-unissued')



class _UnissuedRecipient:
    """Original storage only; no selected issuer, read, grant or public value."""
    __slots__ = ('stage', 'entry', 'opening', 'thread', 'end', 'handler',
                 'server', 'transport', 'streams', 'registry', 'session',
                 'token', 'user', 'role', 'source_contexts',
                 'configuration_data', 'request_data', 'selected_original',
                 'operation_selection', 'read_stage', 'result', 'failures')

    def __init__(self, entry, opening):
        if type(self) is not _UnissuedRecipient or hasattr(self, 'stage'):
            raise _Refused(503)
        self.stage = 'preparing'
        self.entry, self.opening = entry, opening
        if (type(entry) is not _Entry or type(opening) is not _ViewOpening
                or entry.recipient_preparation is not self
                or entry.view_opening is not opening or opening.entry is not entry
                or opening.stage != 'prepared'):
            raise _Refused(503)
        self.thread = threading.current_thread()
        self.end = min(entry.end, opening.end)
        self.handler, self.server = entry.handler, entry.server
        self.transport, self.streams = entry.transport, entry.streams
        self.registry, self.session, self.token = entry.registry, entry.session, entry.token
        self.user, self.role = entry.user, entry.role
        self.source_contexts = entry.source_contexts
        self.configuration_data, self.request_data = entry.configuration_data, entry.request_data
        # Future exact original selection/store/issuer work is still absent.
        # These empty slots confer no authority or permission to enter a read.
        self.selected_original = self.operation_selection = self.result = None
        self.read_stage = 'unused'
        self.failures = [None] * 4
        self.stage = 'unissued'

    def known_unissued(self, entry):
        # A missing final marker on a partial initializer retains its parent.
        # This only permits pure unissued storage settlement, never publication.
        if type(self) is not _UnissuedRecipient or getattr(self, 'stage', None) != 'unissued':
            return False
        return (self.entry is entry and entry.recipient_preparation is self
                and self.opening is entry.view_opening and self.opening.entry is entry
                and threading.current_thread() is self.thread
                and self.end == min(entry.end, self.opening.end)
                and self.handler is entry.handler and self.server is entry.server
                and self.transport is entry.transport and self.streams is entry.streams
                and self.registry is entry.registry and self.session is entry.session
                and self.token is entry.token and self.user is entry.user and self.role is entry.role
                and self.source_contexts is entry.source_contexts
                and self.configuration_data is entry.configuration_data
                and self.request_data is entry.request_data
                and self.selected_original is None and self.operation_selection is None
                and self.read_stage == 'unused' and self.result is None
                and type(self.failures) is list and len(self.failures) == 4
                and all(error is None for error in self.failures))


def _prepare_unissued_recipient(entry, opening):
    if type(entry) is not _Entry or type(opening) is not _ViewOpening:
        raise _Refused(503)
    if entry.recipient_preparation is not None:
        raise _Refused(503)
    recipient = object.__new__(_UnissuedRecipient)
    entry.recipient_preparation = recipient
    _UnissuedRecipient.__init__(recipient, entry, opening)


def _prepare_unissued_opening(entry):
    # Caller is the original final source/auth critical section after request
    # grammar, configured user and fresh runtime checks. No positive issuer is
    # implemented, so reserve and cancel without a reference or provider effect.
    if entry.view_opening is not None or entry.recipient_preparation is not None:
        raise _Refused(503)
    if (entry.handler.path != PREFIX + 'open'
            or entry.request_data['previous_view_ref'] is not None):
        return
    # Root the known pure holder before initializing its private descendants.
    opening = object.__new__(_ViewOpening)
    entry.view_opening = opening
    _ViewOpening.__init__(opening, entry)
    _prepare_unissued_recipient(entry, opening)
    opening.run()


def _write_refusal(entry, status):
    # One attempt consumed before the first fallible header operation. There is
    # no legacy JSON wrapper, session refresh, second error body or retry.
    if entry.response_started:
        return
    entry.response_started = True
    entry.stage = 'response-pending'
    entry.response_stage = 'pending'
    handler = entry.handler
    body = _BODIES[status]
    handler.connection.settimeout(entry.remaining())
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Connection', 'close')
    handler.connection.settimeout(entry.remaining())
    handler.end_headers()
    handler.connection.settimeout(entry.remaining())
    handler.wfile.write(body)
    handler.connection.settimeout(entry.remaining())
    handler.wfile.flush()
    entry.stage = 'response-returned'
    entry.response_stage = 'returned'


def _remember(entry, failure):
    entry.failure = _first_failure(entry.failure, failure)


def _first_failure(first, failure):
    if failure is None:
        return first
    if first is None or issubclass(type(first), Exception) and (
            not issubclass(type(failure), Exception)
            or not issubclass(type(first), MemoryError)
            and issubclass(type(failure), MemoryError)):
        return failure
    return first


@contextmanager
def _auth_gate(entry, *, final):
    """One original auth gate; retain body failure before independent release.

    An unreturned acquire remains pending. Release is attempted exactly once
    only after a known acquired result; losing its return is not closure proof.
    This private context cannot enable positive source admission.
    """
    prefix, index = ('final-auth', 2) if final else ('auth', 0)
    stage_index = 1 if final else 0
    entry.remaining()
    entry.auth_stages[stage_index] = 'acquire-pending'
    entry.stage = prefix + '-lock-pending'
    if not entry.lock.acquire(blocking=False):
        entry.stage = prefix + '-lock-refused'
        entry.auth_stages[stage_index] = 'not-acquired'
        raise _Refused(503)
    entry.stage = prefix + '-lock-owned'
    entry.auth_stages[stage_index] = 'owned'
    try:
        yield
    except BaseException as failure:
        entry.auth_failures[index] = failure
        _remember(entry, failure)
    # Save the exact body failure above BEFORE any release/cleanup/classifier.
    entry.stage = prefix + '-release-pending'
    entry.auth_stages[stage_index] = 'release-pending'
    try:
        entry.lock.release()
    except BaseException as failure:
        entry.auth_failures[index + 1] = failure
        _remember(entry, failure)
    else:
        entry.stage = prefix + '-returned'
        entry.auth_stages[stage_index] = 'returned'
    if entry.failure is not None:
        raise entry.failure from None


def handle(handler):
    """Original HTTP entry. This unfinished positive path only refuses safely.

    Handler owns its parsed request/socket; no supplied service, acceptance flag
    or callback enables source acquisition. Tests may replace I/O seams but
    cannot establish original login, TLS or live application acceptance.
    """
    handler.close_connection = True
    if getattr(handler, '_standard_observe_entry', None) is not None:
        return
    # Same original handler owns the blank BEFORE clock/attribute/allocation
    # helpers in the initializer. This is custody only, never read authority.
    entry = object.__new__(_Entry)
    entry.handler = handler
    entry.retention_stage = 'unreserved'
    entry.stage = 'initialization-pending'
    entry.failure = None
    entry.dispatch_failure = entry.settlement_failure = None
    entry.initialization_pending = entry.initialization_returned = False
    entry.initialization_return = entry.initialization_failure = None
    entry.initialization_complete = False
    handler._standard_observe_entry = entry
    pending = returned = False
    actual = None
    try:
        # Original FreqHandler captures this request start before dispatch.
        # No fallback sample may replace its identity or renew the deadline.
        started = getattr(handler, '_request_started', None)
        server = getattr(handler, 'server', None)
        transport = handler.connection
        write_stream, read_stream = handler.wfile, handler.rfile
        pending = True
        entry.initialization_pending = True
        actual = _Entry.__init__(entry, handler)
        entry.initialization_return = actual  # Actual return BEFORE validation.
        returned = True
        pending = False
        entry.initialization_returned = True
        entry.initialization_pending = False
        # No project validation helper follows this complete constructor tail.
        if not (actual is None and type(entry) is _Entry
                and handler._standard_observe_entry is entry
                and entry.handler is handler and entry.server is server
                and entry.transport is transport
                and type(started) in (int, float) and math.isfinite(started)
                and 0 <= started and type(entry.end) is float
                and math.isfinite(entry.end) and entry.end == started + 10.0
                and type(entry.stage) is str and entry.stage == 'retained'
                and type(entry.retention_stage) is str
                and entry.retention_stage == 'unreserved'
                and entry.failure is None and entry.dispatch_failure is None
                and entry.settlement_failure is None
                and entry.response_started is False
                and entry.registry is None and entry.lock is None
                and entry.token is None and entry.session is None
                and entry.user is None and entry.role is None and entry.csrf is None
                and type(entry.auth_failures) is list and len(entry.auth_failures) == 4
                and entry.auth_failures[0] is None and entry.auth_failures[1] is None
                and entry.auth_failures[2] is None and entry.auth_failures[3] is None
                and type(entry.auth_stages) is list and len(entry.auth_stages) == 2
                and type(entry.auth_stages[0]) is str and entry.auth_stages[0] == 'unused'
                and type(entry.auth_stages[1]) is str and entry.auth_stages[1] == 'unused'
                and type(entry.body_stage) is str and entry.body_stage == 'unused'
                and type(entry.response_stage) is str and entry.response_stage == 'unused'
                and type(entry.transport_stage) is str
                and entry.transport_stage == 'owned-by-http-server'
                and entry.transport_failure is None
                and type(entry.streams) is tuple and len(entry.streams) == 2
                and entry.streams[0] is write_stream and entry.streams[1] is read_stream
                and type(entry.stream_stages) is list and len(entry.stream_stages) == 2
                and type(entry.stream_stages[0]) is str and entry.stream_stages[0] == 'owned'
                and type(entry.stream_stages[1]) is str and entry.stream_stages[1] == 'owned'
                and type(entry.stream_failures) is list and len(entry.stream_failures) == 3
                and entry.stream_failures[0] is None and entry.stream_failures[1] is None
                and entry.stream_failures[2] is None
                and type(entry.source_contexts) is list and len(entry.source_contexts) == 2
                and entry.source_contexts[0] is None and entry.source_contexts[1] is None
                and entry.configuration is None and entry.final_configuration is None
                and entry.configuration_data is None and entry.runtime_identity is None
                and entry.final_runtime_identity is None and entry.request_data is None
                and entry.view_opening is None and entry.recipient_preparation is None
                and entry.initialization_pending is False
                and entry.initialization_returned is True
                and entry.initialization_return is actual
                and entry.initialization_failure is None
                and entry.initialization_complete is False):
            raise _Refused(503)
        entry.initialization_complete = True  # Constructor only, never authority.
    except BaseException as failure:
        # Actual local observations override poisoned mirrors. No classifier,
        # table/auth/body/send/settlement helper or guessed cleanup enters here.
        handler._standard_observe_entry = entry
        entry.handler = handler
        entry.retention_stage = 'unreserved'
        entry.stage = 'initialization-failed'
        entry.initialization_pending = pending
        entry.initialization_returned = returned
        entry.initialization_return = actual
        entry.initialization_failure = failure
        entry.initialization_complete = False
        entry.failure = failure
        entry.dispatch_failure = entry.settlement_failure = None
        raise
    if not _retain_entry(entry):
        # No new response acquisition when no original holder is available.
        # The original HTTP owner closes this request; no legacy fallback.
        return
    try:
        _handle_retained(entry)
    except BaseException as failure:
        entry.dispatch_failure = failure
    # Retain the escaping body before independent bookkeeping. A later
    # settlement failure cannot replace an earlier protected raw failure.
    try:
        _settle_entry(entry)
    except BaseException as failure:
        entry.settlement_failure = failure
    failure = _first_failure(entry.dispatch_failure, entry.settlement_failure)
    if failure is not None:
        _remember(entry, failure)
        raise failure from None


def _handle_retained(entry):
    handler = entry.handler
    status = 503
    try:
        _headers(handler)
        _capture(entry)
        _request(entry)
        _final_auth(entry)
        # Deliberate original refusal: actual source/writer/strong-incarnation
        # ownership and view/reference issuance have not been implemented.
    except _Refused as failure:
        status = failure.status
    except BaseException as failure:
        _remember(entry, failure)
        if not issubclass(type(failure), Exception) or issubclass(type(failure), MemoryError):
            raise
        status = 503
    try:
        _write_refusal(entry, status)
    except BaseException as failure:
        _remember(entry, failure)
        if not issubclass(type(failure), Exception) or issubclass(type(failure), MemoryError):
            raise
        # Socket/header failure has no second interpretation or output path.
