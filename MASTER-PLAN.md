# PVE FREQ — Master Plan: Ship-Ready

**Author:** Morty
**Date:** 2026-03-27
**Status:** Complete (all 4 phases, 14/14 distros green)
**Goal:** Make `pve freq` installable, testable, and bulletproof on every supported distro.

---

## Current State

- **Codebase:** 86 Python files, 39,500+ LOC, 88 CLI commands — all implemented, not stubbed
- **CI:** 14 distros, all green (Debian 12/13, Ubuntu 24.04, Rocky 8/9, Alma 8/9, Fedora 40/41, Arch, openSUSE Tumbleweed, Alpine 3.19/3.20/3.21)
- **Tests:** 33 test files, 13,740 LOC — universal (no DC01 dependencies)
- **Packaging:** pyproject.toml exists (setuptools), zero external deps, `freq` entry point defined
- **Dependencies:** NONE. Pure Python stdlib. Python 3.11+ only (tomllib).

---

## Phase 1: Prove Installability in CI ✅

**Status:** Complete — commit `88b1570`, CI run `23637327220` (14/14 green)

**What:** Add CI steps that `pip install .` the package, then verify `freq --version` and `freq doctor` work.

**Delivered:**
- `pip install --no-deps .` step after Python install
- `freq --version` verification step
- `freq doctor` runs on all distros (SSH/PVE checks fail as expected, no crashes)
- Package data verified via existing CI step

---

## Phase 2: End-to-End Init Dry Run in CI ✅

**Status:** Complete — commit `7111d44`, CI run `23637424544` (14/14 green)

**What:** Add a CI test that exercises `freq init --dry-run` on every distro.

**Delivered:**
- `freq init --dry-run` step — previews init steps, exits 0 on all distros
- `freq init --check` step — validates local state, fails gracefully (no crash) in CI
- Both handle missing freq.toml (first-run scenario) cleanly

---

## Phase 3: CI Hardening ✅

**Status:** Complete — commit `518afb3`, CI run `23637531119` (14/14 green)

**What:** Update GitHub Actions dependencies and add install-from-wheel test.

**Delivered:**
- `actions/checkout@v4` → `@v5` (Node.js 24, eliminates June 2026 deprecation)
- `python3 -m build --wheel` step verifies wheel builds on all distros
- Install from built wheel + verify `freq --version` works
- `build` package added to CI dependency install

---

## Phase 4: Package Polish ✅

**Status:** Complete — pyproject.toml already had all fields; verified by Phase 3 CI

**What:** Ensure pyproject.toml metadata is complete and PyPI-ready.

**Verified:**
- All pyproject.toml fields present: name, description, version (dynamic), requires-python, license, readme, authors, keywords, classifiers
- `[project.urls]` has Homepage, Repository, Issues
- Trove classifiers cover OS, Python versions, topic
- `[tool.setuptools.package-data]` globs match all files in freq/data/
- Phase 3 CI proves wheel builds + installs + entry point resolves on all 14 distros

---

## What's NOT in This Plan

- **New features** — No new commands, modules, or UI work. Foundation first.
- **PDM migration** — pyproject.toml + setuptools works. PDM is optional polish, not blocking.
- **PyPI publishing** — Getting the package *ready* for PyPI, not publishing it. Sonny decides when to ship.
- **Docker Compose packaging** — Future phase, requires Dockerfile + compose.yml. Not blocking.
- **Documentation** — README and docs are out of scope unless Sonny asks.

---

## Execution Summary

| Phase | Commit | CI Run | Result |
|-------|--------|--------|--------|
| 1     | `88b1570` | `23637327220` | 14/14 green |
| 2     | `7111d44` | `23637424544` | 14/14 green |
| 3     | `518afb3` | `23637531119` | 14/14 green |
| 4     | N/A (already complete) | Verified by Phase 3 | 14/14 green |

All phases completed 2026-03-27 by Morty. Zero failures across all 56 distro runs (4 phases × 14 distros).
