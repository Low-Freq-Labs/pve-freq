#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/media.sh
# Plex Media Stack Management
#
# Author:  FREQ Project
# -- when in doubt, check the containers --
# Commands: cmd_media
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================
# shellcheck disable=SC2154

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

# Get list of Docker media VMs — returns "label|ip" lines
# Primary: hosts.conf docker group. Fallback: known VM labels.
_media_get_vms() {
    load_hosts
    local found=false
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        if [[ "${HOST_GROUPS[$i]}" == *docker* ]]; then
            echo "${HOST_LABELS[$i]}|${HOST_IPS[$i]}"
            found=true
        fi
    done
    if ! $found; then
        # Fallback: try known media VM labels through resolver
        local label resolved ip
        for label in vm101 vm102 vm103 vm104 vm201 vm202 vm301; do
            resolved=$(freq_resolve "$label" 2>/dev/null) || continue
            ip=$(echo "$resolved" | awk '{print $1}')
            [ -n "$ip" ] && echo "${label}|${ip}"
        done
    fi
}

# SSH to a media VM using its resolve label
_media_ssh() {
    local label="$1"; shift
    freq_ssh "$label" "$*"
}

# ═══════════════════════════════════════════════════════════════════
# MAIN DISPATCH
# ═══════════════════════════════════════════════════════════════════

cmd_media() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        doctor)      _media_doctor "$@" ;;
        status)      _media_status "$@" ;;
        containers)  _media_containers "$@" ;;
        disk)        _media_disk "$@" ;;
        activity)    _media_activity "$@" ;;
        help|--help|-h) _media_help ;;
        *)
            echo -e "  ${RED}Unknown media command: ${subcmd}${RESET}"
            echo "  Run 'freq media help' for usage."
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# freq media help
# ═══════════════════════════════════════════════════════════════════

_media_help() {
    freq_header "Media Stack"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq media <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    doctor       ${DIM}${_DASH} All checks in one shot${RESET}"
    freq_line "    status       ${DIM}${_DASH} Container states across all media VMs${RESET}"
    freq_line "    containers   ${DIM}${_DASH} Full container inventory${RESET}"
    freq_line "    disk         ${DIM}${_DASH} Storage capacity${RESET}"
    freq_line "    activity     ${DIM}${_DASH} Live activity summary (downloads, streams)${RESET}"
    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# freq media doctor — comprehensive health check
# ═══════════════════════════════════════════════════════════════════

_media_doctor() {
    require_operator || return 1
    require_ssh_key

    freq_header "Media Stack Doctor"
    freq_blank

    local pass=0 warn=0 fail=0
    local vm_list
    vm_list=$(_media_get_vms)

    if [ -z "$vm_list" ]; then
        freq_line "  ${YELLOW}${_WARN}${RESET} No media VMs found in hosts.conf (docker group)."
        freq_line "  ${DIM}Run 'freq hosts add' to register Docker VMs, or 'freq init' to bootstrap.${RESET}"
        freq_blank
        freq_footer
        return 1
    fi

    # -- Container Health --
    freq_line "  ${BOLD}${WHITE}Containers${RESET}"
    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        local containers
        containers=$(_media_ssh "$label" "sudo docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null" 2>/dev/null)
        if [ -z "$containers" ]; then
            freq_line "    ${RED}${_CROSS}${RESET} ${label} (${ip}): cannot query docker"
            fail=$((fail + 1))
            continue
        fi

        local vm_ok=0 vm_bad=0
        while IFS='|' read -r cname cstatus; do
            [ -z "$cname" ] && continue
            if echo "$cstatus" | grep -qi "^Up"; then
                vm_ok=$((vm_ok + 1))
            else
                freq_line "    ${RED}${_CROSS}${RESET} ${label}/${cname}: ${cstatus}"
                vm_bad=$((vm_bad + 1))
                fail=$((fail + 1))
            fi
        done <<< "$containers"

        if [ "$vm_bad" -eq 0 ]; then
            freq_line "    ${GREEN}${_TICK}${RESET} ${label}: ${vm_ok} containers running"
            pass=$((pass + 1))
        fi
    done <<< "$vm_list"
    freq_blank

    # -- Disk Space --
    freq_line "  ${BOLD}${WHITE}Disk Space${RESET}"
    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        local usage
        usage=$(_media_ssh "$label" "df / 2>/dev/null | awk 'NR==2{gsub(/%/,\"\"); print \$5}'" 2>/dev/null)
        if [ -z "$usage" ]; then
            continue
        elif [ "$usage" -gt 90 ] 2>/dev/null; then
            freq_line "    ${RED}${_CROSS}${RESET} ${label}: ${usage}% ${_DASH} CRITICAL"
            fail=$((fail + 1))
        elif [ "$usage" -gt 80 ] 2>/dev/null; then
            freq_line "    ${YELLOW}${_WARN}${RESET} ${label}: ${usage}%"
            warn=$((warn + 1))
        else
            freq_line "    ${GREEN}${_TICK}${RESET} ${label}: ${usage}%"
            pass=$((pass + 1))
        fi
    done <<< "$vm_list"
    freq_blank

    # -- NFS Mounts --
    freq_line "  ${BOLD}${WHITE}Storage Mounts${RESET}"
    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        local nfs_count
        nfs_count=$(_media_ssh "$label" "mount 2>/dev/null | grep -c nfs" 2>/dev/null)
        nfs_count="${nfs_count:-0}"
        if [ "$nfs_count" -gt 0 ] 2>/dev/null; then
            freq_line "    ${GREEN}${_TICK}${RESET} ${label}: ${nfs_count} NFS mount(s)"
            pass=$((pass + 1))
        else
            freq_line "    ${YELLOW}${_WARN}${RESET} ${label}: no NFS mounts"
            warn=$((warn + 1))
        fi
    done <<< "$vm_list"
    freq_blank

    # -- VPN Check (Gluetun containers) --
    freq_line "  ${BOLD}${WHITE}VPN Tunnels${RESET}"
    local vpn_found=false
    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        # Check if this VM runs gluetun
        local has_gluetun
        has_gluetun=$(_media_ssh "$label" "sudo docker ps --format '{{.Names}}' 2>/dev/null | grep -c gluetun" 2>/dev/null)
        [ "${has_gluetun:-0}" -eq 0 ] && continue
        vpn_found=true

        local vpn_ip
        vpn_ip=$(_media_ssh "$label" "sudo docker exec gluetun wget -qO- http://localhost:8000/v1/publicip/ip 2>/dev/null" 2>/dev/null | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('public_ip',''))" 2>/dev/null)
        if [ -n "$vpn_ip" ]; then
            freq_line "    ${GREEN}${_TICK}${RESET} ${label}: VPN active (${vpn_ip})"
            pass=$((pass + 1))
        else
            freq_line "    ${RED}${_CROSS}${RESET} ${label}: VPN down or unreachable"
            fail=$((fail + 1))
        fi
    done <<< "$vm_list"
    if ! $vpn_found; then
        freq_line "    ${DIM}No VPN containers found${RESET}"
    fi
    freq_blank

    # -- Summary --
    freq_divider "Summary"
    freq_line "  Pass: ${GREEN}${pass}${RESET}  |  Warn: ${YELLOW}${warn}${RESET}  |  Fail: ${RED}${fail}${RESET}"
    freq_blank
    freq_footer

    log "media: doctor pass=$pass warn=$warn fail=$fail"
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# freq media status — container states across all media VMs
# ═══════════════════════════════════════════════════════════════════

_media_status() {
    require_operator || return 1
    require_ssh_key

    freq_header "Media Stack ${_DASH} Container Status"
    freq_blank

    local vm_list
    vm_list=$(_media_get_vms)

    if [ -z "$vm_list" ]; then
        freq_line "  ${YELLOW}${_WARN}${RESET} No media VMs found in hosts.conf (docker group)."
        freq_blank
        freq_footer
        return 1
    fi

    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        freq_line "  ${BOLD}${WHITE}${label}${RESET} ${DIM}(${ip})${RESET}"

        local containers
        containers=$(_media_ssh "$label" "sudo docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null" 2>/dev/null)
        if [ -z "$containers" ]; then
            freq_line "    ${DIM}unreachable or no Docker${RESET}"
            freq_blank
            continue
        fi

        while IFS='|' read -r cname cstatus; do
            [ -z "$cname" ] && continue
            local icon="${RED}${_CROSS}${RESET}"
            echo "$cstatus" | grep -qi "^Up" && icon="${GREEN}${_TICK}${RESET}"
            local short_status
            short_status=$(echo "$cstatus" | sed 's/ (.*//')
            freq_line "    ${icon} $(printf '%-20s %s' "${cname}" "${short_status}")"
        done <<< "$containers"
        freq_blank
    done <<< "$vm_list"

    freq_footer
    log "media: status viewed"
}

# ═══════════════════════════════════════════════════════════════════
# freq media containers — full container inventory
# ═══════════════════════════════════════════════════════════════════

_media_containers() {
    require_operator || return 1
    require_ssh_key

    freq_header "Media Stack ${_DASH} Container Inventory"
    freq_blank
    freq_line "  ${DIM}$(printf '%-14s %-20s %-20s %s' 'VM' 'Container' 'Status' 'Image')${RESET}"
    freq_divider ""

    local vm_list
    vm_list=$(_media_get_vms)

    if [ -z "$vm_list" ]; then
        freq_line "  ${YELLOW}${_WARN}${RESET} No media VMs found."
        freq_blank
        freq_footer
        return 1
    fi

    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        local containers
        containers=$(_media_ssh "$label" "sudo docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null" 2>/dev/null)
        [ -z "$containers" ] && continue

        while IFS='|' read -r cname cstatus cimage; do
            [ -z "$cname" ] && continue
            local short_status short_image
            short_status=$(echo "$cstatus" | sed 's/ (.*//' | head -c 18)
            short_image=$(echo "$cimage" | sed 's|.*/||' | head -c 25)
            freq_line "  $(printf '%-14s %-20s %-20s %s' "${label:0:14}" "${cname:0:20}" "${short_status}" "${short_image}")"
        done <<< "$containers"
    done <<< "$vm_list"

    freq_blank
    freq_footer
    log "media: containers viewed"
}

# ═══════════════════════════════════════════════════════════════════
# freq media disk — storage capacity
# ═══════════════════════════════════════════════════════════════════

_media_disk() {
    require_operator || return 1
    require_ssh_key

    freq_header "Media Stack ${_DASH} Storage"
    freq_blank
    freq_line "  ${DIM}$(printf '%-14s %-12s %-8s %-8s %s' 'VM' 'Mount' 'Size' 'Used' 'Avail')${RESET}"
    freq_divider ""

    local vm_list
    vm_list=$(_media_get_vms)

    if [ -z "$vm_list" ]; then
        freq_line "  ${YELLOW}${_WARN}${RESET} No media VMs found."
        freq_blank
        freq_footer
        return 1
    fi

    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        local df_out
        df_out=$(_media_ssh "$label" "df -h / /data /media 2>/dev/null | awk 'NR>1{print \$6\"|\"\$2\"|\"\$3\"|\"\$4}' | sort -u" 2>/dev/null)
        [ -z "$df_out" ] && continue

        while IFS='|' read -r mount size used avail; do
            [ -z "$mount" ] && continue
            freq_line "  $(printf '%-14s %-12s %-8s %-8s %s' "${label:0:14}" "${mount:0:12}" "$size" "$used" "$avail")"
        done <<< "$df_out"
    done <<< "$vm_list"

    freq_blank
    freq_footer
    log "media: disk viewed"
}

# ═══════════════════════════════════════════════════════════════════
# freq media activity — live activity summary
# ═══════════════════════════════════════════════════════════════════

_media_activity() {
    require_operator || return 1
    require_ssh_key

    freq_header "Media Stack ${_DASH} Live Activity"
    freq_blank

    local vm_list
    vm_list=$(_media_get_vms)

    if [ -z "$vm_list" ]; then
        freq_line "  ${YELLOW}${_WARN}${RESET} No media VMs found."
        freq_blank
        freq_footer
        return 1
    fi

    # Container summary per VM
    freq_line "  ${BOLD}${WHITE}Container Summary${RESET}"
    local total_running=0 total_containers=0
    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        local counts
        counts=$(_media_ssh "$label" "echo \"\$(sudo docker ps -q 2>/dev/null | wc -l)/\$(sudo docker ps -aq 2>/dev/null | wc -l)\"" 2>/dev/null)
        if [ -n "$counts" ]; then
            local running total
            running=$(echo "$counts" | cut -d/ -f1)
            total=$(echo "$counts" | cut -d/ -f2)
            total_running=$((total_running + running))
            total_containers=$((total_containers + total))
            local icon="${GREEN}${_TICK}${RESET}"
            [ "$running" != "$total" ] && icon="${YELLOW}${_WARN}${RESET}"
            freq_line "    ${icon} ${label}: ${running}/${total} running"
        else
            freq_line "    ${RED}${_CROSS}${RESET} ${label}: unreachable"
        fi
    done <<< "$vm_list"
    freq_line "    ${DIM}Total: ${total_running}/${total_containers} containers running${RESET}"
    freq_blank

    # NFS mount status
    freq_line "  ${BOLD}${WHITE}NFS Mounts${RESET}"
    while IFS='|' read -r label ip; do
        [ -z "$label" ] && continue
        local nfs_info
        nfs_info=$(_media_ssh "$label" "mount 2>/dev/null | grep nfs | awk '{print \$3}' | paste -sd, " 2>/dev/null)
        if [ -n "$nfs_info" ]; then
            freq_line "    ${GREEN}${_TICK}${RESET} ${label}: ${nfs_info}"
        else
            freq_line "    ${DIM}${_DASH}${RESET}  ${label}: no NFS"
        fi
    done <<< "$vm_list"
    freq_blank

    freq_footer
    log "media: activity viewed"
}
