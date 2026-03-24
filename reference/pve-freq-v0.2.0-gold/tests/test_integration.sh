#!/bin/bash
# =============================================================================
# PVE FREQ v0.2.0 — Integration Test Suite
# Tests the engine CLI against the actual installation
# =============================================================================
set -uo pipefail

FREQ_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
PASS=0
FAIL=0
SKIP=0

# Colors
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
DIM="\033[2m"
BOLD="\033[1m"
RESET="\033[0m"

pass() { ((PASS++)); echo -e "  ${GREEN}PASS${RESET} $1"; }
fail() { ((FAIL++)); echo -e "  ${RED}FAIL${RESET} $1: $2"; }
skip() { ((SKIP++)); echo -e "  ${YELLOW}SKIP${RESET} $1: $2"; }

echo -e "\n${BOLD}PVE FREQ v0.2.0 — Integration Tests${RESET}"
echo -e "FREQ_DIR: $FREQ_DIR"
echo -e "Date: $(date)\n"

# ─── Directory Structure ───
echo -e "${BOLD}[1] Directory Structure${RESET}"

for dir in engine engine/core engine/policies lib conf data tests; do
    if [ -d "$FREQ_DIR/$dir" ]; then
        pass "Directory exists: $dir"
    else
        fail "Directory missing: $dir" "Expected $FREQ_DIR/$dir"
    fi
done

# ─── Python Files ───
echo -e "\n${BOLD}[2] Engine Files${RESET}"

for f in \
    engine/__init__.py engine/__main__.py engine/cli.py \
    engine/core/__init__.py engine/core/types.py engine/core/transport.py \
    engine/core/resolver.py engine/core/runner.py engine/core/policy.py \
    engine/core/enforcers.py engine/core/display.py engine/core/store.py \
    engine/policies/__init__.py engine/policies/ssh_hardening.py \
    engine/policies/ntp_sync.py engine/policies/rpcbind_block.py \
    engine/policies/docker_security.py engine/policies/nfs_security.py \
    engine/policies/auto_updates.py; do
    if [ -f "$FREQ_DIR/$f" ]; then
        pass "File exists: $f"
    else
        fail "File missing: $f" "Expected $FREQ_DIR/$f"
    fi
done

# ─── Bash Layer ───
echo -e "\n${BOLD}[3] Bash Layer${RESET}"

if [ -f "$FREQ_DIR/freq" ]; then
    pass "Dispatcher exists"
else
    fail "Dispatcher missing" "$FREQ_DIR/freq"
fi

lib_count=$(ls "$FREQ_DIR/lib/"*.sh 2>/dev/null | wc -l)
if [ "$lib_count" -ge 40 ]; then
    pass "Library count: $lib_count (>= 40)"
else
    fail "Library count" "Expected >= 40, got $lib_count"
fi

# ─── Python Import Test ───
echo -e "\n${BOLD}[4] Python Import Test${RESET}"

if command -v python3 &>/dev/null; then
    pass "Python3 available: $(python3 --version 2>&1)"

    # Test engine imports
    import_result=$(cd "$FREQ_DIR" && python3 -c "
from engine.core.types import Phase, Host, CmdResult, Finding, Resource, Policy, FleetResult
from engine.core.transport import SSHTransport, PLATFORM_SSH
from engine.core.resolver import load_fleet, filter_by_scope, filter_by_labels
from engine.core.policy import PolicyStore, PolicyExecutor
from engine.core.runner import PipelineRunner
from engine.core.display import show_results, show_diff, show_policies
from engine.core.store import ResultStore
from engine.core import enforcers
print('ALL_IMPORTS_OK')
" 2>&1)

    if echo "$import_result" | grep -q "ALL_IMPORTS_OK"; then
        pass "All engine imports successful"
    else
        fail "Engine imports" "$import_result"
    fi
else
    skip "Python imports" "python3 not found"
fi

# ─── Policy Loading ───
echo -e "\n${BOLD}[5] Policy Loading${RESET}"

policy_result=$(cd "$FREQ_DIR" && python3 -c "
from engine.core.policy import PolicyStore
store = PolicyStore('$FREQ_DIR/engine/policies')
names = store.names()
print(f'POLICIES:{len(names)}:{\",\".join(sorted(names))}')
" 2>&1)

if echo "$policy_result" | grep -q "POLICIES:6:"; then
    pass "All 6 policies loaded"
    # Extract names
    policy_names=$(echo "$policy_result" | grep "POLICIES" | cut -d: -f3)
    for expected in ssh-hardening ntp-sync rpcbind-block docker-security nfs-security auto-updates; do
        if echo "$policy_names" | grep -q "$expected"; then
            pass "Policy loaded: $expected"
        else
            fail "Policy missing" "$expected"
        fi
    done
else
    fail "Policy loading" "$policy_result"
fi

# ─── Engine CLI Help ───
echo -e "\n${BOLD}[6] Engine CLI${RESET}"

cli_help=$(cd "$FREQ_DIR" && PYTHONPATH="$FREQ_DIR" python3 -m engine --help 2>&1)
if echo "$cli_help" | grep -q "freq-engine"; then
    pass "Engine CLI --help works"
else
    fail "Engine CLI --help" "$cli_help"
fi

# ─── Engine CLI: policies command ───
policies_output=$(cd "$FREQ_DIR" && PYTHONPATH="$FREQ_DIR" python3 -m engine policies --freq-dir "$FREQ_DIR" 2>&1)
if echo "$policies_output" | grep -q "ssh-hardening"; then
    pass "Engine CLI 'policies' command works"
else
    fail "Engine CLI policies" "$policies_output"
fi

# ─── Engine CLI: policies --json ───
policies_json=$(cd "$FREQ_DIR" && PYTHONPATH="$FREQ_DIR" python3 -m engine policies --freq-dir "$FREQ_DIR" --json 2>&1)
if echo "$policies_json" | python3 -m json.tool &>/dev/null; then
    pass "Engine CLI 'policies --json' returns valid JSON"
else
    fail "Engine CLI policies --json" "Invalid JSON"
fi

# ─── Engine CLI: status (no history) ───
status_output=$(cd "$FREQ_DIR" && PYTHONPATH="$FREQ_DIR" python3 -m engine status --freq-dir "$FREQ_DIR" 2>&1)
if echo "$status_output" | grep -qi "no\|history\|previous"; then
    pass "Engine CLI 'status' handles empty history"
else
    fail "Engine CLI status" "$status_output"
fi

# ─── Engine CLI: check without policy ───
check_nopolicy=$(cd "$FREQ_DIR" && PYTHONPATH="$FREQ_DIR" python3 -m engine check --freq-dir "$FREQ_DIR" 2>&1)
rc=$?
if [ $rc -ne 0 ] || echo "$check_nopolicy" | grep -qi "usage\|policy"; then
    pass "Engine CLI 'check' without policy shows usage"
else
    fail "Engine CLI check no-policy" "Expected usage message, got rc=$rc"
fi

# ─── Version Check ───
echo -e "\n${BOLD}[7] Version${RESET}"

version_result=$(cd "$FREQ_DIR" && python3 -c "from engine import __version__; print(__version__)" 2>&1)
if [ "$version_result" = "0.2.0" ]; then
    pass "Engine version: 0.2.0"
else
    fail "Engine version" "Expected 0.2.0, got $version_result"
fi

if grep -q 'FREQ_VERSION="0.2.0"' "$FREQ_DIR/conf/freq.conf"; then
    pass "freq.conf version: 0.2.0"
else
    fail "freq.conf version" "Not set to 0.2.0"
fi

# ─── Dispatcher Engine Hook ───
echo -e "\n${BOLD}[8] Dispatcher Integration${RESET}"

if grep -q '_engine_dispatch' "$FREQ_DIR/freq"; then
    pass "Dispatcher has _engine_dispatch function"
else
    fail "Dispatcher hook" "Missing _engine_dispatch"
fi

for cmd in check fix diff policies engine; do
    if grep -q "^        ${cmd})" "$FREQ_DIR/freq"; then
        pass "Dispatcher routes: $cmd"
    else
        fail "Dispatcher routing" "Missing route for: $cmd"
    fi
done

# ─── freq.conf Engine Config ───
if grep -q 'FREQ_ENGINE_ENABLED' "$FREQ_DIR/conf/freq.conf"; then
    pass "freq.conf has FREQ_ENGINE_ENABLED"
else
    fail "freq.conf" "Missing FREQ_ENGINE_ENABLED"
fi

if grep -q 'FREQ_ENGINE_MAX_PARALLEL' "$FREQ_DIR/conf/freq.conf"; then
    pass "freq.conf has FREQ_ENGINE_MAX_PARALLEL"
else
    fail "freq.conf" "Missing FREQ_ENGINE_MAX_PARALLEL"
fi

# ─── SQLite Store ───
echo -e "\n${BOLD}[9] SQLite Store${RESET}"

store_test=$(cd "$FREQ_DIR" && python3 -c "
import os, tempfile
from engine.core.store import ResultStore
from engine.core.types import FleetResult, Host, Phase

db = os.path.join(tempfile.mkdtemp(), 'test.db')
rs = ResultStore(db)

# Save a test result
result = FleetResult(
    policy='test', mode='check', duration=1.0,
    hosts=[Host(ip='10.0.0.1', label='h1', htype='linux', phase=Phase.COMPLIANT, duration=0.3)],
    total=1, compliant=1
)
run_id = rs.save(result)
last = rs.last_run('test')
detail = rs.host_detail(run_id)
history = rs.run_history(limit=5)
rs.close()
os.unlink(db)
print(f'STORE_OK:run_id={run_id}:last={last[\"policy\"]}:detail={len(detail)}:history={len(history)}')
" 2>&1)

if echo "$store_test" | grep -q "STORE_OK"; then
    pass "SQLite store: save/retrieve/history works"
else
    fail "SQLite store" "$store_test"
fi

# ─── Summary ───
echo -e "\n$BOLD════════════════════════════════════════$RESET"
TOTAL=$((PASS + FAIL + SKIP))
echo -e "  Total: $TOTAL | ${GREEN}Pass: $PASS${RESET} | ${RED}Fail: $FAIL${RESET} | ${YELLOW}Skip: $SKIP${RESET}"

if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}ALL TESTS PASSED${RESET}"
    exit 0
else
    echo -e "  ${RED}${BOLD}$FAIL TESTS FAILED${RESET}"
    exit 1
fi
