#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/audit.sh
# Security Audit
#
# Author:  FREQ Project
# -- the part where things get real --
# Commands: cmd_audit
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================
# shellcheck disable=SC2154,SC2155

# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY
# ═══════════════════════════════════════════════════════════════════

cmd_audit() {
    require_operator || return 1
    require_ssh_key

    local target="" audit_all=false group="" brief=false
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --all)      audit_all=true; shift ;;
            -g|--group) group="${2:-}"; shift 2 ;;
            --brief)    brief=true; shift ;;
            --help|-h)  _audit_help; return 0 ;;
            *)          echo -e "  ${RED}Unknown flag: ${1}${RESET}"; return 1 ;;
        esac
    done
    target="${1:-}"

    if [ -z "$target" ] && ! $audit_all && [ -z "$group" ]; then
        _audit_help
        return 1
    fi

    load_hosts

    # Build audit target list
    local -a audit_labels=() audit_ips=() audit_types=()

    if $audit_all; then
        local i
        for ((i=0; i<HOST_COUNT; i++)); do
            case "${HOST_TYPES[$i]}" in
                linux|truenas|pfsense) ;;
                *) continue ;;
            esac
            audit_labels+=("${HOST_LABELS[$i]}")
            audit_ips+=("${HOST_IPS[$i]}")
            audit_types+=("${HOST_TYPES[$i]}")
        done
    elif [ -n "$group" ]; then
        local i
        for ((i=0; i<HOST_COUNT; i++)); do
            [[ "${HOST_GROUPS[$i]}" == *"$group"* ]] || continue
            case "${HOST_TYPES[$i]}" in
                linux|truenas|pfsense) ;;
                *) continue ;;
            esac
            audit_labels+=("${HOST_LABELS[$i]}")
            audit_ips+=("${HOST_IPS[$i]}")
            audit_types+=("${HOST_TYPES[$i]}")
        done
    else
        local resolved
        resolved=$(freq_resolve "$target" 2>/dev/null)
        if [ -z "$resolved" ]; then
            echo -e "  ${RED}Host '${target}' not found.${RESET}"
            return 1
        fi
        local r_ip r_type r_label
        read -r r_ip r_type r_label <<< "$resolved"
        audit_labels+=("$r_label")
        audit_ips+=("$r_ip")
        audit_types+=("$r_type")
    fi

    if [ "${#audit_labels[@]}" -eq 0 ]; then
        echo -e "  ${RED}No auditable hosts found.${RESET}"
        return 1
    fi

    # Log setup
    local log_dir="${FREQ_DATA_DIR}/log"
    mkdir -p "$log_dir" 2>/dev/null
    local log_file="${log_dir}/audit-$(date +%Y%m%d-%H%M).log"

    local total_crit=0 total_high=0 total_med=0 total_low=0 total_pass=0

    freq_header "Security Audit"
    freq_line "  ${DIM}Targets:${RESET} ${#audit_labels[@]} host(s)"
    freq_line "  ${DIM}Log:${RESET} ${log_file}"
    freq_blank

    # ── Audit each host sequentially ──
    local h
    for ((h=0; h<${#audit_labels[@]}; h++)); do
        local ip="${audit_ips[$h]}"
        local label="${audit_labels[$h]}"
        local htype="${audit_types[$h]}"
        local crit=0 high=0 med=0 low=0 hpass=0

        freq_divider "${label} (${ip})"
        echo "=== ${label} (${ip}) === $(date)" >> "$log_file"

        # Skip non-SSH types
        if [ "$htype" = "switch" ] || [ "$htype" = "idrac" ] || [ "$htype" = "external" ]; then
            freq_line "  ${DIM}Skipped (type: ${htype})${RESET}"
            continue
        fi

        # Connectivity check
        if ! ping -c 1 -W 3 "$ip" &>/dev/null; then
            freq_line "  ${RED}CRITICAL${RESET} ${_DASH} Host unreachable (ICMP)"
            echo "CRITICAL -- Host unreachable -- ${label}" >> "$log_file"
            crit=$((crit + 1))
            total_crit=$((total_crit + 1))
            _audit_host_summary "$label" "$crit" "$high" "$med" "$low" "$hpass" "$brief"
            continue
        fi

        # Collect audit data in a single SSH call
        local audit_data
        audit_data=$(freq_ssh "$label" '
            echo "===SSHD==="
            grep -E "^(PermitRootLogin|PasswordAuthentication|X11Forwarding|MaxAuthTries)" /etc/ssh/sshd_config 2>/dev/null
            cat /etc/ssh/sshd_config.d/*.conf 2>/dev/null | grep -E "^(PermitRootLogin|PasswordAuthentication|X11Forwarding|MaxAuthTries)"
            echo "===SUDOERS==="
            sudo cat /etc/sudoers.d/* 2>/dev/null
            echo "===EMPTYPASS==="
            sudo grep -E "^[^:]+:::" /etc/shadow 2>/dev/null | cut -d: -f1
            echo "===SUDOGROUP==="
            getent group sudo 2>/dev/null; getent group wheel 2>/dev/null
            echo "===LISTENING==="
            ss -tlnp 2>/dev/null | grep "0.0.0.0\|:::" | awk "{print \$4}" | sort -u
            echo "===DOCKER==="
            if command -v docker &>/dev/null; then
                sudo docker ps --format "{{.Names}}:{{.Status}}" 2>/dev/null | head -20
                sudo docker ps --filter "status=running" --format "{{.Names}}:{{.Mounts}}" 2>/dev/null | grep "docker.sock" && echo "DOCKERSOCK:YES"
            fi
            echo "===UPDATES==="
            if command -v apt-get &>/dev/null; then
                apt-get -s upgrade 2>/dev/null | grep -c "^Inst" || echo "0"
            fi
            echo "===LASTLOGIN==="
            last -n 20 -i 2>/dev/null | grep -oE "[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+" | sort -u
            echo "===SUID==="
            find / -perm -4000 -type f 2>/dev/null | grep -v "^/usr/bin\|^/usr/sbin\|^/bin\|^/sbin\|^/usr/lib\|^/snap" | head -10
            echo "===WORLDWRITE==="
            find /opt /home /etc -type d -perm -0002 2>/dev/null | head -10
            echo "===HISTORY==="
            for u in $(ls /home/ 2>/dev/null); do
                grep -iE "password|secret|token|api.key|passwd" "/home/$u/.bash_history" 2>/dev/null | head -3 | while read -r hline; do echo "HIST:$u:$hline"; done
            done
            echo "===EXTENDED==="
            echo "GA=$(systemctl is-active qemu-guest-agent 2>/dev/null || echo inactive)"
            echo "NTP=$(timedatectl show --property=NTPSynchronized --value 2>/dev/null || echo unknown)"
            echo "RPCBIND=$(systemctl is-active rpcbind 2>/dev/null || echo inactive)"
            if command -v docker &>/dev/null; then
                echo "DOCKER_INSTALLED=yes"
                if [ -f /etc/docker/daemon.json ] && grep -q max-size /etc/docker/daemon.json 2>/dev/null; then
                    echo "DAEMON_JSON=yes"
                else
                    echo "DAEMON_JSON=no"
                fi
                echo "LATEST=$(sudo docker ps --format "'"'"'{{.Image}}'"'"'" 2>/dev/null | grep -c ":latest" || echo 0)"
            else
                echo "DOCKER_INSTALLED=no"
            fi
            echo "===END==="
        ' 2>/dev/null)

        if [ -z "$audit_data" ]; then
            freq_line "  ${RED}CRITICAL${RESET} ${_DASH} SSH failed"
            echo "CRITICAL -- SSH failed -- ${label}" >> "$log_file"
            crit=$((crit + 1))
            total_crit=$((total_crit + 1))
            _audit_host_summary "$label" "$crit" "$high" "$med" "$low" "$hpass" "$brief"
            continue
        fi

        # Parse audit data section by section
        local section=""
        local root_login_checked=false
        while IFS= read -r line; do
            case "$line" in
                ===*===) section="${line//=/}"; section="${section// /}"; continue ;;
            esac

            case "$section" in
                SSHD)
                    case "$line" in
                        *PermitRootLogin*prohibit-password*|*PermitRootLogin*without-password*|*PermitRootLogin*no*)
                            freq_line "  ${GREEN}${_TICK}${RESET}  PASS ${_DASH} PermitRootLogin restricted"
                            hpass=$((hpass + 1)); root_login_checked=true ;;
                        *PermitRootLogin*yes*)
                            freq_line "  ${RED}CRITICAL${RESET} ${_DASH} PermitRootLogin yes"
                            echo "CRITICAL -- PermitRootLogin yes -- ${label}" >> "$log_file"
                            crit=$((crit + 1)); root_login_checked=true ;;
                        *PasswordAuthentication*yes*)
                            freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} PasswordAuthentication yes"
                            echo "MEDIUM -- PasswordAuth yes -- ${label}" >> "$log_file"
                            med=$((med + 1)) ;;
                        *X11Forwarding*yes*)
                            freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} X11Forwarding yes"
                            echo "MEDIUM -- X11Forwarding yes -- ${label}" >> "$log_file"
                            med=$((med + 1)) ;;
                        *MaxAuthTries*)
                            local tries
                            tries=$(echo "$line" | awk '{print $2}')
                            if [ "${tries:-6}" -gt 3 ] 2>/dev/null; then
                                freq_line "  ${DIM}LOW${RESET}     ${_DASH} MaxAuthTries ${tries} (> 3)"
                                echo "LOW -- MaxAuthTries ${tries} -- ${label}" >> "$log_file"
                                low=$((low + 1))
                            else
                                hpass=$((hpass + 1))
                            fi ;;
                    esac ;;
                SUDOERS)
                    [[ "$line" =~ ^[[:space:]]*# ]] && continue
                    [ -z "$line" ] && continue
                    if [[ "$line" != *"${FREQ_SERVICE_ACCOUNT}"* ]] && [[ "$line" =~ NOPASSWD ]]; then
                        freq_line "  ${RED}HIGH${RESET}    ${_DASH} NOPASSWD sudoers: $(echo "$line" | head -c 60)"
                        echo "HIGH -- NOPASSWD sudoers -- ${label}" >> "$log_file"
                        high=$((high + 1))
                    fi ;;
                EMPTYPASS)
                    if [ -n "$line" ] && [[ ! "$line" =~ ^(nobody|sync|halt|shutdown)$ ]]; then
                        freq_line "  ${RED}CRITICAL${RESET} ${_DASH} Empty password: ${line}"
                        echo "CRITICAL -- Empty password: ${line} -- ${label}" >> "$log_file"
                        crit=$((crit + 1))
                    fi ;;
                SUDOGROUP)
                    if [ -n "$line" ]; then
                        local members
                        members=$(echo "$line" | cut -d: -f4)
                        local IFS=','
                        local m
                        for m in $members; do
                            m=$(echo "$m" | tr -d ' ')
                            [ -z "$m" ] && continue
                            case "$m" in
                                root|svc-admin|sonny-aif|chrisadmin|donmin|jarvis-ai) ;;
                                *)
                                    freq_line "  ${RED}HIGH${RESET}    ${_DASH} Unknown sudo/wheel member: ${m}"
                                    echo "HIGH -- Unknown sudo member: ${m} -- ${label}" >> "$log_file"
                                    high=$((high + 1)) ;;
                            esac
                        done
                        unset IFS
                    fi ;;
                LISTENING)
                    if [ -n "$line" ]; then
                        local port
                        port=$(echo "$line" | grep -oE '[0-9]+$')
                        case "$port" in
                            22|80|443|8006|3000|8080|8081|8096|9090|5432|3306|111) ;;
                            *)
                                if ! $brief; then
                                    freq_line "  ${DIM}LOW${RESET}     ${_DASH} Listening on 0.0.0.0:${port}"
                                fi
                                echo "LOW -- Open port ${port} -- ${label}" >> "$log_file"
                                low=$((low + 1)) ;;
                        esac
                    fi ;;
                DOCKER)
                    if [[ "$line" == *"DOCKERSOCK:YES"* ]]; then
                        freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} docker.sock mounted in container"
                        echo "MEDIUM -- docker.sock exposed -- ${label}" >> "$log_file"
                        med=$((med + 1))
                    fi ;;
                LASTLOGIN)
                    if [ -n "$line" ] && [[ ! "$line" =~ ^10\.25\. ]] && [[ "$line" != "0.0.0.0" ]]; then
                        freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} Login from non-DC01 IP: ${line}"
                        echo "MEDIUM -- External login ${line} -- ${label}" >> "$log_file"
                        med=$((med + 1))
                    fi ;;
                SUID)
                    if [ -n "$line" ]; then
                        freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} SUID outside standard paths: $(basename "$line")"
                        echo "MEDIUM -- SUID: ${line} -- ${label}" >> "$log_file"
                        med=$((med + 1))
                    fi ;;
                WORLDWRITE)
                    if [ -n "$line" ]; then
                        freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} World-writable: ${line}"
                        echo "MEDIUM -- World-writable: ${line} -- ${label}" >> "$log_file"
                        med=$((med + 1))
                    fi ;;
                HISTORY)
                    if [[ "$line" == HIST:* ]]; then
                        local huser
                        huser=$(echo "$line" | cut -d: -f2)
                        freq_line "  ${RED}HIGH${RESET}    ${_DASH} Credentials in history for: ${huser}"
                        echo "HIGH -- Creds in history: ${huser} -- ${label}" >> "$log_file"
                        high=$((high + 1))
                    fi ;;
                EXTENDED)
                    case "$line" in
                        GA=active)
                            freq_line "  ${GREEN}${_TICK}${RESET}  PASS ${_DASH} qemu-guest-agent running"
                            hpass=$((hpass + 1)) ;;
                        GA=*)
                            freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} qemu-guest-agent not running"
                            echo "MEDIUM -- guest agent not running -- ${label}" >> "$log_file"
                            med=$((med + 1)) ;;
                        NTP=yes)
                            freq_line "  ${GREEN}${_TICK}${RESET}  PASS ${_DASH} NTP synchronized"
                            hpass=$((hpass + 1)) ;;
                        NTP=*)
                            freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} NTP NOT synchronized"
                            echo "MEDIUM -- NTP not synced -- ${label}" >> "$log_file"
                            med=$((med + 1)) ;;
                        RPCBIND=active)
                            freq_line "  ${YELLOW}MEDIUM${RESET}  ${_DASH} rpcbind running"
                            echo "MEDIUM -- rpcbind active -- ${label}" >> "$log_file"
                            med=$((med + 1)) ;;
                        RPCBIND=*)
                            freq_line "  ${GREEN}${_TICK}${RESET}  PASS ${_DASH} rpcbind disabled"
                            hpass=$((hpass + 1)) ;;
                        DOCKER_INSTALLED=yes)
                            ;; # handled by DAEMON_JSON/LATEST
                        DOCKER_INSTALLED=no)
                            ;; # skip docker checks
                        DAEMON_JSON=yes)
                            freq_line "  ${GREEN}${_TICK}${RESET}  PASS ${_DASH} Docker log rotation configured"
                            hpass=$((hpass + 1)) ;;
                        DAEMON_JSON=no)
                            freq_line "  ${RED}HIGH${RESET}    ${_DASH} No Docker log rotation (daemon.json)"
                            echo "HIGH -- No docker log rotation -- ${label}" >> "$log_file"
                            high=$((high + 1)) ;;
                        LATEST=*)
                            local lcount="${line#LATEST=}"
                            if [ "${lcount:-0}" -gt 0 ] 2>/dev/null; then
                                freq_line "  ${RED}HIGH${RESET}    ${_DASH} ${lcount} container(s) using :latest tag"
                                echo "HIGH -- ${lcount} :latest tags -- ${label}" >> "$log_file"
                                high=$((high + 1))
                            else
                                freq_line "  ${GREEN}${_TICK}${RESET}  PASS ${_DASH} No :latest image tags"
                                hpass=$((hpass + 1))
                            fi ;;
                    esac ;;
            esac
        done <<< "$audit_data"

        # Default PermitRootLogin check
        if ! $root_login_checked; then
            freq_line "  ${GREEN}${_TICK}${RESET}  PASS ${_DASH} PermitRootLogin (default)"
            hpass=$((hpass + 1))
        fi

        _audit_host_summary "$label" "$crit" "$high" "$med" "$low" "$hpass" "$brief"
        total_crit=$((total_crit + crit))
        total_high=$((total_high + high))
        total_med=$((total_med + med))
        total_low=$((total_low + low))
        total_pass=$((total_pass + hpass))
    done

    # ── Fleet Summary ──
    freq_blank
    freq_divider "Audit Summary"
    freq_line "  ${RED}CRITICAL: ${total_crit}${RESET}  |  ${RED}HIGH: ${total_high}${RESET}  |  ${YELLOW}MEDIUM: ${total_med}${RESET}  |  LOW: ${total_low}  |  ${GREEN}PASS: ${total_pass}${RESET}"
    freq_line "  ${DIM}Log: ${log_file}${RESET}"
    freq_blank
    freq_footer

    log "audit: ${#audit_labels[@]} host(s) -- ${total_crit}C ${total_high}H ${total_med}M ${total_low}L ${total_pass}P"

    [ "$total_crit" -gt 0 ] && return 1
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

_audit_host_summary() {
    local label="$1" crit="$2" high="$3" med="$4" low="$5" hpass="$6" brief="$7"
    freq_blank
    if [ "$brief" = "true" ]; then
        local sev=""
        [ "$crit" -gt 0 ] && sev="${RED}${crit}C${RESET} "
        [ "$high" -gt 0 ] && sev="${sev}${RED}${high}H${RESET} "
        [ "$med" -gt 0 ] && sev="${sev}${YELLOW}${med}M${RESET} "
        [ "$low" -gt 0 ] && sev="${sev}${low}L "
        echo -e "  ${DIM}${label}:${RESET} ${sev}${GREEN}${hpass}P${RESET}"
    else
        echo -e "  ${DIM}${label}: ${crit} critical, ${high} high, ${med} medium, ${low} low, ${hpass} pass${RESET}"
    fi
}

_audit_help() {
    freq_header "Security Audit"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq audit <host> | --all | -g <group>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Options:${RESET}"
    freq_line "    --all         ${DIM}${_DASH} Audit all SSH-capable hosts${RESET}"
    freq_line "    -g, --group   ${DIM}${_DASH} Audit hosts in a specific group${RESET}"
    freq_line "    --brief       ${DIM}${_DASH} Compact summary per host${RESET}"
    freq_line "    --help, -h    ${DIM}${_DASH} Show this help${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Checks:${RESET}"
    freq_line "    SSH config     ${DIM}${_DASH} PermitRootLogin, PasswordAuth, X11${RESET}"
    freq_line "    Sudoers        ${DIM}${_DASH} NOPASSWD rules, wildcard access${RESET}"
    freq_line "    Passwords      ${DIM}${_DASH} Empty/locked password accounts${RESET}"
    freq_line "    Ports          ${DIM}${_DASH} Services listening on 0.0.0.0${RESET}"
    freq_line "    Docker         ${DIM}${_DASH} Socket exposure, :latest tags, log rotation${RESET}"
    freq_line "    System         ${DIM}${_DASH} NTP, guest agent, rpcbind, SUID, world-writable${RESET}"
    freq_line "    History        ${DIM}${_DASH} Credentials in bash_history${RESET}"
    freq_blank
    freq_footer
}
