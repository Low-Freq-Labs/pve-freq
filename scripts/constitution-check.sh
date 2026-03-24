#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  constitution-check.sh — Verify CLAUDE.md integrity at session start
#  Usage: constitution-check.sh [claude_md_path]
#
#  Compares SHA-256 hash of CLAUDE.md against stored reference in
#  $HOME/cold-storage/claude-md-hash.sha256
#
#  Exit codes:
#    0 — hash verified
#    1 — no hash file (warn, don't block — initial setup needed)
#    2 — hash MISMATCH (refuse to operate)
#
#  v1 — Rick, S018. Canonical version for nexus repo.
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

CLAUDE_MD="${1:-$HOME/CLAUDE.md}"
HASH_FILE="$HOME/cold-storage/claude-md-hash.sha256"

if [[ ! -f "$CLAUDE_MD" ]]; then
    echo "ERROR: CLAUDE.md not found at $CLAUDE_MD" >&2
    exit 2
fi

if [[ ! -f "$HASH_FILE" ]]; then
    echo "WARNING: No constitution hash at $HASH_FILE — run initial setup:"
    echo "  sha256sum $CLAUDE_MD | cut -d' ' -f1 > $HASH_FILE"
    exit 1
fi

EXPECTED=$(cat "$HASH_FILE" | tr -d '[:space:]')
ACTUAL=$(sha256sum "$CLAUDE_MD" | cut -d' ' -f1)

if [[ "$EXPECTED" != "$ACTUAL" ]]; then
    echo "CONSTITUTION MISMATCH — REFUSING TO OPERATE" >&2
    echo "  Expected: $EXPECTED" >&2
    echo "  Got:      $ACTUAL" >&2
    exit 2
fi

echo "Constitution verified: $ACTUAL"
