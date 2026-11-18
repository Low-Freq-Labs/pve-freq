"""Pure pending installation prefix; no native factory or serving entry.

The original outside controller must retain this exact object before invoking
its no-argument preparation method and before acquiring any installation gate,
event, context, server, source or credential resource. This module implements
only that pending object's storage. It does not establish that the outside
controller exists or followed that order. Import setup is not resource-free.

There is deliberately no positive currentness implementation, native owner
attachment API, activation method or CLI caller. A separately reviewed source
successor must implement the real producer/cohort/writer/lifetime joins.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.pilot_component_binding import (
    _OriginalPilotComponentBinding, _first_preparation_failure,
)
from freq.services.pilot_owner_auth_forwards import _OriginalPilotAuthForwards
from freq.services.pilot_snippet_pending import _PendingOriginalSnippetCustodian
from freq.services.pilot_startup_formats.coordinator import DormantCoordinator


class OriginalPilotInstallation(
        _OriginalPilotComponentBinding, _OriginalPilotAuthForwards):
    """Actual canonical pending type, not an authority or installation factory.

    Allocation initializes only private Python storage. The outside original
    parent retains its returned object before calling _prepare_pending_original.
    Losing this allocation's return acquires no native resource, but never
    licenses repeating an unknown later acquiring operation. No supplied owner,
    parser, path, map, native observation or callback is accepted here.
    """
    __slots__ = (
        '_pending_state', '_pending_retirement_required',
        '_component_preparation_errors', '_component_preparation_failure',
        '_component_binding_errors', '_component_binding_failure',
        '_pending_preparation_errors', '_pending_preparation_failure',
        '_components_state', '_live', '_admission_uncertain', '_server', '_gate',
        '_source_uid', '_credential_uid', '_startup_inputs', '_references',
        '_auth_inputs', '_auth_commit', '_login_rate', '_cluster_selections',
        '_cluster_reads', '_static_responder', '_dispatcher',
        '_auth_attempts', '_asset_attempts', '_issued_sessions', '_read_attempts',
        '_native_read_attempts', '_original_component_tables', '_configured_data',
        '_discovery_attempts', '_native_discovery_attempts', '_original_discovery_tables',
        '_discovery_contexts', '_discovery_collector_storage',
        '_configured_fleet_targets_data', '_fleet_targets_reader',
        '_guest_families_by_nonce', '_guest_families_by_ref',
        '_guest_reference_records', '_guest_capacity', '_original_guest_capacity',
        '_guest_reference_store', '_original_guest_reference_store',
        '_guest_inventory_attempts', '_native_guest_inventory_attempts',
        '_original_guest_inventory_tables',
        '_guest_profile_attempts', '_native_guest_profile_attempts',
        '_original_guest_profile_tables',
        '_configuration_revision', '_configured_nodes', '_configured_roles',
        '_service_user', '_configured_token_id', '_config_supported',
        '_policy_supported', '_snippet_custodian', '_profile_coordinator',
    )

    def __new__(cls):
        if cls is not OriginalPilotInstallation:
            raise _RequestUnavailable()
        self = object.__new__(cls)
        # Pure storage only. No Lock/Event/socket/context/reader construction.
        self._pending_state = 'allocated'
        self._pending_retirement_required = False
        self._component_preparation_errors = [None] * 4
        self._component_preparation_failure = None
        self._component_binding_errors = [None] * 5
        self._component_binding_failure = None
        self._pending_preparation_errors = [None] * 6
        self._pending_preparation_failure = None
        self._components_state = 'unused'
        self._live = False
        self._admission_uncertain = False
        for field in (
                '_server', '_gate', '_source_uid', '_credential_uid',
                '_startup_inputs', '_references', '_auth_inputs', '_auth_commit',
                '_login_rate', '_cluster_selections', '_cluster_reads',
                '_static_responder', '_dispatcher', '_auth_attempts',
                '_asset_attempts', '_issued_sessions', '_read_attempts',
                '_native_read_attempts', '_original_component_tables',
                '_discovery_attempts', '_native_discovery_attempts', '_original_discovery_tables',
                '_discovery_contexts', '_discovery_collector_storage',
                '_guest_families_by_nonce', '_guest_families_by_ref',
                '_guest_reference_records', '_guest_capacity', '_original_guest_capacity',
                '_guest_reference_store', '_original_guest_reference_store',
                '_guest_inventory_attempts', '_native_guest_inventory_attempts',
                '_original_guest_inventory_tables',
                '_guest_profile_attempts', '_native_guest_profile_attempts',
                '_original_guest_profile_tables',
                '_configured_data', '_configured_fleet_targets_data', '_fleet_targets_reader',
                '_configuration_revision', '_configured_nodes',
                '_configured_roles', '_service_user', '_configured_token_id',
                '_config_supported', '_policy_supported', '_snippet_custodian',
                '_profile_coordinator'):
            setattr(self, field, None)
        return self

    def __init__(self):
        # Repeating Python __init__ cannot refund or replace the original maps.
        pass

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original pending installation cannot be subclassed')

    def __copy__(self):
        raise TypeError('original pending installation cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('original pending installation cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('original pending installation cannot be serialized')

    def _prepare_pending_original(self):
        """Once-only pure tables, after outside retention, before acquisition.

        State checks refuse misuse; they do not prove original parent custody.
        A lost/failed return permanently retires this same pending instance.
        The outside parent must retain unknown duties without retry/adoption.
        """
        if (type(self) is not OriginalPilotInstallation or
                self._pending_state != 'allocated' or
                self._pending_retirement_required is not False or
                self._components_state != 'unused' or self._live is not False or
                self._admission_uncertain is not False or
                self._gate is not None or self._server is not None):
            raise _RequestUnavailable()
        self._pending_state = 'preparing'
        first = None
        try:
            _OriginalPilotComponentBinding._prepare_original_component_tables(self)
            # Retain this pure pending object before its own map preparation.
            # No original snippet authority or acquiring operation is added.
            self._snippet_custodian = _PendingOriginalSnippetCustodian()
            _PendingOriginalSnippetCustodian._prepare(self._snippet_custodian, self)
            # Retain pure coordinator storage before any future native Lock
            # initialization. Missing fields confer no readiness or cleanup.
            self._profile_coordinator = object.__new__(DormantCoordinator)
            self._pending_state = 'prepared'
            return
        except BaseException as error:
            first = self._pending_preparation_failure = error
            self._pending_preparation_errors[0] = error
        # Every independent quarantine assignment is attempted. A cleanup
        # control outranks an ordinary body failure; an original control wins.
        for index, (field, value) in enumerate((
                ('_pending_state', 'retirement-only'),
                ('_pending_retirement_required', True),
                ('_components_state', 'retirement-only'),
                ('_live', False), ('_admission_uncertain', True)), 1):
            try:
                setattr(self, field, value)
            except BaseException as error:
                self._pending_preparation_errors[index] = error
                first = _first_preparation_failure(first, error)
        self._pending_preparation_failure = first
        if first is not None and (not issubclass(type(first), Exception) or issubclass(type(first), MemoryError)):
            raise first
        raise _RequestUnavailable() from None

    def _native_current_locked(self, original):
        """Permanent refusal until a real original producer source successor.

        No IO, lock, hash, clock, callback, serialized observation, or truthy
        supplied object can make this pending implementation admit a request.
        """
        return False


# No start/serve/factory/attach/activate/close operation. Existing CLI remains78.
