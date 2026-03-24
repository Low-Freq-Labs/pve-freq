#!/bin/bash
# shellcheck disable=SC2034
# =============================================================================
# PVE FREQ v1.0.0 -- lib/core.sh
# Core Utilities: colors, logging, errors, traps, RBAC, lock, protected ops
#
# -- the foundation. everything stands on this. --
# Dependencies: none (loaded first)
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# COLORS — ANSI escape sequences
# -- the palette. every pixel of this matters. --
# ═══════════════════════════════════════════════════════════════════
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; MAGENTA='\033[0;35m'
PURPLE='\033[38;5;93m'; PURPLELIGHT='\033[38;5;135m'
PURPLEDIM='\033[38;5;60m'; PURPLEGLOW='\033[38;5;141m'
WHITE='\033[1;37m'; DIM='\033[2m'; BOLD='\033[1m'; RESET='\033[0m'
BLUE='\033[38;5;69m'; ORANGE='\033[38;5;208m'

# ═══════════════════════════════════════════════════════════════════
# TERMINAL COMPATIBILITY — PuTTY-safe output
# -- where the bass EQ lives --
# unicode is beautiful until you're in putty at 1am. ascii saves lives.
# ═══════════════════════════════════════════════════════════════════
if [ "${FREQ_ASCII:-1}" = "0" ]; then
    # Box drawing — refined single-line with rounded corners
    _B_H="\u2500"; _B_V="\u2502"
    _B_TL="\u256d"; _B_TR="\u256e"; _B_BL="\u2570"; _B_BR="\u256f"
    _B_LM="\u251c"; _B_RM="\u2524"; _B_HH="\u2550"
    # Status indicators
    _TICK="\u2714"; _CROSS="\u2718"; _WARN="\u26a0"; _SPIN="\u25dc"
    _ICO_OK="\u2714"; _ICO_FAIL="\u2718"; _ICO_WARN="\u26a0"; _ICO_INFO="\u25c9"
    _ICO_ZAP="\u26a1"; _ICO_SSH="\u26d3"
    _ICO_GEAR="\u2699"; _ICO_SKULL="\u2620"; _ICO_LOCK="\u26bf"
    # Decorative
    _SPARKLE="\u2728"; _STAR="\u2605"; _DIAMOND="\u25c6"
    _ARROW="\u2192"; _BULLET="\u2022"; _DOT="\u00b7"; _DASH="\u2014"
    _RARROW="\u203a"; _CIRCLE="\u25cf"; _RING="\u25cb"
    _HBAR="\u2501"; _VBAR="\u2503"
    _TRI_R="\u25b8"; _TRI_D="\u25be"
else
    # ASCII fallback — every symbol has a clean equivalent
    _B_H="-"; _B_V="|"
    _B_TL="+"; _B_TR="+"; _B_BL="+"; _B_BR="+"
    _B_LM="+"; _B_RM="+"; _B_HH="="
    _TICK="OK"; _CROSS="!!"; _WARN="!!"; _SPIN="..."
    _SPARKLE="*"; _STAR="*"; _DIAMOND="*"
    _ARROW="->"; _BULLET="*"; _DOT="."; _DASH="--"
    _RARROW=">"; _CIRCLE="*"; _RING="o"
    _HBAR="="; _VBAR="|"
    _TRI_R=">"; _TRI_D="v"
    _ICO_OK="OK"; _ICO_FAIL="!!"; _ICO_WARN="!!"; _ICO_INFO="--"
    _ICO_ZAP="ZAP"; _ICO_SSH="SSH"
    _ICO_GEAR="*"; _ICO_SKULL="!!"; _ICO_LOCK="!!"
fi

# ═══════════════════════════════════════════════════════════════════
# GLOBAL INTERRUPT HANDLER — single Ctrl+C always breaks cleanly
# ═══════════════════════════════════════════════════════════════════
_freq_interrupted=false
_freq_handle_interrupt() {
    _freq_interrupted=true
    echo ""
    echo -e "  ${YELLOW}Interrupted. Cleaning up...${RESET}"
}

# ═══════════════════════════════════════════════════════════════════
# CORE HELPERS — die, log, lock, dry-run
# -- the foundation. everything stands on this. --
# ═══════════════════════════════════════════════════════════════════
die() {
    echo -e ""
    echo -e "    ${RED}${_CROSS} ${RESET}$1"
    freq_unlock 2>/dev/null
    rollback_cleanup 2>/dev/null
    exit 1
}

log() {
    local msg="$*"
    msg=$(echo "$msg" | sed -E 's/(password|pass|passwd|secret|cipassword|credential|svc.pass|root.pass|VAULT_CREDENTIAL)[=: ]*[^ ]*/\1=***REDACTED***/gi')
    local logdir; logdir=$(dirname "$FREQ_LOG")
    if [ ! -d "$logdir" ]; then
        mkdir -p "$logdir" 2>/dev/null
        chmod 775 "$logdir" 2>/dev/null
    fi
    [ -f "$FREQ_LOG" ] || { touch "$FREQ_LOG" 2>/dev/null; chmod 664 "$FREQ_LOG" 2>/dev/null; }
    echo "$(date '+%Y-%m-%d %H:%M:%S') [${FREQ_USER:-$(id -un)}] $msg" >> "$FREQ_LOG" 2>/dev/null
}

freq_debug() {
    [[ "${FREQ_DEBUG:-0}" = "1" ]] && echo -e "  [DEBUG] $*" >&2
}

# ═══════════════════════════════════════════════════════════════════
# LOCK / UNLOCK — Prevent concurrent operations
# ═══════════════════════════════════════════════════════════════════
freq_lock() {
    if [ "$DRY_RUN" = "true" ]; then return 0; fi
    local lockdir="${FREQ_LOCK}.d"
    if mkdir "$lockdir" 2>/dev/null; then
        echo "$$" > "$FREQ_LOCK"
        return 0
    fi
    if [ -f "$FREQ_LOCK" ]; then
        local pid; pid=$(head -1 "$FREQ_LOCK" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            die "FREQ is locked by PID $pid. Another operation is in progress."
        fi
    fi
    rm -rf "$lockdir" "$FREQ_LOCK" 2>/dev/null
    if mkdir "$lockdir" 2>/dev/null; then
        echo "$$" > "$FREQ_LOCK"
        return 0
    fi
    die "Cannot acquire lock."
}

freq_unlock() {
    rm -rf "${FREQ_LOCK}.d" "$FREQ_LOCK" 2>/dev/null || true
}

trap 'echo ""; echo "  Interrupted."; freq_unlock 2>/dev/null; rollback_cleanup 2>/dev/null; exit 130' INT TERM
trap 'freq_unlock 2>/dev/null' EXIT

# ═══════════════════════════════════════════════════════════════════
# ROLLBACK — Placeholder for multi-step operation recovery
# ═══════════════════════════════════════════════════════════════════
_ROLLBACK_DIR=""
_ROLLBACK_OP=""
_ROLLBACK_COUNT=0

rollback_cleanup() {
    [ -n "$_ROLLBACK_DIR" ] && [ -d "$_ROLLBACK_DIR" ] && rm -rf "$_ROLLBACK_DIR" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# RETRY / SKIP / QUIT — Offer recovery at every failure point
# ═══════════════════════════════════════════════════════════════════
ask_rsq() {
    local msg="${1:-Something went wrong.}"
    if [ ! -t 0 ]; then
        echo -e "    ${YELLOW}${_STAR} ${msg} (non-interactive — auto-skipping)${RESET}" >&2
        return 1
    fi
    echo ""
    echo -e "    ${YELLOW}${_STAR} ${msg}${RESET}"
    echo ""
    echo -e "    ${PURPLELIGHT}R${RESET} Retry    ${PURPLELIGHT}S${RESET} Skip    ${PURPLELIGHT}Q${RESET} Quit to menu"
    echo ""
    local _rsq_tries=0
    while [[ $_rsq_tries -lt 20 ]]; do
        _rsq_tries=$((_rsq_tries + 1))
        if ! read -t 120 -rp "    ${_SPARKLE} > " _c; then
            echo ""
            echo -e "    ${YELLOW}Timed out. Defaulting to Skip.${RESET}"
            return 1
        fi
        case "${_c,,}" in
            r|retry) return 0 ;; s|skip) return 1 ;; q|quit) return 2 ;;
            "") echo -e "    ${DIM}Type R to retry, S to skip, or Q to quit${RESET}" ;;
            *) echo -e "    ${DIM}Type R, S, or Q${RESET}" ;;
        esac
    done
    echo -e "    ${YELLOW}Too many invalid inputs. Defaulting to Skip.${RESET}"
    return 1
}

# ═══════════════════════════════════════════════════════════════════
# SSH KEY DETECTION — Find the operator's key for PVE/fleet access
# ═══════════════════════════════════════════════════════════════════
freq_detect_ssh_key() {
    if [ -n "${FREQ_KEY:-}" ] && [ -r "$FREQ_KEY" ]; then
        FREQ_KEY_PATH="$FREQ_KEY"
    elif [ -n "${FREQ_SSH_KEY:-}" ] && [ -r "$FREQ_SSH_KEY" ]; then
        FREQ_KEY_PATH="$FREQ_SSH_KEY"
    elif [ -r "${FREQ_DIR}/data/keys/freq_id_rsa" ]; then
        FREQ_KEY_PATH="${FREQ_DIR}/data/keys/freq_id_rsa"
    elif [ -r "$HOME/.ssh/id_ed25519" ]; then
        FREQ_KEY_PATH="$HOME/.ssh/id_ed25519"
    elif [ -r "$HOME/.ssh/id_rsa" ]; then
        FREQ_KEY_PATH="$HOME/.ssh/id_rsa"
    fi

    if [ -n "$FREQ_KEY_PATH" ]; then
        SSH_OPTS="-i $FREQ_KEY_PATH -o ConnectTimeout=${SSH_CONNECT_TIMEOUT:-5} -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ForwardAgent=no -o ControlMaster=no -o ControlPath=none"
    else
        SSH_OPTS="-o ConnectTimeout=${SSH_CONNECT_TIMEOUT:-5} -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ForwardAgent=no -o ControlMaster=no -o ControlPath=none"
    fi

    FLEET_KEY_PATH="$FREQ_KEY_PATH"
    SSH_KEY_PATH="$FREQ_KEY_PATH"
}

require_ssh_key() {
    if [ -z "$FREQ_KEY_PATH" ]; then
        if [ -f "${FREQ_DIR}/data/keys/freq_id_rsa" ] && [ ! -r "${FREQ_DIR}/data/keys/freq_id_rsa" ]; then
            die "SSH key exists at ${FREQ_DIR}/data/keys/freq_id_rsa but is not readable by $(id -un). Run 'freq doctor --fix' as root, or: chown root:$FREQ_GROUP ${FREQ_DIR}/data/keys/freq_id_rsa && chmod 640 ${FREQ_DIR}/data/keys/freq_id_rsa"
        fi
        die "No SSH key found. Set FREQ_KEY, FREQ_SSH_KEY in freq.conf, or place key at ${FREQ_DIR}/data/keys/freq_id_rsa"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# SSH PUBLIC KEY — For cloud-init injection
# ═══════════════════════════════════════════════════════════════════
get_ssh_pubkey() {
    if [ -n "${FREQ_KEY_PATH:-}" ] && [ -f "${FREQ_KEY_PATH}.pub" ]; then
        cat "${FREQ_KEY_PATH}.pub"
        return 0
    fi
    for _kp in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub"; do
        if [ -f "$_kp" ]; then
            cat "$_kp"
            return 0
        fi
    done
    return 1
}

# ═══════════════════════════════════════════════════════════════════
# CONFIRMATION — THE standard confirmation wrapper
# ═══════════════════════════════════════════════════════════════════
_freq_confirm() {
    local msg="$1"
    local mode="${2:-}"

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would prompt: ${msg}"
        return 1
    fi
    if [ "${FREQ_YES:-false}" = "true" ]; then
        log "auto-yes: ${msg}"
        return 0
    fi
    if [ ! -t 0 ]; then
        echo -e "  ${RED}${_CROSS}${RESET}  Non-interactive stdin — use --yes to approve non-interactively."
        echo -e "  ${DIM}Aborted: ${msg}${RESET}"
        return 1
    fi
    if [ "$mode" = "--danger" ]; then
        echo ""
        echo -e "  ${RED}${_WARN}  ${msg}${RESET}"
        local ans
        read -t 60 -rp "  Type 'yes' to confirm: " ans || { echo ""; echo "  Timed out."; return 1; }
        [ "$ans" = "yes" ] && return 0 || return 1
    fi
    if [ "$mode" = "--default-yes" ]; then
        local ans
        read -t 60 -rp "  ${msg} [Y/n]: " ans || ans="n"
        case "$ans" in n|N) return 1 ;; *) return 0 ;; esac
    fi
    local ans
    read -t 60 -rp "  ${msg} [y/N]: " ans || ans="n"
    case "$ans" in y|Y) return 0 ;; *) return 1 ;; esac
}

# ═══════════════════════════════════════════════════════════════════
# IMMUTABLE ACCOUNT PROTECTION
# ═══════════════════════════════════════════════════════════════════
readonly -a IMMUTABLE_ACCOUNTS=("root" "$FREQ_SERVICE_ACCOUNT")

is_immutable() {
    local u="$1" ia
    for ia in "${IMMUTABLE_ACCOUNTS[@]}"; do [ "$u" = "$ia" ] && return 0; done
    return 1
}

require_not_immutable() {
    local u="$1" action="${2:-modify}"
    if is_immutable "$u"; then
        echo ""
        echo -e "    ${RED}BLOCKED${RESET}: '${BOLD}$u${RESET}' is an ${RED}immutable system account${RESET}."
        echo -e "    ${DIM}Immutable accounts (${IMMUTABLE_ACCOUNTS[*]}) -- action '$action' is blocked.${RESET}"
        echo -e "    ${DIM}This protection is hardcoded and cannot be bypassed.${RESET}"
        echo ""
        return 1
    fi
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# ACTION LABELS — Visual indicators for state-changing operations
# ═══════════════════════════════════════════════════════════════════
freq_action_modify() {
    local desc="${1:-}"
    echo -e "    ${YELLOW}${_ICO_GEAR} [MODIFY]${RESET} ${desc}"
}

freq_action_risky() {
    local desc="${1:-}"
    if [ "$DRY_RUN" = "true" ]; then
        echo -e "    ${CYAN}[DRY-RUN]${RESET} ${desc} ${DIM}(risky action skipped)${RESET}"
        return 0
    fi
    echo -e "    ${RED}${_ICO_SKULL} [RISKY]${RESET} ${desc}"
    if [ "${FREQ_YES:-false}" != "true" ]; then
        if [ -t 0 ]; then
            read -t 60 -rp "    Continue? [y/N]: " _confirm || _confirm="n"
            [[ "$_confirm" =~ ^[Yy] ]] || { echo -e "    ${DIM}Cancelled.${RESET}"; return 1; }
        fi
    fi
}

# ═══════════════════════════════════════════════════════════════════
# RBAC — Role-based access checks
# ═══════════════════════════════════════════════════════════════════
is_privileged() {
    local u="$1"
    echo "$PRIV_ACCOUNTS" | grep -qw "$u"
}

_is_protected_vmid() {
    local vmid="$1"
    [[ "$vmid" =~ ^[0-9]+$ ]] || return 1
    PROTECTED_TYPE=""
    # Check explicit list first
    local p
    for p in "${PROTECTED_VMIDS[@]}"; do
        [ "$vmid" = "$p" ] && { PROTECTED_TYPE="explicit"; return 0; }
    done
    # Production range (default: 900-999)
    if [ "$vmid" -ge "${PROTECTED_PROD_RANGE_START:-900}" ] && \
       [ "$vmid" -le "${PROTECTED_PROD_RANGE_END:-999}" ]; then
        PROTECTED_TYPE="production"
        return 0
    fi
    # Template range (default: 9000-9999)
    if [ "$vmid" -ge "${PROTECTED_TEMPLATE_RANGE_START:-9000}" ] && \
       [ "$vmid" -le "${PROTECTED_TEMPLATE_RANGE_END:-9999}" ]; then
        PROTECTED_TYPE="template"
        return 0
    fi
    return 1
}

require_admin() {
    if [ "$FREQ_ROLE" != "admin" ]; then
        echo -e "" >&2
        echo -e "    ${RED}${_CROSS} ${RESET}Admin access required" >&2
        echo -e "    ${DIM}Current user: ${FREQ_USER} (${FREQ_ROLE})${RESET}" >&2
        return 1
    fi
}

require_operator() {
    case "$FREQ_ROLE" in
        admin|operator) return 0 ;;
        *)
            echo -e "" >&2
            echo -e "    ${RED}${_CROSS} ${RESET}This operation requires operator role or higher." >&2
            echo -e "    ${DIM}Current role: ${FREQ_ROLE}${RESET}" >&2
            return 1
            ;;
    esac
}

require_elevated() {
    local action_desc="${1:-this action}"
    [ "$FREQ_ROLE" = "admin" ] && return 0
    if [ "$FREQ_ROLE" = "operator" ]; then
        local svc_account="${FREQ_SERVICE_ACCOUNT:-freq-admin}"
        if [ ! -t 0 ]; then
            echo -e "    ${RED}${_CROSS} Elevated access required (non-interactive — cannot prompt)${RESET}"
            return 1
        fi
        echo ""
        echo -e "    ${YELLOW}${_WARN} Elevated access required for: ${action_desc}${RESET}"
        echo -e "    ${DIM}Enter ${BOLD}${svc_account}${RESET}${DIM} password to continue, or press Enter to cancel${RESET}"
        echo -n "    Password: "
        if ! read -t 30 -rs _elev_pass; then
            echo ""
            echo -e "    ${RED}${_CROSS} Timed out waiting for password.${RESET}"
            return 1
        fi
        echo ""
        if [ -z "$_elev_pass" ]; then
            echo -e "    ${RED}${_CROSS} Cancelled.${RESET} Ask an admin to perform ${action_desc}."
            unset _elev_pass
            return 1
        fi
        if echo "$_elev_pass" | timeout 5 su - "$svc_account" -c "true" &>/dev/null; then
            unset _elev_pass
            echo -e "    ${GREEN}${_TICK} Elevated access granted${RESET}"
            return 0
        else
            unset _elev_pass
            echo -e "    ${RED}${_CROSS} Authentication failed.${RESET} Ask an admin to perform ${action_desc}."
            return 1
        fi
    fi
    die "This operation requires operator role or higher. Current role: ${FREQ_ROLE}"
}

# ═══════════════════════════════════════════════════════════════════
# TIER 4: Protected Operations
# Root password is NEVER stored — used as SSH tunnel for that one command.
# ═══════════════════════════════════════════════════════════════════
PROTECTED_ROOT_PASS=""

_protected_log() {
    local result="$1" user="$2" action="$3" target="$4" detail="${5:-}"
    local logfile="${FREQ_PROTECTED_LOG}"
    local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $result | user=$user | action=$action | target=$target | $detail" >> "$logfile" 2>/dev/null
}

_protected_risk_banner() {
    local action="$1" risk="$2" recovery="$3"
    echo ""
    echo -e "    ${RED}${_WARN}  PROTECTED OPERATION${RESET} — ${BOLD}${action}${RESET}"
    echo -e "    ${DIM}Risk:     ${risk}${RESET}"
    echo -e "    ${DIM}Recovery: ${recovery}${RESET}"
    echo ""
}

_protected_locality_check() {
    local action="${1:-unknown}" target="${2:-unknown}"
    if [[ ! -t 0 ]]; then
        echo -e "    ${RED}${_CROSS} Non-interactive — cannot complete locality check${RESET}"
        return 1
    fi
    echo -e "    ${YELLOW}Type your infrastructure name to confirm physical access:${RESET}"
    echo -n "    > "
    local _infra_input
    if ! read -t 30 -r _infra_input; then
        echo ""
        echo -e "    ${RED}${_CROSS} Timed out waiting for input.${RESET}"
        return 1
    fi
    local infra="${FREQ_INFRA_NAME:-UNNAMED}"
    if [ "$_infra_input" != "$infra" ]; then
        echo -e "    ${RED}${_CROSS} Incorrect. Protected operation cancelled.${RESET}"
        _protected_log "BLOCKED" "${FREQ_USER:-$(id -un)}" "$action" "$target" "locality-check-failed"
        return 1
    fi
    return 0
}

_protected_root_auth() {
    local target_host="$1"
    local action_desc="${2:-protected operation}"
    local max_retries=3
    local attempt=0

    while [ $attempt -lt $max_retries ]; do
        attempt=$((attempt + 1))
        echo -e "    ${DIM}Root password for ${target_host}:${RESET}"
        echo -n "    Password: "
        local _root_pass
        if ! read -t 30 -rs _root_pass; then
            echo ""
            echo -e "    ${RED}${_CROSS} Timed out waiting for password.${RESET}"
            _protected_log "CANCELLED" "${FREQ_USER:-$(id -un)}" "$action_desc" "$target_host" "timeout"
            return 1
        fi
        echo ""
        if [ -z "$_root_pass" ]; then
            echo -e "    ${RED}${_CROSS} Cancelled.${RESET}"
            _protected_log "CANCELLED" "${FREQ_USER:-$(id -un)}" "$action_desc" "$target_host" "empty-password"
            return 1
        fi
        if SSHPASS="$_root_pass" sshpass -e ssh -n -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
            root@"$target_host" "echo OK" &>/dev/null; then
            PROTECTED_ROOT_PASS="$_root_pass"
            echo -e "    ${GREEN}${_TICK} Root access verified${RESET}"
            _protected_log "GRANTED" "${FREQ_USER:-$(id -un)}" "$action_desc" "$target_host" "attempt-$attempt"
            return 0
        else
            echo -e "    ${RED}${_CROSS} Authentication failed (attempt $attempt/$max_retries)${RESET}"
            if [ $attempt -lt $max_retries ]; then
                echo -e "    ${DIM}TIP: Fleet-wide root passwords (24+ chars, 3+ special) make this easier.${RESET}"
            fi
        fi
    done

    echo -e "    ${RED}${_CROSS} Root authentication failed after $max_retries attempts.${RESET}"
    _protected_log "FAILED" "${FREQ_USER:-$(id -un)}" "$action_desc" "$target_host" "max-retries-exceeded"
    return 1
}

require_protected() {
    local action_desc="$1"
    local target_host="$2"
    local risk_line="${3:-}"
    local recovery_line="${4:-}"
    local no_locality=false
    [[ "${5:-}" == "--no-locality" ]] && no_locality=true

    if [ ! -t 0 ]; then
        echo -e "    ${RED}${_CROSS} Protected operation requires interactive terminal${RESET}"
        _protected_log "BLOCKED" "${FREQ_USER:-$(id -un)}" "$action_desc" "$target_host" "non-interactive"
        return 1
    fi
    if [ "$FREQ_ROLE" != "admin" ]; then
        echo ""
        echo -e "    ${RED}${_CROSS} PROTECTED OPERATION${RESET} — ${BOLD}${action_desc}${RESET}"
        echo -e "    ${DIM}This requires an admin with ROOT ACCESS to the target system.${RESET}"
        echo -e "    ${DIM}Contact an admin who can provide root credentials.${RESET}"
        echo -e "    ${DIM}Current user: ${FREQ_USER:-$(id -un)} (${FREQ_ROLE:-unknown})${RESET}"
        _protected_log "BLOCKED" "${FREQ_USER:-$(id -un)}" "$action_desc" "$target_host" "role-${FREQ_ROLE:-unknown}"
        return 1
    fi
    if ! $no_locality && [ -n "$risk_line" ]; then
        _protected_risk_banner "$action_desc" "$risk_line" "$recovery_line"
    fi
    if ! $no_locality; then
        _protected_locality_check "$action_desc" "$target_host" || return 1
    fi
    _protected_root_auth "$target_host" "$action_desc" || return 1
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# PASSWORD INPUT — Secure double-entry with confirmation
# ═══════════════════════════════════════════════════════════════════
PASS1=""

read_password() {
    local prompt="${1:-New password}"
    local attempts=0 max_attempts=5
    if [ ! -t 0 ]; then
        echo -e "    ${RED}Password input requires a terminal.${RESET}" >&2
        return 1
    fi
    while true; do
        attempts=$((attempts + 1))
        if [ $attempts -gt $max_attempts ]; then
            echo -e "    ${RED}Too many failed attempts ($max_attempts).${RESET}"
            return 1
        fi
        if ! read -t 60 -rsp "    $prompt: " PASS1; then
            echo ""
            echo -e "    ${RED}Timed out waiting for password.${RESET}"
            return 1
        fi
        echo
        [ -z "$PASS1" ] && { echo -e "    ${YELLOW}Cannot be empty.${RESET}"; continue; }
        [ ${#PASS1} -lt 8 ] && { echo -e "    ${YELLOW}Min 8 characters.${RESET}"; continue; }
        local pass2
        if ! read -t 60 -rsp "    Confirm: " pass2; then
            echo ""
            echo -e "    ${RED}Timed out waiting for confirmation.${RESET}"
            return 1
        fi
        echo
        [ "$PASS1" = "$pass2" ] && return 0
        echo -e "    ${YELLOW}Passwords don't match.${RESET}"
    done
}

# ═══════════════════════════════════════════════════════════════════
# CONFIG BACKUP — Save a copy before modifying
# ═══════════════════════════════════════════════════════════════════
backup_config() {
    local file="$1"
    [ ! -f "$file" ] && return
    local backup_dir="${FREQ_DIR}/bak"
    mkdir -p "$backup_dir" 2>/dev/null
    cp "$file" "${backup_dir}/$(basename "$file").$(date +%Y%m%d-%H%M%S).bak" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# NETWORK CONFIG STYLE DETECTION
# ═══════════════════════════════════════════════════════════════════
_freq_net_config_style() {
    local host_ip="$1"
    freq_ssh "$host_ip" '
        if [ -d /etc/netplan ] && ls /etc/netplan/*.yaml >/dev/null 2>&1; then
            if [ -f /etc/cloud/cloud.cfg ]; then
                echo "cloud-init-netplan"
            else
                echo "netplan"
            fi
        elif [ -f /etc/network/interfaces.d/50-cloud-init.cfg ] || \
             [ -f /etc/network/interfaces.d/50-cloud-init ]; then
            echo "cloud-init-interfaces"
        elif ls /etc/network/interfaces.d/*.cfg >/dev/null 2>&1; then
            echo "interfaces.d"
        elif [ -f /etc/network/interfaces ] && grep -q "iface" /etc/network/interfaces 2>/dev/null; then
            echo "interfaces"
        else
            echo "unknown"
        fi
    ' 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# VERSION BUMP — Update FREQ_VERSION in freq.conf
# ═══════════════════════════════════════════════════════════════════
_freq_bump_version() {
    require_admin || return 1
    local new_version="${1:-}"
    [ -z "$new_version" ] && { echo "Usage: freq bump <version>"; return 1; }
    [[ "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Invalid version format. Use X.Y.Z"

    local old_version="$FREQ_VERSION"
    echo ""
    freq_header "Version Bump"
    echo -e "    Bumping ${BOLD}${old_version}${RESET} ${_ARROW} ${BOLD}${new_version}${RESET}"
    echo ""

    sed -i "s/^FREQ_VERSION=\"${old_version}\"/FREQ_VERSION=\"${new_version}\"/" "$FREQ_DIR/conf/freq.conf"
    echo -e "    ${GREEN}${_TICK}${RESET} freq.conf updated"

    local stale
    stale=$(grep -rn "$old_version" "$FREQ_DIR/lib/" "$FREQ_DIR/conf/" "$FREQ_DIR/freq" 2>/dev/null | grep -v "\.bak\|pre-\|broken\|archive/" || true)
    if [ -n "$stale" ]; then
        echo -e "    ${YELLOW}${_WARN} Found references to old version $old_version:${RESET}"
        echo "$stale" | head -20 | while IFS= read -r line; do
            echo -e "      ${DIM}$line${RESET}"
        done
    else
        echo -e "    ${GREEN}${_TICK}${RESET} No stale references to ${old_version}"
    fi

    if bash -n "$FREQ_DIR/freq" 2>/dev/null; then
        echo -e "    ${GREEN}${_TICK}${RESET} Syntax OK"
    else
        echo -e "    ${RED}${_CROSS}${RESET} Syntax FAIL — check manually"
    fi

    echo ""
    echo -e "    ${GREEN}${_TICK}${RESET} Version bumped to ${BOLD}${new_version}${RESET}"
    freq_footer
    log "version: bumped $old_version -> $new_version"
}

# ═══════════════════════════════════════════════════════════════════
# VERSION & HELP — Available from CW-1
# ═══════════════════════════════════════════════════════════════════
cmd_version() {
    local _subtitle="${PACK_SUBTITLE:-${FREQ_BRAND}}"
    freq_header "VERSION"
    freq_blank
    freq_line "${BOLD}${WHITE}PVE FREQ${RESET} v${FREQ_VERSION}  ${DIM}\"The Convergence\"${RESET}"
    freq_line "${DIM}${_subtitle}${RESET}"
    freq_blank
    freq_line "${DIM}${_SPARKLE} ${_DOT} ${_DOT} ${_DOT} ${_STAR} ${_DOT} ${_BULLET} ${_DOT} ${_STAR}  ${FREQ_BRAND}  ${_STAR} ${_DOT} ${_BULLET} ${_DOT} ${_STAR} ${_DOT} ${_DOT} ${_DOT} ${_SPARKLE}${RESET}"
    freq_blank
    freq_line "${DIM}Bash CLI + Python Engine ${_DASH} 40 libs, 6 policies, 4 enforcers${RESET}"
    freq_blank
    freq_footer
}

cmd_help() {
    freq_header "HELP"
    freq_blank
    freq_line "${BOLD}${WHITE}Usage:${RESET}  freq <command> [options]"
    freq_blank

    freq_divider "${BOLD}${WHITE}VM Lifecycle${RESET}"
    freq_line "  ${PURPLELIGHT}create${RESET}     New VM from scratch          ${PURPLELIGHT}list${RESET}       VM inventory"
    freq_line "  ${PURPLELIGHT}clone${RESET}      Clone VM or template         ${PURPLELIGHT}destroy${RESET}    Remove VM permanently"
    freq_line "  ${PURPLELIGHT}resize${RESET}     CPU/RAM/disk adjustment      ${PURPLELIGHT}snapshot${RESET}   Create/manage snapshots"
    freq_line "  ${PURPLELIGHT}import${RESET}     Import external VM           ${PURPLELIGHT}change-id${RESET}  Reassign VMID"

    freq_divider "${BOLD}${WHITE}Fleet Operations${RESET}"
    freq_line "  ${PURPLELIGHT}dashboard${RESET}  Fleet overview               ${PURPLELIGHT}status${RESET}     Host UP/DOWN check"
    freq_line "  ${PURPLELIGHT}info${RESET}       System info for any host     ${PURPLELIGHT}diagnose${RESET}   Deep host analysis"
    freq_line "  ${PURPLELIGHT}run-on${RESET}     Execute command on fleet     ${PURPLELIGHT}docker${RESET}     Container status"
    freq_line "  ${PURPLELIGHT}log${RESET}        Operation history            ${PURPLELIGHT}ssh${RESET}        SSH to any fleet host"

    freq_divider "${BOLD}${WHITE}Host & User Management${RESET}"
    freq_line "  ${PURPLELIGHT}hosts${RESET}      Fleet registry CRUD          ${PURPLELIGHT}discover${RESET}   Auto-find PVE hosts"
    freq_line "  ${PURPLELIGHT}setup${RESET}      Bootstrap new host           ${PURPLELIGHT}onboard${RESET}    Full onboarding flow"
    freq_line "  ${PURPLELIGHT}new-user${RESET}   Create fleet user            ${PURPLELIGHT}users${RESET}      List managed users"
    freq_line "  ${PURPLELIGHT}roles${RESET}      RBAC role assignments        ${PURPLELIGHT}keys${RESET}       SSH key management"

    freq_divider "${BOLD}${WHITE}Proxmox${RESET}"
    freq_line "  ${PURPLELIGHT}vm-overview${RESET} Cluster-wide VM view        ${PURPLELIGHT}vmconfig${RESET}   Edit VM configuration"
    freq_line "  ${PURPLELIGHT}migrate${RESET}    Live migrate between nodes   ${PURPLELIGHT}rescue${RESET}     Serial console rescue"

    freq_divider "${BOLD}${WHITE}Appliances${RESET}"
    freq_line "  ${PURPLELIGHT}pfsense${RESET}    pfSense firewall (12 cmds)   ${PURPLELIGHT}truenas${RESET}    TrueNAS storage (13 cmds)"
    freq_line "  ${PURPLELIGHT}switch${RESET}     Cisco Catalyst (12 cmds)     ${PURPLELIGHT}idrac${RESET}      Dell BMC management"
    freq_line "  ${PURPLELIGHT}vpn${RESET}        WireGuard tunnels            ${PURPLELIGHT}zfs${RESET}        ZFS pool management"

    freq_divider "${BOLD}${WHITE}Monitoring & Security${RESET}"
    freq_line "  ${PURPLELIGHT}audit${RESET}      18-category security scan    ${PURPLELIGHT}harden${RESET}     SSH/security hardening"
    freq_line "  ${PURPLELIGHT}health${RESET}     Fleet health dashboard       ${PURPLELIGHT}watch${RESET}      Monitoring daemon"
    freq_line "  ${PURPLELIGHT}vault${RESET}      Encrypted credentials        ${PURPLELIGHT}media${RESET}      Plex stack monitoring"

    freq_divider "${BOLD}${WHITE}Remediation Engine ${DIM}(v2.0.0)${RESET}"
    freq_line "  ${PURPLELIGHT}check${RESET} ${DIM}<policy>${RESET}  Discover drift (read-only)"
    freq_line "  ${PURPLELIGHT}fix${RESET}   ${DIM}<policy>${RESET}  Remediate + verify (applies changes)"
    freq_line "  ${PURPLELIGHT}diff${RESET}  ${DIM}<policy>${RESET}  Git-style colored diffs"
    freq_line "  ${PURPLELIGHT}policies${RESET}       List available policies"
    freq_line "  ${DIM}Policies: ssh-hardening, ntp-sync, rpcbind-block, docker-security,${RESET}"
    freq_line "  ${DIM}          nfs-security, auto-updates${RESET}"

    freq_divider "${BOLD}${WHITE}Operations ${DIM}(v2.0.0)${RESET}"
    freq_line "  ${PURPLELIGHT}learn${RESET}      Searchable knowledge base    ${PURPLELIGHT}risk${RESET}       Blast radius analyzer"
    freq_line "  ${PURPLELIGHT}creds${RESET}      Fleet credential management  ${PURPLELIGHT}checkpoint${RESET} Pre-change safety"

    freq_divider "${BOLD}${WHITE}Utilities${RESET}"
    freq_line "  ${PURPLELIGHT}doctor${RESET}     Self-diagnostic (35+ checks) ${PURPLELIGHT}init${RESET}       First-time setup"
    freq_line "  ${PURPLELIGHT}journal${RESET}    Operation journal            ${PURPLELIGHT}backup${RESET}     Config snapshots"
    freq_line "  ${PURPLELIGHT}version${RESET}    Build information            ${PURPLELIGHT}help${RESET}       This screen"

    freq_blank
    freq_line "${BOLD}${WHITE}Global Flags:${RESET}"
    freq_line "  ${PURPLELIGHT}--dry-run${RESET}  Preview without changes      ${PURPLELIGHT}--json${RESET}     Machine-readable output"
    freq_line "  ${PURPLELIGHT}--yes${RESET}      Skip confirmations           ${PURPLELIGHT}--debug${RESET}    Verbose trace output"
    freq_blank
    freq_line "${DIM}Roles: viewer (read-only) ${_RARROW} operator (fleet ops) ${_RARROW} admin (full access)${RESET}"
    freq_blank
    freq_footer
}
