#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/menu.sh
# Interactive TUI & Menu System
#
# Author:  FREQ Project
# -- first thing you see. make it count. --
# Commands: none (helper lib, called by dispatcher when no args)
# Dependencies: core.sh, fmt.sh, personality.sh, resolve.sh
# =============================================================================
# shellcheck disable=SC2154

# ═══════════════════════════════════════════════════════════════════
# MENU ICON DEFINITIONS — risk/status tags
# ═══════════════════════════════════════════════════════════════════

# These adapt to Unicode/ASCII mode set by core.sh and _menu_detect_unicode
_menu_init_icons() {
    if [ "${FREQ_ASCII:-1}" = "0" ]; then
        _TAG_CHANGES="\u26a0\ufe0f"     # warning sign
        _TAG_RISKY="\u2620"              # skull and crossbones
        _TAG_DESTRUCTIVE="\u26a1"        # lightning bolt / zap
        _TAG_COMING="\u23f3"             # hourglass
        _TAG_READONLY="\u2630"           # trigram / eye-like
        _TAG_SAFE="\u2714"               # checkmark
        _SEC_VM="\u2601"                 # cloud (VM/compute)
        _SEC_FLEET="\u2318"              # command/network
        _SEC_INFRA="\u2699"              # gear
        _SEC_APPL="\u2616"              # router-like
        _SEC_MON="\u26c9"               # shield
        _SEC_UTIL="\u2692"              # hammer+wrench
    else
        _TAG_CHANGES="!"
        _TAG_RISKY="!!"
        _TAG_DESTRUCTIVE="!!!"
        _TAG_COMING="..."
        _TAG_READONLY="~"
        _TAG_SAFE="ok"
        _SEC_VM="*"
        _SEC_FLEET="*"
        _SEC_INFRA="*"
        _SEC_APPL="*"
        _SEC_MON="*"
        _SEC_UTIL="*"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# BREADCRUMB STATE
# ═══════════════════════════════════════════════════════════════════

_MENU_BREADCRUMB="PVE FREQ"
_BREADCRUMB_STACK=()
breadcrumb_push() { _BREADCRUMB_STACK+=("$1"); }
breadcrumb_pop()  { [ ${#_BREADCRUMB_STACK[@]} -gt 0 ] && unset "_BREADCRUMB_STACK[-1]"; }
breadcrumb_render() {
    local trail="PVE FREQ"
    local i
    for i in "${_BREADCRUMB_STACK[@]}"; do
        if [ "${FREQ_ASCII:-1}" = "0" ]; then
            trail="${trail} \u203a ${i}"
        else
            trail="${trail} > ${i}"
        fi
    done
    echo -e "  ${DIM}${trail}${RESET}"
}

# ═══════════════════════════════════════════════════════════════════
# MENU TAG HELPERS — consistent risk/status badges
# ═══════════════════════════════════════════════════════════════════

_tag_changes()     { echo -e "${YELLOW}${_TAG_CHANGES} changes${RESET}"; }
_tag_risky()       { echo -e "${RED}${_TAG_RISKY} risky${RESET}"; }
_tag_destructive() { echo -e "${RED}${_TAG_DESTRUCTIVE} destructive${RESET}"; }
_tag_coming()      { echo -e "${DIM}${_TAG_COMING} v1.1${RESET}"; }
_tag_safe()        { echo -e "${GREEN}${_TAG_SAFE}${RESET}"; }

# ═══════════════════════════════════════════════════════════════════
# HOST PICKER — Interactive host selection by type
# ═══════════════════════════════════════════════════════════════════

_menu_host_picker() {
    local host_type="$1"
    local -a hosts=()
    local -a ips=()

    while IFS= read -r line; do
        [[ "$line" =~ ^#|^[[:space:]]*$ ]] && continue
        local ip label htype
        ip=$(echo "$line" | awk '{print $1}')
        label=$(echo "$line" | awk '{print $2}')
        htype=$(echo "$line" | awk '{print $3}')
        if [ "$htype" = "$host_type" ]; then
            hosts+=("$label")
            ips+=("$ip")
        fi
    done < "$HOSTS_FILE"

    if [ ${#hosts[@]} -eq 0 ]; then
        echo -e "  ${YELLOW}No ${host_type} hosts in fleet.${RESET}" >&2
        echo ""
        return 1
    fi

    # Single host — auto-select
    if [ ${#hosts[@]} -eq 1 ]; then
        echo -e "  ${DIM}Auto-selected: ${hosts[0]} (${ips[0]})${RESET}" >&2
        echo "${hosts[0]}"
        return 0
    fi

    # Multiple hosts — show picker
    echo "" >&2
    echo -e "  ${BOLD}Select ${host_type} host:${RESET}" >&2
    local j
    for ((j=0; j<${#hosts[@]}; j++)); do
        printf "    ${PURPLELIGHT}[%d]${RESET}  %-20s  ${DIM}%s${RESET}\n" "$((j+1))" "${hosts[$j]}" "${ips[$j]}" >&2
    done
    echo -e "    ${DIM}[0]  Cancel${RESET}" >&2
    echo "" >&2

    local choice
    read -rp "  Selection: " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#hosts[@]} ]; then
        echo "${hosts[$((choice-1))]}"
        return 0
    fi
    echo ""
    return 1
}

# ═══════════════════════════════════════════════════════════════════
# ENGINE POLICY PICKER — Interactive policy selection for engine
# ═══════════════════════════════════════════════════════════════════

_menu_engine_policy_picker() {
    local engine_dir="${FREQ_DIR}/engine"

    if [ ! -f "$engine_dir/__main__.py" ]; then
        echo -e "  ${YELLOW:-}Engine not installed. Place engine/ in ${FREQ_DIR}/${RESET:-}" >&2
        echo ""
        return 1
    fi

    local json_out
    json_out=$(PYTHONPATH="$FREQ_DIR" python3 -m engine policies --freq-dir "$FREQ_DIR" --json 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$json_out" ]; then
        echo -e "  ${YELLOW:-}No policies found or engine error.${RESET:-}" >&2
        echo ""
        return 1
    fi

    # Parse policy names from JSON array
    local -a policies=()
    while IFS= read -r name; do
        [ -n "$name" ] && policies+=("$name")
    done < <(echo "$json_out" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        for p in data:
            if isinstance(p, dict):
                print(p.get('name', p.get('id', '')))
            else:
                print(p)
    elif isinstance(data, dict):
        for p in data.get('policies', data.get('items', [])):
            if isinstance(p, dict):
                print(p.get('name', p.get('id', '')))
            else:
                print(p)
except: pass
" 2>/dev/null)

    if [ ${#policies[@]} -eq 0 ]; then
        echo -e "  ${YELLOW:-}No policies available.${RESET:-}" >&2
        echo ""
        return 1
    fi

    echo "" >&2
    echo -e "  ${BOLD}Select policy:${RESET}" >&2
    local j
    for ((j=0; j<${#policies[@]}; j++)); do
        printf "    ${PURPLELIGHT}[%d]${RESET}  %s\n" "$((j+1))" "${policies[$j]}" >&2
    done
    echo -e "    ${DIM}[0]  Cancel${RESET}" >&2
    echo "" >&2

    local choice
    read -rp "  Selection: " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#policies[@]} ]; then
        echo "${policies[$((choice-1))]}"
        return 0
    fi
    echo ""
    return 1
}

# ═══════════════════════════════════════════════════════════════════
# ENGINE MENU DISPATCHER — routes C/X/D/P to engine commands
# ═══════════════════════════════════════════════════════════════════

_menu_engine_run() {
    local action="$1"
    local engine_dir="${FREQ_DIR}/engine"

    if [ ! -f "$engine_dir/__main__.py" ]; then
        echo ""
        echo -e "  ${YELLOW:-}Engine not installed. Place engine/ in ${FREQ_DIR}/${RESET:-}"
        _pause
        return
    fi

    if [ "$action" = "policies" ]; then
        _engine_dispatch policies
        _pause
        return
    fi

    # check, fix, diff all need a policy selection
    local policy
    policy=$(_menu_engine_policy_picker)
    if [ -z "$policy" ]; then
        return
    fi

    _engine_dispatch "$action" "$policy"
    _pause
}

# ═══════════════════════════════════════════════════════════════════
# CONFIRMATION DIALOG
# ═══════════════════════════════════════════════════════════════════

_menu_confirm() {
    local msg="${1:-Continue?}"
    local default="${2:-n}"
    local prompt
    [ "$default" = "y" ] && prompt="[Y/n]" || prompt="[y/N]"

    echo ""
    local answer
    read -rp "  ${msg} ${prompt} " answer
    answer="${answer:-$default}"
    case "${answer,,}" in
        y|yes) return 0 ;;
        *)     return 1 ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# ERROR MESSAGE TRANSLATION
# ═══════════════════════════════════════════════════════════════════

_menu_error() {
    local raw="$1" ctx="${2:-}"
    case "$raw" in
        *"Connection refused"*)
            echo "  Cannot connect to ${ctx:-host} ${_DASH} service may be down" ;;
        *"timed out"*|*"Connection timed"*)
            echo "  ${ctx:-Host} not responding ${_DASH} check network" ;;
        *"Permission denied"*)
            echo "  Access denied to ${ctx:-host} ${_DASH} check SSH key" ;;
        *"No route to host"*)
            echo "  Cannot reach ${ctx:-host} ${_DASH} check VLAN/routing" ;;
        *"parse error"*|*"JSON"*|*"json"*)
            echo "  ${ctx:-Service} returned unexpected data ${_DASH} API may have changed" ;;
        *"unreachable"*)
            echo "  ${ctx:-Host} unreachable ${_DASH} check if powered on" ;;
        *)
            echo "  Error: ${raw}" ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# PERMISSION DISPLAY
# ═══════════════════════════════════════════════════════════════════

_menu_show_permissions() {
    echo ""
    echo -e "  ${BOLD}Your role: ${FREQ_ROLE}${RESET}"
    echo ""
    case "$FREQ_ROLE" in
        admin)
            echo -e "  ${GREEN}Full access${RESET} ${_DASH} all commands available" ;;
        operator)
            echo -e "  ${GREEN}Read/diagnose${RESET} ${_DASH} status, health, audit, docker"
            echo -e "  ${YELLOW}Restricted${RESET}    ${_DASH} create, destroy, migrate need admin" ;;
        viewer)
            echo -e "  ${GREEN}Read-only${RESET}     ${_DASH} status and health only"
            echo -e "  ${RED}No changes${RESET}    ${_DASH} contact admin for access" ;;
    esac
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# PAUSE FOR KEYPRESS
# ═══════════════════════════════════════════════════════════════════

_pause() {
    echo ""
    read -rsn1 -p "  Press any key to continue..." 2>/dev/null || true
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# TERMINAL CLEAR — ANSI clear + cursor home (works in PuTTY, xterm)
# ═══════════════════════════════════════════════════════════════════

_menu_clear() {
    printf '\033[2J\033[H'
}

# ═══════════════════════════════════════════════════════════════════
# UNICODE AUTO-DETECTION — for interactive mode
# ═══════════════════════════════════════════════════════════════════

_menu_detect_unicode() {
    # In interactive mode: default to Unicode if terminal supports it
    if [[ -t 1 ]] && [[ "${LANG:-}" == *UTF-8* || "${LC_ALL:-}" == *UTF-8* ]]; then
        FREQ_ASCII="${FREQ_ASCII:-0}"
    fi

    # Reload symbols if we switched to Unicode
    if [ "${FREQ_ASCII:-1}" = "0" ]; then
        # Box drawing — rounded corners
        _B_H="\u2500"; _B_V="\u2502"
        _B_TL="\u256d"; _B_TR="\u256e"; _B_BL="\u2570"; _B_BR="\u256f"
        _B_LM="\u251c"; _B_RM="\u2524"; _B_HH="\u2550"
        # Status
        _TICK="\u2714"; _CROSS="\u2718"; _WARN="\u26a0"; _SPIN="\u25dc"
        _ICO_OK="\u2714"; _ICO_FAIL="\u2718"; _ICO_WARN="\u26a0"; _ICO_INFO="\u25c9"
        _ICO_ZAP="\u26a1"; _ICO_SSH="\u26d3"
        _ICO_GEAR="\u2699"; _ICO_SKULL="\u2620"; _ICO_LOCK="\u26bf"
        # Decorative
        _SPARKLE="\u2728"; _STAR="\u2605"; _DIAMOND="\u25c6"
        _ARROW="\u2192"; _BULLET="\u2022"; _DOT="\u00b7"; _DASH="\u2014"
        _RARROW="\u203a"; _CIRCLE="\u25cf"; _RING="\u25cb"
        _HBAR="\u2501"; _VBAR="\u2503"
        _TRI_R="\u25b8"; _TRI_D="\u25be"
    fi

    # Initialize menu-specific icons
    _menu_init_icons
}

# ═══════════════════════════════════════════════════════════════════
# STUB COMMAND WRAPPER — graceful "coming soon" for stub libs
# ═══════════════════════════════════════════════════════════════════

_menu_run() {
    local cmd_name="$1"
    shift
    if type -t "$cmd_name" &>/dev/null; then
        ( "$cmd_name" "$@" ) || true
    else
        echo ""
        echo -e "  ${DIM}${_TAG_COMING}${RESET}  ${BOLD}${cmd_name}${RESET} ${_DASH} coming in v1.1"
        echo -e "  ${DIM}This feature is planned but not yet implemented.${RESET}"
        echo ""
    fi
}

# ═══════════════════════════════════════════════════════════════════
# SPLASH SCREEN — Full startup banner with logo + live stats
# -- first thing you see. make it count. --
# ═══════════════════════════════════════════════════════════════════

_splash_screen() {
    local tl _sub _upad _apad
    tl=$(freq_tagline 2>/dev/null || echo "-- ready --")
    _sub="${PACK_SUBTITLE:-PVE Infrastructure Platform}"
    local host_ct=0
    [ -f "$HOSTS_FILE" ] && host_ct=$(grep -cv '^#\|^$' "$HOSTS_FILE" 2>/dev/null || echo 0)
    local user_ct=0
    [ -f "$USERS_FILE" ] && user_ct=$(grep -cv '^#\|^$' "$USERS_FILE" 2>/dev/null || echo 0)

    echo ""
    if [ "${FREQ_ASCII:-1}" = "0" ]; then
        # ─────────────────────────────────────────────────────────────
        # PVE FREQ — The Logo
        # Refined block letters with clean geometry and breathing room
        # Designed to feel timeless at any terminal width
        # ─────────────────────────────────────────────────────────────
        echo -e "    ${PURPLE}┏━━━━┓╻ ╻┏━━━┓   ┏━━━━┓┏━━━┓┏━━━━┓ ┏━━━┓${RESET}"
        echo -e "    ${PURPLE}┃ ┏━┓┃┃ ┃┃ ┏━┛   ┃ ┏━━┛┃ ┏┓┃┃ ┏━━┛┃ ┏┓ ┃${RESET}"
        echo -e "    ${PURPLE}┃ ┗━┛┃┃ ┃┃ ┗━┓   ┃ ┗━┓ ┃ ┗┛┃┃ ┗━┓ ┃ ┃┃ ┃${RESET}"
        echo -e "    ${PURPLE}┃ ┏━━┛┗┓┃┃ ┏━┛   ┃ ┏━┛ ┃ ┏┓┃┃ ┏━┛ ┃ ┗┛▄┃${RESET}"
        echo -e "    ${PURPLE}┃ ┃    ┗┛┃ ┗━━┓  ┃ ┃   ┃ ┃┃ ┃ ┗━━┓┗━━━━┛${RESET}"
        echo -e "    ${PURPLE}┗━┛     ╹┗━━━━┛  ┗━┛   ┗━┛┗━┗━━━━┛  v${FREQ_VERSION}${RESET}"
        _upad=$(( (46 - ${#_sub}) / 2 )); [ $_upad -lt 0 ] && _upad=0
        printf "    %*s${DIM}%s${RESET}\n" "$_upad" "" "$_sub"
    else
        # PVE FREQ ASCII fallback — clean, readable, timeless
        echo -e "    ${PURPLE} ___  _  _ ___   ___ ___ ___ ___  ${RESET}"
        echo -e "    ${PURPLE}| _ \\| || | __| | __| _ | __/ _ \\ ${RESET}"
        echo -e "    ${PURPLE}|  _/| \\/ | _|  | _||   | _| (_) |${RESET}"
        echo -e "    ${PURPLE}|_|   \\__/|___| |_| |_|_|___\\__\\_\\${RESET}"
        echo -e "    ${DIM}                          v${FREQ_VERSION}${RESET}"
        _apad=$(( (35 - ${#_sub}) / 2 )); [ $_apad -lt 0 ] && _apad=0
        printf "    ${DIM}%*s%s${RESET}\n" "$_apad" "" "$_sub"
    fi

    # Waveform separator — the frequency signature
    echo ""
    if [ "${FREQ_ASCII:-1}" = "0" ]; then
        echo -e "    ${PURPLEDIM}\u2500\u2500\u2500 \u223f \u2500\u2500 \u223f \u2500\u2500 \u223f \u2500\u2500 \u223f \u2500\u2500 \u223f \u2500\u2500 \u223f \u2500\u2500 \u223f \u2500\u2500 \u223f \u2500\u2500\u2500${RESET}"
    else
        echo -e "    ${DIM}--- ~ -- ~ -- ~ -- ~ -- ~ -- ~ -- ~ -- ~ ---${RESET}"
    fi
    echo ""

    # MOTD quote
    _freq_motd 2>/dev/null
    echo ""

    # Live stats — two-column layout with status indicators
    local _pve_up=0 _pve_tot=${#PVE_NODES[@]}
    for _pip in "${PVE_NODES[@]}"; do
        ping -c1 -W1 "$_pip" &>/dev/null && _pve_up=$((_pve_up+1))
    done

    local _pve_color="${GREEN}"
    [ "$_pve_up" -lt "$_pve_tot" ] && _pve_color="${YELLOW}"
    [ "$_pve_up" -eq 0 ] && _pve_color="${RED}"

    printf "    ${PURPLEDIM}${_BULLET}${RESET} %-12s ${BOLD}%s${RESET} hosts" "Fleet" "$host_ct"
    printf "       ${PURPLEDIM}${_BULLET}${RESET} %-12s ${BOLD}%s${RESET} managed\n" "Users" "$user_ct"
    printf "    ${PURPLEDIM}${_BULLET}${RESET} %-12s ${_pve_color}%s/%s${RESET} nodes online" "Proxmox" "$_pve_up" "$_pve_tot"
    printf "  ${PURPLEDIM}${_BULLET}${RESET} %-12s ${DIM}%s${RESET}\n" "Time" "$(date '+%H:%M %b %d')"
    printf "    ${PURPLEDIM}${_BULLET}${RESET} %-12s ${DIM}%s${RESET} ${PURPLEDIM}(%s)${RESET}\n" "Operator" "$FREQ_USER" "$FREQ_ROLE"
    echo ""
    echo -e "    ${DIM}\"${tl}\"${RESET}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# COMPACT HEADER — shown on menu redraws (not first run)
# -- fresh tagline each time. keeps it alive. --
# ═══════════════════════════════════════════════════════════════════

_compact_header() {
    local tl
    tl=$(freq_tagline 2>/dev/null || echo "-- ready --")
    echo ""
    if [ "${FREQ_ASCII:-1}" = "0" ]; then
        echo -e "    ${PURPLE}${_DIAMOND}${RESET} ${BOLD}${WHITE}PVE FREQ${RESET} ${DIM}v${FREQ_VERSION}${RESET}  ${PURPLEDIM}${_DASH}${RESET}  ${DIM}${tl}${RESET}"
    else
        echo -e "    ${PURPLE}*${RESET} ${BOLD}${WHITE}PVE FREQ${RESET} ${DIM}v${FREQ_VERSION}${RESET}  ${DIM}-- ${tl}${RESET}"
    fi
    echo ""
}

# ═══════════════════════════════════════════════════════════════════
# INTERACTIVE MENU — Main TUI loop with terminal clearing
# ═══════════════════════════════════════════════════════════════════

_interactive_menu() {
    # Auto-detect Unicode for interactive mode
    _menu_detect_unicode

    local first_run=true

    while true; do
        _menu_clear

        if $first_run; then
            _splash_screen
            first_run=false
        else
            _compact_header
        fi

        freq_header "MAIN MENU"

        freq_line "  ${PURPLE}${_ICO_ZAP}${RESET} ${PURPLELIGHT}[!]${RESET}  ${BOLD}Quick Actions${RESET}       ${DIM}${_DASH} top 8 daily commands${RESET}"

        freq_divider "${BOLD}${WHITE}${_SEC_VM} VM Operations${RESET}"
        freq_line "  ${PURPLELIGHT}[v]${RESET}  ${BOLD}VM Lifecycle${RESET}        ${DIM}${_DASH} create, clone, resize, change-id, destroy${RESET}"
        freq_line "  ${PURPLELIGHT}[t]${RESET}  ${BOLD}Templates${RESET}          ${DIM}${_DASH} save and manage VM config templates${RESET}      $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[i]${RESET}  ${BOLD}Image Manager${RESET}      ${DIM}${_DASH} download and verify cloud images${RESET}         $(_tag_coming)"

        freq_divider "${BOLD}${WHITE}${_SEC_FLEET} Fleet${RESET}"
        freq_line "  ${PURPLELIGHT}[b]${RESET}  ${BOLD}Host Setup${RESET}         ${DIM}${_DASH} discover, onboard, bootstrap, harden${RESET}     $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[f]${RESET}  ${BOLD}Fleet Info${RESET}         ${DIM}${_DASH} dashboard, status, diagnose, docker${RESET}"
        freq_line "  ${PURPLELIGHT}[u]${RESET}  ${BOLD}User Management${RESET}    ${DIM}${_DASH} passwd, roles, promote, demote${RESET}            $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[x]${RESET}  ${BOLD}Run Commands${RESET}       ${DIM}${_DASH} exec on fleet, SSH keys, packages${RESET}         $(_tag_risky)"

        freq_divider "${BOLD}${WHITE}${_SEC_INFRA} Infrastructure${RESET}"
        freq_line "  ${PURPLELIGHT}[p]${RESET}  ${BOLD}Proxmox${RESET}            ${DIM}${_DASH} vm-overview, vmconfig, migrate, rescue${RESET}    $(_tag_risky)"
        freq_line "  ${PURPLELIGHT}[n]${RESET}  ${BOLD}Hosts & Groups${RESET}     ${DIM}${_DASH} host registry, groups, migrate-ip${RESET}"

        freq_divider "${BOLD}${WHITE}${_SEC_APPL} Appliances${RESET}"
        freq_line "  ${PURPLELIGHT}[F]${RESET}  ${BOLD}pfSense${RESET}            ${DIM}${_DASH} rules, NAT, logs, probe, backup${RESET}"
        freq_line "  ${PURPLELIGHT}[T]${RESET}  ${BOLD}TrueNAS${RESET}            ${DIM}${_DASH} pools, shares, alerts, snapshots${RESET}"
        freq_line "  ${PURPLELIGHT}[S]${RESET}  ${BOLD}Switch${RESET}             ${DIM}${_DASH} Cisco Catalyst ports, VLANs${RESET}"
        freq_line "  ${PURPLELIGHT}[I]${RESET}  ${BOLD}iDRAC${RESET}              ${DIM}${_DASH} server BMC, sensors, remote mgmt${RESET}"
        freq_line "  ${PURPLELIGHT}[V]${RESET}  ${BOLD}VPN${RESET}                ${DIM}${_DASH} WireGuard tunnels and peers${RESET}               $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[O]${RESET}  ${BOLD}OPNsense${RESET}           ${DIM}${_DASH} OPNsense firewall management${RESET}              $(_tag_coming)"

        freq_divider "${BOLD}${WHITE}${_SEC_MON} Monitoring & Security${RESET}"
        freq_line "  ${PURPLELIGHT}[w]${RESET}  ${BOLD}Watch${RESET}              ${DIM}${_DASH} monitoring daemon, alerts${RESET}"
        freq_line "  ${PURPLELIGHT}[j]${RESET}  ${BOLD}Journal${RESET}            ${DIM}${_DASH} operation log, history${RESET}                    $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[a]${RESET}  ${BOLD}Audit${RESET}              ${DIM}${_DASH} security audit (host or fleet)${RESET}"
        freq_line "  ${PURPLELIGHT}[K]${RESET}  ${BOLD}Vault${RESET}              ${DIM}${_DASH} encrypted credential store${RESET}"
        freq_line "  ${PURPLELIGHT}[W]${RESET}  ${BOLD}Wazuh${RESET}              ${DIM}${_DASH} SIEM agent management${RESET}                     $(_tag_coming)"

        freq_divider "${BOLD}${WHITE}${_ICO_GEAR} Engine${RESET}"
        freq_line "  ${PURPLELIGHT}[C]${RESET}  ${BOLD}Check Policy${RESET}       ${DIM}${_DASH} discover drift across fleet${RESET}"
        freq_line "  ${PURPLELIGHT}[X]${RESET}  ${BOLD}Fix Policy${RESET}         ${DIM}${_DASH} remediate drift, verify compliance${RESET}         $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[D]${RESET}  ${BOLD}Diff View${RESET}          ${DIM}${_DASH} git-style config drift diffs${RESET}"
        freq_line "  ${PURPLELIGHT}[P]${RESET}  ${BOLD}Policies${RESET}           ${DIM}${_DASH} list available remediation policies${RESET}"

        freq_divider "${BOLD}${WHITE}${_DIAMOND} Operations${RESET}"
        freq_line "  ${PURPLELIGHT}[L]${RESET}  ${BOLD}Learn${RESET}              ${DIM}${_DASH} searchable knowledge base${RESET}"
        freq_line "  ${PURPLELIGHT}[G]${RESET}  ${BOLD}Credentials${RESET}        ${DIM}${_DASH} fleet credential management${RESET}                $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[Y]${RESET}  ${BOLD}Checkpoint${RESET}         ${DIM}${_DASH} pre-change safety system${RESET}"

        freq_divider "${BOLD}${WHITE}${_SEC_UTIL} Utilities${RESET}"
        freq_line "  ${PURPLELIGHT}[d]${RESET}  ${BOLD}Doctor${RESET}             ${DIM}${_DASH} self-check FREQ installation${RESET}"
        freq_line "  ${PURPLELIGHT}[H]${RESET}  ${BOLD}Health${RESET}             ${DIM}${_DASH} DC01 infrastructure dashboard${RESET}"
        freq_line "  ${PURPLELIGHT}[M]${RESET}  ${BOLD}Media${RESET}              ${DIM}${_DASH} Plex media stack management${RESET}"
        freq_line "  ${PURPLELIGHT}[B]${RESET}  ${BOLD}Backup${RESET}             ${DIM}${_DASH} config and VM backups${RESET}                     $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[N]${RESET}  ${BOLD}Init${RESET}               ${DIM}${_DASH} initialize FREQ on this host${RESET}              $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[R]${RESET}  ${BOLD}Mounts${RESET}             ${DIM}${_DASH} NFS/SMB mount management${RESET}                  $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[h]${RESET}  ${BOLD}Help${RESET}               ${DIM}${_DASH} usage and documentation${RESET}"
        freq_line "  ${PURPLELIGHT}[e]${RESET}  ${BOLD}Version${RESET}            ${DIM}${_DASH} show version and build info${RESET}"
        freq_line "  ${DIM}[q]  Quit${RESET}"
        freq_blank
        echo -e "  ${DIM}v${FREQ_VERSION}${RESET}"
        freq_footer

        local choice
        read -rp "  Selection: " choice || { echo ""; echo -e "  ${DIM}Goodbye.${RESET}"; echo ""; exit 0; }
        case "$choice" in
            '!')  _submenu_quick_actions ;;
            v)  _submenu_vm ;;
            t)  _submenu_templates ;;
            i)  _submenu_images ;;
            b)  _submenu_host_setup ;;
            f)  _submenu_fleet_info ;;
            u)  _submenu_user_mgmt ;;
            x)  _submenu_run_commands ;;
            p)  _submenu_proxmox ;;
            n)  _submenu_hosts_groups ;;
            F)  _host=$(_menu_host_picker "pfsense")
                [ -n "$_host" ] && { _menu_run cmd_pfsense status "$_host"; _pause; } ;;
            T)  _host=$(_menu_host_picker "truenas")
                [ -n "$_host" ] && { _menu_run cmd_truenas status "$_host"; _pause; } ;;
            S)  _host=$(_menu_host_picker "switch")
                [ -n "$_host" ] && { _menu_run cmd_switch status "$_host"; _pause; } ;;
            I)  _submenu_idrac ;;
            V)  _menu_run cmd_vpn; _pause ;;
            O)  _menu_run cmd_opnsense; _pause ;;
            w)  _menu_run cmd_watch; _pause ;;
            j)  _menu_run cmd_journal; _pause ;;
            a)  _menu_run cmd_audit; _pause ;;
            K)  _submenu_vault ;;
            W)  _menu_run cmd_wazuh; _pause ;;
            C)  _menu_engine_run check ;;
            X)  _menu_engine_run fix ;;
            D)  _menu_engine_run diff ;;
            P)  _menu_engine_run policies ;;
            L)  echo ""; read -rp "    Search: " _lq; [ -n "$_lq" ] && { _menu_run cmd_learn "$_lq"; _pause; } ;;
            G)  _menu_run cmd_creds status; _pause ;;
            Y)  _menu_run cmd_checkpoint list; _pause ;;
            d)  _menu_run cmd_doctor; _pause ;;
            H)  _menu_run cmd_health; _pause ;;
            M)  _submenu_media ;;
            B)  _menu_run cmd_backup; _pause ;;
            N)  _submenu_init ;;
            R)  _menu_run cmd_mount; _pause ;;
            h)  _menu_run cmd_help; _pause ;;
            e)  _menu_run cmd_version; _pause ;;
            q|quit|exit)
                echo ""; echo -e "  ${DIM}Goodbye.${RESET}"; echo ""; exit 0 ;;
            "")
                ;; # just redraw
            *)
                echo -e "  ${YELLOW}Valid keys shown in brackets. Press a key to select.${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# QUICK ACTIONS — Top 8 daily driver commands
# ═══════════════════════════════════════════════════════════════════

_submenu_quick_actions() {
    breadcrumb_push "Quick Actions"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "QUICK ACTIONS"
        freq_blank
        freq_divider "${BOLD}${WHITE}Monitoring${RESET}"
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Dashboard${RESET}          ${DIM}${_DASH} fleet-wide monitoring overview${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Health${RESET}             ${DIM}${_DASH} DC01 infrastructure dashboard${RESET}"
        freq_divider "${BOLD}${WHITE}Inventory${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}VM Overview${RESET}        ${DIM}${_DASH} cluster-wide VM inventory${RESET}"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Docker${RESET}             ${DIM}${_DASH} container status across all VMs${RESET}"
        freq_divider "${BOLD}${WHITE}Action${RESET}"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}Fleet Exec${RESET}         ${DIM}${_DASH} run command on all hosts${RESET}              $(_tag_risky)"
        freq_line "  ${PURPLELIGHT}[6]${RESET}  ${BOLD}Host Info${RESET}          ${DIM}${_DASH} deep dive on a single host${RESET}"
        freq_divider "${BOLD}${WHITE}Diagnostic${RESET}"
        freq_line "  ${PURPLELIGHT}[7]${RESET}  ${BOLD}Diagnose${RESET}           ${DIM}${_DASH} find problems on a host${RESET}"
        freq_line "  ${PURPLELIGHT}[8]${RESET}  ${BOLD}Audit${RESET}              ${DIM}${_DASH} security scan (host or fleet)${RESET}"
        freq_blank
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|dashboard)  _menu_run cmd_dashboard; _pause ;;
            2|health)     _menu_run cmd_health; _pause ;;
            3|vm-overview) _menu_run cmd_vm_overview; _pause ;;
            4|docker)     _menu_run cmd_docker; _pause ;;
            5|exec)
                echo ""; read -rp "  Command: " _cmd
                [ -n "$_cmd" ] && { _menu_run cmd_exec "$_cmd"; _pause; } ;;
            6|info)
                echo ""; read -rp "  Host (name or IP): " _t
                [ -n "$_t" ] && { _menu_run cmd_info "$_t"; _pause; } ;;
            7|diagnose)
                echo ""; read -rp "  Host (name or IP, Enter=all): " _t
                if [ -n "$_t" ]; then
                    _menu_run cmd_diagnose "$_t"
                else
                    _menu_run cmd_diagnose
                fi; _pause ;;
            8|audit)      _menu_run cmd_audit; _pause ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-8 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: VM Lifecycle
# ═══════════════════════════════════════════════════════════════════

_submenu_vm() {
    breadcrumb_push "VM Lifecycle"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "VM Lifecycle"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Create VM${RESET}          ${DIM}${_DASH} launch the creation wizard${RESET}              $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Clone VM${RESET}           ${DIM}${_DASH} full clone an existing VM${RESET}               $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Resize VM${RESET}          ${DIM}${_DASH} change CPU/RAM (Docker-aware)${RESET}           $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Import VM${RESET}          ${DIM}${_DASH} import existing VM into FREQ${RESET}            $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}List VMs${RESET}           ${DIM}${_DASH} live cluster inventory${RESET}"
        freq_line "  ${PURPLELIGHT}[6]${RESET}  ${BOLD}VM Status${RESET}          ${DIM}${_DASH} post-creation health check${RESET}"
        freq_line "  ${PURPLELIGHT}[7]${RESET}  ${BOLD}SSH to VM${RESET}          ${DIM}${_DASH} connect directly${RESET}"
        freq_line "  ${PURPLELIGHT}[8]${RESET}  ${BOLD}Snapshot VM${RESET}        ${DIM}${_DASH} take a quick snapshot${RESET}                   $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[9]${RESET}  ${BOLD}Destroy VM${RESET}         ${DIM}${_DASH} safely remove a VM${RESET}                      $(_tag_destructive)"
        freq_line "  ${PURPLELIGHT}[c]${RESET}  ${BOLD}Change ID${RESET}          ${DIM}${_DASH} rename a VM's VMID${RESET}                      $(_tag_risky)"
        freq_line "  ${PURPLELIGHT}[n]${RESET}  ${BOLD}NIC Config${RESET}         ${DIM}${_DASH} reconfigure VM network interface${RESET}        $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[s]${RESET}  ${BOLD}Start VM${RESET}           ${DIM}${_DASH} power on a VM${RESET}"
        freq_line "  ${PURPLELIGHT}[o]${RESET}  ${BOLD}Stop VM${RESET}            ${DIM}${_DASH} power off a VM${RESET}                          $(_tag_risky)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|create)   _menu_run cmd_create; _pause ;;
            2|clone)
                echo ""; read -rp "  Source VMID: " _svmid
                if [ -n "$_svmid" ]; then
                    read -rp "  New name: " _nname
                    [ -n "$_nname" ] && { _menu_run cmd_clone "$_svmid" "$_nname"; _pause; }
                fi ;;
            3|resize)
                echo ""; read -rp "  VMID to resize: " _t
                [ -n "$_t" ] && { _menu_run cmd_resize "$_t"; _pause; } ;;
            4|import)
                echo ""; read -rp "  VMID to import: " _t
                [ -n "$_t" ] && { _menu_run cmd_import "$_t"; _pause; } ;;
            5|list)     _menu_run cmd_list; _pause ;;
            6|status)
                echo ""; read -rp "  VMID or name: " _t
                [ -n "$_t" ] && { _menu_run cmd_vm_status "$_t"; _pause; } ;;
            7|ssh)
                echo ""; read -rp "  VMID or name: " _t
                [ -n "$_t" ] && cmd_ssh_vm "$_t" ;;
            8|snapshot)
                echo ""; read -rp "  VMID: " _t
                [ -n "$_t" ] && { _menu_run cmd_snapshot "$_t"; _pause; } ;;
            9|destroy)
                echo ""; read -rp "  VMID to destroy: " _vmid
                [ -n "$_vmid" ] && { _menu_run cmd_destroy "$_vmid"; _pause; } ;;
            c|change-id)
                echo ""; read -rp "  Current VMID: " _old
                if [ -n "$_old" ]; then
                    read -rp "  New VMID: " _new
                    [ -n "$_new" ] && { _menu_run cmd_vm change-id "$_old" "$_new"; _pause; }
                fi ;;
            n|nic)
                echo ""; read -rp "  VMID: " _t
                [ -n "$_t" ] && { _menu_run cmd_vm nic "$_t"; _pause; } ;;
            s|start)
                echo ""; read -rp "  VMID: " _t
                [ -n "$_t" ] && { _menu_run cmd_vm start "$_t"; _pause; } ;;
            o|stop)
                echo ""; read -rp "  VMID: " _t
                [ -n "$_t" ] && { _menu_run cmd_vm stop "$_t"; _pause; } ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-9/c/n/s/o or 0 to go back${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Host Setup
# ═══════════════════════════════════════════════════════════════════

_submenu_host_setup() {
    breadcrumb_push "Host Setup"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Host Setup"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Discover VMs${RESET}       ${DIM}${_DASH} scan PVE cluster for unregistered VMs${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Onboard New Host${RESET}   ${DIM}${_DASH} add + bootstrap + configure + provision${RESET}  $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Bootstrap${RESET}          ${DIM}${_DASH} deploy ${FREQ_SERVICE_ACCOUNT} + SSH keys to a host${RESET}   $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Provision Accounts${RESET} ${DIM}${_DASH} deploy fleet users to a host${RESET}            $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}Configure${RESET}          ${DIM}${_DASH} SSH hardening, hostname, packages${RESET}       $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[6]${RESET}  ${BOLD}Harden${RESET}             ${DIM}${_DASH} security hardening (SSH, firewall)${RESET}      $(_tag_coming)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|discover)   _menu_run cmd_discover; _pause ;;
            2|onboard)    _menu_run cmd_onboard; _pause ;;
            3|bootstrap)
                echo ""; read -rp "  Host (IP or label): " _ip
                if [ -n "$_ip" ]; then
                    _menu_run cmd_bootstrap "$_ip"; _pause
                fi ;;
            4|provision)  _menu_run cmd_provision; _pause ;;
            5|configure)  _menu_run cmd_configure; _pause ;;
            6|harden)     _menu_run cmd_harden; _pause ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-6 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Fleet Info
# ═══════════════════════════════════════════════════════════════════

_submenu_fleet_info() {
    breadcrumb_push "Fleet Info"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Fleet Info"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Dashboard${RESET}          ${DIM}${_DASH} mini-monitoring overview${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Fleet Status${RESET}       ${DIM}${_DASH} SSH ping all hosts${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Host Info${RESET}          ${DIM}${_DASH} detailed info for one host${RESET}"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Diagnose${RESET}           ${DIM}${_DASH} deep diagnostic scan${RESET}"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}Docker${RESET}             ${DIM}${_DASH} container status and management${RESET}"
        freq_line "  ${PURPLELIGHT}[6]${RESET}  ${BOLD}Log${RESET}                ${DIM}${_DASH} view recent fleet activity${RESET}"
        freq_line "  ${PURPLELIGHT}[7]${RESET}  ${BOLD}Operator Mode${RESET}      ${DIM}${_DASH} switch operator context${RESET}"
        freq_line "  ${PURPLELIGHT}[8]${RESET}  ${BOLD}SSH Mode${RESET}           ${DIM}${_DASH} configure SSH auth method${RESET}               $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[9]${RESET}  ${BOLD}Registry${RESET}           ${DIM}${_DASH} container registry management${RESET}           $(_tag_coming)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|dashboard)  _menu_run cmd_dashboard; _pause ;;
            2|status)     _menu_run cmd_fleet_status; _pause ;;
            3|info)
                echo ""; read -rp "  Host (name or IP): " _t
                [ -n "$_t" ] && { _menu_run cmd_info "$_t"; _pause; } ;;
            4|diagnose)
                echo ""; read -rp "  Host (name or IP, Enter=all): " _t
                if [ -n "$_t" ]; then
                    _menu_run cmd_diagnose "$_t"
                else
                    _menu_run cmd_diagnose
                fi; _pause ;;
            5|docker)     _menu_run cmd_docker; _pause ;;
            6|log)        _menu_run cmd_log; _pause ;;
            7|operator)   _menu_run cmd_operator; _pause ;;
            8|ssh-mode)   _menu_run cmd_fleet_ssh_mode; _pause ;;
            9|registry)   _menu_run cmd_registry; _pause ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-9 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: User Management
# ═══════════════════════════════════════════════════════════════════

_submenu_user_mgmt() {
    breadcrumb_push "User Management"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "User Management"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}New User Wizard${RESET}    ${DIM}${_DASH} register + deploy fleet-wide${RESET}         $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Password Change${RESET}    ${DIM}${_DASH} change password fleet-wide${RESET}            $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}User Registry${RESET}      ${DIM}${_DASH} list, add, remove users${RESET}"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Roles${RESET}              ${DIM}${_DASH} view role assignments${RESET}"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}Promote${RESET}            ${DIM}${_DASH} elevate user to higher role${RESET}           $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[6]${RESET}  ${BOLD}Demote${RESET}             ${DIM}${_DASH} lower user role${RESET}                       $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[7]${RESET}  ${BOLD}Install User${RESET}       ${DIM}${_DASH} deploy user to specific host${RESET}          $(_tag_changes)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|new-user)   _menu_run cmd_new_user; _pause ;;
            2|passwd)
                echo ""; read -rp "  Username: " _u
                [ -n "$_u" ] && { _menu_run cmd_passwd "$_u"; _pause; } ;;
            3|users)      _menu_run cmd_users; _pause ;;
            4|roles)      _menu_run cmd_roles; _pause ;;
            5|promote)
                echo ""; read -rp "  Username: " _u
                [ -n "$_u" ] && { _menu_run cmd_promote "$_u"; _pause; } ;;
            6|demote)
                echo ""; read -rp "  Username: " _u
                [ -n "$_u" ] && { _menu_run cmd_demote "$_u"; _pause; } ;;
            7|install-user)
                echo ""; read -rp "  Username: " _u
                if [ -n "$_u" ]; then
                    read -rp "  Target host: " _h
                    [ -n "$_h" ] && { _menu_run cmd_install_user "$_u" "$_h"; _pause; }
                fi ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-7 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Proxmox
# ═══════════════════════════════════════════════════════════════════

_submenu_proxmox() {
    breadcrumb_push "Proxmox"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Proxmox"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}VM Overview${RESET}        ${DIM}${_DASH} live cluster VM inventory${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}VM Config${RESET}          ${DIM}${_DASH} view/edit VM configuration${RESET}            $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Migrate${RESET}            ${DIM}${_DASH} move VM between nodes${RESET}                 $(_tag_risky)"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Rescue${RESET}             ${DIM}${_DASH} boot VM from rescue ISO${RESET}               $(_tag_risky)"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}ZFS${RESET}                ${DIM}${_DASH} pool status, health, scrub${RESET}            $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[6]${RESET}  ${BOLD}Serial Console${RESET}     ${DIM}${_DASH} access serial console on host${RESET}         $(_tag_coming)"
        freq_line "  ${PURPLELIGHT}[7]${RESET}  ${BOLD}PDM${RESET}                ${DIM}${_DASH} Proxmox Datacenter Manager${RESET}            $(_tag_coming)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|vm-overview) _menu_run cmd_vm_overview; _pause ;;
            2|vmconfig)
                echo ""; read -rp "  VMID: " _t
                [ -n "$_t" ] && { _menu_run cmd_vmconfig "$_t"; _pause; } ;;
            3|migrate)
                echo ""; read -rp "  VMID: " _t
                [ -n "$_t" ] && { _menu_run cmd_migrate "$_t"; _pause; } ;;
            4|rescue)
                echo ""; read -rp "  VMID: " _t
                [ -n "$_t" ] && { _menu_run cmd_rescue "$_t"; _pause; } ;;
            5|zfs)      _menu_run cmd_zfs; _pause ;;
            6|serial)   _menu_run cmd_serial; _pause ;;
            7|pdm)      _menu_run cmd_pdm; _pause ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-7 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Run Commands
# ═══════════════════════════════════════════════════════════════════

_submenu_run_commands() {
    local _sticky_target=""
    breadcrumb_push "Run Commands"

    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Run Commands"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Fleet Exec${RESET}         ${DIM}${_DASH} run command on all hosts${RESET}             $(_tag_risky)"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Single Host Exec${RESET}   ${DIM}${_DASH} run command on one host${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Key Deploy${RESET}         ${DIM}${_DASH} deploy SSH keys${RESET}                      $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Key Audit${RESET}          ${DIM}${_DASH} audit SSH key status${RESET}"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}Packages${RESET}           ${DIM}${_DASH} check and install packages${RESET}           $(_tag_coming)"
        if [ -n "$_sticky_target" ]; then
            freq_line "  ${DIM}Target: ${_sticky_target} (sticky)${RESET}"
        fi
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|exec)
                echo ""; read -rp "  Command: " _cmd
                [ -n "$_cmd" ] && { _menu_run cmd_exec "$_cmd"; _pause; } ;;
            2|single)
                if [ -z "$_sticky_target" ]; then
                    echo ""; read -rp "  Host (name or IP): " _sticky_target
                fi
                if [ -n "$_sticky_target" ]; then
                    echo ""; read -rp "  Command: " _cmd
                    [ -n "$_cmd" ] && { _menu_run cmd_exec -h "$_sticky_target" "$_cmd"; _pause; }
                fi ;;
            3|keys)       _menu_run cmd_keys deploy; _pause ;;
            4|key-audit)  _menu_run cmd_keys audit; _pause ;;
            5|packages)   _submenu_packages ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-5 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Templates
# ═══════════════════════════════════════════════════════════════════

_submenu_templates() {
    breadcrumb_push "Templates"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Templates"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}List templates${RESET}     ${DIM}${_DASH} show saved templates${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Save template${RESET}      ${DIM}${_DASH} save a VM config as template${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Create from template${RESET} ${DIM}${_DASH} create VM using saved defaults${RESET}"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|list)     _menu_run cmd_templates list; _pause ;;
            2|save)
                echo ""
                read -rp "  Source VMID: " _svmid
                if [ -n "$_svmid" ]; then
                    read -rp "  Template name: " _tname
                    [ -n "$_tname" ] && { _menu_run cmd_templates save "$_svmid" "$_tname"; _pause; }
                fi ;;
            3|create)
                echo ""
                _menu_run cmd_templates list
                read -rp "  Template name: " _tname
                [ -n "$_tname" ] && { _menu_run cmd_create --template "$_tname"; _pause; }
                ;;
            0|b|back)   breadcrumb_pop; return ;;
            "")         ;;
            *)          echo -e "  ${YELLOW}Pick 1-3 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Image Manager
# ═══════════════════════════════════════════════════════════════════

_submenu_images() {
    breadcrumb_push "Image Manager"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Image Manager"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}List images${RESET}        ${DIM}${_DASH} show cloud image status${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Download images${RESET}    ${DIM}${_DASH} download cloud images${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Verify images${RESET}      ${DIM}${_DASH} check SHA256 checksums${RESET}"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Distros${RESET}            ${DIM}${_DASH} list supported distributions${RESET}"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|list)     _menu_run cmd_images list; _pause ;;
            2|download)
                echo ""
                echo -e "  ${DIM}Distros: ubuntu, debian, rocky, alma, all${RESET}"
                read -rp "  Download which? " _distro
                [ -n "$_distro" ] && { _menu_run cmd_images download "$_distro"; _pause; }
                ;;
            3|verify)   _menu_run cmd_images verify; _pause ;;
            4|distros)  _menu_run cmd_distros; _pause ;;
            0|b|back)   breadcrumb_pop; return ;;
            "")         ;;
            *)          echo -e "  ${YELLOW}Pick 1-4 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Hosts & Groups
# ═══════════════════════════════════════════════════════════════════

_submenu_hosts_groups() {
    breadcrumb_push "Hosts & Groups"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Hosts & Groups"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Host Registry${RESET}      ${DIM}${_DASH} list, add, remove hosts${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Groups${RESET}             ${DIM}${_DASH} view host groups${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Discover VMs${RESET}       ${DIM}${_DASH} scan PVE for unregistered VMs${RESET}"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Migrate IP${RESET}         ${DIM}${_DASH} change a host's IP fleet-wide${RESET}          $(_tag_changes)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|hosts)    _menu_run cmd_hosts; _pause ;;
            2|groups)   _menu_run cmd_groups; _pause ;;
            3|discover) _menu_run cmd_discover; _pause ;;
            4|migrate-ip)
                echo ""; read -rp "  Host label: " _h
                if [ -n "$_h" ]; then
                    read -rp "  New IP: " _ip
                    [ -n "$_ip" ] && { _menu_run cmd_migrate_ip "$_h" "$_ip"; _pause; }
                fi ;;
            0|b|back)   breadcrumb_pop; return ;;
            "")         ;;
            *)          echo -e "  ${YELLOW}Pick 1-4 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: iDRAC (NEW)
# ═══════════════════════════════════════════════════════════════════

_submenu_idrac() {
    breadcrumb_push "iDRAC"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "iDRAC Remote Management"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Sensor Data${RESET}        ${DIM}${_DASH} temperatures, fans, voltages${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}System Info${RESET}        ${DIM}${_DASH} hardware inventory${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}SEL (Event Log)${RESET}   ${DIM}${_DASH} system event log${RESET}"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Power Status${RESET}      ${DIM}${_DASH} power state and consumption${RESET}"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|sensors)
                echo -e "  ${DIM}Select iDRAC target:${RESET}"
                echo -e "    ${PURPLELIGHT}[1]${RESET} R530  ${DIM}(10.25.255.10)${RESET}"
                echo -e "    ${PURPLELIGHT}[2]${RESET} T620  ${DIM}(10.25.255.11)${RESET}"
                local _ic
                read -rp "  Selection: " _ic
                case "$_ic" in
                    1) _menu_run cmd_idrac sensors r530; _pause ;;
                    2) _menu_run cmd_idrac sensors t620; _pause ;;
                esac ;;
            2|info)
                echo -e "  ${DIM}Select: [1] R530  [2] T620${RESET}"
                local _ic; read -rp "  Selection: " _ic
                case "$_ic" in
                    1) _menu_run cmd_idrac info r530; _pause ;;
                    2) _menu_run cmd_idrac info t620; _pause ;;
                esac ;;
            3|sel)
                echo -e "  ${DIM}Select: [1] R530  [2] T620${RESET}"
                local _ic; read -rp "  Selection: " _ic
                case "$_ic" in
                    1) _menu_run cmd_idrac sel r530; _pause ;;
                    2) _menu_run cmd_idrac sel t620; _pause ;;
                esac ;;
            4|power)
                echo -e "  ${DIM}Select: [1] R530  [2] T620${RESET}"
                local _ic; read -rp "  Selection: " _ic
                case "$_ic" in
                    1) _menu_run cmd_idrac power r530; _pause ;;
                    2) _menu_run cmd_idrac power t620; _pause ;;
                esac ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-4 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Vault (NEW)
# ═══════════════════════════════════════════════════════════════════

_submenu_vault() {
    breadcrumb_push "Vault"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Credential Vault"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}List Secrets${RESET}       ${DIM}${_DASH} show stored credential keys${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Get Secret${RESET}         ${DIM}${_DASH} retrieve a stored credential${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Set Secret${RESET}         ${DIM}${_DASH} store or update a credential${RESET}          $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Delete Secret${RESET}      ${DIM}${_DASH} remove a stored credential${RESET}            $(_tag_destructive)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|list)   _menu_run cmd_vault list; _pause ;;
            2|get)
                echo ""; read -rp "  Secret name: " _k
                [ -n "$_k" ] && { _menu_run cmd_vault get "$_k"; _pause; } ;;
            3|set)
                echo ""; read -rp "  Secret name: " _k
                if [ -n "$_k" ]; then
                    read -rsp "  Secret value: " _v; echo ""
                    [ -n "$_v" ] && { _menu_run cmd_vault set "$_k" "$_v"; _pause; }
                fi ;;
            4|delete)
                echo ""; read -rp "  Secret name: " _k
                [ -n "$_k" ] && { _menu_run cmd_vault delete "$_k"; _pause; } ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-4 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Init (NEW)
# ═══════════════════════════════════════════════════════════════════

_submenu_init() {
    breadcrumb_push "Init"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "System Initialization"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Full Init${RESET}          ${DIM}${_DASH} run complete FREQ setup${RESET}               $(_tag_changes)"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Check Only${RESET}         ${DIM}${_DASH} dry run, show what would change${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Reset${RESET}              ${DIM}${_DASH} reset FREQ to factory defaults${RESET}         $(_tag_destructive)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|init)   _menu_run cmd_init; _pause ;;
            2|check)  _menu_run cmd_init --check; _pause ;;
            3|reset)  _menu_run cmd_init --reset; _pause ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-3 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Packages (nested under Run Commands)
# ═══════════════════════════════════════════════════════════════════

_submenu_packages() {
    breadcrumb_push "Packages"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Packages"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}List${RESET}               ${DIM}${_DASH} show default package set${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Check${RESET}              ${DIM}${_DASH} audit hosts for missing defaults${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Install${RESET}            ${DIM}${_DASH} install packages on hosts${RESET}             $(_tag_changes)"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|list)     _menu_run cmd_packages list; _pause ;;
            2|check)
                echo ""
                echo -e "    ${DIM}Target: [Enter]=all, or comma-separated host names${RESET}"
                read -rp "    Hosts: " _hosts
                if [ -n "$_hosts" ]; then
                    _menu_run cmd_packages check "$_hosts"
                else
                    _menu_run cmd_packages check
                fi
                _pause ;;
            3|install)
                require_operator || return 1
                echo ""
                echo -e "    ${DIM}Packages to install (space-separated):${RESET}"
                read -rp "    Packages: " _pkgs
                [ -z "$_pkgs" ] && { echo -e "    ${YELLOW}No packages specified.${RESET}"; continue; }
                echo -e "    ${DIM}Target: [Enter]=all, host name, or group name${RESET}"
                read -rp "    Target: " _target
                local _args=()
                if [ -n "$_target" ]; then
                    if grep -q "^${_target}:" "$GROUPS_FILE" 2>/dev/null; then
                        _args=(-g "$_target")
                    else
                        _args=(-h "$_target")
                    fi
                fi
                _menu_run cmd_packages install "${_args[@]}" $_pkgs
                _pause ;;
            0|b|back) breadcrumb_pop; return ;;
            "")       ;;
            *)        echo -e "  ${YELLOW}Pick 1-3 or 0${RESET}"; sleep 1 ;;
        esac
    done
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU: Media Stack
# ═══════════════════════════════════════════════════════════════════

_submenu_media() {
    breadcrumb_push "Media Stack"
    while true; do
        _menu_clear
        breadcrumb_render
        freq_header "Media Stack"
        freq_blank
        freq_line "  ${PURPLELIGHT}[1]${RESET}  ${BOLD}Doctor${RESET}             ${DIM}${_DASH} comprehensive health check${RESET}"
        freq_line "  ${PURPLELIGHT}[2]${RESET}  ${BOLD}Container Status${RESET}   ${DIM}${_DASH} container states across VMs${RESET}"
        freq_line "  ${PURPLELIGHT}[3]${RESET}  ${BOLD}Container Inventory${RESET} ${DIM}${_DASH} full inventory with images${RESET}"
        freq_line "  ${PURPLELIGHT}[4]${RESET}  ${BOLD}Disk${RESET}               ${DIM}${_DASH} storage capacity${RESET}"
        freq_line "  ${PURPLELIGHT}[5]${RESET}  ${BOLD}Activity${RESET}           ${DIM}${_DASH} live activity summary${RESET}"
        freq_line "  ${DIM}[0]  Back${RESET}"
        freq_blank
        freq_footer

        local choice
        read -rp "  Selection: " choice || { breadcrumb_pop; return; }
        case "${choice,,}" in
            1|doctor)      _menu_run cmd_media doctor; _pause ;;
            2|status)      _menu_run cmd_media status; _pause ;;
            3|containers)  _menu_run cmd_media containers; _pause ;;
            4|disk)        _menu_run cmd_media disk; _pause ;;
            5|activity)    _menu_run cmd_media activity; _pause ;;
            0|b|back) breadcrumb_pop; return ;;
            "") ;;
            *)  echo -e "  ${YELLOW}Pick 1-5 or 0${RESET}"; sleep 1 ;;
        esac
    done
}
