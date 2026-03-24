#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/pfsense.sh
# pfSense Firewall Management
#
# Author:  FREQ Project / LOW FREQ Labs
#
# pfSense status, interfaces, rules, NAT, logs, services, backup, check, probe
# Supports --target lab|prod|<IP> for multi-firewall environments
#
# Commands: cmd_pfsense
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════

# Resolve pfSense target: prod (default), lab, or raw IP
# Sets: _PF_IP, _PF_NAME, _PF_RESOLVE (freq_resolve-friendly label)
_pf_resolve_target() {
    local target="${1:-prod}"
    case "$target" in
        prod|production)
            _PF_IP="${PFSENSE_HOST:-${PFSENSE_IP:-10.25.255.1}}"
            _PF_NAME="pfsense (prod)"
            _PF_RESOLVE="pfsense"
            ;;
        lab)
            _PF_IP="${PFSENSE_LAB_IP:-10.25.255.180}"
            _PF_NAME="pfsense-lab"
            _PF_RESOLVE="pfsense-lab"
            ;;
        *)
            # Raw IP or hosts.conf label
            local resolved
            resolved=$(freq_resolve "$target" 2>/dev/null)
            if [ -n "$resolved" ]; then
                _PF_IP=$(echo "$resolved" | awk '{print $1}')
                _PF_NAME=$(echo "$resolved" | awk '{print $3}')
                _PF_RESOLVE="$_PF_NAME"
            else
                _PF_IP="$target"
                _PF_NAME="$target"
                _PF_RESOLVE="$target"
            fi
            ;;
    esac
}

# SSH to pfSense target — uses resolve label so freq_ssh detects type correctly
# pfSense type → root@host via FREQ key (configured in ssh.sh)
_pf_ssh() {
    freq_ssh "$_PF_RESOLVE" "$@"
}

# ═══════════════════════════════════════════════════════════════════
# cmd_pfsense — Main entry point
# Usage: freq pfsense <subcommand> [--target lab|prod|IP]
# ═══════════════════════════════════════════════════════════════════
cmd_pfsense() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    # Parse --target flag from remaining args
    local target="prod"
    local args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target)
                if [[ -z "${2:-}" ]]; then
                    echo -e "  ${RED}Missing value for --target (expected: lab, prod, or IP)${RESET}"
                    return 1
                fi
                target="$2"; shift 2
                ;;
            --help|-h)
                _pf_help
                return 0
                ;;
            *)
                args+=("$1"); shift
                ;;
        esac
    done
    _pf_resolve_target "$target"

    case "$subcmd" in
        status)       _pf_status ;;
        interfaces|if) _pf_interfaces ;;
        rules)        _pf_rules ;;
        nat)          _pf_nat ;;
        states)       _pf_states ;;
        logs)         _pf_logs "${args[@]}" ;;
        services)     _pf_services "${args[@]}" ;;
        backup)       _pf_backup ;;
        check)        _pf_check ;;
        probe)        _pf_probe ;;
        configure)    _pf_configure "${args[@]}" ;;
        remove)       _pf_remove "${args[@]}" ;;
        help|--help|-h) _pf_help ;;
        *)
            echo -e "  ${RED}Unknown subcommand: ${subcmd}${RESET}"
            _pf_help
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# _pf_help — Usage text
# ═══════════════════════════════════════════════════════════════════
_pf_help() {
    cat << 'EOF'
Usage: freq pfsense <subcommand> [--target lab|prod|IP]

  freq pfsense status          — version, uptime, states, WireGuard peers
  freq pfsense interfaces      — interface details (IP, MAC, status)
  freq pfsense rules           — active firewall rules (pfctl -sr)
  freq pfsense nat             — NAT/port-forward rules (pfctl -sn)
  freq pfsense states          — active state table count
  freq pfsense logs [N]        — last N firewall log entries (default 50)
  freq pfsense services [svc]  — list services, or restart <svc> (admin)
  freq pfsense backup          — backup config.xml (admin)
  freq pfsense check           — connectivity + pfctl health check
  freq pfsense probe           — deploy FREQ SSH key (admin, protected)
  freq pfsense configure       — add DHCP/DNS entry (admin)
  freq pfsense remove          — remove DHCP/DNS entry (admin)

  --target lab|prod|IP    Target firewall (default: prod)

Examples:
  freq pfsense status                    # prod firewall status
  freq pfsense status --target lab       # lab firewall status
  freq pfsense rules --target lab        # lab firewall rules
  freq pfsense services unbound          # restart unbound on prod
  freq pfsense logs 100                  # last 100 firewall log entries
EOF
}

# ═══════════════════════════════════════════════════════════════════
# STATUS — Version, uptime, firewall states, WireGuard peers
# ═══════════════════════════════════════════════════════════════════
_pf_status() {
    require_operator || return 1
    freq_header "pfSense Status ($_PF_NAME)"

    echo -n "  Connectivity: "
    if ! ping -c 1 -W 3 "$_PF_IP" &>/dev/null; then
        echo -e "${RED}UNREACHABLE${RESET}"
        freq_footer
        return 1
    fi
    echo -e "${GREEN}OK${RESET}"

    # Single SSH call to collect all info
    local data
    data=$(_pf_ssh '
        echo "VERSION:$(cat /etc/version 2>/dev/null)"
        echo "UPTIME:$(uptime 2>/dev/null)"
        echo "STATES:$(pfctl -si 2>/dev/null | grep "current entries" | awk "{print \$3}")"
        echo "IFACE:$(ifconfig -l 2>/dev/null)"
        if command -v wg >/dev/null 2>&1; then
            peers=$(wg show all peers 2>/dev/null | wc -l | tr -d " ")
            echo "WG_PEERS:$peers"
        fi
    ')

    if [ -z "$data" ]; then
        echo -e "  ${RED}SSH failed — cannot collect status${RESET}"
        freq_footer
        return 1
    fi

    echo "$data" | while IFS=: read -r key val; do
        case "$key" in
            VERSION)  echo -e "  Version:    ${DIM}$val${RESET}" ;;
            UPTIME)   echo -e "  Uptime:     ${DIM}$val${RESET}" ;;
            STATES)   echo -e "  FW states:  ${BOLD}$val${RESET}" ;;
            IFACE)    echo -e "  Interfaces: ${DIM}$val${RESET}" ;;
            WG_PEERS) echo -e "  WG peers:   ${BOLD}$val${RESET}" ;;
        esac
    done

    freq_footer
    log "pfsense: status viewed ($_PF_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# INTERFACES — Interface details (IP, MAC, status)
# ═══════════════════════════════════════════════════════════════════
_pf_interfaces() {
    require_operator || return 1
    freq_header "pfSense Interfaces ($_PF_NAME)"

    local data
    data=$(_pf_ssh '
        for iface in $(ifconfig -l); do
            inet=$(ifconfig "$iface" 2>/dev/null | grep "inet " | head -1 | awk "{print \$2}")
            mask=$(ifconfig "$iface" 2>/dev/null | grep "inet " | head -1 | awk "{print \$4}")
            status=$(ifconfig "$iface" 2>/dev/null | grep "status:" | awk "{print \$2}")
            ether=$(ifconfig "$iface" 2>/dev/null | grep "ether " | awk "{print \$2}")
            echo "IF:${iface}|${inet}|${mask}|${status}|${ether}"
        done
    ')

    if [ -z "$data" ]; then
        echo -e "  ${RED}SSH failed — cannot collect interface data${RESET}"
        freq_footer
        return 1
    fi

    echo "$data" | while IFS='|' read -r iface_raw ip mask status ether; do
        local iface="${iface_raw#IF:}"
        [ -z "$iface" ] && continue
        # Skip pseudo-interfaces with no useful info
        [ -z "$ip" ] && [ -z "$status" ] && [ -z "$ether" ] && continue

        echo ""
        echo -e "  ${BOLD}${iface}${RESET}"
        [ -n "$ether" ] && echo -e "    MAC:    ${DIM}${ether}${RESET}"
        if [ -n "$ip" ]; then
            echo -e "    IP:     ${GREEN}${ip}${RESET}  mask ${DIM}${mask}${RESET}"
        else
            echo -e "    IP:     ${DIM}(none)${RESET}"
        fi
        if [ -n "$status" ]; then
            if [ "$status" = "active" ]; then
                echo -e "    Status: ${GREEN}active${RESET}"
            else
                echo -e "    Status: ${RED}${status}${RESET}"
            fi
        fi
    done

    echo ""
    freq_footer
    log "pfsense: interfaces viewed ($_PF_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# RULES — Active firewall rules
# ═══════════════════════════════════════════════════════════════════
_pf_rules() {
    require_operator || return 1
    freq_header "pfSense Rules ($_PF_NAME)"

    local rules
    rules=$(_pf_ssh "pfctl -sr 2>/dev/null")
    if [ -z "$rules" ]; then
        echo -e "  ${RED}Cannot retrieve firewall rules${RESET}"
        freq_footer
        return 1
    fi

    echo "$rules" | head -50 | while IFS= read -r line; do
        echo "  $line"
    done

    local total
    total=$(echo "$rules" | wc -l | tr -d ' ')
    if [ "$total" -gt 50 ]; then
        echo -e "  ${DIM}... showing 50 of $total rules${RESET}"
    fi

    freq_footer
    log "pfsense: rules viewed ($_PF_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# NAT — NAT/port-forward rules
# ═══════════════════════════════════════════════════════════════════
_pf_nat() {
    require_operator || return 1
    freq_header "pfSense NAT Rules ($_PF_NAME)"

    local nat
    nat=$(_pf_ssh "pfctl -sn 2>/dev/null")
    if [ -z "$nat" ]; then
        echo -e "  ${DIM}No NAT rules or cannot retrieve${RESET}"
        freq_footer
        return 0
    fi

    echo "$nat" | while IFS= read -r line; do
        echo "  $line"
    done

    freq_footer
    log "pfsense: NAT rules viewed ($_PF_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# STATES — Active state table count
# ═══════════════════════════════════════════════════════════════════
_pf_states() {
    require_operator || return 1
    local count
    count=$(_pf_ssh "pfctl -si 2>/dev/null | grep 'current entries' | awk '{print \$3}'" 2>/dev/null)
    echo -e "  Active states: ${BOLD}${count:-unknown}${RESET}"
    log "pfsense: states viewed ($_PF_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# LOGS — Recent firewall log entries
# pfSense filter.log is binary clog format, needs special handling
# ═══════════════════════════════════════════════════════════════════
_pf_logs() {
    require_operator || return 1
    local count="${1:-50}"
    freq_header "pfSense Firewall Logs ($_PF_NAME, last $count)"

    # filter.log is binary clog format — use cat | strings | tail
    local logs
    logs=$(_pf_ssh "cat /var/log/filter.log 2>/dev/null | strings | tail -${count}")
    if [ -z "$logs" ]; then
        echo -e "  ${DIM}No log entries or cannot read filter.log${RESET}"
        freq_footer
        return 0
    fi

    echo "$logs" | while IFS= read -r line; do
        # Color-code pass/block
        if echo "$line" | grep -q ",block,"; then
            echo -e "  ${RED}$line${RESET}"
        elif echo "$line" | grep -q ",pass,"; then
            echo -e "  ${GREEN}$line${RESET}"
        else
            echo "  $line"
        fi
    done

    freq_footer
    log "pfsense: logs viewed ($_PF_NAME, count=$count)"
}

# ═══════════════════════════════════════════════════════════════════
# SERVICES — List or restart pfSense services
# [HIDDEN-2/7] S037 guard — pfSense service restart with pre/post SSH check
# ═══════════════════════════════════════════════════════════════════
_pf_services() {
    local service="${1:-}"

    if [ -z "$service" ]; then
        # List all services
        require_operator || return 1
        freq_header "pfSense Services ($_PF_NAME)"

        local services
        services=$(_pf_ssh "php -r 'require_once(\"service-utils.inc\"); foreach(get_services() as \$s) echo \$s[\"name\"].\":\".get_service_status(\$s).\"\\n\";' 2>/dev/null")

        if [ -z "$services" ]; then
            echo -e "  ${RED}Cannot retrieve service list${RESET}"
            freq_footer
            return 1
        fi

        echo "$services" | while IFS=: read -r name status; do
            [ -z "$name" ] && continue
            if [ "$status" = "1" ]; then
                echo -e "  ${GREEN}${_TICK}${RESET} $name"
            else
                echo -e "  ${RED}${_CROSS}${RESET} $name"
            fi
        done

        freq_footer
        log "pfsense: services listed ($_PF_NAME)"
    else
        # Restart a specific service — admin + protected op
        require_admin || return 1

        if ! require_protected "pfsense service restart" "$_PF_IP" \
            "Stopping DNS/gateway services = DC-wide outage" \
            "Physical console access to pfSense"; then
            return 1
        fi

        # S037 guard — pre-flight SSH check
        echo -n "  Pre-flight SSH check... "
        if ! _pf_ssh "echo OK" 2>/dev/null | grep -q "OK"; then
            echo -e "${RED}FAIL${RESET}"
            echo -e "  ${RED}Cannot verify SSH to $_PF_NAME — aborting restart${RESET}"
            unset PROTECTED_ROOT_PASS 2>/dev/null
            return 1
        fi
        echo -e "${GREEN}OK${RESET}"

        local dry_run="${DRY_RUN:-false}"
        if [ "$dry_run" = "true" ]; then
            echo -e "  ${YELLOW}[DRY-RUN]${RESET} Would restart service '$service' on ${BOLD}$_PF_NAME${RESET}"
            unset PROTECTED_ROOT_PASS 2>/dev/null
            return 0
        fi

        echo -e "  Restarting $service on $_PF_NAME..."
        _pf_ssh "php -r 'require_once(\"service-utils.inc\"); service_control_restart(\"$service\", array());' 2>/dev/null"
        echo -e "  ${GREEN}${_TICK}${RESET} Restart command sent"

        # S037 guard — post-flight SSH check
        sleep 2
        echo -n "  Post-flight SSH check... "
        if _pf_ssh "echo OK" 2>/dev/null | grep -q "OK"; then
            echo -e "${GREEN}OK${RESET}"
        else
            echo -e "${RED}FAIL — connectivity may be impacted!${RESET}"
            echo -e "  ${YELLOW}S037 WARNING: pfSense may be unreachable after service restart${RESET}"
        fi

        log "pfsense: restarted $service on $_PF_NAME"
        unset PROTECTED_ROOT_PASS 2>/dev/null
    fi
}

# ═══════════════════════════════════════════════════════════════════
# BACKUP — Backup config.xml
# ═══════════════════════════════════════════════════════════════════
_pf_backup() {
    require_admin || return 1
    freq_action_modify "Backing up pfSense configuration..."

    local dry_run="${DRY_RUN:-false}"
    if [ "$dry_run" = "true" ]; then
        echo -e "  ${YELLOW}[DRY-RUN]${RESET} Would back up config.xml from ${BOLD}$_PF_NAME${RESET}"
        return 0
    fi

    local backup_dir="${FREQ_DATA_DIR}/backup/pfsense"
    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)
    local backup_file="${backup_dir}/${_PF_NAME//[^a-zA-Z0-9_-]/_}-${timestamp}.xml"

    mkdir -p "$backup_dir" 2>/dev/null

    local config
    config=$(_pf_ssh "cat ${PFSENSE_CONFIG:-/cf/conf/config.xml} 2>/dev/null")
    if [ -n "$config" ]; then
        echo "$config" > "$backup_file"
        local lines
        lines=$(echo "$config" | wc -l | tr -d ' ')
        echo -e "  ${GREEN}${_TICK}${RESET} config.xml backed up ($lines lines)"
        echo -e "  ${DIM}  → $backup_file${RESET}"
        log "pfsense: config backed up from $_PF_NAME → $backup_file"
    else
        echo -e "  ${RED}${_CROSS}${RESET} Could not retrieve config.xml from $_PF_NAME"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════
# CHECK — Connectivity + pfctl health check
# ═══════════════════════════════════════════════════════════════════
_pf_check() {
    require_operator || return 1
    freq_header "pfSense Health Check ($_PF_NAME)"
    local pass=0 fail=0

    # Ping
    echo -n "  Ping: "
    if ping -c 3 -W 2 "$_PF_IP" &>/dev/null; then
        echo -e "${GREEN}OK${RESET}"
        pass=$((pass + 1))
    else
        echo -e "${RED}FAIL${RESET}"
        fail=$((fail + 1))
        echo -e "  ${DIM}(remaining checks skipped — host unreachable)${RESET}"
        freq_footer
        return 1
    fi

    # SSH
    echo -n "  SSH:  "
    if _pf_ssh "echo OK" 2>/dev/null | grep -q "OK"; then
        echo -e "${GREEN}OK${RESET}"
        pass=$((pass + 1))
    else
        echo -e "${RED}FAIL${RESET}"
        fail=$((fail + 1))
    fi

    # pfctl
    echo -n "  pfctl: "
    local states
    states=$(_pf_ssh "pfctl -si 2>/dev/null | grep 'current entries' | awk '{print \$3}'" 2>/dev/null)
    if [ -n "$states" ]; then
        echo -e "${GREEN}OK ($states states)${RESET}"
        pass=$((pass + 1))
    else
        echo -e "${RED}FAIL${RESET}"
        fail=$((fail + 1))
    fi

    echo ""
    echo -e "  Pass: ${GREEN}$pass${RESET}  Fail: ${RED}$fail${RESET}"
    freq_footer
    log "pfsense: check on $_PF_NAME (pass=$pass fail=$fail)"
}

# ═══════════════════════════════════════════════════════════════════
# PROBE — Deploy FREQ SSH key to pfSense
# ═══════════════════════════════════════════════════════════════════
_pf_probe() {
    require_admin || return 1

    if ! require_protected "deploy SSH keys to pfSense" "$_PF_IP" \
        "Deploying keys to firewall — misconfiguration can break SSH access" \
        "Physical console access to pfSense"; then
        return 1
    fi

    local dry_run="${DRY_RUN:-false}"
    if [ "$dry_run" = "true" ]; then
        echo -e "  ${YELLOW}[DRY-RUN]${RESET} Would deploy FREQ SSH key to ${BOLD}$_PF_NAME${RESET}"
        unset PROTECTED_ROOT_PASS 2>/dev/null
        return 0
    fi

    echo "  Deploying FREQ SSH key on $_PF_NAME..."
    local pubkey
    pubkey=$(cat "${FREQ_SSH_KEY}.pub" 2>/dev/null)
    if [ -z "$pubkey" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} FREQ public key not found at ${FREQ_SSH_KEY}.pub"
        unset PROTECTED_ROOT_PASS 2>/dev/null
        return 1
    fi

    if _pf_ssh "mkdir -p /root/.ssh && echo '$pubkey' >> /root/.ssh/authorized_keys && sort -u /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.tmp && mv /root/.ssh/authorized_keys.tmp /root/.ssh/authorized_keys && echo DEPLOYED" 2>/dev/null | grep -q "DEPLOYED"; then
        echo -e "  ${GREEN}${_TICK}${RESET} FREQ key deployed to $_PF_NAME"
        log "pfsense: SSH key deployed to $_PF_NAME"
    else
        echo -e "  ${RED}${_CROSS}${RESET} Key deploy failed on $_PF_NAME"
    fi

    unset PROTECTED_ROOT_PASS 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# CONFIGURE — Add DHCP static mapping + DNS host override
# ═══════════════════════════════════════════════════════════════════
_pf_configure() {
    require_admin || return 1

    local hostname="${1:-}" ip="${2:-}" mac="${3:-}"
    if [ -z "$hostname" ] || [ -z "$ip" ] || [ -z "$mac" ]; then
        echo "Usage: freq pfsense configure <hostname> <ip> <mac>"
        echo "  Adds a DHCP static mapping and DNS host override on pfSense."
        return 1
    fi

    # Sanitize inputs — reject shell metacharacters
    [[ "$hostname" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo -e "  ${RED}Invalid hostname: $hostname${RESET}"; return 1; }
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo -e "  ${RED}Invalid IP: $ip${RESET}"; return 1; }
    [[ "$mac" =~ ^[0-9a-fA-F:]+$ ]] || { echo -e "  ${RED}Invalid MAC: $mac${RESET}"; return 1; }

    local dry_run="${DRY_RUN:-false}"
    if [ "$dry_run" = "true" ]; then
        echo -e "  ${YELLOW}[DRY-RUN]${RESET} Would add DHCP+DNS for ${BOLD}$hostname${RESET} ($ip / $mac) on $_PF_NAME"
        return 0
    fi

    # Verify SSH connectivity first
    if ! _pf_ssh "echo OK" 2>/dev/null | grep -q "OK"; then
        echo -e "  ${RED}Cannot SSH to $_PF_NAME — aborting${RESET}"
        return 1
    fi

    mac=$(echo "$mac" | tr '[:upper:]' '[:lower:]')
    local domain="${VM_DOMAIN:-dc01.local}"

    # PHP script to add DHCP static mapping + DNS host override
    local php_cmd="require_once('config.inc'); require_once('util.inc'); require_once('services.inc');"
    php_cmd+=" if(!is_array(\$config['dhcpd']['lan']['staticmap'])) \$config['dhcpd']['lan']['staticmap']=array();"
    php_cmd+=" \$sm=array(); \$sm['mac']='${mac}'; \$sm['ipaddr']='${ip}'; \$sm['hostname']='${hostname}'; \$sm['descr']='FREQ auto-provisioned';"
    php_cmd+=" \$config['dhcpd']['lan']['staticmap'][]=\$sm;"
    php_cmd+=" if(!is_array(\$config['unbound']['hosts'])) \$config['unbound']['hosts']=array();"
    php_cmd+=" \$dh=array(); \$dh['host']='${hostname}'; \$dh['domain']='${domain}'; \$dh['ip']='${ip}'; \$dh['descr']='FREQ auto-provisioned';"
    php_cmd+=" \$config['unbound']['hosts'][]=\$dh;"
    php_cmd+=" write_config('FREQ: Added VM ${hostname} (${ip})');"
    php_cmd+=" services_dhcpd_configure(); services_unbound_configure();"
    php_cmd+=" echo 'OK';"

    local result
    result=$(_pf_ssh "php -r \"$php_cmd\"" 2>/dev/null)

    if echo "$result" | grep -q "OK"; then
        echo -e "  ${GREEN}${_TICK}${RESET} DHCP ${mac} → ${ip} + DNS ${hostname}.${domain} → ${ip}"
        log "pfsense: added DHCP+DNS for $hostname ($ip/$mac) on $_PF_NAME"
        return 0
    else
        echo -e "  ${RED}${_CROSS}${RESET} Failed to configure DHCP/DNS on $_PF_NAME"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════
# REMOVE — Remove DHCP static mapping + DNS host override
# ═══════════════════════════════════════════════════════════════════
_pf_remove() {
    require_admin || return 1

    local hostname="${1:-}" ip="${2:-}"
    if [ -z "$hostname" ] || [ -z "$ip" ]; then
        echo "Usage: freq pfsense remove <hostname> <ip>"
        echo "  Removes DHCP static mapping and DNS host override from pfSense."
        return 1
    fi

    # Sanitize
    [[ "$hostname" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo -e "  ${RED}Invalid hostname: $hostname${RESET}"; return 1; }
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo -e "  ${RED}Invalid IP: $ip${RESET}"; return 1; }

    local dry_run="${DRY_RUN:-false}"
    if [ "$dry_run" = "true" ]; then
        echo -e "  ${YELLOW}[DRY-RUN]${RESET} Would remove DHCP+DNS for ${BOLD}$hostname${RESET} ($ip) from $_PF_NAME"
        return 0
    fi

    if ! _pf_ssh "echo OK" 2>/dev/null | grep -q "OK"; then
        echo -e "  ${RED}Cannot SSH to $_PF_NAME — aborting${RESET}"
        return 1
    fi

    local php_cmd="require_once('config.inc'); require_once('util.inc'); require_once('services.inc');"
    php_cmd+=" if(is_array(\$config['dhcpd']['lan']['staticmap'])) {"
    php_cmd+="   foreach(\$config['dhcpd']['lan']['staticmap'] as \$idx=>\$map) {"
    php_cmd+="     if(\$map['ipaddr']=='${ip}' || \$map['hostname']=='${hostname}') unset(\$config['dhcpd']['lan']['staticmap'][\$idx]);"
    php_cmd+="   }"
    php_cmd+=" }"
    php_cmd+=" if(is_array(\$config['unbound']['hosts'])) {"
    php_cmd+="   foreach(\$config['unbound']['hosts'] as \$idx=>\$host) {"
    php_cmd+="     if(\$host['ip']=='${ip}' || \$host['host']=='${hostname}') unset(\$config['unbound']['hosts'][\$idx]);"
    php_cmd+="   }"
    php_cmd+=" }"
    php_cmd+=" write_config('FREQ: Removed VM ${hostname} (${ip})');"
    php_cmd+=" services_dhcpd_configure(); services_unbound_configure();"
    php_cmd+=" echo 'OK';"

    local result
    result=$(_pf_ssh "php -r \"$php_cmd\"" 2>/dev/null)

    if echo "$result" | grep -q "OK"; then
        echo -e "  ${GREEN}${_TICK}${RESET} Removed DHCP+DNS for $hostname ($ip) from $_PF_NAME"
        log "pfsense: removed DHCP+DNS for $hostname ($ip) from $_PF_NAME"
        return 0
    else
        echo -e "  ${RED}${_CROSS}${RESET} Failed to remove DHCP/DNS from $_PF_NAME"
        return 1
    fi
}
