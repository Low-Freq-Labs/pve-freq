#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/wazuh.sh
# Wazuh SIEM Management — agent deployment, alerts, status
#
# -- eyes everywhere --
# Commands: cmd_wazuh
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

# Wazuh API config — set in freq.conf or environment
# WAZUH_HOST, WAZUH_API_USER, WAZUH_API_PASS, WAZUH_API_PORT (default 55000)
WAZUH_API_PORT="${WAZUH_API_PORT:-55000}"
WAZUH_TOKEN=""

cmd_wazuh() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)   _wazuh_status ;;
        deploy)   _wazuh_deploy "$@" ;;
        agents)   _wazuh_agents ;;
        alerts)   _wazuh_alerts "$@" ;;
        help|--help|-h) _wazuh_help ;;
        *)
            echo -e "  ${RED}Unknown wazuh command: ${subcmd}${RESET}"
            echo "  Run 'freq wazuh help' for usage."
            return 1
            ;;
    esac
}

_wazuh_help() {
    freq_header "Wazuh SIEM"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq wazuh <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    status           ${DIM}${_DASH} Wazuh manager status${RESET}"
    freq_line "    deploy <host>    ${DIM}${_DASH} Deploy agent to a host${RESET}"
    freq_line "    agents           ${DIM}${_DASH} List all registered agents${RESET}"
    freq_line "    alerts [--limit N] ${DIM}${_DASH} Show recent alerts${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Config:${RESET} Set WAZUH_HOST, WAZUH_API_USER, WAZUH_API_PASS"
    freq_blank
    freq_footer
}

_wazuh_check_config() {
    if [ -z "${WAZUH_HOST:-}" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} WAZUH_HOST not set. Configure in freq.conf."
        return 1
    fi
    if [ -z "${WAZUH_API_USER:-}" ] || [ -z "${WAZUH_API_PASS:-}" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} WAZUH_API_USER / WAZUH_API_PASS not set."
        return 1
    fi
    return 0
}

_wazuh_auth() {
    # Get JWT token from Wazuh API
    local token
    token=$(curl -s --connect-timeout 10 --max-time 30 -k -X POST \
        "https://${WAZUH_HOST}:${WAZUH_API_PORT}/security/user/authenticate" \
        -u "${WAZUH_API_USER}:${WAZUH_API_PASS}" \
        --connect-timeout 10 --max-time 30 2>/dev/null | grep -o '"jwt":"[^"]*"' | cut -d'"' -f4)

    if [ -z "$token" ]; then
        return 1
    fi
    WAZUH_TOKEN="$token"
    return 0
}

_wazuh_api() {
    local endpoint="$1"
    local method="${2:-GET}"

    [ -z "$WAZUH_TOKEN" ] && _wazuh_auth

    curl -s --connect-timeout 10 --max-time 30 -k -X "$method" \
        "https://${WAZUH_HOST}:${WAZUH_API_PORT}/${endpoint}" \
        -H "Authorization: Bearer ${WAZUH_TOKEN}" \
        --connect-timeout 10 --max-time 30 2>/dev/null
}

_wazuh_status() {
    require_operator || return 1
    _wazuh_check_config || return 1

    freq_header "Wazuh Manager Status"
    freq_blank

    _step_start "Authenticating with Wazuh API"
    if ! _wazuh_auth; then
        _step_fail "auth failed"
        freq_footer
        return 1
    fi
    _step_ok

    # Manager info
    _step_start "Fetching manager info"
    local info
    info=$(_wazuh_api "manager/info")
    if [ -n "$info" ]; then
        _step_ok
        local version
        version=$(echo "$info" | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4)
        freq_line "  Version: ${BOLD}${version:-unknown}${RESET}"
    else
        _step_fail "cannot reach API"
        freq_footer
        return 1
    fi

    # Manager status
    _step_start "Fetching daemon status"
    local mgr_status
    mgr_status=$(_wazuh_api "manager/status")
    if [ -n "$mgr_status" ]; then
        _step_ok
        local running stopped
        running=$(echo "$mgr_status" | grep -o '"running"' | wc -l)
        stopped=$(echo "$mgr_status" | grep -o '"stopped"' | wc -l)
        freq_line "  Daemons: ${GREEN}${running} running${RESET}  ${RED}${stopped} stopped${RESET}"
    else
        _step_warn "no status data"
    fi

    # Agent summary
    _step_start "Agent summary"
    local summary
    summary=$(_wazuh_api "agents/summary/status")
    if [ -n "$summary" ]; then
        _step_ok
        local active disconnected never pending
        active=$(echo "$summary" | grep -o '"active":[0-9]*' | cut -d: -f2)
        disconnected=$(echo "$summary" | grep -o '"disconnected":[0-9]*' | cut -d: -f2)
        never=$(echo "$summary" | grep -o '"never_connected":[0-9]*' | cut -d: -f2)
        pending=$(echo "$summary" | grep -o '"pending":[0-9]*' | cut -d: -f2)
        freq_line "  Agents: ${GREEN}${active:-0} active${RESET}  ${RED}${disconnected:-0} disconnected${RESET}  ${DIM}${never:-0} never${RESET}  ${DIM}${pending:-0} pending${RESET}"
    else
        _step_warn "no summary"
    fi

    freq_blank
    freq_footer
    log "wazuh: status checked"
}

_wazuh_deploy() {
    require_admin || return 1
    require_ssh_key
    _wazuh_check_config || return 1

    local host="${1:-}"
    [ -z "$host" ] && { echo -e "  ${RED}Usage: freq wazuh deploy <host>${RESET}"; return 1; }

    freq_header "Wazuh Agent Deploy ${_DASH} ${host}"
    freq_blank

    local resolved host_ip host_type
    resolved=$(freq_resolve "$host" 2>/dev/null) || die "Cannot resolve: ${host}"
    host_ip=$(echo "$resolved" | awk '{print $1}')
    host_type=$(echo "$resolved" | awk '{print $2}')

    if [ "$host_type" != "linux" ]; then
        freq_line "  ${YELLOW}${_WARN}${RESET} Agent deploy only supports Linux hosts. Type: ${host_type}"
        freq_footer
        return 1
    fi

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would deploy Wazuh agent to ${host} (${host_ip})"
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Steps: add repo, install agent, configure manager, start service"
        freq_footer
        return 0
    fi

    _freq_confirm "Deploy Wazuh agent to ${host} (${host_ip})?" || return 1

    # Check if agent already installed
    _step_start "Check existing agent"
    local existing
    existing=$(freq_ssh "$host" "dpkg -l wazuh-agent 2>/dev/null || rpm -q wazuh-agent 2>/dev/null" 2>/dev/null)
    if echo "$existing" | grep -qi "wazuh-agent"; then
        _step_warn "agent already installed"
        freq_line "  ${DIM}Use 'freq wazuh agents' to check registration status.${RESET}"
        freq_footer
        return 0
    fi
    _step_ok "not installed"

    # Detect package manager
    local pm
    pm=$(freq_ssh "$host" 'command -v apt-get &>/dev/null && echo apt || echo rpm' 2>/dev/null)

    # Deploy agent
    _step_start "Install Wazuh agent (${pm})"
    local install_result
    if [ "$pm" = "apt" ]; then
        install_result=$(freq_ssh "$host" "
            curl -s --connect-timeout 10 --max-time 30 --connect-timeout 10 --max-time 30 https://packages.wazuh.com/key/GPG-KEY-WAZUH | sudo gpg --no-default-keyring --keyring gnupg-ring:/usr/share/keyrings/wazuh.gpg --import 2>/dev/null
            sudo chmod 644 /usr/share/keyrings/wazuh.gpg
            echo 'deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main' | sudo tee /etc/apt/sources.list.d/wazuh.list >/dev/null
            WAZUH_MANAGER='${WAZUH_HOST}' sudo apt-get update -qq && sudo apt-get install -y -qq wazuh-agent 2>&1
        " 2>/dev/null)
    else
        install_result=$(freq_ssh "$host" "
            sudo rpm --import https://packages.wazuh.com/key/GPG-KEY-WAZUH 2>/dev/null
            echo -e '[wazuh]\ngpgcheck=1\ngpgkey=https://packages.wazuh.com/key/GPG-KEY-WAZUH\nenabled=1\nname=EL-\$releasever - Wazuh\nbaseurl=https://packages.wazuh.com/4.x/yum/\nprotect=1' | sudo tee /etc/yum.repos.d/wazuh.repo >/dev/null
            WAZUH_MANAGER='${WAZUH_HOST}' sudo yum install -y wazuh-agent 2>&1
        " 2>/dev/null)
    fi
    if echo "$install_result" | grep -qi "error\|failed"; then
        _step_fail "install failed"
        freq_footer
        return 1
    fi
    _step_ok

    # Configure manager address
    _step_start "Configure manager address"
    freq_ssh "$host" "sudo sed -i 's|<address>.*</address>|<address>${WAZUH_HOST}</address>|' /var/ossec/etc/ossec.conf" 2>/dev/null
    _step_ok

    # Start agent
    _step_start "Start wazuh-agent service"
    if freq_ssh "$host" "sudo systemctl daemon-reload && sudo systemctl enable wazuh-agent && sudo systemctl start wazuh-agent" 2>/dev/null; then
        _step_ok
    else
        _step_fail "start failed"
    fi

    freq_blank
    freq_line "  ${GREEN}${_TICK}${RESET} Wazuh agent deployed to ${host}"
    freq_line "  ${DIM}Agent should auto-register. Check 'freq wazuh agents' in a few minutes.${RESET}"
    freq_footer
    log "wazuh: agent deployed to ${host} (${host_ip})"
}

_wazuh_agents() {
    require_operator || return 1
    _wazuh_check_config || return 1

    freq_header "Wazuh Agents"
    freq_blank

    if ! _wazuh_auth; then
        freq_line "  ${RED}${_CROSS}${RESET} Auth failed"
        freq_footer
        return 1
    fi

    local agents
    agents=$(_wazuh_api "agents?limit=100&sort=-dateAdd")

    if [ -z "$agents" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} Cannot fetch agent list"
        freq_footer
        return 1
    fi

    local agent_ids
    agent_ids=$(echo "$agents" | grep -o '"id":"[^"]*"' | cut -d'"' -f4)

    if [ -z "$agent_ids" ]; then
        freq_line "  ${DIM}No agents registered${RESET}"
        freq_footer
        return 0
    fi

    local total=0
    while IFS= read -r aid; do
        [ -z "$aid" ] && continue
        total=$((total + 1))

        # Extract agent info
        local a_block
        a_block=$(echo "$agents" | grep -o "{[^}]*\"id\":\"${aid}\"[^}]*}")
        local name status ip os version
        name=$(echo "$a_block" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
        status=$(echo "$a_block" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        ip=$(echo "$a_block" | grep -o '"ip":"[^"]*"' | cut -d'"' -f4)
        os=$(echo "$a_block" | grep -o '"os_name":"[^"]*"' | cut -d'"' -f4)
        version=$(echo "$a_block" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)

        local color="${DIM}"
        case "$status" in
            active)       color="${GREEN}" ;;
            disconnected) color="${RED}" ;;
            pending)      color="${YELLOW}" ;;
        esac

        freq_line "  ${color}${_BULLET}${RESET} ${BOLD}${name:-?}${RESET} (${aid})  ${DIM}${ip:-?}  ${os:-?}  ${version:-?}${RESET}"
        freq_line "    Status: ${color}${status:-?}${RESET}"
    done <<< "$agent_ids"

    freq_blank
    freq_line "  ${DIM}Total agents: ${total}${RESET}"
    freq_footer
    log "wazuh: agents listed (${total} total)"
}

_wazuh_alerts() {
    require_operator || return 1
    _wazuh_check_config || return 1

    local limit=20
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --limit|-n) limit="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    freq_header "Wazuh Alerts ${_DASH} last ${limit}"
    freq_blank

    if ! _wazuh_auth; then
        freq_line "  ${RED}${_CROSS}${RESET} Auth failed"
        freq_footer
        return 1
    fi

    local alerts
    alerts=$(_wazuh_api "alerts?limit=${limit}&sort=-timestamp")

    if [ -z "$alerts" ]; then
        freq_line "  ${DIM}No alerts or API error${RESET}"
        freq_footer
        return 1
    fi

    local total_items
    total_items=$(echo "$alerts" | grep -o '"total_affected_items":[0-9]*' | cut -d: -f2)

    if [ "${total_items:-0}" = "0" ]; then
        freq_line "  ${GREEN}${_TICK}${RESET} No alerts"
        freq_footer
        return 0
    fi

    # Parse alert entries
    local timestamps
    timestamps=$(echo "$alerts" | grep -o '"timestamp":"[^"]*"' | cut -d'"' -f4)
    local rules
    rules=$(echo "$alerts" | grep -o '"description":"[^"]*"' | cut -d'"' -f4)
    local levels
    levels=$(echo "$alerts" | grep -o '"level":[0-9]*' | cut -d: -f2)

    # Display as table
    local count=0
    while IFS= read -r ts; do
        [ -z "$ts" ] && continue
        count=$((count + 1))
        local level desc
        level=$(echo "$levels" | sed -n "${count}p")
        desc=$(echo "$rules" | sed -n "${count}p")

        local color="${DIM}"
        [ "${level:-0}" -ge 7 ] && color="${YELLOW}"
        [ "${level:-0}" -ge 10 ] && color="${RED}"

        freq_line "  ${color}L${level:-?}${RESET} ${DIM}${ts}${RESET}"
        freq_line "    ${desc:-no description}"
    done <<< "$timestamps"

    freq_blank
    freq_line "  ${DIM}Showing ${count} of ${total_items:-?} alerts${RESET}"
    freq_footer
    log "wazuh: alerts viewed (${count} shown)"
}
