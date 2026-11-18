"""Actual binding orchestration with explicitly fictional resource ports.

Canonical objects carry DATA only. Gate type, source diagnostics and downstream
component constructors are mocked; no actual native parent is established.
"""
from contextlib import ExitStack, contextmanager
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from freq.services import pilot_component_binding as binding
from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.pilot_configured_cohort import PilotConfiguredData
from freq.services.pilot_startup_acquisition import OriginalStartupInputAttempt
from freq.services.pilot_fleet_targets_data import (
    ConfiguredFleetTargetsData, decode_fleet_target_bytes,
)


_DEFAULT = object()


class FictionalGate:
    pass


class FleetComponentRetentionData(unittest.TestCase):
    @contextmanager
    def fixture(self, fleet=_DEFAULT):
        if fleet is _DEFAULT:
            fleet = decode_fleet_target_bytes(
                b'[[host]]\nlabel="fixture-host"\nip="192.0.2.7"\n')
        owner = OriginalPilotInstallation()
        owner._prepare_pending_original()
        startup = object.__new__(OriginalStartupInputAttempt)
        config = PilotConfiguredData('fixture-revision', (),
            MappingProxyType({'fixture': 'viewer'}), 'fixture-service',
            ('fixture@pve', 'configured'), True, True)
        startup._state, startup._data = 'retained', config
        startup._fleet_targets_data = fleet
        startup._sources = SimpleNamespace(_uid=1003)
        startup._identity = SimpleNamespace(_source_uid=1003)
        owner._startup_inputs = startup
        owner._source_uid, owner._credential_uid = 1003, 1004
        owner._gate = FictionalGate()
        server = object.__new__(binding._OriginalPilotServer)
        broker = object.__new__(binding._OriginalHTTPRequests)
        broker._server, broker._live = server, False
        broker._gate_uncertain, broker._requests = False, {}
        server._cluster_pilot_installation, server._pilot_requests = owner, broker
        owner._server = server
        with ExitStack() as stack:
            stack.enter_context(patch.object(binding, 'LockType', FictionalGate))
            read = stack.enter_context(patch.object(
                OriginalStartupInputAttempt, 'private_data', return_value=config))
            recheck = stack.enter_context(patch.object(
                OriginalStartupInputAttempt, '_current_data'))
            stack.enter_context(patch.object(binding.ClusterReferences, '__init__',
                                            return_value=None))
            stack.enter_context(patch.object(binding.OriginalGuestReferenceStore,
                                            '__init__', return_value=None))
            # New pure read constructor is an explicit fictional downstream port.
            stack.enter_context(patch.object(binding.OriginalPilotFleetTargets,
                                            '__init__', return_value=None))
            ports = {}
            for name in ('OriginalPilotAuthAttempts', 'OriginalAuthCommit',
                         'OriginalPilotLoginRate', 'OriginalClusterSelections',
                         'OriginalClusterReads', 'OriginalPilotStatic',
                         'OriginalPilotDispatch'):
                ports[name] = stack.enter_context(patch.object(
                    binding, name, Mock(side_effect=lambda unused: object())))
            yield SimpleNamespace(owner=owner, startup=startup, config=config,
                                  fleet=fleet, read=read, recheck=recheck, ports=ports)

    def test_FC01_binding_retains_same_optional_projection_without_reparse(self):
        with self.fixture() as f:
            f.owner._bind_original_components()
            self.assertIs(f.owner._configured_fleet_targets_data, f.fleet)
            self.assertIs(f.owner._configured_data, f.config)
            self.assertTrue(f.owner._original_fleet_targets_data_current())
            self.assertEqual(f.owner._components_state, 'constructed-inactive')
            f.read.assert_called_once_with()
            f.recheck.assert_called_once_with()

    def test_FC02_explicit_empty_projection_remains_same_supported_object(self):
        empty = decode_fleet_target_bytes(b'host=[]')
        with self.fixture(empty) as f:
            f.owner._bind_original_components()
            self.assertIs(f.owner._configured_fleet_targets_data, empty)
            self.assertEqual(empty.pairs, ())
            self.assertTrue(f.owner._original_fleet_targets_data_current())

    def test_FC03_unsupported_optional_projection_preserves_cluster_binding(self):
        with self.fixture(None) as f:
            f.owner._bind_original_components()
            self.assertIsNone(f.owner._configured_fleet_targets_data)
            self.assertFalse(f.owner._original_fleet_targets_data_current())
            self.assertTrue(f.owner._original_configured_data_current())
            self.assertEqual(f.owner._components_state, 'constructed-inactive')

    def test_FC04_wrong_optional_type_refuses_before_downstream_constructors(self):
        class Hostile:
            def __getattribute__(self, name):
                raise AssertionError('foreign attribute hook')
            def __eq__(self, other):
                raise AssertionError('foreign equality hook')
        with self.fixture(Hostile()) as f:
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            for port in f.ports.values():
                port.assert_not_called()
            self.assertIsNone(f.owner._configured_fleet_targets_data)
            self.assertEqual(f.owner._components_state, 'retirement-only')
            self.assertIs(f.owner._live, False)

    def test_FC05_late_projection_replacement_cannot_finish_binding(self):
        with self.fixture() as f:
            def replace(unused):
                f.startup._fleet_targets_data = ConfiguredFleetTargetsData(
                    f.fleet.pairs, f.fleet.target_set_sha256)
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = replace
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertIs(f.owner._configured_fleet_targets_data, f.fleet)
            self.assertEqual(f.owner._components_state, 'retirement-only')
            self.assertIs(f.owner._admission_uncertain, True)

    def test_FC06_equal_replacement_on_owner_refuses_without_cluster_repair(self):
        with self.fixture() as f:
            f.owner._bind_original_components()
            f.owner._configured_fleet_targets_data = ConfiguredFleetTargetsData(
                f.fleet.pairs, f.fleet.target_set_sha256)
            self.assertFalse(f.owner._original_fleet_targets_data_current())
            self.assertTrue(f.owner._original_configured_data_current())
            self.assertIs(f.startup._fleet_targets_data, f.fleet)

    def test_FC07_startup_data_replacement_invalidates_fleet_filter(self):
        with self.fixture() as f:
            f.owner._bind_original_components()
            f.startup._data = object()
            self.assertFalse(f.owner._original_fleet_targets_data_current())
            self.assertIs(f.owner._configured_fleet_targets_data, f.fleet)

    def test_FC08_retired_startup_invalidates_retained_copy_without_io(self):
        with self.fixture() as f:
            f.owner._bind_original_components()
            f.startup._state, f.startup._fleet_targets_data = 'retired', None
            f.read.reset_mock(); f.recheck.reset_mock()
            self.assertFalse(f.owner._original_fleet_targets_data_current())
            self.assertIs(f.owner._configured_fleet_targets_data, f.fleet)
            f.read.assert_not_called(); f.recheck.assert_not_called()

    def test_FC09_partial_pending_installation_refuses_without_field_repair(self):
        owner = object.__new__(OriginalPilotInstallation)
        self.assertFalse(owner._original_fleet_targets_data_current())
        self.assertFalse(hasattr(owner, '_configured_fleet_targets_data'))

    def test_FC10_foreign_self_refuses_before_attribute_hooks(self):
        class Hostile:
            def __getattribute__(self, name):
                raise AssertionError('foreign attribute hook')
        self.assertFalse(binding._OriginalPilotComponentBinding.
                         _original_fleet_targets_data_current(Hostile()))

    def test_FC11_data_filter_never_invokes_source_diagnostics_under_gates(self):
        with self.fixture() as f:
            f.owner._bind_original_components()
            f.read.reset_mock(); f.recheck.reset_mock()
            f.read.side_effect = AssertionError('source diagnostic under gates')
            f.recheck.side_effect = AssertionError('source diagnostic under gates')
            self.assertTrue(f.owner._original_fleet_targets_data_current())
            f.read.assert_not_called(); f.recheck.assert_not_called()

    def test_FC12_supported_projection_still_cannot_issue_native_admission(self):
        with self.fixture() as f:
            f.owner._bind_original_components()
            self.assertTrue(f.owner._original_fleet_targets_data_current())
            self.assertFalse(f.owner._native_current_locked(object()))
            self.assertIs(f.owner._live, False)
            self.assertIs(f.owner._server._pilot_requests._live, False)

    def test_FC13_repeated_installation_init_cannot_replace_retained_projection(self):
        with self.fixture() as f:
            f.owner._bind_original_components()
            OriginalPilotInstallation.__init__(f.owner)
            self.assertIs(f.owner._configured_fleet_targets_data, f.fleet)
            self.assertIs(f.owner._startup_inputs, f.startup)
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            f.read.assert_called_once_with()

    def test_FC14_late_retirement_refuses_final_binding_without_restoring_startup(self):
        with self.fixture() as f:
            def retire(unused):
                f.startup._state, f.startup._fleet_targets_data = 'retired', None
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = retire
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertEqual(f.startup._state, 'retired')
            self.assertEqual(f.owner._components_state, 'retirement-only')
            self.assertIs(f.owner._live, False)

    def test_FC15_clearing_only_owner_projection_cannot_skip_captured_obligation(self):
        with self.fixture() as f:
            def clear(unused):
                f.owner._configured_fleet_targets_data = None
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = clear
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertIs(f.startup._fleet_targets_data, f.fleet)
            self.assertEqual(f.owner._components_state, 'retirement-only')

    def test_FC16_clearing_both_projections_cannot_reclassify_supported_as_optional(self):
        with self.fixture() as f:
            def clear(unused):
                f.owner._configured_fleet_targets_data = None
                f.startup._fleet_targets_data = None
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = clear
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertEqual(f.owner._components_state, 'retirement-only')
            self.assertIs(f.owner._admission_uncertain, True)

    def test_FC17_initial_none_cannot_be_replaced_on_owner_during_construction(self):
        with self.fixture(None) as f:
            def insert(unused):
                f.owner._configured_fleet_targets_data = decode_fleet_target_bytes(b'host=[]')
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = insert
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertIsNone(f.startup._fleet_targets_data)
            self.assertEqual(f.owner._components_state, 'retirement-only')

    def test_FC18_initial_none_cannot_be_replaced_only_on_startup(self):
        with self.fixture(None) as f:
            def insert(unused):
                f.startup._fleet_targets_data = decode_fleet_target_bytes(b'host=[]')
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = insert
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertIsNone(f.owner._configured_fleet_targets_data)
            self.assertEqual(f.owner._components_state, 'retirement-only')

    def test_FC19_initial_none_cannot_adopt_one_new_object_in_both_slots(self):
        with self.fixture(None) as f:
            def insert(unused):
                late = decode_fleet_target_bytes(b'host=[]')
                f.startup._fleet_targets_data = late
                f.owner._configured_fleet_targets_data = late
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = insert
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertIs(f.owner._configured_fleet_targets_data, f.startup._fleet_targets_data)
            self.assertEqual(f.owner._components_state, 'retirement-only')
            self.assertFalse(f.owner._native_current_locked(object()))

    def test_FC20_missing_owner_slot_cannot_be_repaired_or_finish_construction(self):
        with self.fixture() as f:
            def remove(unused):
                del f.owner._configured_fleet_targets_data
                return object()
            f.ports['OriginalPilotDispatch'].side_effect = remove
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertFalse(hasattr(f.owner, '_configured_fleet_targets_data'))
            self.assertIs(f.startup._fleet_targets_data, f.fleet)
            self.assertEqual(f.owner._components_state, 'retirement-only')
