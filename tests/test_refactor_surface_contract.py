"""Durable causal owner for the exact-ref refactor public-surface diff."""

from __future__ import annotations

import copy
import functools
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import refactor_surface_contract as contract
from tests.case_matrix import run_case_matrix

@functools.cache
def _current_snapshot():
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=REPO, text=True).strip()
    return sha, tree, contract.snapshot(REPO, sha, tree)


class RefactorSurfaceContractCases(unittest.TestCase):
    def setUp(self):
        self.sha, self.tree, self.snapshot = _current_snapshot()

    def _case_snapshot_covers_every_required_public_boundary(self):
        self.assertEqual(self.snapshot["schema_version"], contract.SCHEMA_VERSION)
        self.assertEqual(
            set(contract.REQUIRED_DIFF_SECTIONS),
            set(self.snapshot) - {"schema_version", "source_sha", "source_tree"},
        )
        self.assertIn("<root>", self.snapshot["cli_help_docs"]["cli"])
        self.assertIn("README.md", self.snapshot["cli_help_docs"]["docs"])
        self.assertIn("ui-api-consumer:freq/data/web/js/app.js:/api/events", self.snapshot["frontend_consumers"]["consumers"])
        self.assertIn("http-legacy:/api/events", self.snapshot["http_contract"]["routes"])
        routes = self.snapshot["http_contract"]["routes"]
        login = routes["http-legacy:/api/auth/login"]
        self.assertEqual(login["methods"], ["POST"])
        self.assertEqual(login["dispatch_auth"], "public-or-bootstrap")
        self.assertEqual(login["csrf"], "exempt")
        ui_event = routes["http-legacy:/api/ui/event"]
        self.assertEqual(ui_event["handler_rbac"], "viewer")
        self.assertEqual(ui_event["csrf"], "required")
        self.assertIn(405, {row["status"] for row in ui_event["responses"]})
        globals_ = self.snapshot["http_contract"]["global"]
        self.assertIn(404, {row["status"] for row in globals_["dispatch_404_and_500"]["responses"]})
        self.assertIn("error", globals_["dispatch_404_and_500"]["responses"][0]["envelope"])
        self.assertIn("Cache-Control", {row["name"] for row in globals_["json_error_and_cache"]["headers"]})
        self.assertIn("Content-Security-Policy", {row["name"] for row in globals_["security_headers"]["headers"]})
        self.assertEqual(globals_["sse"]["path"], "/api/events")
        self.assertIn("text/event-stream", {row["value"] for row in globals_["sse"]["headers"]})
        self.assertIn("paths", self.snapshot["openapi"])
        self.assertEqual(len(self.snapshot["authenticated_modules"]["modules"]), 230)

    def _case_snapshot_follows_the_shared_security_header_policy(self):
        from freq.api.auth import send_security_headers

        expected = contract._response_contract(contract._handler_source(send_security_headers))
        actual = self.snapshot["http_contract"]["global"]["security_headers"]
        self.assertEqual(actual["source_sha256"], contract._sha256(contract._handler_source(send_security_headers)))
        self.assertEqual(actual["headers"], expected["headers"])

    def _case_equal_snapshots_emit_a_clean_complete_diff(self):
        result = contract.compare(self.snapshot, copy.deepcopy(self.snapshot))
        self.assertTrue(result["clean"])
        self.assertEqual(set(result["sections"]), set(contract.REQUIRED_DIFF_SECTIONS))
        self.assertEqual(set(result["summary"].values()), {0})

    def _case_each_required_boundary_emits_an_executable_delta(self):
        changed = copy.deepcopy(self.snapshot)
        changed["cli_help_docs"]["cli"]["<root>"]["description"] = "mutated help"
        changed["frontend_consumers"]["assets"]["freq/data/web/js/app.js"]["sha256"] = "0" * 64
        changed["http_contract"]["routes"]["http-legacy:/api/events"]["csrf"] = "mutated"
        changed["openapi"]["openapi"] = "0.0.0"
        module = next(iter(changed["authenticated_modules"]["modules"].values()))
        module["classification"] = "mutated"

        result = contract.compare(self.snapshot, changed)
        self.assertFalse(result["clean"])
        self.assertTrue(all(result["sections"][section] for section in contract.REQUIRED_DIFF_SECTIONS))
        self.assertTrue(all(result["summary"][section] >= 1 for section in contract.REQUIRED_DIFF_SECTIONS))
        encoded = json.dumps(result, sort_keys=True)
        for token in ("mutated help", "app.js", "http-legacy:~1api~1events", "0.0.0", "classification"):
            self.assertIn(token, encoded)

    def _case_cli_ref_diff_is_exact_and_leaves_no_repository_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "diff.json"
            exit_code = contract.main(
                [
                    "diff",
                    "--repo",
                    str(REPO),
                    "--base-ref",
                    self.sha,
                    "--head-ref",
                    self.sha,
                    "--output",
                    str(output),
                    "--require-no-drift",
                ]
            )
            result = json.loads(output.read_text())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["clean"])
        self.assertEqual(result["base"], {"sha": self.sha, "tree": self.tree})
        self.assertEqual(result["head"], result["base"])

    def _case_unregistered_public_module_fails_closed(self):
        from scripts import test_health

        _additions, authenticated = test_health.authenticated_effective_module_contract(REPO)
        live = [*authenticated, {**authenticated[-1], "path": "freq/services/unregistered.py"}]
        with mock.patch(
            "scripts.test_health.authenticated_effective_module_contract",
            return_value=({"additions": []}, authenticated),
        ):
            with self.assertRaisesRegex(ValueError, "differ from authenticated manifest"):
                contract._authenticated_modules(REPO, live)

    def _case_pure_config_projection_delegation_preserves_response_contract(self):
        from freq.modules.serve import FreqHandler

        delegated = contract._response_contract(contract._handler_source(FreqHandler._serve_config))
        literal = contract._response_contract(
            """
def _serve_config(self):
    cfg = load_config()
    self._json_response(
        {
            "version": cfg.version,
            "brand": cfg.brand,
            "build": cfg.build,
            "ssh_account": cfg.ssh_service_account,
            "ssh_timeout": cfg.ssh_connect_timeout,
            "ssh_parallel": cfg.ssh_max_parallel,
            "pve_nodes": cfg.pve_nodes,
            "cluster": cfg.cluster_name,
            "timezone": cfg.timezone,
            "truenas_ip": cfg.truenas_ip,
            "pfsense_ip": cfg.pfsense_ip,
            "install_dir": cfg.install_dir,
            "hosts_count": len(cfg.hosts),
            "vlans_count": len(cfg.vlans),
            "distros_count": len(cfg.distros),
            "protected_vmids": cfg.protected_vmids,
            "pve_nodes_discovered": [n.get("name", "") for n in _get_discovered_nodes()],
            "kill_chain": _load_kill_chain(cfg)
            or ["Operator", "VPN", "Firewall", "Switch", "Network", "Target"],
        }
    )
"""
        )
        self.assertEqual(delegated, literal)


class TestRefactorSurfaceContract(unittest.TestCase):
    def test_refactor_surface_contract(self):
        run_case_matrix(
            self,
            RefactorSurfaceContractCases,
            (
                "_case_snapshot_covers_every_required_public_boundary",
                "_case_snapshot_follows_the_shared_security_header_policy",
                "_case_equal_snapshots_emit_a_clean_complete_diff",
                "_case_each_required_boundary_emits_an_executable_delta",
                "_case_cli_ref_diff_is_exact_and_leaves_no_repository_artifact",
                "_case_unregistered_public_module_fails_closed",
                "_case_pure_config_projection_delegation_preserves_response_contract",
            ),
        )


if __name__ == "__main__":
    unittest.main()
