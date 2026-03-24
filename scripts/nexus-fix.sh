#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  nexus-fix — Emergency out-of-band reset
#  NO DEPENDENCIES. No colors. No curls. No python. Just bash.
#  Run this when NEXUS is completely broken.
# ═══════════════════════════════════════════════════════════════

echo ""
echo "  NEXUS EMERGENCY FIX"
echo "  ==================="
echo ""

FIXED=0

# 1. Fix terminal (most critical — if this is broken, nothing works)
echo "  [1/6] Terminal reset..."
stty sane 2>/dev/null && echo "    OK  terminal restored" || echo "    --  could not reset"
tput cnorm 2>/dev/null
tput sgr0 2>/dev/null
printf '\033[?25h'   # force cursor visible
printf '\033[0m'     # force color reset
FIXED=$((FIXED+1))

# 2. Kill ALL tmux sessions
echo "  [2/6] Killing tmux sessions..."
TMUX_COUNT=0
for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null || true); do
    tmux kill-session -t "$s" 2>/dev/null
    TMUX_COUNT=$((TMUX_COUNT+1))
done
echo "    OK  killed $TMUX_COUNT session(s)"
FIXED=$((FIXED+TMUX_COUNT))

# 3. Kill dashboard
echo "  [3/6] Killing dashboard..."
DASH=$(pgrep -u "$(id -u)" -f "freq serve|python.*8888" 2>/dev/null || true)
if [ -n "$DASH" ]; then
    echo "$DASH" | xargs kill -9 2>/dev/null || true
    echo "    OK  dashboard killed"
    FIXED=$((FIXED+1))
else
    echo "    --  not running"
fi

# 4. (AI-NET sweep removed — decommissioned 2026-03-18)
echo "  [4/6] Sweep — decommissioned, skipping"

# 5. Kill ALL orphan nexus-related processes
echo "  [5/6] Killing orphans..."
ORPHANS=$(pgrep -u "$(id -u)" -f "nexus|freq.serve" 2>/dev/null | grep -v "$$" || true)
if [ -n "$ORPHANS" ]; then
    COUNT=$(echo "$ORPHANS" | wc -l)
    echo "$ORPHANS" | xargs kill -9 2>/dev/null || true
    echo "    OK  killed $COUNT orphan(s)"
    FIXED=$((FIXED+COUNT))
else
    echo "    --  no orphans"
fi

# 6. Verify clean state
echo "  [6/6] Verify..."
REMAINING=$(tmux list-sessions 2>/dev/null | wc -l || echo 0)
if [ "$REMAINING" -eq 0 ]; then
    echo "    OK  no tmux sessions"
else
    echo "    !!  $REMAINING tmux sessions still alive"
fi

PROCS=$(pgrep -u "$(id -u)" -f "nexus|freq.serve" 2>/dev/null | grep -v "$$" | wc -l || echo 0)
if [ "$PROCS" -eq 0 ]; then
    echo "    OK  no nexus processes"
else
    echo "    !!  $PROCS processes still alive"
fi

echo ""
echo "  ==================="
echo "  Fixed $FIXED thing(s)"
echo ""
echo "  Terminal is clean. You can type again."
echo "  Run nexus-start to go live."
echo ""

# 7. If emergency kit exists, offer restore
if [ -f /opt/ai-net/rick/vault/rick-essentials.tar.gz ]; then
    echo "  Emergency kit available at:"
    echo "    /opt/ai-net/rick/vault/rick-essentials.tar.gz"
    echo "    bash /opt/ai-net/rick/vault/restore-rick.sh"
    echo ""
fi
