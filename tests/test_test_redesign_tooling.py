"""Behavior tests for the test-redesign baseline and retirement tooling."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import surface_inventory, test_health
from tests.case_matrix import run_case_matrix

REPO = Path(__file__).resolve().parents[1]


def _require_role_through_unknown_helper(handler):
    return bool(handler)


def _handler_with_unresolved_role_guard(handler):
    """POST /api/example -- guarded through unresolved local helper."""
    if not _require_role_through_unknown_helper(handler):
        return None
    return handler


def subprocess_result(stdout: str):
    return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()


def passing_metrics():
    contract = test_health.load_public_contract(REPO / test_health.PUBLIC_MANIFEST)
    modules = [
        {
            "path": row["path"],
            "retained_public": row["classification"] in {"RETAINED", "UNKNOWN_KEEP"},
            "critical": row["critical"],
            "coverage_status": "MEASURED",
            "covered_lines": 7,
            "num_statements": 10,
            "covered_branches": 6,
            "num_branches": 10,
        }
        for row in contract
    ]
    metrics = {
        "source_sha": test_health.BASELINE_SOURCE_SHA,
        "default_cases": 2700,
        "covered_lines": 37000,
        "num_statements": 52000,
        "covered_branches": 11000,
        "num_branches": 18000,
        "skipped": 0,
        "warnings": 0,
        "browser": {
            "definitions": len(test_health.BROWSER_TERMINAL_OWNERS),
            "node_ids_sha256": "a" * 64,
            "owner_ids": sorted(test_health.BROWSER_TERMINAL_OWNERS),
            "owner_ids_sha256": test_health._sha256_lines(
                sorted(test_health.BROWSER_TERMINAL_OWNERS)
            ),
            "file_counts": test_health.BROWSER_TERMINAL_FILE_COUNTS,
        },
        "runtime": {
            "schema_version": 1,
            "source_sha": test_health.BASELINE_SOURCE_SHA,
            "host": test_health.CANONICAL_RUNTIME_HOST,
            "canonical": True,
            "runs": [
                {"seconds": 260.0, "clean": True},
                {"seconds": 270.0, "clean": True},
                {"seconds": 300.0, "clean": True},
            ],
        },
        "pollution": {
            "source_sha": test_health.BASELINE_SOURCE_SHA,
            "host": test_health.CANONICAL_RUNTIME_HOST,
            "canonical": True,
            "results": {
                name: {"measured": True, "clean": True, "before": "a", "after": "a"}
                for name in test_health.POLLUTION_CATEGORIES
            }
        },
        "coverage_identity": test_health._frozen_identity(),
        "baseline_coverage_identity": test_health._frozen_identity(),
        "baseline_denominators": test_health.BASELINE_DENOMINATORS,
        "module_contract": contract,
        "module_contract_sha256": test_health.module_contract_sha256(contract),
        "module_coverage": modules,
    }
    coverage = test_health.CoverageMetrics(37000, 52000, 11000, 18000).as_dict()
    metrics.update(coverage)
    totals = {
        key: metrics[key]
        for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
    }
    metrics["coverage_provenance"] = {
        "source_sha": test_health.BASELINE_SOURCE_SHA,
        "canonical": True,
        "clean": True,
        "artifact_sha256": "artifact",
        "totals_sha256": test_health._canonical_sha256(totals),
    }
    return metrics


def passing_delivery_metrics():
    metrics = passing_metrics()
    _, contract = test_health.authenticated_effective_module_contract(REPO)
    source_sha = "e" * 40
    metrics.update(
        {
            "source_sha": source_sha,
            "module_contract_mode": "delivery",
            "reviewed_module_additions_sha256": (
                test_health.FROZEN_REVIEWED_MODULE_ADDITIONS_SHA256
            ),
            "effective_module_contract_sha256": (
                test_health.FROZEN_EFFECTIVE_MODULE_CONTRACT_SHA256
            ),
            "module_contract": contract,
            "module_contract_sha256": test_health.module_contract_sha256(contract),
            "module_coverage": [
                {
                    "path": row["path"],
                    "retained_public": row["classification"] in {"RETAINED", "UNKNOWN_KEEP"},
                    "critical": row["critical"],
                    "coverage_status": "MEASURED",
                    "covered_lines": 7,
                    "num_statements": 10,
                    "covered_branches": 6,
                    "num_branches": 10,
                }
                for row in contract
            ],
        }
    )
    metrics["coverage_provenance"]["source_sha"] = source_sha
    metrics["runtime"]["source_sha"] = source_sha
    metrics["pollution"]["source_sha"] = source_sha
    return metrics


class TestHealthTool(unittest.TestCase):
    def _case_coverage_json_uses_raw_statement_and_branch_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coverage.json"
            path.write_text(
                json.dumps(
                    {
                        "totals": {
                            "covered_lines": 70,
                            "num_statements": 100,
                            "covered_branches": 60,
                            "num_branches": 100,
                            "percent_covered": 67.0,
                        }
                    }
                )
            )
            metrics = test_health.load_coverage_metrics(path)

        self.assertEqual(metrics.covered_lines, 70)
        self.assertEqual(metrics.covered_branches, 60)
        self.assertEqual(metrics.statement_ratio, 0.70)
        self.assertEqual(metrics.branch_ratio, 0.60)
        self.assertEqual(metrics.combined_ratio, 0.65)

    def _case_terminal_gate_passes_only_the_complete_contract(self):
        metrics = passing_metrics()
        self.assertEqual(test_health.evaluate(metrics), [])

    def _case_delivery_gate_uses_authenticated_effective_contract_and_row_floors(self):
        metrics = passing_delivery_metrics()
        self.assertEqual(test_health.evaluate(metrics), [])

        fleet = next(
            row for row in metrics["module_coverage"]
            if row["path"] == "freq/services/fleet_status.py"
        )
        fleet["covered_branches"] = 3
        self.assertIn(
            "module branch floor missed: freq/services/fleet_status.py",
            test_health.evaluate(metrics),
        )

        metrics = passing_delivery_metrics()
        fleet = next(
            row for row in metrics["module_coverage"]
            if row["path"] == "freq/services/fleet_status.py"
        )
        fleet.update(
            coverage_status="OMITTED_OR_MISSING",
            covered_lines=None,
            num_statements=None,
            covered_branches=None,
            num_branches=None,
        )
        self.assertIn(
            "module coverage unavailable: freq/services/fleet_status.py",
            test_health.evaluate(metrics),
        )

    def _case_baseline_metrics_do_not_require_future_terminal_browser_fields(self):
        metrics = passing_metrics()
        metrics.pop("browser")
        self.assertEqual(test_health.evaluate(metrics), [])

    def _case_contract_mode_and_delivery_authentication_fail_closed(self):
        metrics = passing_delivery_metrics()
        metrics["module_contract_mode"] = "future"
        self.assertIn("module contract mode is unknown", test_health.evaluate(metrics))

        metrics = passing_delivery_metrics()
        del metrics["module_contract_mode"]
        self.assertIn("source SHA does not match frozen baseline", test_health.evaluate(metrics))

        metrics = passing_delivery_metrics()
        metrics["reviewed_module_additions_sha256"] = "tampered"
        self.assertIn(
            "delivery module contract authentication missing or modified",
            test_health.evaluate(metrics),
        )
        self.assertIn(
            "delivery module contract authentication missing or modified",
            test_health.evaluate(metrics, delivery=False),
        )

        metrics = passing_metrics()
        metrics["module_contract_mode"] = "delivery"
        self.assertIn(
            "delivery source SHA must differ from frozen baseline",
            test_health.evaluate(metrics),
        )

        metrics = passing_metrics()
        metrics["module_contract_mode"] = "baseline"
        self.assertEqual(test_health.evaluate(metrics), [])

    def _case_terminal_gate_reports_count_coverage_hygiene_and_runtime_failures(self):
        metrics = passing_metrics()
        metrics.update(
            {
                "default_cases": 3001,
                "covered_lines": 5200,
                "covered_branches": 1800,
                "skipped": 1,
                "warnings": 1,
            }
        )
        metrics.update(test_health.CoverageMetrics(5200, 52000, 1800, 18000).as_dict())
        totals = {
            key: metrics[key]
            for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
        }
        metrics["coverage_provenance"]["totals_sha256"] = test_health._canonical_sha256(totals)
        metrics["runtime"]["runs"] = [
            {"seconds": 290.0, "clean": True},
            {"seconds": 301.0, "clean": True},
            {"seconds": 331.0, "clean": True},
        ]
        failures = test_health.evaluate(metrics)
        self.assertIn("hard case ceiling exceeded", failures)
        self.assertIn("raw branch ratio missed", failures)
        self.assertIn("statement ratio missed", failures)
        self.assertIn("default suite contains skips", failures)
        self.assertIn("default suite contains warnings", failures)
        self.assertIn("runtime hard median exceeded", failures)
        self.assertIn("runtime maximum exceeded", failures)

    def _case_terminal_gate_rejects_browser_count_owner_file_and_hash_drift(self):
        metrics = passing_delivery_metrics()
        metrics["browser"]["definitions"] = len(test_health.BROWSER_TERMINAL_OWNERS) + 1
        self.assertIn("browser terminal definition count is not exact", test_health.evaluate(metrics))

        metrics = passing_delivery_metrics()
        metrics["browser"]["owner_ids"][-1] = "S02"
        metrics["browser"]["owner_ids_sha256"] = test_health._sha256_lines(
            metrics["browser"]["owner_ids"]
        )
        self.assertIn(
            "browser terminal owner inventory is missing, duplicated, or modified",
            test_health.evaluate(metrics),
        )

        metrics = passing_delivery_metrics()
        metrics["browser"]["file_counts"] = {
            **metrics["browser"]["file_counts"],
            "live-safe.spec.js": 5,
        }
        self.assertIn("browser terminal file distribution is modified", test_health.evaluate(metrics))

        metrics = passing_delivery_metrics()
        metrics["browser"]["node_ids_sha256"] = "not-a-sha"
        self.assertIn("browser terminal node inventory hash is missing or invalid", test_health.evaluate(metrics))

    def _case_manifest_metrics_preserves_browser_delivery_contract(self):
        manifest = {
            "coverage": {},
            "python": {},
            "browser": passing_metrics()["browser"],
        }
        self.assertEqual(
            test_health._manifest_metrics(manifest)["browser"],
            manifest["browser"],
        )

    def _case_browser_terminal_contract_resolves_exact_owner_and_file_inventory(self):
        node_ids = []
        for index, (owner, (filename, marker)) in enumerate(
            test_health.BROWSER_TERMINAL_OWNERS.items(), start=1
        ):
            node_ids.append(f"[chromium] › {filename}:{index}:1 › suite › {marker} owns behavior")
        contract = test_health.browser_terminal_contract(node_ids)
        self.assertEqual(contract["owner_ids"], sorted(test_health.BROWSER_TERMINAL_OWNERS))
        self.assertEqual(contract["file_counts"], test_health.BROWSER_TERMINAL_FILE_COUNTS)

        with self.assertRaisesRegex(ValueError, "exactly one terminal owner"):
            test_health.browser_terminal_contract(
                ["[chromium] › live-safe.spec.js:1:1 › suite › unknown owner"]
            )

        with self.assertRaisesRegex(ValueError, "exactly one terminal owner"):
            test_health.browser_terminal_contract(
                [
                    "[chromium] › hermetic-dashboard.spec.js:1:1 "
                    "› H01 auth and security lifecycle › unrelated leaf"
                ]
            )

        moved = list(node_ids)
        moved[0] = moved[0].replace(
            "hermetic-dashboard.spec.js", "live-safe.spec.js", 1
        )
        with self.assertRaisesRegex(ValueError, "exactly one terminal owner"):
            test_health.browser_terminal_contract(moved)

        duplicated = list(node_ids)
        duplicated[-1] = duplicated[0].replace(":1:1", ":99:1", 1)
        with self.assertRaisesRegex(ValueError, "missing or duplicated"):
            test_health.browser_terminal_contract(duplicated)

    def _case_hard_only_mode_preserves_reserved_capacity_without_redefining_the_ceiling(self):
        metrics = passing_metrics()
        metrics["default_cases"] = 2900
        metrics["runtime"]["runs"] = [
            {"seconds": 280.0, "clean": True},
            {"seconds": 290.0, "clean": True},
            {"seconds": 300.0, "clean": True},
        ]
        self.assertEqual(test_health.evaluate(metrics, delivery=False), [])
        delivery_failures = test_health.evaluate(metrics, delivery=True)
        self.assertIn("default case delivery target exceeded", delivery_failures)
        self.assertIn("runtime delivery median exceeded", delivery_failures)

    def _case_node_manifest_hash_is_order_and_newline_sensitive(self):
        first = test_health._sha256_lines(["tests/a.py::test_a", "tests/b.py::test_b"])
        same = test_health._sha256_lines(["tests/a.py::test_a", "tests/b.py::test_b"])
        reversed_ids = test_health._sha256_lines(["tests/b.py::test_b", "tests/a.py::test_a"])
        self.assertEqual(first, same)
        self.assertNotEqual(first, reversed_ids)

    def _case_runtime_pollution_coverage_identity_and_module_inputs_fail_closed(self):
        for runs in ([], [250.0], [250.0, 260.0], [250.0, 260.0, 270.0, 280.0]):
            metrics = passing_metrics()
            metrics["runtime"]["runs"] = [{"seconds": value, "clean": True} for value in runs]
            self.assertTrue(any("exactly three clean VM999" in item for item in test_health.evaluate(metrics)))

        metrics = passing_metrics()
        metrics["pollution"] = {"results": {}}
        self.assertTrue(any("pollution gate" in item for item in test_health.evaluate(metrics)))
        metrics = passing_metrics()
        metrics["coverage_identity"] = {}
        self.assertTrue(any("coverage source/omit/config" in item for item in test_health.evaluate(metrics)))
        metrics = passing_metrics()
        metrics["coverage_identity"]["omit"] = []
        self.assertTrue(any("coverage source/omit/config" in item for item in test_health.evaluate(metrics)))
        metrics = passing_metrics()
        critical = next(row for row in metrics["module_coverage"] if row["critical"])
        critical["covered_branches"] = 5
        self.assertTrue(any(item.startswith("module branch floor missed:") for item in test_health.evaluate(metrics)))

    def _case_terminal_integrity_rejects_all_round_two_tampering_paths(self):
        metrics = passing_metrics()
        relaxed = dict(test_health.DELIVERY_TARGETS)
        relaxed["hard_case_ceiling"] = 9999
        self.assertIn("delivery target contract modified", test_health.evaluate(metrics, relaxed))

        metrics = passing_metrics()
        metrics["baseline_denominators"] = {"num_statements": 1, "num_branches": 1}
        self.assertIn("coverage denominator baseline modified", test_health.evaluate(metrics))

        metrics = passing_metrics()
        metrics["statement_ratio"] = 1.0
        self.assertIn("coverage ratios do not match absolute counts", test_health.evaluate(metrics))

        metrics = passing_metrics()
        metrics["coverage_identity"]["source"] = ["freq", "tests"]
        self.assertTrue(any("coverage source/omit/config" in item for item in test_health.evaluate(metrics)))

        metrics = passing_metrics()
        metrics["pollution"]["results"]["sockets"].update(after="b", clean=True)
        self.assertTrue(any("internally inconsistent" in item for item in test_health.evaluate(metrics)))

        metrics = passing_metrics()
        metrics["module_coverage"][0]["critical"] = not metrics["module_coverage"][0]["critical"]
        self.assertTrue(any("module classification modified" in item for item in test_health.evaluate(metrics)))

        metrics = passing_metrics()
        metrics["module_contract"][0]["classification"] = "RETIRED"
        metrics["module_contract_sha256"] = test_health.module_contract_sha256(metrics["module_contract"])
        self.assertIn("module contract hash missing or modified", test_health.evaluate(metrics))

    def _case_terminal_provenance_rejects_cross_sha_wrong_host_and_unclean_runs(self):
        metrics = passing_metrics()
        metrics["coverage_provenance"]["source_sha"] = "other"
        self.assertTrue(any("coverage provenance" in item for item in test_health.evaluate(metrics)))
        metrics = passing_metrics()
        metrics["runtime"]["host"] = "not-vm999"
        self.assertTrue(any("VM999" in item for item in test_health.evaluate(metrics)))
        metrics = passing_metrics()
        metrics["runtime"]["runs"][0]["clean"] = False
        self.assertTrue(any("VM999" in item for item in test_health.evaluate(metrics)))
        metrics = passing_metrics()
        metrics["pollution"]["source_sha"] = "other"
        self.assertTrue(any("pollution gate" in item for item in test_health.evaluate(metrics)))

    def _case_coverage_artifact_provenance_binds_sha_hash_totals_and_clean_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coverage_path = root / "coverage.json"
            coverage_path.write_text(
                json.dumps(
                    {
                        "totals": {
                            "covered_lines": 7,
                            "num_statements": 10,
                            "covered_branches": 6,
                            "num_branches": 10,
                        }
                    }
                )
            )
            coverage = test_health.load_coverage_metrics(coverage_path)
            totals = {
                key: coverage.as_dict()[key]
                for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
            }
            provenance_path = root / "provenance.json"
            provenance = {
                "source_sha": test_health.BASELINE_SOURCE_SHA,
                "artifact_sha256": test_health._sha256_file(coverage_path),
                "totals_sha256": test_health._canonical_sha256(totals),
                "canonical": True,
                "clean": True,
            }
            provenance_path.write_text(json.dumps(provenance))
            self.assertEqual(
                test_health._load_coverage_provenance(
                    provenance_path, coverage_path, test_health.BASELINE_SOURCE_SHA, coverage
                ),
                provenance,
            )
            coverage_path.write_text(coverage_path.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "does not authenticate"):
                test_health._load_coverage_provenance(
                    provenance_path, coverage_path, test_health.BASELINE_SOURCE_SHA, coverage
                )

    def _case_snapshot_contract_selection_is_mode_bound_and_fail_closed(self):
        baseline = json.loads((REPO / test_health.PUBLIC_MANIFEST).read_text())
        contract, authentication = test_health.snapshot_module_contract(
            REPO,
            test_health.BASELINE_SOURCE_SHA,
            baseline,
            delivery=False,
        )
        self.assertEqual(contract, baseline["module_contract"])
        self.assertEqual(authentication, {})

        current_sha = test_health._git_sha(REPO)
        live = surface_inventory.inventory(REPO, source_sha=current_sha)
        contract, authentication = test_health.snapshot_module_contract(
            REPO,
            current_sha,
            live,
            delivery=True,
        )
        self.assertEqual(len(contract), 230)
        self.assertEqual(authentication["module_contract_mode"], "delivery")

        with self.assertRaisesRegex(ValueError, "unless --delivery"):
            test_health.snapshot_module_contract(REPO, current_sha, live, delivery=False)
        with self.assertRaisesRegex(ValueError, "nonbaseline"):
            test_health.snapshot_module_contract(
                REPO,
                test_health.BASELINE_SOURCE_SHA,
                baseline,
                delivery=True,
            )

        unreviewed = json.loads(json.dumps(live))
        unreviewed["module_contract"].append(
            {
                **unreviewed["module_contract"][-1],
                "path": "freq/services/unreviewed.py",
            }
        )
        with self.assertRaisesRegex(ValueError, "differs from authenticated"):
            test_health.snapshot_module_contract(
                REPO,
                current_sha,
                unreviewed,
                delivery=True,
            )

    def _case_reviewed_additions_manifest_and_effective_hash_are_frozen(self):
        additions, effective = test_health.authenticated_effective_module_contract(REPO)
        self.assertEqual(additions["schema_version"], 2)
        self.assertEqual(len(additions["additions"]), 35)
        self.assertEqual(len(additions["retirements"]), 4)
        additions_by_path = {
            addition["contract"]["path"]: addition
            for addition in additions["additions"]
        }
        self.assertEqual(
            {
                path: addition["introduced_at"]
                for path, addition in additions_by_path.items()
            },
            {
                "freq/services/cert.py": "7eb00c6fc4ebe5e94a60648a846f709ec2c3b4ac",
                "freq/services/cert_management.py": "7eb00c6fc4ebe5e94a60648a846f709ec2c3b4ac",
                "freq/core/first_admin_claim.py": "4378a9ed3588ed4bbb258402902f0a51333d5195",
                "freq/core/host_identity.py": "04c6978ecc71dc3d2a7e13fd33aef90406de1b20",
                "freq/core/setup_paths.py": "89e7dc889d9709ec0ed16ec76c338554d7d58f5f",
                "freq/core/vault.py": "2beb85030ac7f8619f9477ee75d911a185a531a1",
                "freq/services/cert_renewal.py": "e1084cb6425f353421d61d4b050527dc2787280a",
                "freq/services/container_action.py": "7b0c27133572cbf20a1d5bec4f8fddaf097ae74e",
                "freq/services/container_logs.py": "7c10dc27722880574f6f961f5308d528aca7c82d",
                "freq/services/fleet_connectivity.py": "433e2dcc832ddf0bd1e799ee09cb27c81337db90",
                "freq/services/host_diagnostic.py": "3a4cb791933283587aa89b39eba09cdb1cf5ff5f",
                "freq/services/portscan.py": "d27b3c8c67105e66546111ed5fd14770f47781b7",
                "freq/services/pve.py": "22af9e4a2d275b7b8bf18a173838399dcc20d3d9",
                "freq/services/snmp.py": "7eb00c6fc4ebe5e94a60648a846f709ec2c3b4ac",
                "freq/services/switch_inventory.py": "0baa5a00f0bf83c13b7181c932ac9688e0dfd656",
                "freq/services/user_registry.py": "af617fef1f2891fc00de03c61cab5433d6bfda35",
                "freq/services/watch_control.py": "33bff958e7e4333c9eaf05bd53dd370a982eac32",
                "freq/services/dashboard_doctor.py": "350253231d71975442c0c48929566cd521767c2c",
                "freq/services/deployment_history.py": "5f3e7406e455daf53362abcfea5a6718fad82f06",
                "freq/services/release_update.py": "7be576601526f554ab30d9fbfcbc5cc75758b184",
                "freq/services/setup_keys.py": "06ea49440ebbddeb035dda9f7a5eed11f2ddf38d",
                "freq/services/setup_inputs.py": "420706e8accd570dc287fb1f1108cba3aff273a9",
                "freq/services/setup_handoff.py": "8cbe5079271aa0e863f4c98deaf19753939b4792",
                "freq/services/setup_health.py": "f5454f6004ae857434e12b6839c189dadb06c43c",
                "freq/services/setup_progress.py": "c2915ae692ad8c83c1a0c2b50b46eda024fcf721",
                "freq/services/ssh_mux_cleanup.py": "0dc8c8c80f9ea291578c782765f93d11da6aabf9",
                "freq/services/dns_lookup.py": "42123403de0cb41f5cfb8e139216ca0d48c12bda",
                "freq/services/device_command.py": "96b7621525312cabedc371eb8ce6dd68f194607f",
                "freq/services/lab_tool_proxy.py": "16639b93b22d2af36bba9059c20bbbfc5b8aae26",
                "freq/services/media_activity.py": "0f86693ae05d18e532f9c614fb590f8d7af41fab",
                "freq/services/fleet_policy.py": "d01d5699bebb40c4aead454a45823d62ae3f5133",
                "freq/services/fleet_status.py": "42963dddc849f9d2bf0f98eab2c285ef2482898c",
                "freq/core/install_root.py": "876d79481fb59541ad6b2f8f33452edbe9960e4c",
                "freq/core/opnsense_enrollment.py": "1f0e0641ba88fe34b22478a698742078ba95964a",
                "freq/core/opnsense_lifecycle.py": "1f0e0641ba88fe34b22478a698742078ba95964a",
            },
        )
        self.assertTrue(
            all(addition["review_status"] == "ACCEPTED" for addition in additions_by_path.values())
        )
        self.assertTrue(
            all(
                addition["contract"]
                == {
                    "path": path,
                    "classification": "UNKNOWN_KEEP",
                    "critical": False,
                    "branch_floor": 0.4,
                    "zero_branch_statement_floor": 0.7,
                    "evidence": ["UNKNOWN defaults KEEP"],
                }
                for path, addition in additions_by_path.items()
            )
        )
        self.assertEqual(
            {row["path"] for row in additions["retirements"]},
            {
                "freq/jarvis/agent.py",
                "freq/jarvis/gitops.py",
                "freq/jarvis/learn.py",
                "freq/modules/specialist.py",
            },
        )
        self.assertTrue(
            all(row["review_status"] == "SONNY_APPROVED" for row in additions["retirements"])
        )
        self.assertEqual(len(effective), 230)
        self.assertEqual(
            test_health.module_contract_sha256(effective),
            test_health.FROZEN_EFFECTIVE_MODULE_CONTRACT_SHA256,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / test_health.PUBLIC_MANIFEST
            additions_path = root / test_health.REVIEWED_MODULE_ADDITIONS_MANIFEST
            baseline_path.parent.mkdir(parents=True)
            additions_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_bytes((REPO / test_health.PUBLIC_MANIFEST).read_bytes())
            tampered = json.loads(
                (REPO / test_health.REVIEWED_MODULE_ADDITIONS_MANIFEST).read_text()
            )
            tampered["additions"][0]["review_status"] = "PENDING"
            additions_path.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "missing or modified"):
                test_health.authenticated_effective_module_contract(root)

    def _case_python_collection_disables_cache_provider(self):
        completed = subprocess_result("tests/test_x.py::test_x\n")
        with mock.patch.object(test_health.subprocess, "run", return_value=completed) as run:
            self.assertEqual(test_health.collect_python_nodeids(REPO), ["tests/test_x.py::test_x"])
        command = run.call_args.args[0]
        self.assertIn("no:cacheprovider", command)

    def _case_browser_collection_refuses_network_or_install_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "refusing install/network fallback"):
                test_health.collect_browser_ids(Path(tmp))

    def _case_delivery_snapshot_defaults_to_full_browser_inventory_config(self):
        args = test_health.build_parser().parse_args(
            [
                "snapshot",
                "--coverage-json", "coverage.json",
                "--coverage-provenance", "coverage-provenance.json",
                "--public-surface-manifest", "surfaces.json",
                "--pollution-report", "pollution.json",
                "--runtime-report", "runtime.json",
                "--python-ids-output", "python.txt",
                "--browser-ids-output", "browser.txt",
                "--output", "health.json",
                "--passed", "1",
                "--skipped", "0",
                "--warnings", "0",
            ]
        )
        self.assertEqual(args.playwright_config, "playwright.config.js")

    def _case_pollution_comparison_requires_every_category_and_reports_drift(self):
        before = {name: f"hash-{name}" for name in test_health.POLLUTION_CATEGORIES}
        after = dict(before)
        report = test_health.compare_pollution_snapshots(before, after)
        self.assertTrue(all(row["clean"] for row in report["results"].values()))
        after["sockets"] = "changed"
        report = test_health.compare_pollution_snapshots(before, after)
        self.assertFalse(report["results"]["sockets"]["clean"])
        with self.assertRaisesRegex(ValueError, "every required category"):
            test_health.compare_pollution_snapshots({}, {})


TEST_HEALTH_TOOL_CASES = (
    "_case_coverage_json_uses_raw_statement_and_branch_counts",
    "_case_terminal_gate_passes_only_the_complete_contract",
    "_case_delivery_gate_uses_authenticated_effective_contract_and_row_floors",
    "_case_baseline_metrics_do_not_require_future_terminal_browser_fields",
    "_case_contract_mode_and_delivery_authentication_fail_closed",
    "_case_terminal_gate_reports_count_coverage_hygiene_and_runtime_failures",
    "_case_terminal_gate_rejects_browser_count_owner_file_and_hash_drift",
    "_case_manifest_metrics_preserves_browser_delivery_contract",
    "_case_browser_terminal_contract_resolves_exact_owner_and_file_inventory",
    "_case_hard_only_mode_preserves_reserved_capacity_without_redefining_the_ceiling",
    "_case_node_manifest_hash_is_order_and_newline_sensitive",
    "_case_runtime_pollution_coverage_identity_and_module_inputs_fail_closed",
    "_case_terminal_integrity_rejects_all_round_two_tampering_paths",
    "_case_terminal_provenance_rejects_cross_sha_wrong_host_and_unclean_runs",
    "_case_coverage_artifact_provenance_binds_sha_hash_totals_and_clean_state",
    "_case_snapshot_contract_selection_is_mode_bound_and_fail_closed",
    "_case_reviewed_additions_manifest_and_effective_hash_are_frozen",
    "_case_python_collection_disables_cache_provider",
    "_case_browser_collection_refuses_network_or_install_fallback",
    "_case_delivery_snapshot_defaults_to_full_browser_inventory_config",
    "_case_pollution_comparison_requires_every_category_and_reports_drift",
)


class TestHealthToolMatrix(unittest.TestCase):
    def test_health_tool_matrix(self):
        self.assertEqual(len(TEST_HEALTH_TOOL_CASES), 21)
        run_case_matrix(self, TestHealthTool, TEST_HEALTH_TOOL_CASES)

class TestSurfaceInventoryTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = surface_inventory.inventory(REPO, source_sha="baseline-sha")

    def test_inventory_comes_from_real_cli_and_http_registries(self):
        surfaces = {(item["kind"], item["name"]): item for item in self.manifest["surfaces"]}
        self.assertIn(("cli-command", "doctor"), surfaces)
        self.assertIn(("cli-command", "vm list"), surfaces)
        self.assertIn(("http-legacy", "/healthz"), surfaces)
        self.assertTrue(any(kind == "http-v1" for kind, _ in surfaces))

    def test_inventory_is_unique_and_unknown_fails_to_keep(self):
        keys = [(item["kind"], item["name"]) for item in self.manifest["surfaces"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(self.manifest["classification_policy"]["default"], "UNKNOWN")
        self.assertIn("KEEP", self.manifest["classification_policy"]["unknown_means"])
        self.assertEqual(self.manifest["source_sha"], "baseline-sha")

    def test_completeness_matrix_and_cli_action_counts_are_frozen(self):
        self.assertEqual(set(self.manifest["completeness_matrix"]), surface_inventory.REQUIRED_CATEGORIES)
        tracked = json.loads((REPO / test_health.PUBLIC_MANIFEST).read_text())
        changes = test_health.authenticated_public_surface_deltas(REPO)
        expected = dict(tracked["counts"])
        for row in changes["retirements"]:
            expected[row["kind"]] -= 1
        for row in changes["additions"]:
            kind = row["surface"]["kind"]
            expected[kind] = expected.get(kind, 0) + 1
        self.assertEqual(self.manifest["counts"], expected)
        for category in surface_inventory.REQUIRED_CATEGORIES:
            self.assertGreater(self.manifest["completeness_matrix"][category]["count"], 0)

    def test_http_rows_freeze_method_mutation_and_access_semantics(self):
        http_rows = [row for row in self.manifest["surfaces"] if row["kind"].startswith("http-")]
        tracked = json.loads((REPO / test_health.PUBLIC_MANIFEST).read_text())
        changes = test_health.authenticated_public_surface_deltas(REPO)
        expected = sum(row["kind"].startswith("http-") for row in tracked["surfaces"])
        expected -= sum(row["kind"].startswith("http-") for row in changes["retirements"])
        expected += sum(
            row["surface"]["kind"].startswith("http-") for row in changes["additions"]
        )
        self.assertEqual(len(http_rows), expected)
        for row in http_rows:
            self.assertTrue(row["methods"])
            self.assertIn(row["mutation"], {"read", "mutation", "mixed", "unknown"})
            self.assertTrue(row["access"])

    def test_legacy_http_semantics_come_from_enforcement_not_path_guessing(self):
        rows = {
            row["name"]: row for row in self.manifest["surfaces"] if row["kind"] == "http-legacy"
        }
        expected = {
            "/api/containers/action": (["POST"], "operator"),
            "/api/lab-tool/save-config": (["POST"], "admin"),
            "/api/setup/configure": (["POST"], "bootstrap-or-public-guarded"),
            "/api/setup/contract": (["GET", "POST"], "admin"),
            "/api/setup/device-credentials": (["POST"], "admin"),
            "/api/setup/discovery/start": (["POST"], "admin"),
            "/api/setup/init/cancel": (["POST"], "admin"),
            "/api/setup/init/start": (["POST"], "admin"),
        }
        for path, (methods, access) in expected.items():
            self.assertEqual(rows[path]["methods"], methods)
            self.assertEqual(rows[path]["access"], access)
            self.assertEqual(rows[path]["semantics_status"], "RESOLVED")

        def handler_without_enforcement():
            return None

        unresolved = surface_inventory._http_semantics("/api/widgets/create", handler_without_enforcement)
        self.assertEqual(unresolved["methods"], ["UNKNOWN"])
        self.assertEqual(unresolved["mutation"], "unknown")
        self.assertEqual(unresolved["semantics_status"], "UNKNOWN_KEEP")

    def test_local_role_guard_aliases_and_unresolved_indirection_fail_closed(self):
        rows = {
            row["name"]: row for row in self.manifest["surfaces"] if row["kind"] == "http-v1"
        }
        aliases = {
            "/api/snmp/setup/apply",
            "/api/snmp/setup/credentials",
            "/api/v1/net/snmp/setup/apply",
            "/api/v1/net/snmp/setup/credentials",
        }
        for path in aliases:
            self.assertEqual(rows[path]["access"], "admin")
            self.assertEqual(rows[path]["access_status"], "RESOLVED")
            self.assertEqual(rows[path]["semantics_status"], "RESOLVED")

        mixed = rows["/api/vm/network-profiles"]
        self.assertEqual(mixed["methods"], ["GET", "POST"])
        self.assertEqual(mixed["access"], "UNKNOWN")
        self.assertEqual(mixed["access_status"], "UNKNOWN_KEEP")
        self.assertEqual(mixed["semantics_status"], "UNKNOWN_KEEP")

        unresolved = surface_inventory._http_semantics(
            "/api/example", _handler_with_unresolved_role_guard
        )
        self.assertEqual(unresolved["methods"], ["POST"])
        self.assertEqual(unresolved["access"], "UNKNOWN")
        self.assertEqual(unresolved["access_status"], "UNKNOWN_KEEP")
        self.assertEqual(unresolved["semantics_status"], "UNKNOWN_KEEP")

    def test_inventory_contains_only_tracked_source_artifacts(self):
        forbidden = {"__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"}
        evidence = [item for row in self.manifest["surfaces"] for item in row["evidence"]]
        module_paths = [row["path"] for row in self.manifest["module_contract"]]
        for value in [*evidence, *module_paths]:
            path = Path(value.split(":", 1)[0])
            self.assertFalse(forbidden.intersection(path.parts), value)
            self.assertNotIn(path.suffix, {".pyc", ".pyo"}, value)

    def test_retained_and_critical_module_contract_is_versioned(self):
        modules = {row["path"]: row for row in self.manifest["module_contract"]}
        self.assertEqual(set(test_health.CRITICAL_MODULES), surface_inventory.CRITICAL_MODULES)
        self.assertTrue(surface_inventory.CRITICAL_MODULES <= modules.keys())
        self.assertTrue(all(modules[path]["critical"] for path in surface_inventory.CRITICAL_MODULES))


class TestTrackedBaselineManifests(unittest.TestCase):
    def test_baseline_node_ids_and_coverage_are_exact_and_self_verifying(self):
        manifest = json.loads((REPO / "tests/manifests/b94321f-test-health.json").read_text())
        python_ids = (REPO / manifest["python"]["node_ids_file"]).read_text().splitlines()
        browser_ids = (REPO / manifest["browser"]["node_ids_file"]).read_text().splitlines()

        self.assertEqual(manifest["source_sha"], "b94321f968d1f2601b40404c3aff242e5858ced7")
        self.assertEqual(len(python_ids), 4886)
        self.assertEqual(len(browser_ids), 76)
        self.assertEqual(test_health._sha256_lines(python_ids), manifest["python"]["node_ids_sha256"])
        self.assertEqual(test_health._sha256_lines(browser_ids), manifest["browser"]["node_ids_sha256"])
        self.assertEqual(manifest["coverage"]["covered_branches"], 5955)
        self.assertEqual(manifest["coverage"]["num_branches"], 18204)
        self.assertNotIn("covered_branches", manifest["delivery_targets"])
        self.assertEqual(manifest["coverage_identity"], test_health.coverage_identity(REPO))
        self.assertEqual(manifest["baseline_coverage_identity"], manifest["coverage_identity"])
        self.assertEqual(len(manifest["module_coverage"]), 199)
        self.assertEqual(
            {
                row["path"]
                for row in manifest["module_coverage"]
                if row["retained_public"] and row["coverage_status"] != "MEASURED"
            },
            {
                "freq/data/__init__.py",
                "freq/data/conf-templates/plugins/example_ping.py",
                "freq/data/web/__init__.py",
                "freq/tui/__init__.py",
                "freq/tui/menu.py",
            },
        )
        self.assertEqual(manifest["module_contract_sha256"], test_health.FROZEN_MODULE_CONTRACT_SHA256)
        self.assertEqual(manifest["coverage_provenance"]["source_sha"], manifest["source_sha"])
        self.assertFalse(manifest["python"]["runtime"]["canonical"])
        self.assertEqual(manifest["python"]["runtime"]["host"], "VM999")
        self.assertTrue(
            all(not row["measured"] for row in manifest["python"]["pollution"]["results"].values())
        )
        failures = test_health.evaluate(test_health._manifest_metrics(manifest), manifest["delivery_targets"])
        self.assertTrue(any("exactly three clean VM999" in item for item in failures))
        self.assertTrue(any("pollution gate" in item for item in failures))

    def test_public_surface_baseline_and_module_contract_are_preserved(self):
        tracked = json.loads((REPO / "tests/manifests/b94321f-public-surfaces.json").read_text())
        live = surface_inventory.inventory(REPO, source_sha=tracked["source_sha"])
        changes = test_health.authenticated_public_surface_deltas(REPO)
        tracked_surfaces = {(row["kind"], row["name"]): row for row in tracked["surfaces"]}
        live_surfaces = {(row["kind"], row["name"]): row for row in live["surfaces"]}
        retired = {(row["kind"], row["name"]) for row in changes["retirements"]}
        additions = {
            (row["surface"]["kind"], row["surface"]["name"]): row["surface"]
            for row in changes["additions"]
        }
        self.assertEqual(tracked_surfaces.keys() - live_surfaces.keys(), retired)
        self.assertEqual(live_surfaces.keys() - tracked_surfaces.keys(), additions.keys())
        shared = tracked_surfaces.keys() & live_surfaces.keys()
        self.assertEqual(
            {key: tracked_surfaces[key] for key in shared},
            {key: live_surfaces[key] for key in shared},
        )
        self.assertEqual({key: live_surfaces[key] for key in additions}, additions)

        _, effective = test_health.authenticated_effective_module_contract(REPO)
        live_modules = {row["path"]: row for row in live["module_contract"]}
        effective_modules = {row["path"]: row for row in effective}
        self.assertEqual(live_modules, effective_modules)

        audit = json.loads(
            (REPO / "tests/manifests/test_redesign_stage1_retirement_audit.json").read_text()
        )
        self.assertEqual(audit["source_sha"], "178a0265ec856c4b3e4944cc77925f8418da482d")
        self.assertEqual(audit["summary"]["tracked_python_modules"], 199)
        self.assertEqual(audit["summary"]["config_fields_with_known_consumers"], 86)
        self.assertEqual(audit["summary"]["approved_public_retirements"], 0)
        self.assertEqual(len(audit["safe_internal_candidates"]), 1)
        r4 = next(row for row in audit["public_candidates_held_unknown_keep"] if row["id"] == "R4")
        self.assertEqual(
            r4["known_cross_repo_consumer"]["commit"],
            "df95511bcc0ced8a90833d479205b8947563d675",
        )
        self.assertEqual(r4["known_cross_repo_consumer"]["line"], 3607)
        self.assertNotIn("/data/projects", json.dumps(audit))
        self.assertTrue(
            all(
                row["classification"] == "UNKNOWN_KEEP" and row["approval_required"]
                for row in audit["public_candidates_held_unknown_keep"]
            )
        )

        retirements = json.loads(
            (REPO / "tests/manifests/test_redesign_stage2_retirements.json").read_text()
        )
        self.assertEqual(retirements["base_source_sha"], "05eede825ac1934f36a7612af0fbdb268e848cbf")
        self.assertEqual(len(retirements["retirements"]), 1)
        retirement = retirements["retirements"][0]
        self.assertEqual(retirement["classification"], "RETIRED")
        self.assertEqual(retirement["public_surface_delta"], 0)
        self.assertEqual(retirement["post_retirement_denominators"]["num_statements"], 52803)
        self.assertEqual(retirement["post_retirement_denominators"]["num_branches"], 18204)


if __name__ == "__main__":
    unittest.main()
