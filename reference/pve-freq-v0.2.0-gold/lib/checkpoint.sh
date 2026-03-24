#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/checkpoint.sh
# Pre-Change Safety System — WIP markers for multi-step operations
#
# -- measure twice, cut once --
# Commands: cmd_checkpoint
# Dependencies: core.sh, fmt.sh
# =============================================================================

CHECKPOINT_DIR="${FREQ_DATA_DIR}/checkpoints"

cmd_checkpoint() {
    local subcmd="${1:-list}"
    shift 2>/dev/null || true

    case "$subcmd" in
        create)   _checkpoint_create "$@" ;;
        verify)   _checkpoint_verify "$@" ;;
        clear)    _checkpoint_clear "$@" ;;
        list)     _checkpoint_list ;;
        help|--help|-h) _checkpoint_help ;;
        *)
            echo -e "  ${RED}Unknown checkpoint command: ${subcmd}${RESET}"
            echo "  Run 'freq checkpoint help' for usage."
            return 1
            ;;
    esac
}

_checkpoint_help() {
    freq_header "Checkpoint System"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq checkpoint <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    create <name> [desc]  ${DIM}${_DASH} Create a checkpoint before changes${RESET}"
    freq_line "    verify <name>         ${DIM}${_DASH} Verify checkpoint integrity${RESET}"
    freq_line "    clear <name|--all>    ${DIM}${_DASH} Clear a checkpoint (mark complete)${RESET}"
    freq_line "    list                  ${DIM}${_DASH} List active checkpoints${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Purpose:${RESET}"
    freq_line "    Checkpoints mark the start of multi-step operations."
    freq_line "    If FREQ detects stale checkpoints, it means something was"
    freq_line "    interrupted mid-operation and may need manual cleanup."
    freq_blank
    freq_footer
}

_checkpoint_create() {
    local name="${1:-}"
    [ -z "$name" ] && { echo -e "  ${RED}Usage: freq checkpoint create <name> [description]${RESET}"; return 1; }
    shift
    local desc="$*"
    [ -z "$desc" ] && desc="No description"

    mkdir -p "$CHECKPOINT_DIR" 2>/dev/null

    local cp_file="${CHECKPOINT_DIR}/${name}.wip"
    if [ -f "$cp_file" ]; then
        echo -e "  ${YELLOW}${_WARN}${RESET} Checkpoint '${name}' already exists!"
        echo -e "  ${DIM}Created: $(head -1 "$cp_file" 2>/dev/null)${RESET}"
        _freq_confirm "Overwrite existing checkpoint?" || return 1
    fi

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would create checkpoint: ${name}"
        return 0
    fi

    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    local user="${FREQ_USER:-$(id -un)}"

    # Capture pre-change state
    {
        echo "timestamp: ${ts}"
        echo "user: ${user}"
        echo "name: ${name}"
        echo "description: ${desc}"
        echo "status: IN_PROGRESS"
        echo "---"
        echo "# Pre-change state snapshot"
        echo "hostname: $(hostname)"
        echo "pid: $$"
        echo "pwd: $(pwd)"
        # Capture fleet state if SSH available
        if [ -n "${FREQ_KEY_PATH:-}" ]; then
            echo "# PVE VM count per node"
            local n
            for ((n=0; n<${#PVE_NODES[@]}; n++)); do
                local count
                count=$(freq_ssh "${PVE_NODE_NAMES[$n]}" "sudo qm list 2>/dev/null | tail -n+2 | wc -l" 2>/dev/null)
                echo "pve_vms_${PVE_NODE_NAMES[$n]}: ${count:-?}"
            done 2>/dev/null
        fi
    } > "$cp_file" 2>/dev/null

    chmod 644 "$cp_file" 2>/dev/null
    echo -e "  ${GREEN}${_TICK}${RESET} Checkpoint created: ${BOLD}${name}${RESET}"
    echo -e "  ${DIM}Description: ${desc}${RESET}"
    log "checkpoint: created '${name}' — ${desc}"
}

_checkpoint_verify() {
    local name="${1:-}"
    [ -z "$name" ] && { echo -e "  ${RED}Usage: freq checkpoint verify <name>${RESET}"; return 1; }

    local cp_file="${CHECKPOINT_DIR}/${name}.wip"
    if [ ! -f "$cp_file" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} Checkpoint '${name}' not found"
        return 1
    fi

    freq_header "Checkpoint Verify ${_DASH} ${name}"
    freq_blank

    # Read checkpoint data
    local cp_ts cp_user cp_desc cp_status
    cp_ts=$(grep "^timestamp:" "$cp_file" | cut -d' ' -f2-)
    cp_user=$(grep "^user:" "$cp_file" | cut -d' ' -f2-)
    cp_desc=$(grep "^description:" "$cp_file" | cut -d' ' -f2-)
    cp_status=$(grep "^status:" "$cp_file" | cut -d' ' -f2-)

    freq_line "  Name: ${BOLD}${name}${RESET}"
    freq_line "  Created: ${cp_ts}"
    freq_line "  User: ${cp_user}"
    freq_line "  Description: ${cp_desc}"
    freq_line "  Status: ${YELLOW}${cp_status}${RESET}"
    freq_blank

    # Check age
    local file_age_secs
    file_age_secs=$(( $(date +%s) - $(stat -c %Y "$cp_file" 2>/dev/null || echo 0) ))
    local age_hours=$((file_age_secs / 3600))
    local age_min=$(( (file_age_secs % 3600) / 60 ))

    if [ "$age_hours" -gt 24 ]; then
        freq_line "  ${RED}${_WARN} STALE${RESET}: Checkpoint is ${age_hours}h old!"
        freq_line "  ${DIM}This operation may have been interrupted. Review and clear manually.${RESET}"
    elif [ "$age_hours" -gt 1 ]; then
        freq_line "  ${YELLOW}${_WARN} WARNING${RESET}: Checkpoint is ${age_hours}h ${age_min}m old"
    else
        freq_line "  ${GREEN}${_TICK}${RESET} Age: ${age_min}m (recent)"
    fi

    # Show pre-change snapshot
    freq_blank
    freq_divider "Pre-Change Snapshot"
    local in_data=false
    while IFS= read -r line; do
        if [ "$line" = "---" ]; then
            in_data=true
            continue
        fi
        $in_data && freq_line "  ${DIM}${line}${RESET}"
    done < "$cp_file"

    freq_blank
    freq_footer
    log "checkpoint: verified '${name}' (age: ${age_hours}h ${age_min}m)"
}

_checkpoint_clear() {
    local name="${1:-}"

    if [ "$name" = "--all" ]; then
        local count=0
        for cp in "${CHECKPOINT_DIR}"/*.wip; do
            [ ! -f "$cp" ] && continue
            count=$((count + 1))
        done

        if [ "$count" -eq 0 ]; then
            echo -e "  ${DIM}No active checkpoints.${RESET}"
            return 0
        fi

        if [ "$DRY_RUN" = "true" ]; then
            echo -e "  ${CYAN}[DRY-RUN]${RESET} Would clear ${count} checkpoints"
            return 0
        fi

        _freq_confirm "Clear ALL ${count} checkpoints?" || return 1

        for cp in "${CHECKPOINT_DIR}"/*.wip; do
            [ ! -f "$cp" ] && continue
            local cpname
            cpname=$(basename "$cp" .wip)
            # Mark as completed before removing
            sed -i "s/^status: .*/status: COMPLETED/" "$cp" 2>/dev/null
            mv "$cp" "${cp%.wip}.done" 2>/dev/null
            echo -e "  ${GREEN}${_TICK}${RESET} Cleared: ${cpname}"
        done
        log "checkpoint: cleared all (${count})"
        return 0
    fi

    [ -z "$name" ] && { echo -e "  ${RED}Usage: freq checkpoint clear <name|--all>${RESET}"; return 1; }

    local cp_file="${CHECKPOINT_DIR}/${name}.wip"
    if [ ! -f "$cp_file" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} Checkpoint '${name}' not found"
        return 1
    fi

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would clear checkpoint: ${name}"
        return 0
    fi

    # Mark as completed and archive
    sed -i "s/^status: .*/status: COMPLETED/" "$cp_file" 2>/dev/null
    echo "completed: $(date '+%Y-%m-%d %H:%M:%S')" >> "$cp_file"
    mv "$cp_file" "${cp_file%.wip}.done" 2>/dev/null

    echo -e "  ${GREEN}${_TICK}${RESET} Checkpoint '${name}' cleared (marked complete)"
    log "checkpoint: cleared '${name}'"
}

_checkpoint_list() {
    freq_header "Active Checkpoints"
    freq_blank

    mkdir -p "$CHECKPOINT_DIR" 2>/dev/null

    local active=0 stale=0
    for cp in "${CHECKPOINT_DIR}"/*.wip; do
        [ ! -f "$cp" ] && continue
        active=$((active + 1))

        local cpname ts desc
        cpname=$(basename "$cp" .wip)
        ts=$(grep "^timestamp:" "$cp" 2>/dev/null | cut -d' ' -f2-)
        desc=$(grep "^description:" "$cp" 2>/dev/null | cut -d' ' -f2-)

        local age_secs
        age_secs=$(( $(date +%s) - $(stat -c %Y "$cp" 2>/dev/null || echo 0) ))
        local age_hours=$((age_secs / 3600))

        local color="${GREEN}" age_label="${age_hours}h"
        if [ "$age_hours" -gt 24 ]; then
            color="${RED}"; age_label="${age_hours}h STALE"
            stale=$((stale + 1))
        elif [ "$age_hours" -gt 1 ]; then
            color="${YELLOW}"
        fi

        freq_line "  ${color}${_BULLET}${RESET} ${BOLD}${cpname}${RESET}  ${DIM}${ts}  (${age_label})${RESET}"
        freq_line "    ${DIM}${desc}${RESET}"
    done

    if [ "$active" -eq 0 ]; then
        freq_line "  ${GREEN}${_TICK}${RESET} No active checkpoints"
    else
        freq_blank
        freq_line "  Active: ${YELLOW}${active}${RESET}  Stale (>24h): ${RED}${stale}${RESET}"
        if [ "$stale" -gt 0 ]; then
            freq_line "  ${RED}${_WARN}${RESET} Stale checkpoints may indicate interrupted operations!"
        fi
    fi

    # Show recently completed
    local done_count=0
    for cp in "${CHECKPOINT_DIR}"/*.done; do
        [ ! -f "$cp" ] && continue
        done_count=$((done_count + 1))
    done
    if [ "$done_count" -gt 0 ]; then
        freq_blank
        freq_line "  ${DIM}Completed checkpoints: ${done_count}${RESET}"
    fi

    freq_blank
    freq_footer
}
