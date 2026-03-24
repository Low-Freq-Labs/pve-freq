#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/users.sh
# User Lifecycle, Password Management, RBAC
#
# Author:  FREQ Project
# -- the roster. who's in, who's out. --
#
# Commands: cmd_users, cmd_passwd, cmd_new_user, cmd_install_user,
#           cmd_promote, cmd_demote, cmd_roles
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh, validate.sh, vault.sh
# =============================================================================

# Globals from resolve.sh load_hosts(): HOST_IPS, HOST_LABELS, HOST_TYPES, HOST_COUNT, HOST_GROUPS
# Globals from core.sh: IMMUTABLE_ACCOUNTS, PRIV_ACCOUNTS
# Globals from fmt.sh: GREEN, RED, YELLOW, BOLD, DIM, RESET, _TICK, _CROSS, _WARN, _ARROW, _DASH

# ═══════════════════════════════════════════════════════════════════
# USER REGISTRY HELPERS
# ═══════════════════════════════════════════════════════════════════

# lookup_user <username> — sets REG_UID, REG_GID, REG_GROUP on success
lookup_user() {
    local target="$1" line
    line=$(grep "^${target}:" "$USERS_FILE" 2>/dev/null) || return 1
    IFS=: read -r _ REG_UID REG_GID REG_GROUP <<< "$line"
}

# next_uid — prints next available UID in UID_MIN..UID_MAX range
next_uid() {
    local used=()
    while IFS=: read -r _ uid _ _; do
        used+=("$uid")
    done < <(grep -v '^#' "$USERS_FILE" 2>/dev/null | grep -v '^$')
    local r
    for r in $RESERVED_UIDS; do used+=("$r"); done
    local uid
    for ((uid=UID_MIN; uid<=UID_MAX; uid++)); do
        local taken=false u
        for u in "${used[@]}"; do
            [ "$uid" = "$u" ] && { taken=true; break; }
        done
        $taken || { echo "$uid"; return 0; }
    done
    die "No available UIDs in range ${UID_MIN}-${UID_MAX}."
}

# update_credential <file> <password> — write password to file with tight perms
_users_update_credential() {
    local file="$1" password="$2"
    ( umask 077; echo "$password" > "$file" )
}

# _users_ensure_registry — create users.conf if missing
_users_ensure_registry() {
    if [ ! -f "$USERS_FILE" ]; then
        cat > "$USERS_FILE" <<'HDR'
# PVE FREQ User Registry — username:uid:gid:groupname
# UID range: 3000-3999 (3003 reserved for svc-admin)
HDR
        chmod 640 "$USERS_FILE"
        freq_debug "Created empty users.conf"
    fi
}

# _users_ensure_roles — create roles.conf if missing
_users_ensure_roles() {
    if [ ! -f "$ROLES_FILE" ]; then
        cat > "$ROLES_FILE" <<'HDR'
# PVE FREQ Roles — username:role
# Roles: admin, operator, viewer
HDR
        chmod 640 "$ROLES_FILE"
        freq_debug "Created empty roles.conf"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# REMOTE USER OPERATIONS
# ═══════════════════════════════════════════════════════════════════

# _users_change_remote_password <ip> <type> <username> <password>
# Returns: OK | FAILED | __MISSING__ | skip (...)
_users_change_remote_password() {
    local host="$1" htype="$2" username="$3" password="$4"

    case "$htype" in
        linux)
            freq_ssh "$host" "id '$username'" &>/dev/null || { echo "__MISSING__"; return; }
            freq_ssh "$host" "echo '${username}:${password}' | sudo chpasswd" &>/dev/null \
                && echo "OK" || echo "FAILED"
            ;;
        truenas)
            local exists
            exists=$(freq_ssh "$host" "sudo midclt call user.query '[[\"username\",\"=\",\"${username}\"]]'" 2>/dev/null)
            [ "$exists" = "[]" ] && { echo "__MISSING__"; return; }
            local uid_val
            uid_val=$(echo "$exists" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'])" 2>/dev/null)
            [ -z "$uid_val" ] && { echo "FAILED (cannot parse user id)"; return; }
            freq_ssh "$host" "sudo midclt call user.update $uid_val '{\"password\": \"${password}\"}'" &>/dev/null \
                && echo "OK" || echo "FAILED"
            ;;
        pfsense)
            freq_ssh "$host" "id '$username'" &>/dev/null || { echo "__MISSING__"; return; }
            freq_ssh "$host" "echo '${password}' | sudo pw usermod '${username}' -h 0" &>/dev/null \
                && echo "OK" || echo "FAILED"
            ;;
        switch)
            # Cisco IOS — legacy SSH + password auth + IOS config commands
            local switch_pass="" _lbl=""
            # Find host label for vault lookup
            load_hosts
            local _si
            for ((_si=0; _si<${HOST_COUNT:-0}; _si++)); do
                [ "${HOST_IPS[$_si]:-}" = "$host" ] && { _lbl="${HOST_LABELS[$_si]}"; break; }
            done
            # Get SSH password from vault (label-specific, then DEFAULT)
            [ -n "$_lbl" ] && switch_pass=$(vault_get "$_lbl" "${FREQ_SERVICE_ACCOUNT}-pass" 2>/dev/null)
            [ -z "$switch_pass" ] && switch_pass=$(vault_get "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" 2>/dev/null)
            [ -z "$switch_pass" ] && { echo "FAILED (no vault creds for switch)"; return; }
            export SSHPASS="$switch_pass"
            sshpass -e ssh -T \
                -o KexAlgorithms=+diffie-hellman-group14-sha1 \
                -o HostKeyAlgorithms=+ssh-rsa \
                -o PubkeyAcceptedKeyTypes=+ssh-rsa \
                -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
                -o StrictHostKeyChecking=no \
                -o ConnectTimeout=10 \
                "${REMOTE_USER}@${host}" <<IOSEOF 2>/dev/null
conf t
username $username secret 0 $password
end
wr
exit
IOSEOF
            local rc=$?
            unset SSHPASS
            [ $rc -eq 0 ] && echo "OK" || echo "FAILED"
            ;;
        idrac|external)
            echo "skip ($htype)"
            ;;
        *)
            echo "skip (unknown type: $htype)"
            ;;
    esac
}

# _users_create_remote <ip> <username> <uid> <gid> <group> <password>
# Returns: CREATED | CREATE FAILED
_users_create_remote() {
    local host="$1" username="$2" uid="$3" gid="$4" group="$5" password="$6"
    freq_ssh "$host" "
        getent group $gid >/dev/null 2>&1 || sudo groupadd -g $gid $group
        getent group ${SVC_GID} >/dev/null 2>&1 || sudo groupadd -g ${SVC_GID} ${FREQ_GROUP}
        sudo useradd -u $uid -g $gid -G ${FREQ_GROUP} -m -s /bin/bash '$username' 2>/dev/null
    " &>/dev/null
    local rc=$?
    if [ $rc -eq 0 ]; then
        freq_ssh "$host" "echo '${username}:${password}' | sudo chpasswd" &>/dev/null
        echo "CREATED"
    else
        echo "CREATE FAILED"
    fi
}

# _users_delete_from_fleet <username> <dry_run>
# Deletes user account from all fleet hosts
_users_delete_from_fleet() {
    local username="$1" dry_run="$2"
    require_ssh_key
    load_hosts

    local ok=0 fail=0 skip=0 i
    for ((i=0; i<HOST_COUNT; i++)); do
        local host="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        [ "$htype" != "linux" ] && { skip=$((skip + 1)); continue; }
        printf "      %-30s " "$label ($host)"
        if [ "$dry_run" = "true" ]; then
            echo "[DRY RUN] would delete"
            continue
        fi
        local result
        result=$(freq_ssh "$host" "
            if id '$username' &>/dev/null; then
                sudo pkill -u '$username' 2>/dev/null || true
                sudo userdel -r '$username' 2>/dev/null && echo 'DELETED' || echo 'FAILED'
            else
                echo 'NOT_FOUND'
            fi
        " 2>/dev/null)
        case "$result" in
            DELETED)   echo -e "${GREEN}${_TICK} deleted${RESET}"; ok=$((ok + 1)) ;;
            NOT_FOUND) echo -e "${DIM}not found${RESET}"; skip=$((skip + 1)) ;;
            *)         echo -e "${RED}${_CROSS} failed${RESET}"; fail=$((fail + 1)) ;;
        esac
    done
    echo ""
    echo -e "      ${DIM}Fleet cleanup: $ok deleted, $skip skipped, $fail failed${RESET}"
}

# ═══════════════════════════════════════════════════════════════════
# PASSWORD CHANGE — Fleet-wide
# ═══════════════════════════════════════════════════════════════════
cmd_passwd() {
    require_operator || return 1
    require_ssh_key
    freq_action_modify "Changing password across fleet..."

    local USERNAME="" dry_run=${DRY_RUN:-false}
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) dry_run=true ;;
            --help|-h)
                echo "Usage: freq passwd [username] [--dry-run]"
                echo ""
                echo "Change a user's password across all fleet hosts."
                echo "Operators can only change their own password."
                echo "Admins can change any user's password."
                return 0
                ;;
            -*) die "Unknown flag: $1. Use --help for usage." ;;
            *) [ -z "$USERNAME" ] && USERNAME="$1" ;;
        esac
        shift
    done

    [ -z "$USERNAME" ] && { echo ""; read -rp "    Username: " USERNAME; }
    [ -z "$USERNAME" ] && die "No username provided."
    validate_username "$USERNAME"

    # Operators can only change their own password
    local current_role
    current_role=$(_users_get_role "$(id -un)")
    if [ "$current_role" = "operator" ] && [ "$USERNAME" != "$(id -un)" ]; then
        die "Operators can only change their own password. Ask an admin to change others."
    fi

    # Only admins can change privileged account passwords
    if is_privileged "$USERNAME" && [ "$current_role" != "admin" ]; then
        die "Only admins can change passwords for privileged accounts (root, ${FREQ_SERVICE_ACCOUNT})."
    fi

    # Register user if not in registry and not privileged
    if ! is_privileged "$USERNAME"; then
        _users_ensure_registry
        if ! lookup_user "$USERNAME"; then
            echo ""
            echo -e "    ${YELLOW}'$USERNAME' is not in the user registry.${RESET}"
            read -rp "    Register now? [y/N]: " _reg
            if [[ "$_reg" =~ ^[Yy] ]]; then
                local new_uid
                new_uid=$(next_uid)
                echo "${USERNAME}:${new_uid}:${new_uid}:${USERNAME}" >> "$USERS_FILE"
                _users_ensure_roles
                if ! grep -q "^${USERNAME}:" "$ROLES_FILE" 2>/dev/null; then
                    echo "${USERNAME}:operator" >> "$ROLES_FILE"
                fi
                echo -e "      ${GREEN}${_TICK}${RESET} Registered: $USERNAME (uid=$new_uid)"
                lookup_user "$USERNAME" || die "Registration failed."
            else
                die "Cannot proceed without registration."
            fi
        fi
    fi

    # Confirmation for privileged accounts
    if is_privileged "$USERNAME" && ! $dry_run; then
        echo ""
        freq_header "PRIVILEGED PASSWORD CHANGE"
        freq_line "${BOLD}Account: ${USERNAME}${RESET}"
        freq_line "${DIM}This affects ALL hosts in the fleet.${RESET}"
        freq_footer
        echo ""
        read -rp "    Type 'CONFIRM' to proceed: " confirm
        [ "$confirm" != "CONFIRM" ] && die "Aborted."
    fi

    # Dry run preview
    if $dry_run; then
        echo ""
        echo -e "    ${YELLOW}DRY RUN ${_DASH} password change preview for '$USERNAME':${RESET}"
        load_hosts
        echo ""
        if [ "$(id -u)" -eq 0 ]; then
            printf "      %-30s %s\n" "localhost" "$(id "$USERNAME" &>/dev/null && echo "would change" || echo "would create")"
        fi
        local i
        for ((i=0; i<HOST_COUNT; i++)); do
            printf "      %-30s %s\n" "${HOST_LABELS[$i]} (${HOST_IPS[$i]})" "would change/create"
        done
        echo ""
        echo -e "    ${YELLOW}DRY RUN ${_DASH} no passwords were changed.${RESET}"
        return 0
    fi

    read_password "New password for '$USERNAME'" || return 1
    echo ""
    echo -e "    Changing ${BOLD}$USERNAME${RESET} across fleet..."
    freq_divider "Fleet Password Change"

    local ok=0 skip=0 fail=0 created=0

    # Local (only if running as root)
    if [ "$(id -u)" -eq 0 ]; then
        printf "      %-30s " "localhost"
        if id "$USERNAME" &>/dev/null; then
            if echo "${USERNAME}:${PASS1}" | chpasswd 2>/dev/null; then
                echo -e "${GREEN}${_TICK} OK${RESET}"; ok=$((ok + 1))
            else
                echo -e "${RED}${_CROSS} FAILED${RESET}"; fail=$((fail + 1))
            fi
        elif [ "$USERNAME" = "$FREQ_SERVICE_ACCOUNT" ]; then
            if _users_create_svc_local "$PASS1"; then
                echo -e "${GREEN}${_TICK} CREATED${RESET}"; created=$((created + 1)); ok=$((ok + 1))
            else
                echo -e "${RED}${_CROSS} FAILED${RESET}"; fail=$((fail + 1))
            fi
        elif ! is_privileged "$USERNAME"; then
            getent group "$REG_GID" &>/dev/null || groupadd -g "$REG_GID" "$REG_GROUP" 2>/dev/null
            getent group "${SVC_GID}" &>/dev/null || groupadd -g "${SVC_GID}" "$FREQ_GROUP" 2>/dev/null
            if useradd -u "$REG_UID" -g "$REG_GID" -G "$FREQ_GROUP" -m -s /bin/bash "$USERNAME" 2>/dev/null; then
                if echo "${USERNAME}:${PASS1}" | chpasswd 2>/dev/null; then
                    echo -e "${GREEN}${_TICK} CREATED${RESET}"; created=$((created + 1)); ok=$((ok + 1))
                else
                    echo -e "${YELLOW}${_WARN} CREATED (password failed)${RESET}"; fail=$((fail + 1))
                fi
            else
                echo -e "${RED}${_CROSS} CREATE FAILED${RESET}"; fail=$((fail + 1))
            fi
        else
            echo -e "${DIM}skip (not found)${RESET}"; skip=$((skip + 1))
        fi
    fi

    # Remote fleet
    load_hosts
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        local host="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        printf "      %-30s " "$label ($host)"

        # Check connectivity for SSH-capable hosts
        if [ "$htype" != "switch" ] && [ "$htype" != "idrac" ] && [ "$htype" != "external" ]; then
            if ! freq_ssh "$host" "true" &>/dev/null; then
                echo -e "${YELLOW}${_WARN} UNREACHABLE${RESET}"
                fail=$((fail + 1))
                continue
            fi
        fi

        local result
        result=$(_users_change_remote_password "$host" "$htype" "$USERNAME" "$PASS1")

        # Auto-create on linux hosts if missing and not privileged
        if [ "$result" = "__MISSING__" ] && ! is_privileged "$USERNAME" && [ "$htype" = "linux" ]; then
            result=$(_users_create_remote "$host" "$USERNAME" "$REG_UID" "$REG_GID" "$REG_GROUP" "$PASS1")
        elif [ "$result" = "__MISSING__" ]; then
            result="skip (not found)"
        fi

        case "$result" in
            OK*)      echo -e "${GREEN}${_TICK} ${result}${RESET}"; ok=$((ok + 1)) ;;
            CREATED)  echo -e "${GREEN}${_TICK} ${result}${RESET}"; created=$((created + 1)); ok=$((ok + 1)) ;;
            skip*)    echo -e "${DIM}${result}${RESET}"; skip=$((skip + 1)) ;;
            *)        echo -e "${RED}${_CROSS} ${result}${RESET}"; fail=$((fail + 1)) ;;
        esac
    done

    freq_divider "Summary"
    echo -e "      ${GREEN}${_TICK}${RESET} Done: ${GREEN}$ok changed${RESET} ($created new), $skip skipped, $fail failed"
    freq_footer
    freq_celebrate
    time_saved 2

    # Update credential files if running as root
    if [ "$(id -u)" -eq 0 ] && [ $ok -gt 0 ]; then
        if [ "$USERNAME" = "root" ]; then
            _users_update_credential "$ROOT_PASS_FILE" "$PASS1"
            echo -e "      ${DIM}Updated ${ROOT_PASS_FILE}${RESET}"
            vault_store_if_root "DEFAULT" "root-pass" "$PASS1"
        elif [ "$USERNAME" = "$FREQ_SERVICE_ACCOUNT" ]; then
            _users_update_credential "$SVC_PASS_FILE" "$PASS1"
            echo -e "      ${DIM}Updated ${SVC_PASS_FILE}${RESET}"
            vault_store_if_root "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" "$PASS1"
        fi
    fi

    log "passwd: $USERNAME -- $ok changed, $skip skipped, $fail failed"
}

# ═══════════════════════════════════════════════════════════════════
# USER REGISTRY COMMANDS
# ═══════════════════════════════════════════════════════════════════
cmd_users() {
    _users_ensure_registry

    local subcmd="${1:-}"
    shift 2>/dev/null || true

    case "$subcmd" in
        list|ls)
            _users_list
            ;;
        add)
            _users_add "$@"
            ;;
        remove|rm)
            _users_remove "$@"
            ;;
        info)
            _users_info "$@"
            ;;
        orphans)
            _users_orphans
            ;;
        --help|-h|help)
            echo "Usage: freq users <list|add|remove|info|orphans>"
            echo ""
            echo "  list      Show all registered users"
            echo "  add       Register a new user"
            echo "  remove    Unregister a user [--full] [--dry-run]"
            echo "  info      Show details for a user"
            echo "  orphans   Find accounts not in registry"
            return 0
            ;;
        "")
            echo ""
            freq_header "User Registry"
            echo ""
            menu_item 1 "list" "Show all registered users" "safe"
            menu_item 2 "add" "Register a new user" "changes"
            menu_item 3 "remove" "Unregister a user" "destructive"
            menu_item 4 "info" "Show user details" "safe"
            menu_item 5 "orphans" "Find accounts not in registry" "safe"
            freq_footer
            menu_prompt 5
            case "$_MENU_CHOICE" in
                1) _users_list ;;
                2) _users_add ;;
                3) _users_remove "$@" ;;
                4) _users_info ;;
                5) _users_orphans ;;
                0|"") return 0 ;;
                *) echo -e "\n    ${YELLOW}Pick a number from the menu.${RESET}" ;;
            esac
            ;;
        *)
            echo "Usage: freq users [list|add|remove|info|orphans|--help]"
            return 1
            ;;
    esac
}

# _users_list — display all registered users
_users_list() {
    echo ""
    freq_header "User Registry"
    echo -e "      ${DIM}Username           UID      GID      Group${RESET}"
    freq_divider ""
    local count=0
    while IFS=: read -r name uid gid group; do
        [ -z "$name" ] && continue
        printf "      %-18s %-8s %-8s %s\n" "$name" "$uid" "$gid" "$group"
        count=$((count + 1))
    done < <(grep -v '^#' "$USERS_FILE" | grep -v '^$')
    echo ""
    echo -e "      ${DIM}$count users (range ${UID_MIN}-${UID_MAX})${RESET}"
    echo -e "      ${DIM}Immutable: ${IMMUTABLE_ACCOUNTS[*]}${RESET}"
    freq_footer
}

# _users_add — register a new user
_users_add() {
    require_operator || return 1

    local USERNAME="${1:-}"
    if [ -z "$USERNAME" ]; then
        echo ""
        read -rp "    Username: " USERNAME
    fi
    [ -z "$USERNAME" ] && die "No username provided."
    validate_username "$USERNAME"
    is_privileged "$USERNAME" && die "'$USERNAME' is a privileged account."
    grep -q "^${USERNAME}:" "$USERS_FILE" 2>/dev/null && die "'$USERNAME' is already registered."

    local new_uid
    new_uid=$(next_uid)

    echo ""
    echo -e "      Username: ${BOLD}$USERNAME${RESET}"
    echo -e "      UID/GID:  $new_uid"
    echo ""
    read -rp "    Register? [y/N]: " confirm
    [[ "$confirm" =~ ^[Yy] ]] || { echo "    Aborted."; return 0; }

    backup_config "$USERS_FILE"
    echo "${USERNAME}:${new_uid}:${new_uid}:${USERNAME}" >> "$USERS_FILE"

    # Also add to roles.conf as operator
    _users_ensure_roles
    if ! grep -q "^${USERNAME}:" "$ROLES_FILE" 2>/dev/null; then
        echo "${USERNAME}:operator" >> "$ROLES_FILE"
        log "users add: wrote ${USERNAME}:operator to roles.conf"
    fi

    echo -e "      ${GREEN}${_TICK}${RESET} Registered: $USERNAME (uid=$new_uid)"

    echo ""
    read -rp "    Deploy fleet-wide now? [y/N]: " deploy
    if [[ "$deploy" =~ ^[Yy] ]]; then
        cmd_passwd "$USERNAME"
    else
        echo -e "      ${DIM}Run 'freq passwd $USERNAME' to deploy later.${RESET}"
    fi
    log "users add: $USERNAME (uid=$new_uid)"
}

# _users_remove — unregister a user
_users_remove() {
    require_operator || return 1

    local target="" full_cleanup=false dry_run=false
    while [ $# -gt 0 ]; do
        case "$1" in
            --full|--purge) full_cleanup=true ;;
            --dry-run) dry_run=true ;;
            --help|-h)
                echo "Usage: freq users remove <username> [--full] [--dry-run]"
                echo ""
                echo "  --full      Also delete account from all fleet hosts"
                echo "  --dry-run   Preview only, no changes"
                return 0
                ;;
            -*) die "Unknown flag: $1" ;;
            *) target="$1" ;;
        esac
        shift
    done

    if [ -z "$target" ]; then
        echo ""
        read -rp "    Username to remove: " target
    fi
    [ -z "$target" ] && die "No username provided."
    validate_username "$target"
    require_not_immutable "$target" "remove"
    is_privileged "$target" && die "'$target' is a privileged account and cannot be removed."
    grep -q "^${target}:" "$USERS_FILE" 2>/dev/null || die "'$target' not in user registry."

    local reg_entry
    reg_entry=$(grep "^${target}:" "$USERS_FILE")

    echo ""
    freq_header "Remove User: $target"
    echo ""
    echo -e "      ${DIM}Registry entry: $reg_entry${RESET}"
    echo ""
    echo -e "      ${BOLD}This will:${RESET}"
    echo -e "        ${DIM}1. Remove '$target' from users.conf${RESET}"
    echo -e "        ${DIM}2. Remove '$target' from roles.conf (if present)${RESET}"
    if $full_cleanup; then
        echo -e "        ${RED}3. Kill processes + delete account on every fleet host${RESET}"
    fi
    $dry_run && echo -e "      ${YELLOW}DRY RUN ${_DASH} no changes will be made${RESET}"
    echo ""

    if ! $dry_run; then
        read -rp "    Type the username '$target' to confirm: " confirm
        [ "$confirm" != "$target" ] && die "Confirmation failed. Aborted."
        freq_lock "users rm $target"
    fi

    # Remove from registry
    if $dry_run; then
        echo -e "      ${DIM}[DRY RUN] Would remove from users.conf${RESET}"
    else
        backup_config "$USERS_FILE"
        local tmp
        tmp=$(mktemp)
        grep -v "^${target}:" "$USERS_FILE" > "$tmp"
        mv "$tmp" "$USERS_FILE"
        chmod 640 "$USERS_FILE"
        echo -e "      ${GREEN}${_TICK}${RESET} Removed from user registry"
    fi

    # Remove from roles
    if grep -q "^${target}:" "$ROLES_FILE" 2>/dev/null; then
        if $dry_run; then
            echo -e "      ${DIM}[DRY RUN] Would remove from roles.conf${RESET}"
        else
            backup_config "$ROLES_FILE"
            local tmp
            tmp=$(mktemp)
            grep -v "^${target}:" "$ROLES_FILE" > "$tmp"
            mv "$tmp" "$ROLES_FILE"
            chmod 640 "$ROLES_FILE"
            echo -e "      ${GREEN}${_TICK}${RESET} Removed from roles.conf"
        fi
    fi

    # Full fleet cleanup
    if $full_cleanup; then
        echo ""
        freq_divider "Fleet Cleanup"
        _users_delete_from_fleet "$target" "$( $dry_run && echo true || echo false )"
    fi

    if ! $dry_run; then
        freq_unlock
        log "users remove: $target (full=$full_cleanup)"
        echo ""
        echo -e "      ${GREEN}${_TICK}${RESET} User '${BOLD}$target${RESET}' has been removed."
        freq_celebrate
    else
        echo ""
        echo -e "      ${YELLOW}DRY RUN complete. No changes were made.${RESET}"
    fi
}

# _users_info <username> — show details for a user
_users_info() {
    local target="${1:-}"
    if [ -z "$target" ]; then
        echo ""
        read -rp "    Username: " target
    fi
    [ -z "$target" ] && die "No username provided."

    echo ""
    freq_header "User Info: $target"
    echo ""

    # Registry
    if lookup_user "$target"; then
        echo -e "      ${BOLD}Registry:${RESET}  $target:$REG_UID:$REG_GID:$REG_GROUP"
    elif is_privileged "$target"; then
        echo -e "      ${BOLD}Registry:${RESET}  ${DIM}privileged account (not in registry)${RESET}"
    else
        echo -e "      ${BOLD}Registry:${RESET}  ${YELLOW}not registered${RESET}"
    fi

    # Role
    local role
    role=$(_users_get_role "$target")
    echo -e "      ${BOLD}Role:${RESET}      $role"

    # Local account
    if id "$target" &>/dev/null; then
        local uid_local gid_local
        uid_local=$(id -u "$target")
        gid_local=$(id -g "$target")
        echo -e "      ${BOLD}Local:${RESET}     uid=$uid_local gid=$gid_local (exists)"
    else
        echo -e "      ${BOLD}Local:${RESET}     ${DIM}not on this host${RESET}"
    fi

    # Privileged / Immutable
    is_privileged "$target" && echo -e "      ${BOLD}Flags:${RESET}     ${YELLOW}privileged${RESET}"
    is_immutable "$target" && echo -e "      ${BOLD}Flags:${RESET}     ${RED}immutable (cannot delete)${RESET}"

    echo ""
    freq_footer
}

# _users_orphans — find accounts in UID range not in registry
_users_orphans() {
    require_operator || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts in fleet."

    echo ""
    freq_header "Orphan Detection"
    echo -e "      ${DIM}Finding accounts in UID range ${UID_MIN}-${UID_MAX} not in registry...${RESET}"
    echo ""

    declare -A registered
    while IFS=: read -r name uid gid group; do
        registered[$name]=1
    done < <(grep -v '^#' "$USERS_FILE" | grep -v '^$')

    local found_orphans=false i
    for ((i=0; i<HOST_COUNT; i++)); do
        local host="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        [ "$htype" != "linux" ] && continue
        freq_ssh "$host" "true" &>/dev/null || continue
        local remote_users
        remote_users=$(freq_ssh "$host" \
            "awk -F: '\$3>=${UID_MIN} && \$3<=${UID_MAX}{print \$1}' /etc/passwd 2>/dev/null" 2>/dev/null)
        local u
        for u in $remote_users; do
            [ -n "${registered[$u]:-}" ] && continue
            [ "$u" = "$FREQ_SERVICE_ACCOUNT" ] && continue
            found_orphans=true
            echo -e "      ${YELLOW}${_WARN}${RESET} ${BOLD}$u${RESET} exists on ${BOLD}$label${RESET} but NOT in registry"
        done
    done

    if ! $found_orphans; then
        echo -e "      ${GREEN}${_TICK}${RESET} No orphan accounts found."
        freq_celebrate
    fi
    echo ""
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# INSTALL-USER — Set up an existing local user for fleet access
# ═══════════════════════════════════════════════════════════════════
cmd_install_user() {
    require_admin || return 1
    require_ssh_key

    local target_user="${1:-}" dry_run=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) dry_run=true ;;
            --help|-h)
                echo "Usage: freq install-user <username> [--dry-run]"
                echo ""
                echo "Set up an existing local user for fleet SSH access."
                echo "Generates SSH key, assigns operator role, deploys key to fleet."
                return 0
                ;;
            -*) die "Unknown flag: $1" ;;
            *) target_user="$1" ;;
        esac
        shift
    done

    [ -z "$target_user" ] && { echo ""; read -rp "    Username: " target_user; }
    [ -z "$target_user" ] && die "Usage: freq install-user <username>"
    validate_username "$target_user"

    echo ""
    freq_header "Install User for Fleet Access"
    echo -e "      ${DIM}Setting up ${BOLD}$target_user${RESET}${DIM} for fleet operations...${RESET}"
    echo ""

    # Check user exists locally
    id "$target_user" &>/dev/null || die "User '$target_user' does not exist on this system. Create with 'freq users add' first."

    local user_home
    user_home=$(getent passwd "$target_user" | cut -d: -f6)
    [ -z "$user_home" ] && die "Cannot determine home directory for '$target_user'."

    # Step 1: SSH key setup
    show_step "INSTALL-USER" 1 4 "SSH key setup"
    if [ -f "${user_home}/.ssh/id_ed25519" ]; then
        echo -e "      ${GREEN}${_TICK}${RESET} SSH key exists: ${user_home}/.ssh/id_ed25519"
    elif $dry_run; then
        echo -e "      ${DIM}[DRY RUN] Would generate ed25519 key${RESET}"
    else
        read -rp "      No SSH key found. Generate one? [Y/n]: " yn
        if [[ ! "$yn" =~ ^[nN] ]]; then
            mkdir -p "${user_home}/.ssh"
            ssh-keygen -t ed25519 -f "${user_home}/.ssh/id_ed25519" -N "" -C "${target_user}@$(hostname)" >/dev/null 2>&1
            chown -R "${target_user}" "${user_home}/.ssh"
            chmod 700 "${user_home}/.ssh"
            chmod 600 "${user_home}/.ssh/id_ed25519"
            chmod 644 "${user_home}/.ssh/id_ed25519.pub"
            echo -e "      ${GREEN}${_TICK}${RESET} ed25519 key generated"
        fi
    fi

    # Step 2: Add to roles.conf
    show_step "INSTALL-USER" 2 4 "Assign operator role"
    _users_ensure_roles
    if grep -q "^${target_user}:" "$ROLES_FILE" 2>/dev/null; then
        echo -e "      ${DIM}Already in roles.conf: $(grep "^${target_user}:" "$ROLES_FILE")${RESET}"
    elif $dry_run; then
        echo -e "      ${DIM}[DRY RUN] Would add ${target_user}:operator to roles.conf${RESET}"
    else
        backup_config "$ROLES_FILE"
        echo "${target_user}:operator" >> "$ROLES_FILE"
        echo -e "      ${GREEN}${_TICK}${RESET} Added: ${target_user}:operator"
    fi

    # Step 3: Register in users.conf if not present
    show_step "INSTALL-USER" 3 4 "Register in user registry"
    _users_ensure_registry
    if grep -q "^${target_user}:" "$USERS_FILE" 2>/dev/null; then
        echo -e "      ${DIM}Already registered in users.conf${RESET}"
    elif $dry_run; then
        echo -e "      ${DIM}[DRY RUN] Would register in users.conf${RESET}"
    else
        local new_uid
        new_uid=$(next_uid)
        echo "${target_user}:${new_uid}:${new_uid}:${target_user}" >> "$USERS_FILE"
        echo -e "      ${GREEN}${_TICK}${RESET} Registered: ${target_user} (uid=$new_uid)"
    fi

    # Step 4: Deploy SSH key to fleet
    show_step "INSTALL-USER" 4 4 "Deploy SSH key to fleet"
    local pubkey_file="${user_home}/.ssh/id_ed25519.pub"
    [ ! -f "$pubkey_file" ] && pubkey_file="${user_home}/.ssh/id_rsa.pub"
    if [ -f "$pubkey_file" ]; then
        if $dry_run; then
            echo -e "      ${DIM}[DRY RUN] Would deploy public key to fleet${RESET}"
        else
            _users_deploy_pubkey "$target_user" "$pubkey_file"
        fi
    else
        echo -e "      ${YELLOW}${_WARN}${RESET} No public key to deploy"
    fi

    echo ""
    echo -e "      ${GREEN}${_TICK}${RESET} ${BOLD}$target_user${RESET} can now use freq commands (tier: operator)"
    freq_celebrate
    time_saved 3
    log "install-user: $target_user (operator)"
}

# _users_deploy_pubkey <username> <pubkey_file> — deploy a public key to fleet
_users_deploy_pubkey() {
    local username="$1" pubkey_file="$2"
    local pubkey
    pubkey=$(cat "$pubkey_file" 2>/dev/null)
    [ -z "$pubkey" ] && { echo -e "      ${YELLOW}${_WARN}${RESET} Empty public key file"; return 1; }

    load_hosts
    local ok=0 fail=0 skip=0 i
    for ((i=0; i<HOST_COUNT; i++)); do
        local host="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        [ "$htype" = "switch" ] || [ "$htype" = "idrac" ] || [ "$htype" = "external" ] && { skip=$((skip + 1)); continue; }

        local result
        result=$(freq_ssh "$host" "
            target_home=\$(getent passwd '${username}' 2>/dev/null | cut -d: -f6)
            [ -z \"\$target_home\" ] && { echo 'NO_USER'; exit 0; }
            sudo mkdir -p \"\${target_home}/.ssh\"
            if sudo grep -qF '${pubkey}' \"\${target_home}/.ssh/authorized_keys\" 2>/dev/null; then
                echo 'EXISTS'
            else
                echo '${pubkey}' | sudo tee -a \"\${target_home}/.ssh/authorized_keys\" >/dev/null
                sudo chmod 700 \"\${target_home}/.ssh\"
                sudo chmod 600 \"\${target_home}/.ssh/authorized_keys\"
                sudo chown -R '${username}' \"\${target_home}/.ssh\"
                echo 'DEPLOYED'
            fi
        " 2>/dev/null)

        case "$result" in
            DEPLOYED) ok=$((ok + 1)); freq_debug "Key deployed to $label" ;;
            EXISTS)   ok=$((ok + 1)); freq_debug "Key already on $label" ;;
            NO_USER)  skip=$((skip + 1)); freq_debug "User not on $label" ;;
            *)        fail=$((fail + 1)); freq_debug "Key deploy failed on $label" ;;
        esac
    done
    echo -e "      ${GREEN}${_TICK}${RESET} Key deployed: $ok hosts, $skip skipped, $fail failed"
}

# ═══════════════════════════════════════════════════════════════════
# NEW USER WIZARD
# ═══════════════════════════════════════════════════════════════════
cmd_new_user() {
    require_operator || return 1

    local USERNAME="${1:-}" dry_run=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) dry_run=true ;;
            --help|-h)
                echo "Usage: freq new-user [username] [--dry-run]"
                echo ""
                echo "Create a new user account across the entire fleet."
                echo "Registers in users.conf, sets password, and creates on all hosts."
                return 0
                ;;
            -*) die "Unknown flag: $1" ;;
            *) [ -z "$USERNAME" ] && USERNAME="$1" ;;
        esac
        shift
    done

    echo ""
    freq_header "New User Setup"
    echo -e "      ${DIM}This will create a user account across every host in the fleet.${RESET}"
    echo ""

    if [ -z "$USERNAME" ]; then
        read -rp "    Username: " USERNAME
    fi
    [ -z "$USERNAME" ] && die "No username provided."
    validate_username "$USERNAME"

    if $dry_run; then
        echo -e "    ${YELLOW}DRY RUN ${_DASH} previewing new user creation for '$USERNAME'${RESET}"
        echo ""
    fi

    # Step 1: Register
    show_step "NEW USER" 1 3 "Register $USERNAME"
    _users_ensure_registry
    if grep -q "^${USERNAME}:" "$USERS_FILE" 2>/dev/null; then
        local existing
        existing=$(grep "^${USERNAME}:" "$USERS_FILE")
        echo -e "      ${GREEN}${_TICK}${RESET} Already registered: $existing"
    elif $dry_run; then
        local preview_uid
        preview_uid=$(next_uid)
        echo -e "      ${DIM}[DRY RUN] Would register: ${USERNAME}:${preview_uid}:${preview_uid}:${USERNAME}${RESET}"
    else
        local new_uid
        new_uid=$(next_uid)
        backup_config "$USERS_FILE"
        echo "${USERNAME}:${new_uid}:${new_uid}:${USERNAME}" >> "$USERS_FILE"
        _users_ensure_roles
        if ! grep -q "^${USERNAME}:" "$ROLES_FILE" 2>/dev/null; then
            echo "${USERNAME}:operator" >> "$ROLES_FILE"
        fi
        echo -e "      ${GREEN}${_TICK}${RESET} Registered: $USERNAME (uid=$new_uid)"
    fi

    # Step 2: Set password fleet-wide
    show_step "NEW USER" 2 3 "Set password + create $USERNAME on all hosts"
    if $dry_run; then
        echo -e "      ${DIM}[DRY RUN] Would prompt for password and deploy fleet-wide${RESET}"
        load_hosts
        local i
        for ((i=0; i<HOST_COUNT; i++)); do
            printf "        %-30s %s\n" "${HOST_LABELS[$i]} (${HOST_IPS[$i]})" "would create/set password"
        done
    else
        cmd_passwd "$USERNAME"
    fi

    # Step 3: Deploy SSH key (optional)
    show_step "NEW USER" 3 3 "Deploy SSH key for $USERNAME"
    if $dry_run; then
        echo -e "      ${DIM}[DRY RUN] Would offer to deploy SSH key${RESET}"
    else
        echo -e "      ${DIM}If $USERNAME has an SSH public key, paste it to deploy fleet-wide.${RESET}"
        echo ""
        read -rp "    Deploy an SSH key now? [y/N]: " _dokeys
        if [[ "$_dokeys" =~ ^[Yy] ]]; then
            echo ""
            read -rp "    Paste the public key: " _pubkey
            if [ -n "$_pubkey" ]; then
                validate_ssh_pubkey "$_pubkey"
                local tmpkey
                tmpkey=$(mktemp)
                echo "$_pubkey" > "$tmpkey"
                _users_deploy_pubkey "$USERNAME" "$tmpkey"
                rm -f "$tmpkey"
            fi
        else
            echo -e "      ${DIM}Skipped. Deploy later with 'freq install-user $USERNAME'.${RESET}"
        fi
    fi

    echo ""
    echo -e "      ${GREEN}${_TICK}${RESET} ${BOLD}$USERNAME${RESET} is ready."
    freq_celebrate
    time_saved 3
    log "new-user: $USERNAME -- full setup complete"
}

# ═══════════════════════════════════════════════════════════════════
# SVC-ADMIN LOCAL CREATION (helper)
# ═══════════════════════════════════════════════════════════════════
_users_create_svc_local() {
    local password="$1"
    getent group "${SVC_GID}" &>/dev/null || groupadd -g "${SVC_GID}" "$FREQ_GROUP" 2>/dev/null
    useradd -u "${SVC_UID}" -g "${SVC_GID}" -G sudo -m -s /bin/bash "$FREQ_SERVICE_ACCOUNT" 2>/dev/null || return 1
    echo "${FREQ_SERVICE_ACCOUNT}:${password}" | chpasswd 2>/dev/null || return 1
    mkdir -p /etc/sudoers.d
    echo "${FREQ_SERVICE_ACCOUNT} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${FREQ_SERVICE_ACCOUNT}"
    chmod 440 "/etc/sudoers.d/${FREQ_SERVICE_ACCOUNT}"
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# PROMOTE / DEMOTE
# ═══════════════════════════════════════════════════════════════════
cmd_promote() {
    case "${1:-}" in
        --help|-h)
            echo "Usage: freq promote <username>"
            echo ""
            echo "Promote a user to admin role."
            return 0
            ;;
    esac

    require_admin || return 1
    _users_ensure_roles

    local target="${1:-}"
    [ -z "$target" ] && { echo ""; read -rp "    Username to promote: " target; }
    [ -z "$target" ] && die "No username provided."
    validate_username "$target"

    local current_role
    current_role=$(_users_get_role "$target")

    if [ "$current_role" = "admin" ]; then
        echo -e "      ${DIM}$target is already an admin.${RESET}"
        return 0
    fi

    echo ""
    freq_header "Promote: $target"
    echo -e "      ${DIM}Current role: $current_role${RESET}"
    echo -e "      ${BOLD}New role: admin${RESET}"
    echo ""
    read -rp "    Confirm promote $target to admin? [y/N]: " confirm
    [[ "$confirm" =~ ^[Yy] ]] || { echo "    Aborted."; return 0; }

    backup_config "$ROLES_FILE"
    # Remove existing entry
    local tmp
    tmp=$(mktemp)
    grep -v "^${target}:" "$ROLES_FILE" > "$tmp" 2>/dev/null
    echo "${target}:admin" >> "$tmp"
    mv "$tmp" "$ROLES_FILE"
    chmod 640 "$ROLES_FILE"

    echo -e "      ${GREEN}${_TICK}${RESET} ${BOLD}$target${RESET} promoted to admin."
    echo -e "      ${DIM}Run 'freq roles sync' to update sudoers on fleet hosts.${RESET}"
    freq_celebrate
    log "promote: $target -> admin"
}

cmd_demote() {
    case "${1:-}" in
        --help|-h)
            echo "Usage: freq demote <username>"
            echo ""
            echo "Demote a user to operator role."
            return 0
            ;;
    esac

    require_admin || return 1
    _users_ensure_roles

    local target="${1:-}"
    [ -z "$target" ] && { echo ""; read -rp "    Username to demote: " target; }
    [ -z "$target" ] && die "No username provided."
    validate_username "$target"
    require_not_immutable "$target" "demote"

    local current_role
    current_role=$(_users_get_role "$target")

    if [ "$current_role" = "operator" ]; then
        echo -e "      ${DIM}$target is already an operator.${RESET}"
        return 0
    fi
    if [ "$current_role" = "viewer" ]; then
        echo -e "      ${DIM}$target is already below operator level.${RESET}"
        return 0
    fi

    echo ""
    freq_header "Demote: $target"
    echo -e "      ${DIM}Current role: $current_role${RESET}"
    echo -e "      ${BOLD}New role: operator${RESET}"
    echo ""
    read -rp "    Confirm demote $target to operator? [y/N]: " confirm
    [[ "$confirm" =~ ^[Yy] ]] || { echo "    Aborted."; return 0; }

    backup_config "$ROLES_FILE"
    local tmp
    tmp=$(mktemp)
    grep -v "^${target}:" "$ROLES_FILE" > "$tmp" 2>/dev/null
    echo "${target}:operator" >> "$tmp"
    mv "$tmp" "$ROLES_FILE"
    chmod 640 "$ROLES_FILE"

    echo -e "      ${GREEN}${_TICK}${RESET} ${BOLD}$target${RESET} demoted to operator."
    echo -e "      ${DIM}Run 'freq roles sync' to update sudoers on fleet hosts.${RESET}"
    log "demote: $target -> operator"
}

# ═══════════════════════════════════════════════════════════════════
# ROLE HELPERS
# ═══════════════════════════════════════════════════════════════════

# _users_get_role <username> — returns role from roles.conf or "none"
_users_get_role() {
    local target="$1" role
    role=$(grep "^${target}:" "$ROLES_FILE" 2>/dev/null | head -1 | cut -d: -f2)
    echo "${role:-none}"
}

# ═══════════════════════════════════════════════════════════════════
# RBAC & SUDOERS — cmd_roles
# ═══════════════════════════════════════════════════════════════════

# Sudoers template directory
SUDOERS_TMPL_DIR="${FREQ_DIR}/conf/sudoers"

cmd_roles() {
    _users_ensure_roles

    local subcmd="${1:-list}"
    shift 2>/dev/null || true

    case "$subcmd" in
        list|ls)   _roles_list ;;
        sync)      _roles_sync "$@" ;;
        check)     _roles_check "$@" ;;
        assign)    _roles_assign "$@" ;;
        --help|-h|help)
            echo "Usage: freq roles <list|sync|check|assign>"
            echo ""
            echo "  list       Show all role assignments"
            echo "  sync       Deploy sudoers profiles to fleet [host|--all]"
            echo "  check      Check for sudoers drift [host|--all]"
            echo "  assign     Assign role to user: freq roles assign <user> <role>"
            return 0
            ;;
        *)
            echo "Usage: freq roles <list|sync|check|assign|--help>"
            return 1
            ;;
    esac
}

# _roles_list — display all role assignments
_roles_list() {
    echo ""
    freq_header "Roles"
    echo ""
    echo -e "      ${DIM}Roles configuration: ${ROLES_FILE}${RESET}"
    echo ""
    printf "      %-20s %-12s %s\n" "USER" "ROLE" "SUDOERS PROFILE"
    freq_divider ""
    local count=0
    while IFS=: read -r username role; do
        [[ "$username" =~ ^#|^$ ]] && continue
        [ -z "$username" ] && continue
        local profile
        case "$role" in
            admin)    profile="freq-admin (NOPASSWD:ALL)" ;;
            operator) profile="freq-operator (service mgmt)" ;;
            viewer)   profile="freq-probe (read-only)" ;;
            *)        profile="freq-probe (default)" ;;
        esac
        printf "      %-20s %-12s %s\n" "$username" "$role" "$profile"
        count=$((count + 1))
    done < "$ROLES_FILE"
    echo ""
    echo -e "      ${DIM}$count role assignments${RESET}"
    freq_footer
}

# _roles_assign <user> <role> — assign role
_roles_assign() {
    require_admin || return 1
    local target="${1:-}" role="${2:-}"
    [ -z "$target" ] && die "Usage: freq roles assign <username> <admin|operator|viewer>"
    [ -z "$role" ] && die "Usage: freq roles assign <username> <admin|operator|viewer>"

    case "$role" in
        admin|operator|viewer) ;;
        *) die "Invalid role: '$role'. Must be admin, operator, or viewer." ;;
    esac

    validate_username "$target"

    backup_config "$ROLES_FILE"
    local tmp
    tmp=$(mktemp)
    grep -v "^${target}:" "$ROLES_FILE" > "$tmp" 2>/dev/null
    echo "${target}:${role}" >> "$tmp"
    mv "$tmp" "$ROLES_FILE"
    chmod 640 "$ROLES_FILE"

    echo -e "      ${GREEN}${_TICK}${RESET} ${BOLD}$target${RESET} assigned role: $role"
    echo -e "      ${DIM}Run 'freq roles sync' to update sudoers on fleet hosts.${RESET}"
    log "roles assign: $target -> $role"
}

# _roles_write_templates — create sudoers templates
_roles_write_templates() {
    mkdir -p "$SUDOERS_TMPL_DIR" 2>/dev/null || true

    cat > "${SUDOERS_TMPL_DIR}/freq-admin.sudoers" << 'TMPL'
# FREQ Admin sudoers profile — full sudo
# Managed by: freq roles sync
TMPL

    cat > "${SUDOERS_TMPL_DIR}/freq-operator.sudoers" << 'TMPL'
# FREQ Operator sudoers profile — service management
# Managed by: freq roles sync
Cmnd_Alias FREQ_OP_ALLOW = \
  /usr/bin/systemctl status *, /usr/bin/systemctl start *, \
  /usr/bin/systemctl stop *, /usr/bin/systemctl restart *, \
  /usr/bin/systemctl reload *, /usr/bin/systemctl enable *, \
  /usr/bin/systemctl disable *, \
  /usr/bin/docker ps, /usr/bin/docker stats, /usr/bin/docker logs *, \
  /usr/bin/docker inspect *, /usr/bin/docker exec *, \
  /usr/bin/journalctl *, /usr/bin/tail *, /usr/bin/cat *, \
  /usr/bin/apt-get update, /usr/bin/apt-get upgrade
Cmnd_Alias FREQ_OP_DENY = \
  /bin/rm -rf *, /usr/sbin/visudo, /usr/sbin/userdel, \
  /bin/chmod 777 *, /usr/bin/passwd root
TMPL

    cat > "${SUDOERS_TMPL_DIR}/freq-probe.sudoers" << 'TMPL'
# FREQ Probe/Viewer sudoers profile — read-only
# Managed by: freq roles sync
Cmnd_Alias FREQ_PROBE_ALLOW = \
  /usr/bin/systemctl status *, /usr/bin/systemctl is-active *, \
  /usr/bin/systemctl is-enabled *, /usr/bin/systemctl list-units *, \
  /usr/bin/docker ps, /usr/bin/docker stats --no-stream *, \
  /usr/bin/docker inspect *, /usr/bin/docker logs --tail * *, \
  /usr/bin/journalctl -n * -u *, /usr/bin/cat /etc/*, \
  /usr/bin/df *, /usr/bin/free *, /usr/bin/uptime, \
  /sbin/ip addr, /sbin/ip route, /bin/ss -tlnp, \
  /usr/bin/last, /usr/bin/who, /usr/bin/id *
TMPL
}

# _roles_sync — deploy sudoers profiles to fleet hosts
_roles_sync() {
    require_admin || return 1
    require_ssh_key
    load_hosts
    freq_action_modify "Syncing roles to fleet..."

    local targets_ip=() targets_label=()
    local _target=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --all)
                local i
                for ((i=0; i<HOST_COUNT; i++)); do
                    [ "${HOST_TYPES[$i]}" != "linux" ] && continue
                    targets_ip+=("${HOST_IPS[$i]}")
                    targets_label+=("${HOST_LABELS[$i]}")
                done
                ;;
            --help|-h) echo "Usage: freq roles sync <host>|--all"; return 0 ;;
            -*) die "Unknown flag: $1" ;;
            *) _target="$1" ;;
        esac
        shift
    done

    if [ -n "$_target" ] && [ ${#targets_ip[@]} -eq 0 ]; then
        freq_resolve "$_target" || die "Host '$_target' not found."
        targets_ip+=("$(freq_resolve_ip "$_target")")
        targets_label+=("$(freq_resolve_label "$_target")")
    fi

    [ ${#targets_ip[@]} -eq 0 ] && die "Usage: freq roles sync <host>|--all"

    _roles_write_templates

    echo ""
    freq_header "Roles Sync"
    echo ""

    local ok=0 fail=0 t
    for ((t=0; t<${#targets_ip[@]}; t++)); do
        local ip="${targets_ip[$t]}" hostname="${targets_label[$t]}"
        echo -e "      ${_ARROW} ${BOLD}$hostname${RESET} ($ip)"

        while IFS=: read -r username role; do
            [[ "$username" =~ ^#|^$ ]] && continue
            [ -z "$username" ] || [ -z "$role" ] && continue
            local profile
            case "$role" in
                admin)    profile="freq-admin" ;;
                operator) profile="freq-operator" ;;
                viewer)   profile="freq-probe" ;;
                *)        profile="freq-probe" ;;
            esac

            # Check if user exists on this host
            freq_ssh "$ip" "id '$username'" &>/dev/null || continue

            local sudoers_content
            sudoers_content=$(cat "${SUDOERS_TMPL_DIR}/${profile}.sudoers" 2>/dev/null)
            [ -z "$sudoers_content" ] && continue

            # Build sudoers entry with username
            local user_sudoers
            if [ "$profile" = "freq-admin" ]; then
                user_sudoers="${sudoers_content}
${username} ALL=(ALL) NOPASSWD:ALL"
            else
                user_sudoers="${sudoers_content}
${username} ALL=(root) NOPASSWD: FREQ_${profile##freq-}_ALLOW
${username} ALL=(root) !FREQ_${profile##freq-}_DENY"
            fi

            local result
            result=$(freq_ssh "$ip" "
                echo '$user_sudoers' | sudo tee /etc/sudoers.d/freq-${username} > /dev/null && \
                sudo chmod 440 /etc/sudoers.d/freq-${username} && \
                sudo visudo -c -f /etc/sudoers.d/freq-${username} 2>/dev/null && echo ok || echo fail
            " 2>/dev/null)

            if [ "$result" = "ok" ]; then
                echo -e "        ${GREEN}${_TICK}${RESET} $username ${_ARROW} $role ($profile)"
                ok=$((ok + 1))
            else
                echo -e "        ${RED}${_CROSS}${RESET} $username ${_ARROW} FAILED"
                fail=$((fail + 1))
            fi
        done < "$ROLES_FILE"
    done

    echo ""
    echo -e "      ${DIM}Sync complete: $ok deployed, $fail failed${RESET}"
    freq_footer
    log "roles sync: ${#targets_ip[@]} targets, $ok deployed, $fail failed"
}

# _roles_check — check for sudoers drift on fleet hosts
_roles_check() {
    require_ssh_key
    load_hosts

    local targets_ip=() targets_label=()
    case "${1:-}" in
        --all)
            local i
            for ((i=0; i<HOST_COUNT; i++)); do
                [ "${HOST_TYPES[$i]}" != "linux" ] && continue
                targets_ip+=("${HOST_IPS[$i]}")
                targets_label+=("${HOST_LABELS[$i]}")
            done
            ;;
        --help|-h) echo "Usage: freq roles check <host>|--all"; return 0 ;;
        "")  die "Usage: freq roles check <host>|--all" ;;
        *)
            freq_resolve "$1" || die "Host '$1' not found."
            targets_ip+=("$(freq_resolve_ip "$1")")
            targets_label+=("$(freq_resolve_label "$1")")
            ;;
    esac

    [ ${#targets_ip[@]} -eq 0 ] && die "No hosts to check."

    echo ""
    freq_header "Roles Drift Check"
    echo ""

    local t
    for ((t=0; t<${#targets_ip[@]}; t++)); do
        local ip="${targets_ip[$t]}" hostname="${targets_label[$t]}"
        echo -e "      ${_ARROW} ${BOLD}$hostname${RESET}"

        local data
        data=$(freq_ssh "$ip" "
            echo '===DANGEROUS==='
            sudo grep -r 'NOPASSWD:ALL' /etc/sudoers /etc/sudoers.d/ 2>/dev/null | grep -v '^#' | grep -v '${FREQ_SERVICE_ACCOUNT}' | grep -v 'root'
            echo '===UNMANAGED==='
            sudo ls /etc/sudoers.d/ 2>/dev/null | grep -v '^freq-' | grep -v '^README'
            echo '===END==='
        " 2>/dev/null)

        if [ -z "$data" ]; then
            echo -e "        ${RED}${_CROSS} UNREACHABLE${RESET}"
            continue
        fi

        local dangerous unmanaged
        dangerous=$(echo "$data" | sed -n '/===DANGEROUS===/,/===UNMANAGED===/p' | grep -v '===')
        unmanaged=$(echo "$data" | sed -n '/===UNMANAGED===/,/===END===/p' | grep -v '===')

        [ -n "$dangerous" ] && echo -e "        ${RED}${_CROSS} DANGEROUS:${RESET} $dangerous"
        [ -n "$unmanaged" ] && echo -e "        ${YELLOW}${_WARN} Unmanaged:${RESET} $unmanaged"
        [ -z "$dangerous" ] && [ -z "$unmanaged" ] && echo -e "        ${GREEN}${_TICK} clean${RESET}"
    done

    echo ""
    freq_footer
    log "roles check: ${#targets_ip[@]} targets"
}
