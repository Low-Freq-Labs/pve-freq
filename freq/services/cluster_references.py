"""Bounded, process-local references for the structured Cluster Status route.

References bind an application session and a configured inventory snapshot.
They do not establish provider identity, permission, freshness or quorum.
The route must check the original session under the authentication lock both
before calling this store and before publishing a response.
"""
from dataclasses import dataclass
import secrets
import threading
import time


class ReferenceUnavailable(ValueError):
    """A missing, foreign, expired, spent or capacity-refused reference."""


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    configuration_revision: str
    selection_key: str
    endpoint: str


@dataclass(frozen=True, slots=True)
class _Reference:
    session: object
    target: TargetSnapshot
    expires: float


class ClusterReferences:
    SELECTIONS_PER_SESSION = 64
    BINDINGS_PER_SESSION = 16
    PROCESS_LIMIT = 1024
    TTL_SECONDS = 30.0

    def __init__(self):
        self._lock = threading.Lock()
        self._selections = {}
        self._bindings = {}

    @staticmethod
    def _valid_reference(value):
        return (type(value) is str and len(value) == 32
                and all(c in '0123456789abcdef' for c in value))

    @staticmethod
    def _valid_target(target):
        return (type(target) is TargetSnapshot
                and all(type(value) is str and 0 < len(value) <= 512
                        for value in (target.configuration_revision,
                                      target.selection_key, target.endpoint)))

    def _expire(self, now):
        for records in (self._selections, self._bindings):
            expired = [key for key, record in records.items()
                       if record.expires <= now]
            for key in expired:
                del records[key]

    def _new_key(self):
        # Bounded collision refusal, never overwrite an existing reference.
        for _ in range(4):
            key = secrets.token_hex(16)
            if key not in self._selections and key not in self._bindings:
                return key
        raise ReferenceUnavailable('cluster_report_unavailable')

    def issue_selection(self, session, target):
        """Called by the inventory publisher, never with a browser target."""
        if session is None or not self._valid_target(target):
            raise ReferenceUnavailable('cluster_report_unavailable')
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            if (len(self._selections) + len(self._bindings) >= self.PROCESS_LIMIT
                    or sum(r.session is session for r in self._selections.values())
                    >= self.SELECTIONS_PER_SESSION):
                raise ReferenceUnavailable('cluster_report_unavailable')
            key = self._new_key()
            self._selections[key] = _Reference(session, target, now + self.TTL_SECONDS)
            return key

    def bind(self, session, selection_ref, current_revision):
        """Mint one request reference without acquiring any provider data."""
        if not self._valid_reference(selection_ref):
            raise ReferenceUnavailable('cluster_report_unavailable')
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            selected = self._selections.get(selection_ref)
            if (selected is None or selected.session is not session
                    or type(current_revision) is not str
                    or selected.target.configuration_revision != current_revision
                    or len(self._selections) + len(self._bindings) >= self.PROCESS_LIMIT
                    or sum(r.session is session for r in self._bindings.values())
                    >= self.BINDINGS_PER_SESSION):
                raise ReferenceUnavailable('cluster_report_unavailable')
            key = self._new_key()
            # A binding cannot extend the inventory snapshot lifetime.
            expires = min(selected.expires, now + self.TTL_SECONDS)
            remaining_ms = int((expires - now) * 1000)
            if remaining_ms <= 0:
                raise ReferenceUnavailable('cluster_report_unavailable')
            self._bindings[key] = _Reference(session, selected.target, expires)
            return key, remaining_ms

    def consume(self, session, binding_ref, current_revision):
        """Remove an owned binding before any acquisition or response effect."""
        if not self._valid_reference(binding_ref):
            raise ReferenceUnavailable('cluster_report_unavailable')
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            bound = self._bindings.get(binding_ref)
            if bound is None or bound.session is not session:
                raise ReferenceUnavailable('cluster_report_unavailable')
            del self._bindings[binding_ref]
            if (type(current_revision) is not str
                    or bound.target.configuration_revision != current_revision):
                raise ReferenceUnavailable('cluster_report_unavailable')
            return bound.target

    def retire_session(self, session):
        """Called under auth ownership when the original session terminates."""
        with self._lock:
            for records in (self._selections, self._bindings):
                keys = [key for key, record in records.items()
                        if record.session is session]
                for key in keys:
                    del records[key]
