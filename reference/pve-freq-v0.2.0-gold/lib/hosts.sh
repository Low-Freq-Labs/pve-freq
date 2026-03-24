#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/hosts.sh
# Host Registry: CRUD, PVE discovery, group management
#
# Author:  FREQ Project / LOW FREQ Labs
#
# -- the address book. every host we've ever met. --
# Commands: cmd_hosts, cmd_discover, cmd_groups
# Dependencies: core.sh, fmt.sh, resolve.sh, ssh.sh, validate.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# HOST SELECTION — Interactive picker
# Uses resolve.sh's load_hosts() / HOST_* arrays
# ═══════════════════════════════════════════════════════════════════
select_host() {
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts in fleet. Add hosts with 'freq hosts add <IP> <label> [type] [groups]'."

    echo ""
    freq_header "Select Host"
    echo ""
    local _sh_rows=$(( (HOST_COUNT + 1) / 2 )) r
    for ((r=0; r<_sh_rows; r++)); do
        local left=$r right=$(( r + _sh_rows ))
        if (( left < HOST_COUNT )); then
            local entry_l
            entry_l=$(printf "${PURPLELIGHT}%2d${RESET}  ${BOLD}%-16s${RESET} ${DIM}[%s]${RESET}" "$((left+1))" "${HOST_LABELS[$left]}" "${HOST_TYPES[$left]}")
            printf "    %-72b" "$entry_l"
        fi
        if (( right < HOST_COUNT )); then
            local entry_r
            entry_r=$(printf "${PURPLELIGHT}%2d${RESET}  ${BOLD}%-16s${RESET} ${DIM}[%s]${RESET}" "$((right+1))" "${HOST_LABELS[$right]}" "${HOST_TYPES[$right]}")
            echo -e "$entry_r"
        else
            echo ""
        fi
    done
    echo ""
    freq_footer
    echo ""
    read -rp "    Host number: " hnum
    [ -z "$hnum" ] && die "No host selected."
    [[ "$hnum" =~ ^[0-9]+$ ]] || die "Invalid input '$hnum'. Enter a number, e.g. 1."
    (( hnum < 1 || hnum > HOST_COUNT )) && die "Out of range. Pick between 1 and $HOST_COUNT."
    FOUND_IDX=$((hnum - 1))
}

# ═══════════════════════════════════════════════════════════════════
# FIND HOST — Search by label or IP, set FOUND_IDX
# ═══════════════════════════════════════════════════════════════════
find_host() {
    local target="$1" i
    for ((i=0; i<HOST_COUNT; i++)); do
        if [ "${HOST_LABELS[$i]}" = "$target" ] || [ "${HOST_IPS[$i]}" = "$target" ]; then
            FOUND_IDX=$i  # used by callers (select_host, fleet.sh, etc.)
            export FOUND_IDX
            return 0
        fi
    done
    return 1
}

# ═══════════════════════════════════════════════════════════════════
# HOST TYPE CHECK — Does this host type support SSH/bash?
# Returns 0 for linux/truenas/pfsense, 1 for switch/external/idrac
# ═══════════════════════════════════════════════════════════════════
host_supports_ssh() {
    local htype="${1:-linux}"
    case "$htype" in
        switch|external|idrac) return 1 ;;
        *) return 0 ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# HOST REGISTRY — cmd_hosts: list, add, remove, edit, import
# ═══════════════════════════════════════════════════════════════════
cmd_hosts() {
    case "${1:-}" in
        list|ls)     _hosts_list ;;
        add)         shift; _hosts_add "$@" ;;
        remove|rm)   shift; _hosts_remove "$@" ;;
        edit)        shift; _hosts_edit "$@" ;;
        import)      shift; _hosts_import "$@" ;;
        --help|-h)   _hosts_usage ;;
        "")          _hosts_interactive ;;
        *)           echo "Unknown subcommand: $1"; _hosts_usage; return 1 ;;
    esac
}

_hosts_usage() {
    echo ""
    freq_header "Host Registry"
    freq_blank
    freq_line "${BOLD}${WHITE}Usage:${RESET}  freq hosts <subcommand>"
    freq_blank
    freq_line "  ${PURPLELIGHT}list${RESET}                    Show all fleet hosts"
    freq_line "  ${PURPLELIGHT}add${RESET} <IP> <label> [type] [groups]  Add a host"
    freq_line "  ${PURPLELIGHT}remove${RESET} <label|IP>       Remove a host"
    freq_line "  ${PURPLELIGHT}edit${RESET} <label|IP>         Edit a host entry"
    freq_line "  ${PURPLELIGHT}import${RESET} <file>           Bulk import from file"
    freq_blank
    freq_line "${DIM}Types: linux, truenas, pfsense, switch, external, idrac${RESET}"
    freq_line "${DIM}Groups: comma-separated (e.g. prod,docker)${RESET}"
    freq_blank
    freq_footer
}

_hosts_interactive() {
    echo ""
    freq_header "Host Registry"
    echo ""
    menu_item 1 "list" "Show all fleet hosts" "safe"
    menu_item 2 "add" "Add a host to fleet" "changes"
    menu_item 3 "remove" "Remove a host from fleet" "destructive"
    menu_item 4 "edit" "Edit a host entry" "changes"
    echo ""
    echo -e "    ${DIM} 0  Back${RESET}"
    echo ""
    read -rp "    Select [0-4]: " choice
    case "$choice" in
        1) _hosts_list ;;
        2) _hosts_add_interactive ;;
        3) _hosts_remove ;;
        4) _hosts_edit ;;
        0|"") ;;
        *) echo -e "\n    ${YELLOW}Pick a number from the menu.${RESET}" ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# LIST — Show all fleet hosts
# ═══════════════════════════════════════════════════════════════════
_hosts_list() {
    load_hosts
    echo ""
    freq_header "Fleet Hosts"
    echo ""

    if [ "$HOST_COUNT" -eq 0 ]; then
        echo -e "    ${DIM}No hosts registered. Add hosts with:${RESET}"
        echo -e "    ${DIM}  freq hosts add <IP> <label> [type] [groups]${RESET}"
        echo -e "    ${DIM}  freq discover${RESET}"
        echo ""
        freq_footer
        return 0
    fi

    printf "    ${DIM}%-16s %-20s %-10s %s${RESET}\n" "IP" "Label" "Type" "Groups"
    freq_footer

    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        printf "    %-16s %-20s %-10s %s\n" \
            "${HOST_IPS[$i]}" "${HOST_LABELS[$i]}" "${HOST_TYPES[$i]}" "${HOST_GROUPS[$i]}"
    done

    echo ""
    echo -e "    ${DIM}Total: ${HOST_COUNT} hosts${RESET}"
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# ADD — Add a host to the registry
# Usage: freq hosts add <IP> <label> [type] [groups] [--skip-key]
# ═══════════════════════════════════════════════════════════════════
_hosts_add() {
    require_admin || return 1

    local host_ip="${1:-}" label="${2:-}" htype="${3:-linux}" groups="${4:-prod}" skip_key="${5:-}"

    if [ -z "$host_ip" ] || [ -z "$label" ]; then
        echo "Usage: freq hosts add <IP> <label> [type] [groups] [--skip-key]"
        return 1
    fi

    validate_ip "$host_ip"
    validate_label "$label"

    # Validate host type
    case "$htype" in
        linux|truenas|pfsense|switch|external|idrac) ;;
        *) die "Invalid host type: '$htype'. Use: linux, truenas, pfsense, switch, external, idrac" ;;
    esac

    # Load current hosts and check for duplicates (idempotent)
    load_hosts
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        [ "${HOST_IPS[$i]}" = "$host_ip" ] && die "IP $host_ip already in fleet (label: ${HOST_LABELS[$i]}). Use 'freq hosts edit' to modify."
        [ "${HOST_LABELS[$i]}" = "$label" ] && die "Label '$label' already in fleet (IP: ${HOST_IPS[$i]}). Use 'freq hosts edit' to modify."
    done

    # Dry-run: show what would happen
    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "    ${CYAN}[DRY-RUN]${RESET} Would add ${BOLD}${label}${RESET} (${host_ip}) [${htype}] groups=${groups}"
        return 0
    fi

    freq_action_modify "Adding host to registry..."

    # Ensure hosts file exists
    if [ ! -f "$HOSTS_FILE" ]; then
        touch "$HOSTS_FILE" 2>/dev/null || die "Cannot create $HOSTS_FILE. Check permissions."
    fi

    # Backup then append
    backup_config "$HOSTS_FILE"
    if ! printf "%-14s  %-18s  %-10s  %s\n" "$host_ip" "$label" "$htype" "$groups" >> "$HOSTS_FILE" 2>/dev/null; then
        die "Cannot write to ${HOSTS_FILE}. Check permissions (need group-write for ${FREQ_GROUP})."
    fi
    echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${label}${RESET} (${host_ip}) added to fleet [${htype}] groups=${groups}"

    # Deploy SSH key unless skipped
    if [ "$skip_key" != "--skip-key" ] && command -v sshpass &>/dev/null && host_supports_ssh "$htype"; then
        _hosts_deploy_key "$host_ip" "$label" "$htype"
    elif [ "$skip_key" != "--skip-key" ] && ! host_supports_ssh "$htype"; then
        echo -e "    ${DIM}Key deploy skipped: host type '$htype' does not support SSH.${RESET}"
    fi

    freq_celebrate 2>/dev/null || true
    time_saved 1 2>/dev/null || true
    log "hosts add: $label ($host_ip) [$htype] groups=$groups"
}

_hosts_add_interactive() {
    require_admin || return 1
    echo ""
    echo -e "    ${BOLD}Add a new host to the fleet${RESET}"
    echo ""
    local host_ip label htype groups

    read -rp "    IP address: " host_ip
    [ -z "$host_ip" ] && die "IP address is required."

    read -rp "    Label: " label
    [ -z "$label" ] && die "Label is required."

    echo -e "    ${DIM}Types: linux, truenas, pfsense, switch, external, idrac${RESET}"
    read -rp "    Type [linux]: " htype
    htype="${htype:-linux}"

    read -rp "    Groups [prod]: " groups
    groups="${groups:-prod}"

    _hosts_add "$host_ip" "$label" "$htype" "$groups"
}

# Deploy SSH key to a newly added host
_hosts_deploy_key() {
    local host_ip="$1" label="$2" htype="$3"

    [ -z "${FREQ_KEY_PATH:-}" ] && { echo -e "    ${DIM}No SSH key found. Skipping key deploy. Run 'freq init' first.${RESET}"; return 0; }
    [ ! -f "${FREQ_KEY_PATH}.pub" ] && { echo -e "    ${DIM}No public key found. Skipping key deploy.${RESET}"; return 0; }

    echo -e "    Deploying SSH key to ${REMOTE_USER}@${host_ip}..."

    # Try vault first for password
    local svc_pass=""
    if type -t vault_get &>/dev/null; then
        svc_pass=$(vault_get "${FREQ_SERVICE_ACCOUNT}-pass" 2>/dev/null) || true
    fi

    if [ -z "$svc_pass" ] && [ -t 0 ]; then
        read -rsp "    Password for ${REMOTE_USER}@${host_ip}: " svc_pass; echo
    fi

    if [ -z "$svc_pass" ]; then
        echo -e "    ${DIM}Skipping key deploy: no credentials. Use 'freq keys deploy' later.${RESET}"
        return 0
    fi

    local _done=false
    while ! $_done; do
        if SSHPASS="$svc_pass" sshpass -e ssh-copy-id -o StrictHostKeyChecking=accept-new \
            -i "${FREQ_KEY_PATH}.pub" "${REMOTE_USER}@${host_ip}" &>/dev/null; then
            echo -e "    ${GREEN}${_TICK}${RESET}  Key deployed to ${label}"
            _done=true
        else
            echo -e "    ${YELLOW}${_WARN}${RESET}  Key deploy failed for ${host_ip}"
            if [ -t 0 ]; then
                ask_rsq "SSH key deploy failed. Wrong password?"
                case $? in
                    0) read -rsp "    Password for ${REMOTE_USER}: " svc_pass; echo; continue ;;
                    1) _done=true ;;
                    2) break ;;
                esac
            else
                _done=true
            fi
        fi
    done

    # Verify key access
    if ssh -n -i "$FREQ_KEY_PATH" -o ConnectTimeout=5 -o BatchMode=yes "${REMOTE_USER}@${host_ip}" true 2>/dev/null; then
        echo -e "    ${GREEN}${_TICK}${RESET}  Key verified"
    else
        echo -e "    ${DIM}Key verify skipped. Bootstrap will handle this.${RESET}"
    fi

    unset svc_pass
}

# ═══════════════════════════════════════════════════════════════════
# REMOVE — Remove a host from the registry
# Usage: freq hosts remove [label|IP]
# ═══════════════════════════════════════════════════════════════════
_hosts_remove() {
    require_admin || return 1

    local target="${1:-}"

    if [ -z "$target" ]; then
        _hosts_list
        echo ""
        read -rp "    Label or IP to remove: " target
        [ -z "$target" ] && die "No target specified."
    fi

    [ ! -f "$HOSTS_FILE" ] && die "No hosts file found at $HOSTS_FILE."

    # Find the matching entry
    load_hosts
    local match_idx=-1 i
    for ((i=0; i<HOST_COUNT; i++)); do
        if [ "${HOST_LABELS[$i]}" = "$target" ] || [ "${HOST_IPS[$i]}" = "$target" ]; then
            match_idx=$i
            break
        fi
    done
    [ "$match_idx" -eq -1 ] && die "No host found matching '$target'. Run 'freq hosts list' to see registered hosts."

    local match_label="${HOST_LABELS[$match_idx]}"
    local match_ip="${HOST_IPS[$match_idx]}"
    local match_type="${HOST_TYPES[$match_idx]}"

    echo -e "    Found: ${BOLD}${match_label}${RESET} (${match_ip}) [${match_type}]"

    # Dry-run: show what would happen
    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "    ${CYAN}[DRY-RUN]${RESET} Would remove ${match_label} from hosts.conf"
        return 0
    fi

    # Confirm unless --yes
    if [ "${FREQ_YES}" != "true" ]; then
        if [ -t 0 ]; then
            local confirm
            read -rp "    Remove ${match_label}? [y/N]: " confirm
            [[ "$confirm" =~ ^[Yy] ]] || die "Aborted."
        else
            die "Non-interactive mode: use --yes to confirm removal."
        fi
    fi

    backup_config "$HOSTS_FILE"

    # Remove the line matching this label (exact match on column 2)
    local tmp_file="${HOSTS_FILE}.tmp.$$"
    awk -v lbl="$match_label" '
        /^[[:space:]]*#/ { print; next }
        /^[[:space:]]*$/ { print; next }
        { if ($2 != lbl) print }
    ' "$HOSTS_FILE" > "$tmp_file"

    local orig_perms orig_owner
    orig_perms=$(stat -c '%a' "$HOSTS_FILE" 2>/dev/null)
    orig_owner=$(stat -c '%u:%g' "$HOSTS_FILE" 2>/dev/null)
    mv "$tmp_file" "$HOSTS_FILE"
    [ -n "$orig_perms" ] && chmod "$orig_perms" "$HOSTS_FILE" 2>/dev/null
    [ -n "$orig_owner" ] && chown "$orig_owner" "$HOSTS_FILE" 2>/dev/null

    echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${match_label}${RESET} removed from fleet."
    log "hosts remove: $match_label ($match_ip)"
}

# ═══════════════════════════════════════════════════════════════════
# EDIT — Edit a host entry (IP, label, type, groups)
# Usage: freq hosts edit <label|IP> [--ip X] [--label X] [--type X] [--groups X]
# ═══════════════════════════════════════════════════════════════════
_hosts_edit() {
    require_admin || return 1

    local target="${1:-}"
    [ -z "$target" ] && { echo "Usage: freq hosts edit <label|IP> [--ip X] [--label X] [--type X] [--groups X]"; return 1; }
    shift

    [ ! -f "$HOSTS_FILE" ] && die "No hosts file found at $HOSTS_FILE."

    load_hosts
    local match_idx=-1 i
    for ((i=0; i<HOST_COUNT; i++)); do
        if [ "${HOST_LABELS[$i]}" = "$target" ] || [ "${HOST_IPS[$i]}" = "$target" ]; then
            match_idx=$i
            break
        fi
    done
    [ "$match_idx" -eq -1 ] && die "No host found matching '$target'."

    local old_ip="${HOST_IPS[$match_idx]}"
    local old_label="${HOST_LABELS[$match_idx]}"
    local old_type="${HOST_TYPES[$match_idx]}"
    local old_groups="${HOST_GROUPS[$match_idx]}"

    local new_ip="$old_ip" new_label="$old_label" new_type="$old_type" new_groups="$old_groups"

    # Parse flags
    while [ $# -gt 0 ]; do
        case "$1" in
            --ip)     new_ip="$2"; shift 2 ;;
            --label)  new_label="$2"; shift 2 ;;
            --type)   new_type="$2"; shift 2 ;;
            --groups) new_groups="$2"; shift 2 ;;
            *)        echo "Unknown option: $1"; return 1 ;;
        esac
    done

    # If no flags given, go interactive
    if [ "$new_ip" = "$old_ip" ] && [ "$new_label" = "$old_label" ] && \
       [ "$new_type" = "$old_type" ] && [ "$new_groups" = "$old_groups" ]; then
        echo -e "    Current: ${BOLD}${old_label}${RESET} (${old_ip}) [${old_type}] groups=${old_groups}"
        echo ""
        read -rp "    New IP [$old_ip]: " new_ip; new_ip="${new_ip:-$old_ip}"
        read -rp "    New label [$old_label]: " new_label; new_label="${new_label:-$old_label}"
        read -rp "    New type [$old_type]: " new_type; new_type="${new_type:-$old_type}"
        read -rp "    New groups [$old_groups]: " new_groups; new_groups="${new_groups:-$old_groups}"
    fi

    # Validate changes
    [ "$new_ip" != "$old_ip" ] && validate_ip "$new_ip"
    [ "$new_label" != "$old_label" ] && validate_label "$new_label"
    case "$new_type" in
        linux|truenas|pfsense|switch|external|idrac) ;;
        *) die "Invalid type: '$new_type'." ;;
    esac

    # Check for duplicate IP/label conflicts (other hosts)
    for ((i=0; i<HOST_COUNT; i++)); do
        [ "$i" -eq "$match_idx" ] && continue
        [ "${HOST_IPS[$i]}" = "$new_ip" ] && die "IP $new_ip already used by ${HOST_LABELS[$i]}."
        [ "${HOST_LABELS[$i]}" = "$new_label" ] && die "Label '$new_label' already used by ${HOST_IPS[$i]}."
    done

    if [ "$new_ip" = "$old_ip" ] && [ "$new_label" = "$old_label" ] && \
       [ "$new_type" = "$old_type" ] && [ "$new_groups" = "$old_groups" ]; then
        echo -e "    ${DIM}No changes.${RESET}"
        return 0
    fi

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "    ${CYAN}[DRY-RUN]${RESET} Would update ${old_label}:"
        [ "$new_ip" != "$old_ip" ] && echo -e "      IP: ${old_ip} ${_ARROW} ${new_ip}"
        [ "$new_label" != "$old_label" ] && echo -e "      Label: ${old_label} ${_ARROW} ${new_label}"
        [ "$new_type" != "$old_type" ] && echo -e "      Type: ${old_type} ${_ARROW} ${new_type}"
        [ "$new_groups" != "$old_groups" ] && echo -e "      Groups: ${old_groups} ${_ARROW} ${new_groups}"
        return 0
    fi

    freq_action_modify "Updating host entry..."
    backup_config "$HOSTS_FILE"

    # Replace the line matching old_label
    local tmp_file="${HOSTS_FILE}.tmp.$$"
    awk -v old_lbl="$old_label" -v new_line="$(printf '%-14s  %-18s  %-10s  %s' "$new_ip" "$new_label" "$new_type" "$new_groups")" '
        /^[[:space:]]*#/ { print; next }
        /^[[:space:]]*$/ { print; next }
        { if ($2 == old_lbl) print new_line; else print }
    ' "$HOSTS_FILE" > "$tmp_file"

    local orig_perms orig_owner
    orig_perms=$(stat -c '%a' "$HOSTS_FILE" 2>/dev/null)
    orig_owner=$(stat -c '%u:%g' "$HOSTS_FILE" 2>/dev/null)
    mv "$tmp_file" "$HOSTS_FILE"
    [ -n "$orig_perms" ] && chmod "$orig_perms" "$HOSTS_FILE" 2>/dev/null
    [ -n "$orig_owner" ] && chown "$orig_owner" "$HOSTS_FILE" 2>/dev/null

    echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${new_label}${RESET} updated."
    [ "$new_ip" != "$old_ip" ] && echo -e "      IP: ${old_ip} ${_ARROW} ${new_ip}"
    [ "$new_label" != "$old_label" ] && echo -e "      Label: ${old_label} ${_ARROW} ${new_label}"
    [ "$new_type" != "$old_type" ] && echo -e "      Type: ${old_type} ${_ARROW} ${new_type}"
    [ "$new_groups" != "$old_groups" ] && echo -e "      Groups: ${old_groups} ${_ARROW} ${new_groups}"
    log "hosts edit: $old_label -> $new_label ($new_ip) [$new_type] groups=$new_groups"
}

# ═══════════════════════════════════════════════════════════════════
# IMPORT — Bulk import hosts from a file
# File format: IP LABEL TYPE GROUPS (one per line, # comments OK)
# ═══════════════════════════════════════════════════════════════════
_hosts_import() {
    require_admin || return 1

    local import_file="${1:-}"
    [ -z "$import_file" ] && { echo "Usage: freq hosts import <file>"; return 1; }
    [ ! -f "$import_file" ] && die "Import file not found: $import_file"

    load_hosts
    local added=0 skipped=0 errors=0 line_num=0

    echo ""
    freq_header "Import Hosts"
    echo ""

    while IFS= read -r line; do
        line_num=$((line_num + 1))

        # Skip comments and blank lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue

        local imp_ip imp_label imp_type imp_groups
        read -r imp_ip imp_label imp_type imp_groups <<< "$line"

        [ -z "$imp_ip" ] || [ -z "$imp_label" ] && {
            echo -e "    ${YELLOW}${_WARN}${RESET}  Line $line_num: missing IP or label, skipping"
            errors=$((errors + 1))
            continue
        }

        imp_type="${imp_type:-linux}"
        imp_groups="${imp_groups:-prod}"

        # Validate
        if ! [[ "$imp_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo -e "    ${YELLOW}${_WARN}${RESET}  Line $line_num: invalid IP '$imp_ip', skipping"
            errors=$((errors + 1))
            continue
        fi

        case "$imp_type" in
            linux|truenas|pfsense|switch|external|idrac) ;;
            *) echo -e "    ${YELLOW}${_WARN}${RESET}  Line $line_num: invalid type '$imp_type', skipping"
               errors=$((errors + 1)); continue ;;
        esac

        # Check duplicates against current fleet
        local dup=false i
        for ((i=0; i<HOST_COUNT; i++)); do
            if [ "${HOST_IPS[$i]}" = "$imp_ip" ] || [ "${HOST_LABELS[$i]}" = "$imp_label" ]; then
                echo -e "    ${DIM}Skipping ${imp_label} (${imp_ip}): already in fleet${RESET}"
                skipped=$((skipped + 1))
                dup=true
                break
            fi
        done
        $dup && continue

        # Also check against entries added this session
        if grep -qP "^\Q${imp_ip}\E\s" "$HOSTS_FILE" 2>/dev/null; then
            echo -e "    ${DIM}Skipping ${imp_label}: IP duplicate in file${RESET}"
            skipped=$((skipped + 1))
            continue
        fi

        if [ "${DRY_RUN}" = "true" ]; then
            echo -e "    ${CYAN}[DRY-RUN]${RESET} Would add ${imp_label} (${imp_ip}) [${imp_type}]"
            added=$((added + 1))
            continue
        fi

        printf "%-14s  %-18s  %-10s  %s\n" "$imp_ip" "$imp_label" "$imp_type" "$imp_groups" >> "$HOSTS_FILE"
        echo -e "    ${GREEN}${_TICK}${RESET}  ${imp_label} (${imp_ip}) [${imp_type}]"
        added=$((added + 1))

        # Update in-memory arrays so subsequent dupe checks work
        HOST_IPS+=("$imp_ip")
        HOST_LABELS+=("$imp_label")
        HOST_TYPES+=("$imp_type")
        HOST_GROUPS+=("$imp_groups")
        HOST_COUNT=$((HOST_COUNT + 1))
    done < "$import_file"

    echo ""
    echo -e "    ${BOLD}Import complete:${RESET} ${GREEN}${added} added${RESET}, ${DIM}${skipped} skipped${RESET}, ${YELLOW}${errors} errors${RESET}"
    freq_footer

    [ "$added" -gt 0 ] && log "hosts import: $added added from $import_file ($skipped skipped, $errors errors)"
}

# ═══════════════════════════════════════════════════════════════════
# DISCOVER — Scan PVE cluster for VMs not in hosts.conf
#
# Globals set for callers:
#   _disc_count       — number of unregistered VMs found
#   _disc_vmids[]     — VMID array
#   _disc_names[]     — PVE name array
#   _disc_ips[]       — IP array (from guest-agent or "unknown")
#   _disc_nodes[]     — PVE node array
#   _disc_statuses[]  — running/stopped array
# ═══════════════════════════════════════════════════════════════════
_disc_count=0
declare -ga _disc_vmids=() _disc_names=() _disc_ips=() _disc_nodes=() _disc_statuses=()

cmd_discover() {
    require_operator || return 1
    require_ssh_key

    echo ""
    freq_header "Discover VMs"
    freq_blank
    echo -e "    ${DIM}Scanning PVE cluster for unregistered VMs...${RESET}"
    echo ""

    load_hosts

    # Build set of known IPs for duplicate checking
    declare -A _known_ips=()
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        _known_ips["${HOST_IPS[$i]}"]=1
    done

    # Scan each PVE node
    _disc_count=0
    _disc_vmids=() _disc_names=() _disc_ips=() _disc_nodes=() _disc_statuses=()

    local node_idx
    for ((node_idx=0; node_idx<${#PVE_NODES[@]}; node_idx++)); do
        local node_ip="${PVE_NODES[$node_idx]}"
        local node_name="${PVE_NODE_NAMES[$node_idx]}"

        freq_debug "Scanning $node_name ($node_ip)..."

        local json
        json=$(freq_ssh "$node_ip" "pvesh get /nodes/${node_name}/qemu --output-format json 2>/dev/null" 2>/dev/null) || continue
        [ -z "$json" ] || [ "$json" = "[]" ] && continue

        local parsed
        parsed=$(echo "$json" | python3 -c "
import sys, json
try:
    vms = json.loads(sys.stdin.read())
    for vm in sorted(vms, key=lambda v: v.get('vmid', 0)):
        if vm.get('template', 0) == 1:
            continue
        vmid = vm.get('vmid', 0)
        name = vm.get('name', '?')
        status = vm.get('status', '?')
        print(f'{vmid}|{name}|{status}')
except Exception:
    pass
" 2>/dev/null) || continue

        while IFS='|' read -r vmid vmname vmstatus; do
            [ -z "$vmid" ] && continue

            # Try to get IP from guest-agent (only for running VMs)
            local vm_ip="unknown"
            if [ "$vmstatus" = "running" ]; then
                local agent_out
                agent_out=$(freq_ssh "$node_ip" "qm guest cmd ${vmid} network-get-interfaces 2>/dev/null" 2>/dev/null)
                if [ -n "$agent_out" ]; then
                    local found_ip
                    found_ip=$(echo "$agent_out" | python3 -c "
import sys, json
try:
    ifaces = json.loads(sys.stdin.read())
    for iface in ifaces:
        if iface.get('name', '') in ('lo', 'lo0'):
            continue
        for addr in iface.get('ip-addresses', []):
            ip = addr.get('ip-address', '')
            if ip and not ip.startswith('127.') and not ip.startswith('fe80'):
                print(ip)
                raise SystemExit(0)
except SystemExit:
    pass
except Exception:
    pass
" 2>/dev/null)
                    [ -n "$found_ip" ] && vm_ip="$found_ip"
                fi
            fi

            # Check if already registered
            local already_known=false
            if [ "$vm_ip" != "unknown" ] && [ -n "${_known_ips[$vm_ip]:-}" ]; then
                already_known=true
            fi
            # Check vmXXX label pattern in hosts.conf
            if [ -f "$HOSTS_FILE" ] && grep -q "vm${vmid}" "$HOSTS_FILE" 2>/dev/null; then
                already_known=true
            fi

            if ! $already_known; then
                _disc_vmids+=("$vmid")
                _disc_names+=("$vmname")
                _disc_ips+=("$vm_ip")
                _disc_nodes+=("$node_name")
                _disc_statuses+=("$vmstatus")
                _disc_count=$((_disc_count + 1))
            fi
        done <<< "$parsed"
    done

    # Display results
    if [ "$_disc_count" -eq 0 ]; then
        echo -e "    ${GREEN}${_TICK}${RESET}  All cluster VMs are registered in hosts.conf."
        echo -e "    ${DIM}${HOST_COUNT} hosts in fleet, 0 unregistered VMs found.${RESET}"
        freq_blank
        freq_footer
        return 0
    fi

    echo -e "    ${YELLOW}${_WARN}${RESET}  ${BOLD}${_disc_count} unregistered VM(s) found:${RESET}"
    echo ""
    printf "    ${DIM}%-4s  %-5s  %-22s %-17s %-8s %s${RESET}\n" "#" "VMID" "Name" "IP" "Status" "Node"
    freq_footer

    local d
    for ((d=0; d<_disc_count; d++)); do
        local _icon="${GREEN}${_TICK}${RESET}"
        [ "${_disc_statuses[$d]}" = "stopped" ] && _icon="${RED}${_CROSS}${RESET}"
        [ "${_disc_ips[$d]}" = "unknown" ] && _icon="${YELLOW}?${RESET}"
        printf "    %b %-4s  %-5s  %-22s %-17s %-8s %s\n" \
            "$_icon" "$((d+1))" "${_disc_vmids[$d]}" "${_disc_names[$d]}" \
            "${_disc_ips[$d]}" "${_disc_statuses[$d]}" "${_disc_nodes[$d]}"
    done
    echo ""
    echo -e "    ${DIM}${_disc_count} unregistered ${_BULLET} ${HOST_COUNT} in fleet${RESET}"
    freq_footer

    # Offer to add (interactive, not --quiet)
    if [ "${1:-}" != "--quiet" ] && [ -t 0 ]; then
        _discover_select_and_add
    fi
}

# ═══════════════════════════════════════════════════════════════════
# DISCOVER SELECT + ADD — Interactive VM selection from discover
# ═══════════════════════════════════════════════════════════════════
_discover_select_and_add() {
    echo ""
    echo -e "    ${BOLD}Select VMs to add to fleet:${RESET}"
    echo -e "    ${DIM}Enter numbers separated by spaces, a range (1-3), or 'all'. Press Enter to skip.${RESET}"
    echo ""
    read -rp "    Select []: " _pick_input
    [ -z "$_pick_input" ] && return 0

    # Parse selection into indices
    local -a selected_indices=()
    if [ "$_pick_input" = "all" ]; then
        local _si
        for ((_si=0; _si<_disc_count; _si++)); do
            selected_indices+=("$_si")
        done
    else
        local _token
        for _token in $_pick_input; do
            if [[ "$_token" =~ ^([0-9]+)-([0-9]+)$ ]]; then
                local _from="${BASH_REMATCH[1]}" _to="${BASH_REMATCH[2]}"
                local _ri
                for ((_ri=_from; _ri<=_to; _ri++)); do
                    if (( _ri >= 1 && _ri <= _disc_count )); then
                        selected_indices+=($((_ri - 1)))
                    fi
                done
            elif [[ "$_token" =~ ^[0-9]+$ ]] && (( _token >= 1 && _token <= _disc_count )); then
                selected_indices+=($((_token - 1)))
            fi
        done
    fi

    if [ ${#selected_indices[@]} -eq 0 ]; then
        echo -e "    ${DIM}No valid selection.${RESET}"
        return 0
    fi

    echo ""
    echo -e "    ${BOLD}Selected ${#selected_indices[@]} VM(s) for fleet onboarding:${RESET}"
    local _si
    for _si in "${selected_indices[@]}"; do
        echo -e "      VM ${_disc_vmids[$_si]} (${_disc_names[$_si]}) on ${_disc_nodes[$_si]}"
    done
    echo ""
    local _proceed
    read -rp "    Proceed? [Y/n]: " _proceed
    [[ "$_proceed" =~ ^[Nn] ]] && return 0

    # Process each selected VM
    local _added=0 _failed=0
    for _si in "${selected_indices[@]}"; do
        local d_vmid="${_disc_vmids[$_si]}"
        local d_name="${_disc_names[$_si]}"
        local d_ip="${_disc_ips[$_si]}"

        echo ""
        freq_footer
        echo -e "    ${BOLD}Adding VM ${d_vmid} (${d_name})${RESET}"
        echo ""

        # Suggest a label
        local suggested_label
        suggested_label=$(echo "$d_name" | tr '[:upper:]' '[:lower:]' | tr ' _' '--')
        suggested_label="vm${d_vmid}-${suggested_label}"

        if [ "$d_ip" = "unknown" ]; then
            read -rp "    IP address (required): " d_ip
            [ -z "$d_ip" ] && { echo -e "    ${RED}Skipped: IP required.${RESET}"; _failed=$((_failed + 1)); continue; }
        else
            local _new_ip
            read -rp "    IP address [$d_ip]: " _new_ip
            [ -n "$_new_ip" ] && d_ip="$_new_ip"
        fi

        local _new_label
        read -rp "    Label [$suggested_label]: " _new_label
        local final_label="${_new_label:-$suggested_label}"

        local _new_groups
        read -rp "    Groups [prod]: " _new_groups
        local final_groups="${_new_groups:-prod}"

        # Add to hosts.conf (skip key deploy — user can bootstrap later)
        _hosts_add "$d_ip" "$final_label" "linux" "$final_groups" "--skip-key"
        if [ $? -eq 0 ]; then
            _added=$((_added + 1))
        else
            _failed=$((_failed + 1))
        fi

        # Offer full onboard if fleet.sh is available
        if type -t cmd_bootstrap &>/dev/null; then
            echo ""
            local _do_onboard
            read -rp "    Run bootstrap for ${final_label}? [Y/n]: " _do_onboard
            if [[ ! "$_do_onboard" =~ ^[Nn] ]]; then
                cmd_bootstrap "$final_label" --yes 2>/dev/null || \
                    echo -e "    ${YELLOW}${_WARN}${RESET}  Bootstrap had issues. Run manually: freq bootstrap ${final_label}"
            fi
        fi
    done

    echo ""
    echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${_added} VM(s) added to fleet${RESET}"
    [ "$_failed" -gt 0 ] && echo -e "    ${YELLOW}${_WARN}${RESET}  ${_failed} skipped/failed"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# DISCOVER ONBOARD — Streamlined onboard for discovered VMs
# Used by fleet.sh / onboard when available
# Handles: NIC profile, host octet, bootstrap, configure
# ═══════════════════════════════════════════════════════════════════
_discover_onboard_vm() {
    local vmid="$1" label="$2" ip="$3" node="$4" groups="$5"

    # Find the PVE node IP
    local node_ip="" _ni
    for ((_ni=0; _ni<${#PVE_NODE_NAMES[@]}; _ni++)); do
        if [ "${PVE_NODE_NAMES[$_ni]}" = "$node" ]; then
            node_ip="${PVE_NODES[$_ni]}"
            break
        fi
    done
    [ -z "$node_ip" ] && { echo -e "    ${RED}Cannot find node IP for ${node}${RESET}"; return 1; }

    # Step 1: NIC Profile
    echo ""
    echo -e "    ${BOLD}Step 1: NIC Profile${RESET}"
    echo -e "      ${DIM}[1] standard  -- MGMT (2550) + STORAGE (25)${RESET}"
    echo -e "      ${DIM}[2] public    -- MGMT (2550) + STORAGE (25) + PUBLIC (5)${RESET}"
    echo -e "      ${DIM}[3] dirty     -- DIRTY (66) + MGMT (2550) + STORAGE (25)${RESET}"
    echo -e "      ${DIM}[4] minimal   -- MGMT (2550) only${RESET}"
    echo -e "      ${DIM}[5] skip      -- Keep current NICs${RESET}"
    echo ""
    local _nic_choice
    read -rp "    NIC profile [1]: " _nic_choice
    _nic_choice="${_nic_choice:-1}"

    if [ "$_nic_choice" != "5" ] && [ "$_nic_choice" != "skip" ]; then
        local profile_name="" profile_vlans=""
        case "$_nic_choice" in
            1|standard) profile_name="standard"; profile_vlans="${NIC_PROFILES[standard]:-}" ;;
            2|public)   profile_name="public";   profile_vlans="${NIC_PROFILES[public]:-}" ;;
            3|dirty)    profile_name="dirty";    profile_vlans="${NIC_PROFILES[dirty]:-}" ;;
            4|minimal)  profile_name="minimal";  profile_vlans="${NIC_PROFILES[minimal]:-}" ;;
            *) echo -e "    ${YELLOW}Invalid selection. NIC setup skipped.${RESET}"; profile_vlans="" ;;
        esac

        if [ -n "$profile_vlans" ]; then
            IFS="," read -ra nic_vlans <<< "$profile_vlans"

            # Step 2: Host octet
            echo ""
            echo -e "    ${BOLD}Step 2: Host Address${RESET}"
            echo -e "    ${DIM}Same last octet on every VLAN.${RESET}"
            local _v _vname _vprefix
            for _v in "${nic_vlans[@]}"; do
                _vname="${VLAN_NAMES[$_v]:-VLAN$_v}"
                _vprefix="${VLAN_PREFIXES[$_v]:-?}"
                echo -e "      ${DIM}${_vname}: ${_vprefix}.???${RESET}"
            done
            echo ""
            local host_octet
            read -rp "    Host number (last octet): " host_octet
            [[ "$host_octet" =~ ^[0-9]+$ ]] || { echo -e "    ${YELLOW}Invalid. NIC setup skipped.${RESET}"; return 0; }

            # Remove existing NICs
            local cur_nic_count
            cur_nic_count=$(freq_ssh "$node_ip" "qm config $vmid" 2>/dev/null | grep -c '^net' || echo 0)
            local _rn
            for ((_rn=0; _rn<cur_nic_count; _rn++)); do
                freq_ssh "$node_ip" "qm set $vmid --delete net${_rn}" 2>/dev/null || true
            done

            # Add new NICs with VLAN tags + cloud-init ipconfigs
            local _n=0
            for _v in "${nic_vlans[@]}"; do
                _vname="${VLAN_NAMES[$_v]:-VLAN$_v}"
                local fw_flag="firewall=1"
                [ "$_v" = "25" ] && fw_flag="firewall=0"

                local nic_opts="virtio,bridge=${NIC_BRIDGE:-vmbr0},${fw_flag},tag=${_v}"
                printf "    %-35s " "net${_n} ${_ARROW} VLAN ${_v} (${_vname})"
                if freq_ssh "$node_ip" "qm set $vmid --net${_n} '${nic_opts}'" 2>/dev/null; then
                    echo -e "${GREEN}OK${RESET}"
                else
                    echo -e "${RED}FAILED${RESET}"
                fi

                # Set cloud-init ipconfig
                _vprefix="${VLAN_PREFIXES[$_v]:-10.25.0}"
                local _ip="${_vprefix}.${host_octet}"
                local _gw="${VLAN_GATEWAYS[$_v]:-}"
                local ipconf="ip=${_ip}/24"
                [ -n "$_gw" ] && ipconf+=",gw=${_gw}"
                freq_ssh "$node_ip" "qm set $vmid --ipconfig${_n} '${ipconf}'" 2>/dev/null || true

                _n=$((_n + 1))
            done

            # Update nameserver (from freq.conf)
            freq_ssh "$node_ip" "qm set $vmid --nameserver '${VM_NAMESERVER:-1.1.1.1}'" 2>/dev/null || true

            # Update hosts.conf with the MGMT IP
            local mgmt_ip=""
            for ((_n=0; _n<${#nic_vlans[@]}; _n++)); do
                if [ "${nic_vlans[$_n]}" = "2550" ]; then
                    mgmt_ip="${VLAN_PREFIXES[2550]:-10.25.255}.${host_octet}"
                    break
                fi
            done
            if [ -n "$mgmt_ip" ] && [ "$mgmt_ip" != "$ip" ]; then
                sed -i "s|^${ip}|${mgmt_ip}|" "$HOSTS_FILE" 2>/dev/null || true
                ip="$mgmt_ip"
                echo -e "    ${DIM}Updated hosts.conf IP ${_ARROW} ${mgmt_ip}${RESET}"
            fi

            echo -e "    ${GREEN}${_TICK}${RESET}  NIC profile: ${BOLD}${profile_name}${RESET}"
            echo ""
            for ((_n=0; _n<${#nic_vlans[@]}; _n++)); do
                _v="${nic_vlans[$_n]}"
                _vname="${VLAN_NAMES[$_v]:-VLAN$_v}"
                _vprefix="${VLAN_PREFIXES[$_v]:-10.25.0}"
                local _gw="${VLAN_GATEWAYS[$_v]:-}"
                if [ -n "$_gw" ]; then
                    echo -e "      net${_n}: ${_vprefix}.${host_octet} (${_vname}) gw=${_gw}"
                else
                    echo -e "      net${_n}: ${_vprefix}.${host_octet} (${_vname})"
                fi
            done
        fi
    fi

    # Step 3: Offer bootstrap
    echo ""
    echo -e "    ${BOLD}Step 3: Bootstrap${RESET}"
    local _do_boot
    read -rp "    Run bootstrap (SSH keys + ${FREQ_SERVICE_ACCOUNT})? [Y/n]: " _do_boot
    if [[ ! "$_do_boot" =~ ^[Nn] ]]; then
        if type -t cmd_bootstrap &>/dev/null; then
            cmd_bootstrap "$label" --yes 2>/dev/null || \
                echo -e "    ${YELLOW}${_WARN}${RESET}  Bootstrap had issues. Run manually: freq bootstrap ${label}"
        else
            echo -e "    ${DIM}Bootstrap module not yet installed. Run later: freq bootstrap ${label}${RESET}"
        fi
    fi

    # Step 4: Offer configure
    echo ""
    echo -e "    ${BOLD}Step 4: Configure${RESET}"
    local _do_conf
    read -rp "    Run configure (hardening, packages, hostname)? [Y/n]: " _do_conf
    if [[ ! "$_do_conf" =~ ^[Nn] ]]; then
        if type -t cmd_configure &>/dev/null; then
            cmd_configure "$label" -y 2>/dev/null || \
                echo -e "    ${YELLOW}${_WARN}${RESET}  Configure had issues. Run manually: freq configure ${label}"
        else
            echo -e "    ${DIM}Configure module not yet installed. Run later: freq configure ${label}${RESET}"
        fi
    fi

    echo ""
    echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${label} onboarded!${RESET}"
    log "discover-onboard: $label ($ip) vmid=$vmid node=$node"
}

# ═══════════════════════════════════════════════════════════════════
# GROUPS — Host group management
# ═══════════════════════════════════════════════════════════════════
cmd_groups() {
    case "${1:-list}" in
        list|ls)     _groups_list ;;
        add)         shift; _groups_add "$@" ;;
        remove|rm)   shift; _groups_remove "$@" ;;
        --help|-h)   _groups_usage ;;
        *)           echo "Unknown subcommand: $1"; _groups_usage; return 1 ;;
    esac
}

_groups_usage() {
    echo ""
    freq_header "Host Groups"
    freq_blank
    freq_line "${BOLD}${WHITE}Usage:${RESET}  freq groups <subcommand>"
    freq_blank
    freq_line "  ${PURPLELIGHT}list${RESET}              Show all groups with host counts"
    freq_line "  ${PURPLELIGHT}add${RESET} <name> [desc]  Add a group definition"
    freq_line "  ${PURPLELIGHT}remove${RESET} <name>      Remove a group definition"
    freq_blank
    freq_line "${DIM}Groups are assigned per-host in hosts.conf (comma-separated).${RESET}"
    freq_line "${DIM}Group definitions with descriptions are stored in groups.conf.${RESET}"
    freq_blank
    freq_footer
}

_groups_list() {
    require_operator || return 1
    load_hosts

    echo ""
    freq_header "Host Groups"
    echo ""

    # Count hosts per group
    declare -A group_counts=()
    local i g
    for ((i=0; i<HOST_COUNT; i++)); do
        IFS=',' read -ra _grps <<< "${HOST_GROUPS[$i]}"
        for g in "${_grps[@]}"; do
            [ -n "$g" ] && group_counts[$g]=$(( ${group_counts[$g]:-0} + 1 ))
        done
    done

    # Also include groups from groups.conf that have no hosts
    if [ -f "$GROUPS_FILE" ]; then
        while IFS=: read -r gname gdesc; do
            [[ "$gname" =~ ^#|^$ ]] && continue
            gname="${gname#"${gname%%[![:space:]]*}"}"
            [ -z "$gname" ] && continue
            [ -z "${group_counts[$gname]:-}" ] && group_counts[$gname]=0
        done < "$GROUPS_FILE"
    fi

    if [ ${#group_counts[@]} -eq 0 ]; then
        echo -e "    ${DIM}No groups found. Assign groups when adding hosts:${RESET}"
        echo -e "    ${DIM}  freq hosts add <IP> <label> linux prod,docker${RESET}"
        echo ""
        freq_footer
        return 0
    fi

    printf "    ${DIM}%-16s %-7s %s${RESET}\n" "Group" "Hosts" "Description"
    freq_footer

    for g in $(echo "${!group_counts[@]}" | tr ' ' '\n' | sort); do
        local desc=""
        if [ -f "$GROUPS_FILE" ]; then
            desc=$(grep "^${g}:" "$GROUPS_FILE" 2>/dev/null | cut -d: -f2-)
            desc="${desc#"${desc%%[![:space:]]*}"}"
        fi
        printf "    %-16s %-7d %s\n" "$g" "${group_counts[$g]}" "${desc:-}"
    done

    echo ""
    echo -e "    ${DIM}Usage: freq exec -g <group> <command>${RESET}"
    freq_footer
}

_groups_add() {
    require_admin || return 1

    local gname="${1:-}"
    [ -z "$gname" ] && { echo "Usage: freq groups add <name> [description]"; return 1; }
    shift
    local gdesc="$*"

    # Validate name
    [[ "$gname" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || die "Invalid group name: '$gname'. Use alphanumeric, hyphens, underscores."

    # Check if already defined in groups.conf
    if [ -f "$GROUPS_FILE" ] && grep -q "^${gname}:" "$GROUPS_FILE" 2>/dev/null; then
        echo -e "    ${DIM}Group '$gname' already defined in groups.conf.${RESET}"
        return 0
    fi

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "    ${CYAN}[DRY-RUN]${RESET} Would add group '$gname' to groups.conf"
        return 0
    fi

    echo "${gname}:${gdesc}" >> "$GROUPS_FILE" 2>/dev/null || die "Cannot write to $GROUPS_FILE."
    echo -e "    ${GREEN}${_TICK}${RESET}  Group ${BOLD}${gname}${RESET} added."
    [ -n "$gdesc" ] && echo -e "    ${DIM}Description: ${gdesc}${RESET}"
    log "groups add: $gname ($gdesc)"
}

_groups_remove() {
    require_admin || return 1

    local gname="${1:-}"
    [ -z "$gname" ] && { echo "Usage: freq groups remove <name>"; return 1; }

    if [ ! -f "$GROUPS_FILE" ] || ! grep -q "^${gname}:" "$GROUPS_FILE" 2>/dev/null; then
        die "Group '$gname' not found in groups.conf. Note: this only removes the group definition, not group assignments in hosts.conf."
    fi

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "    ${CYAN}[DRY-RUN]${RESET} Would remove group '$gname' from groups.conf"
        return 0
    fi

    local tmp_file="${GROUPS_FILE}.tmp.$$"
    grep -v "^${gname}:" "$GROUPS_FILE" > "$tmp_file"
    local orig_perms orig_owner
    orig_perms=$(stat -c '%a' "$GROUPS_FILE" 2>/dev/null)
    orig_owner=$(stat -c '%u:%g' "$GROUPS_FILE" 2>/dev/null)
    mv "$tmp_file" "$GROUPS_FILE"
    [ -n "$orig_perms" ] && chmod "$orig_perms" "$GROUPS_FILE" 2>/dev/null
    [ -n "$orig_owner" ] && chown "$orig_owner" "$GROUPS_FILE" 2>/dev/null

    echo -e "    ${GREEN}${_TICK}${RESET}  Group ${BOLD}${gname}${RESET} removed from groups.conf."
    echo -e "    ${DIM}Note: hosts still assigned to '$gname' in hosts.conf are unchanged. Use 'freq hosts edit' to update.${RESET}"
    log "groups remove: $gname"
}
