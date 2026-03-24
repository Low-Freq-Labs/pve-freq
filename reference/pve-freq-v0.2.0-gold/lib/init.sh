#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 — lib/init.sh
# First-Run Setup Wizard
#
# Author:  LOW FREQ Labs / JARVIS
#
# Full initialization: service account, vault, SSH keys, fleet deployment
# -- the genesis. everything starts here. --
#
# Commands: cmd_init
# Dependencies: core.sh, fmt.sh, vault.sh, ssh.sh, resolve.sh, validate.sh, personality.sh
# =============================================================================

# shellcheck disable=SC2154
# External variables from resolve.sh (load_hosts): host_count, host_ips, host_labels, host_types
# External variables from core.sh/fmt.sh: FREQ_DIR, GREEN, RED, YELLOW, BOLD, WHITE, DIM, RESET,
#   _TICK, _CROSS, _WARN, _BULLET, _DASH, _ARROW, _STAR, _SPARKLE, _DOT, PASS1

FREQ_INIT_FILE="${FREQ_DIR}/conf/.initialized"

# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY: cmd_init
# Usage: freq init [--dry-run] [--reset] [--check] [--help]
# ═══════════════════════════════════════════════════════════════════
cmd_init() {
    local do_reset=false do_check=false

    # Parse init-specific flags
    while [ $# -gt 0 ]; do
        case "$1" in
            --reset) do_reset=true ;;
            --check) do_check=true ;;
            --help|-h)
                _init_usage
                return 0
                ;;
            *)
                echo -e "  ${RED}Unknown option: $1${RESET}"
                _init_usage
                return 1
                ;;
        esac
        shift
    done

    # --check mode: non-destructive validation only
    if $do_check; then
        _init_check
        return $?
    fi

    # Must be root for account creation, vault, key permissions
    if [ "$(id -u)" -ne 0 ]; then
        die "freq init must be run as root (needed for account creation, vault, SSH keys)"
    fi

    # --reset mode: wipe and start fresh (tier 4 protected)
    if $do_reset; then
        _init_reset
        return $?
    fi

    # Personality locality check
    if [ -t 0 ]; then
        echo ""
        echo -e "    ${DIM}Are you deploying this while local to the infrastructure?${RESET}"
        echo -e "    ${DIM}If yes, you either work at a datacenter or haven't FULLY${RESET}"
        echo -e "    ${DIM}completed the setup necessary to make this easy bro...${RESET}"
        echo ""
        echo -e "    ${DIM}You'll get there...${RESET}"
        echo ""
        echo -n "    [press any key to continue] "
        read -t 120 -rsn1 _init_ack || true
        echo ""
    fi

    # Dry-run: show what init would do
    if [ "$DRY_RUN" = "true" ]; then
        _init_dry_run
        return 0
    fi

    # Check if already initialized — offer re-run
    if [ -f "$FREQ_INIT_FILE" ]; then
        local ver
        ver=$(cat "$FREQ_INIT_FILE" 2>/dev/null)
        echo ""
        echo -e "    ${GREEN}${_TICK}${RESET} FREQ already initialized (${ver:-unknown})"
        echo -e "    ${DIM}Run 'freq doctor' to check status, or re-run wizard below.${RESET}"
        echo ""
        read -t 30 -rp "    Re-run initialization wizard? [y/N]: " _rerun || _rerun="n"
        [[ "$_rerun" =~ ^[Yy] ]] || return 0
    fi

    # ── Phase 1/8: Welcome ────────────────────────────────────────
    _init_welcome

    # ── Phase 2/8: Service Account ────────────────────────────────
    _init_service_account || return 1

    # ── Phase 3/8: SSH Keys ───────────────────────────────────────
    _init_ssh_keys

    # ── Phase 4/8: PVE Node Deployment ────────────────────────────
    _init_pve_deploy

    # ── Phase 5/8: Fleet Host Deployment ──────────────────────────
    _init_fleet_deploy

    # ── Phase 6/8: Admin Accounts ─────────────────────────────────
    _init_admin_setup

    # ── Phase 7/8: Configuration + Verification ───────────────────
    _init_verify

    # ── Phase 8/8: Summary ────────────────────────────────────────
    _init_summary

    log "init: FREQ initialized (${FREQ_VERSION})"
}

# ═══════════════════════════════════════════════════════════════════
# USAGE
# ═══════════════════════════════════════════════════════════════════
_init_usage() {
    echo ""
    echo "  Usage: freq init [OPTIONS]"
    echo ""
    echo "  First-run setup wizard for PVE FREQ."
    echo "  Creates service account, vault, SSH keys, deploys to fleet."
    echo ""
    echo "  Options:"
    echo "    --check      Non-destructive validation (read-only)"
    echo "    --reset      Wipe vault, roles, .initialized (fresh start)"
    echo "    --dry-run    Show what init would do without making changes"
    echo "    --help       Show this help"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# --check: Non-destructive validation
# ═══════════════════════════════════════════════════════════════════
_init_check() {
    freq_header "FREQ Init Check (read-only)"
    freq_blank

    local pass=0 fail=0 warn=0
    local svc_name="${FREQ_SERVICE_ACCOUNT:-svc-admin}"

    _ichk() {
        local label="$1" result="$2"
        case "$result" in
            pass) echo -e "    ${GREEN}${_TICK}${RESET} $label"; pass=$((pass + 1)) ;;
            fail) echo -e "    ${RED}${_CROSS}${RESET} $label"; fail=$((fail + 1)) ;;
            warn) echo -e "    ${YELLOW}${_WARN}${RESET} $label"; warn=$((warn + 1)) ;;
        esac
    }

    # Initialized?
    if [ -f "$FREQ_INIT_FILE" ]; then
        _ichk "Initialized: $(cat "$FREQ_INIT_FILE" 2>/dev/null)" pass
    else
        _ichk "Not initialized (.initialized file missing)" warn
    fi

    # Service account
    if id "$svc_name" &>/dev/null; then
        _ichk "Service account '${svc_name}' exists" pass
    else
        _ichk "Service account '${svc_name}' not found" fail
    fi

    # SSH keys
    local key_dir="${FREQ_DIR}/data/keys"
    if [ -f "${key_dir}/freq_id_rsa" ] && [ -f "${key_dir}/freq_id_rsa.pub" ]; then
        _ichk "SSH keypair exists (${key_dir}/freq_id_rsa)" pass
    else
        _ichk "SSH keypair missing (${key_dir}/freq_id_rsa)" fail
    fi

    # Vault
    if [ -f "$VAULT_FILE" ]; then
        _ichk "Vault file exists" pass
        if vault_get "DEFAULT" "svc-account-pass" 2>/dev/null | grep -q '.'; then
            _ichk "Vault: svc-account-pass stored" pass
        else
            _ichk "Vault: svc-account-pass missing or empty" warn
        fi
    else
        _ichk "Vault file missing" fail
    fi

    # Config files
    if [ -r "$HOSTS_FILE" ]; then
        local hcount
        hcount=$(grep -cv '^#\|^$' "$HOSTS_FILE" 2>/dev/null || true); hcount=${hcount:-0}
        _ichk "hosts.conf readable (${hcount} hosts)" pass
    else
        _ichk "hosts.conf not readable" fail
    fi

    if [ -r "$ROLES_FILE" ]; then
        local rcount
        rcount=$(grep -cv '^#\|^$' "$ROLES_FILE" 2>/dev/null || true); rcount=${rcount:-0}
        _ichk "roles.conf readable (${rcount} entries)" pass
    else
        _ichk "roles.conf not readable" fail
    fi

    # freq.conf key variables
    if [ -n "${FREQ_SERVICE_ACCOUNT:-}" ]; then
        _ichk "FREQ_SERVICE_ACCOUNT=${FREQ_SERVICE_ACCOUNT}" pass
    else
        _ichk "FREQ_SERVICE_ACCOUNT not set" fail
    fi

    if [ -n "${FREQ_SSH_MODE:-}" ]; then
        _ichk "FREQ_SSH_MODE=${FREQ_SSH_MODE}" pass
    else
        _ichk "FREQ_SSH_MODE not set" warn
    fi

    # PVE connectivity (non-destructive)
    if [ "${#PVE_NODES[@]}" -gt 0 ] && [ -n "${FREQ_KEY_PATH:-}" ] && [ -f "${FREQ_KEY_PATH:-}" ]; then
        for i in "${!PVE_NODES[@]}"; do
            local nip="${PVE_NODES[$i]}" nname="${PVE_NODE_NAMES[$i]:-node${i}}"
            if ssh -n $SSH_OPTS -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o BatchMode=yes "${REMOTE_USER}@${nip}" "echo OK" &>/dev/null; then
                _ichk "PVE SSH: ${nname} (${nip})" pass
            else
                _ichk "PVE SSH: ${nname} (${nip}) — cannot connect" fail
            fi
        done
    else
        _ichk "PVE SSH: skipped (no key or no nodes)" warn
    fi

    # Log dir
    local log_dir
    log_dir=$(dirname "$FREQ_LOG")
    if [ -d "$log_dir" ] && [ -w "$log_dir" ]; then
        _ichk "Log dir writable (${log_dir})" pass
    else
        _ichk "Log dir not writable (${log_dir})" warn
    fi

    freq_blank
    freq_line "Results: ${GREEN}${pass} pass${RESET}, ${RED}${fail} fail${RESET}, ${YELLOW}${warn} warn${RESET}"
    freq_blank
    freq_footer

    [ "$fail" -eq 0 ] && return 0 || return 1
}

# ═══════════════════════════════════════════════════════════════════
# --reset: Wipe and start fresh (tier 4 protected operation)
# ═══════════════════════════════════════════════════════════════════
_init_reset() {
    require_admin || return 1
    require_protected 4 "init --reset" "Wipe vault, roles, .initialized, SSH keys"

    echo ""
    echo -e "    ${RED}${_CROSS}${RESET} Wiping FREQ initialization state..."

    # Remove .initialized
    rm -f "$FREQ_INIT_FILE"
    echo -e "    ${GREEN}${_TICK}${RESET} Removed .initialized"

    # Remove vault
    if [ -f "$VAULT_FILE" ]; then
        rm -f "$VAULT_FILE"
        echo -e "    ${GREEN}${_TICK}${RESET} Removed vault"
    fi

    # Remove SSH keys
    local key_dir="${FREQ_DIR}/data/keys"
    if [ -d "$key_dir" ]; then
        rm -f "${key_dir}/freq_id_rsa" "${key_dir}/freq_id_rsa.pub"
        echo -e "    ${GREEN}${_TICK}${RESET} Removed SSH keys"
    fi

    # Clear roles.conf (keep file, remove entries)
    if [ -f "$ROLES_FILE" ]; then
        backup_config "$ROLES_FILE"
        : > "$ROLES_FILE"
        echo -e "    ${GREEN}${_TICK}${RESET} Cleared roles.conf (backup saved)"
    fi

    echo ""
    echo -e "    ${DIM}Run 'freq init' to start fresh.${RESET}"
    log "init: reset performed — vault, keys, roles, .initialized wiped"
}

# ═══════════════════════════════════════════════════════════════════
# --dry-run: Show what init would do
# ═══════════════════════════════════════════════════════════════════
_init_dry_run() {
    freq_header "FREQ Init (DRY-RUN)"
    freq_blank
    freq_line "${BOLD}${WHITE}Init wizard would:${RESET}"
    freq_line "  1. Create service account (${FREQ_SERVICE_ACCOUNT:-svc-admin})"
    freq_line "  2. Generate SSH keys at ${FREQ_DIR}/data/keys/"
    freq_line "  3. Deploy to PVE nodes (${PVE_NODE_NAMES[*]:-none configured})"

    local hcount=0
    [ -f "$HOSTS_FILE" ] && hcount=$(grep -cv '^#\|^$' "$HOSTS_FILE" 2>/dev/null || true); hcount=${hcount:-0}
    freq_line "  4. Deploy to fleet hosts (${hcount} hosts in hosts.conf)"
    freq_line "  5. Set up admin accounts and roles"
    freq_line "  6. Configure freq.conf and validate"
    freq_blank
    freq_line "${DIM}No changes made (--dry-run)${RESET}"
    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 1/8: Welcome + Prerequisites
# ═══════════════════════════════════════════════════════════════════
_init_welcome() {
    show_step "INIT" 1 8 "Welcome + Prerequisites"

    freq_header "PVE FREQ First-Run Setup"
    freq_blank
    freq_line "${BOLD}${WHITE}Welcome to PVE FREQ${RESET} ${_DASH} Proxmox Fleet Manager"
    freq_line ""
    freq_line "This wizard will:"
    freq_line "  1. Create a service account for fleet-wide SSH"
    freq_line "  2. Generate SSH keys and deploy them"
    freq_line "  3. Configure PVE nodes and fleet hosts"
    freq_line "  4. Set up admin accounts and roles"
    freq_line "  5. Validate everything works"
    freq_blank
    freq_line "${DIM}You can re-run this wizard anytime with 'freq init'${RESET}"
    freq_blank
    freq_footer
    echo ""

    # Check prerequisites
    local prereq_ok=true
    for cmd_name in sshpass openssl python3; do
        if command -v "$cmd_name" &>/dev/null; then
            echo -e "    ${GREEN}${_TICK}${RESET} ${cmd_name} found"
        else
            echo -e "    ${RED}${_CROSS}${RESET} ${cmd_name} not found — install before continuing"
            prereq_ok=false
        fi
    done

    if ! $prereq_ok; then
        echo ""
        echo -e "    ${RED}Missing prerequisites. Install them and re-run 'freq init'.${RESET}"
        return 1
    fi
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 2/8: Service Account Setup
# ═══════════════════════════════════════════════════════════════════
_init_service_account() {
    show_step "INIT" 2 8 "Service Account Setup"

    local svc_name="${FREQ_SERVICE_ACCOUNT:-svc-admin}"

    # Ask for service account name
    echo -e "    ${DIM}The service account is used for fleet-wide SSH and elevated operations.${RESET}"
    echo -e "    ${DIM}It will be created on this host and deployed to all managed nodes.${RESET}"
    echo ""
    read -t 60 -rp "    Service account name [${svc_name}]: " _svc_input || _svc_input=""
    [ -n "$_svc_input" ] && svc_name="$_svc_input"
    echo ""

    # Validate username
    if ! validate_username "$svc_name"; then
        die "Invalid service account name: ${svc_name}"
    fi

    # Ask for operator group name
    local grp_name="${FREQ_GROUP:-freq-group}"
    echo -e "    ${DIM}The operator group controls which users can run freq commands.${RESET}"
    read -t 60 -rp "    Operator group name [${grp_name}]: " _grp_input || _grp_input=""
    [ -n "$_grp_input" ] && grp_name="$_grp_input"
    echo ""

    # Create group locally if it doesn't exist
    if ! getent group "$grp_name" &>/dev/null; then
        groupadd "$grp_name" 2>/dev/null || true
        if getent group "$grp_name" &>/dev/null; then
            echo -e "    ${GREEN}${_TICK}${RESET} Group '${grp_name}' created (local)"
        else
            echo -e "    ${YELLOW}${_WARN}${RESET} Could not create group '${grp_name}' locally"
        fi
    else
        echo -e "    ${GREEN}${_TICK}${RESET} Group '${grp_name}' already exists (local)"
    fi

    # Update freq.conf with chosen group
    _init_update_conf "FREQ_GROUP" "\"${grp_name}\""
    FREQ_GROUP="$grp_name"

    # Store for later phases
    _INIT_GRP_NAME="$grp_name"
    echo ""

    # Check if account already exists
    if id "$svc_name" &>/dev/null; then
        echo -e "    ${GREEN}${_TICK}${RESET} Account '${svc_name}' already exists locally"
        local _existing_home
        _existing_home=$(getent passwd "$svc_name" | cut -d: -f6)
        echo -e "    ${DIM}Home: ${_existing_home}${RESET}"

        # Check sudo
        if sudo -u "$svc_name" sudo -n true &>/dev/null; then
            echo -e "    ${GREEN}${_TICK}${RESET} Has NOPASSWD sudo"
        else
            echo -e "    ${YELLOW}${_WARN}${RESET} No NOPASSWD sudo — setting up..."
            _init_setup_sudoers "$svc_name"
        fi

        # Ask for password (to store in vault + deploy to remote hosts)
        echo ""
        echo -e "    ${DIM}Enter the password for '${svc_name}' (needed for vault + remote deployment)${RESET}"
        read_password "Service account password"
        local svc_pass="$PASS1"
    else
        echo -e "    ${DIM}Creating service account '${svc_name}'...${RESET}"
        echo ""

        # Ask for password
        read_password "Password for '${svc_name}'"
        local svc_pass="$PASS1"

        # Create local account
        if getent group "$FREQ_GROUP" &>/dev/null; then
            useradd -m -s /bin/bash -G "$FREQ_GROUP" "$svc_name" 2>/dev/null
        else
            useradd -m -s /bin/bash "$svc_name" 2>/dev/null
        fi

        if id "$svc_name" &>/dev/null; then
            echo -e "    ${GREEN}${_TICK}${RESET} Account '${svc_name}' created"
        else
            echo -e "    ${RED}${_CROSS}${RESET} Failed to create account '${svc_name}'"
            return 1
        fi

        # Set password via chpasswd (no eval)
        printf '%s:%s\n' "$svc_name" "$svc_pass" | chpasswd 2>/dev/null
        echo -e "    ${GREEN}${_TICK}${RESET} Password set"

        # Set up sudoers
        _init_setup_sudoers "$svc_name"
    fi

    # Initialize vault if needed
    if [ ! -f "$VAULT_FILE" ]; then
        vault_init
    fi

    # Store password in vault
    vault_set "DEFAULT" "svc-account-pass" "$svc_pass"
    echo -e "    ${GREEN}${_TICK}${RESET} Password stored in vault (key: svc-account-pass)"

    # Update freq.conf
    _init_update_conf "FREQ_SERVICE_ACCOUNT" "\"${svc_name}\""
    echo -e "    ${GREEN}${_TICK}${RESET} freq.conf updated: FREQ_SERVICE_ACCOUNT=\"${svc_name}\""

    # Export for use in later phases
    FREQ_SERVICE_ACCOUNT="$svc_name"
    _INIT_SVC_NAME="$svc_name"
    _INIT_SVC_PASS="$svc_pass"

    echo ""
    echo -e "    ${DIM}Remember this password — it's your break-glass access (su - ${svc_name})${RESET}"
}

# ═══════════════════════════════════════════════════════════════════
# Local sudoers helper (Linux only)
# ═══════════════════════════════════════════════════════════════════
_init_setup_sudoers() {
    local svc_name="$1"
    local sudoers_file="/etc/sudoers.d/freq-${svc_name}"
    echo "${svc_name} ALL=(ALL) NOPASSWD: ALL" > "$sudoers_file"
    chmod 440 "$sudoers_file"
    if visudo -cf "$sudoers_file" &>/dev/null; then
        echo -e "    ${GREEN}${_TICK}${RESET} Sudoers configured: ${sudoers_file} (validated)"
    else
        rm -f "$sudoers_file"
        echo -e "    ${RED}${_CROSS}${RESET} Sudoers validation failed — removed ${sudoers_file}"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 3/8: SSH Key Generation
# ═══════════════════════════════════════════════════════════════════
_init_ssh_keys() {
    show_step "INIT" 3 8 "SSH Key Generation"

    local key_dir="${FREQ_DIR}/data/keys"
    local key_file="${key_dir}/freq_id_rsa"

    if [ -f "$key_file" ]; then
        echo -e "    ${GREEN}${_TICK}${RESET} FREQ RSA key already exists"
        ssh-keygen -l -f "${key_file}.pub" 2>/dev/null | sed 's/^/    /'
    else
        echo -e "    ${DIM}Generating RSA 4096 keypair...${RESET}"
        mkdir -p "$key_dir"
        chmod 700 "$key_dir"
        ssh-keygen -t rsa -b 4096 -C "freq@$(hostname -s)" \
            -f "$key_file" -N "" 2>/dev/null
        chmod 600 "$key_file"
        chmod 644 "${key_file}.pub"
        echo -e "    ${GREEN}${_TICK}${RESET} FREQ RSA key generated"
        ssh-keygen -l -f "${key_file}.pub" 2>/dev/null | sed 's/^/    /'
    fi

    # Deploy public key to local service account
    local svc_name="${_INIT_SVC_NAME:-${FREQ_SERVICE_ACCOUNT:-svc-admin}}"
    if id "$svc_name" &>/dev/null; then
        local svc_home
        svc_home=$(getent passwd "$svc_name" | cut -d: -f6)
        local ssh_dir="${svc_home}/.ssh"
        local auth_keys="${ssh_dir}/authorized_keys"
        local pubkey
        pubkey=$(cat "${key_file}.pub" 2>/dev/null)

        mkdir -p "$ssh_dir"
        chmod 700 "$ssh_dir"
        chown "${svc_name}:${svc_name}" "$ssh_dir" 2>/dev/null

        if [ -n "$pubkey" ]; then
            if ! grep -qF "$pubkey" "$auth_keys" 2>/dev/null; then
                echo "$pubkey" >> "$auth_keys"
            fi
            chmod 600 "$auth_keys"
            chown "${svc_name}:${svc_name}" "$auth_keys" 2>/dev/null
            echo -e "    ${GREEN}${_TICK}${RESET} Public key deployed to local ${svc_name}"
        fi
    fi
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 4/8: PVE Node Deployment
# ═══════════════════════════════════════════════════════════════════
_init_pve_deploy() {
    show_step "INIT" 4 8 "PVE Node Deployment"

    local svc_name="${_INIT_SVC_NAME:-${FREQ_SERVICE_ACCOUNT:-svc-admin}}"
    local svc_pass="${_INIT_SVC_PASS:-}"

    # Show configured PVE nodes
    if [ "${#PVE_NODES[@]}" -gt 0 ]; then
        echo -e "    ${DIM}PVE nodes from freq.conf:${RESET}"
        local i
        for ((i=0; i<${#PVE_NODES[@]}; i++)); do
            echo -e "      ${_BULLET} ${PVE_NODES[$i]} (${PVE_NODE_NAMES[$i]:-node${i}})"
        done
        echo ""
    else
        echo -e "    ${YELLOW}${_WARN}${RESET} No PVE nodes configured in freq.conf"
        echo -e "    ${DIM}Add nodes to PVE_NODES array in ${FREQ_DIR}/conf/freq.conf${RESET}"
        echo ""
        read -t 120 -rp "    Enter PVE node IPs (space-separated), or Enter to skip: " _pve_input || _pve_input=""
        if [ -z "$_pve_input" ]; then
            echo -e "    ${DIM}Skipping PVE deployment.${RESET}"
            return 0
        fi
        read -ra PVE_NODES <<< "$_pve_input"
    fi

    # Ask how to authenticate for initial root access
    echo -e "    ${DIM}How should FREQ authenticate to PVE nodes for initial setup?${RESET}"
    echo -e "      ${BOLD}A${RESET}) Root password"
    echo -e "      ${BOLD}B${RESET}) Existing SSH key path"
    echo ""
    read -t 60 -rp "    Choice [A/B]: " _auth_choice || _auth_choice="A"

    local auth_method="" auth_pass="" auth_key=""
    case "$_auth_choice" in
        [bB])
            read -t 60 -rp "    SSH key path: " auth_key || auth_key=""
            if [ ! -f "${auth_key:-}" ]; then
                echo -e "    ${RED}${_CROSS}${RESET} Key not found: ${auth_key:-empty}"
                echo -e "    ${DIM}Falling back to password...${RESET}"
                auth_method="password"
                auth_key=""
            else
                auth_method="key"
            fi
            ;;
        *)
            auth_method="password"
            ;;
    esac

    if [ "$auth_method" = "password" ]; then
        read -t 60 -rsp "    Root password for PVE nodes: " auth_pass || { echo ""; die "Timed out waiting for password"; }
        echo
    fi

    # Deploy to each PVE node
    local pve_ok=0 pve_fail=0
    local pubkey
    pubkey=$(cat "${FREQ_DIR}/data/keys/freq_id_rsa.pub" 2>/dev/null)

    for node_ip in "${PVE_NODES[@]}"; do
        echo ""
        echo -e "    ${_ARROW} ${BOLD}${node_ip}${RESET}"
        if _init_deploy_node "$node_ip" "$svc_name" "$svc_pass" "$pubkey" "$auth_method" "$auth_pass" "$auth_key"; then
            pve_ok=$((pve_ok + 1))
        else
            pve_fail=$((pve_fail + 1))
        fi
    done

    echo ""
    echo -e "    PVE deployment: ${GREEN}${pve_ok} OK${RESET}, ${RED}${pve_fail} failed${RESET}"
}

# ── Deploy service account to a single PVE node via root SSH ──────
# BUG FIX #4: No eval injection. Uses export SSHPASS + direct sshpass.
# BUG FIX #6: Key fallback goes to "password" (not "freq").
_init_deploy_node() {
    local node_ip="$1" svc_name="$2" svc_pass="$3" pubkey="$4"
    local auth_method="$5" auth_pass="$6" auth_key="$7"

    local ssh_opts="-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new"

    # --- SSH function for this node (no eval) ---
    _node_ssh() {
        local cmd="$1"
        if [ "$auth_method" = "key" ]; then
            ssh -n -i "$auth_key" $ssh_opts -o BatchMode=yes "root@${node_ip}" "$cmd"
        else
            export SSHPASS="$auth_pass"
            sshpass -e ssh -n $ssh_opts "root@${node_ip}" "$cmd"
            local rc=$?
            unset SSHPASS
            return $rc
        fi
    }

    # Test connectivity
    if ! _node_ssh "echo OK" &>/dev/null; then
        echo -e "      ${RED}${_CROSS}${RESET} Cannot connect to ${node_ip}"
        return 1
    fi
    echo -e "      ${GREEN}${_TICK}${RESET} Connected"

    # Single SSH call: create account, group, password, sudoers, SSH key
    local deploy_script
    deploy_script=$(cat <<DEPLOY_EOF
set -e

# Create account if needed
if ! id '${svc_name}' &>/dev/null; then
    useradd -m -s /bin/bash '${svc_name}' 2>/dev/null || true
fi

# Create/add group
if ! getent group '${_INIT_GRP_NAME:-freq-group}' &>/dev/null; then
    groupadd '${_INIT_GRP_NAME:-freq-group}' 2>/dev/null || true
fi
usermod -aG '${_INIT_GRP_NAME:-freq-group}' '${svc_name}' 2>/dev/null || true

# Set password
printf '%s:%s\n' '${svc_name}' '${svc_pass}' | chpasswd 2>/dev/null || true

# Sudoers
echo '${svc_name} ALL=(ALL) NOPASSWD: ALL' > '/etc/sudoers.d/freq-${svc_name}'
chmod 440 '/etc/sudoers.d/freq-${svc_name}'
visudo -cf '/etc/sudoers.d/freq-${svc_name}' || { rm -f '/etc/sudoers.d/freq-${svc_name}'; echo 'SUDOERS_FAIL'; exit 1; }

# SSH key
svc_home=\$(getent passwd '${svc_name}' | cut -d: -f6)
mkdir -p "\${svc_home}/.ssh"
chmod 700 "\${svc_home}/.ssh"
if [ -n '${pubkey}' ]; then
    grep -qF '${pubkey}' "\${svc_home}/.ssh/authorized_keys" 2>/dev/null || echo '${pubkey}' >> "\${svc_home}/.ssh/authorized_keys"
    chmod 600 "\${svc_home}/.ssh/authorized_keys"
    chown -R '${svc_name}:${svc_name}' "\${svc_home}/.ssh"
fi

echo 'DEPLOY_OK'
DEPLOY_EOF
)
    local result
    result=$(_node_ssh "$deploy_script" 2>&1)
    freq_debug "deploy_node ${node_ip}: ${result}"

    if echo "$result" | grep -q "SUDOERS_FAIL"; then
        echo -e "      ${RED}${_CROSS}${RESET} Sudoers validation failed"
        return 1
    elif echo "$result" | grep -q "DEPLOY_OK"; then
        echo -e "      ${GREEN}${_TICK}${RESET} Account, group, password, sudoers, key deployed"
    else
        echo -e "      ${YELLOW}${_WARN}${RESET} Deploy completed with warnings"
    fi

    # Verify FREQ key access
    local freq_key="${FREQ_DIR}/data/keys/freq_id_rsa"
    if [ -f "$freq_key" ]; then
        if ssh -n -i "$freq_key" -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${svc_name}@${node_ip}" "echo OK" &>/dev/null; then
            echo -e "      ${GREEN}${_TICK}${RESET} Verified: FREQ key works as ${svc_name}"
        else
            echo -e "      ${YELLOW}${_WARN}${RESET} FREQ key login not working yet (may need sshd restart)"
        fi
    fi

    return 0
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 5/8: Fleet Host Deployment
# Routes ALL host types: linux, truenas, pfsense, switch
# BUG FIX #2: pfSense handler exists (NEW)
# BUG FIX #3: Switch handler exists (NEW)
# ═══════════════════════════════════════════════════════════════════
_init_fleet_deploy() {
    show_step "INIT" 5 8 "Fleet Host Deployment"

    # BUG FIX #10: Check data row count, not file size (-s)
    local host_ct=0
    if [ -f "$HOSTS_FILE" ]; then
        host_ct=$(grep -cv '^#\|^$' "$HOSTS_FILE" 2>/dev/null || true); host_ct=${host_ct:-0}
    fi

    if [ "$host_ct" -eq 0 ]; then
        echo -e "    ${DIM}No hosts in hosts.conf — skipping fleet deployment.${RESET}"
        echo -e "    ${DIM}Use 'freq hosts add' to register hosts later.${RESET}"
        return 0
    fi

    load_hosts

    echo -e "    ${DIM}Fleet hosts from hosts.conf:${RESET}"
    local deploy_count=0 skip_count=0 i
    for ((i=0; i<host_count; i++)); do
        local htype="${host_types[$i]}"
        case "$htype" in
            linux|truenas|pfsense)
                echo -e "      ${_BULLET} ${host_ips[$i]} (${host_labels[$i]}) [${htype}]"
                deploy_count=$((deploy_count + 1))
                ;;
            switch)
                echo -e "      ${DIM}${_DASH} ${host_ips[$i]} (${host_labels[$i]}) [switch — connect only]${RESET}"
                deploy_count=$((deploy_count + 1))
                ;;
            *)
                echo -e "      ${DIM}${_DASH} ${host_ips[$i]} (${host_labels[$i]}) [${htype} — skipped]${RESET}"
                skip_count=$((skip_count + 1))
                ;;
        esac
    done
    echo ""
    echo -e "    ${DIM}${deploy_count} deployable hosts, ${skip_count} skipped${RESET}"
    echo ""

    read -t 60 -rp "    Deploy service account to fleet hosts? [y/N]: " _fleet_deploy || _fleet_deploy="n"
    [[ "$_fleet_deploy" =~ ^[Yy] ]] || { echo -e "    ${DIM}Skipped. Run 'freq init' again to deploy later.${RESET}"; return 0; }

    local svc_name="${_INIT_SVC_NAME:-${FREQ_SERVICE_ACCOUNT:-svc-admin}}"
    local svc_pass="${_INIT_SVC_PASS:-}"
    local pubkey
    pubkey=$(cat "${FREQ_DIR}/data/keys/freq_id_rsa.pub" 2>/dev/null)

    # Ask for authentication method
    echo ""
    echo -e "    ${DIM}How should FREQ authenticate to fleet hosts?${RESET}"
    echo -e "      ${BOLD}A${RESET}) Root password (same for all)"
    echo -e "      ${BOLD}B${RESET}) Existing SSH key"
    echo ""
    read -t 60 -rp "    Choice [A/B]: " _fleet_auth || _fleet_auth="A"

    local fleet_auth_method="" fleet_auth_pass="" fleet_auth_key=""
    case "$_fleet_auth" in
        [bB])
            read -t 60 -rp "    SSH key path: " fleet_auth_key || fleet_auth_key=""
            if [ -f "${fleet_auth_key:-}" ]; then
                fleet_auth_method="key"
            else
                echo -e "    ${DIM}Key not found, falling back to password...${RESET}"
                fleet_auth_method="password"
                fleet_auth_key=""
            fi
            ;;
        *)
            fleet_auth_method="password"
            ;;
    esac

    if [ "$fleet_auth_method" = "password" ]; then
        read -t 60 -rsp "    Root password for fleet hosts: " fleet_auth_pass || { echo ""; die "Timed out waiting for password"; }
        echo
    fi

    local fleet_ok=0 fleet_fail=0 fleet_skip=0
    for ((i=0; i<host_count; i++)); do
        local host="${host_ips[$i]}" label="${host_labels[$i]}" htype="${host_types[$i]}"

        # Skip PVE nodes (already done in Phase 4)
        local is_pve=false
        for pve_ip in "${PVE_NODES[@]}"; do
            [ "$host" = "$pve_ip" ] && { is_pve=true; break; }
        done
        if $is_pve; then
            freq_debug "fleet_deploy: skipping ${label} (PVE node, already deployed)"
            continue
        fi

        echo ""
        echo -e "    ${_ARROW} ${BOLD}${label}${RESET} (${host}) [${htype}]"

        case "$htype" in
            linux)
                _init_deploy_fleet_host "$host" "$label" "$svc_name" "$svc_pass" "$pubkey" \
                    "$fleet_auth_method" "$fleet_auth_pass" "$fleet_auth_key"
                ;;
            truenas)
                _init_deploy_truenas "$host" "$label" "$svc_name" "$svc_pass" "$pubkey" \
                    "$fleet_auth_method" "$fleet_auth_pass" "$fleet_auth_key"
                ;;
            pfsense)
                _init_deploy_pfsense "$host" "$label" "$svc_name" "$svc_pass" "$pubkey" \
                    "$fleet_auth_method" "$fleet_auth_pass" "$fleet_auth_key"
                ;;
            switch)
                _init_deploy_switch "$host" "$label" "$svc_name" \
                    "$fleet_auth_method" "$fleet_auth_pass" "$fleet_auth_key"
                ;;
            *)
                echo -e "      ${DIM}Skipped (unsupported type: ${htype})${RESET}"
                fleet_skip=$((fleet_skip + 1))
                continue
                ;;
        esac

        local rc=$?
        if [ $rc -eq 0 ]; then
            fleet_ok=$((fleet_ok + 1))
        else
            fleet_fail=$((fleet_fail + 1))
        fi
    done

    echo ""
    echo -e "    Fleet deployment: ${GREEN}${fleet_ok} OK${RESET}, ${RED}${fleet_fail} failed${RESET}, ${DIM}${fleet_skip} skipped${RESET}"
    [ "$fleet_fail" -gt 0 ] && return 2 || return 0
}

# ── Deploy to standard Linux fleet host ───────────────────────────
# BUG FIX #4: No eval injection — uses export SSHPASS + direct sshpass call
_init_deploy_fleet_host() {
    local host="$1" label="$2" svc_name="$3" svc_pass="$4" pubkey="$5"
    local auth_method="$6" auth_pass="$7" auth_key="$8"

    local ssh_opts="-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new"

    _fleet_ssh() {
        local cmd="$1"
        if [ "$auth_method" = "key" ]; then
            ssh -n -i "$auth_key" $ssh_opts -o BatchMode=yes "root@${host}" "$cmd"
        else
            export SSHPASS="$auth_pass"
            sshpass -e ssh -n $ssh_opts "root@${host}" "$cmd"
            local rc=$?
            unset SSHPASS
            return $rc
        fi
    }

    # Test connectivity
    if ! _fleet_ssh "echo OK" &>/dev/null; then
        echo -e "      ${RED}${_CROSS}${RESET} Cannot connect to ${host}"
        return 1
    fi
    echo -e "      ${GREEN}${_TICK}${RESET} Connected"

    # Single SSH call: account + group + password + sudoers + key
    local deploy_script
    deploy_script=$(cat <<DEPLOY_EOF
set -e
if ! id '${svc_name}' &>/dev/null; then
    useradd -m -s /bin/bash '${svc_name}' 2>/dev/null || true
fi
if ! getent group '${_INIT_GRP_NAME:-freq-group}' &>/dev/null; then
    groupadd '${_INIT_GRP_NAME:-freq-group}' 2>/dev/null || true
fi
usermod -aG '${_INIT_GRP_NAME:-freq-group}' '${svc_name}' 2>/dev/null || true
printf '%s:%s\n' '${svc_name}' '${svc_pass}' | chpasswd 2>/dev/null || true
echo '${svc_name} ALL=(ALL) NOPASSWD: ALL' > '/etc/sudoers.d/freq-${svc_name}'
chmod 440 '/etc/sudoers.d/freq-${svc_name}'
visudo -cf '/etc/sudoers.d/freq-${svc_name}' || { rm -f '/etc/sudoers.d/freq-${svc_name}'; echo 'SUDOERS_FAIL'; exit 1; }
svc_home=\$(getent passwd '${svc_name}' | cut -d: -f6)
mkdir -p "\${svc_home}/.ssh"
chmod 700 "\${svc_home}/.ssh"
if [ -n '${pubkey}' ]; then
    grep -qF '${pubkey}' "\${svc_home}/.ssh/authorized_keys" 2>/dev/null || echo '${pubkey}' >> "\${svc_home}/.ssh/authorized_keys"
    chmod 600 "\${svc_home}/.ssh/authorized_keys"
    chown -R '${svc_name}:${svc_name}' "\${svc_home}/.ssh"
fi
echo 'DEPLOY_OK'
DEPLOY_EOF
)

    local result
    result=$(_fleet_ssh "$deploy_script" 2>&1)

    if echo "$result" | grep -q "SUDOERS_FAIL"; then
        echo -e "      ${RED}${_CROSS}${RESET} Sudoers validation failed"
        return 1
    elif echo "$result" | grep -q "DEPLOY_OK"; then
        echo -e "      ${GREEN}${_TICK}${RESET} Account, group, password, sudoers, key deployed"
        return 0
    else
        echo -e "      ${YELLOW}${_WARN}${RESET} Deploy completed (could not verify)"
        return 0
    fi
}

# ── TrueNAS special deployment ────────────────────────────────────
# BUG FIX #1: /usr/bin/bash (not /bin/bash)
# BUG FIX #7: sudoers setup via middleware (sudo_commands_nopasswd)
# BUG FIX #8: chown with group (:svc_name)
_init_deploy_truenas() {
    local host="$1" label="$2" svc_name="$3" svc_pass="$4" pubkey="$5"
    local auth_method="$6" auth_pass="$7" auth_key="$8"

    local ssh_opts="-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new"

    _tn_ssh() {
        local cmd="$1"
        if [ "$auth_method" = "key" ]; then
            ssh -n -i "$auth_key" $ssh_opts -o BatchMode=yes "root@${host}" "$cmd"
        else
            export SSHPASS="$auth_pass"
            sshpass -e ssh -n $ssh_opts "root@${host}" "$cmd"
            local rc=$?
            unset SSHPASS
            return $rc
        fi
    }

    # Test connectivity
    if ! _tn_ssh "echo OK" &>/dev/null; then
        echo -e "      ${RED}${_CROSS}${RESET} Cannot connect to ${host}"
        return 1
    fi
    echo -e "      ${GREEN}${_TICK}${RESET} Connected (TrueNAS)"

    # Check if user exists via middleware
    local exists
    exists=$(_tn_ssh "midclt call user.query '[[\"username\",\"=\",\"${svc_name}\"]]'" 2>/dev/null)
    if [ -n "$exists" ] && [ "$exists" != "[]" ]; then
        echo -e "      ${GREEN}${_TICK}${RESET} Account '${svc_name}' already exists (TrueNAS middleware)"
    else
        # Create via middleware — BUG FIX #1: /usr/bin/bash (not /bin/bash)
        echo -e "      ${DIM}Creating via TrueNAS middleware...${RESET}"
        local create_payload
        create_payload=$(SVC_NAME="$svc_name" SVC_PASS="$svc_pass" python3 -c "
import json, os
print(json.dumps({
    'username': os.environ['SVC_NAME'],
    'full_name': 'FREQ Service Account',
    'password': os.environ['SVC_PASS'],
    'shell': '/usr/bin/bash',
    'group_create': True
}))")
        _tn_ssh "midclt call user.create '${create_payload}'" 2>/dev/null

        # Verify creation
        exists=$(_tn_ssh "midclt call user.query '[[\"username\",\"=\",\"${svc_name}\"]]'" 2>/dev/null)
        if [ -n "$exists" ] && [ "$exists" != "[]" ]; then
            echo -e "      ${GREEN}${_TICK}${RESET} Account '${svc_name}' created (TrueNAS middleware)"
        else
            echo -e "      ${RED}${_CROSS}${RESET} Failed to create account on TrueNAS"
            return 1
        fi
    fi

    # Create/verify group on TrueNAS via middleware
    if [ -n "${_INIT_GRP_NAME:-}" ]; then
        local tn_grp_exists
        tn_grp_exists=$(_tn_ssh "midclt call group.query '[[\"group\",\"=\",\"${_INIT_GRP_NAME}\"]]'" 2>/dev/null)
        if [ "$tn_grp_exists" = "[]" ] || [ -z "$tn_grp_exists" ]; then
            local grp_payload
            grp_payload=$(python3 -c "import json; print(json.dumps({'name': '${_INIT_GRP_NAME}', 'smb': False}))")
            _tn_ssh "midclt call group.create '${grp_payload}'" 2>/dev/null
            echo -e "      ${GREEN}${_TICK}${RESET} Group '${_INIT_GRP_NAME}' created (TrueNAS middleware)"
        else
            echo -e "      ${GREEN}${_TICK}${RESET} Group '${_INIT_GRP_NAME}' exists (TrueNAS)"
        fi
    fi

    # BUG FIX #7: Set up sudoers via middleware (sudo_commands_nopasswd)
    # TrueNAS SCALE stores sudoers in middleware database, not /etc/sudoers.d/
    local user_id
    user_id=$(_tn_ssh "midclt call user.query '[[\"username\",\"=\",\"${svc_name}\"]]' | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')\"" 2>/dev/null)
    if [ -n "$user_id" ]; then
        local sudo_payload
        sudo_payload=$(python3 -c "import json; print(json.dumps({'sudo_commands_nopasswd': ['ALL']}))")
        _tn_ssh "midclt call user.update ${user_id} '${sudo_payload}'" 2>/dev/null
        echo -e "      ${GREEN}${_TICK}${RESET} Sudoers configured (TrueNAS middleware: NOPASSWD ALL)"
    else
        echo -e "      ${YELLOW}${_WARN}${RESET} Could not configure sudoers (user ID not found)"
    fi

    # Deploy SSH key — BUG FIX #8: chown with group (:svc_name)
    if [ -n "$pubkey" ]; then
        local tn_home
        tn_home=$(_tn_ssh "getent passwd '${svc_name}'" 2>/dev/null | cut -d: -f6)
        if [ -n "$tn_home" ]; then
            _tn_ssh "mkdir -p '${tn_home}/.ssh' && chmod 700 '${tn_home}/.ssh' && (grep -qF '${pubkey}' '${tn_home}/.ssh/authorized_keys' 2>/dev/null || echo '${pubkey}' >> '${tn_home}/.ssh/authorized_keys') && chmod 600 '${tn_home}/.ssh/authorized_keys' && chown -R '${svc_name}:${svc_name}' '${tn_home}/.ssh'" 2>/dev/null
            echo -e "      ${GREEN}${_TICK}${RESET} SSH key deployed (${tn_home})"
        else
            echo -e "      ${YELLOW}${_WARN}${RESET} Could not determine home directory"
        fi
    fi

    return 0
}

# ── pfSense deployment (NEW — BUG FIX #2) ─────────────────────────
# FreeBSD: uses 'pw' commands, sudoers at /usr/local/etc/sudoers.d/
_init_deploy_pfsense() {
    local host="$1" label="$2" svc_name="$3" svc_pass="$4" pubkey="$5"
    local auth_method="$6" auth_pass="$7" auth_key="$8"

    local ssh_opts="-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new"

    _pf_ssh() {
        local cmd="$1"
        if [ "$auth_method" = "key" ]; then
            ssh -n -i "$auth_key" $ssh_opts -o BatchMode=yes "root@${host}" "$cmd"
        else
            export SSHPASS="$auth_pass"
            sshpass -e ssh -n $ssh_opts "root@${host}" "$cmd"
            local rc=$?
            unset SSHPASS
            return $rc
        fi
    }

    # Test connectivity
    if ! _pf_ssh "echo OK" &>/dev/null; then
        echo -e "      ${RED}${_CROSS}${RESET} Cannot connect to ${host}"
        return 1
    fi
    echo -e "      ${GREEN}${_TICK}${RESET} Connected (pfSense/FreeBSD)"

    # FreeBSD deployment script (single SSH call)
    local deploy_script
    deploy_script=$(cat <<'PFEOF'
# Check if user exists
if ! pw usershow 'SVC_PLACEHOLDER' >/dev/null 2>&1; then
    pw useradd 'SVC_PLACEHOLDER' -m -s /bin/sh -c "FREQ Service Account" 2>/dev/null
    if pw usershow 'SVC_PLACEHOLDER' >/dev/null 2>&1; then
        echo 'ACCOUNT_CREATED'
    else
        echo 'ACCOUNT_FAIL'; exit 1
    fi
else
    echo 'ACCOUNT_EXISTS'
fi

# Check if group exists, create if not
if ! pw groupshow 'GRP_PLACEHOLDER' >/dev/null 2>&1; then
    pw groupadd 'GRP_PLACEHOLDER' 2>/dev/null
    echo 'GROUP_CREATED'
fi
pw groupmod 'GRP_PLACEHOLDER' -m 'SVC_PLACEHOLDER' 2>/dev/null

# Set password
echo 'PASS_PLACEHOLDER' | pw usermod 'SVC_PLACEHOLDER' -h 0 2>/dev/null

# Sudoers (FreeBSD path)
mkdir -p /usr/local/etc/sudoers.d
echo 'SVC_PLACEHOLDER ALL=(ALL) NOPASSWD: ALL' > '/usr/local/etc/sudoers.d/freq-SVC_PLACEHOLDER'
chmod 440 '/usr/local/etc/sudoers.d/freq-SVC_PLACEHOLDER'

# SSH key
svc_home=$(pw usershow 'SVC_PLACEHOLDER' | cut -d: -f9)
mkdir -p "${svc_home}/.ssh"
chmod 700 "${svc_home}/.ssh"
PFEOF
)
    # Replace placeholders (avoids variable expansion issues in heredoc)
    deploy_script="${deploy_script//SVC_PLACEHOLDER/$svc_name}"
    deploy_script="${deploy_script//GRP_PLACEHOLDER/${_INIT_GRP_NAME:-freq-group}}"
    deploy_script="${deploy_script//PASS_PLACEHOLDER/$svc_pass}"

    # Append key deployment (needs the actual pubkey value)
    if [ -n "$pubkey" ]; then
        deploy_script="${deploy_script}
svc_home=\$(pw usershow '${svc_name}' | cut -d: -f9)
grep -qF '${pubkey}' \"\${svc_home}/.ssh/authorized_keys\" 2>/dev/null || echo '${pubkey}' >> \"\${svc_home}/.ssh/authorized_keys\"
chmod 600 \"\${svc_home}/.ssh/authorized_keys\"
chown -R '${svc_name}' \"\${svc_home}/.ssh\"
echo 'KEY_DEPLOYED'"
    fi

    deploy_script="${deploy_script}
echo 'PF_DEPLOY_OK'"

    local result
    result=$(_pf_ssh "$deploy_script" 2>&1)
    freq_debug "deploy_pfsense ${host}: ${result}"

    if echo "$result" | grep -q "ACCOUNT_FAIL"; then
        echo -e "      ${RED}${_CROSS}${RESET} Failed to create account"
        return 1
    fi
    if echo "$result" | grep -q "ACCOUNT_CREATED"; then
        echo -e "      ${GREEN}${_TICK}${RESET} Account '${svc_name}' created (FreeBSD pw)"
    elif echo "$result" | grep -q "ACCOUNT_EXISTS"; then
        echo -e "      ${GREEN}${_TICK}${RESET} Account '${svc_name}' already exists"
    fi
    if echo "$result" | grep -q "GROUP_CREATED"; then
        echo -e "      ${GREEN}${_TICK}${RESET} Group '${_INIT_GRP_NAME:-freq-group}' created"
    fi
    echo -e "      ${GREEN}${_TICK}${RESET} Password, sudoers, key deployed"

    # NOTE: pfSense sudoers wipes on reboot/update. Warn the operator.
    echo -e "      ${YELLOW}${_WARN}${RESET} pfSense sudoers may wipe on reboot/update — verify after updates"

    return 0
}

# ── Switch deployment (NEW — BUG FIX #3) ──────────────────────────
# Cisco IOS: connect as existing user, verify connectivity only.
# Switches don't support account creation via SSH — just verify access.
_init_deploy_switch() {
    local host="$1" label="$2" svc_name="$3"
    local auth_method="$4" auth_pass="$5" auth_key="$6"

    local ssh_opts="-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=no"
    ssh_opts="$ssh_opts -o KexAlgorithms=+diffie-hellman-group14-sha1"
    ssh_opts="$ssh_opts -o HostKeyAlgorithms=+ssh-rsa"
    ssh_opts="$ssh_opts -o PubkeyAcceptedKeyTypes=+ssh-rsa"
    ssh_opts="$ssh_opts -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc"

    # Switches typically use an existing admin account
    local sw_user="$svc_name"

    _sw_ssh() {
        local cmd="$1"
        if [ "$auth_method" = "key" ]; then
            echo "$cmd" | ssh -n -i "$auth_key" $ssh_opts "${sw_user}@${host}" 2>/dev/null
        else
            export SSHPASS="$auth_pass"
            echo "$cmd" | sshpass -e ssh -n $ssh_opts "${sw_user}@${host}" 2>/dev/null
            local rc=$?
            unset SSHPASS
            return $rc
        fi
    }

    # Test connectivity — switches respond to 'show version'
    local result
    result=$(_sw_ssh "show version" 2>&1)
    if [ -n "$result" ] && echo "$result" | grep -qi "cisco\|switch\|IOS\|version"; then
        echo -e "      ${GREEN}${_TICK}${RESET} Connected (IOS switch — connectivity verified)"
        echo -e "      ${DIM}Switch accounts must be managed via IOS configure terminal.${RESET}"
        echo -e "      ${DIM}FREQ will use existing credentials for switch operations.${RESET}"
        return 0
    else
        echo -e "      ${YELLOW}${_WARN}${RESET} Could not verify switch connectivity"
        echo -e "      ${DIM}Ensure the switch user '${sw_user}' is configured in IOS.${RESET}"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 6/8: Admin Account Setup
# ═══════════════════════════════════════════════════════════════════
_init_admin_setup() {
    show_step "INIT" 6 8 "Admin Account Setup"

    local current_user
    current_user=$(logname 2>/dev/null || echo "${SUDO_USER:-root}")
    echo -e "    ${DIM}Current user: ${BOLD}${current_user}${RESET}"

    # Ensure roles.conf exists
    [ -f "$ROLES_FILE" ] || touch "$ROLES_FILE"

    # Add current user as admin
    if grep -q "^${current_user}:" "$ROLES_FILE" 2>/dev/null; then
        local existing_role
        existing_role=$(grep "^${current_user}:" "$ROLES_FILE" | cut -d: -f2)
        echo -e "    ${GREEN}${_TICK}${RESET} ${current_user} already in roles.conf (${existing_role})"
    else
        backup_config "$ROLES_FILE"
        echo "${current_user}:admin" >> "$ROLES_FILE"
        echo -e "    ${GREEN}${_TICK}${RESET} Added ${current_user} as admin"
    fi

    # Also ensure service account is admin
    local svc_name="${_INIT_SVC_NAME:-${FREQ_SERVICE_ACCOUNT:-svc-admin}}"
    if ! grep -q "^${svc_name}:" "$ROLES_FILE" 2>/dev/null; then
        echo "${svc_name}:admin" >> "$ROLES_FILE"
        echo -e "    ${GREEN}${_TICK}${RESET} Added ${svc_name} as admin"
    fi

    # Offer to create additional accounts
    echo ""
    read -t 30 -rp "    Create additional admin or operator accounts? [y/N]: " _add_more || _add_more="n"
    if [[ "$_add_more" =~ ^[Yy] ]]; then
        local _acct_loop=0
        while [[ $_acct_loop -lt 100 ]]; do
            _acct_loop=$((_acct_loop + 1))
            echo ""
            if ! read -t 60 -rp "    Username (or press Enter to finish): " _new_user; then
                echo ""
                echo -e "    ${YELLOW}${_WARN}${RESET} Timed out waiting for input."
                break
            fi
            [ -z "$_new_user" ] && break

            if ! validate_username "$_new_user"; then
                echo -e "    ${RED}${_CROSS}${RESET} Invalid username"
                continue
            fi

            echo -e "      ${BOLD}A${RESET}) admin"
            echo -e "      ${BOLD}O${RESET}) operator"
            if ! read -t 30 -rp "    Role [A/O]: " _new_role; then
                echo ""
                echo -e "    ${YELLOW}${_WARN}${RESET} Timed out. Skipping."
                break
            fi

            local role="operator"
            [[ "$_new_role" =~ ^[aA] ]] && role="admin"

            if grep -q "^${_new_user}:" "$ROLES_FILE" 2>/dev/null; then
                echo -e "    ${DIM}${_new_user} already in roles.conf${RESET}"
            else
                echo "${_new_user}:${role}" >> "$ROLES_FILE"
                echo -e "    ${GREEN}${_TICK}${RESET} Added ${_new_user} as ${role}"
            fi
        done
        [[ $_acct_loop -ge 100 ]] && echo -e "    ${YELLOW}${_WARN}${RESET} Max accounts reached (100). Exiting loop."
    fi
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 7/8: Configuration + Verification (merged old phases 7+8)
# BUG FIX #5: Correct step counter (7/8, not 7/9)
# BUG FIX #10: hosts.conf checks data rows, not file size (-s)
# ═══════════════════════════════════════════════════════════════════
_init_verify() {
    show_step "INIT" 7 8 "Configuration + Verification"

    local svc_name="${_INIT_SVC_NAME:-${FREQ_SERVICE_ACCOUNT:-svc-admin}}"

    # --- Configuration updates ---
    echo -e "    ${DIM}Updating freq.conf...${RESET}"

    # Update PVE_SSH_USER to match service account
    _init_update_conf "PVE_SSH_USER" "\"${svc_name}\""
    echo -e "    ${GREEN}${_TICK}${RESET} PVE_SSH_USER=\"${svc_name}\""

    # Update REMOTE_USER
    _init_update_conf "REMOTE_USER" "\"${svc_name}\""
    echo -e "    ${GREEN}${_TICK}${RESET} REMOTE_USER=\"${svc_name}\""

    # Set SSH mode to sudo
    _init_update_conf "FREQ_SSH_MODE" "\"sudo\""
    echo -e "    ${GREEN}${_TICK}${RESET} FREQ_SSH_MODE=\"sudo\""

    # Check hosts.conf (BUG FIX #10: count data rows, not -s)
    local host_ct=0
    if [ -f "$HOSTS_FILE" ]; then
        host_ct=$(grep -cv '^#\|^$' "$HOSTS_FILE" 2>/dev/null || true); host_ct=${host_ct:-0}
    fi
    if [ "$host_ct" -gt 0 ]; then
        echo -e "    ${GREEN}${_TICK}${RESET} hosts.conf: ${host_ct} hosts"
    else
        echo -e "    ${YELLOW}${_WARN}${RESET} hosts.conf is empty — use 'freq hosts add' or 'freq discover'"
    fi

    # Check timezone
    local tz
    tz=$(timedatectl show --property=Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo "unknown")
    echo -e "    ${GREEN}${_TICK}${RESET} Timezone: ${tz}"

    echo ""
    echo -e "    ${DIM}Running verification checks...${RESET}"

    # --- Verification checks ---
    local pass=0 fail=0

    _icheck() {
        local label="$1"; shift
        if "$@" >/dev/null 2>&1; then
            echo -e "    ${GREEN}${_TICK}${RESET} $label"
            pass=$((pass + 1))
        else
            echo -e "    ${RED}${_CROSS}${RESET} $label"
            fail=$((fail + 1))
        fi
    }

    _icheck "Service account exists locally"  id "$svc_name"
    _icheck "FREQ RSA key exists"             test -f "${FREQ_DIR}/data/keys/freq_id_rsa"
    _icheck "Vault exists"                    test -f "$VAULT_FILE"
    _icheck "roles.conf readable"             test -r "$ROLES_FILE"
    _icheck "freq.conf loadable"              test -r "${FREQ_DIR}/conf/freq.conf"

    # Log dir
    local log_dir
    log_dir=$(dirname "$FREQ_LOG")
    mkdir -p "$log_dir" 2>/dev/null
    _icheck "Log dir writable" test -w "$log_dir"

    # Vault data dir
    mkdir -p "$VAULT_DIR" 2>/dev/null
    _icheck "Vault dir exists" test -d "$VAULT_DIR"

    # Check PVE SSH connectivity
    if [ "${#PVE_NODES[@]}" -gt 0 ] && [ -f "${FREQ_DIR}/data/keys/freq_id_rsa" ]; then
        local freq_key="${FREQ_DIR}/data/keys/freq_id_rsa"
        for node_ip in "${PVE_NODES[@]}"; do
            if ssh -n -i "$freq_key" -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${svc_name}@${node_ip}" "echo OK" &>/dev/null; then
                echo -e "    ${GREEN}${_TICK}${RESET} FREQ key connects to ${node_ip}"
                pass=$((pass + 1))
            else
                echo -e "    ${RED}${_CROSS}${RESET} FREQ key cannot connect to ${node_ip}"
                fail=$((fail + 1))
            fi
        done
    fi

    # Check freq.conf values
    if grep -q "FREQ_SERVICE_ACCOUNT=.*${svc_name}" "${FREQ_DIR}/conf/freq.conf" 2>/dev/null; then
        echo -e "    ${GREEN}${_TICK}${RESET} freq.conf FREQ_SERVICE_ACCOUNT matches"
        pass=$((pass + 1))
    else
        echo -e "    ${RED}${_CROSS}${RESET} freq.conf FREQ_SERVICE_ACCOUNT mismatch"
        fail=$((fail + 1))
    fi

    echo ""
    echo -e "    Verification: ${GREEN}${pass} pass${RESET}, ${RED}${fail} fail${RESET}"

    # Mark initialized only if all checks passed
    if [ "$fail" -gt 0 ]; then
        echo -e "    ${RED}${_CROSS}${RESET} NOT marking initialized (${fail} failures — fix and re-run 'freq init')"
        return 1
    fi
    echo "PVE FREQ ${FREQ_VERSION} -- initialized $(date '+%Y-%m-%d %H:%M')" > "$FREQ_INIT_FILE"
    echo -e "    ${GREEN}${_TICK}${RESET} Marked initialized: ${FREQ_INIT_FILE}"
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 8/8: Summary & Next Steps
# BUG FIX #5: show_step 8/8 (not 8/9)
# ═══════════════════════════════════════════════════════════════════
_init_summary() {
    show_step "INIT" 8 8 "Summary"

    local svc_name="${_INIT_SVC_NAME:-${FREQ_SERVICE_ACCOUNT:-svc-admin}}"

    echo ""
    freq_header "Setup Complete"
    freq_blank
    freq_line "${GREEN}${_TICK}${RESET} PVE FREQ ${FREQ_VERSION} is ready."
    freq_blank
    freq_line "${BOLD}What was configured:${RESET}"
    freq_line "  ${_BULLET} Service account: ${BOLD}${svc_name}${RESET}"
    freq_line "  ${_BULLET} SSH key: ${FREQ_DIR}/data/keys/freq_id_rsa"
    freq_line "  ${_BULLET} Vault: ${VAULT_FILE}"
    freq_line "  ${_BULLET} SSH mode: sudo (via ${svc_name})"
    freq_blank
    freq_line "${BOLD}Next steps:${RESET}"
    freq_line "  freq hosts list        ${_DASH} see registered hosts"
    freq_line "  freq discover          ${_DASH} find unregistered VMs"
    freq_line "  freq hosts add         ${_DASH} add your first host"
    freq_line "  freq doctor            ${_DASH} verify FREQ is healthy"
    freq_blank
    freq_line "${DIM}Break-glass access: su - ${svc_name}${RESET}"
    freq_blank
    freq_footer

    freq_celebrate
    time_saved 5
}

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

# Safe config update — preserves file permissions and ownership
# BUG FIX #9: chmod/chown after mv to preserve permissions
_init_update_conf() {
    local key="$1" value="$2"
    local conf_file="${FREQ_DIR}/conf/freq.conf"

    # Capture current permissions and ownership before modifying
    local orig_perms orig_owner
    orig_perms=$(stat -c '%a' "$conf_file" 2>/dev/null)
    orig_owner=$(stat -c '%u:%g' "$conf_file" 2>/dev/null)

    if grep -q "^${key}=" "$conf_file" 2>/dev/null; then
        awk -v k="${key}" -v v="${value}" '
            index($0, k"=") == 1 { $0 = k"="v }
            { print }
        ' "$conf_file" > "${conf_file}.tmp" && mv "${conf_file}.tmp" "$conf_file"
    else
        echo "${key}=${value}" >> "$conf_file"
    fi

    # Restore permissions and ownership after mv (BUG FIX #9)
    if [ -n "$orig_perms" ]; then
        chmod "$orig_perms" "$conf_file" 2>/dev/null
    fi
    if [ -n "$orig_owner" ]; then
        chown "$orig_owner" "$conf_file" 2>/dev/null
    fi
}
