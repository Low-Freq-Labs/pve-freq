#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/resolve.sh
# ONE unified resolver — replaces 6 per-module resolvers
#
# freq_resolve <label_or_ip>   → "IP TYPE LABEL" (space-separated)
# freq_resolve_ip <label>      → just the IP (convenience)
# freq_resolve_type <label>    → just the type (convenience)
#
# Sources (in priority order):
#   1. hosts.conf (fleet registry)
#   2. PVE_NODES / PVE_NODE_NAMES (cluster)
#   3. PFSENSE_HOST, TRUENAS_IP (hardcoded appliances)
#   4. Built-in aliases (pve01, pve02, etc.)
#   5. Raw IP passthrough (if input looks like an IP)
#
# Dependencies: core.sh (variables)
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# freq_resolve — Main resolver
# Input: label, hostname, alias, or IP
# Output: "IP TYPE LABEL" to stdout
# Returns: 0 on success, 1 if unresolvable
# ═══════════════════════════════════════════════════════════════════
freq_resolve() {
    local input="$1"
    [ -z "$input" ] && return 1

    # 1. Check hosts.conf (most specific, always wins)
    if [ -f "$HOSTS_FILE" ]; then
        local match
        # Try matching by label (column 2)
        match=$(grep -v '^#' "$HOSTS_FILE" | grep -v '^$' | awk -v t="$input" '$2 == t {print $1, $3, $2; exit}')
        if [ -n "$match" ]; then
            echo "$match"
            return 0
        fi
        # Try matching by IP (column 1)
        match=$(grep -v '^#' "$HOSTS_FILE" | grep -v '^$' | awk -v t="$input" '$1 == t {print $1, $3, $2; exit}')
        if [ -n "$match" ]; then
            echo "$match"
            return 0
        fi
        # Try partial label match (e.g., "plex" matches "vm101-plex")
        match=$(grep -v '^#' "$HOSTS_FILE" | grep -v '^$' | awk -v t="$input" '$2 ~ t {print $1, $3, $2; exit}')
        if [ -n "$match" ]; then
            echo "$match"
            return 0
        fi
    fi

    # 2. Check PVE node names
    local i
    for i in "${!PVE_NODE_NAMES[@]}"; do
        if [ "${PVE_NODE_NAMES[$i]}" = "$input" ]; then
            echo "${PVE_NODES[$i]} linux ${PVE_NODE_NAMES[$i]}"
            return 0
        fi
    done

    # 3. Check hardcoded appliance aliases
    case "$input" in
        pfsense|fw|firewall)
            echo "${PFSENSE_HOST:-${PFSENSE_IP:-10.25.255.1}} pfsense pfsense"
            return 0
            ;;
        pfsense-lab|fw-lab)
            echo "${PFSENSE_LAB_IP:-10.25.255.180} pfsense pfsense-lab"
            return 0
            ;;
        truenas|nas|tn)
            echo "${TRUENAS_IP:-10.25.255.25} truenas truenas"
            return 0
            ;;
        truenas-lab|nas-lab|tn-lab)
            echo "${TRUENAS_LAB_IP:-10.25.255.181} truenas truenas-lab"
            return 0
            ;;
        switch|switch01|sw)
            echo "10.25.255.5 switch switch01"
            return 0
            ;;
        idrac-r530)
            echo "10.25.255.10 idrac idrac-r530"
            return 0
            ;;
        idrac-t620)
            echo "10.25.255.11 idrac idrac-t620"
            return 0
            ;;
    esac

    # 4. Raw IP passthrough — if it looks like an IP, return it as linux type
    if [[ "$input" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "$input linux $input"
        return 0
    fi

    # 5. Not found
    return 1
}

# ═══════════════════════════════════════════════════════════════════
# freq_resolve_ip — Convenience: return just the IP
# ═══════════════════════════════════════════════════════════════════
freq_resolve_ip() {
    local result
    result=$(freq_resolve "$1") || return 1
    echo "$result" | awk '{print $1}'
}

# ═══════════════════════════════════════════════════════════════════
# freq_resolve_type — Convenience: return just the type
# ═══════════════════════════════════════════════════════════════════
freq_resolve_type() {
    local result
    result=$(freq_resolve "$1") || return 1
    echo "$result" | awk '{print $2}'
}

# ═══════════════════════════════════════════════════════════════════
# freq_resolve_label — Convenience: return just the label
# ═══════════════════════════════════════════════════════════════════
freq_resolve_label() {
    local result
    result=$(freq_resolve "$1") || return 1
    echo "$result" | awk '{print $3}'
}

# ═══════════════════════════════════════════════════════════════════
# load_hosts — Load hosts.conf into arrays for iteration
# Sets: HOST_IPS, HOST_LABELS, HOST_TYPES, HOST_GROUPS, HOST_COUNT
# ═══════════════════════════════════════════════════════════════════
HOST_IPS=()
HOST_LABELS=()
HOST_TYPES=()
HOST_GROUPS=()
HOST_COUNT=0

load_hosts() {
    HOST_IPS=(); HOST_LABELS=(); HOST_TYPES=(); HOST_GROUPS=(); HOST_COUNT=0
    [ ! -f "$HOSTS_FILE" ] && return

    while IFS= read -r line; do
        # Skip comments and blank lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue

        local ip label htype groups
        read -r ip label htype groups <<< "$line"
        [ -z "$ip" ] || [ -z "$label" ] && continue

        HOST_IPS+=("$ip")
        HOST_LABELS+=("$label")
        HOST_TYPES+=("${htype:-linux}")
        HOST_GROUPS+=("${groups:-}")
        HOST_COUNT=$((HOST_COUNT + 1))
    done < "$HOSTS_FILE"
}

# ═══════════════════════════════════════════════════════════════════
# hosts_in_group — Filter hosts by group membership
# Usage: hosts_in_group "docker"
# Sets: FILTERED_IPS, FILTERED_LABELS, FILTERED_TYPES, FILTERED_COUNT
# ═══════════════════════════════════════════════════════════════════
FILTERED_IPS=()
FILTERED_LABELS=()
FILTERED_TYPES=()
FILTERED_COUNT=0

hosts_in_group() {
    local target_group="$1"
    FILTERED_IPS=(); FILTERED_LABELS=(); FILTERED_TYPES=(); FILTERED_COUNT=0

    [ "$HOST_COUNT" -eq 0 ] && load_hosts

    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        if echo "${HOST_GROUPS[$i]}" | grep -qw "$target_group"; then
            FILTERED_IPS+=("${HOST_IPS[$i]}")
            FILTERED_LABELS+=("${HOST_LABELS[$i]}")
            FILTERED_TYPES+=("${HOST_TYPES[$i]}")
            FILTERED_COUNT=$((FILTERED_COUNT + 1))
        fi
    done
}
