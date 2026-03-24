#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# shellcheck disable=SC2034
# PVE FREQ v2.0.0 -- lib/personality.sh
# Delight layer: celebrations, vibes, MOTD, taglines, time savings
#
# -- the vibe is not optional. it's the product. --
#
# Pack-based personality system:
#   - Loads from conf/personality/${FREQ_BUILD}.conf
#   - Falls back to clean minimal defaults if no pack
#   - FREQ_BUILD set in freq.conf (default: none = no pack)
#   - Drop any .conf pack into conf/personality/ and set FREQ_BUILD
#
# Dependencies: core.sh (colors, symbols)
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# PERSONALITY PACK LOADER
# ═══════════════════════════════════════════════════════════════════
_FREQ_PACK_DIR="${FREQ_DIR}/conf/personality"
_FREQ_ACTIVE_PACK="${_FREQ_PACK_DIR}/${FREQ_BUILD:-personal}.conf"

if [ -f "$_FREQ_ACTIVE_PACK" ]; then
    # shellcheck source=/dev/null
    . "$_FREQ_ACTIVE_PACK"
else
    # No pack — clean functional defaults. No flair. Just the tool.
    PACK_NAME="none"
    PACK_SUBTITLE="PVE Infrastructure Platform"
    PACK_VIBE_ENABLED=false
    PACK_VIBE_PROBABILITY=100
    PACK_CELEBRATIONS=(
        "Done."
        "Complete."
        "Applied."
    )
    PACK_PREMIER_CREATE="VM created."
    PACK_PREMIER_CLONE="VM cloned."
    PACK_PREMIER_MIGRATE="Migration complete."
    PACK_PREMIER_BOOTSTRAP="Host bootstrapped."
    PACK_PREMIER_DESTROY="VM removed."
    PACK_PREMIER_SNAPSHOT="Snapshot taken."
    PACK_PREMIER_AUDIT="Audit complete."
    PACK_PREMIER_HARDEN="Hardening applied."
    PACK_PREMIER_FIX="Policy enforced."
    PACK_TAGLINES=(
        "Proxmox fleet management"
        "Infrastructure CLI"
    )
    PACK_QUOTES=(
        '"Ready." -- PVE FREQ'
    )
    PACK_VIBE_COMMON=()
    PACK_VIBE_RARE=()
    PACK_VIBE_LEGENDARY=()
    PACK_DASHBOARD_HEADER="Dashboard"
fi

# ═══════════════════════════════════════════════════════════════════
# MAP PACK DATA → INTERNAL ARRAYS
# ═══════════════════════════════════════════════════════════════════
_FREQ_CELEBRATIONS=("${PACK_CELEBRATIONS[@]}")

declare -A _FREQ_PREMIER_MSGS=(
    [create]="${PACK_PREMIER_CREATE:-}"
    [clone]="${PACK_PREMIER_CLONE:-}"
    [migrate]="${PACK_PREMIER_MIGRATE:-}"
    [bootstrap]="${PACK_PREMIER_BOOTSTRAP:-}"
    [destroy]="${PACK_PREMIER_DESTROY:-}"
    [snapshot]="${PACK_PREMIER_SNAPSHOT:-}"
    [audit]="${PACK_PREMIER_AUDIT:-}"
    [harden]="${PACK_PREMIER_HARDEN:-}"
    [fix]="${PACK_PREMIER_FIX:-}"
)

_FREQ_TAGLINES=("${PACK_TAGLINES[@]}")
FREQ_QUOTES=("${PACK_QUOTES[@]}")

# Auto-rotate index (no repeats until pool exhausted)
_CELEBRATE_IDX=0

# ═══════════════════════════════════════════════════════════════════
# DELIGHT LAYER — Celebration on successful operations
# ═══════════════════════════════════════════════════════════════════
freq_celebrate() {
    local operation="${1:-}"
    local msg=""

    # Check for premier message first (operation-specific)
    if [ -n "$operation" ] && [ -n "${_FREQ_PREMIER_MSGS[$operation]:-}" ]; then
        msg="${_FREQ_PREMIER_MSGS[$operation]}"
    else
        # Auto-rotate through celebration pool (no repeats until exhausted)
        local pool_size=${#_FREQ_CELEBRATIONS[@]}
        if [ "$_CELEBRATE_IDX" -ge "$pool_size" ]; then
            _CELEBRATE_IDX=0
        fi
        msg="${_FREQ_CELEBRATIONS[$_CELEBRATE_IDX]}"
        _CELEBRATE_IDX=$((_CELEBRATE_IDX + 1))
    fi

    echo ""
    echo -e "    ${PURPLE}${_SPARKLE}${RESET}  ${DIM}${msg}${RESET}"
}

# ═══════════════════════════════════════════════════════════════════
# THE VIBE — rare random drops for the operator who shows up every day
# Probability: 1 in PACK_VIBE_PROBABILITY per command (47 = ~2%)
# Tiers: common (60%), rare (25%), legendary (15%)
# ═══════════════════════════════════════════════════════════════════
_freq_vibe() {
    [[ "${PACK_VIBE_ENABLED:-false}" != "true" ]] && return 0
    [ -t 1 ] || return 0  # Only on interactive terminals

    local prob=${PACK_VIBE_PROBABILITY:-47}
    local roll=$((RANDOM % prob))
    [ $roll -ne 0 ] && return 0

    local tier=$((RANDOM % 100))
    local idx

    if [ $tier -lt 60 ] && [ ${#PACK_VIBE_COMMON[@]} -gt 0 ]; then
        idx=$((RANDOM % ${#PACK_VIBE_COMMON[@]}))
        echo ""
        echo -e "${PURPLEDIM:-${DIM}}${PACK_VIBE_COMMON[$idx]}${RESET}"
        echo ""

    elif [ $tier -lt 85 ] && [ ${#PACK_VIBE_RARE[@]} -gt 0 ]; then
        idx=$((RANDOM % ${#PACK_VIBE_RARE[@]}))
        echo ""
        echo -e "${PURPLEDIM:-${DIM}}${PACK_VIBE_RARE[$idx]}${RESET}"
        echo ""

    elif [ ${#PACK_VIBE_LEGENDARY[@]} -gt 0 ]; then
        idx=$((RANDOM % ${#PACK_VIBE_LEGENDARY[@]}))
        echo ""
        echo -e "${PURPLEDIM:-${DIM}}${PACK_VIBE_LEGENDARY[$idx]}${RESET}"
        echo ""
    fi
}

# ═══════════════════════════════════════════════════════════════════
# MOTD QUOTES — rotating quotes for the splash screen
# ═══════════════════════════════════════════════════════════════════
_freq_motd() {
    [ ${#FREQ_QUOTES[@]} -eq 0 ] && return
    local idx=$((RANDOM % ${#FREQ_QUOTES[@]}))
    echo -e "    ${DIM}${FREQ_QUOTES[$idx]}${RESET}"
}

# ═══════════════════════════════════════════════════════════════════
# TAGLINES — rotating taglines for splash/compact headers
# ═══════════════════════════════════════════════════════════════════
freq_tagline() {
    [ ${#_FREQ_TAGLINES[@]} -eq 0 ] && echo "-- ready --" && return
    local idx=$(( RANDOM % ${#_FREQ_TAGLINES[@]} ))
    echo "${_FREQ_TAGLINES[$idx]}"
}

# ═══════════════════════════════════════════════════════════════════
# TIME SAVED — operational efficiency callout
# ═══════════════════════════════════════════════════════════════════
freq_time_saved() {
    local ops="${1:-20}"
    [ "$ops" -le 1 ] 2>/dev/null && return
    echo -e "    ${DIM}${_DOT} ${ops} commands automated.${RESET}"
}

time_saved() { freq_time_saved "$@"; }
