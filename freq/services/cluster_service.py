"""Structured cluster read composition, with an explicitly supplied source.

Production startup does not install a supplied source. The offline integration
harness installs this service on its own server, exercising the same routes.
A future provider adapter requires its own provenance and qualification gate.
"""
import secrets
import threading
import time

from freq.services.cluster_references import ClusterReferences, TargetSnapshot
from freq.services.cluster_report import cluster_status, cluster_browser


class ClusterReadUnavailable(ValueError):
    pass


class SuppliedClusterService:
    def __init__(self, configured_targets, supplied_reader):
        # This constructor is internal startup composition, not a public API.
        self.lock = threading.Lock()
        self.references = ClusterReferences()
        self._reader = supplied_reader
        self._targets = {}
        self._revision = ''
        self.replace_configuration(configured_targets)

    def replace_configuration(self, configured_targets):
        if type(configured_targets) is not dict or len(configured_targets) > 1024:
            raise ClusterReadUnavailable()
        targets = {}
        for key, endpoint in configured_targets.items():
            if (type(key) is not str or not 0 < len(key) <= 256
                    or type(endpoint) is not str or not 0 < len(endpoint) <= 512):
                raise ClusterReadUnavailable()
            targets[key] = endpoint
        revision = secrets.token_hex(16)
        with self.lock:
            self._targets = targets
            self._revision = revision

    def decorate_inventory(self, session, rows):
        """Copy rows; never mint authority from arbitrary supplied row fields."""
        if type(rows) is not list or len(rows) > 1024:
            raise ClusterReadUnavailable()
        copied = []
        with self.lock:
            for row in rows:
                if type(row) is not dict:
                    raise ClusterReadUnavailable()
                current = dict(row)
                current.pop('cluster_report_selection_ref', None)
                key, endpoint = current.get('name'), current.get('ip')
                if (type(key) is str and type(endpoint) is str
                        and self._targets.get(key) == endpoint):
                    target = TargetSnapshot(self._revision, key, endpoint)
                    from freq.services.cluster_references import ReferenceUnavailable
                    try:
                        current['cluster_report_selection_ref'] = self.references.issue_selection(session, target)
                    except ReferenceUnavailable:
                        # Capacity refusal is visible as a missing optional field.
                        pass
                copied.append(current)
        return copied

    def bind(self, session, selection_ref):
        with self.lock:
            binding, ttl = self.references.bind(session, selection_ref, self._revision)
            return binding, ttl, self._revision

    def acquire(self, session, binding_ref, deadline):
        with self.lock:
            target = self.references.consume(session, binding_ref, self._revision)
        if not time.monotonic() < deadline:
            raise TimeoutError()
        # Reader owns its resource closure and honors the absolute deadline.
        # No session/config/reference lock is held while it runs.
        raw = self._reader(target, deadline)
        if not time.monotonic() < deadline:
            raise TimeoutError()
        if type(raw) is not bytes or not 0 < len(raw) <= 1048576:
            raise ClusterReadUnavailable()
        private = cluster_status.decode(raw, secrets.token_hex(16), cluster_status.PROFILE)
        public = cluster_browser.project(private)
        if type(public) is not cluster_browser.ClusterBrowserAssessment:
            raise ClusterReadUnavailable()
        if not time.monotonic() < deadline:
            raise TimeoutError()
        return target, public.body

    def current_locked(self, target):
        """Caller holds service lock through publication admission, not I/O."""
        return (type(target) is TargetSnapshot
                and target.configuration_revision == self._revision
                and self._targets.get(target.selection_key) == target.endpoint)
