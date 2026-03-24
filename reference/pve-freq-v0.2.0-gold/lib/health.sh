#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/health.sh
# Infrastructure Health Dashboard
#
# Author:  FREQ Project
# -- checking in on everyone --
# Commands: cmd_health
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================
# shellcheck disable=SC2154,SC2034

# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY
# ═══════════════════════════════════════════════════════════════════

cmd_health() {
    local brief=false
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --brief|-b) brief=true; shift ;;
            --help|-h)  _health_help; return 0 ;;
            *) echo -e "  ${RED}Unknown flag: ${1}${RESET}"; return 1 ;;
        esac
    done

    require_operator || return 1
    require_ssh_key

    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M')

    freq_header "Infrastructure Health ${_DASH} ${timestamp}"
    freq_blank

    # ── PVE Cluster ──
    _health_pve_cluster "$brief"

    # ── Storage ──
    _health_storage "$brief"

    # ── Network ──
    _health_network "$brief"

    # ── VMs ──
    if ! $brief; then
        _health_vms
    fi

    # ── Containers ──
    _health_containers "$brief"

    # ── FREQ Status ──
    _health_freq_status

    freq_footer
    log "health: dashboard viewed"
}

_health_help() {
    freq_header "Health Dashboard"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq health [options]"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Options:${RESET}"
    freq_line "    --brief, -b   ${DIM}${_DASH} Compact output${RESET}"
    freq_line "    --help, -h    ${DIM}${_DASH} Show this help${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Sections:${RESET}"
    freq_line "    PVE Cluster    ${DIM}${_DASH} Node status, RAM, CPU, uptime${RESET}"
    freq_line "    Storage        ${DIM}${_DASH} TrueNAS pools and alerts${RESET}"
    freq_line "    Network        ${DIM}${_DASH} pfSense connectivity${RESET}"
    freq_line "    VMs            ${DIM}${_DASH} VM list by PVE node${RESET}"
    freq_line "    Containers     ${DIM}${_DASH} Docker container counts${RESET}"
    freq_line "    FREQ           ${DIM}${_DASH} Vault, watch daemon${RESET}"
    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# PVE CLUSTER
# ═══════════════════════════════════════════════════════════════════

_health_pve_cluster() {
    local brief="${1:-false}"

    freq_line "  ${BOLD}${WHITE}PVE Cluster${RESET}"

    local n
    for ((n=0; n<${#PVE_NODES[@]}; n++)); do
        local nip="${PVE_NODES[$n]}"
        local nname="${PVE_NODE_NAMES[$n]}"

        # Ping check
        if ! ping -c 1 -W 2 "$nip" &>/dev/null; then
            freq_line "    ${RED}${_CROSS}${RESET} ${nname} (${nip}): PING FAIL"
            continue
        fi

        # SSH data collection — single call
        local node_data
        node_data=$(freq_ssh "$nname" '
            ram_pct=$(free | awk "/^Mem:/{printf \"%.0f\", \$3/\$2*100}")
            cpu=$(cat /proc/loadavg | awk "{print \$1}")
            cores=$(nproc)
            disk_pct=$(df / 2>/dev/null | awk "NR==2{print \$5}")
            uptime_str=$(uptime -p 2>/dev/null || echo "unknown")
            echo "RAM:${ram_pct}% LOAD:${cpu}/${cores} DISK:${disk_pct} ${uptime_str}"
        ' 2>/dev/null)

        if [ -z "$node_data" ]; then
            freq_line "    ${YELLOW}${_WARN}${RESET} ${nname} (${nip}): PING OK, SSH FAIL"
        else
            freq_line "    ${GREEN}${_TICK}${RESET} ${nname} (${nip}): ${node_data}"
        fi
    done
    freq_blank
}

# ═══════════════════════════════════════════════════════════════════
# STORAGE (TrueNAS)
# ═══════════════════════════════════════════════════════════════════

_health_storage() {
    local brief="${1:-false}"

    freq_line "  ${BOLD}${WHITE}Storage${RESET}"

    local tn_ip tn_resolved
    tn_resolved=$(freq_resolve "truenas" 2>/dev/null)
    tn_ip=$(echo "$tn_resolved" | awk '{print $1}')

    if [ -z "$tn_ip" ]; then
        freq_line "    ${DIM}TrueNAS not configured${RESET}"
        freq_blank
        return
    fi

    if ! ping -c 1 -W 2 "$tn_ip" &>/dev/null; then
        freq_line "    ${RED}${_CROSS}${RESET} TrueNAS (${tn_ip}): PING FAIL"
        freq_blank
        return
    fi

    # Single SSH call for pool status + alerts
    local tn_data
    tn_data=$(freq_ssh "truenas" '
        echo "=== POOLS ==="
        sudo zpool list -H -o name,health,cap,size,alloc,free 2>/dev/null
        echo "=== ALERTS ==="
        sudo midclt call alert.list 2>/dev/null | python3 -c "
import sys,json
try:
    alerts=json.load(sys.stdin)
    print(len(alerts))
except: print(\"0\")
" 2>/dev/null
        echo "=== VERSION ==="
        sudo midclt call system.version 2>/dev/null || cat /etc/version 2>/dev/null || echo "unknown"
    ' 2>/dev/null)

    if [ -z "$tn_data" ]; then
        freq_line "    ${YELLOW}${_WARN}${RESET} TrueNAS (${tn_ip}): PING OK, SSH FAIL"
        freq_blank
        return
    fi

    # Parse pools
    local section=""
    local pool_summary=""
    local alert_count="0"
    local tn_version=""
    while IFS= read -r line; do
        case "$line" in
            "=== POOLS ===")   section="pools" ; continue ;;
            "=== ALERTS ===")  section="alerts" ; continue ;;
            "=== VERSION ===") section="version" ; continue ;;
        esac
        case "$section" in
            pools)
                [ -z "$line" ] && continue
                local pname phealth pcap _
                read -r pname phealth pcap _ <<< "$line"
                local color="${GREEN}"
                [ "$phealth" = "DEGRADED" ] && color="${YELLOW}"
                [ "$phealth" = "FAULTED" ] && color="${RED}"
                pool_summary="${pool_summary}${pname}:${color}${phealth}${RESET}:${pcap} "
                ;;
            alerts)
                [ -n "$line" ] && alert_count="$line"
                ;;
            version)
                [ -n "$line" ] && tn_version="$line"
                ;;
        esac
    done <<< "$tn_data"

    local alert_color="${GREEN}"
    [ "${alert_count:-0}" -gt 0 ] && alert_color="${YELLOW}"

    freq_line "    ${GREEN}${_TICK}${RESET} TrueNAS (${tn_ip}): ${tn_version}"
    if [ -n "$pool_summary" ]; then
        freq_line "      Pools: ${pool_summary}"
    fi
    freq_line "      Alerts: ${alert_color}${alert_count}${RESET}"
    freq_blank
}

# ═══════════════════════════════════════════════════════════════════
# NETWORK
# ═══════════════════════════════════════════════════════════════════

_health_network() {
    local brief="${1:-false}"

    freq_line "  ${BOLD}${WHITE}Network${RESET}"

    local pf_ip pf_resolved
    pf_resolved=$(freq_resolve "pfsense" 2>/dev/null)
    pf_ip=$(echo "$pf_resolved" | awk '{print $1}')

    if [ -z "$pf_ip" ]; then
        freq_line "    ${DIM}pfSense not configured${RESET}"
        freq_blank
        return
    fi

    if ping -c 1 -W 2 "$pf_ip" &>/dev/null; then
        freq_line "    ${GREEN}${_TICK}${RESET} pfSense (${pf_ip}): PING OK"
    else
        freq_line "    ${RED}${_CROSS}${RESET} pfSense (${pf_ip}): PING FAIL"
    fi

    # Switch check
    local sw_ip sw_resolved
    sw_resolved=$(freq_resolve "switch" 2>/dev/null)
    sw_ip=$(echo "$sw_resolved" | awk '{print $1}')

    if [ -n "$sw_ip" ]; then
        if ping -c 1 -W 2 "$sw_ip" &>/dev/null; then
            freq_line "    ${GREEN}${_TICK}${RESET} Switch (${sw_ip}): PING OK"
        else
            freq_line "    ${RED}${_CROSS}${RESET} Switch (${sw_ip}): PING FAIL"
        fi
    fi

    freq_blank
}

# ═══════════════════════════════════════════════════════════════════
# VMs (by PVE node)
# ═══════════════════════════════════════════════════════════════════

_health_vms() {
    freq_line "  ${BOLD}${WHITE}VMs (by node)${RESET}"

    local n
    for ((n=0; n<${#PVE_NODES[@]}; n++)); do
        local nip="${PVE_NODES[$n]}"
        local nname="${PVE_NODE_NAMES[$n]}"

        freq_line "    ${DIM}${nname}:${RESET}"

        local vm_list
        vm_list=$(freq_ssh "$nname" 'sudo qm list 2>/dev/null | tail -n+2' 2>/dev/null)

        if [ -z "$vm_list" ]; then
            freq_line "      ${DIM}(unreachable)${RESET}"
            continue
        fi

        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local vmid vmname vmstatus
            read -r vmid vmname vmstatus _ <<< "$line"
            local color="${DIM}"
            [ "$vmstatus" = "running" ] && color="${GREEN}"
            [ "$vmstatus" = "stopped" ] && color="${RED}"
            freq_line "      ${color}${vmid} ${vmname} ${vmstatus}${RESET}"
        done <<< "$vm_list"
    done
    freq_blank
}

# ═══════════════════════════════════════════════════════════════════
# CONTAINERS
# ═══════════════════════════════════════════════════════════════════

_health_containers() {
    local brief="${1:-false}"

    freq_line "  ${BOLD}${WHITE}Containers${RESET}"

    load_hosts
    local found=false
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        [[ "${HOST_GROUPS[$i]}" == *docker* ]] || continue
        found=true

        local label="${HOST_LABELS[$i]}"
        local ip="${HOST_IPS[$i]}"

        local counts
        counts=$(freq_ssh "$label" 'echo "$(sudo docker ps -q 2>/dev/null | wc -l)/$(sudo docker ps -aq 2>/dev/null | wc -l)"' 2>/dev/null)

        if [ -n "$counts" ]; then
            local running total
            running=$(echo "$counts" | cut -d/ -f1)
            total=$(echo "$counts" | cut -d/ -f2)
            if [ "$running" = "$total" ]; then
                freq_line "    ${GREEN}${_TICK}${RESET} ${label}: ${counts} running"
            else
                local stopped=$((total - running))
                freq_line "    ${YELLOW}${_WARN}${RESET} ${label}: ${counts} running (${stopped} stopped)"
            fi
        else
            freq_line "    ${RED}${_CROSS}${RESET} ${label}: unreachable"
        fi
    done

    if ! $found; then
        freq_line "    ${DIM}No docker hosts in hosts.conf${RESET}"
    fi
    freq_blank
}

# ═══════════════════════════════════════════════════════════════════
# FREQ STATUS
# ═══════════════════════════════════════════════════════════════════

_health_freq_status() {
    freq_line "  ${BOLD}${WHITE}FREQ${RESET}"

    # Vault
    local vault_count=0
    if [ -f "${VAULT_FILE:-}" ]; then
        vault_count=$(vault_list 2>/dev/null | grep -c . 2>/dev/null || echo 0)
        freq_line "    Vault: ${vault_count} entries"
    else
        freq_line "    Vault: ${DIM}not initialized${RESET}"
    fi

    # Watch daemon
    if crontab -l 2>/dev/null | grep -q "freq watch"; then
        freq_line "    Watch: ${GREEN}RUNNING${RESET}"
    else
        freq_line "    Watch: ${DIM}stopped${RESET}"
    fi

    # Version
    freq_line "    Version: ${FREQ_VERSION:-unknown}"

    freq_blank
}
