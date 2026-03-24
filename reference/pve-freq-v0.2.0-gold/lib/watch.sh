#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/watch.sh
# Watch Daemon
#
# Author:  FREQ Project
# -- silent guardian, watchful protector --
# Commands: cmd_watch
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================
# shellcheck disable=SC2154

# Watch paths — use FREQ_DATA_DIR for portability
WATCH_STATE="${FREQ_DATA_DIR}/log/watch.state"
WATCH_LOG="${FREQ_DATA_DIR}/log/watch.log"
WATCH_ALERTS="${FREQ_DATA_DIR}/log/watch-alerts.log"
WATCH_CRON_TAG="# freq-watch-cron"

# ═══════════════════════════════════════════════════════════════════
# MAIN DISPATCH
# ═══════════════════════════════════════════════════════════════════

cmd_watch() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        start)    _watch_start "$@" ;;
        stop)     _watch_stop ;;
        run)      _watch_run ;;
        status)   _watch_status ;;
        alerts)   _watch_alerts "$@" ;;
        help|--help|-h) _watch_help ;;
        *)
            echo -e "  ${RED}Unknown watch command: ${subcmd}${RESET}"
            echo "  Run 'freq watch help' for usage."
            return 1
            ;;
    esac
}

_watch_help() {
    freq_header "Watch Daemon"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq watch <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    start          ${DIM}${_DASH} Install cron job (every 15 min)${RESET}"
    freq_line "    stop           ${DIM}${_DASH} Remove cron job${RESET}"
    freq_line "    run            ${DIM}${_DASH} Run one check cycle (called by cron)${RESET}"
    freq_line "    status         ${DIM}${_DASH} Show daemon status and host summary${RESET}"
    freq_line "    alerts         ${DIM}${_DASH} View alert history${RESET}"
    freq_line "    alerts --clear ${DIM}${_DASH} Clear all alerts (admin)${RESET}"
    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# freq watch start — install cron
# ═══════════════════════════════════════════════════════════════════

_watch_start() {
    require_admin || return 1

    # Ensure log directory exists
    mkdir -p "${FREQ_DATA_DIR}/log" 2>/dev/null

    # Determine freq path for cron
    local freq_path="${FREQ_DIR}/freq"
    [ ! -x "$freq_path" ] && freq_path=$(command -v freq 2>/dev/null || echo "/usr/local/bin/freq")

    local cron_line="*/15 * * * * ${freq_path} watch run >> ${WATCH_LOG} 2>&1 ${WATCH_CRON_TAG}"

    if crontab -l 2>/dev/null | grep -q "$WATCH_CRON_TAG"; then
        echo -e "  ${YELLOW}${_WARN}${RESET} Watch cron already installed."
        return 0
    fi

    (crontab -l 2>/dev/null; echo "$cron_line") | crontab -

    # Initialize state file
    [ -f "$WATCH_STATE" ] || echo "" > "$WATCH_STATE"
    [ -f "$WATCH_ALERTS" ] || touch "$WATCH_ALERTS"

    echo -e "  ${GREEN}${_TICK}${RESET} Watch cron installed (every 15 minutes)"
    log "watch: started by $(whoami)"
}

# ═══════════════════════════════════════════════════════════════════
# freq watch stop — remove cron
# ═══════════════════════════════════════════════════════════════════

_watch_stop() {
    require_admin || return 1

    if crontab -l 2>/dev/null | grep -q "$WATCH_CRON_TAG"; then
        crontab -l 2>/dev/null | grep -v "$WATCH_CRON_TAG" | crontab -
        echo -e "  ${GREEN}${_TICK}${RESET} Watch cron removed"
    else
        echo -e "  ${DIM}No watch cron found${RESET}"
    fi
    log "watch: stopped by $(whoami)"
}

# ═══════════════════════════════════════════════════════════════════
# freq watch run — one monitoring cycle (called by cron)
# ═══════════════════════════════════════════════════════════════════

_watch_run() {
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M')
    local alert_count=0
    local new_state=""

    [ ! -f "$HOSTS_FILE" ] && return 1
    mkdir -p "${FREQ_DATA_DIR}/log" 2>/dev/null

    load_hosts

    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        local ip="${HOST_IPS[$i]}"
        local label="${HOST_LABELS[$i]}"
        local htype="${HOST_TYPES[$i]}"
        local groups="${HOST_GROUPS[$i]}"
        local status="OK" detail=""

        case "$htype" in
            linux)
                # SSH connectivity check
                if freq_ssh "$label" "echo OK" &>/dev/null; then
                    # Disk check
                    local disk_warn
                    disk_warn=$(freq_ssh "$label" "df -h 2>/dev/null | awk 'NR>1{gsub(/%/,\"\",\$5); if(\$5+0>85) print \$6\"=\"\$5\"%\"}'" 2>/dev/null)
                    if [ -n "$disk_warn" ]; then
                        status="WARN"
                        detail="disk: ${disk_warn}"
                    fi

                    # Docker check (if docker group)
                    if [[ "$groups" == *docker* ]]; then
                        local running
                        running=$(freq_ssh "$label" "sudo docker ps -q 2>/dev/null | wc -l" 2>/dev/null)
                        running="${running:-0}"
                        local prev_count
                        prev_count=$(echo "$new_state" | grep "^${label}:docker:" | cut -d: -f3)
                        if [ -n "$prev_count" ] && [ "$running" -lt "$prev_count" ] 2>/dev/null; then
                            status="ALERT"
                            detail="containers: was ${prev_count}, now ${running}"
                        fi
                        new_state="${new_state}${label}:docker:${running}\n"
                    fi

                    # Load check
                    local load_data
                    load_data=$(freq_ssh "$label" 'nproc; cat /proc/loadavg' 2>/dev/null)
                    if [ -n "$load_data" ]; then
                        local cores load1 threshold
                        cores=$(echo "$load_data" | head -1)
                        load1=$(echo "$load_data" | tail -1 | awk '{print $1}')
                        threshold=$((cores * 2))
                        if [ "$(echo "${load1} > ${threshold}" | bc 2>/dev/null)" = "1" ] 2>/dev/null; then
                            [ "$status" = "OK" ] && status="WARN"
                            detail="${detail:+${detail}, }load: ${load1} (${cores} cores)"
                        fi
                    fi
                else
                    status="DOWN"
                    detail="SSH unreachable"
                fi
                ;;

            pfsense)
                if ping -c 1 -W 3 "$ip" &>/dev/null; then
                    status="OK"
                else
                    status="DOWN"
                    detail="ICMP unreachable"
                fi
                ;;

            truenas)
                if ping -c 1 -W 3 "$ip" &>/dev/null; then
                    # Check pools via SSH
                    local pool_health
                    pool_health=$(freq_ssh "$label" "sudo zpool status -x 2>/dev/null" 2>/dev/null)
                    if [ -n "$pool_health" ]; then
                        if echo "$pool_health" | grep -qi "DEGRADED\|FAULTED"; then
                            status="ALERT"
                            detail="pool: $(echo "$pool_health" | grep -E "DEGRADED|FAULTED" | head -1)"
                        fi
                    fi
                    # Check alerts
                    local alert_ct
                    alert_ct=$(freq_ssh "$label" 'sudo midclt call alert.list 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null' 2>/dev/null)
                    if [ "${alert_ct:-0}" -gt 0 ] 2>/dev/null; then
                        [ "$status" = "OK" ] && status="WARN"
                        detail="${detail:+${detail}, }alerts: ${alert_ct}"
                    fi
                else
                    status="DOWN"
                    detail="ICMP unreachable"
                fi
                ;;

            switch)
                if ping -c 1 -W 3 "$ip" &>/dev/null; then
                    status="OK"
                else
                    status="DOWN"
                    detail="ICMP unreachable"
                fi
                ;;

            *) continue ;;  # Skip idrac, external, etc.
        esac

        new_state="${new_state}${label}:status:${status}\n"

        # Log state changes (alert on non-OK transitions)
        if [ "$status" != "OK" ]; then
            local prev_status
            prev_status=$(grep "^${label}:status:" "$WATCH_STATE" 2>/dev/null | cut -d: -f3)
            if [ "$prev_status" != "$status" ]; then
                local alert_line="${timestamp} | ${label} (${ip}) | ${status} | ${detail:-no detail}"
                echo "$alert_line" >> "$WATCH_ALERTS"
                echo "$alert_line" >> "$WATCH_LOG"
                alert_count=$((alert_count + 1))
            fi
        fi
    done

    # Save new state
    echo -e "$new_state" > "$WATCH_STATE"

    if [ "$alert_count" -gt 0 ]; then
        echo "${timestamp} -- ${alert_count} new alert(s)" >> "$WATCH_LOG"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# freq watch status — show daemon state
# ═══════════════════════════════════════════════════════════════════

_watch_status() {
    freq_header "Watch Status"
    freq_blank

    # Cron check
    if crontab -l 2>/dev/null | grep -q "$WATCH_CRON_TAG"; then
        freq_line "  ${GREEN}${_TICK}${RESET} Watch daemon: ${GREEN}RUNNING${RESET} (cron every 15 min)"
    else
        freq_line "  ${RED}${_CROSS}${RESET} Watch daemon: ${RED}STOPPED${RESET}"
    fi

    # Last check time
    if [ -f "$WATCH_LOG" ]; then
        local last_check
        last_check=$(tail -1 "$WATCH_LOG" 2>/dev/null | head -c 16)
        freq_line "  ${DIM}Last check: ${last_check:-never}${RESET}"
    else
        freq_line "  ${DIM}Last check: never${RESET}"
    fi

    # Alert count
    if [ -f "$WATCH_ALERTS" ] && [ -s "$WATCH_ALERTS" ]; then
        local unacked
        unacked=$(wc -l < "$WATCH_ALERTS" 2>/dev/null)
        freq_line "  ${YELLOW}${_WARN}${RESET} Unacknowledged alerts: ${unacked}"
    else
        freq_line "  ${GREEN}${_TICK}${RESET} No unacknowledged alerts"
    fi

    # Host state summary
    if [ -f "$WATCH_STATE" ] && [ -s "$WATCH_STATE" ]; then
        local down_count warn_count alert_st_count ok_count
        down_count=$(grep -c ":status:DOWN" "$WATCH_STATE" 2>/dev/null || echo 0)
        warn_count=$(grep -c ":status:WARN" "$WATCH_STATE" 2>/dev/null || echo 0)
        alert_st_count=$(grep -c ":status:ALERT" "$WATCH_STATE" 2>/dev/null || echo 0)
        ok_count=$(grep -c ":status:OK" "$WATCH_STATE" 2>/dev/null || echo 0)
        freq_blank
        freq_line "  Hosts: ${GREEN}${ok_count} OK${RESET}  ${YELLOW}${warn_count} WARN${RESET}  ${RED}${alert_st_count} ALERT${RESET}  ${RED}${down_count} DOWN${RESET}"

        # Show non-OK hosts
        if [ "$down_count" -gt 0 ] || [ "$alert_st_count" -gt 0 ]; then
            freq_blank
            freq_line "  ${BOLD}${WHITE}Problem hosts:${RESET}"
            grep -E ":status:(DOWN|ALERT|WARN)" "$WATCH_STATE" 2>/dev/null | while IFS=: read -r wlabel _ wstatus; do
                [ -z "$wlabel" ] && continue
                local color="${YELLOW}"
                [ "$wstatus" = "DOWN" ] || [ "$wstatus" = "ALERT" ] && color="${RED}"
                freq_line "    ${color}${wstatus}${RESET} ${_DASH} ${wlabel}"
            done
        fi
    fi

    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# freq watch alerts — view/clear alerts
# ═══════════════════════════════════════════════════════════════════

_watch_alerts() {
    local clear=false host_filter="" count=20
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --clear)  clear=true; shift ;;
            --host)   host_filter="${2:-}"; shift 2 ;;
            -n)       count="${2:-20}"; shift 2 ;;
            *)        shift ;;
        esac
    done

    if $clear; then
        require_admin || return 1
        if [ -f "$WATCH_ALERTS" ]; then
            : > "$WATCH_ALERTS"
            echo -e "  ${GREEN}${_TICK}${RESET} All alerts cleared"
            log "watch: alerts cleared by $(whoami)"
        else
            echo -e "  ${DIM}No alert file found${RESET}"
        fi
        return
    fi

    if [ ! -f "$WATCH_ALERTS" ] || [ ! -s "$WATCH_ALERTS" ]; then
        echo -e "  ${GREEN}${_TICK}${RESET} No alerts"
        return
    fi

    freq_header "Watch Alerts"
    freq_blank

    if [ -n "$host_filter" ]; then
        grep "$host_filter" "$WATCH_ALERTS" 2>/dev/null | tail -"$count" | while IFS= read -r line; do
            freq_line "  ${line}"
        done
    else
        tail -"$count" "$WATCH_ALERTS" | while IFS= read -r line; do
            freq_line "  ${line}"
        done
    fi

    local total
    total=$(wc -l < "$WATCH_ALERTS" 2>/dev/null || echo 0)
    freq_blank
    freq_line "  ${DIM}Total alerts: ${total} (showing last ${count})${RESET}"
    freq_blank
    freq_footer
}
