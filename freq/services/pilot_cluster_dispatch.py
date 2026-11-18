"""Fixed original Cluster pilot dispatch; uninstalled source, no factory.

The actual OriginalPilotInstallation/native source-cohort/writer/resource owner
is still missing. Exact types and retained objects below refuse substitutes;
they do not issue that authority. No native server is started by this module.
"""
import json

from freq.api import auth
from freq.services.cluster_pilot_http import (
    OriginalPilotResponse, _OriginalPilotHandler, _OriginalPilotServer,
    _RequestUnavailable, _BadRequest,
)
from freq.services.pilot_auth_commit import OriginalAuthCommit
from freq.services.pilot_auth_attempts import OriginalPilotAuthAttempts
from freq.services.pilot_cluster_selections import OriginalClusterSelections, _SelectionRefused
from freq.services.pilot_cluster_read_admission import OriginalClusterReads
from freq.services.pilot_login_rate import OriginalPilotLoginRate
from freq.services.pilot_static_response import OriginalPilotStatic
from freq.services.pilot_fleet_targets_read import OriginalPilotFleetTargets
from freq.services.guest_owner_response import format_owner_unavailable_data
from freq.services.pilot_guest_reference_store import OriginalGuestReferenceStore
from freq.services.pilot_discovery_request_context import OriginalDiscoveryRequestContexts


_AUTH_ERRORS = frozenset((
    (400, 'Invalid request body'),
    (400, 'Username and password required'),
    (401, 'Invalid credentials'),
    (403, 'Matching HTTPS Origin header required'),
    (405, 'Use POST with JSON body for login'),
    (405, 'Use GET for session verification'),
    (405, 'Use POST for logout'),
    (429, 'Too many login attempts. Try again in 5 minutes.'),
    (503, 'Cluster authentication unavailable'),
))


def _first(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception)
            or not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


def _public_refusal(error):
    """Fixed safe schema only, without serializing native exception details."""
    if type(error) is auth._ClusterPilotAuthRefused:
        status, payload = error.status, error.payload
        if (type(status) is int and type(payload) is dict and len(payload) == 1
                and type(payload.get('error')) is str and
                (status, payload['error']) in _AUTH_ERRORS):
            return status, {'error': payload['error']}
        return 503, {'error': 'Cluster authentication unavailable'}
    if type(error) is _SelectionRefused:
        status = error.status
        if type(status) is int and status in (400, 403, 409, 503, 504):
            return status, {'error': 'cluster_observation_unavailable'}
    return (400 if type(error) is _BadRequest else 503,
            {'error': 'cluster_observation_unavailable'})


class OriginalPilotDispatch:
    """One original parsed operation, selected components and response duty.

    Actual startup retains this component as _dispatcher only AFTER its same
    server and exact original auth/rate/static/selections/read components exist.
    Auth's original installation method interface remains mandatory; this
    dispatcher does not replace it with a supplied callback or fixture owner.
    """
    def __init__(self, installation):
        self._installation = installation
        self._validate_owner()
        self._broker = installation._server._pilot_requests
        self._selections = installation._cluster_selections
        self._reads = installation._cluster_reads
        self._static = installation._static_responder
        self._guests = installation._guest_reference_store
        self._fleet = installation._fleet_targets_reader
        self._discovery = installation._discovery_contexts
        self._components = tuple((name, getattr(installation, name)) for name in (
            '_auth_commit', '_auth_inputs', '_login_rate', '_cluster_selections',
            '_cluster_reads', '_static_responder', '_guest_reference_store',
            '_fleet_targets_reader', '_discovery_contexts'))

    def _validate_owner(self):
        try:
            from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        except ImportError:
            raise _RequestUnavailable() from None
        owner = self._installation
        if (type(owner) is not OriginalPilotInstallation or
                type(owner._server) is not _OriginalPilotServer or
                owner._server._cluster_pilot_installation is not owner):
            raise _RequestUnavailable()
        for name, cls in (
            ('_auth_commit', OriginalAuthCommit),
            ('_auth_inputs', OriginalPilotAuthAttempts),
            ('_login_rate', OriginalPilotLoginRate),
            ('_cluster_selections', OriginalClusterSelections),
            ('_cluster_reads', OriginalClusterReads),
            ('_static_responder', OriginalPilotStatic),
            ('_guest_reference_store', OriginalGuestReferenceStore),
            ('_fleet_targets_reader', OriginalPilotFleetTargets),
            ('_discovery_contexts', OriginalDiscoveryRequestContexts),
        ):
            component = getattr(owner, name, None)
            if type(component) is not cls or component._installation is not owner:
                raise _RequestUnavailable()

    def _owned(self, handler):
        self._validate_owner()
        owner = self._installation
        if (type(handler) is not _OriginalPilotHandler or
                handler.server is not owner._server or owner._dispatcher is not self or
                owner._server._pilot_requests is not self._broker or
                owner._cluster_selections is not self._selections or
                owner._cluster_reads is not self._reads or
                owner._static_responder is not self._static or
                owner._guest_reference_store is not self._guests or
                owner._fleet_targets_reader is not self._fleet or
                owner._discovery_contexts is not self._discovery or
                any(getattr(owner, name, None) is not component
                    for name, component in self._components)):
            raise _RequestUnavailable()
        return self._broker._owned(handler)

    def _write_refusal(self, handler, error):
        original = self._owned(handler)
        broker = self._broker
        operation = original.operation
        if type(operation) is not str:
            raise _RequestUnavailable()
        if (operation in ('guest-owner-open', 'guest-owner-sources',
                          'guest-owner-inventory', 'guest-owner-profile',
                          'guest-owner-retire') and
                type(error) is not auth._ClusterPilotAuthRefused):
            # Only ordinary v2 failure. A fixed unavailable frame is never a
            # positive F, source/profile grant or retirement acknowledgement.
            # Original auth/CSRF/rate errors retain their existing fixed shape.
            response = format_owner_unavailable_data()
        else:
            if operation == 'fleet-targets' and type(error) is not auth._ClusterPilotAuthRefused:
                status, payload = 503, {'error': 'fleet_exec_targets_unavailable'}
            else:
                status, payload = _public_refusal(error)
            body = json.dumps(payload, ensure_ascii=True, allow_nan=False,
                              separators=(',', ':')).encode('ascii')
            if len(body) > 256:
                raise _RequestUnavailable()
            response = OriginalPilotResponse(status, body, 'application/json')
        # The SAME retained write_end was shortened at binding capture, so
        # failed read/constructor/parse/admit paths cannot get a later allowance.
        broker._write_remaining(original)
        broker._lock(original.write_end)
        local_error = None
        try:
            if (self._broker is not broker or
                    broker._owned(handler) is not original or
                    type(original.operation) is not str or
                    original.operation != operation or
                    original.phase != 'ready' or original.frame is not None):
                # Nothing can append a status after admission/partial write.
                raise _RequestUnavailable()
            broker._admit_frame_locked(handler, original, response)
            broker._reserve_write_locked(handler, original, response)
        except BaseException as failure:
            local_error = failure
            raise
        finally:
            broker._drop_gate(local_error)
        broker._send_reserved(handler, response)

    def run(self, handler):
        original = self._owned(handler)
        operation = original.operation
        # Save the owned component before any original operation can fail.
        profile_store = self._guests if operation == 'guest-owner-profile' else None
        discovery_contexts = self._discovery if operation == 'discovery' else None
        first = None
        try:
            if operation in ('app', 'asset'):
                self._static.serve(handler)
            elif operation == 'login':
                auth.handle_cluster_pilot_auth_login(handler)
            elif operation == 'verify':
                auth.handle_cluster_pilot_auth_verify(handler)
            elif operation == 'logout':
                auth.handle_cluster_pilot_auth_logout(handler)
            elif operation == 'inventory':
                response = self._selections.admit_inventory(handler)
                self._selections.write_admitted_response(handler, response)
            elif operation == 'bind':
                response = self._selections.admit_bind(handler)
                self._selections.write_admitted_response(handler, response)
            elif operation == 'fleet-targets':
                response = self._fleet.admit_targets_response(handler)
                self._fleet.write_targets_response(handler, response)
            elif operation == 'read':
                response = self._reads.admit_read(handler)
                self._reads.write_admitted_response(handler, response)
            elif operation == 'discovery':
                # Context capture never grants scanning or positive output.
                # The unchanged fixed classifier cannot select this branch.
                discovery_contexts.capture_request(handler)
                raise _RequestUnavailable()
            elif operation == 'guest-owner-open':
                store = self._guests
                response = store.admit_opening_response(handler)
                store.write_opening_response(handler, response)
            elif operation == 'guest-owner-retire':
                store = self._guests
                response = store.admit_retirement_response(handler)
                store.write_retirement_response(handler, response)
            elif operation == 'guest-owner-sources':
                store = self._guests
                response = store.admit_sources_response(handler)
                store.write_sources_response(handler, response)
            else:
                raise _RequestUnavailable()
        except BaseException as failure:
            first = failure
        finally:
            if operation == 'discovery':
                try:
                    # SAME component retained before capture, even when its
                    # return is lost. Before broker drops the request duty.
                    discovery_contexts.retire_handler_context(handler)
                except BaseException as cleanup:
                    first = _first(first, cleanup)
            if operation == 'guest-owner-profile' and (
                    original.profile_custody_started is not False or
                    original.guest_response is not None):
                try:
                    # Fixed original entry retains outside return/error states.
                    # A local return never discharges native or parent custody.
                    profile_store.retire_profile_request_duty(handler)
                except BaseException as cleanup:
                    first = _first(first, cleanup)
            if operation == 'guest-owner-sources':
                try:
                    self._guests.retire_sources_handler_duty(handler)
                except BaseException as cleanup:
                    first = _first(first, cleanup)
            if operation == 'guest-owner-retire':
                try:
                    self._guests.retire_retirement_handler_duty(handler)
                except BaseException as cleanup:
                    first = _first(first, cleanup)
            if operation == 'guest-owner-open':
                try:
                    # Covers a lost begin/admit/write return as well as direct
                    # method failure. No success/ACK follows logical cleanup.
                    self._guests.retire_opening_handler_duty(handler)
                except BaseException as cleanup:
                    first = _first(first, cleanup)
            if operation == 'read':
                try:
                    # Before original broker/server shutdown releases request.
                    # Also runs when admission succeeds but writing is skipped.
                    self._reads.retire_handler_read(handler)
                except BaseException as cleanup:
                    first = _first(first, cleanup)
        if first is None:
            return
        if not isinstance(first, Exception) or isinstance(first, MemoryError):
            raise first
        try:
            self._write_refusal(handler, first)
        except BaseException as cleanup:
            chosen = _first(first, cleanup)
            if not isinstance(chosen, Exception) or isinstance(chosen, MemoryError):
                raise chosen
            # No native details or second response; original handler closes.
            raise _RequestUnavailable() from None


# Actual startup factory, native currentness and physical lifecycle remain open.
