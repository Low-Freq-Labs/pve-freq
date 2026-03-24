#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/journal.sh
# Operations Journal — flat-file audit trail for human operators
#
# -- if it happened, it's in the journal --
# Commands: cmd_journal
# Dependencies: core.sh, fmt.sh
# =============================================================================

JOURNAL_DIR="${FREQ_DATA_DIR}/journal"
JOURNAL_FILE="${JOURNAL_DIR}/operations.log"
JOURNAL_SESSION_FILE="${JOURNAL_DIR}/sessions.log"

_journal_init() {
    mkdir -p "$JOURNAL_DIR" 2>/dev/null
    [ -f "$JOURNAL_FILE" ] || { touch "$JOURNAL_FILE"; chmod 664 "$JOURNAL_FILE" 2>/dev/null; }
    [ -f "$JOURNAL_SESSION_FILE" ] || { touch "$JOURNAL_SESSION_FILE"; chmod 664 "$JOURNAL_SESSION_FILE" 2>/dev/null; }
}

cmd_journal() {
    local subcmd="${1:-show}"
    shift 2>/dev/null || true

    _journal_init

    case "$subcmd" in
        show)      _journal_show "$@" ;;
        log)       _journal_log "$@" ;;
        search)    _journal_search "$@" ;;
        session)   _journal_session "$@" ;;
        export)    _journal_export "$@" ;;
        help|--help|-h) _journal_help ;;
        *)
            echo -e "  ${RED}Unknown journal command: ${subcmd}${RESET}"
            echo "  Run 'freq journal help' for usage."
            return 1
            ;;
    esac
}

_journal_help() {
    freq_header "Operations Journal"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq journal <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    show [--lines N]   ${DIM}${_DASH} Show recent journal entries${RESET}"
    freq_line "    log <message>      ${DIM}${_DASH} Write a journal entry${RESET}"
    freq_line "    search <pattern>   ${DIM}${_DASH} Search journal entries${RESET}"
    freq_line "    session start      ${DIM}${_DASH} Mark session start${RESET}"
    freq_line "    session end        ${DIM}${_DASH} Mark session end${RESET}"
    freq_line "    export [--file F]  ${DIM}${_DASH} Export journal to file${RESET}"
    freq_blank
    freq_footer
}

_journal_show() {
    local lines=25
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --lines|-n) lines="$2"; shift 2 ;;
            --all|-a)   lines=0; shift ;;
            *) shift ;;
        esac
    done

    freq_header "Operations Journal"
    freq_blank

    if [ ! -s "$JOURNAL_FILE" ]; then
        freq_line "  ${DIM}No journal entries yet. Use 'freq journal log <message>'.${RESET}"
        freq_footer
        return 0
    fi

    local content
    if [ "$lines" -eq 0 ]; then
        content=$(cat "$JOURNAL_FILE")
    else
        content=$(tail -"$lines" "$JOURNAL_FILE")
    fi

    while IFS= read -r entry; do
        [ -z "$entry" ] && continue
        local ts msg
        ts=$(echo "$entry" | awk '{print $1, $2}')
        msg=$(echo "$entry" | cut -d' ' -f3-)
        freq_line "  ${DIM}${ts}${RESET}  ${msg}"
    done <<< "$content"

    freq_blank
    local total
    total=$(wc -l < "$JOURNAL_FILE" 2>/dev/null || echo 0)
    freq_line "  ${DIM}Total entries: ${total}${RESET}"
    freq_footer
}

_journal_log() {
    local message="$*"
    [ -z "$message" ] && { echo -e "  ${RED}Usage: freq journal log <message>${RESET}"; return 1; }

    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    local user="${FREQ_USER:-$(id -un)}"

    echo "${ts} [${user}] ${message}" >> "$JOURNAL_FILE"
    echo -e "  ${GREEN}${_TICK}${RESET} Logged: ${message}"
    log "journal: entry added by ${user}"
}

_journal_search() {
    local pattern="$*"
    [ -z "$pattern" ] && { echo -e "  ${RED}Usage: freq journal search <pattern>${RESET}"; return 1; }

    freq_header "Journal Search ${_DASH} ${pattern}"
    freq_blank

    local results
    results=$(grep -i "$pattern" "$JOURNAL_FILE" 2>/dev/null)

    if [ -z "$results" ]; then
        freq_line "  ${DIM}No entries matching '${pattern}'.${RESET}"
    else
        local count
        count=$(echo "$results" | wc -l)
        while IFS= read -r entry; do
            [ -z "$entry" ] && continue
            local ts msg
            ts=$(echo "$entry" | awk '{print $1, $2}')
            msg=$(echo "$entry" | cut -d' ' -f3-)
            freq_line "  ${DIM}${ts}${RESET}  ${msg}"
        done <<< "$results"
        freq_blank
        freq_line "  ${DIM}Found: ${count} entries${RESET}"
    fi

    freq_footer
}

_journal_session() {
    local action="${1:-}"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    local user="${FREQ_USER:-$(id -un)}"

    case "$action" in
        start)
            echo "${ts} [${user}] SESSION START" >> "$JOURNAL_SESSION_FILE"
            echo "${ts} [${user}] === SESSION START ===" >> "$JOURNAL_FILE"
            echo -e "  ${GREEN}${_TICK}${RESET} Session started at ${ts}"
            log "journal: session start by ${user}"
            ;;
        end)
            echo "${ts} [${user}] SESSION END" >> "$JOURNAL_SESSION_FILE"
            echo "${ts} [${user}] === SESSION END ===" >> "$JOURNAL_FILE"
            echo -e "  ${GREEN}${_TICK}${RESET} Session ended at ${ts}"
            log "journal: session end by ${user}"
            ;;
        *)
            echo -e "  ${RED}Usage: freq journal session <start|end>${RESET}"
            return 1
            ;;
    esac
}

_journal_export() {
    local outfile=""
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --file|-f) outfile="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    [ -z "$outfile" ] && outfile="${JOURNAL_DIR}/export-$(date '+%Y%m%d-%H%M%S').log"

    if cp "$JOURNAL_FILE" "$outfile" 2>/dev/null; then
        echo -e "  ${GREEN}${_TICK}${RESET} Journal exported to: ${outfile}"
        local lines
        lines=$(wc -l < "$outfile" 2>/dev/null || echo 0)
        echo -e "  ${DIM}${lines} entries exported${RESET}"
        log "journal: exported ${lines} entries to ${outfile}"
    else
        echo -e "  ${RED}${_CROSS}${RESET} Export failed"
        return 1
    fi
}
