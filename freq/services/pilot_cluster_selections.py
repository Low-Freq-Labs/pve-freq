"""Original observed inventory/binding transactions; uninstalled source.

The actual installation factory is absent. These operations can only use its
retained configured cohort, actual auth session and dedicated observed reference
tables. No supplied config, service, map, parser, target, issuer or commit
callback can initialize this component. Exact type checks are refusal filters,
not proof of native/code/principal/writer authority. The fixed native-current
operation and original outer custody must be implemented and qualified first.
"""
import hmac
import json
import math
import secrets
import time

from freq.api import auth
from freq.services.cluster_pilot_http import OriginalPilotResponse, _RequestUnavailable
from freq.services.cluster_references import ClusterReferences, TargetSnapshot, _Reference
from freq.services.pilot_auth_commit import OriginalAuthCommit, _OrderedAuthGates


_UNAVAILABLE = 'cluster_observation_unavailable'
_MIB = 1048576


class _SelectionRefused(_RequestUnavailable):
    """Fixed original dispatcher may select only this bounded error status."""
    def __init__(self, status):
        if type(status) is not int or status not in (400, 403, 409, 503, 504):
            status = 503
        self.status = status
        super().__init__(_UNAVAILABLE)


def _frame(value, maximum):
    # Fixed internal document shapes only, outside ALL admission locks.
    body = json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(body) > maximum:
        raise _SelectionRefused(503)
    return OriginalPilotResponse(200, body, 'application/json')


def _label(value):
    return (type(value) is str and bool(value) and
            not any(ord(c) < 32 or 127 <= ord(c) <= 159 or
                    0xd800 <= ord(c) <= 0xdfff for c in value) and
            len(value.encode('utf-8')) <= 256)


class OriginalClusterSelections:
    """Fixed configured inventory and nonextended observed binding admission.

    Required private factory fields: _auth_commit, _configured_nodes (exact
    tuple of (literal label, original TargetSnapshot) pairs), and
    _configuration_revision. The SAME native cohort owns these objects through
    the final transaction. Matching strings or a caller-built tuple cannot
    establish that ownership. No original factory is provided in this file.
    """
    def __init__(self, installation):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(installation) is not OriginalPilotInstallation or
                type(installation._auth_commit) is not OriginalAuthCommit or
                installation._auth_commit._installation is not installation or
                type(installation._references) is not ClusterReferences or
                installation._references is not installation._auth_commit._references):
            raise _SelectionRefused(503)
        self._installation = installation
        self._auth = installation._auth_commit
        self._broker = self._auth._broker
        self._references = self._auth._references

    def _native_session_locked(self, original, token, session, values):
        # Fixed ordered helper also checks actual request/native-cohort identity,
        # live/uncertainty, original thread/end/server and original ready phase.
        self._auth._current_locked(original, 'ready')
        if not self._auth._same_session_locked(token, session, values, time.time()):
            raise _SelectionRefused(403)

    def _cohort_locked(self):
        owner = self._installation
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(owner) is not OriginalPilotInstallation or
                OriginalPilotInstallation._original_configured_data_current(owner) is not True):
            raise _SelectionRefused(503)
        nodes = owner._configured_nodes
        revision = owner._configuration_revision
        if (type(nodes) is not tuple or len(nodes) > 1024 or
                type(revision) is not str or not 0 < len(revision) <= 512):
            raise _SelectionRefused(503)
        labels, targets = set(), set()
        for row in nodes:
            if (type(row) is not tuple or len(row) != 2 or not _label(row[0]) or
                    type(row[1]) is not TargetSnapshot or
                    not self._references._valid_target(row[1]) or
                    row[1].configuration_revision != revision or
                    row[0] in labels or id(row[1]) in targets):
                raise _SelectionRefused(503)
            labels.add(row[0]); targets.add(id(row[1]))
        return nodes

    def _tables_locked(self, now):
        references = self._references
        maps = (references._selections, references._bindings)
        if (any(type(table) is not dict for table in maps) or
                sum(len(table) for table in maps) > references.PROCESS_LIMIT):
            raise _SelectionRefused(503)
        for table in maps:
            for key, record in table.items():
                if (not references._valid_reference(key) or
                        type(record) is not _Reference or
                        type(record.session) is not dict or
                        not references._valid_target(record.target) or
                        type(record.expires) is not float or
                        not math.isfinite(record.expires)):
                    raise _SelectionRefused(503)
        # Remove only actually expired references. Never revoke a live old card
        # to create capacity, nor turn a retired row into a fresh selection.
        try:
            references._expire(now)
        except BaseException as error:
            raise self._auth._uncertain(error)
        return tuple((table, tuple(table.items())) for table in maps)

    def _same_tables_locked(self, snapshot):
        for table, (original_table, before) in zip((self._references._selections,
                                                   self._references._bindings), snapshot):
            if (table is not original_table or type(table) is not dict or
                    len(table) != len(before) or
                    any(table.get(key) is not record for key, record in before)):
                return False
        return True

    def _capture(self, handler, operation):
        if (not auth._cluster_pilot_direct_tls(handler) or
                not auth.same_origin_or_absent(handler,
                    require_present=operation == 'bind', is_https=True)):
            raise _SelectionRefused(403)
        original, token, source, session, values = self._auth._capture_session(handler, operation)
        with _OrderedAuthGates(self._auth, original):
            self._native_session_locked(original, token, session, values)
            if operation == 'bind' and source != 'bearer':
                supplied = handler.headers.get('X-Freq-CSRF', '')
                if (values is None or type(values[4]) is not str or
                        type(supplied) is not str or not supplied.isascii() or
                        not values[4].isascii() or
                        not hmac.compare_digest(supplied, values[4])):
                    raise _SelectionRefused(403)
            nodes = self._cohort_locked()
            now = time.monotonic()
            if not math.isfinite(now) or not now < original.end:
                raise _SelectionRefused(504)
            snapshot = self._tables_locked(now)
        return original, token, session, values, nodes, now, snapshot

    @staticmethod
    def _new_key(used):
        # Outside all gates; no unbounded retry. Randomness is native work and
        # still needs the original request/outer supervised resource custody.
        for _ in range(4):
            key = secrets.token_hex(16)
            if type(key) is not str or not ClusterReferences._valid_reference(key):
                raise _SelectionRefused(503)
            if key not in used:
                used.add(key)
                return key
        raise _SelectionRefused(503)

    def _revalidate_locked(self, original, token, session, values, nodes, snapshot):
        self._native_session_locked(original, token, session, values)
        if (self._installation._configured_nodes is not nodes or
                self._cohort_locked() is not nodes or
                not self._same_tables_locked(snapshot)):
            # Another original reference transaction may have completed during
            # serialization. Refuse this request; do not retry/rebuild/extend it.
            raise _SelectionRefused(409)

    def admit_inventory(self, handler):
        captured = self._capture(handler, 'inventory')
        original, token, session, values, nodes, now, snapshot = captured
        selections, bindings = (rows for original_table, rows in snapshot)
        available = min(self._references.SELECTIONS_PER_SESSION -
                        sum(record.session is session for _, record in selections),
                        self._references.PROCESS_LIMIT - len(selections) - len(bindings))
        if available < 0:
            raise _SelectionRefused(503)
        used = {key for original_table, rows in snapshot for key, _ in rows}
        additions, public = [], []
        expires = now + self._references.TTL_SECONDS
        for label, target in nodes:
            key = None
            if len(additions) < available:
                key = self._new_key(used)
                additions.append((key, _Reference(session, target, expires)))
            public.append({'label': label, 'selection_ref': key})
        response = _frame({'schema': 'cluster-observation-inventory-v1',
                           'scope': 'configured_source', 'nodes': public}, _MIB)
        with _OrderedAuthGates(self._auth, original):
            self._revalidate_locked(original, token, session, values, nodes, snapshot)
            if not time.monotonic() < expires:
                raise _SelectionRefused(504)
            try:
                self._broker._admit_frame_locked(handler, original, response)
                for key, record in additions:
                    self._references._selections[key] = record
            except BaseException as error:
                # A partial commit cannot leave a frame eligible to write.
                raise self._auth._uncertain(error)
        return response

    def admit_bind(self, handler):
        # Exact original broker consumes its body once, validates the fixed
        # 256B framing/duplicate-key/string-only selection_ref schema itself.
        body = handler._request_body()
        selected_key = body['selection_ref']
        if not self._references._valid_reference(selected_key):
            raise _SelectionRefused(400)
        captured = self._capture(handler, 'bind')
        original, token, session, values, nodes, now, snapshot = captured
        selections, bindings = (rows for original_table, rows in snapshot)
        selected = next((record for key, record in selections if key == selected_key), None)
        if (selected is None or selected.session is not session or
                not any(selected.target is target for _, target in nodes) or
                not now < selected.expires or
                len(selections) + len(bindings) >= self._references.PROCESS_LIMIT or
                sum(record.session is session for _, record in bindings) >=
                    self._references.BINDINGS_PER_SESSION):
            raise _SelectionRefused(409)
        used = {key for original_table, rows in snapshot for key, _ in rows}
        key = self._new_key(used)
        expires = min(selected.expires, now + self._references.TTL_SECONDS)
        remaining_ms = int((expires - now) * 1000)
        if not 1 <= remaining_ms <= 30000:
            raise _SelectionRefused(409)
        record = _Reference(session, selected.target, expires)
        response = _frame({'schema': 'cluster-observation-binding-v1',
                           'binding_ref': key, 'expires_in_ms': remaining_ms}, 256)
        with _OrderedAuthGates(self._auth, original):
            self._revalidate_locked(original, token, session, values, nodes, snapshot)
            if not time.monotonic() < expires:
                raise _SelectionRefused(504)
            try:
                self._broker._admit_frame_locked(handler, original, response)
                self._references._bindings[key] = record
            except BaseException as error:
                raise self._auth._uncertain(error)
        # Selection remains under its ORIGINAL lifetime; the new one-use
        # binding will be consumed by the unfinished original read owner.
        return response

    def write_admitted_response(self, handler, response):
        # Same final INSTALLATION→AUTH→REFERENCES→HTTP reserve and original
        # once native send outside every admission lock; never a second writer.
        return self._auth.write_admitted_response(handler, response)


# No actual startup factory, provider/read invocation or route dispatch here.
