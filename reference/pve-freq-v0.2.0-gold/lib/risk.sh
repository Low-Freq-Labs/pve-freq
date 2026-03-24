#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v2.0.0 -- lib/risk.sh
# Kill-Chain-Aware Blast Radius Analyzer
#
# -- the safety net. no write operation runs without this. --
#
# The DC01 kill-chain: WSL -> WireGuard VPN -> pfSense -> mgmt VLAN 2550 -> target
# If ANY link in that chain breaks, remote management is severed.
# Physical datacenter access becomes the only recovery path.
#
# Risk levels:
#   LOW      Read-only. No state change. Always safe.
#   MEDIUM   Single host impact. Rollback possible.
#   HIGH     Fleet-wide, auth, or data impact. Requires confirmation.
#   CRITICAL Kill-chain. Touching pfSense or WireGuard. Requires explicit yes.
#
# Integration:
#   _risk_gate(command, target) -- called by dispatcher before write commands
#   _risk_assess(command, target) -- full analysis with display
#   cmd_risk(target) -- user-facing: `freq risk <target>`
#
# Dependencies: core.sh, fmt.sh, resolve.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# KILL-CHAIN DEFINITION
# -- the path from your keyboard to the target. break any link, lose everything. --
# ═══════════════════════════════════════════════════════════════════
readonly -a _KC_HOPS=("WSL" "WireGuard" "pfSense" "VLAN 2550" "Target")
readonly -a _KC_DESC=(
    "Operator workstation (Windows Subsystem for Linux)"
    "Encrypted tunnel to datacenter (UDP 51820)"
    "Firewall + VPN endpoint + gateway"
    "Management VLAN (10.25.255.0/24)"
    "Destination host"
)

# ═══════════════════════════════════════════════════════════════════
# READ-ONLY COMMANDS — always safe, never assessed
# ═══════════════════════════════════════════════════════════════════
readonly _RISK_READONLY="list status show info help version doctor dashboard health audit watch journal learn log ssh hosts users roles keys policies diff check vm-overview media diagnose discover docker run-on"

# ═══════════════════════════════════════════════════════════════════
# TARGET CLASSIFICATION — what are we touching?
# ═══════════════════════════════════════════════════════════════════
_RISK_TARGET_CLASS=""
_RISK_TARGET_LABEL=""
_RISK_TARGET_DESC=""

_risk_classify_target() {
    local target="$1"
    _RISK_TARGET_CLASS="standard"
    _RISK_TARGET_LABEL="$target"
    _RISK_TARGET_DESC="Fleet host"

    case "$target" in
        pfsense|fw|firewall|pfsense-lab|fw-lab)
            _RISK_TARGET_CLASS="killchain"
            _RISK_TARGET_LABEL="pfSense"
            _RISK_TARGET_DESC="Firewall / VPN endpoint / default gateway"
            ;;
        truenas|nas|tn|truenas-lab|nas-lab|tn-lab)
            _RISK_TARGET_CLASS="critical"
            _RISK_TARGET_LABEL="TrueNAS"
            _RISK_TARGET_DESC="28TB storage backbone (ZFS pools, NFS/SMB shares)"
            ;;
        pve01|pve02|pve03)
            _RISK_TARGET_CLASS="critical"
            _RISK_TARGET_LABEL="$target"
            _RISK_TARGET_DESC="Proxmox hypervisor (hosts running VMs)"
            ;;
        switch|switch01|sw)
            _RISK_TARGET_CLASS="critical"
            _RISK_TARGET_LABEL="Cisco switch"
            _RISK_TARGET_DESC="All VLAN trunking (one switch = every VLAN)"
            ;;
        idrac-r530|idrac-t620)
            _RISK_TARGET_CLASS="critical"
            _RISK_TARGET_LABEL="$target"
            _RISK_TARGET_DESC="Out-of-band management controller"
            ;;
        all|fleet)
            _RISK_TARGET_CLASS="critical"
            _RISK_TARGET_LABEL="FLEET-WIDE"
            _RISK_TARGET_DESC="Every host in the fleet"
            ;;
        *)
            # Attempt resolver for richer context
            if type freq_resolve_type &>/dev/null; then
                local rtype
                rtype=$(freq_resolve_type "$target" 2>/dev/null) || rtype=""
                case "$rtype" in
                    pfsense)  _RISK_TARGET_CLASS="killchain"
                              _RISK_TARGET_LABEL="pfSense ($target)"
                              _RISK_TARGET_DESC="Firewall / VPN endpoint" ;;
                    truenas)  _RISK_TARGET_CLASS="critical"
                              _RISK_TARGET_LABEL="TrueNAS ($target)"
                              _RISK_TARGET_DESC="Storage backbone" ;;
                    switch)   _RISK_TARGET_CLASS="critical"
                              _RISK_TARGET_LABEL="Switch ($target)"
                              _RISK_TARGET_DESC="Network infrastructure" ;;
                esac
            fi
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# COMMAND RISK MAPPING — what kind of operation is this?
# ═══════════════════════════════════════════════════════════════════
_RISK_CMD_LEVEL=""
_RISK_CMD_CATEGORY=""

_risk_classify_command() {
    local command="$1"

    _RISK_CMD_LEVEL="LOW"
    _RISK_CMD_CATEGORY="read-only"

    case "$command" in
        # Kill-chain commands — always CRITICAL regardless of target
        pfsense|pf)
            _RISK_CMD_LEVEL="CRITICAL"
            _RISK_CMD_CATEGORY="firewall"
            ;;
        vpn|wireguard|wg)
            _RISK_CMD_LEVEL="CRITICAL"
            _RISK_CMD_CATEGORY="vpn"
            ;;

        # Credential operations — HIGH
        creds|creds-rotate|passwd|rotate|new-user)
            _RISK_CMD_LEVEL="HIGH"
            _RISK_CMD_CATEGORY="credential"
            ;;

        # Destructive operations — HIGH
        destroy|remove|delete|purge)
            _RISK_CMD_LEVEL="HIGH"
            _RISK_CMD_CATEGORY="destructive"
            ;;

        # Data recovery — HIGH
        restore|backup-restore)
            _RISK_CMD_LEVEL="HIGH"
            _RISK_CMD_CATEGORY="restore"
            ;;

        # Migration / resize — MEDIUM
        migrate|resize|change-id)
            _RISK_CMD_LEVEL="MEDIUM"
            _RISK_CMD_CATEGORY="vm-lifecycle"
            ;;

        # Config changes — MEDIUM
        harden|configure|fix|setup|onboard|init|provision)
            _RISK_CMD_LEVEL="MEDIUM"
            _RISK_CMD_CATEGORY="config-change"
            ;;

        # Snapshot / backup creation — MEDIUM (safe but writes state)
        snapshot|backup|clone|create|vmconfig)
            _RISK_CMD_LEVEL="MEDIUM"
            _RISK_CMD_CATEGORY="state-write"
            ;;

        # ZFS / storage operations — MEDIUM to HIGH based on sub-command
        zfs|truenas|mounts)
            _RISK_CMD_LEVEL="MEDIUM"
            _RISK_CMD_CATEGORY="storage"
            ;;

        # Switch config — HIGH (can break VLANs)
        switch)
            _RISK_CMD_LEVEL="HIGH"
            _RISK_CMD_CATEGORY="network"
            ;;

        # Everything else — read-only / safe
        *)
            _RISK_CMD_LEVEL="LOW"
            _RISK_CMD_CATEGORY="read-only"
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# RISK ASSESSMENT ENGINE — combine command + target into final risk
# ═══════════════════════════════════════════════════════════════════

# Risk level numeric values for comparison
_risk_to_num() {
    case "$1" in
        LOW)      echo 0 ;;
        MEDIUM)   echo 1 ;;
        HIGH)     echo 2 ;;
        CRITICAL) echo 3 ;;
        *)        echo 0 ;;
    esac
}

_risk_from_num() {
    case "$1" in
        0) echo "LOW" ;;
        1) echo "MEDIUM" ;;
        2) echo "HIGH" ;;
        3) echo "CRITICAL" ;;
        *) echo "LOW" ;;
    esac
}

_risk_assess() {
    local command="$1" target="${2:-}"
    local warnings=()
    local final_level="LOW"
    local blast_radius=""
    local killchain_link=""

    # --- Classify command ---
    _risk_classify_command "$command"
    local cmd_level="$_RISK_CMD_LEVEL"
    local cmd_category="$_RISK_CMD_CATEGORY"

    # --- Classify target ---
    if [ -n "$target" ]; then
        _risk_classify_target "$target"
    else
        _RISK_TARGET_CLASS="standard"
        _RISK_TARGET_LABEL="(no target)"
        _RISK_TARGET_DESC=""
    fi
    local tgt_class="$_RISK_TARGET_CLASS"
    local tgt_label="$_RISK_TARGET_LABEL"
    local tgt_desc="$_RISK_TARGET_DESC"

    # --- Determine final risk level (highest of command + target) ---
    local cmd_num; cmd_num=$(_risk_to_num "$cmd_level")
    local tgt_num=0
    case "$tgt_class" in
        killchain) tgt_num=3 ;;
        critical)  tgt_num=2 ;;
        standard)  tgt_num=0 ;;
    esac
    local max_num=$cmd_num
    [ "$tgt_num" -gt "$max_num" ] && max_num=$tgt_num
    final_level=$(_risk_from_num "$max_num")

    # --- Build warnings based on command category ---
    case "$cmd_category" in
        firewall)
            warnings+=("KILL-CHAIN: This command touches pfSense ${_DASH} the WireGuard gateway")
            warnings+=("If pfSense breaks, ALL remote management access is lost")
            warnings+=("Recovery requires physical datacenter access")
            killchain_link="pfSense"
            ;;
        vpn)
            warnings+=("KILL-CHAIN: This command touches the WireGuard VPN tunnel")
            warnings+=("If the tunnel drops, remote access is severed immediately")
            warnings+=("pfSense remains up but unreachable from outside")
            killchain_link="WireGuard"
            ;;
        credential)
            warnings+=("CREDENTIAL: Changes authentication material")
            warnings+=("Failure mid-rotation = partial fleet with wrong credentials")
            warnings+=("Pattern: atomic ${_DASH} one host at a time with verify-before-next")
            ;;
        destructive)
            warnings+=("DESTRUCTIVE: Permanently removes data or resources")
            warnings+=("No automatic undo ${_DASH} manual recovery only")
            ;;
        restore)
            warnings+=("RESTORE: Overwrites current state with backup data")
            warnings+=("Current configuration will be replaced")
            ;;
        vm-lifecycle)
            warnings+=("VM OPERATION: Migration or resize can fail mid-operation")
            warnings+=("Snapshot taken automatically before proceeding")
            ;;
        config-change)
            warnings+=("CONFIG CHANGE: Modifies host configuration")
            warnings+=("SSH/network config changes can lock you out of the host")
            ;;
        network)
            warnings+=("NETWORK: Modifies switch or VLAN configuration")
            warnings+=("Trunk port changes affect every VLAN simultaneously")
            ;;
        storage)
            warnings+=("STORAGE: Touches ZFS pools or mount configuration")
            warnings+=("Pool operations on live data require caution")
            ;;
        state-write)
            warnings+=("STATE WRITE: Creates or modifies VM/backup state")
            ;;
    esac

    # --- Add target-specific warnings ---
    case "$tgt_class" in
        killchain)
            warnings+=("TARGET: ${tgt_label} ${_DASH} ${tgt_desc}")
            if [ -z "$killchain_link" ]; then
                killchain_link="pfSense"
            fi
            ;;
        critical)
            warnings+=("TARGET: ${tgt_label} ${_DASH} ${tgt_desc}")
            ;;
    esac

    # --- Blast radius description ---
    case "$final_level" in
        CRITICAL)
            blast_radius="TOTAL MANAGEMENT LOCKOUT. Physical datacenter access required for recovery."
            ;;
        HIGH)
            blast_radius="Service degradation or partial fleet access loss. Manual intervention needed."
            ;;
        MEDIUM)
            blast_radius="Single host impact. Rollback available via snapshot or config backup."
            ;;
        LOW)
            blast_radius="Minimal impact. Read-only operation."
            ;;
    esac

    # --- Log the assessment ---
    log "risk-assess: level=$final_level command=$command target=${target:-none} category=$cmd_category target_class=$tgt_class"

    # --- Skip display for LOW risk with no warnings ---
    if [ "$final_level" = "LOW" ] && [ ${#warnings[@]} -eq 0 ]; then
        return 0
    fi

    # --- Display the assessment ---
    _risk_display "$final_level" "$command" "$target" "$blast_radius" "$killchain_link" "${warnings[@]}"

    # --- Gate: require confirmation for HIGH/CRITICAL ---
    if [ "$final_level" = "CRITICAL" ]; then
        _freq_confirm "Proceed with CRITICAL risk operation?" --danger || {
            log "risk-gate: ABORTED level=$final_level command=$command target=${target:-none}"
            return 1
        }
    elif [ "$final_level" = "HIGH" ]; then
        _freq_confirm "Proceed with HIGH risk operation?" || {
            log "risk-gate: ABORTED level=$final_level command=$command target=${target:-none}"
            return 1
        }
    fi

    return 0
}

# ═══════════════════════════════════════════════════════════════════
# RISK DISPLAY — bordered, color-coded, authoritative
# ═══════════════════════════════════════════════════════════════════

_risk_level_color() {
    case "$1" in
        CRITICAL) printf '%b' "$RED" ;;
        HIGH)     printf '%b' "$ORANGE" ;;
        MEDIUM)   printf '%b' "$YELLOW" ;;
        LOW)      printf '%b' "$GREEN" ;;
        *)        printf '%b' "$DIM" ;;
    esac
}

_risk_level_icon() {
    case "$1" in
        CRITICAL) printf '%b' "${_ICO_SKULL}" ;;
        HIGH)     printf '%b' "${_ICO_ZAP}" ;;
        MEDIUM)   printf '%b' "${_ICO_WARN}" ;;
        LOW)      printf '%b' "${_ICO_INFO}" ;;
        *)        printf '%b' "${_DOT}" ;;
    esac
}

_risk_display() {
    local level="$1" command="$2" target="$3" blast="$4" kc_link="$5"
    shift 5
    local warnings=("$@")

    local color; color=$(_risk_level_color "$level")
    local icon; icon=$(_risk_level_icon "$level")

    echo ""
    freq_header "RISK ASSESSMENT"
    freq_blank

    # Risk level badge — big and obvious
    freq_line "  ${color}${icon}  Risk Level: ${BOLD}${level}${RESET}${color}${RESET}"
    freq_line "  ${DIM}Command: ${RESET}${BOLD}${command}${RESET}${DIM}  Target: ${RESET}${BOLD}${target:-all}${RESET}"
    freq_blank

    # Warnings
    if [ ${#warnings[@]} -gt 0 ]; then
        freq_divider "${BOLD}${WHITE}Warnings${RESET}"
        local w
        for w in "${warnings[@]}"; do
            freq_line "  ${color}${_ARROW}${RESET} ${w}"
        done
        freq_blank
    fi

    # Blast radius
    freq_divider "${BOLD}${WHITE}Blast Radius${RESET}"
    freq_line "  ${color}${blast}${RESET}"
    freq_blank

    # Kill-chain visualization (only for CRITICAL or when a link is involved)
    if [ -n "$kc_link" ]; then
        _risk_killchain_display "$kc_link"
    fi

    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# KILL-CHAIN VISUALIZATION
# -- shows the full path from operator to target --
# -- highlights the vulnerable link in red --
# ═══════════════════════════════════════════════════════════════════

_risk_killchain_display() {
    local vulnerable_link="$1"

    freq_divider "${BOLD}${RED}Kill-Chain Analysis${RESET}"
    freq_blank
    freq_line "  ${DIM}Remote management path to datacenter:${RESET}"
    freq_blank

    # Build the chain visualization
    local i hop_count=${#_KC_HOPS[@]}
    for ((i=0; i<hop_count; i++)); do
        local hop="${_KC_HOPS[$i]}"
        local desc="${_KC_DESC[$i]}"
        local is_vulnerable=false

        # Check if this hop matches the vulnerable link
        case "$vulnerable_link" in
            WireGuard)  [ "$hop" = "WireGuard" ] && is_vulnerable=true ;;
            pfSense)    [ "$hop" = "pfSense" ]   && is_vulnerable=true ;;
            "VLAN 2550") [ "$hop" = "VLAN 2550" ] && is_vulnerable=true ;;
            *)          [ "$hop" = "$vulnerable_link" ] && is_vulnerable=true ;;
        esac

        if $is_vulnerable; then
            # Vulnerable link — highlighted in red with marker
            freq_line "  ${RED}${BOLD}${_TRI_R} [ ${hop} ] ${_ARROW} VULNERABLE LINK${RESET}"
            freq_line "    ${RED}${desc}${RESET}"
            freq_line "    ${RED}${_ICO_SKULL}  If this breaks: severed from datacenter${RESET}"
        else
            # Normal link
            freq_line "  ${DIM}${_CIRCLE} [ ${hop} ]${RESET}"
            freq_line "    ${DIM}${desc}${RESET}"
        fi

        # Draw connector between hops (not after last)
        if [ $((i + 1)) -lt "$hop_count" ]; then
            local next_hop="${_KC_HOPS[$((i+1))]}"
            local next_vuln=false
            case "$vulnerable_link" in
                WireGuard)  [ "$next_hop" = "WireGuard" ] && next_vuln=true ;;
                pfSense)    [ "$next_hop" = "pfSense" ]   && next_vuln=true ;;
                *)          [ "$next_hop" = "$vulnerable_link" ] && next_vuln=true ;;
            esac
            if $is_vulnerable || $next_vuln; then
                freq_line "  ${RED}${_B_V}${RESET}"
            else
                freq_line "  ${DIM}${_B_V}${RESET}"
            fi
        fi
    done

    freq_blank
    freq_line "  ${RED}${BOLD}${_ICO_WARN}  Recovery: Physical access to DC01 rack${RESET}"
    freq_blank
}

# ═══════════════════════════════════════════════════════════════════
# RISK GATE — Integration hook for the dispatcher
# Called before every write command. Read-only commands skip.
# Returns: 0 = proceed, 1 = abort
# ═══════════════════════════════════════════════════════════════════

_risk_gate() {
    local command="$1"
    shift
    local target="${1:-}"

    # DRY_RUN always passes — we show what WOULD happen
    if [ "$DRY_RUN" = "true" ]; then
        _risk_classify_command "$command"
        if [ "$_RISK_CMD_LEVEL" != "LOW" ]; then
            echo -e "  ${CYAN}[DRY-RUN]${RESET} Risk assessment: ${_RISK_CMD_LEVEL} (${_RISK_CMD_CATEGORY})"
        fi
        return 0
    fi

    # Check if command is read-only — skip assessment
    local ro_cmd
    for ro_cmd in $_RISK_READONLY; do
        [ "$command" = "$ro_cmd" ] && return 0
    done

    # Sub-commands that are read-only despite parent being write-capable
    # e.g., "pfsense status" is safe even though "pfsense" is CRITICAL
    local subcmd="${1:-}"
    case "$command" in
        pfsense|pf)
            case "$subcmd" in
                status|info|interfaces|rules|aliases|dhcp|gateways|dns|arp|states|version|"")
                    return 0 ;;
            esac
            ;;
        vpn|wireguard|wg)
            case "$subcmd" in
                status|peers|show|"")
                    return 0 ;;
            esac
            ;;
        truenas|nas)
            case "$subcmd" in
                status|info|pools|datasets|snapshots|shares|alerts|services|version|"")
                    return 0 ;;
            esac
            ;;
        switch|sw)
            case "$subcmd" in
                status|info|vlans|interfaces|mac-table|cdp|show|"")
                    return 0 ;;
            esac
            ;;
        zfs)
            case "$subcmd" in
                status|list|health|"")
                    return 0 ;;
            esac
            ;;
        vm|vm-overview)
            case "$subcmd" in
                list|status|info|show|"")
                    return 0 ;;
            esac
            ;;
        backup)
            case "$subcmd" in
                list|show|"")
                    return 0 ;;
            esac
            ;;
    esac

    # Full risk assessment with display and gating
    _risk_assess "$command" "$target"
    return $?
}

# ═══════════════════════════════════════════════════════════════════
# cmd_risk — User-facing: `freq risk <target>`
# Shows the risk profile of any host without executing anything
# ═══════════════════════════════════════════════════════════════════

cmd_risk() {
    local target="${1:-}"

    if [ -z "$target" ]; then
        # Show risk overview of all critical infrastructure
        _risk_overview
        return 0
    fi

    # Classify the target
    _risk_classify_target "$target"

    local color; color=$(_risk_level_color "$(
        case "$_RISK_TARGET_CLASS" in
            killchain) echo "CRITICAL" ;;
            critical)  echo "HIGH" ;;
            *)         echo "LOW" ;;
        esac
    )")

    local level_label
    case "$_RISK_TARGET_CLASS" in
        killchain) level_label="CRITICAL" ;;
        critical)  level_label="HIGH" ;;
        standard)  level_label="STANDARD" ;;
    esac

    local icon; icon=$(_risk_level_icon "$level_label")

    freq_header "RISK PROFILE"
    freq_blank
    freq_line "  ${BOLD}${WHITE}${_RISK_TARGET_LABEL}${RESET}"
    freq_line "  ${DIM}${_RISK_TARGET_DESC}${RESET}"
    freq_blank

    freq_divider "${BOLD}${WHITE}Classification${RESET}"
    freq_line "  ${color}${icon}  Infrastructure Tier: ${BOLD}${level_label}${RESET}"
    freq_blank

    # What operations are gated
    freq_divider "${BOLD}${WHITE}Operation Gates${RESET}"
    case "$_RISK_TARGET_CLASS" in
        killchain)
            freq_line "  ${GREEN}${_TICK}${RESET} Read-only commands (status, info)     ${_ARROW} ${GREEN}No gate${RESET}"
            freq_line "  ${YELLOW}${_WARN}${RESET} Config changes (harden, configure)   ${_ARROW} ${RED}CRITICAL gate${RESET}"
            freq_line "  ${RED}${_CROSS}${RESET} Write operations (any state change)  ${_ARROW} ${RED}CRITICAL gate${RESET}"
            freq_line "  ${RED}${_ICO_SKULL}${RESET} Destructive operations               ${_ARROW} ${RED}CRITICAL + type 'yes'${RESET}"
            ;;
        critical)
            freq_line "  ${GREEN}${_TICK}${RESET} Read-only commands (status, info)     ${_ARROW} ${GREEN}No gate${RESET}"
            freq_line "  ${YELLOW}${_WARN}${RESET} Config changes (harden, configure)   ${_ARROW} ${YELLOW}HIGH gate${RESET}"
            freq_line "  ${RED}${_CROSS}${RESET} Destructive operations               ${_ARROW} ${RED}HIGH + confirm${RESET}"
            ;;
        *)
            freq_line "  ${GREEN}${_TICK}${RESET} Read-only commands                    ${_ARROW} ${GREEN}No gate${RESET}"
            freq_line "  ${YELLOW}${_WARN}${RESET} Config changes                       ${_ARROW} ${YELLOW}MEDIUM gate${RESET}"
            freq_line "  ${RED}${_CROSS}${RESET} Destructive operations               ${_ARROW} ${ORANGE}HIGH + confirm${RESET}"
            ;;
    esac
    freq_blank

    # Kill-chain position
    if [ "$_RISK_TARGET_CLASS" = "killchain" ]; then
        _risk_killchain_display "pfSense"
    elif [ "$_RISK_TARGET_CLASS" = "critical" ]; then
        freq_divider "${BOLD}${WHITE}Kill-Chain Impact${RESET}"
        freq_line "  ${DIM}This host is not in the kill-chain, but loss would degrade operations.${RESET}"
        freq_blank
        case "$_RISK_TARGET_LABEL" in
            TrueNAS*)
                freq_line "  ${ORANGE}${_ARROW}${RESET} Loss of TrueNAS = loss of all NFS/SMB shares"
                freq_line "  ${ORANGE}${_ARROW}${RESET} ISO storage, VM backups, Obsidian vault go offline"
                freq_line "  ${ORANGE}${_ARROW}${RESET} Running VMs survive but cannot access shared storage"
                ;;
            pve0*)
                freq_line "  ${ORANGE}${_ARROW}${RESET} Loss of PVE node = VMs on that node go down"
                freq_line "  ${ORANGE}${_ARROW}${RESET} Other nodes remain operational"
                freq_line "  ${ORANGE}${_ARROW}${RESET} Migration possible if node is still in cluster"
                ;;
            *switch*|*Cisco*)
                freq_line "  ${ORANGE}${_ARROW}${RESET} Loss of switch = all VLANs lose connectivity"
                freq_line "  ${ORANGE}${_ARROW}${RESET} Management VLAN included ${_DASH} partial lockout"
                freq_line "  ${ORANGE}${_ARROW}${RESET} iDRAC/IPMI may remain on dedicated ports"
                ;;
            *)
                freq_line "  ${ORANGE}${_ARROW}${RESET} Loss of this host degrades fleet operations"
                ;;
        esac
        freq_blank
    fi

    # Resolver info if available
    if type freq_resolve &>/dev/null; then
        local resolved
        resolved=$(freq_resolve "$target" 2>/dev/null)
        if [ -n "$resolved" ]; then
            local r_ip r_type r_label
            read -r r_ip r_type r_label <<< "$resolved"
            freq_divider "${BOLD}${WHITE}Resolution${RESET}"
            freq_line "  ${DIM}IP:${RESET}    ${r_ip}"
            freq_line "  ${DIM}Type:${RESET}  ${r_type}"
            freq_line "  ${DIM}Label:${RESET} ${r_label}"
            freq_blank
        fi
    fi

    freq_footer
    log "risk-profile: target=$target class=$_RISK_TARGET_CLASS"
}

# ═══════════════════════════════════════════════════════════════════
# RISK OVERVIEW — Show all critical infrastructure at a glance
# ═══════════════════════════════════════════════════════════════════

_risk_overview() {
    freq_header "INFRASTRUCTURE RISK MAP"
    freq_blank
    freq_line "  ${BOLD}${WHITE}DC01 Critical Infrastructure${RESET}"
    freq_blank

    freq_divider "${RED}${BOLD}CRITICAL ${_DASH} Kill-Chain${RESET}"
    freq_line "  ${RED}${_ICO_SKULL}${RESET}  ${BOLD}pfSense${RESET}        ${DIM}Firewall + VPN endpoint + gateway${RESET}"
    freq_line "     ${DIM}Aliases: pfsense, fw, firewall${RESET}"
    freq_line "     ${RED}Loss = total remote management lockout${RESET}"
    freq_blank

    freq_divider "${ORANGE}${BOLD}HIGH ${_DASH} Critical Infrastructure${RESET}"
    freq_line "  ${ORANGE}${_ICO_ZAP}${RESET}  ${BOLD}TrueNAS${RESET}        ${DIM}28TB storage backbone (ZFS)${RESET}"
    freq_line "     ${DIM}Aliases: truenas, nas, tn${RESET}"
    freq_blank
    freq_line "  ${ORANGE}${_ICO_ZAP}${RESET}  ${BOLD}PVE Nodes${RESET}      ${DIM}Proxmox hypervisors (pve01-03)${RESET}"
    freq_line "     ${DIM}3-node cluster hosting all VMs${RESET}"
    freq_blank
    freq_line "  ${ORANGE}${_ICO_ZAP}${RESET}  ${BOLD}Cisco Switch${RESET}   ${DIM}All VLAN trunking${RESET}"
    freq_line "     ${DIM}Aliases: switch, sw${RESET}"
    freq_blank

    freq_divider "${BOLD}${WHITE}Kill-Chain Path${RESET}"
    freq_blank

    # Compact chain visualization
    local chain_line=""
    local i
    for ((i=0; i<${#_KC_HOPS[@]}; i++)); do
        if [ $i -gt 0 ]; then
            chain_line+=" ${_ARROW} "
        fi
        local hop="${_KC_HOPS[$i]}"
        case "$hop" in
            pfSense|WireGuard)
                chain_line+="${RED}${BOLD}${hop}${RESET}"
                ;;
            *)
                chain_line+="${DIM}${hop}${RESET}"
                ;;
        esac
    done
    freq_line "  ${chain_line}"
    freq_blank
    freq_line "  ${DIM}Use ${RESET}${PURPLELIGHT}freq risk <host>${RESET}${DIM} for detailed risk profile of any target.${RESET}"
    freq_blank
    freq_footer
}
