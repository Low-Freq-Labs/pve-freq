#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/idrac.sh
# iDRAC Remote Management
#
# Author:  FREQ Project / JARVIS
#
# Dell iDRAC management via racadm over SSH
# Supports iDRAC 7 (T620), 8 (R530), 9
#
# -- hardware doesn't sleep. neither do we. --
#
# Commands: cmd_idrac
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# iDRAC HOST REGISTRY
# Hardcoded — these are out-of-band management controllers,
# not regular fleet hosts. resolve.sh has aliases for these.
# ═══════════════════════════════════════════════════════════════════

# Known iDRAC labels and their descriptions
# IPs come from resolve.sh aliases (idrac-r530, idrac-t620)
declare -A _IDRAC_DESC=(
    [r530]="Dell PowerEdge R530 (pve02)"
    [t620]="Dell PowerEdge T620 (pve01)"
)

# ═══════════════════════════════════════════════════════════════════
# TARGET RESOLUTION
# ═══════════════════════════════════════════════════════════════════

# _idrac_resolve <label>
# Sets: _IDRAC_IP, _IDRAC_NAME, _IDRAC_RESOLVE, _IDRAC_DESC_STR
_idrac_resolve() {
    local label="${1:-}"

    if [ -z "$label" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  No iDRAC label specified"
        echo "      Known labels: r530, t620"
        return 1
    fi

    # Map short labels to resolve aliases
    local resolve_alias=""
    case "$label" in
        r530|idrac-r530)  resolve_alias="idrac-r530" ;;
        t620|idrac-t620)  resolve_alias="idrac-t620" ;;
        *)
            # Try as direct resolve alias
            resolve_alias="$label"
            ;;
    esac

    local resolved
    resolved=$(freq_resolve "$resolve_alias" 2>/dev/null)

    if [ -z "$resolved" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Unknown iDRAC: $label"
        echo "      Known labels: r530, t620"
        return 1
    fi

    _IDRAC_IP=$(echo "$resolved" | awk '{print $1}')
    _IDRAC_NAME=$(echo "$resolved" | awk '{print $3}')
    _IDRAC_RESOLVE="$resolve_alias"

    # Short label for description lookup
    local short_label="${label#idrac-}"
    _IDRAC_DESC_STR="${_IDRAC_DESC[$short_label]:-$_IDRAC_NAME}"
}

# _idrac_ssh <command>
# SSH to iDRAC using resolve label — freq_ssh handles legacy crypto
_idrac_ssh() {
    freq_ssh "$_IDRAC_RESOLVE" "$*"
}

# ═══════════════════════════════════════════════════════════════════
# COMMAND DISPATCHER
# ═══════════════════════════════════════════════════════════════════

cmd_idrac() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)
            [ $# -lt 1 ] && { echo "Usage: freq idrac status <label>"; echo "Labels: r530, t620"; return 1; }
            _idrac_resolve "$1" || return 1
            _idrac_status
            ;;
        sensors)
            [ $# -lt 1 ] && { echo "Usage: freq idrac sensors <label>"; echo "Labels: r530, t620"; return 1; }
            _idrac_resolve "$1" || return 1
            _idrac_sensors
            ;;
        sel)
            [ $# -lt 1 ] && { echo "Usage: freq idrac sel <label>"; echo "Labels: r530, t620"; return 1; }
            _idrac_resolve "$1" || return 1
            _idrac_sel
            ;;
        power)
            [ $# -lt 1 ] && { echo "Usage: freq idrac power <label> [status|cycle|on|off]"; return 1; }
            _idrac_resolve "$1" || return 1
            shift
            _idrac_power "${1:-status}"
            ;;
        console)
            [ $# -lt 1 ] && { echo "Usage: freq idrac console <label>"; echo "Labels: r530, t620"; return 1; }
            _idrac_resolve "$1" || return 1
            _idrac_console
            ;;
        check)
            _idrac_check "$@"
            ;;
        all)
            _idrac_all
            ;;
        help|--help|-h)
            echo "Usage: freq idrac <command> <label>"
            echo ""
            echo "  status <label>      System info + power state"
            echo "  sensors <label>     Temperature + fan + voltage sensors"
            echo "  sel <label>         System Event Log (last 20 entries)"
            echo "  power <label> [status|cycle|on|off]  Power management"
            echo "  console <label>     Show web console URL"
            echo "  check [label]       Connectivity + health check (all if no label)"
            echo "  all                 Status summary of all known iDRACs"
            echo ""
            echo "Labels: r530, t620"
            ;;
        *)
            echo -e "      ${RED}${_CROSS}${RESET}  Unknown subcommand: $subcmd"
            echo "      Run 'freq idrac help' for usage."
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# STATUS — System info + power state
# ═══════════════════════════════════════════════════════════════════
_idrac_status() {
    freq_header "iDRAC Status: $_IDRAC_DESC_STR"

    echo -e "      ${BOLD}System Info${RESET}"

    local sysinfo
    sysinfo=$(_idrac_ssh "racadm getsysinfo" 2>&1)
    if [ $? -ne 0 ] || [ -z "$sysinfo" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot reach iDRAC at $_IDRAC_IP"
        freq_footer
        return 1
    fi

    # Parse key fields from racadm output
    local model="" service_tag="" bios_ver="" firmware="" power_state="" hostname=""

    while IFS= read -r line; do
        case "$line" in
            *"System Model"*)    model=$(echo "$line" | sed 's/.*= *//') ;;
            *"Service Tag"*)     service_tag=$(echo "$line" | sed 's/.*= *//') ;;
            *"BIOS Version"*)    bios_ver=$(echo "$line" | sed 's/.*= *//') ;;
            *"Firmware Version"*) firmware=$(echo "$line" | sed 's/.*= *//') ;;
            *"Power Status"*)    power_state=$(echo "$line" | sed 's/.*= *//') ;;
            *"Host Name"*)       hostname=$(echo "$line" | sed 's/.*= *//') ;;
        esac
    done <<< "$sysinfo"

    printf "      %-18s %s\n" "Model:" "${model:-unknown}"
    printf "      %-18s %s\n" "Service Tag:" "${service_tag:-unknown}"
    printf "      %-18s %s\n" "BIOS:" "${bios_ver:-unknown}"
    printf "      %-18s %s\n" "iDRAC FW:" "${firmware:-unknown}"
    printf "      %-18s %s\n" "Host Name:" "${hostname:-unknown}"
    printf "      %-18s %s\n" "iDRAC IP:" "$_IDRAC_IP"

    echo -ne "      Power:             "
    if [[ "${power_state,,}" == *"on"* ]]; then
        echo -e "${GREEN}ON${RESET}"
    elif [[ "${power_state,,}" == *"off"* ]]; then
        echo -e "${RED}OFF${RESET}"
    else
        echo -e "${YELLOW}${power_state:-unknown}${RESET}"
    fi

    freq_footer
    log "idrac: status viewed ($_IDRAC_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# SENSORS — Temperature, fan, and voltage readings
# ═══════════════════════════════════════════════════════════════════
_idrac_sensors() {
    freq_header "iDRAC Sensors: $_IDRAC_DESC_STR"

    local sensor_output
    sensor_output=$(_idrac_ssh "racadm getsensorinfo" 2>&1)
    if [ $? -ne 0 ] || [ -z "$sensor_output" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve sensor data"
        freq_footer
        return 1
    fi

    # Parse and color-code sensor output
    local section=""
    local line_count=0

    while IFS= read -r line; do
        # Detect section headers
        if [[ "$line" == *"Temp"*"Reading"* ]] || [[ "$line" == *"Temperature"* && "$line" == *"Status"* ]]; then
            echo ""
            echo -e "      ${BOLD}Temperature Sensors:${RESET}"
            section="temp"
            continue
        fi
        if [[ "$line" == *"Fan"*"Reading"* ]] || [[ "$line" == *"Fan"* && "$line" == *"RPM"* ]]; then
            echo ""
            echo -e "      ${BOLD}Fan Sensors:${RESET}"
            section="fan"
            continue
        fi
        if [[ "$line" == *"Voltage"*"Reading"* ]]; then
            echo ""
            echo -e "      ${BOLD}Voltage Sensors:${RESET}"
            section="volt"
            continue
        fi

        # Skip empty lines and headers
        [ -z "$line" ] && continue
        [[ "$line" == *"---"* ]] && continue
        [[ "$line" == *"Sensor"* && "$line" == *"Status"* ]] && continue

        # Color-code based on status
        if [[ "$line" == *"Ok"* ]] || [[ "$line" == *"Normal"* ]]; then
            echo -e "        ${GREEN}${line}${RESET}"
        elif [[ "$line" == *"Warning"* ]] || [[ "$line" == *"Warn"* ]]; then
            echo -e "        ${YELLOW}${line}${RESET}"
        elif [[ "$line" == *"Critical"* ]] || [[ "$line" == *"Fail"* ]]; then
            echo -e "        ${RED}${line}${RESET}"
        elif [ -n "$section" ]; then
            echo "        $line"
        fi

        line_count=$((line_count + 1))
        [ $line_count -gt 60 ] && { echo -e "        ${DIM}(truncated at 60 lines)${RESET}"; break; }
    done <<< "$sensor_output"

    freq_footer
    log "idrac: sensors viewed ($_IDRAC_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# SEL — System Event Log (last 20 entries)
# ═══════════════════════════════════════════════════════════════════
_idrac_sel() {
    freq_header "iDRAC System Event Log: $_IDRAC_DESC_STR"

    local sel_output
    sel_output=$(_idrac_ssh "racadm getsel" 2>&1)
    if [ $? -ne 0 ] || [ -z "$sel_output" ]; then
        echo -e "      ${RED}${_CROSS}${RESET}  Cannot retrieve SEL"
        freq_footer
        return 1
    fi

    # Show last 20 entries, color-code severity
    local count=0
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        [[ "$line" == *"Record"* && "$line" == *"Date"* ]] && continue

        if [[ "$line" == *"Critical"* ]] || [[ "$line" == *"Error"* ]] || [[ "$line" == *"Failure"* ]]; then
            echo -e "      ${RED}${line}${RESET}"
        elif [[ "$line" == *"Warning"* ]]; then
            echo -e "      ${YELLOW}${line}${RESET}"
        else
            echo "      $line"
        fi

        count=$((count + 1))
        [ $count -ge 20 ] && { echo -e "      ${DIM}(showing last 20 entries)${RESET}"; break; }
    done <<< "$(echo "$sel_output" | tail -25)"

    freq_footer
    log "idrac: SEL viewed ($_IDRAC_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# POWER — Power management (status, cycle, on, off)
# ═══════════════════════════════════════════════════════════════════
_idrac_power() {
    local action="${1:-status}"
    local dry_run="${DRY_RUN:-false}"

    case "$action" in
        status)
            echo -ne "      ${_IDRAC_DESC_STR} power: "
            local pstate
            pstate=$(_idrac_ssh "racadm serveraction powerstatus" 2>&1)
            if [[ "$pstate" == *"ON"* ]]; then
                echo -e "${GREEN}ON${RESET}"
            elif [[ "$pstate" == *"OFF"* ]]; then
                echo -e "${RED}OFF${RESET}"
            else
                echo -e "${YELLOW}${pstate:-unknown}${RESET}"
            fi
            ;;
        cycle)
            if [ "$dry_run" = "true" ]; then
                echo -e "      ${YELLOW}[DRY-RUN]${RESET} Would power cycle $_IDRAC_DESC_STR"
                return 0
            fi
            # Protected operation — power cycling a server is tier 4
            if ! require_protected "iDRAC power cycle" "$_IDRAC_IP" \
                "Power cycling ${_IDRAC_DESC_STR} will cause downtime for all VMs on this node" \
                "Ensure VMs are migrated or shut down first"; then
                return 1
            fi
            echo -e "      ${YELLOW}Sending power cycle to $_IDRAC_DESC_STR...${RESET}"
            local result
            result=$(_idrac_ssh "racadm serveraction powercycle" 2>&1)
            if [ $? -eq 0 ]; then
                echo -e "      ${GREEN}${_TICK}${RESET}  Power cycle initiated"
                log "idrac: power cycle $_IDRAC_NAME ($_IDRAC_IP)"
            else
                echo -e "      ${RED}${_CROSS}${RESET}  Power cycle failed: $result"
                return 1
            fi
            ;;
        on)
            if [ "$dry_run" = "true" ]; then
                echo -e "      ${YELLOW}[DRY-RUN]${RESET} Would power on $_IDRAC_DESC_STR"
                return 0
            fi
            echo -e "      ${YELLOW}Powering on $_IDRAC_DESC_STR...${RESET}"
            local result
            result=$(_idrac_ssh "racadm serveraction powerup" 2>&1)
            if [ $? -eq 0 ]; then
                echo -e "      ${GREEN}${_TICK}${RESET}  Power on initiated"
                log "idrac: power on $_IDRAC_NAME ($_IDRAC_IP)"
            else
                echo -e "      ${RED}${_CROSS}${RESET}  Power on failed: $result"
                return 1
            fi
            ;;
        off)
            if [ "$dry_run" = "true" ]; then
                echo -e "      ${YELLOW}[DRY-RUN]${RESET} Would power off $_IDRAC_DESC_STR"
                return 0
            fi
            # Protected — powering off kills all VMs
            if ! require_protected "iDRAC power off" "$_IDRAC_IP" \
                "Powering off ${_IDRAC_DESC_STR} will immediately kill all VMs on this node" \
                "Migrate VMs before powering off"; then
                return 1
            fi
            echo -e "      ${YELLOW}Powering off $_IDRAC_DESC_STR...${RESET}"
            local result
            result=$(_idrac_ssh "racadm serveraction powerdown" 2>&1)
            if [ $? -eq 0 ]; then
                echo -e "      ${GREEN}${_TICK}${RESET}  Power off initiated"
                log "idrac: power off $_IDRAC_NAME ($_IDRAC_IP)"
            else
                echo -e "      ${RED}${_CROSS}${RESET}  Power off failed: $result"
                return 1
            fi
            ;;
        *)
            echo "Usage: freq idrac power <label> [status|cycle|on|off]"
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# CONSOLE — Show web console URL
# ═══════════════════════════════════════════════════════════════════
_idrac_console() {
    echo ""
    echo -e "      ${BOLD}${_IDRAC_DESC_STR}${RESET}"
    echo -e "      Web Console:  https://${_IDRAC_IP}"
    echo ""
    log "idrac: console URL displayed ($_IDRAC_NAME)"
}

# ═══════════════════════════════════════════════════════════════════
# CHECK — Connectivity + health check
# ═══════════════════════════════════════════════════════════════════
_idrac_check() {
    local labels=("$@")
    if [ ${#labels[@]} -eq 0 ]; then
        labels=("r530" "t620")
    fi

    freq_header "iDRAC Health Check"

    local total_pass=0 total_fail=0

    for label in "${labels[@]}"; do
        _idrac_resolve "$label" 2>/dev/null || continue

        echo -e "    ${_ARROW} ${BOLD}${_IDRAC_DESC_STR}${RESET} (${_IDRAC_IP})"

        local pass=0 fail=0

        # 1. Ping
        echo -ne "        Ping:    "
        if ping -c 1 -W 3 "$_IDRAC_IP" &>/dev/null; then
            echo -e "${GREEN}OK${RESET}"
            pass=$((pass + 1))
        else
            echo -e "${RED}FAIL${RESET}"
            fail=$((fail + 1))
            echo -e "        ${DIM}(skipping SSH — host unreachable)${RESET}"
            total_fail=$((total_fail + fail))
            echo ""
            continue
        fi

        # 2. SSH + racadm
        echo -ne "        SSH:     "
        local sysinfo
        sysinfo=$(_idrac_ssh "racadm getsysinfo" 2>&1)
        if [ $? -eq 0 ] && [ -n "$sysinfo" ]; then
            echo -e "${GREEN}OK${RESET}"
            pass=$((pass + 1))

            # Parse power state
            local power_state=""
            power_state=$(echo "$sysinfo" | grep -i "Power Status" | sed 's/.*= *//')
            echo -ne "        Power:   "
            if [[ "${power_state,,}" == *"on"* ]]; then
                echo -e "${GREEN}ON${RESET}"
                pass=$((pass + 1))
            elif [[ "${power_state,,}" == *"off"* ]]; then
                echo -e "${RED}OFF${RESET}"
                fail=$((fail + 1))
            else
                echo -e "${YELLOW}${power_state:-unknown}${RESET}"
            fi
        else
            echo -e "${RED}FAIL${RESET}"
            fail=$((fail + 1))
            # Show error hint
            if [[ "$sysinfo" == *"Permission denied"* ]]; then
                echo -e "        ${DIM}(auth failed — FREQ key may not be deployed to this iDRAC)${RESET}"
            elif [[ "$sysinfo" == *"Connection refused"* ]]; then
                echo -e "        ${DIM}(connection refused — iDRAC SSH may be disabled)${RESET}"
            fi
        fi

        echo -e "        Result:  ${pass} pass, ${fail} fail"
        echo ""

        total_pass=$((total_pass + pass))
        total_fail=$((total_fail + fail))
    done

    local grand_total=$((total_pass + total_fail))
    if [ $total_fail -gt 0 ]; then
        echo -e "      ${RED}Overall: ${total_pass}/${grand_total} pass${RESET}"
    else
        echo -e "      ${GREEN}Overall: ${total_pass}/${grand_total} pass${RESET}"
    fi

    freq_footer
    log "idrac: health check — ${total_pass}/${grand_total} pass, ${total_fail} fail"
}

# ═══════════════════════════════════════════════════════════════════
# ALL — Status summary of all known iDRACs
# ═══════════════════════════════════════════════════════════════════
_idrac_all() {
    freq_header "iDRAC Fleet Overview"

    for label in r530 t620; do
        _idrac_resolve "$label" 2>/dev/null || continue

        echo -e "    ${_ARROW} ${BOLD}${_IDRAC_DESC_STR}${RESET} (${_IDRAC_IP})"

        local sysinfo
        sysinfo=$(_idrac_ssh "racadm getsysinfo" 2>&1)

        if [ $? -ne 0 ] || [ -z "$sysinfo" ]; then
            echo -e "        ${RED}${_CROSS} Unreachable${RESET}"
            echo ""
            continue
        fi

        local model="" power_state="" firmware=""
        while IFS= read -r line; do
            case "$line" in
                *"System Model"*)     model=$(echo "$line" | sed 's/.*= *//') ;;
                *"Power Status"*)     power_state=$(echo "$line" | sed 's/.*= *//') ;;
                *"Firmware Version"*) firmware=$(echo "$line" | sed 's/.*= *//') ;;
            esac
        done <<< "$sysinfo"

        printf "        Model: %-30s  FW: %s\n" "${model:-unknown}" "${firmware:-unknown}"
        echo -ne "        Power: "
        if [[ "${power_state,,}" == *"on"* ]]; then
            echo -e "${GREEN}ON${RESET}"
        else
            echo -e "${RED}${power_state:-unknown}${RESET}"
        fi
        echo ""
    done

    freq_footer
    log "idrac: fleet overview viewed"
}
