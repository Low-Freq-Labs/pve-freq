#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/switch.sh
# Network Switch Management (Cisco IOS)
#
# Author:  FREQ Project / LOW FREQ Labs
#
# Cisco Catalyst switch management via SSH (IOS 15.2)
# Status, VLANs, ports, trunks, LACP, MAC table, CDP, SVI,
# health check, security audit, backup, users
#
# [HIDDEN-6/7] diffie-hellman-group14-sha1. deprecated. technically weak.
# but the switch is a Catalyst 4948E-F running IOS 15.2 from a different era.
# it doesn't know it's old. it just works.
# respect the OGs. even in networking.
#
# Commands: cmd_switch
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════

# Resolve switch host — uses freq_resolve for hosts.conf, falls back to default
# Sets: _SW_IP, _SW_NAME
_switch_resolve() {
    local host="${1:-switch01}"
    local resolved
    resolved=$(freq_resolve "$host" 2>/dev/null)
    if [ -n "$resolved" ]; then
        _SW_IP=$(echo "$resolved" | awk '{print $1}')
        local rtype
        rtype=$(echo "$resolved" | awk '{print $2}')
        _SW_NAME=$(echo "$resolved" | awk '{print $3}')
        # Validate host type if known
        if [ -n "$rtype" ] && [ "$rtype" != "switch" ]; then
            echo -e "  ${RED}$host is type '$rtype', not 'switch'${RESET}"
            return 1
        fi
    elif [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        _SW_IP="$host"
        _SW_NAME="$host"
    else
        echo -e "  ${RED}Cannot resolve host: $host${RESET}"
        return 1
    fi
    return 0
}

# SSH to switch — uses resolve label so freq_ssh detects type (switch → legacy crypto)
# Cisco IOS: one command per SSH session, terminal length 0 for full output
_switch_ssh() {
    freq_ssh "$_SW_NAME" "$@"
}

# ═══════════════════════════════════════════════════════════════════
# cmd_switch — Main entry point
# Usage: freq switch <subcommand> [host]
# ═══════════════════════════════════════════════════════════════════
cmd_switch() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)   _switch_resolve "${1:-switch01}" && _sw_status ;;
        vlans)    _switch_resolve "${1:-switch01}" && _sw_vlans ;;
        ports)    _switch_resolve "${1:-switch01}" && _sw_ports ;;
        trunks)   _switch_resolve "${1:-switch01}" && _sw_trunks ;;
        lacp)     _switch_resolve "${1:-switch01}" && _sw_lacp ;;
        mac)      _switch_resolve "${1:-switch01}" && _sw_mac ;;
        cdp)      _switch_resolve "${1:-switch01}" && _sw_cdp ;;
        svi)      _switch_resolve "${1:-switch01}" && _sw_svi ;;
        backup)   _switch_resolve "${1:-switch01}" && _sw_backup ;;
        users)    _switch_resolve "${1:-switch01}" && _sw_users ;;
        check)    _switch_resolve "${1:-switch01}" && _sw_check ;;
        audit)    _switch_resolve "${1:-switch01}" && _sw_audit ;;
        help|--help|-h) _sw_help ;;
        *)
            echo -e "  ${RED}Unknown subcommand: ${subcmd}${RESET}"
            _sw_help
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# _sw_help — Usage text
# ═══════════════════════════════════════════════════════════════════
_sw_help() {
    cat << 'EOF'
Usage: freq switch <subcommand> [host]

  freq switch status [host]    — version, uptime, ports, VLANs
  freq switch vlans [host]     — VLAN table
  freq switch ports [host]     — all port states (color-coded)
  freq switch trunks [host]    — trunk port config
  freq switch lacp [host]      — EtherChannel and LACP
  freq switch mac [host]       — MAC address table
  freq switch cdp [host]       — CDP neighbor details
  freq switch svi [host]       — VLAN interface IPs
  freq switch backup [host]    — save running-config (admin)
  freq switch users [host]     — configured users
  freq switch check [host]     — health check
  freq switch audit [host]     — security audit

  Default host: switch01

Examples:
  freq switch status               # default switch
  freq switch ports switch01       # port status
  freq switch audit 10.25.255.5    # audit by IP
EOF
}

# ═══════════════════════════════════════════════════════════════════
# STATUS — Version, uptime, connected ports, active VLANs
# ═══════════════════════════════════════════════════════════════════
_sw_status() {
    require_operator || return 1
    freq_header "Switch Status — $_SW_NAME ($_SW_IP)"

    local version
    version=$(_switch_ssh "show version")
    if [ -z "$version" ]; then
        echo -e "  ${RED}Cannot reach switch at $_SW_IP${RESET}"
        freq_footer
        return 1
    fi

    echo "$version" | grep -E "Cisco IOS|uptime|processor|bytes of memory" | sed 's/^/  /'
    echo ""

    local interfaces
    interfaces=$(_switch_ssh "show interfaces status")
    echo "  Interfaces (connected):"
    echo "$interfaces" | grep -E "connected|^Port" | head -25 | sed 's/^/    /'
    echo ""

    local vlans
    vlans=$(_switch_ssh "show vlan brief")
    echo "  VLANs active:"
    echo "$vlans" | grep "active" | sed 's/^/    /'

    freq_footer
    log "switch: status viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# VLANS — VLAN table
# ═══════════════════════════════════════════════════════════════════
_sw_vlans() {
    require_operator || return 1
    freq_header "Switch VLANs — $_SW_NAME"

    local vlans
    vlans=$(_switch_ssh "show vlan brief")
    if [ -z "$vlans" ]; then
        echo -e "  ${RED}Cannot reach switch${RESET}"
        freq_footer
        return 1
    fi

    echo "$vlans" | awk 'NR>2 && NF>=2 {
        if ($3=="active" || $2~/active/)
            printf "  VLAN %-6s %-25s %s\n", $1, $2, $3
    }'

    freq_footer
    log "switch: VLANs viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# PORTS — All port states (color-coded)
# ═══════════════════════════════════════════════════════════════════
_sw_ports() {
    require_operator || return 1
    freq_header "Switch Port Status — $_SW_NAME"

    local ports
    ports=$(_switch_ssh "show interfaces status")
    if [ -z "$ports" ]; then
        echo -e "  ${RED}Cannot reach switch${RESET}"
        freq_footer
        return 1
    fi

    echo "$ports" | while IFS= read -r line; do
        if echo "$line" | grep -q "connected"; then
            echo -e "  ${GREEN}${line}${RESET}"
        elif echo "$line" | grep -q "notconnect"; then
            echo -e "  ${RED}${line}${RESET}"
        elif echo "$line" | grep -q "err-disabled"; then
            echo -e "  ${BOLD}${RED}${line}${RESET}"
        else
            echo "  ${line}"
        fi
    done

    freq_footer
    log "switch: ports viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# TRUNKS — Trunk port config
# ═══════════════════════════════════════════════════════════════════
_sw_trunks() {
    require_operator || return 1
    freq_header "Switch Trunk Ports — $_SW_NAME"
    _switch_ssh "show interfaces trunk" | sed 's/^/  /'
    freq_footer
    log "switch: trunks viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# LACP — EtherChannel and LACP status
# ═══════════════════════════════════════════════════════════════════
_sw_lacp() {
    require_operator || return 1
    freq_header "Switch LACP / EtherChannel — $_SW_NAME"

    echo "  EtherChannel summary:"
    _switch_ssh "show etherchannel summary" | sed 's/^/    /'
    echo ""
    echo "  LACP neighbors:"
    _switch_ssh "show lacp neighbor" | sed 's/^/    /'

    freq_footer
    log "switch: LACP viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# MAC — MAC address table
# ═══════════════════════════════════════════════════════════════════
_sw_mac() {
    require_operator || return 1
    freq_header "Switch MAC Table — $_SW_NAME"

    _switch_ssh "show mac address-table" | \
        grep -v "^$\|^----\|^All" | head -40 | sed 's/^/  /'
    echo ""
    _switch_ssh "show mac address-table count" | sed 's/^/  /'

    freq_footer
    log "switch: MAC table viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# CDP — CDP neighbor details
# ═══════════════════════════════════════════════════════════════════
_sw_cdp() {
    require_operator || return 1
    freq_header "Switch CDP Neighbors — $_SW_NAME"

    _switch_ssh "show cdp neighbors detail" | \
        grep -E "Device ID|IP address|Platform|Interface" | sed 's/^/  /'

    freq_footer
    log "switch: CDP viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# SVI — VLAN interface IPs
# ═══════════════════════════════════════════════════════════════════
_sw_svi() {
    require_operator || return 1
    freq_header "Switch SVI (VLAN Interfaces) — $_SW_NAME"

    local running
    running=$(_switch_ssh "show running-config")
    echo "$running" | grep -A2 "^interface Vlan" | grep -v "^--$" | sed 's/^/  /'

    freq_footer
    log "switch: SVI viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# BACKUP — Save running-config
# ═══════════════════════════════════════════════════════════════════
_sw_backup() {
    require_admin || return 1

    if ! require_protected "switch config backup" "${PVE_NODES[0]}" \
        "Switch config operations touch network infrastructure" \
        "Physical console access to switch for recovery"; then
        return 1
    fi

    freq_action_modify "Backing up switch configuration..."

    local dry_run="${DRY_RUN:-false}"
    if [ "$dry_run" = "true" ]; then
        echo -e "  ${YELLOW}[DRY-RUN]${RESET} Would back up switch config from ${BOLD}$_SW_NAME${RESET}"
        unset PROTECTED_ROOT_PASS 2>/dev/null
        return 0
    fi

    local backup_dir="${FREQ_DATA_DIR}/backup/switch"
    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)
    local backup_file="${backup_dir}/${_SW_NAME}-${timestamp}.txt"

    mkdir -p "$backup_dir" 2>/dev/null

    local config
    config=$(_switch_ssh "show running-config")
    if [ -n "$config" ]; then
        echo "$config" > "$backup_file"
        local lines
        lines=$(echo "$config" | wc -l | tr -d ' ')
        echo -e "  ${GREEN}${_TICK}${RESET} Backup saved ($lines lines)"
        echo -e "  ${DIM}  → $backup_file${RESET}"
        log "switch: running-config backed up from $_SW_NAME → $backup_file"
    else
        echo -e "  ${RED}${_CROSS}${RESET} Backup failed — check connectivity"
        unset PROTECTED_ROOT_PASS 2>/dev/null
        return 1
    fi

    unset PROTECTED_ROOT_PASS 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# USERS — Configured users on switch
# ═══════════════════════════════════════════════════════════════════
_sw_users() {
    require_operator || return 1
    freq_header "Switch Users — $_SW_NAME"
    _switch_ssh "show running-config" | grep "^username" | sed 's/^/  /'
    freq_footer
    log "switch: users viewed ($_SW_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# CHECK — Health check (connectivity, uptime, err-disabled, STP, LACP, CDP, env)
# ═══════════════════════════════════════════════════════════════════
_sw_check() {
    require_operator || return 1
    freq_header "Switch Health Check — $_SW_NAME"
    local pass=0 warn=0 fail=0

    # Connectivity + version
    local version
    version=$(_switch_ssh "show version")
    if echo "$version" | grep -q "Cisco IOS"; then
        echo -e "  ${GREEN}${_TICK}${RESET} Reachable and responding"
        pass=$((pass + 1))

        local uptime_str
        uptime_str=$(echo "$version" | grep "uptime" | sed 's/.*uptime is //')
        echo -e "  ${GREEN}${_TICK}${RESET} Uptime: $uptime_str"
        pass=$((pass + 1))
    else
        echo -e "  ${RED}${_CROSS}${RESET} Cannot reach switch at $_SW_IP"
        freq_footer
        return 1
    fi

    # err-disabled ports
    local errdis
    errdis=$(_switch_ssh "show interfaces status err-disabled" | \
        grep -cv "^$\|^Port\|^----" 2>/dev/null)
    if [ "${errdis:-0}" -eq 0 ]; then
        echo -e "  ${GREEN}${_TICK}${RESET} No err-disabled ports"
        pass=$((pass + 1))
    else
        echo -e "  ${RED}${_CROSS}${RESET} $errdis err-disabled port(s)"
        fail=$((fail + 1))
    fi

    # Spanning-tree
    local stp_root
    stp_root=$(_switch_ssh "show spanning-tree root" | grep -c "Root")
    echo -e "  ${GREEN}${_TICK}${RESET} STP active ($stp_root root bridge entries)"
    pass=$((pass + 1))

    # EtherChannel
    local po_summary
    po_summary=$(_switch_ssh "show etherchannel summary")
    local po_up po_down
    po_up=$(echo "$po_summary" | grep -c "RU\|SU")
    po_down=$(echo "$po_summary" | grep -c "SD\|D ")
    if [ "${po_down:-0}" -eq 0 ]; then
        echo -e "  ${GREEN}${_TICK}${RESET} All port-channels healthy ($po_up up)"
        pass=$((pass + 1))
    else
        echo -e "  ${YELLOW}${_WARN}${RESET} $po_down port-channel(s) degraded"
        warn=$((warn + 1))
    fi

    # CDP neighbors
    local cdp_count
    cdp_count=$(_switch_ssh "show cdp neighbors" | \
        grep -c "Gig\|Ten\|Fas" 2>/dev/null)
    echo -e "  ${GREEN}${_TICK}${RESET} CDP neighbors: $cdp_count device(s) visible"
    pass=$((pass + 1))

    # Environment (power/temp if available)
    local env
    env=$(_switch_ssh "show environment all" 2>/dev/null)
    if [ -n "$env" ]; then
        local ps_ok ps_bad
        ps_ok=$(echo "$env" | grep -c "good\|OK\|Normal")
        ps_bad=$(echo "$env" | grep -ci "fail\|critical\|not present")
        if [ "${ps_bad:-0}" -eq 0 ]; then
            echo -e "  ${GREEN}${_TICK}${RESET} Environment OK ($ps_ok sensors normal)"
            pass=$((pass + 1))
        else
            echo -e "  ${YELLOW}${_WARN}${RESET} Environment: $ps_bad sensor(s) abnormal"
            warn=$((warn + 1))
        fi
    fi

    echo ""
    echo -e "  Pass: ${GREEN}$pass${RESET}  Warn: ${YELLOW}$warn${RESET}  Fail: ${RED}$fail${RESET}"
    freq_footer
    log "switch: health check ($_SW_NAME, pass=$pass warn=$warn fail=$fail)"
}

# ═══════════════════════════════════════════════════════════════════
# AUDIT — Security audit (SSH v2, telnet, encryption, NTP, logging, VTP, etc.)
# ═══════════════════════════════════════════════════════════════════
_sw_audit() {
    require_operator || return 1
    freq_header "Switch Security Audit — $_SW_NAME"

    local running
    running=$(_switch_ssh "show running-config")
    if [ -z "$running" ]; then
        echo -e "  ${RED}Cannot retrieve running-config${RESET}"
        freq_footer
        return 1
    fi

    local pass=0 warn=0 fail=0

    # SSH version 2
    if echo "$running" | grep -q "ip ssh version 2"; then
        echo -e "  ${GREEN}${_TICK}${RESET} SSH v2 enforced"
        pass=$((pass + 1))
    else
        echo -e "  ${RED}${_CROSS}${RESET} SSH v2 not enforced"
        fail=$((fail + 1))
    fi

    # No telnet
    if echo "$running" | grep -q "transport input ssh"; then
        echo -e "  ${GREEN}${_TICK}${RESET} Telnet disabled (SSH only on VTY)"
        pass=$((pass + 1))
    else
        echo -e "  ${YELLOW}${_WARN}${RESET} Telnet may be enabled"
        warn=$((warn + 1))
    fi

    # Password encryption
    if echo "$running" | grep -q "service password-encryption"; then
        echo -e "  ${GREEN}${_TICK}${RESET} Password encryption enabled"
        pass=$((pass + 1))
    else
        echo -e "  ${RED}${_CROSS}${RESET} Password encryption NOT enabled"
        fail=$((fail + 1))
    fi

    # NTP
    local ntp_line
    ntp_line=$(echo "$running" | grep "ntp server" | head -1)
    if [ -n "$ntp_line" ]; then
        echo -e "  ${GREEN}${_TICK}${RESET} NTP: $ntp_line"
        pass=$((pass + 1))
    else
        echo -e "  ${YELLOW}${_WARN}${RESET} No NTP configured"
        warn=$((warn + 1))
    fi

    # Logging
    if echo "$running" | grep -q "^logging"; then
        echo -e "  ${GREEN}${_TICK}${RESET} Logging configured"
        pass=$((pass + 1))
    else
        echo -e "  ${YELLOW}${_WARN}${RESET} No syslog logging configured"
        warn=$((warn + 1))
    fi

    # errdisable recovery
    if echo "$running" | grep -q "errdisable recovery"; then
        echo -e "  ${GREEN}${_TICK}${RESET} Err-disable recovery enabled"
        pass=$((pass + 1))
    else
        echo -e "  ${YELLOW}${_WARN}${RESET} Err-disable recovery not configured"
        warn=$((warn + 1))
    fi

    # Priv 15 users
    local priv15
    priv15=$(echo "$running" | grep -c "username.*privilege 15")
    echo -e "  ${YELLOW}${_WARN}${RESET} $priv15 users with privilege 15 (all admin)"
    warn=$((warn + 1))

    # VTP mode
    if echo "$running" | grep -q "vtp mode off\|vtp mode transparent"; then
        echo -e "  ${GREEN}${_TICK}${RESET} VTP disabled/transparent (no VLAN propagation risk)"
        pass=$((pass + 1))
    else
        echo -e "  ${YELLOW}${_WARN}${RESET} VTP may be in server/client mode"
        warn=$((warn + 1))
    fi

    # MTU consistency (jumbo frames)
    local mtu_count
    mtu_count=$(echo "$running" | grep -c "mtu 9198")
    echo -e "  ${GREEN}${_TICK}${RESET} Jumbo frames: $mtu_count interfaces at MTU 9198"
    pass=$((pass + 1))

    echo ""
    echo -e "  Pass: ${GREEN}$pass${RESET}  Warn: ${YELLOW}$warn${RESET}  Fail: ${RED}$fail${RESET}"
    freq_footer
    log "switch: security audit ($_SW_NAME, pass=$pass warn=$warn fail=$fail)"
}
