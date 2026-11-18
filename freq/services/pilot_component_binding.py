"""Private component construction for the future original installation.

This supplies no installation constructor, native owner or activation. The
actual original factory must acquire and retain all native source, credential,
TLS, principal, writer/code/currentness/resource and physical lifetime first.
Its original inactive server and retained startup input attempt are mandatory.
Exact types/fields below are refusal filters, never proof of those conditions.
"""
from _thread import LockType
from freq.services.guest_reference_capacity import _GuestCapacity

from freq.services.cluster_pilot_http import (
    _OriginalPilotServer, _OriginalHTTPRequests, _RequestUnavailable,
)
from freq.services.cluster_references import ClusterReferences
from freq.services.pilot_startup_acquisition import OriginalStartupInputAttempt
from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.pilot_fleet_targets_data import ConfiguredFleetTargetsData
from freq.services.pilot_auth_attempts import OriginalPilotAuthAttempts
from freq.services.pilot_auth_commit import OriginalAuthCommit
from freq.services.pilot_login_rate import OriginalPilotLoginRate
from freq.services.pilot_guest_reference_store import OriginalGuestReferenceStore
from freq.services.pilot_cluster_selections import OriginalClusterSelections
from freq.services.pilot_cluster_read_admission import OriginalClusterReads
from freq.services.pilot_static_response import OriginalPilotStatic
from freq.services.pilot_fleet_targets_read import OriginalPilotFleetTargets
from freq.services.pilot_cluster_dispatch import OriginalPilotDispatch
from freq.services.pilot_discovery_request_context import OriginalDiscoveryRequestContexts
from freq.services.pilot_discovery_collector_storage import _OriginalDiscoveryCollectorStorage


def _first(first, later):
    if first is None or (issubclass(type(first), Exception) and
                         not issubclass(type(later), Exception)):
        return later
    return first


def _first_preparation_failure(first, later):
    """Private constructor cleanup priority, without widening native admission."""
    if first is None or (issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception) or
            not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError))):
        return later
    return first


class _OriginalPilotComponentBinding:
    """Fixed one-shot construction order, no supplied component/map/callback.

    The actual original Installation must inherit this and the separately
    reviewed auth forwarding mixin, initialize its permanent state as unused
    before effects, and call this only before any request loop/activation.
    Missing actual Installation still refuses; no positive fixture owner is
    supplied to make this executable. Construction alone never enables serving.
    """
    __slots__ = ()

    def _prepare_original_component_tables(self):
        """Pure one-shot storage BEFORE original gate/server construction.

        The actual outer native parent must already retain this SAME pending
        installation. Its constructor initializes unused/False/None fields
        before calling this method, then keeps these exact table objects for
        its whole lifetime. No lock, event, socket, reader or native owner is
        acquired here. DATA storage cannot issue authority or activate serving.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not OriginalPilotInstallation or
                self._components_state != 'unused' or
                self._live is not False or self._admission_uncertain is not False or
                self._server is not None or self._gate is not None):
            raise _RequestUnavailable()
        # Permanent marker precedes allocation. Partial allocation, lost return
        # or failed assignment can never be retried on this same instance.
        self._components_state = 'tables-pending'
        first = None
        try:
            self._auth_attempts = {}
            self._asset_attempts = {}
            self._issued_sessions = {}
            self._read_attempts = {}
            self._native_read_attempts = {}
            # Original Discovery request storage precedes any gate/server or
            # child acquisition. These maps are DATA, not native authority.
            self._discovery_attempts = {}
            self._native_discovery_attempts = {}
            self._original_discovery_tables = (
                self._discovery_attempts, self._native_discovery_attempts)
            # Distinct pure storage for inventory native-parent duties.
            # Neither namespace is the old Cluster native-read namespace.
            self._guest_inventory_attempts = {}
            self._native_guest_inventory_attempts = {}
            self._original_guest_inventory_tables = (
                self._guest_inventory_attempts, self._native_guest_inventory_attempts)
            # Separate profile obligations before any future acquiring effect.
            # A map/count/entry is DATA, never a native allowance or receipt.
            self._guest_profile_attempts = {}
            self._native_guest_profile_attempts = {}
            self._original_guest_profile_tables = (
                self._guest_profile_attempts, self._native_guest_profile_attempts)
            self._guest_families_by_nonce = {}
            self._guest_families_by_ref = {}
            self._guest_reference_records = {}
            # Retain this pure DATA holder before its own map allocation.
            self._guest_capacity = object.__new__(_GuestCapacity)
            _GuestCapacity.__init__(self._guest_capacity)
            self._original_guest_capacity = self._guest_capacity
            self._original_component_tables = (
                self._auth_attempts, self._asset_attempts, self._issued_sessions,
                self._read_attempts, self._native_read_attempts,
                self._guest_families_by_nonce, self._guest_families_by_ref,
                self._guest_reference_records, self._guest_capacity._tickets)
            self._components_state = 'tables-ready'
            return
        except BaseException as error:
            first = self._component_preparation_failure = error
            self._component_preparation_errors[0] = error
        for index, (field, value) in enumerate((('_components_state', 'retirement-only'),
                             ('_live', False), ('_admission_uncertain', True)), 1):
            try:
                setattr(self, field, value)
            except BaseException as error:
                self._component_preparation_errors[index] = error
                first = _first_preparation_failure(first, error)
        self._component_preparation_failure = first
        if first is not None and (not issubclass(type(first), Exception) or issubclass(type(first), MemoryError)):
            raise first
        raise _RequestUnavailable() from None

    def _original_component_tables_current(self):
        """Identity filter for future native currentness, never admission.

        Caller holds the original installation gate after construction. Do not
        copy, clear, repair or replace any table when this filter refuses.
        Actual native owner/cohort/writer/currentness still belongs elsewhere.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if type(self) is not OriginalPilotInstallation:
            return False
        tables = self._original_component_tables
        if (type(tables) is not tuple or len(tables) != 9 or
                any(type(table) is not dict for table in tables) or
                any(tables[i] is tables[j] for i in range(9) for j in range(i))):
            return False
        return (self._auth_attempts is tables[0] and
                self._asset_attempts is tables[1] and
                self._issued_sessions is tables[2] and
                self._read_attempts is tables[3] and
                self._native_read_attempts is tables[4] and
                self._guest_families_by_nonce is tables[5] and
                self._guest_families_by_ref is tables[6] and
                self._guest_reference_records is tables[7] and
                type(self._guest_capacity) is _GuestCapacity and
                self._guest_capacity is self._original_guest_capacity and
                self._guest_capacity._tickets is tables[8] and
                self._guest_capacity._uncertain is False)

    def _original_guest_inventory_tables_current(self):
        """Positive storage identity/count filter only, never native authority.

        The original nine component maps remain their exact separate tuple.
        Future original inventory admission must capture BOTH new maps and
        reserve aggregate logical and physical parent allowances before work.
        Local cleanup must not clear the retained native table or use this
        positive-currentness predicate as its retirement/closure proof.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not OriginalPilotInstallation or
                self._original_component_tables_current() is not True):
            return False
        tables = self._original_guest_inventory_tables
        if (type(tables) is not tuple or len(tables) != 2 or
                any(type(table) is not dict or len(table) > 64 for table in tables) or
                tables[0] is tables[1] or
                any(table is prior for table in tables
                    for prior in self._original_component_tables)):
            return False
        return (self._guest_inventory_attempts is tables[0] and
                self._native_guest_inventory_attempts is tables[1])

    def _original_guest_profile_tables_current(self):
        """Positive identity/count DATA filter only, never native admission.

        Original nine component and two inventory maps remain independent.
        Future profile admission must retain both profile maps before any
        acquiring effect, with separately enforced whole-job allowances.
        Retirement must match captured identities without this positive filter;
        uncertainty can never license clearing a native duty or retrying work.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not OriginalPilotInstallation or
                self._original_guest_inventory_tables_current() is not True):
            return False
        tables = self._original_guest_profile_tables
        if (type(tables) is not tuple or len(tables) != 2 or
                any(type(table) is not dict or len(table) > 64 for table in tables) or
                tables[0] is tables[1] or
                any(table is prior for table in tables
                    for prior in self._original_component_tables +
                        self._original_guest_inventory_tables)):
            return False
        return (self._guest_profile_attempts is tables[0] and
                self._native_guest_profile_attempts is tables[1])

    def _original_discovery_tables_current(self):
        """Exact original storage identity filter; never scan authority.

        The distinct retirement-only map retains original duties after logical
        retirement. This prefix provides no clear/refund/retry, process receipt,
        operation capacity, request/session capture or physical closure API.
        No native allowance or positive currentness is created by empty maps.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not OriginalPilotInstallation or
                self._original_guest_profile_tables_current() is not True):
            return False
        tables = self._original_discovery_tables
        if (type(tables) is not tuple or len(tables) != 2 or
                any(type(table) is not dict for table in tables) or
                tables[0] is tables[1] or
                any(table is prior for table in tables
                    for prior in self._original_component_tables +
                        self._original_guest_inventory_tables +
                        self._original_guest_profile_tables)):
            return False
        return (self._discovery_attempts is tables[0] and
                self._native_discovery_attempts is tables[1])

    def _original_configured_data_current(self):
        """Same retained startup DATA only; no native/currentness authority.

        Called under the existing ordered original admission gates. This
        performs no source recheck, IO, callback or new acquisition. The same
        real native source/writer/credential/trust owner remains mandatory;
        these object identities cannot substitute for it or enable serving.
        Missing/partial construction refuses without repairing any field.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if type(self) is not OriginalPilotInstallation:
            return False
        try:
            data, startup = self._configured_data, self._startup_inputs
            if (type(data) is not PilotConfiguredData or
                    type(startup) is not OriginalStartupInputAttempt or
                    type(startup._state) is not str or
                    startup._state != 'retained' or startup._data is not data):
                return False
            return (self._configuration_revision is data.configuration_revision and
                    self._configured_nodes is data.nodes and
                    self._configured_roles is data.roles and
                    self._service_user is data.service_user and
                    self._configured_token_id is data.token_id and
                    self._config_supported is data.config_supported and
                    self._policy_supported is data.policy_supported)
        except AttributeError:
            # Exact original types can still be partially initialized after
            # a lost constructor return. No positive adoption or retry.
            return False

    def _original_fleet_targets_data_current(self):
        """Same optional retained Fleet DATA; no native or response grant.

        Like the separate Cluster DATA identity filter, this does no source
        diagnostic, parser, clock, callback or IO under admission gates. An
        unsupported optional projection refuses only Fleet use. It cannot
        change Cluster eligibility or supply SSH settings or a native owner.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if type(self) is not OriginalPilotInstallation:
            return False
        try:
            if self._original_configured_data_current() is not True:
                return False
            data = self._configured_fleet_targets_data
            return (type(data) is ConfiguredFleetTargetsData and
                    self._startup_inputs._fleet_targets_data is data)
        except AttributeError:
            return False

    def _bind_original_components(self):
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        from freq.services.pilot_snippet_pending import _PendingOriginalSnippetCustodian
        if type(self) is not OriginalPilotInstallation:
            raise _RequestUnavailable()
        # Refuse an incomplete or retirement-only pure prefix before even
        # looking up its server/gate/startup resource fields. These original
        # state checks grant no native custody, currentness or admission.
        if (type(self._pending_state) is not str or
                self._pending_state != 'prepared' or
                self._pending_retirement_required is not False or
                type(self._snippet_custodian) is not _PendingOriginalSnippetCustodian or
                _PendingOriginalSnippetCustodian._pending_storage_ready(self._snippet_custodian, self) is not True):
            raise _RequestUnavailable()
        # Actual constructor-owned fields, not caller-selected arguments.
        server = self._server
        if (type(server) is not _OriginalPilotServer or
                server._cluster_pilot_installation is not self or
                type(server._pilot_requests) is not _OriginalHTTPRequests or
                server._pilot_requests._server is not server or
                server._pilot_requests._live is not False or
                server._pilot_requests._gate_uncertain is not False or
                type(server._pilot_requests._requests) is not dict or
                server._pilot_requests._requests or self._live is not False or
                self._admission_uncertain is not False or
                type(self._gate) is not LockType or
                type(self._source_uid) is not int or
                type(self._credential_uid) is not int or
                not 1 <= self._source_uid <= 4294967294 or
                not 1 <= self._credential_uid <= 4294967294 or
                self._source_uid == self._credential_uid or
                self._components_state != 'tables-ready' or
                self._original_component_tables_current() is not True or
                self._original_guest_inventory_tables_current() is not True or
                any(self._original_guest_inventory_tables) or
                self._original_guest_profile_tables_current() is not True or
                any(self._original_guest_profile_tables) or
                self._original_discovery_tables_current() is not True or
                any(self._original_discovery_tables) or
                self._discovery_contexts is not None or
                self._discovery_collector_storage is not None or
                any(self._original_component_tables) or
                type(self._startup_inputs) is not OriginalStartupInputAttempt):
            raise _RequestUnavailable()
        if (self._startup_inputs._sources._uid != self._source_uid or
                self._startup_inputs._identity._source_uid != self._source_uid):
            raise _RequestUnavailable()
        # Permanent before any allocation/parser/native diagnostic. Never reset
        # an old instance or allow retry after partial construction/interrupt.
        self._components_state = 'construction-pending'
        first = None
        try:
            # Same original retained readers, native diagnostics outside every
            # admission gate. Actual hard parent and all-writer fence required.
            data = self._startup_inputs.private_data()
            if type(data) is not PilotConfiguredData:
                raise _RequestUnavailable()
            self._configured_data = data
            self._configuration_revision = data.configuration_revision
            self._configured_nodes = data.nodes
            self._configured_roles = data.roles
            self._service_user = data.service_user
            self._configured_token_id = data.token_id
            self._config_supported = data.config_supported
            self._policy_supported = data.policy_supported

            # Retain the SAME optional hosts-byte projection, not a second
            # parse, copy or legacy-loader result. The preceding original
            # private_data diagnostic was outside gates; final identity filters
            # below still refuse a changed or retired startup. None means that
            # Fleet's pair syntax is unsupported, without disabling Cluster.
            fleet_targets = self._startup_inputs._fleet_targets_data
            if (fleet_targets is not None and
                    type(fleet_targets) is not ConfiguredFleetTargetsData):
                raise _RequestUnavailable()
            self._configured_fleet_targets_data = fleet_targets

            # Exact private tables were retained before any original gate or
            # server allocation. Construction must not replace/refund them.
            # The original auth module session/rate maps also stay untouched.
            # Retain the SAME reference holder before its native lock constructor;
            # unknown lock returns remain external original-parent duty.
            self._references = object.__new__(ClusterReferences)
            ClusterReferences.__init__(self._references)

            # Explicit order follows exact constructor prerequisites. All
            # successful partial objects stay strongly retained on this SAME
            # installation; lost allocations still need physical retirement.
            self._auth_inputs = OriginalPilotAuthAttempts(self)
            self._auth_commit = OriginalAuthCommit(self)
            self._login_rate = OriginalPilotLoginRate(self)
            # Retain this exact pure component before its field initializer.
            discovery_contexts = object.__new__(OriginalDiscoveryRequestContexts)
            self._discovery_contexts = discovery_contexts
            OriginalDiscoveryRequestContexts.__init__(discovery_contexts, self)
            # Same pure storage component root precedes its once initializer.
            collector_storage = object.__new__(_OriginalDiscoveryCollectorStorage)
            self._discovery_collector_storage = collector_storage
            _OriginalDiscoveryCollectorStorage._initialize(collector_storage, self)
            if (self._discovery_contexts is not discovery_contexts or
                    self._discovery_collector_storage is not collector_storage):
                raise _RequestUnavailable()
            # Retain the SAME new private component before initializing even
            # its pure fields. No constructor-return adoption/retry or serving.
            self._guest_reference_store = object.__new__(OriginalGuestReferenceStore)
            self._original_guest_reference_store = self._guest_reference_store
            OriginalGuestReferenceStore.__init__(self._guest_reference_store, self)
            self._cluster_selections = OriginalClusterSelections(self)
            self._cluster_reads = OriginalClusterReads(self)
            self._static_responder = OriginalPilotStatic(self)
            # Pre-retain the same pure read component before initialization.
            # Constructor loss never licenses a replacement or second binding.
            fleet_reader = object.__new__(OriginalPilotFleetTargets)
            self._fleet_targets_reader = fleet_reader
            OriginalPilotFleetTargets.__init__(fleet_reader, self)
            self._dispatcher = OriginalPilotDispatch(self)
            self._startup_inputs._current_data()
            if (type(self._snippet_custodian) is not _PendingOriginalSnippetCustodian or
                    _PendingOriginalSnippetCustodian._pending_storage_ready(self._snippet_custodian, self) is not True or
                    self._original_component_tables_current() is not True or
                    self._original_discovery_tables_current() is not True or
                    any(self._original_discovery_tables) or
                    self._discovery_contexts is not discovery_contexts or
                    self._discovery_collector_storage is not collector_storage or
                    self._original_configured_data_current() is not True or
                    self._fleet_targets_reader is not fleet_reader or
                    self._configured_fleet_targets_data is not fleet_targets or
                    self._startup_inputs._fleet_targets_data is not fleet_targets or
                    (fleet_targets is not None and
                     self._original_fleet_targets_data_current() is not True)):
                raise _RequestUnavailable()
            self._components_state = 'constructed-inactive'
            # Deliberately no _live/broker enable, serve loop, success receipt
            # or native currentness claim. Actual original factory still owes
            # the final physical/native construction and activation gates.
            return
        except BaseException as error:
            first = self._component_binding_failure = error
            self._component_binding_errors[0] = error
        # Retain actual failures in storage allocated before any acquiring
        # construction. Attempt each quarantine independently; no temporary
        # cleanup collection is allocated after a constructor has failed.
        # These local assignments do not prove physical/native retirement.
        try:
            setattr(self, '_components_state', 'retirement-only')
        except BaseException as error:
            self._component_binding_errors[1] = error
            first = _first_preparation_failure(first, error)
        try:
            setattr(self, '_live', False)
        except BaseException as error:
            self._component_binding_errors[2] = error
            first = _first_preparation_failure(first, error)
        try:
            setattr(self, '_admission_uncertain', True)
        except BaseException as error:
            self._component_binding_errors[3] = error
            first = _first_preparation_failure(first, error)
        try:
            setattr(server._pilot_requests, '_live', False)
        except BaseException as error:
            self._component_binding_errors[4] = error
            first = _first_preparation_failure(first, error)
        self._component_binding_failure = first
        if first is not None and (not issubclass(type(first), Exception) or issubclass(type(first), MemoryError)):
            raise first
        raise _RequestUnavailable() from None


# No OriginalPilotInstallation definition, native factory, listener or issuer.
