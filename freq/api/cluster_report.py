"""Dedicated supplied Cluster Status handlers for offline product composition.

No production source is installed implicitly. A server without the explicit
internal supplied service responds unavailable; there is no generic exec path.
"""
import json
import time

from freq.api import auth
from freq.services.cluster_http import (
    ERROR_BODY, InvalidClusterRequest, read_reference, write_once,
)
from freq.services.cluster_references import ReferenceUnavailable
from freq.services.cluster_service import SuppliedClusterService


def _handle(handler, bind):
    deadline = time.monotonic() + 10.0
    handler.close_connection = True
    try:
        grant = auth.capture_cluster_session(handler)
        if grant is None:
            write_once(handler, ERROR_BODY, 403, deadline=deadline)
            return
        field = 'selection_ref' if bind else 'binding_ref'
        reference = read_reference(handler, field, deadline)
        service = getattr(getattr(handler, 'server', None), 'cluster_report_service', None)
        if type(service) is not SuppliedClusterService:
            write_once(handler, ERROR_BODY, 503, deadline=deadline)
            return
        current = auth.capture_cluster_session(handler)
        if (current is None or current[1] is not grant[1]
                or current[2:] != grant[2:]):
            write_once(handler, ERROR_BODY, 403, deadline=deadline)
            return
        if bind:
            binding, ttl, revision = service.bind(grant[1], reference)
            body = json.dumps({'schema': 'cluster-report-binding-v1',
                               'binding_ref': binding,
                               'expires_in_ms': ttl}, separators=(',', ':')).encode('utf-8')
        else:
            target, body = service.acquire(grant[1], reference, deadline)
            revision = target.configuration_revision
        if not auth.admit_cluster_publication(handler, grant, deadline,
                                              service=service, revision=revision):
            write_once(handler, ERROR_BODY, 409, deadline=deadline)
            return
        write_once(handler, body, deadline=deadline)
    except InvalidClusterRequest:
        write_once(handler, ERROR_BODY, 400, deadline=deadline)
    except ReferenceUnavailable:
        write_once(handler, ERROR_BODY, 409, deadline=deadline)
    except TimeoutError:
        # A spent total budget cannot justify another network write.
        if time.monotonic() < deadline:
            write_once(handler, ERROR_BODY, 504, deadline=deadline)
    except Exception:
        write_once(handler, ERROR_BODY, 503, deadline=deadline)


def handle_bind(handler):
    _handle(handler, True)


def handle_read(handler):
    _handle(handler, False)


def register(routes):
    routes['/api/pve/cluster-report/bind'] = handle_bind
    routes['/api/pve/cluster-report/read'] = handle_read
