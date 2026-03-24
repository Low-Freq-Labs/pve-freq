#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/notify.sh
# Notification System — Discord/Slack webhooks for alerts
#
# -- the messenger --
# Commands: cmd_notify
# Dependencies: core.sh, fmt.sh
# =============================================================================

NOTIFY_CONF="${FREQ_DIR}/conf/notify.conf"
NOTIFY_LOG="${FREQ_DATA_DIR}/log/notify.log"

cmd_notify() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        test)    _notify_test "$@" ;;
        alert)   _notify_alert "$@" ;;
        status)  _notify_status ;;
        setup)   _notify_setup "$@" ;;
        help|--help|-h) _notify_help ;;
        *)
            echo -e "  ${RED}Unknown notify command: ${subcmd}${RESET}"
            echo "  Run 'freq notify help' for usage."
            return 1
            ;;
    esac
}

_notify_help() {
    freq_header "Notification System"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq notify <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    test [channel]     ${DIM}${_DASH} Send a test notification${RESET}"
    freq_line "    alert <message>    ${DIM}${_DASH} Send an alert notification${RESET}"
    freq_line "    status             ${DIM}${_DASH} Show configured channels${RESET}"
    freq_line "    setup <type> <url> ${DIM}${_DASH} Configure a webhook${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Channels:${RESET} discord, slack"
    freq_blank
    freq_footer
}

_notify_load_conf() {
    DISCORD_WEBHOOK=""
    SLACK_WEBHOOK=""
    if [ -f "$NOTIFY_CONF" ]; then
        # shellcheck source=/dev/null
        source "$NOTIFY_CONF" 2>/dev/null
    fi
}

_notify_send_discord() {
    local message="$1"
    local webhook="${DISCORD_WEBHOOK:-}"
    [ -z "$webhook" ] && { echo -e "  ${RED}Discord webhook not configured. Run 'freq notify setup discord <url>'.${RESET}"; return 1; }

    local payload
    payload=$(printf '{"content": "%s"}' "$(echo "$message" | sed 's/"/\\"/g')")

    local http_code
    http_code=$(curl --connect-timeout 10 --max-time 15 -s -o /dev/null -w '%{http_code}' \
        --connect-timeout 10 --max-time 15 \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$webhook" 2>/dev/null)

    if [ "$http_code" = "204" ] || [ "$http_code" = "200" ]; then
        return 0
    else
        return 1
    fi
}

_notify_send_slack() {
    local message="$1"
    local webhook="${SLACK_WEBHOOK:-}"
    [ -z "$webhook" ] && { echo -e "  ${RED}Slack webhook not configured. Run 'freq notify setup slack <url>'.${RESET}"; return 1; }

    local payload
    payload=$(printf '{"text": "%s"}' "$(echo "$message" | sed 's/"/\\"/g')")

    local http_code
    http_code=$(curl --connect-timeout 10 --max-time 15 -s -o /dev/null -w '%{http_code}' \
        --connect-timeout 10 --max-time 15 \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$webhook" 2>/dev/null)

    if [ "$http_code" = "200" ]; then
        return 0
    else
        return 1
    fi
}

_notify_send() {
    local message="$1" channel="${2:-all}"
    _notify_load_conf

    local sent=false
    if [ "$channel" = "all" ] || [ "$channel" = "discord" ]; then
        if [ -n "$DISCORD_WEBHOOK" ]; then
            _notify_send_discord "$message" && sent=true
        fi
    fi
    if [ "$channel" = "all" ] || [ "$channel" = "slack" ]; then
        if [ -n "$SLACK_WEBHOOK" ]; then
            _notify_send_slack "$message" && sent=true
        fi
    fi

    # Log notification
    mkdir -p "$(dirname "$NOTIFY_LOG")" 2>/dev/null
    echo "$(date '+%Y-%m-%d %H:%M:%S') [${channel}] ${message}" >> "$NOTIFY_LOG" 2>/dev/null

    $sent && return 0 || return 1
}

_notify_test() {
    require_operator || return 1
    local channel="${1:-all}"

    _notify_load_conf

    freq_header "Notification Test"
    freq_blank

    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    local message="[FREQ TEST] PVE FREQ notification test at ${ts} from $(hostname)"

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would send test to: ${channel}"
        freq_line "  Message: ${DIM}${message}${RESET}"
        freq_footer
        return 0
    fi

    _step_start "Sending test notification (${channel})"
    if _notify_send "$message" "$channel"; then
        _step_ok "delivered"
    else
        _step_fail "delivery failed — check webhook config"
    fi

    freq_blank
    freq_footer
    log "notify: test sent to ${channel}"
}

_notify_alert() {
    local message="$*"
    [ -z "$message" ] && { echo -e "  ${RED}Usage: freq notify alert <message>${RESET}"; return 1; }

    _notify_load_conf

    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    local alert_msg="[FREQ ALERT] ${ts} | ${message}"

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would send alert: ${message}"
        return 0
    fi

    if _notify_send "$alert_msg" "all"; then
        echo -e "  ${GREEN}${_TICK}${RESET} Alert sent: ${message}"
    else
        echo -e "  ${YELLOW}${_WARN}${RESET} Alert logged locally (webhook delivery failed)"
    fi
    log "notify: alert sent — ${message}"
}

_notify_status() {
    _notify_load_conf

    freq_header "Notification Status"
    freq_blank

    if [ -n "$DISCORD_WEBHOOK" ]; then
        freq_line "  Discord: ${GREEN}configured${RESET}  ${DIM}${DISCORD_WEBHOOK:0:40}...${RESET}"
    else
        freq_line "  Discord: ${DIM}not configured${RESET}"
    fi

    if [ -n "$SLACK_WEBHOOK" ]; then
        freq_line "  Slack:   ${GREEN}configured${RESET}  ${DIM}${SLACK_WEBHOOK:0:40}...${RESET}"
    else
        freq_line "  Slack:   ${DIM}not configured${RESET}"
    fi

    freq_blank
    if [ -f "$NOTIFY_LOG" ]; then
        local count
        count=$(wc -l < "$NOTIFY_LOG" 2>/dev/null || echo 0)
        freq_line "  ${DIM}Notification log: ${count} entries${RESET}"
        freq_line "  ${DIM}Last 3:${RESET}"
        tail -3 "$NOTIFY_LOG" 2>/dev/null | while IFS= read -r line; do
            freq_line "    ${DIM}${line}${RESET}"
        done
    fi

    freq_blank
    freq_footer
}

_notify_setup() {
    require_admin || return 1
    local channel="${1:-}" url="${2:-}"
    [ -z "$channel" ] || [ -z "$url" ] && {
        echo -e "  ${RED}Usage: freq notify setup <discord|slack> <webhook-url>${RESET}"
        return 1
    }

    mkdir -p "$(dirname "$NOTIFY_CONF")" 2>/dev/null

    case "$channel" in
        discord)
            if [ -f "$NOTIFY_CONF" ] && grep -q "^DISCORD_WEBHOOK=" "$NOTIFY_CONF" 2>/dev/null; then
                sed -i "s|^DISCORD_WEBHOOK=.*|DISCORD_WEBHOOK=\"${url}\"|" "$NOTIFY_CONF"
            else
                echo "DISCORD_WEBHOOK=\"${url}\"" >> "$NOTIFY_CONF"
            fi
            ;;
        slack)
            if [ -f "$NOTIFY_CONF" ] && grep -q "^SLACK_WEBHOOK=" "$NOTIFY_CONF" 2>/dev/null; then
                sed -i "s|^SLACK_WEBHOOK=.*|SLACK_WEBHOOK=\"${url}\"|" "$NOTIFY_CONF"
            else
                echo "SLACK_WEBHOOK=\"${url}\"" >> "$NOTIFY_CONF"
            fi
            ;;
        *)
            echo -e "  ${RED}Unknown channel: ${channel}. Use 'discord' or 'slack'.${RESET}"
            return 1
            ;;
    esac

    chmod 600 "$NOTIFY_CONF" 2>/dev/null
    echo -e "  ${GREEN}${_TICK}${RESET} ${channel} webhook configured"
    log "notify: ${channel} webhook configured"
}
