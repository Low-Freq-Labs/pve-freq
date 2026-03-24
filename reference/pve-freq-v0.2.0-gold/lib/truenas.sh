#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/truenas.sh
# TrueNAS Management (SSH-based)
#
# Author:  FREQ Project / JARVIS
#
# ZFS pools, shares, alerts, snapshots, disks, NFS, users, backup, health check
# Uses SSH + midclt/zfs/zpool — no HTTP API dependency
#
# Commands: cmd_truenas
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# TARGET RESOLUTION
# ═══════════════════════════════════════════════════════════════════

# _tn_resolve_target <prod|lab|IP>
# Sets: _TN_IP, _TN_NAME, _TN_RESOLVE (resolve-friendly label for freq_ssh)
_tn_resolve_target() {
    local target="${1:-prod}"
    local resolved=""

    case "$target" in
        prod|production)
            resolved=$(freq_resolve "truenas" 2>/dev/null)
            _TN_RESOLVE="truenas"
            ;;
        lab|test)
            resolved=$(freq_resolve "truenas-lab" 2>/dev/null)
            _TN_RESOLVE="truenas-lab"
            ;;
        *)
            # Try as alias or IP
            resolved=$(freq_resolve "$target" 2>/dev/null)
            if [ -n "$resolved" ]; then
                local rtype
                rtype=$(echo "$resolved" | awk '{print $2}')
                if [ "$rtype" != "truenas" ]; then
                    echo -e "      ${YELLOW}${_WARN}${RESET}  $target resolves as type '$rtype', not truenas"
                fi
                _TN_RESOLVE=$(echo "$resolved" | awk '{print $3}')
            else
                _TN_RESOLVE="$target"
            fi
            ;;
    esac

    if [ -n "$resolved" ]; then
        _TN_IP=$(echo "$resolved" | awk '{print $1}')
        _TN_NAME=$(echo "$resolved" | awk '{print $3}')
    else
        _TN_IP="${TRUENAS_IP:-10.25.255.25}"
        _TN_NAME="truenas"
        _TN_RESOLVE="truenas"
    fi
}

# _tn_ssh <command>
# SSH to TrueNAS using resolve label (ensures correct host type detection)
_tn_ssh() {
    freq_ssh "$_TN_RESOLVE" "$*"
}

# ═══════════════════════════════════════════════════════════════════
# COMMAND DISPATCHER
# ═══════════════════════════════════════════════════════════════════

cmd_truenas() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    # Parse --target flag
    local target="prod"
    local cmd_args=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --target) target="${2:-prod}"; shift 2 ;;
            *)        cmd_args+=("$1"); shift ;;
        esac
    done
    _tn_resolve_target "$target"

    local dry_run="${DRY_RUN:-false}"

    case "$subcmd" in
        status)     _tn_status ;;
        pools)      _tn_pools ;;
        shares)     _tn_shares ;;
        alerts)     _tn_alerts ;;
        disks)      _tn_disks ;;
        snap)       _tn_snap "${cmd_args[@]}" ;;
        nfs)        _tn_nfs ;;
        smb)        _tn_smb ;;
        users)      _tn_users ;;
        services)   _tn_services ;;
        backup)     _tn_backup ;;
        check)      _tn_check ;;
        scrub)      _tn_scrub ;;
        help|--help|-h)
            echo "Usage: freq truenas <command> [--target prod|lab|IP]"
            echo ""
            echo "  status       System info, pools, alerts overview"
            echo "  pools        ZFS pool status and usage"
            echo "  shares       SMB + NFS shares"
            echo "  alerts       Active system alerts"
            echo "  disks        Physical disk inventory"
            echo "  snap [list]  ZFS snapshots (last 20)"
            echo "  nfs          NFS exports and health"
            echo "  smb          SMB shares detail"
            echo "  users        Non-builtin user accounts"
            echo "  services     Running services"
            echo "  backup       Backup TrueNAS config (--dry-run)"
            echo "  check        Connectivity + health check"
            echo "  scrub        Trigger ZFS scrub (protected)"
            ;;
        *)
            echo -e "      ${RED}${_CROSS}${RESET}  Unknown subcommand: $subcmd"
            echo "      Run 'freq truenas help' for usage."
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# STATUS — Overview: version, uptime, pools, alerts
# ═══════════════════════════════════════════════════════════════════
_tn_status() {
    freq_header "TrueNAS Status ($_TN_NAME)"

    # Single SSH call: hostname, version, uptime, pool summary, alert count
    local output
    output=$(_tn_ssh "
        echo \"=== INFO ===\"
        hostname 2>/dev/null
        ver=\$(sudo midclt call system.version 2>/dev/null || cat /etc/version 2>/dev/null || echo 'unknown')
        echo \"\$ver\"
        uptime -p 2>/dev/null || echo 'uptime unknown'
        echo \"=== POOLS ===\"
        sudo zpool list -H -o name,size,alloc,free,cap,health 2>/dev/null
        echo \"=== ALERTS ===\"
        sudo midclt call alert.list 2>/dev/null | python3 -c \"
import sys, json
try:
    alerts = json.load(sys.stdin)
    crit = sum(1 for a in alerts if a.get('level') in ('CRITICAL','ERROR'))
    warn = sum(1 for a in alerts if a.get('level') == 'WARNING')
    info = sum(1 for a in alerts if a.get('level') not in ('CRITICAL','ERROR','WARNING'))
    print(f'{len(alerts)} total ({crit} critical, {warn} warning, {info} info)')
except:
    print('0 total')
\" 2>/dev/null
    " 2>/dev/null)

    if [ -z "$output" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot reach TrueNAS at $_TN_IP"
        freq_footer
        return 1
    fi

    # Parse sections
    local section=""
    local hostname="" version="" uptime_str="" alert_summary=""
    local -a pool_lines=()
    local info_line=0

    while IFS= read -r line; do
        case "$line" in
            "=== INFO ===")  section="info"; info_line=0; continue ;;
            "=== POOLS ===") section="pools"; continue ;;
            "=== ALERTS ===") section="alerts"; continue ;;
        esac
        case "$section" in
            info)
                info_line=$((info_line + 1))
                case $info_line in
                    1) hostname="$line" ;;
                    2) version="$line" ;;
                    3) uptime_str="$line" ;;
                esac
                ;;
            pools)
                [ -n "$line" ] && pool_lines+=("$line")
                ;;
            alerts)
                [ -n "$line" ] && alert_summary="$line"
                ;;
        esac
    done <<< "$output"

    echo -e "      Hostname:  ${BOLD}${hostname:-unknown}${RESET}"
    echo -e "      Version:   ${version:-unknown}"
    echo -e "      Uptime:    ${uptime_str:-unknown}"
    echo ""

    # Pool summary
    echo -e "      ${BOLD}Pools:${RESET}"
    if [ ${#pool_lines[@]} -gt 0 ]; then
        for pline in "${pool_lines[@]}"; do
            local pname psize palloc pfree pcap phealth
            pname=$(echo "$pline" | awk '{print $1}')
            psize=$(echo "$pline" | awk '{print $2}')
            palloc=$(echo "$pline" | awk '{print $3}')
            pfree=$(echo "$pline" | awk '{print $4}')
            pcap=$(echo "$pline" | awk '{print $5}')
            phealth=$(echo "$pline" | awk '{print $6}')

            local color="${GREEN}"
            [ "$phealth" != "ONLINE" ] && color="${RED}"
            # Cap percentage warning
            local cap_num="${pcap%\%}"
            [ "${cap_num:-0}" -gt 80 ] 2>/dev/null && color="${YELLOW}"
            [ "${cap_num:-0}" -gt 90 ] 2>/dev/null && color="${RED}"

            echo -e "        ${color}${pname}: ${phealth} — ${palloc}/${psize} (${pcap} used, ${pfree} free)${RESET}"
        done
    else
        echo -e "        ${DIM}(no pools found)${RESET}"
    fi

    echo ""
    echo -e "      Alerts:    ${alert_summary:-0 total}"

    freq_footer
    log "truenas: status viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# POOLS — Detailed ZFS pool status
# ═══════════════════════════════════════════════════════════════════
_tn_pools() {
    freq_header "ZFS Pools ($_TN_NAME)"

    local output
    output=$(_tn_ssh "sudo zpool status 2>/dev/null" 2>/dev/null)

    if [ -z "$output" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve pool status"
        freq_footer
        return 1
    fi

    # Color-code pool health
    while IFS= read -r line; do
        if [[ "$line" == *"ONLINE"* ]]; then
            echo -e "      ${GREEN}${line}${RESET}"
        elif [[ "$line" == *"DEGRADED"* ]]; then
            echo -e "      ${YELLOW}${line}${RESET}"
        elif [[ "$line" == *"FAULTED"* ]] || [[ "$line" == *"UNAVAIL"* ]] || [[ "$line" == *"OFFLINE"* ]]; then
            echo -e "      ${RED}${line}${RESET}"
        elif [[ "$line" == *"errors:"* ]] && [[ "$line" != *"No known data errors"* ]]; then
            echo -e "      ${RED}${line}${RESET}"
        else
            echo "      $line"
        fi
    done <<< "$output"

    freq_footer
    log "truenas: pools viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# SHARES — SMB + NFS shares overview
# ═══════════════════════════════════════════════════════════════════
_tn_shares() {
    freq_header "TrueNAS Shares ($_TN_NAME)"

    local output
    output=$(_tn_ssh "
        echo '=== SMB ==='
        sudo midclt call sharing.smb.query 2>/dev/null | python3 -c \"
import sys, json
try:
    shares = json.load(sys.stdin)
    for s in shares:
        enabled = 'ON' if s.get('enabled') else 'OFF'
        print(f\\\"{enabled}|{s.get('name','?')}|{s.get('path','?')}\\\")
except:
    pass
\" 2>/dev/null
        echo '=== NFS ==='
        sudo midclt call sharing.nfs.query 2>/dev/null | python3 -c \"
import sys, json
try:
    exports = json.load(sys.stdin)
    for e in exports:
        enabled = 'ON' if e.get('enabled') else 'OFF'
        paths = ', '.join(e.get('paths', [e.get('path', '?')]))
        networks = ', '.join(e.get('networks', ['any']))
        print(f\\\"{enabled}|{paths}|{networks}\\\")
except:
    pass
\" 2>/dev/null
    " 2>/dev/null)

    if [ -z "$output" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve shares"
        freq_footer
        return 1
    fi

    local section=""
    echo -e "      ${BOLD}SMB Shares:${RESET}"
    local smb_count=0 nfs_count=0

    while IFS= read -r line; do
        case "$line" in
            "=== SMB ===") section="smb"; continue ;;
            "=== NFS ===")
                [ $smb_count -eq 0 ] && echo -e "        ${DIM}(none)${RESET}"
                echo ""
                echo -e "      ${BOLD}NFS Exports:${RESET}"
                section="nfs"; continue ;;
        esac
        [ -z "$line" ] && continue

        local status name_or_path extra
        status=$(echo "$line" | cut -d'|' -f1)
        name_or_path=$(echo "$line" | cut -d'|' -f2)
        extra=$(echo "$line" | cut -d'|' -f3)

        local icon="${GREEN}${_TICK}${RESET}"
        [ "$status" = "OFF" ] && icon="${RED}${_CROSS}${RESET}"

        case "$section" in
            smb)
                echo -e "        ${icon} ${name_or_path}: ${extra}"
                smb_count=$((smb_count + 1))
                ;;
            nfs)
                echo -e "        ${icon} ${name_or_path}  (networks: ${extra})"
                nfs_count=$((nfs_count + 1))
                ;;
        esac
    done <<< "$output"

    [ "$section" = "nfs" ] && [ $nfs_count -eq 0 ] && echo -e "        ${DIM}(none)${RESET}"

    freq_footer
    log "truenas: shares viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# ALERTS — Active system alerts
# ═══════════════════════════════════════════════════════════════════
_tn_alerts() {
    freq_header "TrueNAS Alerts ($_TN_NAME)"

    local output
    output=$(_tn_ssh "sudo midclt call alert.list 2>/dev/null | python3 -c \"
import sys, json
try:
    alerts = json.load(sys.stdin)
    if not alerts:
        print('NONE')
    else:
        for a in alerts:
            level = a.get('level', 'INFO')
            text = a.get('formatted', a.get('text', 'unknown'))
            print(f'{level}|{text}')
except:
    print('ERROR')
\" 2>/dev/null" 2>/dev/null)

    if [ -z "$output" ] || [ "$output" = "ERROR" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve alerts"
        freq_footer
        return 1
    fi

    if [ "$output" = "NONE" ]; then
        echo -e "      ${GREEN}${_TICK}${RESET}  No active alerts"
    else
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local level text
            level=$(echo "$line" | cut -d'|' -f1)
            text=$(echo "$line" | cut -d'|' -f2-)

            case "$level" in
                CRITICAL|ERROR) echo -e "      ${RED}${_CROSS} ${level}${RESET} — $text" ;;
                WARNING)        echo -e "      ${YELLOW}${_WARN} ${level}${RESET} — $text" ;;
                *)              echo -e "      ${DIM}${level}${RESET} — $text" ;;
            esac
        done <<< "$output"
    fi

    freq_footer
    log "truenas: alerts viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# DISKS — Physical disk inventory
# ═══════════════════════════════════════════════════════════════════
_tn_disks() {
    freq_header "TrueNAS Disks ($_TN_NAME)"

    local output
    output=$(_tn_ssh "sudo midclt call disk.query 2>/dev/null | python3 -c \"
import sys, json
try:
    disks = json.load(sys.stdin)
    for d in disks:
        name = d.get('name', '?')
        model = d.get('model', 'unknown')
        serial = d.get('serial', 'unknown')
        size_bytes = d.get('size', 0)
        size_gb = size_bytes / (1024**3) if size_bytes else 0
        temp = d.get('temperature', 'N/A')
        pool = d.get('pool', '') or 'unassigned'
        print(f'{name}|{model}|{serial}|{size_gb:.0f}|{temp}|{pool}')
except:
    print('ERROR')
\" 2>/dev/null" 2>/dev/null)

    if [ -z "$output" ] || [ "$output" = "ERROR" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve disk info"
        freq_footer
        return 1
    fi

    printf "      ${BOLD}%-8s %-25s %-15s %8s  %5s  %s${RESET}\n" "Disk" "Model" "Serial" "Size" "Temp" "Pool"
    freq_line "$(printf '%.0s─' {1..80})"

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        local dname dmodel dserial dsize dtemp dpool
        dname=$(echo "$line" | cut -d'|' -f1)
        dmodel=$(echo "$line" | cut -d'|' -f2)
        dserial=$(echo "$line" | cut -d'|' -f3)
        dsize=$(echo "$line" | cut -d'|' -f4)
        dtemp=$(echo "$line" | cut -d'|' -f5)
        dpool=$(echo "$line" | cut -d'|' -f6)

        # Color temp
        local temp_color="${RESET}"
        if [ "$dtemp" != "N/A" ] && [ "$dtemp" != "None" ]; then
            [ "${dtemp:-0}" -gt 45 ] 2>/dev/null && temp_color="${YELLOW}"
            [ "${dtemp:-0}" -gt 55 ] 2>/dev/null && temp_color="${RED}"
        fi

        printf "      %-8s %-25s %-15s %6sGB  ${temp_color}%5s${RESET}  %s\n" \
            "$dname" "${dmodel:0:25}" "${dserial:0:15}" "$dsize" "${dtemp:-N/A}" "$dpool"
    done <<< "$output"

    freq_footer
    log "truenas: disks viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# SNAPSHOTS — ZFS snapshot listing
# ═══════════════════════════════════════════════════════════════════
_tn_snap() {
    local subcmd="${1:-list}"

    case "$subcmd" in
        list)
            freq_header "ZFS Snapshots ($_TN_NAME)"

            local output
            output=$(_tn_ssh "sudo zfs list -t snapshot -o name,creation,used -s creation 2>/dev/null | tail -20" 2>/dev/null)

            if [ -z "$output" ]; then
                echo -e "      ${DIM}No snapshots found${RESET}"
            else
                echo -e "      ${BOLD}Last 20 snapshots:${RESET}"
                while IFS= read -r line; do
                    echo "      $line"
                done <<< "$output"
            fi

            freq_footer
            ;;
        *)
            echo "Usage: freq truenas snap [list]"
            ;;
    esac
    log "truenas: snapshots viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# NFS — NFS exports and service health
# ═══════════════════════════════════════════════════════════════════
_tn_nfs() {
    freq_header "TrueNAS NFS Health ($_TN_NAME)"

    local output
    output=$(_tn_ssh "
        echo '=== SERVICE ==='
        sudo midclt call nfs.config 2>/dev/null | python3 -c \"
import sys, json
try:
    c = json.load(sys.stdin)
    servers = c.get('servers', 'unknown')
    v4 = c.get('v4', False)
    protocols = c.get('protocols', ['unknown'])
    print(f'servers={servers}')
    print(f'v4={v4}')
    print(f'protocols={protocols}')
except:
    print('error')
\" 2>/dev/null
        echo '=== EXPORTS ==='
        sudo midclt call sharing.nfs.query 2>/dev/null | python3 -c \"
import sys, json
try:
    exports = json.load(sys.stdin)
    for e in exports:
        enabled = 'ON' if e.get('enabled') else 'OFF'
        paths = ', '.join(e.get('paths', [e.get('path', '?')]))
        networks = ', '.join(e.get('networks', ['any']))
        maproot = e.get('maproot_user', '') or e.get('mapall_user', '') or 'default'
        sec = ', '.join(e.get('security', ['sys']))
        print(f'{enabled}|{paths}|{networks}|{maproot}|{sec}')
except:
    pass
\" 2>/dev/null
        echo '=== CLIENTS ==='
        showmount -a 2>/dev/null | head -15 || echo '(showmount unavailable)'
    " 2>/dev/null)

    if [ -z "$output" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve NFS info"
        freq_footer
        return 1
    fi

    local section=""
    while IFS= read -r line; do
        case "$line" in
            "=== SERVICE ===") section="service"; echo -e "      ${BOLD}NFS Service:${RESET}"; continue ;;
            "=== EXPORTS ===") section="exports"; echo ""; echo -e "      ${BOLD}Exports:${RESET}"; continue ;;
            "=== CLIENTS ===") section="clients"; echo ""; echo -e "      ${BOLD}Connected Clients:${RESET}"; continue ;;
        esac
        [ -z "$line" ] && continue

        case "$section" in
            service)
                echo "        $line"
                ;;
            exports)
                local estatus epath enetworks emaproot esec
                estatus=$(echo "$line" | cut -d'|' -f1)
                epath=$(echo "$line" | cut -d'|' -f2)
                enetworks=$(echo "$line" | cut -d'|' -f3)
                emaproot=$(echo "$line" | cut -d'|' -f4)
                esec=$(echo "$line" | cut -d'|' -f5)

                local eicon="${GREEN}${_TICK}${RESET}"
                [ "$estatus" = "OFF" ] && eicon="${RED}${_CROSS}${RESET}"
                echo -e "        ${eicon} ${epath}"
                echo -e "          networks: ${enetworks}  maproot: ${emaproot}  security: ${esec}"
                ;;
            clients)
                echo "        $line"
                ;;
        esac
    done <<< "$output"

    freq_footer
    log "truenas: NFS health viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# SMB — SMB shares detail
# ═══════════════════════════════════════════════════════════════════
_tn_smb() {
    freq_header "TrueNAS SMB Shares ($_TN_NAME)"

    local output
    output=$(_tn_ssh "sudo midclt call sharing.smb.query 2>/dev/null | python3 -c \"
import sys, json
try:
    shares = json.load(sys.stdin)
    if not shares:
        print('NONE')
    else:
        for s in shares:
            enabled = 'ON' if s.get('enabled') else 'OFF'
            name = s.get('name', '?')
            path = s.get('path', '?')
            comment = s.get('comment', '')
            ro = 'RO' if s.get('ro', False) else 'RW'
            print(f'{enabled}|{name}|{path}|{ro}|{comment}')
except:
    print('ERROR')
\" 2>/dev/null" 2>/dev/null)

    if [ -z "$output" ] || [ "$output" = "ERROR" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve SMB shares"
        freq_footer
        return 1
    fi

    if [ "$output" = "NONE" ]; then
        echo -e "      ${DIM}No SMB shares configured${RESET}"
    else
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local sstatus sname spath sro scomment
            sstatus=$(echo "$line" | cut -d'|' -f1)
            sname=$(echo "$line" | cut -d'|' -f2)
            spath=$(echo "$line" | cut -d'|' -f3)
            sro=$(echo "$line" | cut -d'|' -f4)
            scomment=$(echo "$line" | cut -d'|' -f5)

            local sicon="${GREEN}${_TICK}${RESET}"
            [ "$sstatus" = "OFF" ] && sicon="${RED}${_CROSS}${RESET}"

            echo -e "      ${sicon} ${BOLD}${sname}${RESET} (${sro})"
            echo -e "        Path: ${spath}"
            [ -n "$scomment" ] && echo -e "        Note: ${scomment}"
        done <<< "$output"
    fi

    freq_footer
    log "truenas: SMB shares viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# USERS — Non-builtin user accounts
# ═══════════════════════════════════════════════════════════════════
_tn_users() {
    freq_header "TrueNAS Users ($_TN_NAME)"

    local output
    output=$(_tn_ssh "sudo midclt call user.query 2>/dev/null | python3 -c \"
import sys, json
try:
    users = json.load(sys.stdin)
    for u in users:
        if u.get('builtin', False):
            continue
        username = u.get('username', '?')
        uid = u.get('uid', '?')
        groups = u.get('groups', [])
        shell = u.get('shell', '/bin/sh')
        sudo_cmds = u.get('sudo_commands_nopasswd', []) or u.get('sudo_commands', [])
        has_sudo = 'SUDO' if sudo_cmds else ''
        home = u.get('home', '')
        print(f'{username}|{uid}|{shell}|{has_sudo}|{home}')
except:
    print('ERROR')
\" 2>/dev/null" 2>/dev/null)

    if [ -z "$output" ] || [ "$output" = "ERROR" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve users"
        freq_footer
        return 1
    fi

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        local uname uuid ushell usudo uhome
        uname=$(echo "$line" | cut -d'|' -f1)
        uuid=$(echo "$line" | cut -d'|' -f2)
        ushell=$(echo "$line" | cut -d'|' -f3)
        usudo=$(echo "$line" | cut -d'|' -f4)
        uhome=$(echo "$line" | cut -d'|' -f5)

        local sudo_tag=""
        [ -n "$usudo" ] && sudo_tag=" ${YELLOW}[SUDO]${RESET}"

        echo -e "      ${_ARROW} ${BOLD}${uname}${RESET} (uid=${uuid}) shell=${ushell}${sudo_tag}"
        [ -n "$uhome" ] && echo -e "        home: ${uhome}"
    done <<< "$output"

    freq_footer
    log "truenas: users viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# SERVICES — Running services
# ═══════════════════════════════════════════════════════════════════
_tn_services() {
    freq_header "TrueNAS Services ($_TN_NAME)"

    local output
    output=$(_tn_ssh "sudo midclt call service.query 2>/dev/null | python3 -c \"
import sys, json
try:
    services = json.load(sys.stdin)
    for s in sorted(services, key=lambda x: x.get('service', '')):
        svc = s.get('service', '?')
        state = s.get('state', 'UNKNOWN')
        enable = 'auto' if s.get('enable', False) else 'manual'
        print(f'{state}|{svc}|{enable}')
except:
    print('ERROR')
\" 2>/dev/null" 2>/dev/null)

    if [ -z "$output" ] || [ "$output" = "ERROR" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve services"
        freq_footer
        return 1
    fi

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        local sstate sname senable
        sstate=$(echo "$line" | cut -d'|' -f1)
        sname=$(echo "$line" | cut -d'|' -f2)
        senable=$(echo "$line" | cut -d'|' -f3)

        local sicon
        case "$sstate" in
            RUNNING) sicon="${GREEN}${_TICK}${RESET}" ;;
            STOPPED) sicon="${RED}${_CROSS}${RESET}" ;;
            *)       sicon="${YELLOW}${_WARN}${RESET}" ;;
        esac

        printf "      ${sicon} %-20s %-10s %s\n" "$sname" "$sstate" "($senable)"
    done <<< "$output"

    freq_footer
    log "truenas: services viewed ($_TN_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# BACKUP — Backup TrueNAS config via SSH
# ═══════════════════════════════════════════════════════════════════
_tn_backup() {
    local dry_run="${DRY_RUN:-false}"

    freq_header "TrueNAS Config Backup ($_TN_NAME)"

    local backup_dir="${FREQ_DIR}/bak"
    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)
    local backup_file="${backup_dir}/truenas-${_TN_NAME}-${timestamp}.json"

    if [ "$dry_run" = "true" ]; then
        echo -e "      ${YELLOW}[DRY-RUN]${RESET} Would back up TrueNAS config from $_TN_NAME"
        echo -e "      ${DIM}Target: ${backup_file}${RESET}"
        freq_footer
        return 0
    fi

    # Protected operation — config backup is a sensitive read
    if ! require_protected "TrueNAS config backup" "$_TN_IP" \
        "Exports full system configuration" \
        "Verify backup destination is secure"; then
        return 1
    fi

    # Get system general config + pool config via SSH
    local config
    config=$(_tn_ssh "
        echo '{\"general\":' ; sudo midclt call system.general.config 2>/dev/null ; echo ','
        echo '\"ntp\":' ; sudo midclt call system.ntpserver.query 2>/dev/null ; echo ','
        echo '\"network\":' ; sudo midclt call network.configuration.config 2>/dev/null ; echo ','
        echo '\"pools\":' ; sudo midclt call pool.query 2>/dev/null ; echo ','
        echo '\"smb_shares\":' ; sudo midclt call sharing.smb.query 2>/dev/null ; echo ','
        echo '\"nfs_exports\":' ; sudo midclt call sharing.nfs.query 2>/dev/null ; echo ','
        echo '\"users\":' ; sudo midclt call user.query 2>/dev/null ; echo ','
        echo '\"services\":' ; sudo midclt call service.query 2>/dev/null
        echo '}'
    " 2>/dev/null)

    if [ -n "$config" ]; then
        mkdir -p "$backup_dir"
        echo "$config" > "$backup_file"
        echo -e "      ${GREEN}${_TICK}${RESET}  Config backed up to ${backup_file}"
        log "truenas: config backed up from $_TN_NAME to $backup_file"
    else
        echo -e "      ${RED}${_CROSS}${RESET}  Failed to retrieve config from $_TN_NAME"
        return 1
    fi

    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# CHECK — Connectivity + health check
# ═══════════════════════════════════════════════════════════════════
_tn_check() {
    freq_header "TrueNAS Health Check ($_TN_NAME)"

    local pass=0 fail=0 warn=0

    # 1. Ping
    echo -ne "      Ping:        "
    if ping -c 1 -W 3 "$_TN_IP" &>/dev/null; then
        echo -e "${GREEN}OK${RESET}"
        pass=$((pass + 1))
    else
        echo -e "${RED}FAIL${RESET}"
        fail=$((fail + 1))
        freq_footer
        echo -e "      Result: ${RED}${fail} FAIL${RESET}"
        return 1
    fi

    # 2. SSH
    echo -ne "      SSH:         "
    local ssh_test
    ssh_test=$(_tn_ssh "echo SSH_OK" 2>/dev/null)
    if [ "$ssh_test" = "SSH_OK" ]; then
        echo -e "${GREEN}OK${RESET}"
        pass=$((pass + 1))
    else
        echo -e "${RED}FAIL${RESET}"
        fail=$((fail + 1))
    fi

    # Single SSH call for remaining checks
    local health_output
    health_output=$(_tn_ssh "
        echo '=== ZPOOL ==='
        sudo zpool status -x 2>/dev/null || echo 'ZPOOL_ERROR'
        echo '=== ALERTS ==='
        sudo midclt call alert.list 2>/dev/null | python3 -c \"
import sys, json
try:
    alerts = json.load(sys.stdin)
    crit = sum(1 for a in alerts if a.get('level') in ('CRITICAL','ERROR'))
    warn = sum(1 for a in alerts if a.get('level') == 'WARNING')
    print(f'{crit}|{warn}|{len(alerts)}')
except:
    print('0|0|0')
\" 2>/dev/null
        echo '=== UPTIME ==='
        uptime -p 2>/dev/null || uptime
        echo '=== DISK_TEMP ==='
        sudo midclt call disk.query 2>/dev/null | python3 -c \"
import sys, json
try:
    disks = json.load(sys.stdin)
    hot = [d for d in disks if (d.get('temperature') or 0) > 45]
    if hot:
        for d in hot:
            print(f\\\"{d['name']}:{d.get('temperature', 'N/A')}\\\")
    else:
        print('ALL_OK')
except:
    print('UNKNOWN')
\" 2>/dev/null
        echo '=== SERVICES ==='
        sudo midclt call service.query 2>/dev/null | python3 -c \"
import sys, json
try:
    svcs = json.load(sys.stdin)
    nfs = next((s for s in svcs if s.get('service') == 'nfs'), None)
    smb = next((s for s in svcs if s.get('service') == 'cifs'), None)
    print('NFS:' + (nfs.get('state', 'UNKNOWN') if nfs else 'NOT_FOUND'))
    print('SMB:' + (smb.get('state', 'UNKNOWN') if smb else 'NOT_FOUND'))
except:
    print('NFS:UNKNOWN')
    print('SMB:UNKNOWN')
\" 2>/dev/null
    " 2>/dev/null)

    # Parse health output
    local section=""
    local zpool_status="" alert_crit=0 alert_warn=0 uptime_str="" nfs_state="" smb_state=""
    local -a hot_disks=()

    while IFS= read -r line; do
        case "$line" in
            "=== ZPOOL ===")     section="zpool"; continue ;;
            "=== ALERTS ===")    section="alerts"; continue ;;
            "=== UPTIME ===")    section="uptime"; continue ;;
            "=== DISK_TEMP ===") section="disktemp"; continue ;;
            "=== SERVICES ===")  section="services"; continue ;;
        esac
        case "$section" in
            zpool)    [ -n "$line" ] && zpool_status="${zpool_status}${line}" ;;
            alerts)
                if [ -n "$line" ]; then
                    alert_crit=$(echo "$line" | cut -d'|' -f1)
                    alert_warn=$(echo "$line" | cut -d'|' -f2)
                fi
                ;;
            uptime)   [ -n "$line" ] && uptime_str="$line" ;;
            disktemp)
                if [ "$line" = "ALL_OK" ]; then
                    : # fine
                elif [ "$line" != "UNKNOWN" ] && [ -n "$line" ]; then
                    hot_disks+=("$line")
                fi
                ;;
            services)
                if [[ "$line" == NFS:* ]]; then
                    nfs_state="${line#NFS:}"
                elif [[ "$line" == SMB:* ]]; then
                    smb_state="${line#SMB:}"
                fi
                ;;
        esac
    done <<< "$health_output"

    # 3. ZFS health
    echo -ne "      ZFS Pools:   "
    if [[ "$zpool_status" == *"all pools are healthy"* ]]; then
        echo -e "${GREEN}HEALTHY${RESET}"
        pass=$((pass + 1))
    elif [[ "$zpool_status" == *"ZPOOL_ERROR"* ]]; then
        echo -e "${RED}ERROR${RESET}"
        fail=$((fail + 1))
    else
        echo -e "${YELLOW}DEGRADED${RESET}"
        warn=$((warn + 1))
    fi

    # 4. Alerts
    echo -ne "      Alerts:      "
    if [ "${alert_crit:-0}" -gt 0 ]; then
        echo -e "${RED}${alert_crit} critical${RESET}"
        fail=$((fail + 1))
    elif [ "${alert_warn:-0}" -gt 0 ]; then
        echo -e "${YELLOW}${alert_warn} warning${RESET}"
        warn=$((warn + 1))
    else
        echo -e "${GREEN}none${RESET}"
        pass=$((pass + 1))
    fi

    # 5. Disk temps
    echo -ne "      Disk Temps:  "
    if [ ${#hot_disks[@]} -gt 0 ]; then
        echo -e "${YELLOW}${#hot_disks[@]} hot (>45°C)${RESET}"
        for hd in "${hot_disks[@]}"; do
            echo -e "        ${YELLOW}${_WARN}${RESET} ${hd}"
        done
        warn=$((warn + 1))
    else
        echo -e "${GREEN}OK${RESET}"
        pass=$((pass + 1))
    fi

    # 6. NFS service
    echo -ne "      NFS:         "
    if [ "$nfs_state" = "RUNNING" ]; then
        echo -e "${GREEN}RUNNING${RESET}"
        pass=$((pass + 1))
    elif [ "$nfs_state" = "NOT_FOUND" ]; then
        echo -e "${DIM}not configured${RESET}"
    else
        echo -e "${RED}${nfs_state:-DOWN}${RESET}"
        fail=$((fail + 1))
    fi

    # 7. SMB service
    echo -ne "      SMB:         "
    if [ "$smb_state" = "RUNNING" ]; then
        echo -e "${GREEN}RUNNING${RESET}"
        pass=$((pass + 1))
    elif [ "$smb_state" = "NOT_FOUND" ]; then
        echo -e "${DIM}not configured${RESET}"
    else
        echo -e "${RED}${smb_state:-DOWN}${RESET}"
        fail=$((fail + 1))
    fi

    echo ""
    echo -ne "      Uptime:      "
    echo -e "${uptime_str:-unknown}"

    echo ""
    local total=$((pass + fail + warn))
    if [ $fail -gt 0 ]; then
        echo -e "      Result: ${RED}${pass}/${total} pass, ${fail} FAIL, ${warn} warn${RESET}"
    elif [ $warn -gt 0 ]; then
        echo -e "      Result: ${YELLOW}${pass}/${total} pass, ${warn} warn${RESET}"
    else
        echo -e "      Result: ${GREEN}${pass}/${total} pass${RESET}"
    fi

    freq_footer
    log "truenas: health check $_TN_NAME — ${pass}/${total} pass, ${fail} fail, ${warn} warn"
}

# ═══════════════════════════════════════════════════════════════════
# SCRUB — Trigger ZFS scrub (protected operation)
# ═══════════════════════════════════════════════════════════════════
_tn_scrub() {
    local dry_run="${DRY_RUN:-false}"

    freq_header "TrueNAS ZFS Scrub ($_TN_NAME)"

    if [ "$dry_run" = "true" ]; then
        echo -e "      ${YELLOW}[DRY-RUN]${RESET} Would trigger ZFS scrub on all pools ($_TN_NAME)"
        freq_footer
        return 0
    fi

    # Protected operation — scrub on degraded pool can stress failing disks
    if ! require_protected "TrueNAS ZFS scrub" "$_TN_IP" \
        "Forced scrub on degraded pool can accelerate disk failure" \
        "Verify pool health before scrubbing"; then
        return 1
    fi

    # Get pool names and trigger scrub
    local pools
    pools=$(_tn_ssh "sudo zpool list -H -o name 2>/dev/null" 2>/dev/null)

    if [ -z "$pools" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve pool list"
        freq_footer
        return 1
    fi

    while IFS= read -r pool; do
        [ -z "$pool" ] && continue
        echo -ne "      Scrubbing ${BOLD}${pool}${RESET}... "
        local result
        result=$(_tn_ssh "sudo zpool scrub '$pool' 2>&1" 2>/dev/null)
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}started${RESET}"
        else
            echo -e "${RED}failed${RESET}: $result"
        fi
    done <<< "$pools"

    freq_footer
    log "truenas: scrub triggered on $_TN_NAME"
}
