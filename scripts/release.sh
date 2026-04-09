#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# FREQ Release Script — push dev to public safely
#
# Usage: ./scripts/release.sh
#
# What it does:
# 1. Verifies all commits are authored by lowfreqlabs
# 2. Strips active config files (DC01 values)
# 3. Runs tests
# 4. Pushes to public repo via HTTPS+PAT
#
# What it will NOT do:
# - Force push (unless --force is passed)
# - Push morty-ai-dev or finn-ops authored commits
# - Ship credential files, active configs, or DC01 data
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO_DIR="/data/projects/pve-freq"
PUBLIC_URL="https://github.com/Low-Freq-Labs/pve-freq.git"
PAT_FILE="/etc/freq/credentials/github-pat"
REQUIRED_AUTHOR="lowfreqlabs"
REQUIRED_EMAIL="git@lowfreqlabs.com"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

die() { echo -e "${RED}RELEASE BLOCKED: $1${NC}" >&2; exit 1; }
ok()  { echo -e "${GREEN}✔${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }

cd "$REPO_DIR" || die "Cannot cd to $REPO_DIR"

echo ""
echo "═══ FREQ Release Check ═══"
echo ""

# ── Step 1: Verify author identity on recent commits ──
echo "Checking commit identity..."
BAD_AUTHORS=$(git log --format="%an <%ae>" -20 | grep -v "$REQUIRED_AUTHOR <$REQUIRED_EMAIL>" | sort -u || true)
if [ -n "$BAD_AUTHORS" ]; then
    die "Non-lowfreqlabs commits found in last 20:\n$BAD_AUTHORS\n\nAll commits must use: $REQUIRED_AUTHOR <$REQUIRED_EMAIL>"
fi
ok "All recent commits authored by $REQUIRED_AUTHOR"

BAD_COMMITTERS=$(git log --format="%cn <%ce>" -20 | grep -v "$REQUIRED_AUTHOR <$REQUIRED_EMAIL>" | sort -u || true)
if [ -n "$BAD_COMMITTERS" ]; then
    die "Non-lowfreqlabs committers found:\n$BAD_COMMITTERS"
fi
ok "All recent commits committed by $REQUIRED_AUTHOR"

# ── Step 2: Check for credential/config leaks ──
echo ""
echo "Scanning for leaks in tracked files..."
LEAKS=$(git ls-files | xargs grep -l "ghp_\|sk-\|token_secret\s*=" 2>/dev/null | grep -v "\.example$\|test\|scripts/release" || true)
if [ -n "$LEAKS" ]; then
    die "Potential credential leak in tracked files:\n$LEAKS"
fi
ok "No credential patterns in tracked files"

# Check for active config files that shouldn't ship
for f in conf/freq.toml conf/hosts.toml conf/hosts.conf conf/vlans.toml conf/roles.conf; do
    if git ls-files --error-unmatch "$f" 2>/dev/null; then
        die "Active config file $f is tracked — should be .gitignored or removed"
    fi
done
ok "No active config files tracked"

# ── Step 3: Run tests ──
echo ""
echo "Running trust-critical tests..."
python3 -m pytest tests/test_trust_critical.py -q 2>&1 || die "Trust tests failed"
ok "Trust tests pass"

# ── Step 4: Read PAT ──
if [ ! -f "$PAT_FILE" ]; then
    die "GitHub PAT not found at $PAT_FILE"
fi
PAT=$(sudo cat "$PAT_FILE")
ok "GitHub PAT loaded"

# ── Step 5: Push ──
echo ""
echo "Pushing to public..."
PUSH_URL="https://${REQUIRED_AUTHOR}:${PAT}@github.com/Low-Freq-Labs/pve-freq.git"

if [ "${1:-}" = "--force" ]; then
    warn "Force push requested"
    git push --force "$PUSH_URL" main 2>&1
else
    git push "$PUSH_URL" main 2>&1
fi

ok "Public repo updated"
echo ""
echo "═══ Release complete ═══"
echo ""
git log --format="%h %s" -5
echo ""
