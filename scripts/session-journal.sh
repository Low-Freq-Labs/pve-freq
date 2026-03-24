#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  session-journal.sh — Append-only daily journal for DC01 agents
#  Usage: session-journal.sh start|end|compact|precompact|entry "message"
#
#  Writes to: $HOME/memory/daily/YYYY-MM-DD.md (flat file per v3 spec)
#  Works for any agent — determines identity from $HOME.
#
#  v2 — Morty, S025. Added precompact event. Based on Rick v1 (S018).
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

AGENT=$(basename "$HOME")
# freq-ops → JARVIS
[[ "$AGENT" == "freq-ops" ]] && AGENT="jarvis"

JOURNAL_DIR="$HOME/memory/daily"
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S %Z")
JOURNAL="$JOURNAL_DIR/${TODAY}.md"

mkdir -p "$JOURNAL_DIR"

EVENT="${1:-}"
shift 2>/dev/null || true
MESSAGE="$*"

case "$EVENT" in
    start)
        {
            echo "---"
            echo "[$TIMESTAMP] SESSION START — $AGENT"
            echo "HOST: $(hostname)"
            echo "---"
        } >> "$JOURNAL"
        ;;
    end)
        {
            echo "---"
            echo "[$TIMESTAMP] SESSION END — $AGENT"
            [[ -n "$MESSAGE" ]] && echo "NOTE: $MESSAGE"
            echo "---"
        } >> "$JOURNAL"
        ;;
    compact)
        {
            echo "---"
            echo "[$TIMESTAMP] COMPACTION FIRED — $AGENT"
            echo "---"
        } >> "$JOURNAL"
        ;;
    precompact)
        {
            echo "---"
            echo "[$TIMESTAMP] PRE-COMPACT FLUSH — $AGENT"
            [[ -n "$MESSAGE" ]] && echo "CONTEXT: $MESSAGE"
            echo "---"
        } >> "$JOURNAL"
        ;;
    entry)
        if [[ -z "$MESSAGE" ]]; then
            echo "Usage: session-journal.sh entry \"message\"" >&2
            exit 1
        fi
        {
            echo "---"
            echo "[$TIMESTAMP] [$AGENT] $MESSAGE"
            echo "---"
        } >> "$JOURNAL"
        ;;
    *)
        echo "Usage: session-journal.sh {start|end|compact|precompact|entry} [message]" >&2
        exit 1
        ;;
esac
