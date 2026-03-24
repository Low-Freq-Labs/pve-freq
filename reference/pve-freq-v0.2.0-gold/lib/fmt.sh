#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# PVE FREQ v2.0.0 -- lib/fmt.sh
# Display engine: borders, steps, status, menus, tables
# Every lib uses this. Zero raw echos.
#
# -- 80 columns. putty default. designed for the real world. --
# -- but when you have room, it breathes. --
# Dependencies: core.sh (colors, symbols)
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# DYNAMIC-WIDTH ENGINE — one tput call per session
# ═══════════════════════════════════════════════════════════════════
_FREQ_CACHED_WIDTH=0
_freq_width() {
    if [ -n "${FREQ_WIDTH:-}" ]; then echo "$FREQ_WIDTH"; return; fi
    if [ "$_FREQ_CACHED_WIDTH" -gt 0 ]; then echo "$_FREQ_CACHED_WIDTH"; return; fi
    local w
    w=$(tput cols 2>/dev/null) || w=80
    [[ "$w" =~ ^[0-9]+$ ]] || w=80
    [ "$w" -lt 40 ] && w=80
    [ "$w" -gt 300 ] && w=80
    _FREQ_CACHED_WIDTH=$w
    echo "$w"
}

# Pure bash ANSI strip — no external forks
_FREQ_STRIPPED=""
_freq_strip_ansi() {
    printf -v _FREQ_STRIPPED '%b' "$1"
    while [[ "$_FREQ_STRIPPED" == *$'\e['* ]]; do
        local prefix="${_FREQ_STRIPPED%%$'\e['*}"
        local rest="${_FREQ_STRIPPED#*$'\e['}"
        if [[ "$rest" == *m* ]]; then
            rest="${rest#*m}"
        else
            break
        fi
        _FREQ_STRIPPED="${prefix}${rest}"
    done
}

# ANSI-aware text truncation — preserves escape sequences, truncates visible chars
_freq_truncate_ansi() {
    local max_vis="$1"; shift
    local text="$*"
    printf -v text '%b' "$text"
    local result="" vis=0 i=0 len=${#text}
    while [ "$i" -lt "$len" ] && [ "$vis" -lt "$max_vis" ]; do
        local ch="${text:$i:1}"
        if [ "$ch" = $'\e' ] && [ "${text:$((i+1)):1}" = "[" ]; then
            local seq=""
            while [ "$i" -lt "$len" ]; do
                seq+="${text:$i:1}"
                [ "${text:$i:1}" = "m" ] && { i=$((i+1)); break; }
                i=$((i+1))
            done
            result+="$seq"
        else
            result+="$ch"
            vis=$((vis+1))
            i=$((i+1))
        fi
    done
    result+=$'\e[0m'
    printf '%s' "$result"
}

# Repeat a character N times — pure bash, no subshell
_repeat_b() {
    local char="$1" count="$2"
    [ "$count" -le 0 ] 2>/dev/null && return
    local i
    for ((i=0; i<count; i++)); do printf '%b' "$char"; done
}

# ═══════════════════════════════════════════════════════════════════
# BORDER SYSTEM — Rounded Unicode, dynamic width, breadcrumb nav
# ═══════════════════════════════════════════════════════════════════

# Top border with breadcrumb title
freq_header() {
    local title="$1"
    local w; w=$(_freq_width)
    local inner="[ PVE FREQ ${_RARROW} ${title} ]"
    _freq_strip_ansi "$inner"
    local vis_inner=${#_FREQ_STRIPPED}
    local fill=$(( w - vis_inner - 4 ))
    (( fill < 1 )) && fill=1
    local fill_str bh_char; printf -v fill_str '%*s' "$fill" ""; printf -v bh_char '%b' "${_B_H}"
    fill_str="${fill_str// /${bh_char}}"
    printf "\n${PURPLE}%b%b%b%b%s%b${RESET}\n" "${_B_TL}" "${_B_H}" "${_B_H}" "${inner}" "$fill_str" "${_B_TR}"
}

# Bottom border — clean close
freq_footer() {
    local w; w=$(_freq_width)
    local fill=$(( w - 2 ))
    (( fill < 1 )) && fill=1
    local fill_str bh_char; printf -v fill_str '%*s' "$fill" ""; printf -v bh_char '%b' "${_B_H}"
    fill_str="${fill_str// /${bh_char}}"
    printf "${PURPLE}%b%s%b${RESET}\n\n" "${_B_BL}" "$fill_str" "${_B_BR}"
}

# Content line with side borders and auto-padding
freq_line() {
    local content="$1"
    local w; w=$(_freq_width)
    _freq_strip_ansi "$content"
    local vis_len=${#_FREQ_STRIPPED}
    local max_content=$(( w - 4 ))
    if (( vis_len > max_content && max_content > 4 )); then
        content=$(_freq_truncate_ansi $(( max_content - 2 )) "$content")
        content+="${DIM}..${RESET}"
        _freq_strip_ansi "$content"
    fi
    local pad=$(( w - ${#_FREQ_STRIPPED} - 4 ))
    (( pad < 0 )) && pad=0
    printf "${PURPLE}%b${RESET} %b%*s ${PURPLE}%b${RESET}\n" "${_B_V}" "$content" "$pad" "" "${_B_V}"
}

# Empty bordered line
freq_blank() {
    local w; w=$(_freq_width)
    local pad=$(( w - 2 ))
    (( pad < 0 )) && pad=0
    printf "${PURPLE}%b${RESET}%*s${PURPLE}%b${RESET}\n" "${_B_V}" "$pad" "" "${_B_V}"
}

# Mid-section divider with optional title
freq_divider() {
    local title="${1:-}"
    local w; w=$(_freq_width)

    if [ -z "$title" ]; then
        # Plain divider — thin line across
        local fill=$(( w - 2 ))
        printf "${PURPLEDIM:-${PURPLE}}"
        printf '%b' "${_B_LM}"
        _repeat_b "${_B_H}" "$fill"
        printf '%b' "${_B_RM}"
        printf "${RESET}\n"
        return
    fi

    _freq_strip_ansi "$title"
    local vis_len=${#_FREQ_STRIPPED}
    local left=2
    local right=$(( w - vis_len - left - 6 ))
    [ "$right" -lt 1 ] && right=1
    printf "${PURPLE}"
    printf '%b' "${_B_LM}"
    printf "${RESET}"
    _repeat_b "${_B_H}" "$left"
    printf " %b " "$title"
    _repeat_b "${_B_H}" "$right"
    printf "${PURPLE}"
    printf '%b' "${_B_RM}"
    printf "${RESET}\n"
}

# ═══════════════════════════════════════════════════════════════════
# ANIMATED SPINNER — for long-running operations
# -- silence is the enemy of confidence --
# ═══════════════════════════════════════════════════════════════════

# Spinner frames (Braille pattern — smooth rotation)
if [ "${FREQ_ASCII:-1}" = "0" ]; then
    _SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
else
    _SPINNER_FRAMES=("|" "/" "-" "\\")
fi
_SPINNER_PID=""

# Start background spinner with message
_spinner_start() {
    local msg="$1"
    [ ! -t 1 ] && return  # No spinner in non-interactive mode
    (
        local i=0
        local frames=("${_SPINNER_FRAMES[@]}")
        local count=${#frames[@]}
        while true; do
            printf "\r  ${PURPLE}${frames[$((i % count))]}${RESET}  %-50s" "$msg"
            i=$((i + 1))
            sleep 0.1
        done
    ) &
    _SPINNER_PID=$!
    disown "$_SPINNER_PID" 2>/dev/null
}

# Stop spinner and show result
_spinner_stop() {
    local status="$1" detail="${2:-}"
    if [ -n "$_SPINNER_PID" ]; then
        kill "$_SPINNER_PID" 2>/dev/null
        wait "$_SPINNER_PID" 2>/dev/null
        _SPINNER_PID=""
        printf "\r%80s\r" ""  # Clear the line
    fi
    case "$status" in
        ok)   _step_ok "$detail" ;;
        fail) _step_fail "$detail" ;;
        warn) _step_warn "$detail" ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# PROGRESS INDICATORS — Live step display
# -- every operation deserves clear feedback --
# ═══════════════════════════════════════════════════════════════════

_step_start() {
    local msg="$1"
    printf "  ${_SPIN}  %-50s" "$msg"
}

_step_ok() {
    local detail="${1:-}"
    if [ -n "$detail" ]; then
        echo -e "  ${GREEN}${_TICK}${RESET}  ${detail}"
    else
        echo -e "  ${GREEN}${_TICK}${RESET}"
    fi
}

_step_fail() {
    local detail="${1:-}"
    if [ -n "$detail" ]; then
        echo -e "  ${RED}${_CROSS}${RESET}  ${detail}"
    else
        echo -e "  ${RED}${_CROSS}${RESET}"
    fi
}

_step_warn() {
    local detail="${1:-}"
    if [ -n "$detail" ]; then
        echo -e "  ${YELLOW}${_WARN}${RESET}  ${detail}"
    else
        echo -e "  ${YELLOW}${_WARN}${RESET}"
    fi
}

_step_info() {
    local detail="${1:-}"
    echo -e "  ${CYAN}${_ICO_INFO}${RESET}  ${detail}"
}

# ═══════════════════════════════════════════════════════════════════
# MENU HELPERS — Consistent interactive elements
# ═══════════════════════════════════════════════════════════════════

menu_item() {
    local num="$1" name="$2" desc="$3" risk="${4:-safe}"
    local risk_color=""
    case "$risk" in
        safe)        risk_color="" ;;
        changes)     risk_color="${YELLOW}[changes]${RESET} " ;;
        destructive) risk_color="${RED}[destructive]${RESET} " ;;
    esac
    echo -e "    ${PURPLELIGHT}${num}${RESET}  ${BOLD}${name}${RESET}  ${DIM}${desc}${RESET}  ${risk_color}"
}

_MENU_CHOICE=""
menu_prompt() {
    local max="$1"
    echo ""
    echo -e "    ${DIM} 0  Back${RESET}"
    echo ""
    read -rp "    ${_DOT} Select [0-${max}]: " _MENU_CHOICE
}

# Step display for wizards — decorative phase separator
show_step() {
    local context="$1" current="$2" total="$3" desc="$4"
    echo ""
    echo -e "    ${PURPLE}${_DIAMOND} ${_DOT} ${_DOT} ${_DOT} ${_STAR}${RESET}  ${BOLD}${WHITE}${context}${RESET} ${_DASH} Step ${current}/${total}: ${desc}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# TABLE HELPERS — Aligned columnar output
# ═══════════════════════════════════════════════════════════════════

# Print a table header row
_tbl_header() {
    local fmt="$1"; shift
    printf "    ${DIM}${fmt}${RESET}\n" "$@"
    local w; w=$(_freq_width)
    local line_w=$(( w - 8 ))
    printf "    ${DIM}"
    _repeat_b "${_B_H}" "$line_w"
    printf "${RESET}\n"
}

# Print a status badge
_badge() {
    local status="$1"
    case "$status" in
        ok|up|running|compliant|done)
            printf "${GREEN}${_TICK}${RESET}" ;;
        warn|drift|planned)
            printf "${YELLOW}${_WARN}${RESET}" ;;
        fail|down|failed|error)
            printf "${RED}${_CROSS}${RESET}" ;;
        skip|stopped)
            printf "${DIM}${_DASH}${RESET}" ;;
        *)
            printf "${DIM}${_DOT}${RESET}" ;;
    esac
}
