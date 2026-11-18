"""Disabled application-session join; no provider or disclosure authority.

No route imports or installs this issuer. Original auth identity is checked
under the existing auth lock; deferred reference cleanup runs after releasing
that lock. Registration, credentials, TLS and final response admission remain
separate integration gates.
"""
from dataclasses import dataclass, field
import math
import threading
import time

from freq.api import auth
from .node_read_registry import NodeReadRegistry, LeaseSlot
from .node_read_references import NodeReadReferences, ReferenceCleanup


def _refuse():
    raise ValueError("node session unavailable")


def _number(value):
    if type(value) is int:
        return -(1 << 53) <= value <= (1 << 53)
    return type(value) is float and math.isfinite(value)


@dataclass(frozen=True, slots=True, repr=False)
class NodeSessionGrant:
    token: str = field(repr=False)
    session: dict = field(repr=False)
    role: str = field(repr=False)
    user: str = field(repr=False)
    expires: float = field(repr=False)
    store: dict = field(repr=False)
    lock: object = field(repr=False)


def capture_node_session(handler):
    """Capture original app session only; no credential/config resolution."""
    token = auth._extract_session_token(handler)
    if type(token) is not str or not 1 <= len(token) <= 256:
        return None
    lock, store = auth._auth_lock, auth._auth_tokens
    with lock:
        now = time.time()
        if auth._auth_lock is not lock or auth._auth_tokens is not store:
            return None
        if type(store) is not dict:
            return None
        session = store.get(token)
        if type(session) is not dict:
            return None
        role, user = session.get("role"), session.get("user")
        last = session.get("last_activity_ts", session.get("ts"))
        if (type(role) is not str or role not in ("viewer", "operator", "admin", "protected")
                or type(user) is not str or not 1 <= len(user) <= 256
                or not _number(last) or not _number(now)
                or not 0 <= now - last < auth.SESSION_TIMEOUT_SECONDS):
            return None
        # A later session touch cannot renew this original grant.
        expires = float(last + auth.SESSION_TIMEOUT_SECONDS)
        if not math.isfinite(expires):
            return None
        return NodeSessionGrant(token, session, role, user, expires, store, lock)


def _current_locked(grant):
    """Caller holds grant.lock; only original exact dict/scalar checks."""
    now = time.time()
    if (auth._auth_lock is not grant.lock or auth._auth_tokens is not grant.store
            or type(grant.store) is not dict
            or grant.store.get(grant.token) is not grant.session
            or type(grant.session) is not dict):
        return False
    role, user = grant.session.get("role"), grant.session.get("user")
    last = grant.session.get("last_activity_ts", grant.session.get("ts"))
    return (type(role) is str and role == grant.role
            and type(user) is str and user == grant.user
            and _number(last) and _number(now)
            and 0 <= now - last < auth.SESSION_TIMEOUT_SECONDS
            and now < grant.expires)


class NodeSessionIssuer:
    """Finite application issuance only; never authenticates a provider node.

    At most64 concurrent operations own cleanup lists. The original issuer must
    persist; constructing replacements is not a capacity recovery mechanism.
    Callers retain and release their original invocation lease after consume,
    including when this method raises after publishing that lease.
    """
    __slots__ = ("_registry", "_references", "_operations")

    def __init__(self, registry, references):
        if (type(registry) is not NodeReadRegistry
                or type(references) is not NodeReadReferences
                or references._registry is not registry):
            _refuse()
        self._registry = registry
        self._references = references
        self._operations = threading.BoundedSemaphore(64)

    def issue_selection(self, grant, internal_target_key):
        return self._perform(grant, "issue", internal_target_key, None)

    def bind(self, grant, selection_ref):
        return self._perform(grant, "bind", selection_ref, None)

    def consume_into(self, grant, binding_ref, original_lease):
        if type(original_lease) is not LeaseSlot:
            _refuse()
        return self._perform(grant, "consume", binding_ref, original_lease)

    def _perform(self, grant, operation, value, lease):
        if (type(grant) is not NodeSessionGrant
                or grant.lock is not auth._auth_lock
                or grant.store is not auth._auth_tokens
                or type(grant.store) is not dict or type(grant.session) is not dict
                or type(grant.token) is not str or not 1 <= len(grant.token) <= 256
                or type(grant.role) is not str
                or grant.role not in ("viewer", "operator", "admin", "protected")
                or type(grant.user) is not str or not 1 <= len(grant.user) <= 256
                or type(grant.expires) is not float or not math.isfinite(grant.expires)):
            _refuse()
        operations = self._operations
        if not operations.acquire(blocking=False):
            _refuse()
        cleanup = None
        first = None
        result = None
        references, registry = self._references, self._registry
        try:
            cleanup = ReferenceCleanup()
            with grant.lock:
                if (not _current_locked(grant) or self._references is not references
                        or self._registry is not registry
                        or references._registry is not registry):
                    _refuse()
                if operation == "issue":
                    result = references.issue_selection(grant.session, value, cleanup=cleanup)
                elif operation == "bind":
                    result = references.bind(grant.session, value, cleanup=cleanup)
                elif operation == "consume":
                    result = references.consume_into(grant.session, value, lease, cleanup=cleanup)
                else:
                    _refuse()
        except BaseException as error:
            first = error
        finally:
            # Auth, registry and reference locks have all been released.
            try:
                if cleanup is not None:
                    cleanup.drain()
            except BaseException as error:
                if first is None or (isinstance(first, Exception)
                                     and not isinstance(error, Exception)):
                    first = error
            finally:
                operations.release()
        if first is not None:
            raise first
        return result
