#!/usr/bin/env python3
"""Build and validate the Stage-0 frontend/browser test redesign manifest.

The manifest is a frozen baseline, not a test runner configuration.  It records
every in-scope Python node ID and Playwright ID exactly once, assigns the agreed
disposition/target owner, and preserves source hashes so later retirement work
can prove what changed from the accepted b94321f baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

BASELINE_COMMIT = "b94321f968d1f2601b40404c3aff242e5858ced7"
MANIFEST_PATH = Path("tests/manifests/frontend_test_redesign_stage0.json")

OWNER_CATALOG = [
    {"id": "K01", "kind": "static_keep", "name": "session security topology"},
    {"id": "K02", "kind": "static_keep", "name": "single router root"},
    {"id": "C01", "kind": "static_consolidated", "name": "asset package CSP and inline hashes"},
    {"id": "C02", "kind": "static_consolidated", "name": "route subnav and semantic structure"},
    {"id": "C03", "kind": "static_consolidated", "name": "setup endpoint action and marker schema"},
    {"id": "C04", "kind": "static_consolidated", "name": "factual state and copy vocabulary"},
    {"id": "C05", "kind": "static_consolidated", "name": "shipped layout semantics"},
    {"id": "H01", "kind": "hermetic", "name": "auth and security lifecycle"},
    {"id": "H02", "kind": "hermetic", "name": "shell router and navigation"},
    {"id": "H03", "kind": "hermetic", "name": "read and freshness behavior"},
    {"id": "H04", "kind": "hermetic", "name": "mutation safety"},
    {"id": "H05", "kind": "hermetic", "name": "operator RBAC"},
    {"id": "H06", "kind": "hermetic", "name": "zero-state happy path"},
    {"id": "H07", "kind": "hermetic", "name": "zero-state failure and resume"},
    {"id": "H08", "kind": "hermetic", "name": "zero-state explicit empty contract"},
    {"id": "H09", "kind": "hermetic", "name": "accessibility semantics"},
    {"id": "H10", "kind": "hermetic", "name": "responsive shell"},
    {"id": "H11", "kind": "hermetic", "name": "operator truth and degradation"},
    {"id": "H12", "kind": "hermetic", "name": "terminal behavior"},
    {"id": "H13", "kind": "hermetic", "name": "lab-tool proxy credential boundary"},
    {"id": "L01", "kind": "live_safe", "name": "doctor and core reads"},
    {"id": "L02", "kind": "live_safe", "name": "device storage and safe terminals"},
    {"id": "L03", "kind": "live_safe", "name": "responsive shell and console cleanliness"},
    {"id": "L04", "kind": "live_safe", "name": "operator RBAC"},
    {"id": "S01", "kind": "sandbox", "name": "destructive sandbox controls"},
]

# disposition, target owner, source file.  Each source file has exactly one
# Stage-0 disposition; every collected node is expanded explicitly in JSON.
PYTHON_FILE_PLAN = [
    ("KEEP", "K01", "tests/test_public_web_security_frontend_contract.py"),
    ("KEEP", "K02", "tests/test_single_view_router_contract.py"),
    ("CONSOLIDATE", "C05", "tests/test_ah_semantic_classes_contract.py"),
    ("CONSOLIDATE", "C04", "tests/test_brand_surface_contract.py"),
    ("CONSOLIDATE", "C01", "tests/test_browser_deploy_truth.py"),
    ("CONSOLIDATE", "C04", "tests/test_collection_state_semantics_contract.py"),
    ("CONSOLIDATE", "C05", "tests/test_dense_ops_layout_contract.py"),
    ("CONSOLIDATE", "C05", "tests/test_drilldown_affordance_contract.py"),
    ("CONSOLIDATE", "C04", "tests/test_empty_state_evidence_contract.py"),
    ("CONSOLIDATE", "C01", "tests/test_inline_style_sweep_contract.py"),
    ("CONSOLIDATE", "C02", "tests/test_login_form_robustness_contract.py"),
    ("CONSOLIDATE", "C04", "tests/test_login_home_copy_contract.py"),
    ("CONSOLIDATE", "C05", "tests/test_mobile_density_contract.py"),
    ("CONSOLIDATE", "C02", "tests/test_settings_device_assignment_grouping_contract.py"),
    ("CONSOLIDATE", "C03", "tests/test_setup_copy_contract.py"),
    ("CONSOLIDATE", "C02", "tests/test_snmp_setup_ui_contract.py"),
    ("CONSOLIDATE", "C02", "tests/test_ssl_manager_onboarding_ui_contract.py"),
    ("CONSOLIDATE", "C04", "tests/test_status_copy_tone.py"),
    ("CONSOLIDATE", "C02", "tests/test_subnav_symmetry_contract.py"),
    ("CONSOLIDATE", "C01", "tests/test_web_csp_inline_contract.py"),
    ("CONSOLIDATE", "C01", "tests/test_web_external_asset_contract.py"),
    ("CONSOLIDATE", "C01", "tests/test_zero_dependency_fonts_contract.py"),
    ("REPLACE", "H11", "tests/test_auth_fetch_silent_opt_contract.py"),
    ("REPLACE", "H01", "tests/test_auth_preauth_storm_contract.py"),
    ("REPLACE", "H01", "tests/test_blueteam_hardening_contract.py"),
    ("REPLACE", "H04", "tests/test_blueteam_ux_contract.py"),
    ("REPLACE", "H04", "tests/test_chaos_confirmation_ui_contract.py"),
    ("REPLACE", "H09", "tests/test_dashboard_accessibility_contract.py"),
    ("REPLACE", "H05", "tests/test_dashboard_operator_truth_contract.py"),
    ("REPLACE", "H03", "tests/test_data_freshness_ui_contract.py"),
    ("REPLACE", "H10", "tests/test_live_polish_contract.py"),
    ("REPLACE", "H11", "tests/test_operator_truth_contract.py"),
    ("REPLACE", "H11", "tests/test_operator_truth_product_law.py"),
    ("REPLACE", "H11", "tests/test_watchdog_ui_honesty.py"),
    ("DELETE", "H02", "tests/test_fleet_infra_overview_removed_contract.py"),
    ("DELETE", "H01", "tests/test_release_ux_qa_contract.py"),
]

EXPECTED_PYTHON_DISPOSITIONS = {
    "KEEP": 7,
    "CONSOLIDATE": 233,
    "REPLACE": 186,
    "DELETE": 6,
}

PLAYWRIGHT_FILES = [
    "tests/e2e/accessibility-semantics.spec.js",
    "tests/e2e/all-pages-safe-read-buttons.spec.js",
    "tests/e2e/docker-live-controls.spec.js",
    "tests/e2e/hermetic-dashboard.spec.js",
    "tests/e2e/live-safe.spec.js",
    "tests/e2e/operator-truth.spec.js",
    "tests/e2e/responsive-layout-sweep.spec.js",
    "tests/e2e/ui-polish.spec.js",
    "tests/e2e/vm-controls-destructive.spec.js",
    "tests/e2e/zero-state-web-ux.spec.js",
]


def _run(command: list[str], repo: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=repo,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}")
    return result.stdout


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_python_nodes(repo: Path) -> list[str]:
    files = [entry[2] for entry in PYTHON_FILE_PLAN]
    output = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            *files,
        ],
        repo,
    )
    prefixes = tuple(f"{path}::" for path in files)
    return sorted(line.strip() for line in output.splitlines() if line.strip().startswith(prefixes))


def _playwright_command(repo: Path) -> list[str]:
    override = os.environ.get("PVE_FREQ_PLAYWRIGHT_BIN")
    if override:
        return [override]
    local = repo / "node_modules" / ".bin" / "playwright"
    if local.exists():
        return [str(local)]
    executable = shutil.which("playwright")
    if executable:
        return [executable]
    return ["npx", "--no-install", "playwright"]


def collect_playwright_nodes(repo: Path) -> list[dict[str, Any]]:
    command = [
        *_playwright_command(repo),
        "test",
        "--config=playwright.hermetic.config.js",
        "--list",
    ]
    output = _run(command, repo, env=os.environ.copy())
    line_pattern = re.compile(r"^\s*\[(?P<project>[^]]+)]\s+›\s+(?P<rest>.+)$")
    location_pattern = re.compile(
        r"^(?P<file>.+):(?P<line>\d+):(?P<column>\d+)\s+›\s+(?P<title>.+)$"
    )
    nodes: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = line_pattern.match(line)
        if not match:
            continue
        location = location_pattern.match(match.group("rest"))
        if not location:
            raise ValueError(f"unparseable Playwright list row: {line}")
        node = {
            "id": f"[{match.group('project')}] › {match.group('rest')}",
            "project": match.group("project"),
            "file": location.group("file"),
            "line": int(location.group("line")),
            "column": int(location.group("column")),
            "title": location.group("title"),
        }
        node["target_owner"] = classify_playwright_owner(node)
        nodes.append(node)
    return sorted(nodes, key=lambda item: item["id"])


def classify_playwright_owner(node: dict[str, Any]) -> str:
    path = node["file"]
    title = node["title"]

    if path.endswith("accessibility-semantics.spec.js"):
        return "H09"
    if path.endswith("operator-truth.spec.js"):
        return "H05"
    if path.endswith("zero-state-web-ux.spec.js"):
        if "successful empty discovery" in title:
            return "H08"
        if "without both durable markers" in title:
            return "H07"
        return "H06"
    if path.endswith("hermetic-dashboard.spec.js"):
        if title.startswith("H13 lab-tool proxy requests keep vault credentials out of browser request surfaces"):
            return "H13"
        if any(
            phrase in title
            for phrase in (
                "unauthenticated",
                "bad password",
                "empty password",
                "successful login",
                "login rejects GET",
                "content-type protection",
                "denies framing",
                "content security policy",
                "security headers",
                "anonymous fleet access",
                "logout invalidates",
                "unknown api endpoint",
            )
        ):
            return "H01"
        if any(
            phrase in title
            for phrase in (
                "generated Fleet",
                "one view router",
                "browser login reveals",
                "served javascript",
                "served router",
            )
        ):
            return "H02"
        if any(
            phrase in title
            for phrase in (
                "Network actions",
                "expanding a data panel",
                "verified Fleet writes",
            )
        ):
            return "H03"
        if "chaos injection" in title or "mutation endpoint" in title:
            return "H04"
        return "H11"
    if path.endswith("all-pages-safe-read-buttons.spec.js"):
        if "Settings" in title:
            return "L04"
        if "Docker" in title or "Network" in title:
            return "L02"
        return "L01"
    if path.endswith("docker-live-controls.spec.js"):
        return "S01" if "restart" in title else "L02"
    if path.endswith("live-safe.spec.js"):
        if "terminal sessions open and close" in title:
            return "H12"
        if "terminal" in title:
            return "L02"
        if "page errors" in title:
            return "L03"
        return "L01"
    if path.endswith("responsive-layout-sweep.spec.js"):
        return "H03" if "not duplicated" in title else "H10"
    if path.endswith("ui-polish.spec.js"):
        if "optional enrichment" in title:
            return "L01"
        return "L03"
    if path.endswith("vm-controls-destructive.spec.js"):
        return "S01"
    raise ValueError(f"no target owner rule for Playwright node: {node['id']}")


def build_manifest(repo: Path) -> dict[str, Any]:
    python_nodes = collect_python_nodes(repo)
    by_file: dict[str, list[str]] = {path: [] for _, _, path in PYTHON_FILE_PLAN}
    for node in python_nodes:
        source_file = node.split("::", 1)[0]
        if source_file not in by_file:
            raise ValueError(f"collected Python node is outside plan: {node}")
        by_file[source_file].append(node)

    python_sources = []
    for disposition, owner, source_file in PYTHON_FILE_PLAN:
        python_sources.append(
            {
                "source_file": source_file,
                "sha256": _sha256(repo / source_file),
                "disposition": disposition,
                "target_owner": owner,
                "node_ids": sorted(by_file[source_file]),
            }
        )

    playwright_nodes = collect_playwright_nodes(repo)
    hashed_sources = sorted(
        {entry[2] for entry in PYTHON_FILE_PLAN}
        | set(PLAYWRIGHT_FILES)
        | {"playwright.hermetic.config.js"}
    )

    manifest = {
        "schema_version": 1,
        "kind": "pve-freq.frontend-test-redesign-stage0",
        "baseline": {
            "commit": BASELINE_COMMIT,
            "default_python_collected": 4886,
            "default_python_passed": 4862,
            "default_python_skipped": 24,
            "default_python_seconds": 327.54,
            "coverage": {
                "statements": 52806,
                "covered_statements": 21630,
                "branches": 18204,
                "covered_branches": 5955,
                "statement_percent": 40.96,
                "branch_percent": 32.71,
                "combined_display_percent": 39,
            },
            "frontend_python_slice": {
                "files": 36,
                "collected": 432,
                "passed": 431,
                "skipped": 1,
                "seconds": 10.45,
                "source_membership_assertions": 748,
                "source_read_sites": 86,
                "isolated_covered_statements": 1370,
                "isolated_covered_branches": 49,
                "isolated_combined_display_percent": 2,
            },
            "playwright": {
                "files": 10,
                "definitions": 76,
                "hermetic_runnable": 36,
                "hermetic_skipped_live_or_destructive": 40,
            },
        },
        "terminal_targets": {
            "default_python_hard_ceiling": 3000,
            "finn_clancy_delivery_ceiling": 2700,
            "future_infra_failure_reserve_minimum": 300,
            "frontend_python_ceiling": 70,
            "playwright_definitions": {"hermetic": 12, "live_safe": 4, "sandbox": 1},
            "coverage": {
                "statement_percent_minimum": 70,
                "branch_percent_minimum": 60,
                "combined_percent_minimum": 67,
            },
            "runtime_seconds": {
                "delivery_median_target": 270,
                "terminal_median_maximum": 300,
                "terminal_single_run_maximum": 330,
            },
        },
        "owner_catalog": OWNER_CATALOG,
        "python": {
            "expected_nodes": 432,
            "expected_disposition_counts": EXPECTED_PYTHON_DISPOSITIONS,
            "sources": python_sources,
        },
        "playwright": {"expected_nodes": 76, "nodes": playwright_nodes},
        "source_hashes": {path: _sha256(repo / path) for path in hashed_sources},
        "collection_commands": {
            "python": "python -m pytest --collect-only -q -o addopts= -p no:cacheprovider <36 frozen files>",
            "playwright": "playwright test --config=playwright.hermetic.config.js --list",
        },
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported manifest schema")
    if manifest.get("baseline", {}).get("commit") != BASELINE_COMMIT:
        raise ValueError("baseline commit mismatch")

    owners = {entry["id"]: entry for entry in manifest["owner_catalog"]}
    if len(owners) != len(manifest["owner_catalog"]):
        raise ValueError("duplicate owner ID")
    owner_kind_counts: dict[str, int] = {}
    for owner in owners.values():
        owner_kind_counts[owner["kind"]] = owner_kind_counts.get(owner["kind"], 0) + 1
    expected_owner_kinds = {"hermetic": 12, "live_safe": 4, "sandbox": 1}
    for kind, expected in expected_owner_kinds.items():
        if owner_kind_counts.get(kind) != expected:
            raise ValueError(f"{kind} owner count: {owner_kind_counts.get(kind)} != {expected}")

    python_nodes: list[str] = []
    disposition_counts: dict[str, int] = {}
    source_files: list[str] = []
    for source in manifest["python"]["sources"]:
        source_files.append(source["source_file"])
        if source["target_owner"] not in owners:
            raise ValueError(f"unknown Python owner: {source['target_owner']}")
        nodes = source["node_ids"]
        if any(not node.startswith(f"{source['source_file']}::") for node in nodes):
            raise ValueError(f"node/file mismatch: {source['source_file']}")
        python_nodes.extend(nodes)
        disposition = source["disposition"]
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + len(nodes)
    if len(source_files) != len(set(source_files)):
        raise ValueError("Python source file appears more than once")
    if len(python_nodes) != manifest["python"]["expected_nodes"]:
        raise ValueError("Python node total mismatch")
    if len(python_nodes) != len(set(python_nodes)):
        raise ValueError("Python node is accounted more than once")
    if disposition_counts != manifest["python"]["expected_disposition_counts"]:
        raise ValueError(
            f"Python disposition mismatch: {disposition_counts} != "
            f"{manifest['python']['expected_disposition_counts']}"
        )

    playwright_nodes = manifest["playwright"]["nodes"]
    playwright_ids = [node["id"] for node in playwright_nodes]
    if len(playwright_ids) != manifest["playwright"]["expected_nodes"]:
        raise ValueError("Playwright node total mismatch")
    if len(playwright_ids) != len(set(playwright_ids)):
        raise ValueError("Playwright node is accounted more than once")
    for node in playwright_nodes:
        owner = owners.get(node["target_owner"])
        if owner is None or owner["kind"] not in {"hermetic", "live_safe", "sandbox"}:
            raise ValueError(f"invalid Playwright target owner: {node['target_owner']}")
    used_browser_owners = {node["target_owner"] for node in playwright_nodes}
    catalog_browser_owners = {
        owner_id
        for owner_id, owner in owners.items()
        if owner["kind"] in {"hermetic", "live_safe", "sandbox"}
    }
    if used_browser_owners != catalog_browser_owners:
        missing = sorted(catalog_browser_owners - used_browser_owners)
        extra = sorted(used_browser_owners - catalog_browser_owners)
        raise ValueError(f"browser owner coverage mismatch: missing={missing} extra={extra}")


def verify_current(repo: Path, manifest: dict[str, Any]) -> None:
    current_python = set(collect_python_nodes(repo))
    manifest_python = {
        node
        for source in manifest["python"]["sources"]
        for node in source["node_ids"]
    }
    if current_python != manifest_python:
        raise ValueError(
            "current Python collection differs from baseline: "
            f"missing={sorted(manifest_python - current_python)[:10]} "
            f"extra={sorted(current_python - manifest_python)[:10]}"
        )

    current_playwright = {node["id"] for node in collect_playwright_nodes(repo)}
    manifest_playwright = {node["id"] for node in manifest["playwright"]["nodes"]}
    if current_playwright != manifest_playwright:
        raise ValueError(
            "current Playwright collection differs from baseline: "
            f"missing={sorted(manifest_playwright - current_playwright)[:10]} "
            f"extra={sorted(current_playwright - manifest_playwright)[:10]}"
        )

    for path, expected_hash in manifest["source_hashes"].items():
        actual_hash = _sha256(repo / path)
        if actual_hash != expected_hash:
            raise ValueError(f"baseline source hash drift: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="collect and write the deterministic manifest")
    mode.add_argument("--check", action="store_true", help="validate the committed manifest")
    parser.add_argument(
        "--verify-current",
        action="store_true",
        help="also compare the manifest with the current source collection and hashes",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    manifest_path = repo / MANIFEST_PATH
    if args.write:
        manifest = build_manifest(repo)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    else:
        manifest = json.loads(manifest_path.read_text())
        validate_manifest(manifest)
    if args.verify_current:
        verify_current(repo, manifest)

    python_counts = manifest["python"]["expected_disposition_counts"]
    browser_counts: dict[str, int] = {}
    owner_kind = {entry["id"]: entry["kind"] for entry in manifest["owner_catalog"]}
    for node in manifest["playwright"]["nodes"]:
        kind = owner_kind[node["target_owner"]]
        browser_counts[kind] = browser_counts.get(kind, 0) + 1
    print(
        "manifest valid: "
        f"python={manifest['python']['expected_nodes']} dispositions={python_counts} "
        f"playwright={manifest['playwright']['expected_nodes']} source_owner_rows={browser_counts} "
        "targets=12/4/1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
