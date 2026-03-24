#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/doctor.sh
# Self-Diagnostics & Health Check
#
# Author:  FREQ Project
# -- what mac miller would call 'the process' --
# If this passes, you can sleep at night.
# Commands: cmd_doctor
# Dependencies: core.sh, fmt.sh, vault.sh, resolve.sh, ssh.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# cmd_doctor — Main entry point: freq doctor [--fix] [--verbose]
# ═══════════════════════════════════════════════════════════════════
cmd_doctor() {
    local fix=false
    local verbose=false

    while [ $# -gt 0 ]; do
        case "$1" in
            --fix)     fix=true; shift ;;
            --verbose|-v) verbose=true; shift ;;
            --help|-h)
                echo ""
                echo "Usage: freq doctor [--fix] [--verbose]"
                echo ""
                echo "  Run FREQ self-diagnostics. Checks configuration, permissions,"
                echo "  SSH connectivity, vault integrity, and PVE cluster health."
                echo ""
                echo "Options:"
                echo "  --fix       Attempt automatic repairs for issues found"
                echo "  --verbose   Show detailed output for each check"
                echo "  --help      Show this help"
                echo ""
                return 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Usage: freq doctor [--fix] [--verbose]"
                return 1
                ;;
        esac
    done

    if $fix; then require_admin || return 1; fi

    echo ""
    freq_header "FREQ DOCTOR"
    echo ""
    echo -e "    ${BOLD}${WHITE}FREQ${RESET} v${FREQ_VERSION}  ${DIM}Self-diagnostic${RESET}"
    $fix && echo -e "    ${YELLOW}Fix mode enabled -- will attempt repairs${RESET}"
    echo ""

    local issues=0 fixed=0 ok=0 warnings=0

    # ── Internal status helpers ──────────────────────────────────
    _doc_ok() {
        echo -e "      ${GREEN}${_TICK}${RESET}  $1"
        ok=$((ok + 1))
    }
    _doc_warn() {
        echo -e "      ${YELLOW}${_WARN}${RESET}  $1"
        warnings=$((warnings + 1))
    }
    _doc_fail() {
        echo -e "      ${RED}${_CROSS}${RESET}  $1"
        issues=$((issues + 1))
    }
    _doc_fix() {
        echo -e "      ${CYAN}${_ICO_ZAP}${RESET}  Fixed: $1"
        fixed=$((fixed + 1))
    }
    _doc_info() {
        $verbose && echo -e "      ${DIM}$1${RESET}"
    }

    # ═══════════════════════════════════════════════════════════════
    # CHECK 1: FREQ Configuration
    # ═══════════════════════════════════════════════════════════════
    echo -e "    ${BOLD}${WHITE}Configuration${RESET}"

    # freq.conf loadable
    if [ -f "${FREQ_DIR}/conf/freq.conf" ]; then
        if bash -n "${FREQ_DIR}/conf/freq.conf" 2>/dev/null; then
            _doc_ok "freq.conf: loadable (syntax OK)"
        else
            _doc_fail "freq.conf: syntax error — cannot source"
        fi
    else
        _doc_fail "freq.conf: missing (${FREQ_DIR}/conf/freq.conf)"
    fi

    # FREQ_VERSION set
    if [ -n "${FREQ_VERSION:-}" ]; then
        _doc_ok "FREQ_VERSION: v${FREQ_VERSION}"
    else
        _doc_fail "FREQ_VERSION not set in freq.conf"
    fi

    # Key variables present
    local _missing_vars=0
    local _var _val
    for _var in FREQ_DIR FREQ_DATA_DIR FREQ_LOG FREQ_SSH_KEY HOSTS_FILE USERS_FILE ROLES_FILE GROUPS_FILE FREQ_SERVICE_ACCOUNT FREQ_GROUP; do
        _val="${!_var:-}"
        if [ -z "$_val" ]; then
            _doc_fail "Missing config variable: ${_var}"
            _missing_vars=$((_missing_vars + 1))
        fi
    done
    if [ "$_missing_vars" -eq 0 ]; then
        _doc_ok "All required config variables present"
    fi

    # FREQ_INFRA_NAME (used by protected ops)
    if [ -n "${FREQ_INFRA_NAME:-}" ]; then
        _doc_ok "FREQ_INFRA_NAME: ${FREQ_INFRA_NAME}"
    else
        _doc_warn "FREQ_INFRA_NAME not set (protected operations need this)"
    fi

    # ═══════════════════════════════════════════════════════════════
    # CHECK 2: File Permissions
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}Permissions${RESET}"

    # Helper: check path permissions
    _doc_check_perm() {
        local path="$1" exp_mode="$2" exp_owner="$3" exp_group="$4" label="$5"
        if [ ! -e "$path" ]; then
            _doc_warn "${label}: does not exist (${path})"
            return
        fi
        local cur_mode cur_owner cur_group
        cur_mode=$(stat -c '%a' "$path" 2>/dev/null || echo "000")
        cur_owner=$(stat -c '%U' "$path" 2>/dev/null || echo "unknown")
        cur_group=$(stat -c '%G' "$path" 2>/dev/null || echo "unknown")
        if [ "$cur_mode" = "$exp_mode" ] && [ "$cur_owner" = "$exp_owner" ] && [ "$cur_group" = "$exp_group" ]; then
            _doc_ok "${label}: ${cur_mode} ${cur_owner}:${cur_group}"
        else
            _doc_warn "${label}: ${cur_mode} ${cur_owner}:${cur_group} (expected ${exp_mode} ${exp_owner}:${exp_group})"
            if $fix; then
                chown "${exp_owner}:${exp_group}" "$path" 2>/dev/null
                chmod "$exp_mode" "$path" 2>/dev/null \
                    && _doc_fix "Set ${label} to ${exp_mode} ${exp_owner}:${exp_group}" \
                    || _doc_fail "Cannot fix ${label} (need root?)"
            fi
        fi
    }

    local _expected_group="${FREQ_GROUP}"

    # Directories
    _doc_check_perm "$FREQ_DIR"                755 root root              "Install dir"
    _doc_check_perm "$FREQ_DIR/lib"            755 root root              "Library dir"
    _doc_check_perm "$FREQ_DIR/conf"           755 root root              "Config dir"
    _doc_check_perm "$FREQ_DIR/data"           755 root root              "Data dir"
    _doc_check_perm "$FREQ_DIR/data/keys"      700 root root              "Keys dir"
    _doc_check_perm "$FREQ_DIR/data/vault"     700 root root              "Vault dir"
    _doc_check_perm "$FREQ_DIR/bak"            755 root root              "Backup dir"

    # Dispatcher
    _doc_check_perm "$FREQ_DIR/freq"           750 root "$_expected_group" "Dispatcher"

    # Config files (group-readable for operators)
    _doc_check_perm "${FREQ_DIR}/conf/freq.conf"   644 root "$_expected_group" "freq.conf"
    _doc_check_perm "$HOSTS_FILE"                   644 root root              "hosts.conf"
    _doc_check_perm "$USERS_FILE"                   644 root root              "users.conf"
    _doc_check_perm "$ROLES_FILE"                   644 root root              "roles.conf"
    _doc_check_perm "$GROUPS_FILE"                   644 root root              "groups.conf"

    # Libraries — all should be 644 root:root
    local _lib_bad=0
    local _lf _lm _lo _lg
    for _lf in "$FREQ_DIR"/lib/*.sh; do
        [ ! -f "$_lf" ] && continue
        _lm=$(stat -c '%a' "$_lf" 2>/dev/null)
        _lo=$(stat -c '%U' "$_lf" 2>/dev/null)
        _lg=$(stat -c '%G' "$_lf" 2>/dev/null)
        if [ "$_lm" != "644" ] || [ "$_lo" != "root" ] || [ "$_lg" != "root" ]; then
            _lib_bad=$((_lib_bad + 1))
            if [ $_lib_bad -le 3 ]; then
                _doc_warn "lib/$(basename "$_lf"): $_lm $_lo:$_lg (expected 644 root:root)"
            fi
            if $fix; then
                chown root:root "$_lf" 2>/dev/null
                chmod 644 "$_lf" 2>/dev/null
            fi
        fi
    done
    if [ "$_lib_bad" -eq 0 ]; then
        _doc_ok "All libraries: 644 root:root"
    elif [ "$_lib_bad" -gt 3 ]; then
        _doc_warn "... and $((_lib_bad - 3)) more lib files with wrong permissions"
        $fix && _doc_fix "Fixed all library permissions"
    else
        $fix && [ "$_lib_bad" -gt 0 ] && _doc_fix "Fixed $_lib_bad library file(s)"
    fi

    # Log directory
    local _logdir
    _logdir=$(dirname "$FREQ_LOG")
    if [ -d "$_logdir" ]; then
        _doc_check_perm "$_logdir" 770 root "$_expected_group" "Log directory"
        if [ -f "$FREQ_LOG" ]; then
            if [ -w "$FREQ_LOG" ]; then
                _doc_ok "Log file: writable"
            else
                _doc_warn "Log file: not writable (${FREQ_LOG})"
                if $fix; then
                    chmod 660 "$FREQ_LOG" 2>/dev/null && _doc_fix "Set log file to 660" || _doc_fail "Cannot fix log perms"
                fi
            fi
        else
            _doc_info "Log file doesn't exist yet (will be created on first operation)"
        fi
    else
        _doc_warn "Log directory missing: $_logdir"
        if $fix; then
            mkdir -p "$_logdir" 2>/dev/null
            chown "root:$_expected_group" "$_logdir" 2>/dev/null
            chmod 770 "$_logdir" 2>/dev/null \
                && _doc_fix "Created log directory" \
                || _doc_fail "Cannot create log directory"
        fi
    fi

    # Group-writable libs check (security)
    local _gw_files
    _gw_files=$(find "$FREQ_DIR/lib/" -perm /g+w 2>/dev/null | head -3)
    if [ -z "$_gw_files" ]; then
        _doc_ok "No group-writable libs (security OK)"
    else
        _doc_fail "Group-writable files in lib/ — security risk"
        if $fix; then
            chmod g-w "$FREQ_DIR"/lib/*.sh 2>/dev/null && _doc_fix "Removed group-write from libs"
        fi
    fi

    unset -f _doc_check_perm

    # ═══════════════════════════════════════════════════════════════
    # CHECK 3: SSH Keys
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}SSH Keys${RESET}"

    local _key_path="${FREQ_SSH_KEY}"

    if [ -f "$_key_path" ]; then
        _doc_ok "SSH private key: ${_key_path}"

        # Permissions
        local _kp _ko _kg
        _kp=$(stat -c '%a' "$_key_path" 2>/dev/null || echo "000")
        _ko=$(stat -c '%U' "$_key_path" 2>/dev/null || echo "unknown")
        _kg=$(stat -c '%G' "$_key_path" 2>/dev/null || echo "unknown")
        if [ "$_kp" = "600" ] && [ "$_ko" = "root" ]; then
            _doc_ok "Key permissions: ${_kp} ${_ko}:${_kg}"
        else
            _doc_warn "Key permissions: ${_kp} ${_ko}:${_kg} (expected 600 root:root)"
            if $fix; then
                chown root:root "$_key_path" 2>/dev/null
                chmod 600 "$_key_path" 2>/dev/null \
                    && _doc_fix "Set key to 600 root:root" \
                    || _doc_fail "Cannot fix key permissions"
            fi
        fi

        # Public key
        if [ -f "${_key_path}.pub" ]; then
            _doc_ok "Public key: present"
        else
            _doc_warn "Public key missing: ${_key_path}.pub"
        fi

        # Key type detection
        local _key_type
        _key_type=$(ssh-keygen -l -f "$_key_path" 2>/dev/null | awk '{print $NF}' | tr -d '()')
        if [ -n "$_key_type" ]; then
            _doc_ok "Key type: ${_key_type}"
        fi

        # Check if key is deployed to local service account
        local _svc_home _svc_auth
        _svc_home=$(getent passwd "${FREQ_SERVICE_ACCOUNT}" 2>/dev/null | cut -d: -f6)
        if [ -n "$_svc_home" ]; then
            _svc_auth="${_svc_home}/.ssh/authorized_keys"
            if [ -f "$_svc_auth" ]; then
                local _pubkey_fp
                _pubkey_fp=$(ssh-keygen -l -f "${_key_path}.pub" 2>/dev/null | awk '{print $2}')
                if [ -n "$_pubkey_fp" ] && grep -qF "$_pubkey_fp" "$_svc_auth" 2>/dev/null; then
                    _doc_ok "Key deployed to local ${FREQ_SERVICE_ACCOUNT}"
                elif [ -n "$_pubkey_fp" ]; then
                    # Fingerprint not found — try raw pubkey match
                    local _pubkey_data
                    _pubkey_data=$(awk '{print $2}' "${_key_path}.pub" 2>/dev/null)
                    if [ -n "$_pubkey_data" ] && grep -qF "$_pubkey_data" "$_svc_auth" 2>/dev/null; then
                        _doc_ok "Key deployed to local ${FREQ_SERVICE_ACCOUNT}"
                    else
                        _doc_warn "Key NOT found in ${FREQ_SERVICE_ACCOUNT} authorized_keys"
                    fi
                fi
            else
                _doc_warn "No authorized_keys for ${FREQ_SERVICE_ACCOUNT}"
            fi
        else
            _doc_warn "Service account ${FREQ_SERVICE_ACCOUNT} not found on this host"
        fi
    else
        _doc_fail "SSH private key missing: ${_key_path}"
        echo -e "      ${DIM}Run 'freq init' to generate SSH keys${RESET}"
    fi

    # ═══════════════════════════════════════════════════════════════
    # CHECK 4: Vault
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}Vault${RESET}"

    if [ -f "$VAULT_FILE" ]; then
        _doc_ok "Vault file: ${VAULT_FILE}"

        # Vault permissions
        local _vp _vo _vg
        _vp=$(stat -c '%a' "$VAULT_FILE" 2>/dev/null || echo "000")
        _vo=$(stat -c '%U' "$VAULT_FILE" 2>/dev/null || echo "unknown")
        _vg=$(stat -c '%G' "$VAULT_FILE" 2>/dev/null || echo "unknown")
        if [ "$_vp" = "600" ] && [ "$_vo" = "root" ]; then
            _doc_ok "Vault permissions: ${_vp} ${_vo}:${_vg}"
        else
            _doc_warn "Vault permissions: ${_vp} ${_vo}:${_vg} (expected 600 root:root)"
            if $fix; then
                chown root:root "$VAULT_FILE" 2>/dev/null
                chmod 600 "$VAULT_FILE" 2>/dev/null \
                    && _doc_fix "Set vault to 600 root:root" \
                    || _doc_fail "Cannot fix vault permissions"
            fi
        fi

        # Can decrypt?
        local _vault_entries
        _vault_entries=$(_vault_decrypt 2>/dev/null | grep -cv '^#\|^$' 2>/dev/null)
        _vault_entries=${_vault_entries:-0}
        if [ "$_vault_entries" -gt 0 ] 2>/dev/null; then
            _doc_ok "Vault decryptable: ${_vault_entries} entry(ies)"
        elif [ "$_vault_entries" = "0" ]; then
            _doc_warn "Vault is empty (no credentials stored)"
        else
            _doc_fail "Vault cannot be decrypted (machine-id mismatch?)"
        fi

        # Check for svc-account-pass
        local _svc_pass
        _svc_pass=$(vault_get "DEFAULT" "svc-account-pass" 2>/dev/null)
        if [ -n "$_svc_pass" ]; then
            _doc_ok "Vault has svc-account-pass"
        else
            _doc_warn "Vault missing svc-account-pass (fleet SSH may fail)"
        fi
    else
        _doc_warn "Vault not initialized: ${VAULT_FILE}"
        echo -e "      ${DIM}Run 'freq init' or 'freq vault init' to create vault${RESET}"
    fi

    # ═══════════════════════════════════════════════════════════════
    # CHECK 5: Hosts Configuration
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}Fleet Data${RESET}"

    if [ -f "$HOSTS_FILE" ]; then
        local _hcount
        _hcount=$(grep -cv '^#\|^$' "$HOSTS_FILE" 2>/dev/null)
        _hcount=${_hcount:-0}
        if [ "$_hcount" -gt 0 ]; then
            _doc_ok "Host registry: ${_hcount} host(s)"

            # Load hosts for further checks
            load_hosts

            # Validate types
            local _bad_types=0
            local _i _ht
            for ((_i=0; _i<HOST_COUNT; _i++)); do
                _ht="${HOST_TYPES[$_i]}"
                case "$_ht" in
                    linux|truenas|pfsense|switch|idrac|external) ;;
                    *) _bad_types=$((_bad_types + 1))
                       _doc_warn "Invalid host type '${_ht}' for ${HOST_LABELS[$_i]}" ;;
                esac
            done
            [ "$_bad_types" -eq 0 ] && _doc_ok "All host types valid"

            # Check for duplicate IPs
            local _dup_ips
            _dup_ips=$(awk '!/^#/ && !/^$/ {print $1}' "$HOSTS_FILE" | sort | uniq -d)
            if [ -n "$_dup_ips" ]; then
                _doc_warn "Duplicate IPs: ${_dup_ips}"
            else
                _doc_ok "No duplicate IPs"
            fi

            # Check for duplicate labels
            local _dup_labels
            _dup_labels=$(awk '!/^#/ && !/^$/ {print $2}' "$HOSTS_FILE" | sort | uniq -d)
            if [ -n "$_dup_labels" ]; then
                _doc_warn "Duplicate labels: ${_dup_labels}"
            else
                _doc_ok "No duplicate labels"
            fi
        else
            _doc_warn "Host registry is empty (no hosts configured)"
        fi
    else
        _doc_warn "hosts.conf missing: ${HOSTS_FILE}"
    fi

    # users.conf
    if [ -f "$USERS_FILE" ]; then
        local _ucount
        _ucount=$(grep -cv '^#\|^$' "$USERS_FILE" 2>/dev/null)
        _ucount=${_ucount:-0}
        _doc_ok "User registry: ${_ucount} user(s)"
    else
        _doc_warn "users.conf missing: ${USERS_FILE}"
    fi

    # ═══════════════════════════════════════════════════════════════
    # CHECK 6: Roles Configuration
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}Roles${RESET}"

    if [ -f "$ROLES_FILE" ]; then
        local _rcount
        _rcount=$(grep -cv '^#\|^$' "$ROLES_FILE" 2>/dev/null)
        _rcount=${_rcount:-0}
        if [ "$_rcount" -gt 0 ]; then
            _doc_ok "Role assignments: ${_rcount} entry(ies)"
            # Check for at least one admin
            if grep -q ':admin' "$ROLES_FILE" 2>/dev/null; then
                _doc_ok "At least one admin in roles.conf"
            else
                _doc_warn "No admin entries in roles.conf"
            fi
        else
            _doc_warn "roles.conf is empty"
        fi
    else
        _doc_warn "roles.conf missing: ${ROLES_FILE}"
    fi

    # groups.conf
    if [ -f "$GROUPS_FILE" ]; then
        _doc_ok "groups.conf: present"
    else
        _doc_warn "groups.conf missing: ${GROUPS_FILE}"
    fi

    # ═══════════════════════════════════════════════════════════════
    # CHECK 7: PVE SSH Connectivity
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}PVE Cluster${RESET}"

    if [ "${#PVE_NODES[@]}" -eq 0 ]; then
        _doc_warn "No PVE nodes configured (PVE_NODES is empty)"
    else
        local _pve_ok=0 _pve_fail=0
        local _ni _node_ip _node_name
        for ((_ni=0; _ni<${#PVE_NODES[@]}; _ni++)); do
            _node_ip="${PVE_NODES[$_ni]}"
            _node_name="${PVE_NODE_NAMES[$_ni]:-node${_ni}}"

            freq_debug "Testing SSH to PVE node ${_node_name} (${_node_ip})"

            if freq_ssh "$_node_ip" "true" 2>/dev/null; then
                _doc_ok "PVE ${_node_name} (${_node_ip}): reachable"
                _pve_ok=$((_pve_ok + 1))
            else
                _doc_warn "PVE ${_node_name} (${_node_ip}): unreachable"
                _pve_fail=$((_pve_fail + 1))
            fi
        done

        if [ "$_pve_fail" -eq 0 ]; then
            _doc_info "All ${_pve_ok} PVE nodes reachable"
        fi
    fi

    # ═══════════════════════════════════════════════════════════════
    # CHECK 8: Fleet SSH Sample
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}Fleet SSH (sample)${RESET}"

    # Load hosts if not already loaded
    [ "${HOST_COUNT:-0}" -eq 0 ] && load_hosts

    if [ "${HOST_COUNT:-0}" -eq 0 ]; then
        _doc_warn "No hosts in registry — skipping fleet SSH check"
    else
        local _sample_max=3
        local _sample_count=0
        local _sample_ok=0 _sample_fail=0
        local _fi _fip _flabel _ftype

        for ((_fi=0; _fi<HOST_COUNT && _sample_count<_sample_max; _fi++)); do
            _ftype="${HOST_TYPES[$_fi]}"
            # Skip types that don't support standard SSH
            case "$_ftype" in
                external|idrac) continue ;;
            esac

            _fip="${HOST_IPS[$_fi]}"
            _flabel="${HOST_LABELS[$_fi]}"
            _sample_count=$((_sample_count + 1))

            freq_debug "Testing SSH to ${_flabel} (${_fip}) [${_ftype}]"

            if freq_ssh "$_fip" "true" 2>/dev/null; then
                _doc_ok "${_flabel} (${_fip}): reachable"
                _sample_ok=$((_sample_ok + 1))
            else
                _doc_warn "${_flabel} (${_fip}): unreachable"
                _sample_fail=$((_sample_fail + 1))
            fi
        done

        if [ "$_sample_count" -eq 0 ]; then
            _doc_warn "No SSH-capable hosts found for sample check"
        elif [ "$_sample_fail" -eq 0 ]; then
            _doc_info "All ${_sample_ok} sampled hosts reachable"
        fi

        if [ "$HOST_COUNT" -gt "$_sample_max" ]; then
            local _remaining=$((HOST_COUNT - _sample_count))
            echo -e "      ${DIM}(${_remaining} more hosts not tested — use 'freq fleet status' for full check)${RESET}"
        fi
    fi

    # ═══════════════════════════════════════════════════════════════
    # CHECK 9: Syntax Check (bash -n on all libs)
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}Syntax${RESET}"

    local _syntax_ok=0 _syntax_fail=0
    local _slib
    for _slib in "$FREQ_DIR"/lib/*.sh; do
        [ ! -f "$_slib" ] && continue
        if bash -n "$_slib" 2>/dev/null; then
            _syntax_ok=$((_syntax_ok + 1))
        else
            _doc_fail "Syntax error: $(basename "$_slib")"
            _syntax_fail=$((_syntax_fail + 1))
        fi
    done

    # Check dispatcher too
    if [ -f "$FREQ_DIR/freq" ]; then
        if bash -n "$FREQ_DIR/freq" 2>/dev/null; then
            _syntax_ok=$((_syntax_ok + 1))
        else
            _doc_fail "Syntax error: freq dispatcher"
            _syntax_fail=$((_syntax_fail + 1))
        fi
    fi

    if [ "$_syntax_fail" -eq 0 ]; then
        _doc_ok "All ${_syntax_ok} files pass syntax check"
    fi

    # ═══════════════════════════════════════════════════════════════
    # Additional checks
    # ═══════════════════════════════════════════════════════════════
    echo ""
    echo -e "    ${BOLD}${WHITE}System${RESET}"

    # Stale lockfile
    if [ -f "$FREQ_LOCK" ] || [ -d "${FREQ_LOCK}.d" ]; then
        local _lock_pid
        _lock_pid=$(head -1 "$FREQ_LOCK" 2>/dev/null)
        if [ -n "$_lock_pid" ] && kill -0 "$_lock_pid" 2>/dev/null; then
            _doc_ok "Active lock (PID ${_lock_pid}) — operation in progress"
        else
            _doc_warn "Stale lockfile (PID ${_lock_pid:-?} is dead)"
            if $fix; then
                rm -rf "${FREQ_LOCK}.d" "$FREQ_LOCK" 2>/dev/null \
                    && _doc_fix "Removed stale lockfile" \
                    || _doc_fail "Cannot remove lockfile"
            fi
        fi
    else
        _doc_ok "No stale lockfiles"
    fi

    # Protected ops log
    local _plog="${FREQ_PROTECTED_LOG:-}"
    if [ -n "$_plog" ]; then
        local _plog_dir
        _plog_dir=$(dirname "$_plog")
        if [ -d "$_plog_dir" ] && [ -w "$_plog_dir" ]; then
            _doc_ok "Protected ops log: writable"
        elif [ -f "$_plog" ]; then
            _doc_ok "Protected ops log: ${_plog}"
        else
            _doc_warn "Protected ops log directory not writable: ${_plog_dir}"
        fi
    fi

    # Prerequisites
    if command -v sshpass &>/dev/null; then
        _doc_ok "sshpass: installed"
    else
        _doc_warn "sshpass: not installed (password-based SSH will fail)"
    fi

    if command -v openssl &>/dev/null; then
        _doc_ok "openssl: installed"
    else
        _doc_warn "openssl: not installed (vault encryption will fail)"
    fi

    # NTP
    local _ntp_status
    _ntp_status=$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo "unknown")
    if [ "$_ntp_status" = "yes" ]; then
        _doc_ok "NTP synchronized"
    elif [ "$_ntp_status" = "unknown" ]; then
        _doc_info "NTP status: cannot determine"
    else
        _doc_warn "NTP not synchronized"
    fi

    # qemu-guest-agent
    if systemctl is-active qemu-guest-agent >/dev/null 2>&1; then
        _doc_ok "qemu-guest-agent: running"
    else
        _doc_warn "qemu-guest-agent: not running"
        if $fix; then
            systemctl enable --now qemu-guest-agent 2>/dev/null \
                && _doc_fix "Started qemu-guest-agent" \
                || _doc_info "Cannot start guest agent (may not be a VM)"
        fi
    fi

    # Initialized status
    local _init_file="${FREQ_DIR}/conf/.initialized"
    if [ -f "$_init_file" ]; then
        local _init_ver
        _init_ver=$(cat "$_init_file" 2>/dev/null)
        _doc_ok "Initialized: ${_init_ver}"
    else
        _doc_warn "Not initialized (run 'freq init')"
    fi

    # ═══════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════
    echo ""
    freq_divider "Summary"
    echo ""

    local _total_checks=$((ok + issues + warnings))

    if [ "$issues" -eq 0 ] && [ "$warnings" -eq 0 ]; then
        echo -e "      ${GREEN}${_TICK}${RESET}  ${BOLD}FREQ installation is healthy${RESET} (${ok} checks passed)"
        echo ""
        freq_celebrate 2>/dev/null
        _freq_vibe 2>/dev/null
    elif [ "$issues" -eq 0 ]; then
        echo -e "      ${YELLOW}${_WARN}${RESET}  ${BOLD}${warnings} warning(s)${RESET}, ${ok} checks passed"
        [ "$fixed" -gt 0 ] && echo -e "      ${CYAN}${_ICO_ZAP}${RESET}  ${fixed} issue(s) auto-fixed"
        if ! $fix && [ "$warnings" -gt 0 ]; then
            echo ""
            echo -e "      ${DIM}Run 'freq doctor --fix' to attempt automatic repairs.${RESET}"
        fi
    else
        echo -e "      ${RED}${_CROSS}${RESET}  ${BOLD}${issues} error(s), ${warnings} warning(s)${RESET}, ${ok} checks passed"
        [ "$fixed" -gt 0 ] && echo -e "      ${CYAN}${_ICO_ZAP}${RESET}  ${fixed} issue(s) auto-fixed"
        if ! $fix; then
            echo ""
            echo -e "      ${DIM}Run 'freq doctor --fix' to attempt automatic repairs.${RESET}"
        fi
    fi

    echo ""
    freq_footer

    log "doctor: ${ok} ok, ${issues} errors, ${warnings} warnings, ${fixed} fixed (fix=${fix})"

    # Exit code: 0 = all good, 1 = errors found, 2 = warnings only
    if [ "$issues" -gt 0 ]; then
        return 1
    elif [ "$warnings" -gt 0 ]; then
        return 2
    fi
    return 0
}
