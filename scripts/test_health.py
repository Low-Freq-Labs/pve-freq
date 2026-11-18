#!/usr/bin/env python3
"""Capture and evaluate pve-freq test-suite health without new dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from statistics import median

SCHEMA_VERSION = 2
BASELINE_SOURCE_SHA = "b94321f968d1f2601b40404c3aff242e5858ced7"
CANONICAL_RUNTIME_HOST = "VM999"
BASELINE_DENOMINATORS = {"num_statements": 52806, "num_branches": 18204}
DELIVERY_TARGETS = {
    "default_cases": 2700,
    "hard_case_ceiling": 3000,
    "reserved_cases": 300,
    "branch_ratio": 0.60,
    "statement_ratio": 0.70,
    "combined_ratio": 0.67,
    "runtime_median_seconds": 270.0,
    "runtime_hard_median_seconds": 300.0,
    "runtime_max_seconds": 330.0,
    "skipped": 0,
    "warnings": 0,
}
BROWSER_TERMINAL_OWNERS = {
    "H01": ("hermetic-dashboard.spec.js", "H01 auth and security lifecycle"),
    "H02": ("hermetic-dashboard.spec.js", "H02 one view router"),
    "H03": ("hermetic-dashboard.spec.js", "H03 read and freshness behavior"),
    "H04": ("hermetic-dashboard.spec.js", "H04 mutation safety"),
    "H05": ("hermetic-dashboard.spec.js", "H05 operator RBAC"),
    "H06": ("zero-state-web-ux.spec.js", "browser-only wizard builds an explicit fleet contract"),
    "H07": ("zero-state-web-ux.spec.js", "complete state without both durable markers"),
    "H08": ("zero-state-web-ux.spec.js", "successful empty discovery can freeze an explicit empty contract"),
    "H09": ("accessibility-semantics.spec.js", "H09 accessibility semantics"),
    "H10": ("hermetic-dashboard.spec.js", "H10 responsive shell"),
    "H11": ("hermetic-dashboard.spec.js", "H11 operator truth"),
    "H12": ("hermetic-dashboard.spec.js", "H12 terminal behavior"),
    "H13": ("hermetic-dashboard.spec.js", "H13 lab-tool proxy requests keep vault credentials out of browser request surfaces"),
    "L01": ("live-safe.spec.js", "L01 "),
    "L02": ("live-safe.spec.js", "L02 "),
    "L03": ("live-safe.spec.js", "L03 "),
    "L04": ("live-safe.spec.js", "L04 "),
    "S01": ("vm-controls-destructive.spec.js", "sandbox clone exercises VM controls"),
}
BROWSER_TERMINAL_FILE_COUNTS = {
    "accessibility-semantics.spec.js": 1,
    "hermetic-dashboard.spec.js": 9,
    "live-safe.spec.js": 4,
    "vm-controls-destructive.spec.js": 1,
    "zero-state-web-ux.spec.js": 3,
}
FROZEN_COVERAGE_IDENTITY = {
    "branch": True,
    "source": ["freq"],
    "omit": ["freq/data/*", "freq/tui/*"],
    "exclude_lines": [
        "pragma: no cover",
        "if __name__ == .__main__.",
        "raise NotImplementedError",
    ],
}
POLLUTION_CATEGORIES = {
    "git_worktree",
    "root_init_inputs",
    "project_root",
    "agent_home",
    "etc_freq",
    "persistent_temp_paths",
    "processes",
    "sockets",
    "threads",
}
CRITICAL_MODULES = {
    "freq/api/auth.py",
    "freq/api/fleet.py",
    "freq/api/terminal.py",
    "freq/api/vm.py",
    "freq/core/service_units.py",
    "freq/core/services.py",
    "freq/core/setup_contract.py",
    "freq/core/setup_discovery.py",
    "freq/core/setup_state.py",
    "freq/modules/agent_deployment.py",
    "freq/modules/fleet.py",
    "freq/modules/init_cmd.py",
    "freq/modules/selfupdate.py",
    "freq/modules/serve.py",
    "freq/modules/vm.py",
}
PUBLIC_MANIFEST = Path("tests/manifests/b94321f-public-surfaces.json")
FROZEN_MODULE_CONTRACT_SHA256 = "f3a68f994bc55508eae10dc5f56b0a0764340748e7f2337496ddcf756e58c739"
REVIEWED_MODULE_ADDITIONS_MANIFEST = Path(
    "tests/manifests/test_redesign_reviewed_module_additions.json"
)
FROZEN_REVIEWED_MODULE_ADDITIONS_SHA256 = (
    "459f64ce84e4e00229e88e83a395f65555b3141341c0fc7965965d5acf936d4f"
)
FROZEN_EFFECTIVE_MODULE_CONTRACT_SHA256 = (
    "696470bf7e80bd3184fd69d599830510806346a1e5a6b9648c32a4827cb5b411"
)
REVIEWED_PUBLIC_SURFACE_DELTAS_MANIFEST = Path(
    "tests/manifests/test_redesign_reviewed_public_surface_deltas.json"
)
FROZEN_REVIEWED_PUBLIC_SURFACE_DELTAS_SHA256 = (
    "f86d6ed1138aa3970f96140cb47c512e7cc491e42ae7d972ad7600b6690fee1e"
)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


FROZEN_COVERAGE_IDENTITY_SHA256 = _canonical_sha256(FROZEN_COVERAGE_IDENTITY)


@dataclass(frozen=True)
class CoverageMetrics:
    covered_lines: int
    num_statements: int
    covered_branches: int
    num_branches: int

    @property
    def statement_ratio(self) -> float:
        return self.covered_lines / self.num_statements if self.num_statements else 1.0

    @property
    def branch_ratio(self) -> float:
        return self.covered_branches / self.num_branches if self.num_branches else 1.0

    @property
    def combined_ratio(self) -> float:
        denominator = self.num_statements + self.num_branches
        return (self.covered_lines + self.covered_branches) / denominator if denominator else 1.0

    def as_dict(self) -> dict:
        return {
            "covered_lines": self.covered_lines,
            "num_statements": self.num_statements,
            "statement_ratio": self.statement_ratio,
            "covered_branches": self.covered_branches,
            "num_branches": self.num_branches,
            "branch_ratio": self.branch_ratio,
            "combined_ratio": self.combined_ratio,
        }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_lines(lines: list[str]) -> str:
    return hashlib.sha256("".join(f"{line}\n" for line in lines).encode()).hexdigest()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines))


def collect_python_nodeids(repo: Path, tests_root: str = "tests") -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
        tests_root,
    ]
    result = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"pytest collection failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    prefix = tests_root.rstrip("/") + "/"
    nodeids = sorted(
        line.strip() for line in result.stdout.splitlines() if line.strip().startswith(prefix) and "::" in line
    )
    if not nodeids:
        raise RuntimeError("pytest collection returned no node IDs")
    return nodeids


def collect_browser_ids(repo: Path, config: str = "playwright.config.js") -> list[str]:
    playwright = repo / "node_modules" / ".bin" / "playwright"
    if not playwright.is_file():
        raise RuntimeError(f"local Playwright binary is required; refusing install/network fallback: {playwright}")
    command = [str(playwright), "test", f"--config={config}", "--list"]
    result = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Playwright collection failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    browser_ids = sorted(
        line.strip() for line in result.stdout.splitlines() if line.lstrip().startswith("[chromium]") and "›" in line
    )
    if not browser_ids:
        raise RuntimeError("Playwright collection returned no browser IDs")
    return browser_ids


def browser_terminal_contract(browser_ids: list[str]) -> dict:
    """Resolve the terminal browser inventory to one explicit owner per node."""
    owners: list[str] = []
    file_counts: dict[str, int] = {}
    for node_id in browser_ids:
        match = re.search(r"› ([^:]+\.spec\.js):\d+:\d+ › ", node_id)
        if not match:
            raise ValueError(f"browser node ID has unknown shape: {node_id}")
        filename = match.group(1)
        leaf_title = node_id.rsplit(" › ", 1)[-1]
        matches = [
            owner
            for owner, (expected_file, title_marker) in BROWSER_TERMINAL_OWNERS.items()
            if filename == expected_file and leaf_title.startswith(title_marker)
        ]
        if len(matches) != 1:
            raise ValueError(f"browser node ID must resolve to exactly one terminal owner: {node_id}")
        owners.append(matches[0])
        file_counts[filename] = file_counts.get(filename, 0) + 1

    owners.sort()
    file_counts = dict(sorted(file_counts.items()))
    if owners != sorted(BROWSER_TERMINAL_OWNERS):
        raise ValueError("browser terminal owner inventory is missing or duplicated")
    if file_counts != BROWSER_TERMINAL_FILE_COUNTS:
        raise ValueError("browser terminal file distribution is modified")
    return {
        "owner_ids": owners,
        "owner_ids_sha256": _sha256_lines(owners),
        "file_counts": file_counts,
    }


def load_coverage_metrics(path: Path) -> CoverageMetrics:
    totals = json.loads(path.read_text())["totals"]
    return CoverageMetrics(
        covered_lines=int(totals["covered_lines"]),
        num_statements=int(totals["num_statements"]),
        covered_branches=int(totals["covered_branches"]),
        num_branches=int(totals["num_branches"]),
    )


def coverage_identity(repo: Path) -> dict:
    data = tomllib.loads((repo / "pyproject.toml").read_text())
    run = data["tool"]["coverage"]["run"]
    report = data["tool"]["coverage"]["report"]
    identity = {
        "branch": bool(run.get("branch")),
        "source": list(run.get("source", [])),
        "omit": list(run.get("omit", [])),
        "exclude_lines": list(report.get("exclude_lines", [])),
    }
    identity["sha256"] = _canonical_sha256(identity)
    return identity


def _frozen_identity() -> dict:
    return {**FROZEN_COVERAGE_IDENTITY, "sha256": FROZEN_COVERAGE_IDENTITY_SHA256}


def load_public_contract(path: Path) -> list[dict]:
    return json.loads(path.read_text())["module_contract"]


def module_contract_sha256(contract: list[dict]) -> str:
    return _canonical_sha256(contract)


def load_reviewed_module_additions(path: Path) -> dict:
    return json.loads(path.read_text())


def effective_module_contract(baseline: list[dict], changes: dict) -> list[dict]:
    retired = {retirement["path"] for retirement in changes.get("retirements", [])}
    return sorted(
        [
            *(row for row in baseline if row["path"] not in retired),
            *(addition["contract"] for addition in changes["additions"]),
        ],
        key=lambda row: row["path"],
    )


def authenticated_public_surface_deltas(repo: Path) -> dict:
    path = repo / REVIEWED_PUBLIC_SURFACE_DELTAS_MANIFEST
    if (
        not path.is_file()
        or _sha256_file(path) != FROZEN_REVIEWED_PUBLIC_SURFACE_DELTAS_SHA256
    ):
        raise ValueError("reviewed public-surface delta manifest missing or modified")
    changes = json.loads(path.read_text())
    if (
        changes.get("schema_version") != 1
        or changes.get("baseline_source_sha") != BASELINE_SOURCE_SHA
        or changes.get("retirement_review_status") != "SONNY_APPROVED"
        or changes.get("decision_source")
        != "/opt/freq-devs/shared-memory/sonny_decisions_canonical.md#cut-all-ai-code-out-of-pve-freq"
        or len(changes.get("additions", [])) != 7
        or len(changes.get("retirements", [])) != 41
        or any(row.get("review_status") != "ACCEPTED" for row in changes["additions"])
    ):
        raise ValueError("reviewed public-surface delta schema or provenance is invalid")
    addition_keys = [
        (row["surface"]["kind"], row["surface"]["name"])
        for row in changes["additions"]
    ]
    retirement_keys = [
        (row["kind"], row["name"])
        for row in changes["retirements"]
    ]
    if (
        len(addition_keys) != len(set(addition_keys))
        or len(retirement_keys) != len(set(retirement_keys))
        or set(addition_keys) & set(retirement_keys)
    ):
        raise ValueError("reviewed public-surface delta identities are invalid")
    return changes


def authenticated_effective_module_contract(repo: Path) -> tuple[dict, list[dict]]:
    additions_path = repo / REVIEWED_MODULE_ADDITIONS_MANIFEST
    if not additions_path.is_file() or _sha256_file(additions_path) != FROZEN_REVIEWED_MODULE_ADDITIONS_SHA256:
        raise ValueError("reviewed module additions manifest missing or modified")
    additions = load_reviewed_module_additions(additions_path)
    if (
        additions.get("schema_version") != 2
        or additions.get("baseline_source_sha") != BASELINE_SOURCE_SHA
        or len(additions.get("additions", [])) != 35
        or len(additions.get("retirements", [])) != 4
    ):
        raise ValueError("reviewed module additions schema or baseline is invalid")
    expected_provenance = {
        "freq/services/cert.py": "7eb00c6fc4ebe5e94a60648a846f709ec2c3b4ac",
        "freq/services/cert_management.py": "7eb00c6fc4ebe5e94a60648a846f709ec2c3b4ac",
        "freq/core/vault.py": "2beb85030ac7f8619f9477ee75d911a185a531a1",
        "freq/core/host_identity.py": "04c6978ecc71dc3d2a7e13fd33aef90406de1b20",
        "freq/core/first_admin_claim.py": "4378a9ed3588ed4bbb258402902f0a51333d5195",
        "freq/core/setup_paths.py": "89e7dc889d9709ec0ed16ec76c338554d7d58f5f",
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
    }
    additions_by_path = {
        addition.get("contract", {}).get("path"): addition
        for addition in additions["additions"]
    }
    if set(additions_by_path) != set(expected_provenance):
        raise ValueError("reviewed module addition paths are invalid")
    for path, introduced_at in expected_provenance.items():
        addition = additions_by_path[path]
        if (
            addition.get("introduced_at") != introduced_at
            or addition.get("review_status") != "ACCEPTED"
        ):
            raise ValueError("reviewed module addition provenance is invalid")

    expected_retirements = {
        "freq/jarvis/agent.py": "4821a854d65df627ee6433e6759bf0b50d5f169e",
        "freq/jarvis/gitops.py": "4821a854d65df627ee6433e6759bf0b50d5f169e",
        "freq/jarvis/learn.py": "4821a854d65df627ee6433e6759bf0b50d5f169e",
        "freq/modules/specialist.py": "4821a854d65df627ee6433e6759bf0b50d5f169e",
    }
    retirements = {row.get("path"): row for row in additions["retirements"]}
    if set(retirements) != set(expected_retirements):
        raise ValueError("reviewed module retirement paths are invalid")
    for path, retired_at in expected_retirements.items():
        retirement = retirements[path]
        if (
            retirement.get("retired_at") != retired_at
            or retirement.get("review_status") != "SONNY_APPROVED"
        ):
            raise ValueError("reviewed module retirement provenance is invalid")

    baseline = load_public_contract(repo / PUBLIC_MANIFEST)
    if module_contract_sha256(baseline) != FROZEN_MODULE_CONTRACT_SHA256:
        raise ValueError("frozen baseline module contract is modified")
    effective = effective_module_contract(baseline, additions)
    paths = [row["path"] for row in effective]
    if len(paths) != len(set(paths)) or module_contract_sha256(effective) != FROZEN_EFFECTIVE_MODULE_CONTRACT_SHA256:
        raise ValueError("effective module contract is duplicated or modified")
    return additions, effective


def load_module_coverage(path: Path, contract: list[dict]) -> list[dict]:
    data = json.loads(path.read_text())
    by_path = {row["path"]: row for row in contract}
    rows = []
    for module_path, contract_row in sorted(by_path.items()):
        details = data.get("files", {}).get(module_path)
        base = {
            "path": module_path,
            "retained_public": contract_row["classification"] in {"RETAINED", "UNKNOWN_KEEP"},
            "critical": bool(contract_row["critical"]),
        }
        if details is None:
            rows.append(
                {
                    **base,
                    "coverage_status": "OMITTED_OR_MISSING",
                    "covered_lines": None,
                    "num_statements": None,
                    "covered_branches": None,
                    "num_branches": None,
                }
            )
            continue
        summary = details["summary"]
        rows.append(
            {
                **base,
                "coverage_status": "MEASURED",
                "covered_lines": int(summary["covered_lines"]),
                "num_statements": int(summary["num_statements"]),
                "covered_branches": int(summary.get("covered_branches", 0)),
                "num_branches": int(summary.get("num_branches", 0)),
            }
        )
    return rows


def compare_pollution_snapshots(
    before: dict, after: dict, *, source_sha: str = BASELINE_SOURCE_SHA, host: str = CANONICAL_RUNTIME_HOST
) -> dict:
    if set(before) != POLLUTION_CATEGORIES or set(after) != POLLUTION_CATEGORIES:
        raise ValueError("pollution snapshots must contain every required category exactly once")
    return {
        "schema_version": 2,
        "source_sha": source_sha,
        "host": host,
        "canonical": host == CANONICAL_RUNTIME_HOST,
        "results": {
            name: {
                "before": before[name],
                "after": after[name],
                "measured": before[name] is not None and after[name] is not None,
                "clean": before[name] is not None and before[name] == after[name],
            }
            for name in sorted(POLLUTION_CATEGORIES)
        },
    }


def _append_once(failures: list[str], message: str) -> None:
    if message not in failures:
        failures.append(message)


def _module_contract_mode(metrics: dict, failures: list[str]) -> str | None:
    mode = metrics.get("module_contract_mode")
    if mode is None:
        return "baseline"
    if mode not in {"baseline", "delivery"}:
        _append_once(failures, "module contract mode is unknown")
        return None
    return mode


def _validate_provenance(metrics: dict, failures: list[str]) -> None:
    source_sha = metrics.get("source_sha")
    mode = _module_contract_mode(metrics, failures)
    if mode == "baseline" and source_sha != BASELINE_SOURCE_SHA:
        _append_once(failures, "source SHA does not match frozen baseline")
    elif mode == "delivery" and source_sha == BASELINE_SOURCE_SHA:
        _append_once(failures, "delivery source SHA must differ from frozen baseline")
    elif mode == "delivery" and (
        not isinstance(source_sha, str)
        or len(source_sha) != 40
        or any(character not in "0123456789abcdef" for character in source_sha)
    ):
        _append_once(failures, "delivery source SHA is invalid")

    coverage_provenance = metrics.get("coverage_provenance", {})
    coverage_totals = {
        key: metrics.get(key)
        for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
    }
    if (
        coverage_provenance.get("source_sha") != source_sha
        or coverage_provenance.get("canonical") is not True
        or coverage_provenance.get("clean") is not True
        or coverage_provenance.get("totals_sha256") != _canonical_sha256(coverage_totals)
        or not coverage_provenance.get("artifact_sha256")
    ):
        _append_once(failures, "coverage provenance missing, dirty, or cross-SHA")

    runtime = metrics.get("runtime", {})
    runs = runtime.get("runs", [])
    if (
        runtime.get("source_sha") != source_sha
        or runtime.get("host") != CANONICAL_RUNTIME_HOST
        or runtime.get("canonical") is not True
        or len(runs) != 3
        or any(not row.get("clean") or not isinstance(row.get("seconds"), (int, float)) for row in runs)
    ):
        _append_once(failures, "canonical runtime requires exactly three clean VM999 runs at the same SHA")

    pollution = metrics.get("pollution", {})
    pollution_results = pollution.get("results", {})
    pollution_ok = (
        pollution.get("source_sha") == source_sha
        and pollution.get("host") == CANONICAL_RUNTIME_HOST
        and pollution.get("canonical") is True
        and set(pollution_results) == POLLUTION_CATEGORIES
    )
    if pollution_ok:
        for row in pollution_results.values():
            measured = row.get("before") is not None and row.get("after") is not None
            clean = measured and row.get("before") == row.get("after")
            if row.get("measured") is not measured or row.get("clean") is not clean or not clean:
                pollution_ok = False
                break
    if not pollution_ok:
        _append_once(failures, "pollution gate missing, dirty, cross-SHA, or internally inconsistent")


def _validate_coverage_integrity(metrics: dict, failures: list[str]) -> None:
    identity = metrics.get("coverage_identity", {})
    identity_payload = {key: identity.get(key) for key in FROZEN_COVERAGE_IDENTITY}
    if identity_payload != FROZEN_COVERAGE_IDENTITY or identity.get("sha256") != _canonical_sha256(identity_payload):
        _append_once(failures, "coverage source/omit/config identity missing or modified")
    if metrics.get("baseline_coverage_identity") != _frozen_identity():
        _append_once(failures, "frozen coverage identity baseline modified")
    if metrics.get("baseline_denominators") != BASELINE_DENOMINATORS:
        _append_once(failures, "coverage denominator baseline modified")

    statements = metrics.get("num_statements")
    branches = metrics.get("num_branches")
    covered_lines = metrics.get("covered_lines")
    covered_branches = metrics.get("covered_branches")
    if not all(isinstance(value, int) and value >= 0 for value in (statements, branches, covered_lines, covered_branches)):
        _append_once(failures, "coverage absolute counts missing or invalid")
        return
    expected = CoverageMetrics(covered_lines, statements, covered_branches, branches).as_dict()
    for key in ("statement_ratio", "branch_ratio", "combined_ratio"):
        if abs(float(metrics.get(key, -1)) - expected[key]) > 1e-12:
            _append_once(failures, "coverage ratios do not match absolute counts")
            break


def _validate_module_contract(metrics: dict, failures: list[str]) -> None:
    mode = _module_contract_mode(metrics, failures)
    if mode is None:
        return

    repo = Path.cwd()
    contract = metrics.get("module_contract", [])
    contract_hash = module_contract_sha256(contract) if contract else None
    if not contract or metrics.get("module_contract_sha256") != contract_hash:
        _append_once(failures, "module contract hash missing or modified")
        return

    if mode == "baseline":
        if contract_hash != FROZEN_MODULE_CONTRACT_SHA256:
            _append_once(failures, "module contract hash missing or modified")
            return
        if (
            metrics.get("reviewed_module_additions_sha256") is not None
            or metrics.get("effective_module_contract_sha256") is not None
        ):
            _append_once(failures, "baseline module contract or mode authentication modified")
            return
        tracked_path = repo / PUBLIC_MANIFEST
        if tracked_path.is_file():
            tracked = load_public_contract(tracked_path)
            if tracked != contract or module_contract_sha256(tracked) != FROZEN_MODULE_CONTRACT_SHA256:
                _append_once(failures, "module contract differs from tracked frozen baseline")
                return
    else:
        try:
            _, expected_contract = authenticated_effective_module_contract(repo)
        except ValueError as exc:
            _append_once(failures, str(exc))
            return
        if (
            metrics.get("reviewed_module_additions_sha256")
            != FROZEN_REVIEWED_MODULE_ADDITIONS_SHA256
            or metrics.get("effective_module_contract_sha256")
            != FROZEN_EFFECTIVE_MODULE_CONTRACT_SHA256
            or contract_hash != FROZEN_EFFECTIVE_MODULE_CONTRACT_SHA256
            or contract != expected_contract
        ):
            _append_once(failures, "delivery module contract authentication missing or modified")
            return

    expected = {row["path"]: row for row in contract}
    rows = metrics.get("module_coverage", [])
    if len(rows) != len(expected) or {row.get("path") for row in rows} != set(expected):
        _append_once(failures, "module coverage contract incomplete")
        return
    for row in rows:
        contract_row = expected[row["path"]]
        retained = contract_row["classification"] in {"RETAINED", "UNKNOWN_KEEP"}
        critical = bool(contract_row["critical"])
        if row.get("retained_public") is not retained or row.get("critical") is not critical:
            _append_once(failures, f"module classification modified: {row['path']}")
            continue
        if not retained:
            continue
        if row.get("coverage_status") != "MEASURED":
            _append_once(failures, f"module coverage unavailable: {row['path']}")
            continue
        statements = row["num_statements"]
        branches = row["num_branches"]
        statement_ratio = row["covered_lines"] / statements if statements else 1.0
        branch_ratio = row["covered_branches"] / branches if branches else None
        if branches and branch_ratio < contract_row["branch_floor"]:
            _append_once(failures, f"module branch floor missed: {row['path']}")
        if not branches and statement_ratio < contract_row["zero_branch_statement_floor"]:
            _append_once(failures, f"zero-branch module statement floor missed: {row['path']}")


def _validate_browser_contract(metrics: dict, failures: list[str]) -> None:
    if metrics.get("module_contract_mode") != "delivery":
        return
    browser = metrics.get("browser", {})
    expected_owners = sorted(BROWSER_TERMINAL_OWNERS)
    owners = browser.get("owner_ids")
    if browser.get("definitions") != len(expected_owners):
        _append_once(failures, "browser terminal definition count is not exact")
    if owners != expected_owners or browser.get("owner_ids_sha256") != _sha256_lines(expected_owners):
        _append_once(failures, "browser terminal owner inventory is missing, duplicated, or modified")
    if browser.get("file_counts") != BROWSER_TERMINAL_FILE_COUNTS:
        _append_once(failures, "browser terminal file distribution is modified")
    node_ids_sha256 = browser.get("node_ids_sha256")
    if (
        not isinstance(node_ids_sha256, str)
        or len(node_ids_sha256) != 64
        or any(character not in "0123456789abcdef" for character in node_ids_sha256)
    ):
        _append_once(failures, "browser terminal node inventory hash is missing or invalid")


def evaluate(metrics: dict, targets: dict | None = None, *, delivery: bool = True) -> list[str]:
    failures: list[str] = []
    if targets is not None and targets != DELIVERY_TARGETS:
        failures.append("delivery target contract modified")
    targets = DELIVERY_TARGETS
    _validate_provenance(metrics, failures)
    _validate_coverage_integrity(metrics, failures)
    _validate_module_contract(metrics, failures)
    _validate_browser_contract(metrics, failures)

    comparisons = [
        (metrics["default_cases"] <= targets["hard_case_ceiling"], "hard case ceiling exceeded"),
        (metrics["branch_ratio"] >= targets["branch_ratio"], "raw branch ratio missed"),
        (metrics["statement_ratio"] >= targets["statement_ratio"], "statement ratio missed"),
        (metrics["combined_ratio"] >= targets["combined_ratio"], "combined ratio missed"),
        (metrics["skipped"] <= targets["skipped"], "default suite contains skips"),
        (metrics["warnings"] <= targets["warnings"], "default suite contains warnings"),
    ]
    if delivery:
        comparisons.insert(0, (metrics["default_cases"] <= targets["default_cases"], "default case delivery target exceeded"))
    for passed, message in comparisons:
        if not passed:
            _append_once(failures, message)

    runs = metrics.get("runtime", {}).get("runs", [])
    if len(runs) == 3 and all(isinstance(row.get("seconds"), (int, float)) for row in runs):
        timings = sorted(float(row["seconds"]) for row in runs)
        runtime_median = median(timings)
        if delivery and runtime_median > targets["runtime_median_seconds"]:
            _append_once(failures, "runtime delivery median exceeded")
        if runtime_median > targets["runtime_hard_median_seconds"]:
            _append_once(failures, "runtime hard median exceeded")
        if max(timings) > targets["runtime_max_seconds"]:
            _append_once(failures, "runtime maximum exceeded")
    return failures


def _git_sha(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def _load_bound_json(path: Path, source_sha: str, kind: str) -> dict:
    data = json.loads(path.read_text())
    if data.get("source_sha") != source_sha:
        raise ValueError(f"{kind} source SHA does not match checkout")
    return data


def _load_coverage_provenance(path: Path, coverage_json: Path, source_sha: str, coverage: CoverageMetrics) -> dict:
    data = _load_bound_json(path, source_sha, "coverage provenance")
    totals = {
        key: coverage.as_dict()[key]
        for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
    }
    if (
        data.get("artifact_sha256") != _sha256_file(coverage_json)
        or data.get("totals_sha256") != _canonical_sha256(totals)
        or data.get("canonical") is not True
        or data.get("clean") is not True
    ):
        raise ValueError("coverage provenance does not authenticate the canonical clean artifact")
    return data


def snapshot_module_contract(
    repo: Path, source_sha: str, public_manifest: dict, *, delivery: bool
) -> tuple[list[dict], dict]:
    contract = public_manifest.get("module_contract", [])
    if delivery:
        if source_sha == BASELINE_SOURCE_SHA:
            raise ValueError("delivery snapshot requires a nonbaseline checkout")
        _, effective = authenticated_effective_module_contract(repo)
        if contract != effective:
            raise ValueError("delivery public-surface contract differs from authenticated effective contract")
        return contract, {
            "module_contract_mode": "delivery",
            "reviewed_module_additions_sha256": FROZEN_REVIEWED_MODULE_ADDITIONS_SHA256,
            "effective_module_contract_sha256": FROZEN_EFFECTIVE_MODULE_CONTRACT_SHA256,
        }

    if source_sha != BASELINE_SOURCE_SHA:
        raise ValueError("snapshot must run against the frozen b94321f checkout unless --delivery is set")
    baseline = load_public_contract(repo / PUBLIC_MANIFEST)
    if contract != baseline or module_contract_sha256(contract) != FROZEN_MODULE_CONTRACT_SHA256:
        raise ValueError("baseline public-surface contract differs from frozen module contract")
    return contract, {}


def snapshot(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    source_sha = _git_sha(repo)
    if args.source_sha and args.source_sha != source_sha:
        raise ValueError("requested source SHA does not match checkout")
    browser_repo = args.browser_repo.resolve() if args.browser_repo else repo
    artifact_root = args.artifact_root.resolve() if args.artifact_root else repo
    python_ids_output = args.python_ids_output if args.python_ids_output.is_absolute() else repo / args.python_ids_output
    browser_ids_output = args.browser_ids_output if args.browser_ids_output.is_absolute() else repo / args.browser_ids_output
    output = args.output if args.output.is_absolute() else repo / args.output

    python_ids = collect_python_nodeids(repo, args.tests_root)
    browser_ids = collect_browser_ids(browser_repo, args.playwright_config)
    coverage = load_coverage_metrics(args.coverage_json)
    provenance = _load_coverage_provenance(args.coverage_provenance, args.coverage_json, source_sha, coverage)
    public_manifest = _load_bound_json(args.public_surface_manifest, source_sha, "public surface manifest")
    contract, contract_authentication = snapshot_module_contract(
        repo,
        source_sha,
        public_manifest,
        delivery=args.delivery,
    )
    runtime = _load_bound_json(args.runtime_report, source_sha, "runtime report")
    pollution = _load_bound_json(args.pollution_report, source_sha, "pollution report")
    _write_lines(python_ids_output, python_ids)
    _write_lines(browser_ids_output, browser_ids)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "python": {
            "default_cases": len(python_ids),
            "node_ids_file": str(python_ids_output.relative_to(artifact_root)),
            "node_ids_sha256": _sha256_lines(python_ids),
            "passed": args.passed,
            "skipped": args.skipped,
            "warnings": args.warnings,
            "runtime": runtime,
            "pollution": pollution,
        },
        "browser": {
            "definitions": len(browser_ids),
            "node_ids_file": str(browser_ids_output.relative_to(artifact_root)),
            "node_ids_sha256": _sha256_lines(browser_ids),
            **(browser_terminal_contract(browser_ids) if args.delivery else {}),
        },
        "coverage": coverage.as_dict(),
        "coverage_provenance": provenance,
        "coverage_identity": coverage_identity(repo),
        "baseline_coverage_identity": _frozen_identity(),
        "baseline_denominators": BASELINE_DENOMINATORS,
        "module_contract": contract,
        "module_contract_sha256": module_contract_sha256(contract),
        "module_coverage": load_module_coverage(args.coverage_json, contract),
        "delivery_targets": DELIVERY_TARGETS,
    }
    manifest.update(contract_authentication)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _manifest_metrics(manifest: dict) -> dict:
    metrics = {**manifest["coverage"], **manifest["python"]}
    metrics["browser"] = manifest.get("browser", {})
    for key in (
        "source_sha",
        "coverage_provenance",
        "coverage_identity",
        "baseline_coverage_identity",
        "baseline_denominators",
        "module_contract",
        "module_contract_sha256",
        "module_coverage",
        "module_contract_mode",
        "reviewed_module_additions_sha256",
        "effective_module_contract_sha256",
    ):
        metrics[key] = manifest.get(key)
    return metrics


def report(args: argparse.Namespace) -> int:
    manifest = json.loads(args.manifest.read_text())
    metrics = _manifest_metrics(manifest)
    failures = evaluate(metrics, manifest.get("delivery_targets"), delivery=not args.hard_only)
    reserve = DELIVERY_TARGETS["hard_case_ceiling"] - metrics["default_cases"]
    print(f"source_sha={manifest['source_sha']}")
    print(f"default_cases={metrics['default_cases']} reserve={reserve}")
    print(
        "coverage="
        f"statements {metrics['covered_lines']}/{metrics['num_statements']} ({metrics['statement_ratio']:.2%}), "
        f"branches {metrics['covered_branches']}/{metrics['num_branches']} ({metrics['branch_ratio']:.2%}), "
        f"combined {metrics['combined_ratio']:.2%}"
    )
    print(
        "denominator_delta="
        f"statements {metrics['num_statements'] - BASELINE_DENOMINATORS['num_statements']:+d}, "
        f"branches {metrics['num_branches'] - BASELINE_DENOMINATORS['num_branches']:+d}"
    )
    if failures:
        print("terminal_gate=BLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1 if args.enforce else 0
    print("terminal_gate=PASS")
    return 0


def pollution_report(args: argparse.Namespace) -> int:
    before = json.loads(args.before.read_text())
    after = json.loads(args.after.read_text())
    report_data = compare_pollution_snapshots(before, after, source_sha=args.source_sha, host=args.host)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report_data, indent=2, sort_keys=True) + "\n")
    dirty = [name for name, row in report_data["results"].items() if not row["measured"] or not row["clean"]]
    print(f"pollution_gate={'PASS' if not dirty else 'BLOCKED'}")
    for name in dirty:
        print(f"- {name}")
    return 1 if dirty else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("snapshot", help="capture deterministic baseline manifests")
    capture.add_argument("--repo", type=Path, default=Path.cwd())
    capture.add_argument("--browser-repo", type=Path)
    capture.add_argument("--artifact-root", type=Path)
    capture.add_argument("--source-sha")
    capture.add_argument("--tests-root", default="tests")
    capture.add_argument("--playwright-config", default="playwright.config.js")
    capture.add_argument("--coverage-json", type=Path, required=True)
    capture.add_argument("--coverage-provenance", type=Path, required=True)
    capture.add_argument("--public-surface-manifest", type=Path, required=True)
    capture.add_argument("--pollution-report", type=Path, required=True)
    capture.add_argument("--runtime-report", type=Path, required=True)
    capture.add_argument("--python-ids-output", type=Path, required=True)
    capture.add_argument("--browser-ids-output", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--passed", type=int, required=True)
    capture.add_argument("--skipped", type=int, required=True)
    capture.add_argument("--warnings", type=int, required=True)
    capture.add_argument(
        "--delivery",
        action="store_true",
        help="capture a nonbaseline delivery artifact against the authenticated effective module contract",
    )
    capture.set_defaults(func=snapshot)
    show = subparsers.add_parser("report", help="report or enforce a captured manifest")
    show.add_argument("manifest", type=Path)
    show.add_argument("--enforce", action="store_true")
    show.add_argument("--hard-only", action="store_true", help="enforce the post-delivery ceiling, not reserved headroom")
    show.set_defaults(func=report)
    pollution = subparsers.add_parser("pollution-report", help="compare required before/after pollution fingerprints")
    pollution.add_argument("--before", type=Path, required=True)
    pollution.add_argument("--after", type=Path, required=True)
    pollution.add_argument("--source-sha", default=BASELINE_SOURCE_SHA)
    pollution.add_argument("--host", default=CANONICAL_RUNTIME_HOST)
    pollution.add_argument("--output", type=Path, required=True)
    pollution.set_defaults(func=pollution_report)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
