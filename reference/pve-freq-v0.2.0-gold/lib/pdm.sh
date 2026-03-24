#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/pdm.sh
# Proxmox Datacenter Manager — API integration with local cache
#
# -- the view from 30,000 feet --
# Commands: cmd_pdm
# Dependencies: core.sh, fmt.sh
# =============================================================================

# PDM API config — set in freq.conf or environment
# PDM_HOST, PDM_TOKEN_ID, PDM_TOKEN_SECRET
PDM_CACHE_DIR="${FREQ_DATA_DIR}/cache/pdm"
PDM_CACHE_TTL=300  # seconds

cmd_pdm() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)   _pdm_status ;;
        nodes)    _pdm_nodes ;;
        vms)      _pdm_vms "$@" ;;
        storage)  _pdm_storage "$@" ;;
        help|--help|-h) _pdm_help ;;
        *)
            echo -e "  ${RED}Unknown pdm command: ${subcmd}${RESET}"
            echo "  Run 'freq pdm help' for usage."
            return 1
            ;;
    esac
}

_pdm_help() {
    freq_header "Proxmox Datacenter Manager"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq pdm <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    status          ${DIM}${_DASH} PDM connection and cluster overview${RESET}"
    freq_line "    nodes           ${DIM}${_DASH} List managed PVE nodes${RESET}"
    freq_line "    vms [--node N]  ${DIM}${_DASH} List VMs across datacenter${RESET}"
    freq_line "    storage [--node N] ${DIM}${_DASH} Storage overview${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Config:${RESET} Set PDM_HOST, PDM_TOKEN_ID, PDM_TOKEN_SECRET"
    freq_blank
    freq_footer
}

_pdm_check_config() {
    if [ -z "${PDM_HOST:-}" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} PDM_HOST not set. Configure in freq.conf."
        return 1
    fi
    if [ -z "${PDM_TOKEN_ID:-}" ] || [ -z "${PDM_TOKEN_SECRET:-}" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} PDM_TOKEN_ID / PDM_TOKEN_SECRET not set."
        return 1
    fi
    return 0
}

_pdm_api() {
    local endpoint="$1"
    local cache_key="${2:-}"

    # Check cache if key provided
    if [ -n "$cache_key" ]; then
        local cache_file="${PDM_CACHE_DIR}/${cache_key}.json"
        if [ -f "$cache_file" ]; then
            local age=$(( $(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || echo 0) ))
            if [ "$age" -lt "$PDM_CACHE_TTL" ]; then
                cat "$cache_file"
                return 0
            fi
        fi
    fi

    local url="https://${PDM_HOST}:8443/api2/json/${endpoint}"
    local result
    result=$(curl -s -k --connect-timeout 10 \
        -H "Authorization: PVEAPIToken=${PDM_TOKEN_ID}=${PDM_TOKEN_SECRET}" \
        "$url" 2>/dev/null)

    # Cache result if key provided
    if [ -n "$cache_key" ] && [ -n "$result" ]; then
        mkdir -p "$PDM_CACHE_DIR" 2>/dev/null
        echo "$result" > "${PDM_CACHE_DIR}/${cache_key}.json" 2>/dev/null
    fi

    echo "$result"
}

_pdm_status() {
    require_operator || return 1
    _pdm_check_config || return 1

    freq_header "PDM Status ${_DASH} ${PDM_HOST}"
    freq_blank

    _step_start "Connecting to PDM API"
    local version
    version=$(_pdm_api "version" "version")

    if [ -z "$version" ] || echo "$version" | grep -q "NOK\|error\|401"; then
        _step_fail "API unreachable or auth failed"
        freq_footer
        return 1
    fi
    _step_ok

    local ver_str
    ver_str=$(echo "$version" | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4)
    local release
    release=$(echo "$version" | grep -o '"release":"[^"]*"' | head -1 | cut -d'"' -f4)

    freq_line "  Version: ${BOLD}${ver_str:-unknown}${RESET} (${release:-?})"

    # Cluster status
    _step_start "Cluster status"
    local cluster
    cluster=$(_pdm_api "cluster/status" "cluster-status")
    if [ -n "$cluster" ]; then
        _step_ok
        local node_count quorate
        node_count=$(echo "$cluster" | grep -o '"type":"node"' | wc -l)
        quorate=$(echo "$cluster" | grep -o '"quorate":[0-9]' | head -1 | cut -d: -f2)
        freq_line "  Nodes: ${node_count}  Quorate: ${quorate:-?}"
    else
        _step_warn "no cluster data"
    fi

    freq_blank
    freq_footer
    log "pdm: status checked — ${ver_str:-unknown}"
}

_pdm_nodes() {
    require_operator || return 1
    _pdm_check_config || return 1

    freq_header "PDM Nodes"
    freq_blank

    local nodes
    nodes=$(_pdm_api "nodes" "nodes")

    if [ -z "$nodes" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot fetch node list"
        freq_footer
        return 1
    fi

    # Parse node data from JSON (grep-based without jq)
    local node_names
    node_names=$(echo "$nodes" | grep -o '"node":"[^"]*"' | cut -d'"' -f4)

    if [ -z "$node_names" ]; then
        freq_line "  ${DIM}No nodes found${RESET}"
        freq_footer
        return 0
    fi

    # Get detailed info per node
    while IFS= read -r nname; do
        [ -z "$nname" ] && continue
        local status cpu mem maxmem uptime
        # Extract fields for this node from the JSON blob
        local node_block
        node_block=$(echo "$nodes" | grep -o "{[^}]*\"node\":\"${nname}\"[^}]*}")
        status=$(echo "$node_block" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        cpu=$(echo "$node_block" | grep -o '"cpu":[0-9.]*' | cut -d: -f2)
        maxmem=$(echo "$node_block" | grep -o '"maxmem":[0-9]*' | cut -d: -f2)
        uptime=$(echo "$node_block" | grep -o '"uptime":[0-9]*' | cut -d: -f2)

        local color="${GREEN}"
        [ "$status" != "online" ] && color="${RED}"

        local uptime_h=""
        if [ -n "$uptime" ] && [ "$uptime" -gt 0 ] 2>/dev/null; then
            uptime_h="$((uptime / 3600))h"
        fi
        local mem_gb=""
        if [ -n "$maxmem" ] && [ "$maxmem" -gt 0 ] 2>/dev/null; then
            mem_gb="$((maxmem / 1073741824))GB"
        fi
        local cpu_pct=""
        if [ -n "$cpu" ]; then
            cpu_pct=$(printf '%.0f%%' "$(echo "$cpu * 100" | bc 2>/dev/null || echo 0)")
        fi

        freq_line "  ${color}${_TICK}${RESET} ${BOLD}${nname}${RESET}  ${DIM}${status:-?}  CPU:${cpu_pct:-?}  RAM:${mem_gb:-?}  Up:${uptime_h:-?}${RESET}"
    done <<< "$node_names"

    freq_blank
    freq_footer
    log "pdm: nodes listed"
}

_pdm_vms() {
    require_operator || return 1
    _pdm_check_config || return 1

    local filter_node=""
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --node|-n) filter_node="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    freq_header "PDM Virtual Machines"
    freq_blank

    local endpoint="cluster/resources?type=vm"
    local vms
    vms=$(_pdm_api "$endpoint" "vms")

    if [ -z "$vms" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot fetch VM list"
        freq_footer
        return 1
    fi

    local total=0 running=0 stopped=0

    # Extract VM entries
    local vmids
    vmids=$(echo "$vms" | grep -o '"vmid":[0-9]*' | cut -d: -f2 | sort -n)

    while IFS= read -r vmid; do
        [ -z "$vmid" ] && continue
        local vm_block
        vm_block=$(echo "$vms" | grep -o "{[^}]*\"vmid\":${vmid}[^}]*}" | head -1)
        local name node status mem maxmem
        name=$(echo "$vm_block" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
        node=$(echo "$vm_block" | grep -o '"node":"[^"]*"' | cut -d'"' -f4)
        status=$(echo "$vm_block" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)

        [ -n "$filter_node" ] && [ "$filter_node" != "$node" ] && continue

        total=$((total + 1))
        local color="${DIM}"
        if [ "$status" = "running" ]; then
            color="${GREEN}"; running=$((running + 1))
        else
            stopped=$((stopped + 1))
        fi

        freq_line "  ${color}${vmid}${RESET}  ${BOLD}${name:-?}${RESET}  ${DIM}${node:-?}  ${status:-?}${RESET}"
    done <<< "$vmids"

    freq_blank
    freq_line "  ${DIM}Total: ${total}  Running: ${running}  Stopped: ${stopped}${RESET}"
    freq_footer
    log "pdm: vms listed — total=${total} running=${running}"
}

_pdm_storage() {
    require_operator || return 1
    _pdm_check_config || return 1

    local filter_node=""
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --node|-n) filter_node="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    freq_header "PDM Storage"
    freq_blank

    local storage
    storage=$(_pdm_api "cluster/resources?type=storage" "storage")

    if [ -z "$storage" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot fetch storage list"
        freq_footer
        return 1
    fi

    local storages
    storages=$(echo "$storage" | grep -o '"storage":"[^"]*"' | cut -d'"' -f4 | sort -u)

    while IFS= read -r sname; do
        [ -z "$sname" ] && continue
        local s_block
        s_block=$(echo "$storage" | grep -o "{[^}]*\"storage\":\"${sname}\"[^}]*}" | head -1)
        local node status disk maxdisk stype
        node=$(echo "$s_block" | grep -o '"node":"[^"]*"' | cut -d'"' -f4)
        status=$(echo "$s_block" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        disk=$(echo "$s_block" | grep -o '"disk":[0-9]*' | cut -d: -f2)
        maxdisk=$(echo "$s_block" | grep -o '"maxdisk":[0-9]*' | cut -d: -f2)
        stype=$(echo "$s_block" | grep -o '"plugintype":"[^"]*"' | cut -d'"' -f4)

        [ -n "$filter_node" ] && [ "$filter_node" != "$node" ] && continue

        local usage_pct="?"
        if [ -n "$disk" ] && [ -n "$maxdisk" ] && [ "$maxdisk" -gt 0 ] 2>/dev/null; then
            usage_pct=$(( disk * 100 / maxdisk ))
        fi

        local color="${GREEN}"
        [ "${usage_pct}" != "?" ] && [ "$usage_pct" -gt 80 ] 2>/dev/null && color="${YELLOW}"
        [ "${usage_pct}" != "?" ] && [ "$usage_pct" -gt 90 ] 2>/dev/null && color="${RED}"

        freq_line "  ${color}${_BULLET}${RESET} ${BOLD}${sname}${RESET}  ${DIM}${node:-?}  ${stype:-?}  ${usage_pct}% used${RESET}"
    done <<< "$storages"

    freq_blank
    freq_footer
    log "pdm: storage listed"
}
