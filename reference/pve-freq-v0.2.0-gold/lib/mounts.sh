#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/mounts.sh
# Mount Management — NFS/CIFS health, stale detection, repair
#
# -- if the mounts go down, everything goes down --
# Commands: cmd_mount
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

cmd_mount() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)   _mount_status "$@" ;;
        verify)   _mount_verify "$@" ;;
        repair)   _mount_repair "$@" ;;
        help|--help|-h) _mount_help ;;
        *)
            echo -e "  ${RED}Unknown mount command: ${subcmd}${RESET}"
            echo "  Run 'freq mount help' for usage."
            return 1
            ;;
    esac
}

_mount_help() {
    freq_header "Mount Management"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq mount <command> [host]"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    status [host]   ${DIM}${_DASH} Show NFS/CIFS mounts across fleet${RESET}"
    freq_line "    verify [host]   ${DIM}${_DASH} Check mounts for staleness${RESET}"
    freq_line "    repair [host]   ${DIM}${_DASH} Remount stale/failed mounts${RESET}"
    freq_blank
    freq_footer
}

_mount_get_targets() {
    local target="${1:-}"
    TARGET_IPS=(); TARGET_LABELS=()
    if [ -n "$target" ]; then
        local resolved ip label
        resolved=$(freq_resolve "$target" 2>/dev/null) || { echo -e "  ${RED}Cannot resolve: ${target}${RESET}"; return 1; }
        ip=$(echo "$resolved" | awk '{print $1}')
        label=$(echo "$resolved" | awk '{print $3}')
        TARGET_IPS=("$ip"); TARGET_LABELS=("$label")
    else
        load_hosts
        local i
        for ((i=0; i<HOST_COUNT; i++)); do
            # Only check linux/truenas hosts (skip pfsense, switch, idrac)
            case "${HOST_TYPES[$i]}" in
                linux|truenas)
                    TARGET_IPS+=("${HOST_IPS[$i]}")
                    TARGET_LABELS+=("${HOST_LABELS[$i]}")
                    ;;
            esac
        done
    fi
}

_mount_status() {
    require_operator || return 1
    require_ssh_key

    local target="${1:-}"
    _mount_get_targets "$target" || return 1

    freq_header "Mount Status"
    freq_blank

    local i
    for ((i=0; i<${#TARGET_IPS[@]}; i++)); do
        local label="${TARGET_LABELS[$i]}"
        freq_line "  ${BOLD}${WHITE}${label}${RESET}"

        local mount_data
        mount_data=$(freq_ssh "$label" 'grep -E "nfs|cifs|smb" /proc/mounts 2>/dev/null; echo "---FSTAB---"; grep -E "nfs|cifs|smb" /etc/fstab 2>/dev/null' 2>/dev/null)

        if [ -z "$mount_data" ]; then
            freq_line "    ${DIM}No NFS/CIFS mounts or host unreachable${RESET}"
            continue
        fi

        local in_fstab=false
        local active_count=0 fstab_count=0
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            if [ "$line" = "---FSTAB---" ]; then
                in_fstab=true
                continue
            fi
            if ! $in_fstab; then
                local src mp fstype
                read -r src mp fstype _ <<< "$line"
                freq_line "    ${GREEN}${_TICK}${RESET} ${mp} ${DIM}(${fstype} from ${src})${RESET}"
                active_count=$((active_count + 1))
            else
                local src mp fstype
                read -r src mp fstype _ <<< "$line"
                fstab_count=$((fstab_count + 1))
            fi
        done <<< "$mount_data"

        freq_line "    ${DIM}Active: ${active_count}  Fstab: ${fstab_count}${RESET}"
        freq_blank
    done

    freq_footer
    log "mount: status checked"
}

_mount_verify() {
    require_operator || return 1
    require_ssh_key

    local target="${1:-}"
    _mount_get_targets "$target" || return 1

    freq_header "Mount Verification"
    freq_blank

    local total_ok=0 total_stale=0 total_missing=0

    local i
    for ((i=0; i<${#TARGET_IPS[@]}; i++)); do
        local label="${TARGET_LABELS[$i]}"
        freq_line "  ${BOLD}${WHITE}${label}${RESET}"

        # Get active mounts and fstab entries, plus stale check
        local verify_data
        verify_data=$(freq_ssh "$label" '
            # Active NFS/CIFS mounts
            active=$(grep -E "nfs|cifs|smb" /proc/mounts 2>/dev/null | awk "{print \$2}")
            # Fstab NFS/CIFS entries
            fstab=$(grep -vE "^#|^$" /etc/fstab 2>/dev/null | grep -E "nfs|cifs|smb" | awk "{print \$2}")
            # Check each active mount for staleness
            for mp in $active; do
                if timeout 3 stat "$mp" &>/dev/null; then
                    echo "ACTIVE_OK $mp"
                else
                    echo "ACTIVE_STALE $mp"
                fi
            done
            # Check fstab entries not in active
            for mp in $fstab; do
                if ! echo "$active" | grep -qx "$mp"; then
                    echo "FSTAB_MISSING $mp"
                fi
            done
        ' 2>/dev/null)

        if [ -z "$verify_data" ]; then
            freq_line "    ${YELLOW}${_WARN}${RESET} Host unreachable"
            continue
        fi

        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local status mp
            read -r status mp <<< "$line"
            case "$status" in
                ACTIVE_OK)
                    freq_line "    ${GREEN}${_TICK}${RESET} ${mp} ${DIM}healthy${RESET}"
                    total_ok=$((total_ok + 1))
                    ;;
                ACTIVE_STALE)
                    freq_line "    ${RED}${_CROSS}${RESET} ${mp} ${DIM}STALE (stat timeout)${RESET}"
                    total_stale=$((total_stale + 1))
                    ;;
                FSTAB_MISSING)
                    freq_line "    ${YELLOW}${_WARN}${RESET} ${mp} ${DIM}in fstab but not mounted${RESET}"
                    total_missing=$((total_missing + 1))
                    ;;
            esac
        done <<< "$verify_data"

        freq_blank
    done

    freq_divider "Summary"
    freq_line "  OK: ${GREEN}${total_ok}${RESET}  Stale: ${RED}${total_stale}${RESET}  Missing: ${YELLOW}${total_missing}${RESET}"
    freq_blank
    freq_footer
    log "mount: verify ok=${total_ok} stale=${total_stale} missing=${total_missing}"
}

_mount_repair() {
    require_admin || return 1
    require_ssh_key

    local target="${1:-}"
    _mount_get_targets "$target" || return 1

    freq_header "Mount Repair"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would attempt remount of stale/missing mounts"
        freq_footer
        return 0
    fi

    local repaired=0 failed=0

    local i
    for ((i=0; i<${#TARGET_IPS[@]}; i++)); do
        local label="${TARGET_LABELS[$i]}"
        freq_line "  ${BOLD}${WHITE}${label}${RESET}"

        local repair_data
        repair_data=$(freq_ssh "$label" '
            # Find stale mounts
            for mp in $(grep -E "nfs|cifs|smb" /proc/mounts 2>/dev/null | awk "{print \$2}"); do
                if ! timeout 3 stat "$mp" &>/dev/null; then
                    echo "STALE $mp"
                fi
            done
            # Find missing fstab entries
            active=$(grep -E "nfs|cifs|smb" /proc/mounts 2>/dev/null | awk "{print \$2}")
            for mp in $(grep -vE "^#|^$" /etc/fstab 2>/dev/null | grep -E "nfs|cifs|smb" | awk "{print \$2}"); do
                if ! echo "$active" | grep -qx "$mp"; then
                    echo "MISSING $mp"
                fi
            done
        ' 2>/dev/null)

        if [ -z "$repair_data" ]; then
            freq_line "    ${DIM}No issues or host unreachable${RESET}"
            continue
        fi

        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local status mp
            read -r status mp <<< "$line"
            _step_start "Repair: ${mp} (${status})"
            case "$status" in
                STALE)
                    if freq_ssh "$label" "sudo umount -l ${mp} && sudo mount ${mp}" 2>/dev/null; then
                        _step_ok "remounted"
                        repaired=$((repaired + 1))
                    else
                        _step_fail "remount failed"
                        failed=$((failed + 1))
                    fi
                    ;;
                MISSING)
                    if freq_ssh "$label" "sudo mount ${mp}" 2>/dev/null; then
                        _step_ok "mounted"
                        repaired=$((repaired + 1))
                    else
                        _step_fail "mount failed"
                        failed=$((failed + 1))
                    fi
                    ;;
            esac
        done <<< "$repair_data"

        freq_blank
    done

    freq_divider "Result"
    freq_line "  Repaired: ${GREEN}${repaired}${RESET}  Failed: ${RED}${failed}${RESET}"
    freq_blank
    freq_footer
    log "mount: repair repaired=${repaired} failed=${failed}"
}
