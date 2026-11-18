"""Pure original-type DATA correspondence, no acquiring constructor/authority."""
import unittest
from types import MappingProxyType
from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.pilot_startup_acquisition import OriginalStartupInputAttempt
from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.pilot_cluster_selections import OriginalClusterSelections, _SelectionRefused
from freq.services.cluster_references import ClusterReferences, TargetSnapshot


class ConfiguredCohortRetentionData(unittest.TestCase):
    def setUp(self):
        self.owner = OriginalPilotInstallation()
        revision = 'fixture-revision-with-deliberate-noninterned-value'
        nodes = (('node-fixture', TargetSnapshot(revision, 'configured-node-0', '192.0.2.1')),)
        self.data = PilotConfiguredData(revision, nodes, MappingProxyType({'fixture': 'viewer'}),
                                        'fixture-service-account', ('fixture@pve', 'configured'), True, True)
        self.startup = object.__new__(OriginalStartupInputAttempt)
        self.startup._state, self.startup._data = 'retained', self.data
        self.owner._startup_inputs, self.owner._configured_data = self.startup, self.data
        for field, value in (('_configuration_revision', self.data.configuration_revision),
                             ('_configured_nodes', self.data.nodes), ('_configured_roles', self.data.roles),
                             ('_service_user', self.data.service_user), ('_configured_token_id', self.data.token_id),
                             ('_config_supported', self.data.config_supported), ('_policy_supported', self.data.policy_supported)):
            setattr(self.owner, field, value)
        self.reader = object.__new__(OriginalClusterSelections)
        self.reader._installation = self.owner
        self.reader._references = object.__new__(ClusterReferences)

    def refused(self):
        with self.assertRaises(_SelectionRefused) as caught: self.reader._cohort_locked()
        self.assertEqual(caught.exception.status, 503)

    def test_CC01_exact_retained_data_remains_only_a_positive_identity_filter(self):
        self.assertIs(self.reader._cohort_locked(), self.data.nodes)
        self.assertTrue(self.owner._original_configured_data_current())
        self.assertFalse(self.owner._native_current_locked(object()))
        self.assertIs(self.owner._live, False)

    def test_CC02_equal_replacement_node_tuple_is_refused(self):
        self.owner._configured_nodes = tuple(list(self.data.nodes))
        self.assertEqual(self.owner._configured_nodes, self.data.nodes)
        self.assertIsNot(self.owner._configured_nodes, self.data.nodes)
        self.refused()

    def test_CC03_changed_per_node_token_tuple_is_refused_before_deriving_endpoint(self):
        self.owner._configured_token_id = ('different@pve', 'configured')
        self.refused()

    def test_CC04_replaced_startup_data_even_with_same_fields_is_refused(self):
        d = self.data
        self.startup._data = PilotConfiguredData(d.configuration_revision, d.nodes, d.roles,
                                                d.service_user, d.token_id, d.config_supported, d.policy_supported)
        self.refused()

    def test_CC05_equal_revision_reallocation_is_refused(self):
        self.owner._configuration_revision = self.data.configuration_revision.encode().decode()
        self.assertIsNot(self.owner._configuration_revision, self.data.configuration_revision)
        self.refused()

    def test_CC06_replacement_role_mapping_is_refused(self):
        self.owner._configured_roles = MappingProxyType({'fixture': 'viewer'})
        self.refused()

    def test_CC07_equal_service_user_reallocation_is_refused(self):
        self.owner._service_user = self.data.service_user.encode().decode()
        self.assertIsNot(self.owner._service_user, self.data.service_user)
        self.refused()

    def test_CC08_changed_config_support_is_refused(self):
        self.owner._config_supported = False
        self.refused()

    def test_CC09_changed_policy_support_is_refused(self):
        self.owner._policy_supported = False
        self.refused()

    def test_CC10_retired_startup_source_cannot_supply_retained_cohort(self):
        self.startup._state = 'retired'
        self.refused()

    def test_CC11_partial_original_startup_refuses_without_repair(self):
        self.owner._startup_inputs = object.__new__(OriginalStartupInputAttempt)
        self.refused()
        self.assertIs(self.owner._configured_data, self.data)

    def test_CC12_foreign_data_refuses_without_hooks(self):
        class Hostile:
            def __getattribute__(self, name): raise AssertionError('foreign attribute hook')
            def __eq__(self, other): raise AssertionError('foreign equality hook')
        self.owner._configured_data = Hostile()
        self.refused()

    def test_CC13_missing_token_is_not_filled_or_replaced_by_inventory_filter(self):
        d = self.data
        missing = PilotConfiguredData(d.configuration_revision, d.nodes, d.roles, d.service_user, None, True, True)
        self.owner._configured_data = self.startup._data = missing
        self.owner._configured_token_id = None
        self.assertIs(self.reader._cohort_locked(), self.data.nodes)
        self.assertIsNone(self.owner._configured_token_id)
        self.assertFalse(self.owner._native_current_locked(object()))

    def test_CC14_foreign_startup_state_refuses_without_equality_hook(self):
        class Hostile:
            def __eq__(self, other): raise AssertionError('foreign equality hook')
        self.startup._state = Hostile()
        self.refused()
