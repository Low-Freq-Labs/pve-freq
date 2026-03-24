#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  nexus-doctor — Diagnose the full NEXUS stack
#  Run this when something feels off. Checks everything.
# ═══════════════════════════════════════════════════════════════

GD='\033[38;2;234;179;8m'
DG='\033[38;5;245m'
W='\033[1;97m'
R='\033[0m'
LV='\033[38;2;63;185;80m'
DN='\033[38;2;180;30;30m'
YW='\033[38;2;234;179;8m'
PP='\033[38;2;123;47;190m'

PASS=0
WARN=0
FAIL=0
LOG="/tmp/nexus-doctor-$(date +%Y%m%d-%H%M%S).log"

_ok()   { echo -e "    ${LV}◆${R} $1"; echo "[PASS] $1" >> "$LOG"; PASS=$((PASS+1)); }
_warn() { echo -e "    ${YW}◆${R} $1"; echo "[WARN] $1" >> "$LOG"; WARN=$((WARN+1)); }
_fail() { echo -e "    ${DN}◆${R} $1"; echo "[FAIL] $1" >> "$LOG"; FAIL=$((FAIL+1)); }
_skip() { echo -e "    ${DG}·${R} $1"; echo "[SKIP] $1" >> "$LOG"; }

echo "NEXUS Doctor — $(date)" > "$LOG"
echo ""
echo -e "  ${GD}═══════════════════════════════════════════════${R}"
echo -e "  ${W}  NEXUS DOCTOR${R}  ${DG}·${R}  ${DG}diagnosing everything${R}"
echo -e "  ${GD}═══════════════════════════════════════════════${R}"
echo ""

# ── [1] Terminal State ──
echo -e "  ${GD}[1/8]${R} Terminal state..."
if stty -a 2>/dev/null | grep -q 'echo'; then
    _ok "Terminal echo is on"
else
    _fail "Terminal echo is OFF — run: stty sane"
fi
if tput cnorm 2>/dev/null; then
    _ok "Cursor visible"
else
    _warn "Could not verify cursor state"
fi
echo ""

# ── [2] NEXUS tmux session ──
echo -e "  ${GD}[2/8]${R} NEXUS tmux session..."
NEXUS_COUNT=$(tmux list-sessions 2>/dev/null | grep -c "NEXUS" || echo 0)
if [ "$NEXUS_COUNT" -eq 1 ]; then
    _ok "Exactly 1 NEXUS session running"
elif [ "$NEXUS_COUNT" -eq 0 ]; then
    _skip "No NEXUS session (not started)"
else
    _fail "$NEXUS_COUNT NEXUS sessions — duplicates! Run: nexus-stop && nexus-start"
fi
TOTAL_TMUX=$(tmux list-sessions 2>/dev/null | wc -l || echo 0)
if [ "$TOTAL_TMUX" -gt 3 ]; then
    _warn "$TOTAL_TMUX tmux sessions total — check for stale sessions"
fi
echo ""

# ── [3] Dashboard API ──
echo -e "  ${GD}[3/8]${R} Dashboard API (:8888)..."
SRV=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 1 --max-time 2 http://localhost:8888/ 2>/dev/null)
if [ "$SRV" = "200" ]; then
    _ok "Dashboard responding (HTTP 200)"
    # Check response time
    RTIME=$(curl -s -o /dev/null -w "%{time_total}" --connect-timeout 1 --max-time 2 http://localhost:8888/ 2>/dev/null)
    if (( $(echo "$RTIME > 1.0" | bc -l 2>/dev/null || echo 0) )); then
        _warn "Dashboard slow: ${RTIME}s response time"
    else
        _ok "Response time: ${RTIME}s"
    fi
else
    _skip "Dashboard not running (code: $SRV)"
fi
DASH_PIDS=$(pgrep -u "$(id -u)" -f "freq serve|python.*8888" 2>/dev/null || true)
DASH_COUNT=$(echo "$DASH_PIDS" | grep -c . 2>/dev/null || echo 0)
if [ "$DASH_COUNT" -gt 1 ]; then
    _fail "$DASH_COUNT dashboard processes — duplicates! Run: nexus-stop && nexus-start"
fi
echo ""

# ── [4] WATCHDOG ──
echo -e "  ${GD}[4/8]${R} WATCHDOG (:9900)..."
WD=$(curl -s --connect-timeout 1 --max-time 2 http://localhost:9900/api/watchdog/health 2>/dev/null)
if [ -n "$WD" ]; then
    WD_STATUS=$(echo "$WD" | python3 -c "import json,sys;print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null)
    WD_UPTIME=$(echo "$WD" | python3 -c "import json,sys;u=json.load(sys.stdin).get('uptime_sec',0);print(f'{u/3600:.1f}h')" 2>/dev/null)
    if [ "$WD_STATUS" = "healthy" ]; then
        _ok "WATCHDOG healthy (uptime: $WD_UPTIME)"
    else
        _fail "WATCHDOG status: $WD_STATUS"
    fi
    # Check plugins
    PLUGIN_ERRORS=$(echo "$WD" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for name,p in d.get('plugins',{}).items():
    if p.get('consecutive_errors',0) > 0:
        print(f'{name}: {p[\"consecutive_errors\"]} errors')
" 2>/dev/null)
    if [ -n "$PLUGIN_ERRORS" ]; then
        _warn "Plugin errors: $PLUGIN_ERRORS"
    else
        _ok "All plugins healthy"
    fi
else
    _skip "WATCHDOG not responding"
fi
echo ""

# ── [5] Comms ──
echo -e "  ${GD}[5/8]${R} Agent comms..."
# AI-NET inbox decommissioned 2026-03-18 — all comms via SendMessage (team messaging)
_ok "Comms: SendMessage (team messaging)"
echo ""

# ── [6] Fleet cache ──
echo -e "  ${GD}[6/8]${R} Fleet cache..."
if [ -f /tmp/.nexus-fleet-cache ]; then
    CACHE_AGE=$(( $(date +%s) - $(stat -c %Y /tmp/.nexus-fleet-cache 2>/dev/null || echo 0) ))
    CACHE_DATA=$(cat /tmp/.nexus-fleet-cache 2>/dev/null)
    if [ "$CACHE_AGE" -lt 300 ]; then
        _ok "Cache fresh (${CACHE_AGE}s old): $CACHE_DATA"
    elif [ "$CACHE_AGE" -lt 3600 ]; then
        _warn "Cache stale (${CACHE_AGE}s old): $CACHE_DATA"
    else
        _warn "Cache very old ($((CACHE_AGE/3600))h): $CACHE_DATA"
    fi
else
    _skip "No fleet cache — start dashboard to seed it"
fi
echo ""

# ── [7] Emergency kit ──
echo -e "  ${GD}[7/8]${R} Emergency kit..."
[ -f "$HOME/.claude/emergency/rick-essentials.tar.gz" ] && _ok "Primary: ~/.claude/emergency/" || _fail "Primary kit missing"
[ -f /opt/ai-net/rick/vault/rick-essentials.tar.gz ] && _ok "Fallback: /opt/ai-net/rick/vault/" || _warn "Fallback kit missing"
[ -f "$HOME/.claude/emergency/restore-rick.sh" ] && _ok "Restore script present" || _warn "Restore script missing"
echo ""

# ── [8] Orphan processes ──
echo -e "  ${GD}[8/8]${R} Orphan check..."
ORPHAN_NEXUS=$(pgrep -u "$(id -u)" -f "nexus-live|bash.*nexus" 2>/dev/null | wc -l || echo 0)
if [ "$ORPHAN_NEXUS" -gt 0 ] && [ "$NEXUS_COUNT" -eq 0 ]; then
    _fail "$ORPHAN_NEXUS orphan nexus processes (no session running)"
else
    _ok "No orphan processes"
fi

# ── Summary ──
echo ""
echo -e "  ${GD}═══════════════════════════════════════════════${R}"
if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
    echo -e "  ${LV}  ALL CLEAR${R}  ${DG}·${R}  ${W}${PASS} passed${R}"
elif [ "$FAIL" -eq 0 ]; then
    echo -e "  ${YW}  MOSTLY GOOD${R}  ${DG}·${R}  ${W}${PASS} passed${R}  ${DG}·${R}  ${YW}${WARN} warning(s)${R}"
else
    echo -e "  ${DN}  ISSUES FOUND${R}  ${DG}·${R}  ${W}${PASS} passed${R}  ${DG}·${R}  ${YW}${WARN} warning(s)${R}  ${DG}·${R}  ${DN}${FAIL} failed${R}"
fi
echo -e "  ${GD}═══════════════════════════════════════════════${R}"
echo ""
echo -e "    ${DG}Log saved:${R} ${W}${LOG}${R}"
echo ""
