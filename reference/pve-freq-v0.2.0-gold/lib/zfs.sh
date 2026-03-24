#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/zfs.sh
# ZFS Pool Management — health, scrub, iostat via SSH
#
# -- your data's last line of defense --
# Commands: cmd_zfs
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

cmd_zfs() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)   _zfs_status "$@" ;;
        health)   _zfs_health "$@" ;;
        scrub)    _zfs_scrub "$@" ;;
        list)     _zfs_list "$@" ;;
        iostat)   _zfs_iostat "$@" ;;
        help|--help|-h) _zfs_help ;;
        *)
            echo -e "  ${RED}Unknown zfs command: ${subcmd}${RESET}"
            echo "  Run 'freq zfs help' for usage."
            return 1
            ;;
    esac
}

_zfs_help() {
    freq_header "ZFS Management"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq zfs <command> [host]"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    status [host]   ${DIM}${_DASH} Pool status overview${RESET}"
    freq_line "    health [host]   ${DIM}${_DASH} Detailed pool health (zpool status)${RESET}"
    freq_line "    scrub [host] [pool] ${DIM}${_DASH} Start a scrub${RESET}"
    freq_line "    list [host]     ${DIM}${_DASH} List all datasets${RESET}"
    freq_line "    iostat [host]   ${DIM}${_DASH} Pool I/O statistics${RESET}"
    freq_blank
    freq_line "  ${DIM}Default host: truenas${RESET}"
    freq_blank
    freq_footer
}

_zfs_resolve_host() {
    local target="${1:-truenas}"
    local resolved
    resolved=$(freq_resolve "$target" 2>/dev/null)
    if [ -z "$resolved" ]; then
        echo -e "  ${RED}Cannot resolve host: ${target}${RESET}"
        return 1
    fi
    echo "$target"
}

_zfs_status() {
    require_operator || return 1
    require_ssh_key

    local host
    host=$(_zfs_resolve_host "${1:-truenas}") || return 1

    freq_header "ZFS Pools ${_DASH} ${host}"
    freq_blank

    local pool_data
    pool_data=$(freq_ssh "$host" "sudo zpool list -H -o name,size,alloc,free,cap,dedup,health,frag 2>/dev/null" 2>/dev/null)

    if [ -z "$pool_data" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot reach ${host} or no ZFS pools"
        freq_footer
        return 1
    fi

    freq_line "  $(printf '%-12s %8s %8s %8s %5s %6s %5s %s' 'POOL' 'SIZE' 'ALLOC' 'FREE' 'CAP' 'DEDUP' 'FRAG' 'HEALTH')"
    freq_line "  ${DIM}$(printf '%0.s-' {1..72})${RESET}"

    while IFS=$'\t' read -r name size alloc free cap dedup health frag; do
        [ -z "$name" ] && continue
        local color="${GREEN}"
        case "$health" in
            ONLINE)   color="${GREEN}" ;;
            DEGRADED) color="${YELLOW}" ;;
            FAULTED|UNAVAIL) color="${RED}" ;;
        esac
        freq_line "  $(printf '%-12s %8s %8s %8s %5s %6s %5s' "$name" "$size" "$alloc" "$free" "$cap" "$dedup" "$frag") ${color}${health}${RESET}"
    done <<< "$pool_data"

    freq_blank
    freq_footer
    log "zfs: status checked on ${host}"
}

_zfs_health() {
    require_operator || return 1
    require_ssh_key

    local host
    host=$(_zfs_resolve_host "${1:-truenas}") || return 1

    freq_header "ZFS Health ${_DASH} ${host}"
    freq_blank

    local status_data
    status_data=$(freq_ssh "$host" "sudo zpool status 2>/dev/null" 2>/dev/null)

    if [ -z "$status_data" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot reach ${host} or no ZFS pools"
        freq_footer
        return 1
    fi

    # Parse pool-by-pool
    local current_pool="" in_errors=false
    while IFS= read -r line; do
        if echo "$line" | grep -q "^  pool:"; then
            current_pool=$(echo "$line" | awk '{print $2}')
            freq_divider "${current_pool}"
        elif echo "$line" | grep -q "state:"; then
            local state
            state=$(echo "$line" | awk '{print $2}')
            local color="${GREEN}"
            [ "$state" = "DEGRADED" ] && color="${YELLOW}"
            [ "$state" = "FAULTED" ] && color="${RED}"
            freq_line "  State: ${color}${state}${RESET}"
        elif echo "$line" | grep -q "scan:"; then
            local scan_info
            scan_info=$(echo "$line" | sed 's/.*scan: //')
            freq_line "  Scan: ${DIM}${scan_info}${RESET}"
        elif echo "$line" | grep -q "errors:"; then
            local errors
            errors=$(echo "$line" | sed 's/.*errors: //')
            if echo "$errors" | grep -qi "no known"; then
                freq_line "  Errors: ${GREEN}none${RESET}"
            else
                freq_line "  Errors: ${RED}${errors}${RESET}"
            fi
        elif echo "$line" | grep -qE "DEGRADED|FAULTED|UNAVAIL|REMOVED|OFFLINE" && [ -n "$current_pool" ]; then
            freq_line "  ${RED}${_CROSS} ${line}${RESET}"
        fi
    done <<< "$status_data"

    freq_blank
    freq_footer
    log "zfs: health checked on ${host}"
}

_zfs_scrub() {
    require_admin || return 1
    require_ssh_key

    local host
    host=$(_zfs_resolve_host "${1:-truenas}") || return 1
    local pool="${2:-}"

    if [ -z "$pool" ]; then
        # Scrub all pools
        local pools
        pools=$(freq_ssh "$host" "sudo zpool list -H -o name 2>/dev/null" 2>/dev/null)
        if [ -z "$pools" ]; then
            echo -e "  ${RED}No pools found on ${host}${RESET}"
            return 1
        fi

        freq_header "ZFS Scrub All ${_DASH} ${host}"
        freq_blank

        if [ "$DRY_RUN" = "true" ]; then
            freq_line "  ${CYAN}[DRY-RUN]${RESET} Would scrub all pools on ${host}"
            freq_footer
            return 0
        fi

        while IFS= read -r p; do
            [ -z "$p" ] && continue
            _step_start "Scrub: ${p}"
            if freq_ssh "$host" "sudo zpool scrub ${p}" 2>/dev/null; then
                _step_ok "started"
            else
                _step_warn "may already be scrubbing"
            fi
        done <<< "$pools"
    else
        freq_header "ZFS Scrub ${_DASH} ${pool} on ${host}"
        freq_blank

        if [ "$DRY_RUN" = "true" ]; then
            freq_line "  ${CYAN}[DRY-RUN]${RESET} Would scrub pool '${pool}' on ${host}"
            freq_footer
            return 0
        fi

        _step_start "Scrub: ${pool}"
        if freq_ssh "$host" "sudo zpool scrub ${pool}" 2>/dev/null; then
            _step_ok "started"
        else
            _step_warn "may already be scrubbing"
        fi
    fi

    freq_blank
    freq_line "  ${DIM}Scrub runs in background. Check progress with 'freq zfs health ${host}'.${RESET}"
    freq_footer
    log "zfs: scrub started on ${host} pool=${pool:-all}"
}

_zfs_list() {
    require_operator || return 1
    require_ssh_key

    local host
    host=$(_zfs_resolve_host "${1:-truenas}") || return 1

    freq_header "ZFS Datasets ${_DASH} ${host}"
    freq_blank

    local ds_data
    ds_data=$(freq_ssh "$host" "sudo zfs list -H -o name,used,avail,refer,mountpoint 2>/dev/null | head -50" 2>/dev/null)

    if [ -z "$ds_data" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot reach ${host} or no datasets"
        freq_footer
        return 1
    fi

    freq_line "  $(printf '%-30s %8s %8s %8s %s' 'DATASET' 'USED' 'AVAIL' 'REFER' 'MOUNTPOINT')"
    freq_line "  ${DIM}$(printf '%0.s-' {1..78})${RESET}"

    local count=0
    while IFS=$'\t' read -r name used avail refer mp; do
        [ -z "$name" ] && continue
        local short_name="$name"
        [ ${#short_name} -gt 30 ] && short_name="...${short_name: -27}"
        freq_line "  $(printf '%-30s %8s %8s %8s %s' "$short_name" "$used" "$avail" "$refer" "$mp")"
        count=$((count + 1))
    done <<< "$ds_data"

    freq_blank
    freq_line "  ${DIM}Showing ${count} datasets (max 50)${RESET}"
    freq_footer
    log "zfs: list ${count} datasets on ${host}"
}

_zfs_iostat() {
    require_operator || return 1
    require_ssh_key

    local host
    host=$(_zfs_resolve_host "${1:-truenas}") || return 1

    freq_header "ZFS I/O Stats ${_DASH} ${host}"
    freq_blank

    local io_data
    io_data=$(freq_ssh "$host" "sudo zpool iostat -v 2>/dev/null" 2>/dev/null)

    if [ -z "$io_data" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot reach ${host} or no pools"
        freq_footer
        return 1
    fi

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        if echo "$line" | grep -qE "^-+$"; then
            freq_line "  ${DIM}${line}${RESET}"
        elif echo "$line" | grep -qE "^\s*(pool|NAME)"; then
            freq_line "  ${BOLD}${line}${RESET}"
        else
            freq_line "  ${line}"
        fi
    done <<< "$io_data"

    freq_blank
    freq_footer
    log "zfs: iostat viewed on ${host}"
}
