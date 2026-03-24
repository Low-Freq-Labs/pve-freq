#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/backup.sh
# Configuration Backup — pull configs from fleet, store locally
#
# -- save everything. trust nothing. --
# Commands: cmd_backup
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

BACKUP_DIR="${FREQ_DATA_DIR}/backup"

cmd_backup() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        snapshot)  _backup_snapshot "$@" ;;
        diff)      _backup_diff "$@" ;;
        list)      _backup_list ;;
        status)    _backup_status ;;
        prune)     _backup_prune "$@" ;;
        help|--help|-h) _backup_help ;;
        *)
            echo -e "  ${RED}Unknown backup command: ${subcmd}${RESET}"
            echo "  Run 'freq backup help' for usage."
            return 1
            ;;
    esac
}

_backup_help() {
    freq_header "Configuration Backup"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq backup <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    snapshot       ${DIM}${_DASH} Pull configs from all fleet hosts${RESET}"
    freq_line "    diff [ts1] [ts2] ${DIM}${_DASH} Compare two snapshots${RESET}"
    freq_line "    list           ${DIM}${_DASH} List available snapshots${RESET}"
    freq_line "    status         ${DIM}${_DASH} Show last backup info${RESET}"
    freq_line "    prune [--keep N] ${DIM}${_DASH} Remove old snapshots${RESET}"
    freq_blank
    freq_footer
}

_backup_snapshot() {
    require_operator || return 1
    require_ssh_key

    local ts
    ts=$(date '+%Y%m%d-%H%M%S')
    local snap_dir="${BACKUP_DIR}/${ts}"

    freq_header "Backup Snapshot ${_DASH} ${ts}"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would create snapshot at ${snap_dir}"
        freq_footer
        return 0
    fi

    mkdir -p "$snap_dir"

    # PVE nodes — /etc/pve/ configs
    local n
    for ((n=0; n<${#PVE_NODES[@]}; n++)); do
        local nname="${PVE_NODE_NAMES[$n]}"
        _step_start "PVE: ${nname} /etc/pve/"
        local pve_out="${snap_dir}/pve-${nname}"
        mkdir -p "$pve_out"
        if freq_ssh "$nname" "sudo tar czf - /etc/pve/ 2>/dev/null" > "${pve_out}/etc-pve.tar.gz" 2>/dev/null; then
            _step_ok "saved"
        else
            _step_fail "failed"
        fi
    done

    # Docker hosts — docker-compose.yml files
    load_hosts
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        [[ "${HOST_GROUPS[$i]}" == *docker* ]] || continue
        local label="${HOST_LABELS[$i]}"
        _step_start "Docker: ${label} compose files"
        local docker_out="${snap_dir}/docker-${label}"
        mkdir -p "$docker_out"
        if freq_ssh "$label" "sudo find /opt -name 'docker-compose.yml' -o -name 'compose.yml' 2>/dev/null | sudo xargs tar czf - 2>/dev/null" > "${docker_out}/compose-files.tar.gz" 2>/dev/null; then
            _step_ok "saved"
        else
            _step_warn "partial or empty"
        fi
    done

    # pfSense — config.xml
    _step_start "pfSense: config.xml"
    local pf_out="${snap_dir}/pfsense"
    mkdir -p "$pf_out"
    if freq_ssh "pfsense" "cat /cf/conf/config.xml 2>/dev/null" > "${pf_out}/config.xml" 2>/dev/null; then
        _step_ok "saved"
    else
        _step_fail "failed"
    fi

    # TrueNAS — midclt system config
    _step_start "TrueNAS: system config export"
    local tn_out="${snap_dir}/truenas"
    mkdir -p "$tn_out"
    if freq_ssh "truenas" "sudo midclt call system.info 2>/dev/null" > "${tn_out}/system-info.json" 2>/dev/null; then
        _step_ok "saved"
    else
        _step_fail "failed"
    fi

    # Switch — running-config
    _step_start "Switch: running-config"
    local sw_out="${snap_dir}/switch"
    mkdir -p "$sw_out"
    if freq_ssh "switch" "show running-config" > "${sw_out}/running-config.txt" 2>/dev/null; then
        _step_ok "saved"
    else
        _step_fail "failed"
    fi

    freq_blank
    freq_line "  Snapshot saved: ${BOLD}${snap_dir}${RESET}"
    freq_footer
    log "backup: snapshot created at ${snap_dir}"
}

_backup_diff() {
    local ts1="${1:-}" ts2="${2:-}"
    if [ -z "$ts1" ]; then
        local snaps
        snaps=$(ls -1d "${BACKUP_DIR}"/20* 2>/dev/null | sort | tail -2)
        local count
        count=$(echo "$snaps" | grep -c . 2>/dev/null || echo 0)
        if [ "$count" -lt 2 ]; then
            echo -e "  ${YELLOW}Need at least 2 snapshots to diff. Provide timestamps or take more backups.${RESET}"
            return 1
        fi
        ts1=$(echo "$snaps" | head -1 | xargs basename)
        ts2=$(echo "$snaps" | tail -1 | xargs basename)
    fi

    freq_header "Backup Diff ${_DASH} ${ts1} vs ${ts2}"
    freq_blank

    local dir1="${BACKUP_DIR}/${ts1}" dir2="${BACKUP_DIR}/${ts2}"
    [ ! -d "$dir1" ] && { echo -e "  ${RED}Snapshot not found: ${ts1}${RESET}"; return 1; }
    [ ! -d "$dir2" ] && { echo -e "  ${RED}Snapshot not found: ${ts2}${RESET}"; return 1; }

    diff -rq "$dir1" "$dir2" 2>/dev/null | while IFS= read -r line; do
        freq_line "  ${line}"
    done

    freq_blank
    freq_footer
}

_backup_list() {
    freq_header "Backup Snapshots"
    freq_blank

    local count=0
    local snap
    for snap in "${BACKUP_DIR}"/20*; do
        [ ! -d "$snap" ] && continue
        local name size
        name=$(basename "$snap")
        size=$(du -sh "$snap" 2>/dev/null | awk '{print $1}')
        freq_line "  ${name}  ${DIM}${size}${RESET}"
        count=$((count + 1))
    done

    [ "$count" -eq 0 ] && freq_line "  ${DIM}No snapshots found. Run 'freq backup snapshot'.${RESET}"
    freq_blank
    freq_footer
}

_backup_status() {
    freq_header "Backup Status"
    freq_blank

    local latest
    latest=$(ls -1d "${BACKUP_DIR}"/20* 2>/dev/null | sort | tail -1)
    if [ -n "$latest" ] && [ -d "$latest" ]; then
        local name size age_secs age_human
        name=$(basename "$latest")
        size=$(du -sh "$latest" 2>/dev/null | awk '{print $1}')
        age_secs=$(( $(date +%s) - $(stat -c %Y "$latest" 2>/dev/null || echo 0) ))
        age_human="$((age_secs / 3600))h $((age_secs % 3600 / 60))m ago"
        freq_line "  Last snapshot: ${BOLD}${name}${RESET} (${size}, ${age_human})"
    else
        freq_line "  ${DIM}No backups taken yet.${RESET}"
    fi

    local total
    total=$(ls -1d "${BACKUP_DIR}"/20* 2>/dev/null | wc -l)
    freq_line "  Total snapshots: ${total:-0}"
    freq_blank
    freq_footer
}

_backup_prune() {
    require_admin || return 1
    local keep=5
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --keep) keep="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    freq_header "Backup Prune ${_DASH} keep ${keep}"
    freq_blank

    local snaps
    snaps=$(ls -1d "${BACKUP_DIR}"/20* 2>/dev/null | sort)
    local total
    total=$(echo "$snaps" | grep -c . 2>/dev/null || echo 0)

    if [ "$total" -le "$keep" ]; then
        freq_line "  ${DIM}Only ${total} snapshots — nothing to prune.${RESET}"
        freq_footer
        return 0
    fi

    local to_remove=$((total - keep))
    local removed=0
    echo "$snaps" | head -"$to_remove" | while IFS= read -r snap; do
        local name
        name=$(basename "$snap")
        if [ "$DRY_RUN" = "true" ]; then
            freq_line "  ${CYAN}[DRY-RUN]${RESET} Would remove: ${name}"
        else
            rm -rf "$snap"
            freq_line "  ${RED}Removed:${RESET} ${name}"
            removed=$((removed + 1))
        fi
    done

    freq_blank
    freq_footer
    log "backup: pruned ${to_remove} snapshots, kept ${keep}"
}
