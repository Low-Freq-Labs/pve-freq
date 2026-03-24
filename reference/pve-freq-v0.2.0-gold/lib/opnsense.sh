#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/opnsense.sh
# OPNsense Firewall Management — API-driven status, rules, WireGuard, backup
#
# -- the other firewall --
# Commands: cmd_opnsense
# Dependencies: core.sh, fmt.sh
# =============================================================================

# OPNsense API config — set in freq.conf or environment
# OPNSENSE_HOST, OPNSENSE_API_KEY, OPNSENSE_API_SECRET
OPNSENSE_CACHE="${FREQ_DATA_DIR}/cache/opnsense"

cmd_opnsense() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)   _opn_status "$@" ;;
        rules)    _opn_rules "$@" ;;
        wg)       _opn_wg "$@" ;;
        backup)   _opn_backup "$@" ;;
        help|--help|-h) _opn_help ;;
        *)
            echo -e "  ${RED}Unknown opnsense command: ${subcmd}${RESET}"
            echo "  Run 'freq opnsense help' for usage."
            return 1
            ;;
    esac
}

_opn_help() {
    freq_header "OPNsense Management"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq opnsense <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    status         ${DIM}${_DASH} System status via API${RESET}"
    freq_line "    rules          ${DIM}${_DASH} List firewall rules${RESET}"
    freq_line "    wg             ${DIM}${_DASH} WireGuard tunnel status${RESET}"
    freq_line "    backup         ${DIM}${_DASH} Download config backup${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Config:${RESET} Set OPNSENSE_HOST, OPNSENSE_API_KEY, OPNSENSE_API_SECRET"
    freq_blank
    freq_footer
}

_opn_check_config() {
    if [ -z "${OPNSENSE_HOST:-}" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} OPNSENSE_HOST not set. Configure in freq.conf."
        return 1
    fi
    if [ -z "${OPNSENSE_API_KEY:-}" ] || [ -z "${OPNSENSE_API_SECRET:-}" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} OPNSENSE_API_KEY / OPNSENSE_API_SECRET not set."
        return 1
    fi
    return 0
}

_opn_api() {
    local endpoint="$1"
    local method="${2:-GET}"
    local data="${3:-}"

    local url="https://${OPNSENSE_HOST}/api/${endpoint}"
    local curl_opts=(-s -k --connect-timeout 10 --max-time 30 -u "${OPNSENSE_API_KEY}:${OPNSENSE_API_SECRET}")

    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        curl "${curl_opts[@]}" -X POST -H "Content-Type: application/json" -d "$data" "$url" 2>/dev/null
    else
        curl "${curl_opts[@]}" "$url" 2>/dev/null
    fi
}

_opn_status() {
    require_operator || return 1
    _opn_check_config || return 1

    freq_header "OPNsense Status ${_DASH} ${OPNSENSE_HOST}"
    freq_blank

    # System info
    _step_start "Fetching system info"
    local sysinfo
    sysinfo=$(_opn_api "diagnostics/system/systemInformation")

    if [ -z "$sysinfo" ] || echo "$sysinfo" | grep -q "error"; then
        _step_fail "API unreachable"
        freq_footer
        return 1
    fi
    _step_ok

    # Parse key fields (JSON without jq — best-effort grep)
    local hostname version uptime
    hostname=$(echo "$sysinfo" | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
    version=$(echo "$sysinfo" | grep -o '"firmware_version":"[^"]*"' | head -1 | cut -d'"' -f4)

    freq_line "  Hostname: ${BOLD}${hostname:-unknown}${RESET}"
    freq_line "  Firmware: ${version:-unknown}"

    # Gateway status
    _step_start "Gateway status"
    local gateways
    gateways=$(_opn_api "routes/gateway/status")
    if [ -n "$gateways" ]; then
        _step_ok
        # Count online/offline gateways
        local online offline
        online=$(echo "$gateways" | grep -o '"status_translated":"Online"' | wc -l)
        offline=$(echo "$gateways" | grep -o '"status_translated":"Offline"' | wc -l)
        freq_line "  Gateways: ${GREEN}${online} online${RESET}  ${RED}${offline} offline${RESET}"
    else
        _step_warn "no gateway data"
    fi

    # Interface stats
    _step_start "Interface status"
    local interfaces
    interfaces=$(_opn_api "diagnostics/interface/getInterfaceStatistics")
    if [ -n "$interfaces" ]; then
        _step_ok
    else
        _step_warn "no interface data"
    fi

    freq_blank
    freq_footer
    log "opnsense: status checked on ${OPNSENSE_HOST}"
}

_opn_rules() {
    require_operator || return 1
    _opn_check_config || return 1

    freq_header "OPNsense Firewall Rules"
    freq_blank

    _step_start "Fetching rules"
    local rules
    rules=$(_opn_api "firewall/filter/searchRule")

    if [ -z "$rules" ]; then
        _step_fail "API failed"
        freq_footer
        return 1
    fi
    _step_ok

    # Parse rules — count enabled/disabled
    local total enabled disabled
    total=$(echo "$rules" | grep -o '"uuid"' | wc -l)
    enabled=$(echo "$rules" | grep -o '"enabled":"1"' | wc -l)
    disabled=$((total - enabled))

    freq_line "  Total rules: ${BOLD}${total}${RESET}"
    freq_line "  Enabled: ${GREEN}${enabled}${RESET}  Disabled: ${DIM}${disabled}${RESET}"

    # Show rule descriptions
    local descriptions
    descriptions=$(echo "$rules" | grep -o '"description":"[^"]*"' | head -20 | cut -d'"' -f4)
    if [ -n "$descriptions" ]; then
        freq_blank
        freq_line "  ${BOLD}${WHITE}Recent rules:${RESET}"
        while IFS= read -r desc; do
            [ -z "$desc" ] && continue
            freq_line "    ${_BULLET} ${desc}"
        done <<< "$descriptions"
    fi

    freq_blank
    freq_footer
    log "opnsense: rules listed (${total} total)"
}

_opn_wg() {
    require_operator || return 1
    _opn_check_config || return 1

    freq_header "OPNsense WireGuard"
    freq_blank

    _step_start "Fetching WireGuard status"
    local wg_data
    wg_data=$(_opn_api "wireguard/general/getStatus")

    if [ -z "$wg_data" ]; then
        _step_fail "API failed or WireGuard not installed"
        freq_footer
        return 1
    fi
    _step_ok

    # Parse peers
    local peer_count
    peer_count=$(echo "$wg_data" | grep -o '"publicKey"' | wc -l)
    freq_line "  Peers: ${BOLD}${peer_count}${RESET}"

    # Show peer details
    local pubkeys
    pubkeys=$(echo "$wg_data" | grep -o '"publicKey":"[^"]*"' | cut -d'"' -f4)
    if [ -n "$pubkeys" ]; then
        while IFS= read -r pk; do
            [ -z "$pk" ] && continue
            freq_line "    ${_BULLET} ${pk:0:20}..."
        done <<< "$pubkeys"
    fi

    freq_blank
    freq_footer
    log "opnsense: wireguard status — ${peer_count} peers"
}

_opn_backup() {
    require_admin || return 1
    _opn_check_config || return 1

    local backup_dir="${FREQ_DATA_DIR}/backup/opnsense"
    mkdir -p "$backup_dir" 2>/dev/null

    freq_header "OPNsense Backup"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would download config backup from ${OPNSENSE_HOST}"
        freq_footer
        return 0
    fi

    local ts
    ts=$(date '+%Y%m%d-%H%M%S')
    local outfile="${backup_dir}/opnsense-${ts}.xml"

    _step_start "Downloading config backup"
    local config
    config=$(_opn_api "core/backup/download" "GET")

    if [ -n "$config" ] && [ ${#config} -gt 100 ]; then
        echo "$config" > "$outfile"
        chmod 600 "$outfile"
        local size
        size=$(du -h "$outfile" 2>/dev/null | awk '{print $1}')
        _step_ok "${size}"
        freq_line "  Saved: ${outfile}"
    else
        _step_fail "backup failed or empty response"
        freq_footer
        return 1
    fi

    freq_blank
    freq_footer
    log "opnsense: backup saved to ${outfile}"
}
