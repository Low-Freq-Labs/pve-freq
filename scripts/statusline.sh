#!/bin/bash
# ═══════════════════════════════════════════════════════
#  FREQ DEV Statusline — Full width, everything at a glance
#  Refreshes every 30s via Claude Code statusLine config
# ═══════════════════════════════════════════════════════

# Context bar — find newest session file, estimate usage
# Auto-compact fires at ~83% of 1M tokens ≈ ~12MB jsonl
# Map 0-12MB → 0-100% so bar hits FULL right when compact triggers
FILE=$(find /home/freq-ops/dev-ops/rick/.claude/projects/-home-freq-ops-dev-ops-rick/ -maxdepth 1 -name "*.jsonl" -printf "%T@ %p\n" 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
if [ -z "$FILE" ]; then
  FILE=$(find /home/freq-ops/dev-ops/rick/.claude/projects/ -maxdepth 3 -name "*.jsonl" -not -path "*/subagents/*" -printf "%T@ %p\n" 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
fi

SIZE=$(stat -c%s "$FILE" 2>/dev/null || echo 0)
MAX=12582912  # 12MB = "full" (auto-compact threshold)
PCT=$((SIZE * 100 / MAX))
[ $PCT -gt 100 ] && PCT=100

# Build 30-char visual bar (wider = smoother progression)
WIDTH=30
FILLED=$((PCT * WIDTH / 100))
EMPTY=$((WIDTH - FILLED))
BAR=""
i=0; while [ $i -lt $FILLED ]; do BAR="${BAR}█"; i=$((i+1)); done
i=0; while [ $i -lt $EMPTY ];  do BAR="${BAR}░"; i=$((i+1)); done

# Inbox count — DECOMMISSIONED
INBOX=0  # AI-NET inbox decommissioned 2026-03-18

# Server status
SRV=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:8888/ 2>/dev/null)
[ "$SRV" = "200" ] && S="▲ UP" || S="▼ DOWN"

# Output — full width, everything
echo "RICK | FREQ DEV | VM 999 | OPUS 4.6 · 1M CTX [${BAR}] ${PCT}% | ✉ ${INBOX} | ${S}"
