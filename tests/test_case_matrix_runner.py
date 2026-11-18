"""Causal and failure-path lifecycle proof for consolidated case owners."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.case_matrix import run_case_matrix


def _run_probe(case_type: type[unittest.TestCase]) -> unittest.TestResult:
    class _Owner(unittest.TestCase):
        def test_owner(self):
            run_case_matrix(self, case_type, ("test_case",))

    result = unittest.TestResult()
    _Owner("test_owner").run(result)
    return result


class TestCaseMatrixRunner(unittest.TestCase):
    def test_direct_unittest_help_contract_without_pythonpath(self):
        repo = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        for relative in (
            "tests/test_admin_api.py",
            "tests/test_auth_decorator.py",
            "tests/test_auth_integration.py",
            "tests/test_dashboard_events_service.py",
            "tests/test_device_creds_contract.py",
            "tests/test_edge_cases.py",
            "tests/test_foundation.py",
            "tests/test_init_cmd.py",
            "tests/test_install.py",
            "tests/test_jarvis_cost.py",
            "tests/test_jarvis_capacity.py",
            "tests/test_jarvis_chaos.py",
            "tests/test_jarvis_federation.py",
            "tests/test_jarvis_playbook.py",
            "tests/test_jarvis_edge_cases.py",
            "tests/test_jarvis_rules.py",
            "tests/test_logging_lifecycle.py",
            "tests/test_capacity_recommend.py",
            "tests/test_plan.py",
            "tests/test_serve_cache.py",
            "tests/test_serve_helpers.py",
            "tests/test_phase2_gateway.py",
            "tests/test_setup_status_truth.py",
            "tests/test_switch_orchestration.py",
            "tests/test_phase1_killers.py",
            "tests/test_overnight_deep.py",
            "tests/test_overnight_tier1.py",
            "tests/test_overnight_tier3_6.py",
            "tests/test_overnight_extra.py",
        ):
            with self.subTest(relative=relative):
                result = subprocess.run(
                    [sys.executable, relative, "--help"],
                    cwd=repo,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        from tests import test_overnight_deep

        with tempfile.TemporaryDirectory() as tmp:
            absent_config = str(Path(tmp) / "absent-config")
            clean_cases = (
                (
                    test_overnight_deep.TestContainerLoading,
                    "test_load_containers_from_config",
                ),
                (
                    test_overnight_deep.TestVLANLoading,
                    "test_load_vlans_from_config",
                ),
            )
            for case_type, case_name in clean_cases:
                with self.subTest(case=case_name), patch.object(
                    test_overnight_deep,
                    "CONF_DIR",
                    absent_config,
                ):
                    result = unittest.TestResult()
                    case_type(case_name).run(result)
                    self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                    self.assertEqual(result.skipped, [])

    def test_failure_paths_preserve_teardown_cleanup_and_outcome_kind(self):
        events: list[str] = []

        class _TestFailure(unittest.TestCase):
            def setUp(self):
                events.append("test:setUp")
                self.addCleanup(events.append, "test:cleanup")

            def tearDown(self):
                events.append("test:tearDown")

            def test_case(self):
                events.append("test:case")
                raise AssertionError("forced test failure")

        class _SetUpError(unittest.TestCase):
            def setUp(self):
                events.append("setup:setUp")
                self.addCleanup(events.append, "setup:cleanup")
                raise RuntimeError("forced setup error")

            def test_case(self):
                raise AssertionError("unreachable")

        class _TearDownError(unittest.TestCase):
            def setUp(self):
                events.append("teardown:setUp")
                self.addCleanup(events.append, "teardown:cleanup")

            def tearDown(self):
                events.append("teardown:tearDown")
                raise RuntimeError("forced teardown error")

            def test_case(self):
                events.append("teardown:case")

        class _Skip(unittest.TestCase):
            def setUp(self):
                events.append("skip:setUp")
                self.addCleanup(events.append, "skip:cleanup")

            def tearDown(self):
                events.append("skip:tearDown")

            def test_case(self):
                events.append("skip:case")
                raise unittest.SkipTest("forced skip")

        failure = _run_probe(_TestFailure)
        setup_error = _run_probe(_SetUpError)
        teardown_error = _run_probe(_TearDownError)
        skipped = _run_probe(_Skip)

        self.assertEqual((len(failure.failures), len(failure.errors)), (1, 0))
        self.assertEqual((len(setup_error.failures), len(setup_error.errors)), (0, 1))
        self.assertEqual((len(teardown_error.failures), len(teardown_error.errors)), (0, 1))
        self.assertEqual(len(skipped.skipped), 1)
        self.assertEqual(
            events,
            [
                "test:setUp", "test:case", "test:tearDown", "test:cleanup",
                "setup:setUp", "setup:cleanup",
                "teardown:setUp", "teardown:case", "teardown:tearDown", "teardown:cleanup",
                "skip:setUp", "skip:case", "skip:tearDown", "skip:cleanup",
            ],
        )

    def test_each_matrix_detects_failure_and_hosts_leaves_no_artifact(self):
        from tests.test_admin_api import (
            FB_TOML_CASES,
            TestUpdateFbToml,
            TestUpdateFbTomlMatrix,
        )
        from tests.test_auth_integration import (
            AUTH_LIFECYCLE_CASES,
            SESSION_EXPIRY_CASES,
            TestFullAuthLifecycle,
            TestFullAuthLifecycleMatrix,
            TestSessionExpiry,
            TestSessionExpiryMatrix,
        )
        from tests.test_auth_decorator import (
            REQUIRE_ROLE_CASES,
            TestRequireRole,
            TestRequireRoleMatrix,
        )
        from tests.test_device_creds_contract import (
            RUNTIME_DEVICE_CREDENTIAL_CASES,
            TestRuntimeDeviceCredentials,
            TestRuntimeDeviceCredentialsMatrix,
        )
        from tests.test_dashboard_events_service import (
            DASHBOARD_EVENT_SERVICE_CASES,
            DashboardEventServiceTests,
            TestDashboardEventServiceMatrix,
        )
        from tests.test_capacity_recommend import (
            CAPACITY_RECOMMENDATION_CASES,
            TestRecommendMigrations,
            TestRecommendMigrationsMatrix,
        )
        from tests.test_edge_cases import (
            CONFIG_CORRUPTION_CASES,
            CONFIG_MISSING_FIELDS_CASES,
            DUP_LABEL_CALLER_CASES,
            FLEET_ZERO_HOSTS_CASES,
            HOSTS_CONF_CASES,
            MALFORMED_TOML_CASES,
            PVE_API_EDGE_CASES,
            SSH_RESULT_EDGE_CASES,
            SSH_TRANSPORT_EDGE_CASES,
            VALIDATE_BOUNDARY_CASES,
            VALIDATE_EXTENDED_CASES,
            VAULT_PARSING_CASES,
            TestConfigCorruption,
            TestConfigCorruptionMatrix,
            TestConfigMissingFields,
            TestConfigMissingFieldsMatrix,
            TestDupLabelCallers,
            TestDupLabelCallersMatrix,
            TestFleetZeroHosts,
            TestFleetZeroHostsMatrix,
            TestHostsConf,
            TestHostsConfMatrix,
            TestMalformedToml,
            TestMalformedTomlMatrix,
            TestPVEApiEdgeCases,
            TestPVEApiEdgeCasesMatrix,
            TestSSHResultEdgeCases,
            TestSSHResultEdgeCasesMatrix,
            TestSSHTransportEdgeCases,
            TestSSHTransportEdgeCasesMatrix,
            TestValidateBoundaryTables,
            TestValidateBoundaryTablesMatrix,
            TestValidateExtended,
            TestValidateExtendedMatrix,
            TestVaultParsing,
            TestVaultParsingMatrix,
        )
        from tests.test_fleet_operator_truth_contract import (
            FLEET_OPERATOR_TRUTH_CASES,
            TestFleetOperatorTruthMatrix,
            TestFleetProbeNoiseContract,
        )
        from tests.test_hosts_sync import HOSTS_SYNC_CASES, TestHostsSync, TestHostsSyncMatrix
        from tests.test_foundation import (
            VALIDATION_CASES,
            TestValidation,
            TestValidationMatrix,
        )
        from tests.test_jarvis_cost import (
            COMPUTE_COST_CASES,
            TestComputeCosts,
            TestComputeCostsMatrix,
        )
        from tests.test_jarvis_capacity import (
            CAPACITY_PARSING_CASES,
            CAPACITY_PROJECTION_CASES,
            LINEAR_REGRESSION_CASES,
            SHOULD_SNAPSHOT_CASES,
            SNAPSHOT_IO_CASES,
            TestCapacityParsingMatrix,
            TestCapacityProjectionsMatrix,
            TestLinearRegression,
            TestLinearRegressionMatrix,
            TestParsing,
            TestProjections,
            TestShouldSnapshot,
            TestShouldSnapshotMatrix,
            TestSnapshotIO,
            TestSnapshotIOMatrix,
        )
        from tests import (
            test_jarvis_chaos as chaos_cases,
            test_jarvis_cost as cost_cases,
            test_jarvis_edge_cases as jarvis_edge_cases,
            test_jarvis_federation as federation_cases,
            test_jarvis_playbook as playbook_cases,
            test_jarvis_rules as rule_cases,
            test_overnight_extra as overnight_extra_cases,
            test_overnight_tier1 as overnight_tier1_cases,
            test_overnight_tier3_6 as overnight_tier3_6_cases,
        )
        from tests.test_jarvis_rules import (
            RULE_EVALUATION_CASES,
            TestEvaluation,
            TestEvaluationMatrix,
        )
        from tests.test_logging_lifecycle import (
            METRICS_DB_LIFECYCLE_CASES,
            TestMetricsDbLifecycle,
            TestMetricsDbLifecycleMatrix,
        )
        from tests.test_idrac_session_service import (
            IDRAC_SESSION_SERVICE_CASES,
            IdracSessionServiceTests,
            TestIdracSessionServiceMatrix,
        )
        from tests.test_init_cmd import (
            HEADLESS_FLEET_DEPLOY_CASES,
            IDRAC_PARSING_CASES,
            INIT_RESET_LOCAL_STATE_CASES,
            PHASE_CONFIGURE_CASES,
            PHASE_DISCOVER_SCOPED_HOSTS_CASES,
            PVE_UNINSTALL_CASES,
            RUN_WITH_INPUT_CASES,
            SSH_WITH_PASS_CASES,
            TestHeadlessFleetDeployTruth,
            TestHeadlessFleetDeployTruthMatrix,
            TestIdracParsing,
            TestIdracParsingMatrix,
            TestInitResetLocalState,
            TestInitResetLocalStateMatrix,
            TestPhaseConfigure,
            TestPhaseConfigureMatrix,
            TestPhaseDiscoverScopedHosts,
            TestPhaseDiscoverScopedHostsMatrix,
            TestPveUninstall,
            TestPveUninstallMatrix,
            TestRunWithInput,
            TestRunWithInputMatrix,
            TestSSHWithPass,
            TestSSHWithPassMatrix,
        )
        from tests.test_install import (
            PROJECT_FILE_CASES,
            TestProjectFiles,
            TestProjectFilesMatrix,
        )
        from tests.test_overnight_deep import (
            DOCTOR_CHECK_CASES,
            TestDoctorChecks,
            TestDoctorChecksMatrix,
        )
        from tests.test_phase1_killers import (
            ALERT_MODULE_CASES,
            FLEET_INVENTORY_CONTRACT_CASES,
            TestAlertModule,
            TestAlertModuleMatrix,
            TestFleetInventoryContracts,
            TestFleetInventoryContractsMatrix,
        )
        from tests.test_plan import PLAN_DIFF_CASES, TestPlanDiff, TestPlanDiffMatrix
        from tests.test_phase2_gateway import (
            CERT_LIFECYCLE_PLAN_CASES,
            TestCertLifecyclePlan,
            TestCertLifecyclePlanMatrix,
        )
        from tests.test_serve_helpers import (
            PARSE_QUERY_CASES,
            ROUTE_TABLE_CASES,
            SESSION_ROLE_CASES,
            TestCheckSessionRole,
            TestCheckSessionRoleMatrix,
            TestParseQuery,
            TestParseQueryMatrix,
            TestRouteTable,
            TestRouteTableMatrix,
        )
        from tests.test_serve_cache import (
            BG_PROBE_HEALTH_CASES,
            SSE_EVENT_BUS_CASES,
            TestBgProbeHealth,
            TestBgProbeHealthMatrix,
            TestSSEEventBus,
            TestSSEEventBusMatrix,
        )
        from tests.test_setup_status_truth import (
            SETUP_HEALTH_SUMMARY_CASES,
            TestSetupHealthSummary,
            TestSetupHealthSummaryMatrix,
        )
        from tests.test_test_redesign_tooling import (
            TEST_HEALTH_TOOL_CASES,
            TestHealthTool,
            TestHealthToolMatrix,
        )
        from tests.test_switch_orchestration import (
            CISCO_ARP_TABLE_CASES,
            CISCO_CDP_DETAIL_CASES,
            CISCO_DEPLOYER_INTERFACE_CASES,
            CISCO_INTERFACES_STATUS_CASES,
            CISCO_MAC_TABLE_CASES,
            CISCO_POWER_INLINE_CASES,
            CISCO_SHOW_VERSION_CASES,
            CISCO_TRANSPORT_CASES,
            CISCO_VLAN_BRIEF_CASES,
            EXPAND_PORT_RANGE_CASES,
            GET_SWITCH_HOSTS_CASES,
            PROFILE_LOADING_CASES,
            PROFILE_TO_CONFIG_CASES,
            SWITCH_TARGET_RESOLUTION_CASES,
            TestCiscoDeployerInterface,
            TestCiscoDeployerInterfaceMatrix,
            TestCiscoParseArpTable,
            TestCiscoParseArpTableMatrix,
            TestCiscoParseCdpDetail,
            TestCiscoParseCdpDetailMatrix,
            TestCiscoParseInterfacesStatus,
            TestCiscoParseInterfacesStatusMatrix,
            TestCiscoParseMacTable,
            TestCiscoParseMacTableMatrix,
            TestCiscoParsePowerInline,
            TestCiscoParsePowerInlineMatrix,
            TestCiscoParseShowVersion,
            TestCiscoParseShowVersionMatrix,
            TestCiscoParseVlanBrief,
            TestCiscoParseVlanBriefMatrix,
            TestCiscoTransportContract,
            TestCiscoTransportContractMatrix,
            TestExpandPortRange,
            TestExpandPortRangeMatrix,
            TestGetSwitchHosts,
            TestGetSwitchHostsMatrix,
            TestProfileLoading,
            TestProfileLoadingMatrix,
            TestProfileToConfigLines,
            TestProfileToConfigLinesMatrix,
            TestTargetResolution,
            TestTargetResolutionMatrix,
        )
        from tests.test_vm_api import VM_API_TRUST_CASES, TestVmApiTrust, TestVmApiTrustMatrix

        probes = (
            (
                TestCheckSessionRole,
                TestCheckSessionRoleMatrix,
                "test_session_role_matrix",
                SESSION_ROLE_CASES[0],
            ),
            (
                TestParseQuery,
                TestParseQueryMatrix,
                "test_parse_query_matrix",
                PARSE_QUERY_CASES[0],
            ),
            (
                TestBgProbeHealth,
                TestBgProbeHealthMatrix,
                "test_bg_probe_health_matrix",
                BG_PROBE_HEALTH_CASES[0],
            ),
            (
                TestSSEEventBus,
                TestSSEEventBusMatrix,
                "test_sse_event_bus_matrix",
                SSE_EVENT_BUS_CASES[0],
            ),
            (
                DashboardEventServiceTests,
                TestDashboardEventServiceMatrix,
                "test_dashboard_event_service_matrix",
                DASHBOARD_EVENT_SERVICE_CASES[0],
            ),
            (
                TestMetricsDbLifecycle,
                TestMetricsDbLifecycleMatrix,
                "test_metrics_db_lifecycle_matrix",
                METRICS_DB_LIFECYCLE_CASES[0],
            ),
            (
                TestSessionExpiry,
                TestSessionExpiryMatrix,
                "test_session_expiry_matrix",
                SESSION_EXPIRY_CASES[0],
            ),
            (
                TestRequireRole,
                TestRequireRoleMatrix,
                "test_require_role_matrix",
                REQUIRE_ROLE_CASES[0],
            ),
            (
                TestMalformedToml,
                TestMalformedTomlMatrix,
                "test_malformed_toml_matrix",
                MALFORMED_TOML_CASES[0],
            ),
            (
                TestHostsConf,
                TestHostsConfMatrix,
                "test_hosts_conf_matrix",
                HOSTS_CONF_CASES[0],
            ),
            (
                TestConfigMissingFields,
                TestConfigMissingFieldsMatrix,
                "test_config_missing_fields_matrix",
                CONFIG_MISSING_FIELDS_CASES[0],
            ),
            (
                TestSSHResultEdgeCases,
                TestSSHResultEdgeCasesMatrix,
                "test_ssh_result_edge_cases_matrix",
                SSH_RESULT_EDGE_CASES[0],
            ),
            (
                TestValidateBoundaryTables,
                TestValidateBoundaryTablesMatrix,
                "test_validate_boundary_tables_matrix",
                VALIDATE_BOUNDARY_CASES[0],
            ),
            (
                TestPVEApiEdgeCases,
                TestPVEApiEdgeCasesMatrix,
                "test_pve_api_edge_cases_matrix",
                PVE_API_EDGE_CASES[0],
            ),
            (
                TestFleetZeroHosts,
                TestFleetZeroHostsMatrix,
                "test_fleet_zero_hosts_matrix",
                FLEET_ZERO_HOSTS_CASES[0],
            ),
            (
                TestConfigCorruption,
                TestConfigCorruptionMatrix,
                "test_config_corruption_matrix",
                CONFIG_CORRUPTION_CASES[0],
            ),
            (
                TestValidateExtended,
                TestValidateExtendedMatrix,
                "test_validate_extended_matrix",
                VALIDATE_EXTENDED_CASES[0],
            ),
            (
                TestDupLabelCallers,
                TestDupLabelCallersMatrix,
                "test_dup_label_callers_matrix",
                DUP_LABEL_CALLER_CASES[0],
            ),
            (
                TestSnapshotIO, TestSnapshotIOMatrix,
                "test_snapshot_io_matrix", SNAPSHOT_IO_CASES[0],
            ),
            (
                TestParsing, TestCapacityParsingMatrix,
                "test_capacity_parsing_matrix", CAPACITY_PARSING_CASES[0],
            ),
            (
                TestLinearRegression, TestLinearRegressionMatrix,
                "test_linear_regression_matrix", LINEAR_REGRESSION_CASES[0],
            ),
            (
                TestProjections, TestCapacityProjectionsMatrix,
                "test_capacity_projections_matrix", CAPACITY_PROJECTION_CASES[0],
            ),
            (
                TestShouldSnapshot, TestShouldSnapshotMatrix,
                "test_should_snapshot_matrix", SHOULD_SNAPSHOT_CASES[0],
            ),
            (
                chaos_cases.TestValidation,
                chaos_cases.TestChaosValidationMatrix,
                "test_chaos_validation_matrix",
                chaos_cases.CHAOS_VALIDATION_CASES[0],
            ),
            (
                chaos_cases.TestBuildCommands,
                chaos_cases.TestChaosBuildCommandsMatrix,
                "test_chaos_build_commands_matrix",
                chaos_cases.CHAOS_BUILD_COMMAND_CASES[0],
            ),
            (
                chaos_cases.TestSafetyGates,
                chaos_cases.TestChaosSafetyGatesMatrix,
                "test_chaos_safety_gates_matrix",
                chaos_cases.CHAOS_SAFETY_CASES[0],
            ),
            (
                chaos_cases.TestLogging,
                chaos_cases.TestChaosLoggingMatrix,
                "test_chaos_logging_matrix",
                chaos_cases.CHAOS_LOGGING_CASES[0],
            ),
            (
                chaos_cases.TestRunExperiment,
                chaos_cases.TestChaosRunExperimentMatrix,
                "test_chaos_run_experiment_matrix",
                chaos_cases.CHAOS_RUN_CASES[0],
            ),
            (
                chaos_cases.TestSerialization,
                chaos_cases.TestChaosSerializationMatrix,
                "test_chaos_serialization_matrix",
                chaos_cases.CHAOS_SERIALIZATION_CASES[0],
            ),
            (
                federation_cases.TestSiteIO,
                federation_cases.TestFederationSiteIOMatrix,
                "test_federation_site_io_matrix",
                federation_cases.FEDERATION_SITE_IO_CASES[0],
            ),
            (
                federation_cases.TestRegistration,
                federation_cases.TestFederationRegistrationMatrix,
                "test_federation_registration_matrix",
                federation_cases.FEDERATION_REGISTRATION_CASES[0],
            ),
            (
                federation_cases.TestUnregistration,
                federation_cases.TestFederationUnregistrationMatrix,
                "test_federation_unregistration_matrix",
                federation_cases.FEDERATION_UNREGISTRATION_CASES[0],
            ),
            (
                federation_cases.TestHMACAuth,
                federation_cases.TestFederationHMACMatrix,
                "test_federation_hmac_matrix",
                federation_cases.FEDERATION_HMAC_CASES[0],
            ),
            (
                federation_cases.TestPolling,
                federation_cases.TestFederationPollingMatrix,
                "test_federation_polling_matrix",
                federation_cases.FEDERATION_POLLING_CASES[0],
            ),
            (
                federation_cases.TestShouldPoll,
                federation_cases.TestFederationShouldPollMatrix,
                "test_federation_should_poll_matrix",
                federation_cases.FEDERATION_SHOULD_POLL_CASES[0],
            ),
            (
                federation_cases.TestSerialization,
                federation_cases.TestFederationSerializationMatrix,
                "test_federation_serialization_matrix",
                federation_cases.FEDERATION_SERIALIZATION_CASES[0],
            ),
            (
                cost_cases.TestCostConfig, cost_cases.TestCostConfigMatrix,
                "test_cost_config_matrix", cost_cases.COST_CONFIG_CASES[0],
            ),
            (
                cost_cases.TestIdracParsing, cost_cases.TestIdracPowerParsingMatrix,
                "test_idrac_power_parsing_matrix", cost_cases.IDRAC_POWER_PARSING_CASES[0],
            ),
            (
                cost_cases.TestRamParsing, cost_cases.TestRamParsingMatrix,
                "test_ram_parsing_matrix", cost_cases.RAM_PARSING_CASES[0],
            ),
            (
                cost_cases.TestWattEstimation, cost_cases.TestWattEstimationMatrix,
                "test_watt_estimation_matrix", cost_cases.WATT_ESTIMATION_CASES[0],
            ),
            (
                cost_cases.TestSerialization, cost_cases.TestCostSerializationMatrix,
                "test_cost_serialization_matrix", cost_cases.COST_SERIALIZATION_CASES[0],
            ),
            (
                playbook_cases.TestDataTypes, playbook_cases.TestPlaybookDataTypesMatrix,
                "test_playbook_data_types_matrix", playbook_cases.PLAYBOOK_DATA_TYPE_CASES[0],
            ),
            (
                playbook_cases.TestPlaybookLoading, playbook_cases.TestPlaybookLoadingMatrix,
                "test_playbook_loading_matrix", playbook_cases.PLAYBOOK_LOADING_CASES[0],
            ),
            (
                playbook_cases.TestSerialization, playbook_cases.TestPlaybookSerializationMatrix,
                "test_playbook_serialization_matrix", playbook_cases.PLAYBOOK_SERIALIZATION_CASES[0],
            ),
            (
                playbook_cases.TestRunStep, playbook_cases.TestPlaybookRunStepMatrix,
                "test_playbook_run_step_matrix", playbook_cases.PLAYBOOK_RUN_STEP_CASES[0],
            ),
            (
                rule_cases.TestRuleDataTypes, rule_cases.TestRuleDataTypesMatrix,
                "test_rule_data_types_matrix", rule_cases.RULE_DATA_TYPE_CASES[0],
            ),
            (
                rule_cases.TestRuleLoading, rule_cases.TestRuleLoadingMatrix,
                "test_rule_loading_matrix", rule_cases.RULE_LOADING_CASES[0],
            ),
            (
                rule_cases.TestRuleState, rule_cases.TestRuleStateMatrix,
                "test_rule_state_matrix", rule_cases.RULE_STATE_CASES[0],
            ),
            (
                rule_cases.TestAlertHistory, rule_cases.TestAlertHistoryMatrix,
                "test_alert_history_matrix", rule_cases.ALERT_HISTORY_CASES[0],
            ),
            (
                rule_cases.TestTargetMatching, rule_cases.TestTargetMatchingMatrix,
                "test_target_matching_matrix", rule_cases.TARGET_MATCHING_CASES[0],
            ),
            (
                rule_cases.TestParsing, rule_cases.TestRuleParsingMatrix,
                "test_rule_parsing_matrix", rule_cases.RULE_PARSING_CASES[0],
            ),
            (
                jarvis_edge_cases.TestCrossModuleRulesEval,
                jarvis_edge_cases.TestEdgeRuleEvaluationMatrix,
                "test_edge_rule_evaluation_matrix", jarvis_edge_cases.EDGE_RULE_EVAL_CASES[0],
            ),
            (
                jarvis_edge_cases.TestCrossModuleCapacityCost,
                jarvis_edge_cases.TestEdgeCapacityCostMatrix,
                "test_edge_capacity_cost_matrix", jarvis_edge_cases.EDGE_CAPACITY_COST_CASES[0],
            ),
            (
                jarvis_edge_cases.TestEmptyNullInputs,
                jarvis_edge_cases.TestEdgeEmptyNullMatrix,
                "test_edge_empty_null_matrix", jarvis_edge_cases.EDGE_EMPTY_NULL_CASES[0],
            ),
            (
                jarvis_edge_cases.TestHugeInputs,
                jarvis_edge_cases.TestEdgeHugeInputsMatrix,
                "test_edge_huge_inputs_matrix", jarvis_edge_cases.EDGE_HUGE_INPUT_CASES[0],
            ),
            (
                jarvis_edge_cases.TestUnicodeHandling,
                jarvis_edge_cases.TestEdgeUnicodeMatrix,
                "test_edge_unicode_matrix", jarvis_edge_cases.EDGE_UNICODE_CASES[0],
            ),
            (
                jarvis_edge_cases.TestFileCorruptionRecovery,
                jarvis_edge_cases.TestEdgeCorruptionRecoveryMatrix,
                "test_edge_corruption_recovery_matrix", jarvis_edge_cases.EDGE_CORRUPTION_CASES[0],
            ),
            (
                jarvis_edge_cases.TestMathEdgeCases,
                jarvis_edge_cases.TestEdgeMathMatrix,
                "test_edge_math_matrix", jarvis_edge_cases.EDGE_MATH_CASES[0],
            ),
            (
                jarvis_edge_cases.TestHMACBoundary,
                jarvis_edge_cases.TestEdgeHMACMatrix,
                "test_edge_hmac_matrix", jarvis_edge_cases.EDGE_HMAC_CASES[0],
            ),
            (
                jarvis_edge_cases.TestChaosSafetyBoundary,
                jarvis_edge_cases.TestEdgeChaosSafetyMatrix,
                "test_edge_chaos_safety_matrix", jarvis_edge_cases.EDGE_CHAOS_SAFETY_CASES[0],
            ),
            (
                overnight_tier1_cases.TestTier1ConfigLoading,
                overnight_tier1_cases.TestTier1ConfigLoadingMatrix,
                "test_tier1_config_loading_matrix", overnight_tier1_cases.TIER1_CONFIG_LOADING_CASES[0],
            ),
            (
                overnight_tier1_cases.TestTier1ProfileA,
                overnight_tier1_cases.TestTier1ProfileAMatrix,
                "test_tier1_profile_a_matrix", overnight_tier1_cases.TIER1_PROFILE_A_CASES[0],
            ),
            (
                overnight_tier1_cases.TestTier1ProfileB,
                overnight_tier1_cases.TestTier1ProfileBMatrix,
                "test_tier1_profile_b_matrix", overnight_tier1_cases.TIER1_PROFILE_B_CASES[0],
            ),
            (
                overnight_tier1_cases.TestTier1ProfileD,
                overnight_tier1_cases.TestTier1ProfileDMatrix,
                "test_tier1_profile_d_matrix", overnight_tier1_cases.TIER1_PROFILE_D_CASES[0],
            ),
            (
                overnight_tier1_cases.TestTier1EdgeCases,
                overnight_tier1_cases.TestTier1EdgeCasesMatrix,
                "test_tier1_edge_cases_matrix", overnight_tier1_cases.TIER1_EDGE_CASES[0],
            ),
            (
                overnight_tier1_cases.TestPortabilityConfig,
                overnight_tier1_cases.TestPortabilityConfigMatrix,
                "test_portability_config_matrix", overnight_tier1_cases.PORTABILITY_CONFIG_CASES[0],
            ),
            (
                overnight_tier3_6_cases.TestTier3SingleNode,
                overnight_tier3_6_cases.TestTier3SingleNodeMatrix,
                "test_tier3_single_node_matrix", overnight_tier3_6_cases.TIER3_SINGLE_NODE_CASES[0],
            ),
            (
                overnight_tier3_6_cases.TestTier3ProfileB,
                overnight_tier3_6_cases.TestTier3ProfileBMatrix,
                "test_tier3_profile_b_matrix", overnight_tier3_6_cases.TIER3_PROFILE_B_CASES[0],
            ),
            (
                overnight_tier3_6_cases.TestTier3CLIDispatch,
                overnight_tier3_6_cases.TestTier3CLIDispatchMatrix,
                "test_tier3_cli_dispatch_matrix", overnight_tier3_6_cases.TIER3_CLI_DISPATCH_CASES[0],
            ),
            (
                overnight_tier3_6_cases.TestTier6VMNetworkEdgeCases,
                overnight_tier3_6_cases.TestTier6VMNetworkMatrix,
                "test_tier6_vm_network_matrix", overnight_tier3_6_cases.TIER6_VM_NETWORK_CASES[0],
            ),
            (
                overnight_tier3_6_cases.TestTier6StorageFallback,
                overnight_tier3_6_cases.TestTier6StorageMatrix,
                "test_tier6_storage_matrix", overnight_tier3_6_cases.TIER6_STORAGE_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveByLabel,
                overnight_extra_cases.TestResolveByLabelMatrix,
                "test_resolve_by_label_matrix", overnight_extra_cases.RESOLVE_BY_LABEL_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveByIP,
                overnight_extra_cases.TestResolveByIPMatrix,
                "test_resolve_by_ip_matrix", overnight_extra_cases.RESOLVE_BY_IP_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveByTarget,
                overnight_extra_cases.TestResolveByTargetMatrix,
                "test_resolve_by_target_matrix", overnight_extra_cases.RESOLVE_BY_TARGET_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveByGroup,
                overnight_extra_cases.TestResolveByGroupMatrix,
                "test_resolve_by_group_matrix", overnight_extra_cases.RESOLVE_BY_GROUP_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveByType,
                overnight_extra_cases.TestResolveByTypeMatrix,
                "test_resolve_by_type_matrix", overnight_extra_cases.RESOLVE_BY_TYPE_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveAllGroups,
                overnight_extra_cases.TestResolveAllGroupsMatrix,
                "test_resolve_all_groups_matrix", overnight_extra_cases.RESOLVE_ALL_GROUPS_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveAllTypes,
                overnight_extra_cases.TestResolveAllTypesMatrix,
                "test_resolve_all_types_matrix", overnight_extra_cases.RESOLVE_ALL_TYPES_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveByScope,
                overnight_extra_cases.TestResolveByScopeMatrix,
                "test_resolve_by_scope_matrix", overnight_extra_cases.RESOLVE_BY_SCOPE_CASES[0],
            ),
            (
                overnight_extra_cases.TestResolveByLabels,
                overnight_extra_cases.TestResolveByLabelsMatrix,
                "test_resolve_by_labels_matrix", overnight_extra_cases.RESOLVE_BY_LABELS_CASES[0],
            ),
            (
                overnight_extra_cases.TestValidateExtras,
                overnight_extra_cases.TestValidateExtrasMatrix,
                "test_validate_extras_matrix", overnight_extra_cases.VALIDATE_EXTRAS_CASES[0],
            ),
            (
                overnight_extra_cases.TestContainerResolve,
                overnight_extra_cases.TestContainerResolveMatrix,
                "test_container_resolve_matrix", overnight_extra_cases.CONTAINER_RESOLVE_CASES[0],
            ),
            (
                TestCiscoParseShowVersion, TestCiscoParseShowVersionMatrix,
                "test_cisco_show_version_matrix", CISCO_SHOW_VERSION_CASES[0],
            ),
            (
                TestCiscoParseInterfacesStatus, TestCiscoParseInterfacesStatusMatrix,
                "test_cisco_interfaces_status_matrix", CISCO_INTERFACES_STATUS_CASES[0],
            ),
            (
                TestCiscoParseVlanBrief, TestCiscoParseVlanBriefMatrix,
                "test_cisco_vlan_brief_matrix", CISCO_VLAN_BRIEF_CASES[0],
            ),
            (
                TestCiscoParseMacTable, TestCiscoParseMacTableMatrix,
                "test_cisco_mac_table_matrix", CISCO_MAC_TABLE_CASES[0],
            ),
            (
                TestCiscoParseArpTable, TestCiscoParseArpTableMatrix,
                "test_cisco_arp_table_matrix", CISCO_ARP_TABLE_CASES[0],
            ),
            (
                TestCiscoParseCdpDetail, TestCiscoParseCdpDetailMatrix,
                "test_cisco_cdp_detail_matrix", CISCO_CDP_DETAIL_CASES[0],
            ),
            (
                TestCiscoTransportContract, TestCiscoTransportContractMatrix,
                "test_cisco_transport_matrix", CISCO_TRANSPORT_CASES[0],
            ),
            (
                TestTargetResolution, TestTargetResolutionMatrix,
                "test_switch_target_resolution_matrix", SWITCH_TARGET_RESOLUTION_CASES[0],
            ),
            (
                TestGetSwitchHosts, TestGetSwitchHostsMatrix,
                "test_get_switch_hosts_matrix", GET_SWITCH_HOSTS_CASES[0],
            ),
            (
                TestCiscoDeployerInterface, TestCiscoDeployerInterfaceMatrix,
                "test_cisco_deployer_interface_matrix", CISCO_DEPLOYER_INTERFACE_CASES[0],
            ),
            (
                TestCiscoParsePowerInline, TestCiscoParsePowerInlineMatrix,
                "test_cisco_power_inline_matrix", CISCO_POWER_INLINE_CASES[0],
            ),
            (
                TestProfileToConfigLines, TestProfileToConfigLinesMatrix,
                "test_profile_to_config_matrix", PROFILE_TO_CONFIG_CASES[0],
            ),
            (
                TestExpandPortRange, TestExpandPortRangeMatrix,
                "test_expand_port_range_matrix", EXPAND_PORT_RANGE_CASES[0],
            ),
            (
                TestProfileLoading, TestProfileLoadingMatrix,
                "test_profile_loading_matrix", PROFILE_LOADING_CASES[0],
            ),
            (
                TestRunWithInput,
                TestRunWithInputMatrix,
                "test_run_with_input_matrix",
                RUN_WITH_INPUT_CASES[0],
            ),
            (
                TestInitResetLocalState,
                TestInitResetLocalStateMatrix,
                "test_init_reset_local_state_matrix",
                INIT_RESET_LOCAL_STATE_CASES[0],
            ),
            (
                TestSSHWithPass,
                TestSSHWithPassMatrix,
                "test_ssh_with_pass_matrix",
                SSH_WITH_PASS_CASES[0],
            ),
            (
                TestIdracParsing,
                TestIdracParsingMatrix,
                "test_idrac_parsing_matrix",
                IDRAC_PARSING_CASES[0],
            ),
            (
                TestHeadlessFleetDeployTruth,
                TestHeadlessFleetDeployTruthMatrix,
                "test_headless_fleet_deploy_matrix",
                HEADLESS_FLEET_DEPLOY_CASES[0],
            ),
            (
                TestPhaseConfigure,
                TestPhaseConfigureMatrix,
                "test_phase_configure_matrix",
                PHASE_CONFIGURE_CASES[0],
            ),
            (
                TestPhaseDiscoverScopedHosts,
                TestPhaseDiscoverScopedHostsMatrix,
                "test_phase_discover_scoped_hosts_matrix",
                PHASE_DISCOVER_SCOPED_HOSTS_CASES[0],
            ),
            (
                TestEvaluation,
                TestEvaluationMatrix,
                "test_rule_evaluation_matrix",
                RULE_EVALUATION_CASES[0],
            ),
            (
                TestPlanDiff,
                TestPlanDiffMatrix,
                "test_plan_diff_matrix",
                PLAN_DIFF_CASES[0],
            ),
            (
                TestComputeCosts,
                TestComputeCostsMatrix,
                "test_compute_costs_matrix",
                COMPUTE_COST_CASES[0],
            ),
            (
                TestRecommendMigrations,
                TestRecommendMigrationsMatrix,
                "test_capacity_recommendation_matrix",
                CAPACITY_RECOMMENDATION_CASES[0],
            ),
            (
                TestFleetInventoryContracts,
                TestFleetInventoryContractsMatrix,
                "test_fleet_inventory_contract_matrix",
                FLEET_INVENTORY_CONTRACT_CASES[0],
            ),
            (
                TestUpdateFbToml,
                TestUpdateFbTomlMatrix,
                "test_update_fb_toml_matrix",
                FB_TOML_CASES[0],
            ),
            (
                TestRuntimeDeviceCredentials,
                TestRuntimeDeviceCredentialsMatrix,
                "test_runtime_device_credentials_matrix",
                RUNTIME_DEVICE_CREDENTIAL_CASES[0],
            ),
            (
                TestVaultParsing,
                TestVaultParsingMatrix,
                "test_vault_parsing_matrix",
                VAULT_PARSING_CASES[0],
            ),
            (
                TestSSHTransportEdgeCases,
                TestSSHTransportEdgeCasesMatrix,
                "test_ssh_transport_edge_cases_matrix",
                SSH_TRANSPORT_EDGE_CASES[0],
            ),
            (
                TestValidation,
                TestValidationMatrix,
                "test_validation_matrix",
                VALIDATION_CASES[0],
            ),
            (
                TestVmApiTrust,
                TestVmApiTrustMatrix,
                "test_vm_api_trust_matrix",
                VM_API_TRUST_CASES[0],
            ),
            (
                TestFleetProbeNoiseContract,
                TestFleetOperatorTruthMatrix,
                "test_fleet_operator_truth_matrix",
                FLEET_OPERATOR_TRUTH_CASES[0],
            ),
            (
                TestHostsSync,
                TestHostsSyncMatrix,
                "test_hosts_sync_matrix",
                HOSTS_SYNC_CASES[0],
            ),
            (
                TestCertLifecyclePlan,
                TestCertLifecyclePlanMatrix,
                "test_cert_lifecycle_plan_matrix",
                CERT_LIFECYCLE_PLAN_CASES[0],
            ),
            (
                IdracSessionServiceTests,
                TestIdracSessionServiceMatrix,
                "test_idrac_session_service_matrix",
                IDRAC_SESSION_SERVICE_CASES[0],
            ),
            (
                TestSetupHealthSummary,
                TestSetupHealthSummaryMatrix,
                "test_setup_health_summary_matrix",
                SETUP_HEALTH_SUMMARY_CASES[0],
            ),
            (
                TestHealthTool,
                TestHealthToolMatrix,
                "test_health_tool_matrix",
                TEST_HEALTH_TOOL_CASES[0],
            ),
            (
                TestAlertModule,
                TestAlertModuleMatrix,
                "test_alert_module_matrix",
                ALERT_MODULE_CASES[0],
            ),
            (
                TestDoctorChecks,
                TestDoctorChecksMatrix,
                "test_doctor_checks_matrix",
                DOCTOR_CHECK_CASES[0],
            ),
            (
                TestFullAuthLifecycle,
                TestFullAuthLifecycleMatrix,
                "test_full_auth_lifecycle_matrix",
                AUTH_LIFECYCLE_CASES[0],
            ),
            (
                TestPveUninstall,
                TestPveUninstallMatrix,
                "test_pve_uninstall_matrix",
                PVE_UNINSTALL_CASES[0],
            ),
            (
                TestProjectFiles,
                TestProjectFilesMatrix,
                "test_project_files_matrix",
                PROJECT_FILE_CASES[0],
            ),
            (
                TestRouteTable,
                TestRouteTableMatrix,
                "test_route_table_matrix",
                ROUTE_TABLE_CASES[0],
            ),
        )
        temp_root = Path(tempfile.gettempdir())
        for original, owner, owner_method, victim in probes:
            with self.subTest(owner=owner.__name__, victim=victim):
                before = set(temp_root.glob("freq-test-sync-*"))
                result = unittest.TestResult()
                marker = f"causal:{victim}"
                with (
                    patch.object(original, victim, side_effect=AssertionError(marker)),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    owner(owner_method).run(result)
                self.assertEqual(len(result.failures), 1)
                self.assertEqual(result.errors, [])
                self.assertIn(marker, result.failures[0][1])
                self.assertEqual(set(temp_root.glob("freq-test-sync-*")), before)
