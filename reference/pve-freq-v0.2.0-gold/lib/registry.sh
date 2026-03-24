#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/registry.sh
# Container Registry — fleet-wide Docker container inventory
#
# -- every container, every host, one view --
# Commands: cmd_registry
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

REGISTRY_CACHE="${FREQ_DATA_DIR}/cache/registry.json"

cmd_registry() {
    local subcmd="${1:-list}"
    shift 2>/dev/null || true

    case "$subcmd" in
        list)    _registry_list "$@" ;;
        diff)    _registry_diff "$@" ;;
        help|--help|-h) _registry_help ;;
        *)
            echo -e "  ${RED}Unknown registry command: ${subcmd}${RESET}"
            echo "  Run 'freq registry help' for usage."
            return 1
            ;;
    esac
}

_registry_help() {
    freq_header "Container Registry"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq registry <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    list [--host H]  ${DIM}${_DASH} Show all Docker containers fleet-wide${RESET}"
    freq_line "    diff             ${DIM}${_DASH} Compare current vs last cached scan${RESET}"
    freq_blank
    freq_footer
}

_registry_scan_host() {
    local label="$1"
    freq_ssh "$label" '
        sudo docker ps -a --format "{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}" 2>/dev/null
    ' 2>/dev/null
}

_registry_list() {
    require_operator || return 1
    require_ssh_key

    local filter_host=""
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --host|-H) filter_host="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    freq_header "Container Registry"
    freq_blank

    load_hosts
    local total_running=0 total_stopped=0 total_hosts=0

    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        [[ "${HOST_GROUPS[$i]}" == *docker* ]] || continue
        local label="${HOST_LABELS[$i]}"

        # Filter to specific host if requested
        [ -n "$filter_host" ] && [ "$filter_host" != "$label" ] && continue

        total_hosts=$((total_hosts + 1))
        freq_divider "${label}"

        local data
        data=$(_registry_scan_host "$label")

        if [ -z "$data" ]; then
            freq_line "  ${RED}${_CROSS}${RESET} ${DIM}Host unreachable or no containers${RESET}"
            continue
        fi

        local host_running=0 host_stopped=0
        while IFS='|' read -r name image status ports; do
            [ -z "$name" ] && continue
            local color="${RED}" state_icon="${_CROSS}"
            if echo "$status" | grep -qi "^Up"; then
                color="${GREEN}"; state_icon="${_TICK}"
                host_running=$((host_running + 1))
            else
                host_stopped=$((host_stopped + 1))
            fi

            # Truncate image name for display
            local short_image="${image}"
            [ ${#short_image} -gt 35 ] && short_image="${short_image:0:32}..."

            freq_line "  ${color}${state_icon}${RESET} ${BOLD}${name}${RESET}"
            freq_line "    ${DIM}${short_image}${RESET}"
            if [ -n "$ports" ] && [ "$ports" != " " ]; then
                freq_line "    ${DIM}Ports: ${ports}${RESET}"
            fi
        done <<< "$data"

        total_running=$((total_running + host_running))
        total_stopped=$((total_stopped + host_stopped))
        freq_line "  ${DIM}Host total: ${host_running} running, ${host_stopped} stopped${RESET}"
        freq_blank
    done

    freq_divider "Fleet Summary"
    freq_line "  Hosts: ${total_hosts}  Running: ${GREEN}${total_running}${RESET}  Stopped: ${RED}${total_stopped}${RESET}"
    freq_blank
    freq_footer

    # Cache the scan
    mkdir -p "$(dirname "$REGISTRY_CACHE")" 2>/dev/null
    _registry_save_cache

    log "registry: list — ${total_hosts} hosts, ${total_running} running, ${total_stopped} stopped"
}

_registry_save_cache() {
    local cache_tmp="${REGISTRY_CACHE}.tmp"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')

    {
        echo "# FREQ container registry cache — ${ts}"
        load_hosts
        local i
        for ((i=0; i<HOST_COUNT; i++)); do
            [[ "${HOST_GROUPS[$i]}" == *docker* ]] || continue
            local label="${HOST_LABELS[$i]}"
            local data
            data=$(_registry_scan_host "$label")
            while IFS='|' read -r name image status ports; do
                [ -z "$name" ] && continue
                echo "${label}|${name}|${image}|${status}"
            done <<< "$data"
        done
    } > "$cache_tmp" 2>/dev/null

    # Rotate: current -> .prev
    [ -f "$REGISTRY_CACHE" ] && mv "$REGISTRY_CACHE" "${REGISTRY_CACHE}.prev" 2>/dev/null
    mv "$cache_tmp" "$REGISTRY_CACHE" 2>/dev/null
}

_registry_diff() {
    require_operator || return 1

    freq_header "Registry Diff"
    freq_blank

    local current="${REGISTRY_CACHE}"
    local previous="${REGISTRY_CACHE}.prev"

    if [ ! -f "$current" ] || [ ! -f "$previous" ]; then
        freq_line "  ${DIM}Need at least 2 scans to diff.${RESET}"
        freq_line "  ${DIM}Run 'freq registry list' twice to compare.${RESET}"
        freq_footer
        return 1
    fi

    local cur_ts prev_ts
    cur_ts=$(head -1 "$current" 2>/dev/null | sed 's/# FREQ container registry cache -- //')
    prev_ts=$(head -1 "$previous" 2>/dev/null | sed 's/# FREQ container registry cache -- //')
    freq_line "  Comparing: ${DIM}${prev_ts}${RESET} vs ${DIM}${cur_ts}${RESET}"
    freq_blank

    # Find new containers (in current but not previous)
    local added=0 removed=0 changed=0
    while IFS='|' read -r host name image status; do
        [[ "$host" == \#* ]] && continue
        [ -z "$name" ] && continue
        if ! grep -q "|${name}|" "$previous" 2>/dev/null; then
            freq_line "  ${GREEN}+ NEW${RESET} ${host}/${name} ${DIM}(${image})${RESET}"
            added=$((added + 1))
        fi
    done < "$current"

    # Find removed containers (in previous but not current)
    while IFS='|' read -r host name image status; do
        [[ "$host" == \#* ]] && continue
        [ -z "$name" ] && continue
        if ! grep -q "|${name}|" "$current" 2>/dev/null; then
            freq_line "  ${RED}- REMOVED${RESET} ${host}/${name} ${DIM}(${image})${RESET}"
            removed=$((removed + 1))
        fi
    done < "$previous"

    # Find image changes
    while IFS='|' read -r host name image status; do
        [[ "$host" == \#* ]] && continue
        [ -z "$name" ] && continue
        local prev_image
        prev_image=$(grep "|${name}|" "$previous" 2>/dev/null | head -1 | cut -d'|' -f3)
        if [ -n "$prev_image" ] && [ "$prev_image" != "$image" ]; then
            freq_line "  ${YELLOW}~ CHANGED${RESET} ${host}/${name}"
            freq_line "    ${DIM}${prev_image} -> ${image}${RESET}"
            changed=$((changed + 1))
        fi
    done < "$current"

    if [ "$added" -eq 0 ] && [ "$removed" -eq 0 ] && [ "$changed" -eq 0 ]; then
        freq_line "  ${GREEN}${_TICK}${RESET} No changes detected"
    fi

    freq_blank
    freq_line "  ${DIM}Added: ${added}  Removed: ${removed}  Changed: ${changed}${RESET}"
    freq_blank
    freq_footer
    log "registry: diff — added=${added} removed=${removed} changed=${changed}"
}
