# ~/.bashrc — freq-ops@nexus (DC01 Command Center)
case $- in
    *i*) ;;
      *) return;;
esac
HISTCONTROL=ignoreboth
HISTSIZE=10000
HISTFILESIZE=20000
shopt -s histappend
shopt -s checkwinsize

PS1="\[\033[1;38;2;234;179;8m\]freq-ops\[\033[0m\]\[\033[38;2;110;118;129m\]@\[\033[0m\]\[\033[1;38;2;234;179;8m\]nexus\[\033[0m\]\[\033[38;2;110;118;129m\]:\[\033[0m\]\[\033[38;2;234;179;8m\]\w\[\033[0m\]\[\033[38;2;110;118;129m\] \$\[\033[0m\] "

alias ll="ls -alF --color=auto"
alias la="ls -A --color=auto"
alias l="ls -CF --color=auto"
alias ls="ls --color=auto"
alias grep="grep --color=auto"
## nexus-* commands are in /usr/local/bin/ — do NOT alias to $HOME copies

export PATH="/home/freq-ops/.venv/bin:/home/freq-ops/.local/bin:$PATH"

if [ -f /home/freq-ops/.venv/bin/activate ]; then
    source /home/freq-ops/.venv/bin/activate
fi

_nexus_banner() {
    # ── Colors ──
    local GD='\033[38;2;234;179;8m'      # Gold (borders, section headers, dots)
    local DG='\033[38;5;245m'             # Dark gray (labels, descriptions)
    local W='\033[1;97m'                  # White bold (values)
    local R='\033[0m'                     # Reset
    local JV='\033[38;2;255;166;43m'      # Orange (JARVIS)
    local RK='\033[38;2;155;79;222m'      # Purple (RICK)
    local MT='\033[38;2;220;38;38m'       # Red (MORTY)
    local LV='\033[38;2;63;185;80m'       # Green (LIVE indicator)
    local DN='\033[38;2;180;30;30m'       # Red (DOWN indicator)
    local PP='\033[38;2;123;47;190m'      # Purple brand (#7B2FBE)

    # ── Layout: 109 content width → 119 total visible per line ──
    local WIDTH=109
    local BAR_W=115

    # ── Vertical border: 25 lines, ☼ at corners (0,8,16,24) ──
    local -a VP=('☼' '·' '•' '·' '◉' '·' '•' '·' '☼' '·' '•' '·' '◉' '·' '•' '·' '☼' '·' '•' '·' '◉' '·' '•' '·' '☼')
    local _vi=0

    # ── Line renderers ──
    _N() {
        local raw="$1"
        local stripped=$(echo -e "$raw" | sed 's/\x1b\[[0-9;]*m//g')
        local vlen=${#stripped}
        local pad=$((WIDTH - vlen))
        [ $pad -lt 0 ] && pad=0
        local spaces=$(printf "%${pad}s" '')
        local b="${VP[$_vi]}"
        _vi=$((_vi + 1))
        echo -e "  ${GD}│ ${b} ${R}${raw}${spaces}${GD} ${b} │${R}"
    }

    _NC() {
        local raw="$1"
        local stripped=$(echo -e "$raw" | sed 's/\x1b\[[0-9;]*m//g')
        local vlen=${#stripped}
        local total_pad=$((WIDTH - vlen))
        [ $total_pad -lt 0 ] && total_pad=0
        local left_pad=$((total_pad / 2))
        local right_pad=$((total_pad - left_pad))
        local lspaces=$(printf "%${left_pad}s" '')
        local rspaces=$(printf "%${right_pad}s" '')
        local b="${VP[$_vi]}"
        _vi=$((_vi + 1))
        echo -e "  ${GD}│ ${b} ${R}${lspaces}${raw}${rspaces}${GD} ${b} │${R}"
    }

    _BAR() { echo -e "  ${GD}$1$(printf '═%.0s' $(seq 1 $BAR_W))$2${R}"; }

    # ── SUN pattern (starts with · to avoid double-☼ with VP border) ──
    local SUN="· • · ◉ · • · ☼ · • · ◉ · • · ☼ · • · ◉ · • · ☼ · • · ◉ · • · ☼ · • · ◉ · • · ☼ · • · ◉ · • · ☼ · • · ◉ · • ·"

    # ── Generate WAVE pattern (fills WIDTH exactly) ──
    local WAVE="" _wi=0
    local -a _WV=('~' '∿')
    while [ ${#WAVE} -lt $WIDTH ]; do
        [ ${#WAVE} -gt 0 ] && WAVE+=" "
        [ ${#WAVE} -ge $WIDTH ] && break
        WAVE+="${_WV[$((_wi % 2))]}"
        _wi=$((_wi + 1))
    done

    # ── Live data ──
    local SRV=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 0.3 --max-time 0.5 http://localhost:8888/ 2>/dev/null)
    local WD=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 0.3 --max-time 0.5 http://localhost:9900/api/watchdog/health 2>/dev/null)
    [ "$SRV" = "200" ] && local DS="${LV}LIVE${R}" || local DS="${DN}DOWN${R}"
    [ "$WD" = "200" ]  && local WS="${LV}LIVE${R}" || local WS="${DN}DOWN${R}"

    local _CACHE="/tmp/.nexus-fleet-cache"
    local _HEALTH=$(curl -s --connect-timeout 0.3 --max-time 0.5 http://localhost:8888/api/health 2>/dev/null)
    local _QUICK=$(curl -s --connect-timeout 0.3 --max-time 0.5 http://localhost:8888/api/infra/quick 2>/dev/null)
    local F_HOSTS=0 F_NODES=0 F_CONTAINERS=0 F_INFRA=0 F_VMS=0 F_VLANS=7
    if [ -n "$_HEALTH" ]; then
        read F_HOSTS F_NODES F_CONTAINERS F_VMS <<< $(echo "$_HEALTH" | python3 -c "
import json,sys
d=json.load(sys.stdin);h=d.get('hosts',[])
vms=sum(1 for x in h if x.get('type') in ('pve',))
print(len(h), sum(1 for x in h if x.get('type')=='pve' and x.get('status')=='healthy'), sum(int(x.get('docker',0)) for x in h), len(h))
" 2>/dev/null)
        [ -n "$_QUICK" ] && F_INFRA=$(echo "$_QUICK" | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('devices',[])))" 2>/dev/null || echo 0)
        # Cache last known good values
        echo "$F_HOSTS $F_NODES $F_CONTAINERS $F_INFRA $F_VMS $F_VLANS" > "$_CACHE" 2>/dev/null
    elif [ -f "$_CACHE" ]; then
        # Dashboard down — use last known values
        read F_HOSTS F_NODES F_CONTAINERS F_INFRA F_VMS F_VLANS < "$_CACHE" 2>/dev/null
    fi

    local TOTAL_LOGINS=$(last -a 2>/dev/null | grep -v "reboot\|wtmp\|^$" | wc -l)
    local TOTAL_HOURS=$(last -a 2>/dev/null | grep -v "reboot\|wtmp\|^$\|still" | awk -F'[()]' '{print $2}' | awk -F: '{h+=$1; m+=$2} END {h+=int(m/60); printf "%dh", h}')
    local LAST_USER=$(last -1 -a 2>/dev/null | head -1 | awk '{print $1}')

    # ── Formatted values (fixed widths for column alignment) ──
    local _fn=$(printf "%3s" "$F_NODES")
    local _fh=$(printf "%-3s" "$F_HOSTS")
    local _fv=$(printf "%3s" "$F_VMS")
    local _fl=$(printf "%-3s" "$F_VLANS")
    local _fc=$(printf "%3s" "$F_CONTAINERS")
    local _fi=$(printf "%-3s" "$F_INFRA")
    local _ul=$(printf "%-5s" "$TOTAL_LOGINS")
    local _uh=$(printf "%-5s" "$TOTAL_HOURS")
    local _uu=$(printf "%-12s" "$LAST_USER")

    # ── Column gaps: Fleet ends@31, Status@45, Uplink@78 ──
    printf -v G1 '%14s' ''     # Fleet(31) → Status(45): 14
    printf -v G2 '%15s' ''     # Status end(63) → Uplink(78): 15
    printf -v G3 '%47s' ''     # Fleet(31) → Uplink(78) no status: 47
    printf -v H1 '%38s' ''     # "  FLEET"(7) → Status(45): 38
    printf -v H2 '%27s' ''     # "STATUS"(6)@45 → Uplink(78): 27

    # ══════════════════════════════════════════════════════════════════
    #  RENDER — 25 content lines between top bar and bottom bar
    # ══════════════════════════════════════════════════════════════════
    echo ""
    _BAR "╔" "╗"

    # ── Header (7 lines) ──
    _N  "${GD}${SUN}${R}"
    _N  ""
    _NC "${JV}◆${RK}◆${MT}◆${R}  ${GD}N  E  X  U  S${R}  ${MT}◆${RK}◆${JV}◆${R}"
    _N  ""
    _NC "${DG}DC01 COMMAND CENTER${R}  ${GD}·${R}  ${DG}VM 999${R}  ${GD}·${R}  ${DG}THE CONVERGENCE${R}"
    _N  ""
    _N  "${PP}${WAVE}${R}"

    # ── Agents (7 lines) ──
    _BAR "╠" "╣"
    _N  ""
    _N  "  ${GD}AGENTS${R}"
    _N  ""
    _N  "  ${JV}◆ JARVIS${R}   ${DG}Infra Operator${R}    ${GD}·${R}  ${DG}Fleet Authority${R}    ${GD}·${R}  ${W}Lead Agent${R}"
    _N  "  ${RK}◆ RICK${R}     ${DG}Lead Developer${R}    ${GD}·${R}  ${DG}Dashboard + Code${R}   ${GD}·${R}  ${DG}Subagent${R}"
    _N  "  ${MT}◆ MORTY${R}    ${DG}Daemon Builder${R}    ${GD}·${R}  ${DG}WATCHDOG + Tests${R}   ${GD}·${R}  ${DG}Subagent${R}"
    _N  ""

    # ── Fleet / Status / Uplink (7 lines) ──
    _BAR "╠" "╣"
    _N  ""
    _N  "  ${GD}FLEET${R}${H1}${GD}STATUS${R}${H2}${GD}UPLINK${R}"
    _N  ""
    _N  "  ${DG}Nodes${R}      ${W}${_fn}${R}  ${GD}·${R}  ${DG}Hosts${R}  ${W}${_fh}${R}${G1}${DG}Dashboard${R}  ${GD}·${R}  ${DS}${G2}${DG}Logins${R}  ${W}${_ul}${R}"
    _N  "  ${DG}VMs${R}        ${W}${_fv}${R}  ${GD}·${R}  ${DG}VLANs${R}  ${W}${_fl}${R}${G1}${DG}WATCHDOG${R}   ${GD}·${R}  ${WS}${G2}${DG}Hours${R}   ${W}${_uh}${R}"
    _N  "  ${DG}Containers${R} ${W}${_fc}${R}  ${GD}·${R}  ${DG}Infra${R}  ${W}${_fi}${R}${G3}${DG}Last${R}    ${W}${_uu}${R}"
    _N  ""

    # ── Footer (1 line) ──
    _N  "${GD}${SUN}${R}"

    _BAR "╚" "╝"

    # ── Footer (centered, brand purple, uppercase) ──
    local _ftxt="««« LOW FREQUENCY LABS DID NOT COME TO PLAY »»»"
    local _flen=${#_ftxt}
    local _fbox=$((BAR_W + 4))
    local _fpad=$(( (_fbox - _flen) / 2 ))
    echo ""
    echo -e "$(printf "%${_fpad}s" '')${PP}${_ftxt}${R}"
    echo ""
}

# ── Live-updating dashboard — type "nexus" to start, Ctrl+C to exit ──
nexus() {
    local _old_stty _frame _running=1
    _old_stty=$(stty -g 2>/dev/null)
    trap '_running=0' INT TERM
    tput civis 2>/dev/null
    stty -echo -icanon min 0 time 0 2>/dev/null
    clear
    while [ "$_running" -eq 1 ]; do
        _frame=$(_nexus_banner 2>/dev/null) || true
        [ "$_running" -eq 0 ] && break
        printf '\033[H%s\033[J' "$_frame"
        while IFS= read -r -s -n 1 -t 0 2>/dev/null; do :; done
        read -t 10 -s -n 1 2>/dev/null || true
        while IFS= read -r -s -n 1 -t 0 2>/dev/null; do :; done
    done
    stty "$_old_stty" 2>/dev/null
    tput cnorm 2>/dev/null
    trap - INT TERM
    echo
}

## Dashboard available via 'nexus' command — do NOT auto-run (blocks Claude Code)
