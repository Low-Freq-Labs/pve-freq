#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/vpn.sh
# WireGuard VPN Management — peers, status, stale detection
#
# -- tunnel vision, but the good kind --
# Commands: cmd_vpn
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

cmd_vpn() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)   _vpn_status "$@" ;;
        peers)    _vpn_peers "$@" ;;
        stale)    _vpn_stale "$@" ;;
        genkey)   _vpn_genkey "$@" ;;
        help|--help|-h) _vpn_help ;;
        *)
            echo -e "  ${RED}Unknown vpn command: ${subcmd}${RESET}"
            echo "  Run 'freq vpn help' for usage."
            return 1
            ;;
    esac
}

_vpn_help() {
    freq_header "WireGuard VPN"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq vpn <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    status         ${DIM}${_DASH} Show WireGuard interface status${RESET}"
    freq_line "    peers          ${DIM}${_DASH} List all peers with handshake times${RESET}"
    freq_line "    stale          ${DIM}${_DASH} Find peers with no recent handshake${RESET}"
    freq_line "    genkey         ${DIM}${_DASH} Generate a new WireGuard keypair${RESET}"
    freq_blank
    freq_footer
}

_vpn_get_wg_data() {
    local target="${1:-pfsense}"
    local wg_data
    wg_data=$(freq_ssh "$target" "wg show all 2>/dev/null" 2>/dev/null)
    echo "$wg_data"
}

_vpn_status() {
    require_operator || return 1
    require_ssh_key

    local target="${1:-pfsense}"

    freq_header "WireGuard Status ${_DASH} ${target}"
    freq_blank

    local wg_data
    wg_data=$(_vpn_get_wg_data "$target")

    if [ -z "$wg_data" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot reach ${target} or WireGuard not running"
        freq_footer
        return 1
    fi

    local current_iface=""
    local iface_count=0 peer_count=0

    while IFS= read -r line; do
        [ -z "$line" ] && continue

        if echo "$line" | grep -q "^interface:"; then
            current_iface=$(echo "$line" | awk '{print $2}')
            iface_count=$((iface_count + 1))
            freq_line "  ${BOLD}${WHITE}Interface: ${current_iface}${RESET}"
        elif echo "$line" | grep -q "^  listening port:"; then
            local port
            port=$(echo "$line" | awk '{print $3}')
            freq_line "    Port: ${port}"
        elif echo "$line" | grep -q "^  public key:"; then
            local pubkey
            pubkey=$(echo "$line" | awk '{print $3}')
            freq_line "    PubKey: ${DIM}${pubkey:0:20}...${RESET}"
        elif echo "$line" | grep -q "^peer:"; then
            peer_count=$((peer_count + 1))
        fi
    done <<< "$wg_data"

    freq_blank
    freq_line "  Interfaces: ${iface_count}  Total Peers: ${peer_count}"
    freq_blank
    freq_footer
    log "vpn: status checked on ${target} — ${iface_count} ifaces, ${peer_count} peers"
}

_vpn_peers() {
    require_operator || return 1
    require_ssh_key

    local target="${1:-pfsense}"

    freq_header "WireGuard Peers ${_DASH} ${target}"
    freq_blank

    local wg_data
    wg_data=$(_vpn_get_wg_data "$target")

    if [ -z "$wg_data" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot reach ${target} or WireGuard not running"
        freq_footer
        return 1
    fi

    local current_iface="" peer_key="" peer_endpoint="" peer_allowed="" peer_handshake="" peer_transfer=""

    _flush_peer() {
        [ -z "$peer_key" ] && return
        local hs_display="${peer_handshake:-never}"
        local color="${GREEN}"
        # Check if handshake is stale (contains "minutes" or "hours" or "days")
        if [ "$hs_display" = "never" ]; then
            color="${RED}"
        elif echo "$hs_display" | grep -qE "hour|day"; then
            color="${YELLOW}"
        fi
        freq_line "    ${color}${_BULLET}${RESET} ${peer_key:0:16}..."
        [ -n "$peer_endpoint" ] && freq_line "      Endpoint: ${peer_endpoint}"
        [ -n "$peer_allowed" ] && freq_line "      Allowed:  ${peer_allowed}"
        freq_line "      Handshake: ${color}${hs_display}${RESET}"
        [ -n "$peer_transfer" ] && freq_line "      Transfer: ${DIM}${peer_transfer}${RESET}"
        peer_key=""; peer_endpoint=""; peer_allowed=""; peer_handshake=""; peer_transfer=""
    }

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        if echo "$line" | grep -q "^interface:"; then
            _flush_peer
            current_iface=$(echo "$line" | awk '{print $2}')
            freq_divider "${current_iface}"
        elif echo "$line" | grep -q "^peer:"; then
            _flush_peer
            peer_key=$(echo "$line" | awk '{print $2}')
        elif echo "$line" | grep -q "endpoint:"; then
            peer_endpoint=$(echo "$line" | sed 's/.*endpoint: *//')
        elif echo "$line" | grep -q "allowed ips:"; then
            peer_allowed=$(echo "$line" | sed 's/.*allowed ips: *//')
        elif echo "$line" | grep -q "latest handshake:"; then
            peer_handshake=$(echo "$line" | sed 's/.*latest handshake: *//')
        elif echo "$line" | grep -q "transfer:"; then
            peer_transfer=$(echo "$line" | sed 's/.*transfer: *//')
        fi
    done <<< "$wg_data"
    _flush_peer

    freq_blank
    freq_footer
    log "vpn: peers listed on ${target}"
}

_vpn_stale() {
    require_operator || return 1
    require_ssh_key

    local target="${1:-pfsense}"
    local threshold_min="${2:-15}"

    freq_header "Stale VPN Peers ${_DASH} >${threshold_min}min"
    freq_blank

    local wg_dump
    wg_dump=$(freq_ssh "$target" "wg show all dump 2>/dev/null" 2>/dev/null)

    if [ -z "$wg_dump" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot reach ${target} or WireGuard not running"
        freq_footer
        return 1
    fi

    local now stale_count=0
    now=$(date +%s)
    local threshold_sec=$((threshold_min * 60))

    while IFS=$'\t' read -r iface pubkey psk endpoint allowed_ips handshake_ts rx tx keepalive; do
        # Skip interface lines (4 fields)
        [ -z "$handshake_ts" ] && continue
        [ "$handshake_ts" = "0" ] && {
            freq_line "  ${RED}${_CROSS}${RESET} ${pubkey:0:16}... ${DIM}(${iface})${RESET} ${_DASH} ${RED}never connected${RESET}"
            stale_count=$((stale_count + 1))
            continue
        }
        local age=$((now - handshake_ts))
        if [ "$age" -gt "$threshold_sec" ]; then
            local age_min=$((age / 60))
            freq_line "  ${YELLOW}${_WARN}${RESET} ${pubkey:0:16}... ${DIM}(${iface})${RESET} ${_DASH} last seen ${age_min}m ago"
            stale_count=$((stale_count + 1))
        fi
    done <<< "$wg_dump"

    if [ "$stale_count" -eq 0 ]; then
        freq_line "  ${GREEN}${_TICK}${RESET} All peers healthy (handshake within ${threshold_min}min)"
    fi

    freq_blank
    freq_footer
    log "vpn: stale check — ${stale_count} stale peers"
}

_vpn_genkey() {
    freq_header "WireGuard Keypair"
    freq_blank

    if ! command -v wg &>/dev/null; then
        freq_line "  ${RED}${_CROSS}${RESET} 'wg' command not found. Install wireguard-tools."
        freq_footer
        return 1
    fi

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would generate a new WireGuard keypair"
        freq_footer
        return 0
    fi

    local privkey pubkey
    privkey=$(wg genkey 2>/dev/null)
    pubkey=$(echo "$privkey" | wg pubkey 2>/dev/null)

    freq_line "  ${BOLD}${WHITE}Private Key:${RESET} ${privkey}"
    freq_line "  ${BOLD}${WHITE}Public Key:${RESET}  ${pubkey}"
    freq_blank
    freq_line "  ${YELLOW}${_WARN}${RESET} Save the private key securely. It will not be stored by FREQ."
    freq_blank
    freq_footer
    log "vpn: keypair generated (pubkey=${pubkey:0:10}...)"
}
