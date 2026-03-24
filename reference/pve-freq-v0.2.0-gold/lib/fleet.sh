#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/fleet.sh
# Fleet Operations — dashboard, status, info, diagnose, docker, exec, log, ssh
#
# Author:  FREQ Project
# -- the morning check. coffee in hand. how's everyone doing. --
# Commands: cmd_dashboard, cmd_fleet_status, cmd_info, cmd_diagnose,
#           cmd_docker, cmd_exec, cmd_log, cmd_ssh_vm, cmd_keys,
#           cmd_bootstrap, cmd_onboard, cmd_migrate_ip, cmd_operator,
#           cmd_fleet_ssh_mode
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh, hosts.sh, validate.sh
# =============================================================================

# shellcheck disable=SC2154
# HOST_IPS, HOST_LABELS, HOST_TYPES, HOST_GROUPS, HOST_COUNT, FOUND_IDX,
# FREQ_USER, FREQ_ROLE, SSH_OPTS, FREQ_KEY_PATH, REMOTE_USER, HOSTS_FILE,
# FREQ_LOG, FREQ_BUILD, DC01_TIMEZONE, SVC_UID, SVC_GID, FREQ_SSH_KEY,
# MAX_PARALLEL, FREQ_SERVICE_ACCOUNT, FREQ_GROUP — set by core.sh/resolve.sh/freq.conf

# ═══════════════════════════════════════════════════════════════════
# HELPER: Check if host at index $1 belongs to group $2
# ═══════════════════════════════════════════════════════════════════
_fleet_host_in_group() {
    local idx="$1" group="$2"
    echo "${HOST_GROUPS[$idx]}" | grep -qw "$group" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# DASHBOARD — Fleet-wide overview (ping + resource summary)
# ═══════════════════════════════════════════════════════════════════
cmd_dashboard() {
    require_operator || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts registered. Run 'freq hosts add' first."

    local show_help=false
    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help) show_help=true; shift ;;
            *) shift ;;
        esac
    done

    if $show_help; then
        echo "Usage: freq dashboard"
        echo ""
        echo "Show a fleet-wide infrastructure dashboard with host status,"
        echo "resource usage, and Docker container counts."
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    echo ""
    freq_header "${PACK_DASHBOARD_HEADER:-Dashboard}"
    echo ""

    local tmpdir
    tmpdir=$(mktemp -d /tmp/freq-dash.XXXXXX) || die "Cannot create temp dir."

    # Parallel probe all hosts
    local running=0
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        local ip="${HOST_IPS[$i]}" htype="${HOST_TYPES[$i]}"
        (
            local result="DOWN|||"
            if [ "$htype" = "switch" ] || [ "$htype" = "external" ] || [ "$htype" = "idrac" ]; then
                if ping -c1 -W2 "$ip" &>/dev/null; then
                    result="UP|||"
                fi
            elif ! host_supports_ssh "$htype"; then
                if ping -c1 -W2 "$ip" &>/dev/null; then
                    result="UP|||"
                fi
            else
                local info
                info=$(freq_ssh "$ip" "
                    _up=\$(uptime -p 2>/dev/null || uptime | sed 's/.*up /up /' | sed 's/,.*//')
                    _load=\$(cat /proc/loadavg 2>/dev/null | awk '{print \$1}' || sysctl -n vm.loadavg 2>/dev/null | awk '{print \$2}')
                    _disk=\$(df / 2>/dev/null | awk 'NR==2{print \$5}' | tr -d '%')
                    _dock=\$(sudo docker ps -q 2>/dev/null | wc -l || echo 0)
                    echo \"\${_up}|\${_load}|\${_disk}|\${_dock}\"
                " 2>/dev/null)
                if [ -n "$info" ]; then
                    result="UP|$info"
                fi
            fi
            echo "$result" > "$tmpdir/$i"
        ) &
        running=$((running + 1))
        if [ $running -ge "${MAX_PARALLEL:-5}" ]; then
            wait -n 2>/dev/null || true
            running=$((running - 1))
        fi
    done
    wait

    # Collect and display results by category
    declare -a cat_infra=() cat_pve=() cat_vm=() cat_ext=()
    local up=0 down=0

    for ((i=0; i<HOST_COUNT; i++)); do
        local label="${HOST_LABELS[$i]}" ip="${HOST_IPS[$i]}" htype="${HOST_TYPES[$i]}"
        local probe="DOWN|||"
        [ -f "$tmpdir/$i" ] && probe=$(cat "$tmpdir/$i")

        local status _unused_up load_str disk_str dock_str
        IFS='|' read -r status _unused_up load_str disk_str dock_str <<< "$probe"

        local status_icon
        case "$status" in
            UP)   status_icon="${GREEN}UP${RESET}"; up=$((up + 1)) ;;
            DOWN) status_icon="${RED}DOWN${RESET}"; down=$((down + 1)) ;;
            *)    status_icon="${RED}DOWN${RESET}"; down=$((down + 1)) ;;
        esac

        # Build detail string
        local detail=""
        [ -n "$load_str" ] && detail="load:${load_str}"
        if [ -n "$disk_str" ] && [ "$disk_str" != "0" ]; then
            [ -n "$detail" ] && detail="${detail}  "
            detail="${detail}disk:${disk_str}%"
        fi
        if [ -n "$dock_str" ] && [ "$dock_str" != "0" ]; then
            [ -n "$detail" ] && detail="${detail}  "
            detail="${detail}containers:${dock_str}"
        fi

        local tag=""
        case "$label" in
            *-lab*)     tag="  ${YELLOW}[LAB]${RESET}" ;;
            *freq-dev*) tag="  ${YELLOW}[DEV]${RESET}" ;;
            *-dev*)     tag="  ${YELLOW}[DEV]${RESET}" ;;
        esac

        local entry="${label}|${ip}|${status_icon}|${detail}|${tag}"

        # Categorize
        if [ "$htype" = "external" ] || [[ "$label" == ext-* ]]; then
            cat_ext+=("$entry")
        elif [ "$htype" = "pfsense" ] || [ "$htype" = "truenas" ] || [ "$htype" = "switch" ]; then
            cat_infra+=("$entry")
        elif _fleet_host_in_group "$i" "pve"; then
            cat_pve+=("$entry")
        else
            cat_vm+=("$entry")
        fi
    done

    rm -rf "$tmpdir"

    # Print table
    printf "    ${DIM}%-22s %-18s %-8s %s${RESET}\n" "Host" "IP" "Status" "Details"
    echo -e "    ${DIM}$(printf '%0.s-' {1..70})${RESET}"

    _dashboard_print_group() {
        local group_name="$1"; shift
        [ $# -eq 0 ] && return
        echo -e "    ${BOLD}${group_name}${RESET}"
        local e
        for e in "$@"; do
            local _lbl _ip _st _det _tag
            IFS='|' read -r _lbl _ip _st _det _tag <<< "$e"
            printf "    %-22s ${DIM}%-18s${RESET} %b  ${DIM}%s${RESET}%b\n" "$_lbl" "$_ip" "$_st" "$_det" "$_tag"
        done
    }

    _dashboard_print_group "Infrastructure" "${cat_infra[@]}"
    _dashboard_print_group "PVE Cluster" "${cat_pve[@]}"
    _dashboard_print_group "Virtual Machines" "${cat_vm[@]}"
    [ ${#cat_ext[@]} -gt 0 ] && _dashboard_print_group "External" "${cat_ext[@]}"

    echo ""
    freq_footer
    if [ $down -eq 0 ]; then
        echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}All $up hosts online${RESET}"
        freq_celebrate
    else
        echo -e "    ${GREEN}$up online${RESET}  ${RED}$down offline${RESET}  ${DIM}($((up+down)) total)${RESET}"
    fi
    echo ""
    log "dashboard: $up online, $down offline (${HOST_COUNT} total)"
}

# ═══════════════════════════════════════════════════════════════════
# STATUS — Fleet-wide reachability check (lighter than dashboard)
# ═══════════════════════════════════════════════════════════════════
cmd_fleet_status() {
    require_operator || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts registered. Run 'freq hosts add' first."

    local group_filter="" show_help=false
    while [ $# -gt 0 ]; do
        case "$1" in
            -g|--group) group_filter="${2:-}"; shift 2 ;;
            -h|--help) show_help=true; shift ;;
            *) shift ;;
        esac
    done

    if $show_help; then
        echo "Usage: freq status [-g <group>]"
        echo ""
        echo "Show reachability status for all fleet hosts."
        echo ""
        echo "Options:"
        echo "  -g, --group <name>  Filter by host group"
        echo "  -h, --help          Show this help"
        return 0
    fi

    # Validate group filter if provided
    if [ -n "$group_filter" ]; then
        local found_group=false gi
        for ((gi=0; gi<HOST_COUNT; gi++)); do
            if _fleet_host_in_group "$gi" "$group_filter"; then
                found_group=true; break
            fi
        done
        $found_group || die "No hosts found in group '$group_filter'. Run 'freq groups list' to see available groups."
    fi

    echo ""
    freq_header "Fleet Status"
    [ -n "$group_filter" ] && echo -e "    ${DIM}Group: $group_filter${RESET}"
    echo ""

    # Collect filtered indices
    declare -a idxs=()
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        if [ -n "$group_filter" ] && ! _fleet_host_in_group "$i" "$group_filter"; then
            continue
        fi
        idxs+=("$i")
    done
    [ ${#idxs[@]} -eq 0 ] && die "No hosts match filter."

    local tmpdir
    tmpdir=$(mktemp -d /tmp/freq-status.XXXXXX) || die "Cannot create temp dir."

    # Parallel SSH/ping check
    local running=0
    for idx in "${idxs[@]}"; do
        local ip="${HOST_IPS[$idx]}" htype="${HOST_TYPES[$idx]}"
        (
            if [ "$htype" = "switch" ] || [ "$htype" = "external" ] || [ "$htype" = "idrac" ]; then
                if ping -c1 -W2 "$ip" &>/dev/null; then
                    echo "UP" > "$tmpdir/$idx"
                else
                    echo "DOWN" > "$tmpdir/$idx"
                fi
            else
                if freq_ssh "$ip" "true" 2>/dev/null; then
                    echo "UP" > "$tmpdir/$idx"
                else
                    echo "DOWN" > "$tmpdir/$idx"
                fi
            fi
        ) &
        running=$((running + 1))
        if [ $running -ge "${MAX_PARALLEL:-5}" ]; then
            wait -n 2>/dev/null || true
            running=$((running - 1))
        fi
    done
    wait

    # Display results
    local up=0 down=0
    printf "    ${DIM}%-22s %-18s %-8s %-10s${RESET}\n" "Host" "IP" "Type" "Status"
    echo -e "    ${DIM}$(printf '%0.s-' {1..62})${RESET}"

    for idx in "${idxs[@]}"; do
        local label="${HOST_LABELS[$idx]}" ip="${HOST_IPS[$idx]}" htype="${HOST_TYPES[$idx]}"
        local probe_result="DOWN"
        [ -f "$tmpdir/$idx" ] && probe_result=$(cat "$tmpdir/$idx")

        local status_str
        if [ "$probe_result" = "UP" ]; then
            status_str="${GREEN}${_TICK} UP${RESET}"
            up=$((up + 1))
        else
            status_str="${RED}${_CROSS} DOWN${RESET}"
            down=$((down + 1))
        fi

        printf "    %-22s ${DIM}%-18s${RESET} %-10s %b\n" "$label" "$ip" "$htype" "$status_str"
    done

    rm -rf "$tmpdir"

    echo ""
    freq_footer
    if [ $down -eq 0 ]; then
        echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}All $up hosts online${RESET}"
    else
        echo -e "    ${GREEN}$up online${RESET}  ${RED}$down offline${RESET}  ${DIM}($((up+down)) total)${RESET}"
    fi
    echo ""
    log "status: $up online, $down offline (group: ${group_filter:-all})"
}

# ═══════════════════════════════════════════════════════════════════
# EXEC — Run a command across the fleet (or a group)
# ═══════════════════════════════════════════════════════════════════
cmd_exec() {
    require_admin || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts registered."

    local group_filter="" dry_run=false show_help=false
    local -a exec_args=()

    while [ $# -gt 0 ]; do
        case "$1" in
            -g|--group)    group_filter="${2:-}"; shift 2 ;;
            --dry-run)     dry_run=true; shift ;;
            -h|--help)     show_help=true; shift ;;
            --)            shift; exec_args+=("$@"); break ;;
            *)             exec_args+=("$1"); shift ;;
        esac
    done

    if $show_help || [ ${#exec_args[@]} -eq 0 ]; then
        echo "Usage: freq exec [-g <group>] [--dry-run] -- <command>"
        echo ""
        echo "Execute a command on all fleet hosts (or a group)."
        echo ""
        echo "Options:"
        echo "  -g, --group <name>  Only target hosts in this group"
        echo "  --dry-run           Show what would run without executing"
        echo "  -h, --help          Show this help"
        echo ""
        echo "Examples:"
        echo "  freq exec -- hostname"
        echo "  freq exec -g docker -- sudo docker ps -q | wc -l"
        echo "  freq exec -g pve -- uptime"
        return 0
    fi

    local remote_cmd="${exec_args[*]}"
    sanitize_ssh_cmd "$remote_cmd"

    # Collect targets
    declare -a target_idxs=()
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        if [ -n "$group_filter" ] && ! _fleet_host_in_group "$i" "$group_filter"; then
            continue
        fi
        # Skip external and idrac
        local htype="${HOST_TYPES[$i]}"
        [ "$htype" = "external" ] && continue
        [ "$htype" = "idrac" ] && continue
        target_idxs+=("$i")
    done

    [ ${#target_idxs[@]} -eq 0 ] && die "No SSH-capable hosts match filter."

    echo ""
    freq_header "Fleet Exec"
    echo -e "    ${DIM}Command: ${remote_cmd}${RESET}"
    echo -e "    ${DIM}Targets: ${#target_idxs[@]} hosts${RESET}"
    [ -n "$group_filter" ] && echo -e "    ${DIM}Group:   ${group_filter}${RESET}"
    echo ""

    if $dry_run; then
        echo -e "    ${YELLOW}DRY RUN ${_DASH} no commands will be executed${RESET}"
        echo ""
        for idx in "${target_idxs[@]}"; do
            echo -e "    ${_ARROW} ${HOST_LABELS[$idx]} (${HOST_IPS[$idx]}) [${HOST_TYPES[$idx]}]"
        done
        echo ""
        freq_footer
        return 0
    fi

    # Confirm for fleet-wide exec
    _freq_confirm "Execute on ${#target_idxs[@]} hosts?" || return 1
    echo ""

    local tmpdir
    tmpdir=$(mktemp -d /tmp/freq-exec.XXXXXX) || die "Cannot create temp dir."

    # Parallel execution
    local running=0
    for idx in "${target_idxs[@]}"; do
        local ip="${HOST_IPS[$idx]}"
        (
            freq_ssh "$ip" "$remote_cmd" > "$tmpdir/$idx.out" 2>&1
            echo $? > "$tmpdir/$idx.rc"
        ) &
        running=$((running + 1))
        if [ $running -ge "${MAX_PARALLEL:-5}" ]; then
            wait -n 2>/dev/null || true
            running=$((running - 1))
        fi
    done
    wait

    # Display results
    local succeeded=0 failed=0
    for idx in "${target_idxs[@]}"; do
        local label="${HOST_LABELS[$idx]}"
        local rc
        rc=$(cat "$tmpdir/$idx.rc" 2>/dev/null || echo 255)
        local output
        output=$(cat "$tmpdir/$idx.out" 2>/dev/null)

        if [ "$rc" = "0" ]; then
            echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${label}${RESET}"
            succeeded=$((succeeded + 1))
        else
            echo -e "    ${RED}${_CROSS}${RESET}  ${BOLD}${label}${RESET}  ${DIM}(exit: ${rc})${RESET}"
            failed=$((failed + 1))
        fi
        [ -n "$output" ] && echo "$output" | sed 's/^/      /'
    done

    rm -rf "$tmpdir"

    echo ""
    freq_footer
    echo -e "    ${BOLD}Results:${RESET} ${GREEN}$succeeded OK${RESET}, ${RED}$failed failed${RESET} (${#target_idxs[@]} total)"
    echo ""
    log "exec: '${remote_cmd}' on ${#target_idxs[@]} hosts -- $succeeded OK, $failed failed (group: ${group_filter:-all})"

    [ $failed -gt 0 ] && return 2
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# INFO — Detailed system info for a single host (OS-aware)
# ═══════════════════════════════════════════════════════════════════
cmd_info() {
    require_operator || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts registered."

    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
        echo "Usage: freq info [<host>]"
        echo ""
        echo "Show detailed system information for a single host."
        echo "If no host is specified, an interactive picker is shown."
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    if [ -n "${1:-}" ]; then
        find_host "$1" || die "Host '$1' not found. Run 'freq hosts list' to see available hosts."
    else
        select_host
    fi
    local idx=$FOUND_IDX
    local ip="${HOST_IPS[$idx]}" label="${HOST_LABELS[$idx]}" htype="${HOST_TYPES[$idx]}"

    # Switch — no SSH, just ping
    if [ "$htype" = "switch" ]; then
        echo ""
        freq_header "System Info"
        echo -e "    ${_ARROW} ${BOLD}${label}${RESET}  ${DIM}${ip} [switch]${RESET}"
        echo ""
        printf "      %-16s %s\n" "IP:" "$ip"
        printf "      %-16s " "Ping:"
        if ping -c1 -W2 "$ip" &>/dev/null; then
            echo -e "${GREEN}reachable${RESET}"
        else
            echo -e "${RED}unreachable${RESET}"
        fi
        echo ""
        echo -e "    ${DIM}Switch management -- SSH diagnostics limited${RESET}"
        freq_footer
        return 0
    fi

    # Verify SSH
    if ! freq_ssh "$ip" "true" 2>/dev/null; then
        die "Cannot SSH to ${label} (${ip}). Check connectivity and SSH key deployment."
    fi

    echo ""
    freq_header "System Info"
    echo -e "    ${_ARROW} ${BOLD}${label}${RESET}  ${DIM}${ip} [${htype}]${RESET}"
    echo ""

    local info
    case "$htype" in
        pfsense)
            info=$(freq_ssh "$ip" "
                echo \"HOSTNAME=\$(hostname)\"
                echo \"OS=pfSense \$(cat /etc/version 2>/dev/null || echo unknown) (FreeBSD \$(freebsd-version 2>/dev/null || uname -r))\"
                echo \"KERNEL=\$(uname -r)\"
                echo \"UPTIME=\$(uptime | sed 's/.*up /up /' | sed 's/,.*//')\"
                echo \"CPU=\$(sysctl -n hw.ncpu 2>/dev/null || echo unknown) cores\"
                _phys=\$(sysctl -n hw.physmem 2>/dev/null || echo 0)
                _phys_mb=\$(( _phys / 1024 / 1024 ))
                echo \"MEM=\${_phys_mb}M total\"
                echo \"DISK=\$(df -h / 2>/dev/null | awk 'NR==2{print \$3 \" / \" \$2 \" (\" \$5 \")\"}')\"
                echo \"TZ=\$(cat /var/db/zoneinfo 2>/dev/null || echo unknown)\"
                echo \"DOCKER=none\"
                echo \"DOCKER_PS=0\"
                echo \"USERS=\"
                echo \"LOAD=\$(sysctl -n vm.loadavg 2>/dev/null | sed 's/[{}]//g' | xargs)\"
            " 2>/dev/null)
            ;;
        truenas)
            info=$(freq_ssh "$ip" "
                echo \"HOSTNAME=\$(hostname)\"
                echo \"OS=\$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"')\"
                echo \"KERNEL=\$(uname -r)\"
                echo \"UPTIME=\$(uptime -p 2>/dev/null || uptime)\"
                echo \"CPU=\$(nproc 2>/dev/null || echo unknown) cores\"
                echo \"MEM=\$(free -h 2>/dev/null | awk '/^Mem:/{print \$3 \" / \" \$2}')\"
                echo \"DISK=\$(df -h / 2>/dev/null | awk 'NR==2{print \$3 \" / \" \$2 \" (\" \$5 \")\"}')\"
                echo \"TZ=\$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)\"
                echo \"DOCKER=none\"
                echo \"DOCKER_PS=0\"
                _zpools=\$(sudo zpool list -H -o name,size,alloc,cap 2>/dev/null | head -5 | tr '\t' ' ')
                echo \"ZPOOLS=\${_zpools:-none}\"
                echo \"USERS=\$(awk -F: '\$3>=3000 && \$3<=3999{printf \"%s \",\$1}' /etc/passwd 2>/dev/null)\"
                echo \"LOAD=\$(cat /proc/loadavg 2>/dev/null | awk '{print \$1, \$2, \$3}')\"
            " 2>/dev/null)
            ;;
        linux|*)
            info=$(freq_ssh "$ip" "
                echo \"HOSTNAME=\$(hostname)\"
                echo \"OS=\$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"')\"
                echo \"KERNEL=\$(uname -r)\"
                echo \"UPTIME=\$(uptime -p 2>/dev/null || uptime)\"
                echo \"CPU=\$(nproc 2>/dev/null || echo unknown) cores\"
                echo \"MEM=\$(free -h 2>/dev/null | awk '/^Mem:/{print \$3 \" / \" \$2}')\"
                echo \"DISK=\$(df -h / 2>/dev/null | awk 'NR==2{print \$3 \" / \" \$2 \" (\" \$5 \")\"}')\"
                echo \"TZ=\$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)\"
                echo \"DOCKER=\$(docker --version 2>/dev/null | awk '{print \$3}' | tr -d ',' || echo none)\"
                echo \"DOCKER_PS=\$(sudo docker ps -q 2>/dev/null | wc -l || echo 0)\"
                echo \"USERS=\$(awk -F: '\$3>=3000 && \$3<=3999{printf \"%s \",\$1}' /etc/passwd 2>/dev/null)\"
                echo \"LOAD=\$(cat /proc/loadavg 2>/dev/null | awk '{print \$1, \$2, \$3}')\"
            " 2>/dev/null)
            ;;
    esac

    _info_field() {
        local key="$1" field="$2"
        local val
        val=$(echo "$info" | grep "^${field}=" | cut -d= -f2-)
        printf "      %-16s %s\n" "${key}:" "${val:-unknown}"
    }

    echo -e "    ${BOLD}System${RESET}"
    _info_field "Hostname" "HOSTNAME"
    _info_field "OS" "OS"
    _info_field "Kernel" "KERNEL"
    _info_field "Uptime" "UPTIME"
    echo ""
    echo -e "    ${BOLD}Resources${RESET}"
    _info_field "CPU" "CPU"
    _info_field "Memory" "MEM"
    _info_field "Disk /" "DISK"
    _info_field "Load" "LOAD"

    # ZFS pools (TrueNAS)
    local zpools
    zpools=$(echo "$info" | grep '^ZPOOLS=' | cut -d= -f2-)
    if [ -n "$zpools" ] && [ "$zpools" != "none" ]; then
        echo ""
        echo -e "    ${BOLD}ZFS Pools${RESET}"
        echo "$zpools" | while IFS= read -r line; do
            printf "      %s\n" "$line"
        done
    fi

    echo ""
    echo -e "    ${BOLD}Services${RESET}"
    local docker_ver
    docker_ver=$(echo "$info" | grep '^DOCKER=' | cut -d= -f2-)
    local docker_cnt
    docker_cnt=$(echo "$info" | grep '^DOCKER_PS=' | cut -d= -f2-)
    if [ -n "$docker_ver" ] && [ "$docker_ver" != "none" ]; then
        printf "      %-16s %s (%s running)\n" "Docker:" "$docker_ver" "${docker_cnt:-0}"
    else
        printf "      %-16s %s\n" "Docker:" "not installed"
    fi
    _info_field "Fleet Users" "USERS"

    echo ""
    echo -e "    ${BOLD}Security${RESET}"
    _info_field "Timezone" "TZ"

    echo ""
    freq_footer
    log "info: ${label} (${ip})"
}

# ═══════════════════════════════════════════════════════════════════
# DIAGNOSE — Health checks for a single host (OS-aware)
# ═══════════════════════════════════════════════════════════════════
cmd_diagnose() {
    require_operator || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts registered."

    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
        echo "Usage: freq diagnose [<host>]"
        echo ""
        echo "Run health checks on a single fleet host."
        echo "If no host is specified, an interactive picker is shown."
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    if [ -n "${1:-}" ]; then
        find_host "$1" || die "Host '$1' not found. Run 'freq hosts list'."
    else
        select_host
    fi
    local idx=$FOUND_IDX
    local ip="${HOST_IPS[$idx]}" label="${HOST_LABELS[$idx]}" htype="${HOST_TYPES[$idx]}"

    # Switch — ping only
    if [ "$htype" = "switch" ]; then
        echo ""
        freq_header "Diagnose"
        echo -e "    ${DIM}Health checks: ${label} (${ip}) [switch]${RESET}"
        echo ""
        printf "    %-30s " "Ping"
        if ping -c1 -W3 "$ip" &>/dev/null; then
            echo -e "${GREEN}${_TICK}${RESET} reachable"
        else
            echo -e "${RED}${_CROSS}${RESET} unreachable"
        fi
        echo ""
        echo -e "    ${DIM}Network switch -- SSH diagnostics limited${RESET}"
        freq_footer
        log "diagnose: ${label} (switch) -- ping only"
        return 0
    fi

    echo ""
    freq_header "Diagnose"
    echo -e "    ${DIM}Health checks: ${label} (${ip}) [${htype}]${RESET}"
    echo ""

    local issues=0 warnings=0

    # Check 1: Ping
    printf "    %-30s " "Ping"
    if ping -c1 -W3 "$ip" &>/dev/null; then
        echo -e "${GREEN}${_TICK}${RESET} reachable"
    else
        if freq_ssh "$ip" "true" 2>/dev/null; then
            echo -e "${YELLOW}${_WARN}${RESET} ICMP blocked (SSH works)"
            warnings=$((warnings + 1))
        else
            echo -e "${RED}${_CROSS}${RESET} UNREACHABLE"
            issues=$((issues + 1))
            echo ""
            echo -e "    ${YELLOW}Cannot continue without connectivity. Fix networking first.${RESET}"
            freq_footer
            return 1
        fi
    fi

    # Check 2: SSH
    printf "    %-30s " "SSH (${REMOTE_USER})"
    if freq_ssh "$ip" "true" 2>/dev/null; then
        echo -e "${GREEN}${_TICK}${RESET} connected"
    else
        echo -e "${RED}${_CROSS}${RESET} FAILED"
        issues=$((issues + 1))
        echo -e "      ${DIM}Fix: Check SSH key deployment. Run 'freq init' or deploy key manually.${RESET}"
        echo ""
        freq_footer
        return 1
    fi

    # Check 3: sudo
    printf "    %-30s " "sudo (NOPASSWD)"
    if freq_ssh "$ip" "sudo -n true" 2>/dev/null; then
        echo -e "${GREEN}${_TICK}${RESET} working"
    else
        echo -e "${RED}${_CROSS}${RESET} needs password"
        issues=$((issues + 1))
        echo -e "      ${DIM}Fix: Check sudoers config for ${REMOTE_USER}.${RESET}"
    fi

    # Gather all diagnostics in ONE SSH call (section 9.6)
    local diag_data
    diag_data=$(freq_ssh "$ip" "
        echo \"HOSTNAME=\$(hostname)\"
        echo \"DISK_PCT=\$(df / 2>/dev/null | awk 'NR==2{print \$5}' | tr -d '%')\"
        echo \"MEM_USED=\$(free -m 2>/dev/null | awk '/^Mem:/{print \$3}')\"
        echo \"MEM_TOTAL=\$(free -m 2>/dev/null | awk '/^Mem:/{print \$2}')\"
        echo \"LOAD=\$(cat /proc/loadavg 2>/dev/null | awk '{print \$1}' || sysctl -n vm.loadavg 2>/dev/null | awk '{print \$2}')\"
        echo \"NPROC=\$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)\"
        echo \"TZ=\$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || cat /var/db/zoneinfo 2>/dev/null || echo unknown)\"
        echo \"SSH_ROOT=\$(sudo grep -rh '^PermitRootLogin' /etc/ssh/sshd_config.d/ /etc/ssh/sshd_config 2>/dev/null | tail -1 | awk '{print \$2}')\"
        echo \"DOCKER_ACTIVE=\$(command -v docker >/dev/null 2>&1 && sudo systemctl is-active docker 2>/dev/null || echo none)\"
        echo \"DOCKER_UNHEALTHY=\$(sudo docker ps --filter health=unhealthy -q 2>/dev/null | wc -l || echo 0)\"
        echo \"FLEET_USERS=\$(awk -F: '\$3>=3000 && \$3<=3999{printf \"%s \",\$1}' /etc/passwd 2>/dev/null)\"
        echo \"DNS_OK=\$(host google.com >/dev/null 2>&1 && echo yes || ping -c1 -W3 8.8.8.8 >/dev/null 2>&1 && echo yes || echo no)\"
    " 2>/dev/null)

    _diag_val() { echo "$diag_data" | grep "^${1}=" | cut -d= -f2-; }

    # Check 4: Hostname
    printf "    %-30s " "Hostname"
    local cur_hostname
    cur_hostname=$(_diag_val HOSTNAME)
    if [ "$cur_hostname" = "debian" ] || [ "$cur_hostname" = "localhost" ]; then
        echo -e "${YELLOW}${_WARN}${RESET} generic ('$cur_hostname')"
        warnings=$((warnings + 1))
    else
        echo -e "${GREEN}${_TICK}${RESET} $cur_hostname"
    fi

    # Check 5: DNS
    printf "    %-30s " "DNS resolution"
    local dns_ok
    dns_ok=$(_diag_val DNS_OK)
    if [ "$dns_ok" = "yes" ]; then
        echo -e "${GREEN}${_TICK}${RESET} working"
    else
        echo -e "${YELLOW}${_WARN}${RESET} may be broken"
        warnings=$((warnings + 1))
    fi

    # Check 6: Disk space
    printf "    %-30s " "Disk space /"
    local disk_pct
    disk_pct=$(_diag_val DISK_PCT)
    if [ -n "$disk_pct" ] && [ "$disk_pct" -ge 90 ] 2>/dev/null; then
        echo -e "${RED}${_CROSS}${RESET} ${disk_pct}% FULL"
        issues=$((issues + 1))
    elif [ -n "$disk_pct" ] && [ "$disk_pct" -ge 80 ] 2>/dev/null; then
        echo -e "${YELLOW}${_WARN}${RESET} ${disk_pct}% used"
        warnings=$((warnings + 1))
    elif [ -n "$disk_pct" ]; then
        echo -e "${GREEN}${_TICK}${RESET} ${disk_pct}% used"
    else
        echo -e "${YELLOW}${_WARN}${RESET} could not check"
        warnings=$((warnings + 1))
    fi

    # Check 7: Memory
    printf "    %-30s " "Memory"
    local mem_used mem_total
    mem_used=$(_diag_val MEM_USED)
    mem_total=$(_diag_val MEM_TOTAL)
    if [ -n "$mem_used" ] && [ -n "$mem_total" ] && [ "$mem_total" -gt 0 ] 2>/dev/null; then
        local mem_pct=$(( mem_used * 100 / mem_total ))
        if [ "$mem_pct" -ge 90 ]; then
            echo -e "${RED}${_CROSS}${RESET} ${mem_pct}% (${mem_used}M/${mem_total}M)"
            issues=$((issues + 1))
        elif [ "$mem_pct" -ge 75 ]; then
            echo -e "${YELLOW}${_WARN}${RESET} ${mem_pct}% (${mem_used}M/${mem_total}M)"
            warnings=$((warnings + 1))
        else
            echo -e "${GREEN}${_TICK}${RESET} ${mem_pct}% (${mem_used}M/${mem_total}M)"
        fi
    else
        echo -e "${YELLOW}${_WARN}${RESET} could not check"
        warnings=$((warnings + 1))
    fi

    # Check 8: Load
    printf "    %-30s " "CPU Load"
    local load_val nproc_val
    load_val=$(_diag_val LOAD)
    nproc_val=$(_diag_val NPROC)
    if [ -n "$load_val" ] && [ -n "$nproc_val" ]; then
        local load_int=${load_val%.*}
        if [ "${load_int:-0}" -ge "${nproc_val:-1}" ] 2>/dev/null; then
            echo -e "${RED}${_CROSS}${RESET} ${load_val} (${nproc_val} cores)"
            issues=$((issues + 1))
        else
            echo -e "${GREEN}${_TICK}${RESET} ${load_val} (${nproc_val} cores)"
        fi
    else
        echo -e "${YELLOW}${_WARN}${RESET} could not check"
        warnings=$((warnings + 1))
    fi

    # Check 9: SSH PermitRootLogin
    printf "    %-30s " "SSH PermitRootLogin"
    local ssh_root
    ssh_root=$(_diag_val SSH_ROOT)
    case "$ssh_root" in
        no|prohibit-password|without-password)
            echo -e "${GREEN}${_TICK}${RESET} ${ssh_root}" ;;
        ""|" ")
            echo -e "${YELLOW}${_WARN}${RESET} default (check sshd_config)"
            warnings=$((warnings + 1)) ;;
        *)
            echo -e "${YELLOW}${_WARN}${RESET} ${ssh_root}"
            warnings=$((warnings + 1)) ;;
    esac

    # Check 10: Timezone
    printf "    %-30s " "Timezone"
    local cur_tz
    cur_tz=$(_diag_val TZ)
    if [ "$cur_tz" = "${DC01_TIMEZONE:-America/Chicago}" ]; then
        echo -e "${GREEN}${_TICK}${RESET} ${cur_tz}"
    else
        echo -e "${YELLOW}${_WARN}${RESET} ${cur_tz} (expected: ${DC01_TIMEZONE:-America/Chicago})"
        warnings=$((warnings + 1))
    fi

    # Check 11: Docker (if present)
    local docker_state
    docker_state=$(_diag_val DOCKER_ACTIVE)
    if [ "$docker_state" != "none" ] && [ -n "$docker_state" ]; then
        printf "    %-30s " "Docker"
        if [ "$docker_state" = "active" ]; then
            echo -e "${GREEN}${_TICK}${RESET} running"
        else
            echo -e "${RED}${_CROSS}${RESET} ${docker_state}"
            issues=$((issues + 1))
        fi

        local unhealthy
        unhealthy=$(_diag_val DOCKER_UNHEALTHY)
        if [ "${unhealthy:-0}" -gt 0 ] 2>/dev/null; then
            printf "    %-30s " "Unhealthy containers"
            echo -e "${RED}${_CROSS}${RESET} ${unhealthy} unhealthy"
            issues=$((issues + 1))
        fi
    fi

    # Check 12: Fleet users
    printf "    %-30s " "Fleet users"
    local fleet_users
    fleet_users=$(_diag_val FLEET_USERS)
    local user_count=0
    # shellcheck disable=SC2034
    local _fu
    for _fu in $fleet_users; do [ -n "$_fu" ] && user_count=$((user_count + 1)); done
    echo -e "${GREEN}${_TICK}${RESET} ${user_count} users (${fleet_users})"

    # Summary
    echo ""
    freq_footer
    if [ $issues -eq 0 ] && [ $warnings -eq 0 ]; then
        echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${label} is healthy!${RESET}"
        freq_celebrate
    elif [ $issues -eq 0 ]; then
        echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${label} is OK${RESET} ${_DASH} ${warnings} warning(s)"
    else
        echo -e "    ${RED}${_CROSS}${RESET}  ${BOLD}${label} needs attention${RESET} ${_DASH} ${issues} issue(s), ${warnings} warning(s)"
    fi
    echo ""
    log "diagnose: ${label} -- ${issues} issues, ${warnings} warnings"
}

# ═══════════════════════════════════════════════════════════════════
# DOCKER — Container management for a single host
# ═══════════════════════════════════════════════════════════════════
cmd_docker() {
    require_operator || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts registered."

    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
        echo "Usage: freq docker [<host>]"
        echo ""
        echo "Interactive Docker container management for a fleet host."
        echo "If no host is specified, an interactive picker is shown."
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    if [ -n "${1:-}" ]; then
        find_host "$1" || die "Host '$1' not found."
    else
        select_host
    fi
    local idx=$FOUND_IDX
    local ip="${HOST_IPS[$idx]}" label="${HOST_LABELS[$idx]}" htype="${HOST_TYPES[$idx]}"

    [ "$htype" = "switch" ] && die "${label} is a network switch -- Docker not applicable."
    [ "$htype" = "external" ] && die "${label} is external -- Docker not applicable."

    if ! freq_ssh "$ip" "true" 2>/dev/null; then
        die "Cannot SSH to ${label} (${ip}). Check connectivity."
    fi

    freq_ssh "$ip" "command -v docker" &>/dev/null \
        || die "Docker is not installed on ${label}."

    local _dock_loop=0
    while [[ $_dock_loop -lt 100 ]]; do
        _dock_loop=$((_dock_loop + 1))
        echo ""
        freq_header "Docker ${_DASH} ${label}"
        echo ""

        local containers
        containers=$(freq_ssh "$ip" "sudo docker ps -a --format '{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}'" 2>/dev/null)

        if [ -z "$containers" ]; then
            echo -e "    ${DIM}No containers on ${label}.${RESET}"
            freq_footer
            return 0
        fi

        local cidx=0
        declare -a _cids=() _cnames=()
        printf "    ${DIM}%-4s %-20s %-22s %s${RESET}\n" "#" "Name" "Status" "Image"
        echo -e "    ${DIM}$(printf '%0.s-' {1..70})${RESET}"
        while IFS=$'\t' read -r cid cname cstatus cimage; do
            [ -z "$cid" ] && continue
            cidx=$((cidx + 1))
            _cids+=("$cid")
            _cnames+=("$cname")
            local icon="${GREEN}${_TICK}${RESET}"
            [[ "$cstatus" == *"Exited"* ]] && icon="${RED}${_CROSS}${RESET}"
            [[ "$cstatus" == *"Restarting"* ]] && icon="${YELLOW}${_WARN}${RESET}"
            printf "    %b %2d  %-20s %-22s %s\n" "$icon" "$cidx" "$cname" "${cstatus:0:22}" "$cimage"
        done <<< "$containers"

        echo ""
        echo -e "    ${BOLD}Actions:${RESET}"
        echo -e "    L <#>  Logs          R <#>  Restart       S <#>  Stop"
        echo -e "    U <#>  Start         I <#>  Inspect       Q      Quit"
        echo ""
        if ! read -t 120 -rp "    > " action arg; then
            echo ""
            echo -e "    ${YELLOW}${_WARN}${RESET} Timed out waiting for input. Exiting Docker menu."
            return 0
        fi

        case "${action,,}" in
            l|logs)
                [[ "$arg" =~ ^[0-9]+$ ]] || { echo -e "    ${YELLOW}Usage: L <number>${RESET}"; continue; }
                (( arg >= 1 && arg <= cidx )) || { echo -e "    ${YELLOW}Out of range (1-${cidx}).${RESET}"; continue; }
                local ai=$((arg - 1))
                echo ""
                echo -e "    ${DIM}Last 50 lines of ${_cnames[$ai]}:${RESET}"
                echo -e "    ${DIM}$(printf '%0.s-' {1..50})${RESET}"
                freq_ssh "$ip" "sudo docker logs --tail 50 ${_cids[$ai]}" 2>&1 | sed 's/^/    /'
                ;;
            r|restart)
                [[ "$arg" =~ ^[0-9]+$ ]] || { echo -e "    ${YELLOW}Usage: R <number>${RESET}"; continue; }
                (( arg >= 1 && arg <= cidx )) || continue
                local ai=$((arg - 1))
                printf "    Restarting ${_cnames[$ai]}... "
                if freq_ssh "$ip" "sudo docker restart ${_cids[$ai]}" &>/dev/null; then
                    echo -e "${GREEN}OK${RESET}"
                    log "docker: restart ${_cnames[$ai]} on ${label}"
                else
                    echo -e "${RED}FAILED${RESET}"
                fi
                ;;
            s|stop)
                [[ "$arg" =~ ^[0-9]+$ ]] || continue
                (( arg >= 1 && arg <= cidx )) || continue
                local ai=$((arg - 1))
                printf "    Stopping ${_cnames[$ai]}... "
                if freq_ssh "$ip" "sudo docker stop ${_cids[$ai]}" &>/dev/null; then
                    echo -e "${GREEN}OK${RESET}"
                    log "docker: stop ${_cnames[$ai]} on ${label}"
                else
                    echo -e "${RED}FAILED${RESET}"
                fi
                ;;
            u|start|up)
                [[ "$arg" =~ ^[0-9]+$ ]] || continue
                (( arg >= 1 && arg <= cidx )) || continue
                local ai=$((arg - 1))
                printf "    Starting ${_cnames[$ai]}... "
                if freq_ssh "$ip" "sudo docker start ${_cids[$ai]}" &>/dev/null; then
                    echo -e "${GREEN}OK${RESET}"
                    log "docker: start ${_cnames[$ai]} on ${label}"
                else
                    echo -e "${RED}FAILED${RESET}"
                fi
                ;;
            i|inspect)
                [[ "$arg" =~ ^[0-9]+$ ]] || continue
                (( arg >= 1 && arg <= cidx )) || continue
                local ai=$((arg - 1))
                echo ""
                freq_ssh "$ip" "sudo docker inspect ${_cids[$ai]} 2>/dev/null | python3 -c '
import sys,json
d=json.load(sys.stdin)[0]
s=d.get(\"State\",{})
c=d.get(\"Config\",{})
n=d.get(\"NetworkSettings\",{})
print(f\"  Name:      {d.get(chr(78)+chr(97)+chr(109)+chr(101),chr(63)).lstrip(chr(47))}\")
print(f\"  Image:     {c.get(chr(73)+chr(109)+chr(97)+chr(103)+chr(101),chr(63))}\")
print(f\"  Status:    {s.get(chr(83)+chr(116)+chr(97)+chr(116)+chr(117)+chr(115),chr(63))}\")
print(f\"  Started:   {s.get(chr(83)+chr(116)+chr(97)+chr(114)+chr(116)+chr(101)+chr(100)+chr(65)+chr(116),chr(63))[:19]}\")
print(f\"  Restarts:  {d.get(chr(82)+chr(101)+chr(115)+chr(116)+chr(97)+chr(114)+chr(116)+chr(67)+chr(111)+chr(117)+chr(110)+chr(116),0)}\")
ports=n.get(\"Ports\",{})
for p,v in ports.items():
    if v: print(f\"  Port:      {v[0].get(chr(72)+chr(111)+chr(115)+chr(116)+chr(80)+chr(111)+chr(114)+chr(116),chr(63))} -> {p}\")
mounts=d.get(\"Mounts\",[])
for m in mounts[:5]:
    print(f\"  Mount:     {m.get(chr(83)+chr(111)+chr(117)+chr(114)+chr(99)+chr(101),chr(63))} -> {m.get(chr(68)+chr(101)+chr(115)+chr(116)+chr(105)+chr(110)+chr(97)+chr(116)+chr(105)+chr(111)+chr(110),chr(63))}\")
'" 2>/dev/null | sed 's/^/    /'
                ;;
            q|quit|"")
                return 0 ;;
            *)
                echo -e "    ${YELLOW}Unknown action. Use L/R/S/U/I/Q.${RESET}" ;;
        esac

        echo ""
        read -t 60 -rp "    Press Enter to refresh..." _ || true
    done
    [[ $_dock_loop -ge 100 ]] && echo -e "    ${YELLOW}${_WARN}${RESET} Max iterations reached. Exiting Docker menu."
}

# ═══════════════════════════════════════════════════════════════════
# LOG — View the FREQ operation log
# ═══════════════════════════════════════════════════════════════════
cmd_log() {
    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
        echo "Usage: freq log [<lines>]"
        echo ""
        echo "Show the last N lines of the FREQ operation log (default: 30)."
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    local lines="${1:-30}"

    if [ ! -f "$FREQ_LOG" ]; then
        echo "    No log entries yet."
        return 0
    fi

    echo ""
    freq_header "Operation Log (last ${lines})"
    echo ""
    tail -n "$lines" "$FREQ_LOG" | sed 's/^/    /'
    echo ""
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# SSH — Open an SSH session to a fleet host
# ═══════════════════════════════════════════════════════════════════
cmd_ssh_vm() {
    require_operator || return 1
    require_ssh_key
    load_hosts
    [ "$HOST_COUNT" -eq 0 ] && die "No hosts registered."

    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
        echo "Usage: freq ssh [<host>]"
        echo ""
        echo "Open an interactive SSH session to a fleet host."
        echo "If no host is specified, an interactive picker is shown."
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    if [ -n "${1:-}" ]; then
        find_host "$1" || die "Host '$1' not found."
    else
        select_host
    fi
    local idx=$FOUND_IDX
    local ip="${HOST_IPS[$idx]}" label="${HOST_LABELS[$idx]}" htype="${HOST_TYPES[$idx]}"

    [ "$htype" = "external" ] && die "${label} is external -- cannot SSH."

    # Determine SSH user
    local ssh_user="${REMOTE_USER}"
    [ "$htype" = "pfsense" ] && ssh_user="root"

    echo -e "    ${DIM}Connecting to ${label} (${ip}) as ${ssh_user}...${RESET}"
    log "ssh: ${label} (${ip})"

    # Drop into interactive SSH (not freq_ssh because we need stdin)
    if [ "$htype" = "switch" ]; then
        ssh \
            -o KexAlgorithms=+diffie-hellman-group14-sha1 \
            -o HostKeyAlgorithms=+ssh-rsa \
            -o PubkeyAcceptedKeyTypes=+ssh-rsa \
            -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
            -o StrictHostKeyChecking=no \
            -o ConnectTimeout=10 \
            ${FREQ_KEY_PATH:+-i "$FREQ_KEY_PATH"} \
            "${ssh_user}@${ip}"
    else
        # shellcheck disable=SC2086
        ssh $SSH_OPTS "${ssh_user}@${ip}"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# KEYS — SSH key management
# ═══════════════════════════════════════════════════════════════════
cmd_keys() {
    local subcmd="${1:-help}"; shift 2>/dev/null || true

    case "$subcmd" in
        show|info)
            require_ssh_key
            local key_path="${FREQ_KEY_PATH:-${FREQ_SSH_KEY}}"
            echo ""
            freq_header "SSH Key Info"
            echo ""
            echo -e "    ${BOLD}FREQ SSH Key${RESET}"
            printf "      %-16s %s\n" "Path:" "$key_path"
            printf "      %-16s %s\n" "Type:" "$(ssh-keygen -l -f "$key_path" 2>/dev/null | awk '{print $4}' || echo unknown)"
            printf "      %-16s %s\n" "Fingerprint:" "$(ssh-keygen -l -f "$key_path" 2>/dev/null | awk '{print $2}' || echo unknown)"
            local pubkey_preview
            pubkey_preview=$(cut -c1-60 < "${key_path}.pub" 2>/dev/null)
            printf "      %-16s %s...\n" "Public key:" "${pubkey_preview:-unknown}"
            echo ""
            freq_footer
            ;;
        deploy)
            require_admin || return 1
            require_ssh_key
            load_hosts
            local target="${1:-}"
            [ -z "$target" ] && die "Usage: freq keys deploy <host>"
            find_host "$target" || die "Host '$target' not found."
            local kidx=$FOUND_IDX
            local kip="${HOST_IPS[$kidx]}" klabel="${HOST_LABELS[$kidx]}"

            echo -e "    Deploying SSH key to ${klabel} (${kip})..."
            local pubkey
            pubkey=$(get_ssh_pubkey)
            [ -z "$pubkey" ] && die "Cannot read public key."

            if freq_ssh "$kip" "grep -qF '${pubkey}' ~/.ssh/authorized_keys 2>/dev/null" 2>/dev/null; then
                echo -e "    ${GREEN}${_TICK}${RESET}  Key already deployed"
            else
                if freq_ssh "$kip" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '${pubkey}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" 2>/dev/null; then
                    echo -e "    ${GREEN}${_TICK}${RESET}  Key deployed to ${klabel}"
                    log "keys deploy: ${klabel} (${kip})"
                else
                    echo -e "    ${RED}${_CROSS}${RESET}  Failed to deploy key"
                    return 1
                fi
            fi
            ;;
        -h|--help|help|*)
            echo "Usage: freq keys <subcommand>"
            echo ""
            echo "Subcommands:"
            echo "  show       Show SSH key information"
            echo "  deploy     Deploy SSH key to a host"
            echo "  -h, --help Show this help"
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# BOOTSTRAP — Full init deploy to a single host (post-init)
# ═══════════════════════════════════════════════════════════════════
cmd_bootstrap() {
    require_admin || return 1
    require_ssh_key
    load_hosts

    local dry_run=false target=""

    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help)
                echo "Usage: freq bootstrap <host> [--dry-run]"
                echo ""
                echo "Deploy service account, SSH key, and sudoers to a single host."
                echo "The host must already be registered in hosts.conf."
                echo ""
                echo "Options:"
                echo "  --dry-run     Show what would be done without executing"
                echo "  -h, --help    Show this help"
                return 0
                ;;
            --dry-run) dry_run=true; shift ;;
            *) target="$1"; shift ;;
        esac
    done

    [ -z "$target" ] && die "Usage: freq bootstrap <host> [--dry-run]"

    find_host "$target" || die "Host '$target' not found. Register with 'freq hosts add' first."
    local bidx=$FOUND_IDX
    local ip="${HOST_IPS[$bidx]}" label="${HOST_LABELS[$bidx]}" htype="${HOST_TYPES[$bidx]}"

    [ "$htype" = "external" ] && die "${label} is external -- cannot bootstrap."
    [ "$htype" = "idrac" ] && die "${label} is iDRAC -- cannot bootstrap."

    echo ""
    freq_header "Bootstrap ${_DASH} ${label}"
    echo -e "    ${DIM}Target: ${label} (${ip}) [${htype}]${RESET}"
    echo ""

    if $dry_run; then
        echo -e "    ${YELLOW}DRY RUN${RESET}"
        echo -e "    Would deploy: service account, SSH key, sudoers"
        echo -e "    Target: ${label} (${ip})"
        freq_footer
        return 0
    fi

    _freq_confirm "Bootstrap ${label}? This will create/update the service account." || return 1

    # Need root password for bootstrap
    local root_pass
    root_pass=$(vault_get "root-password" 2>/dev/null)
    if [ -z "$root_pass" ]; then
        echo -n "    Root password for ${label}: "
        if ! read -t 30 -rs root_pass; then
            echo ""
            echo -e "    ${RED}${_CROSS}${RESET} Timed out waiting for password."
            return 1
        fi
        echo ""
    fi
    [ -z "$root_pass" ] && die "Root password required for bootstrap."

    local svc_name="${FREQ_SERVICE_ACCOUNT}"
    local svc_group="${FREQ_GROUP:-freq-group}"
    local pubkey
    pubkey=$(get_ssh_pubkey)
    [ -z "$pubkey" ] && die "Cannot read SSH public key."

    _step_start "Connecting to ${label}..."
    if ! freq_ssh_pass "$ip" "$root_pass" "echo OK" 2>/dev/null; then
        _step_fail "Cannot connect with root password"
        die "Root SSH failed to ${label} (${ip}). Verify password."
    fi
    _step_ok "Connected"

    case "$htype" in
        switch)
            _step_start "Switch -- verifying connectivity..."
            if ping -c1 -W2 "$ip" &>/dev/null; then
                _step_ok "Switch reachable"
            else
                _step_fail "Switch unreachable"
            fi
            echo -e "    ${DIM}Switch bootstrap limited -- user accounts via IOS CLI${RESET}"
            ;;
        pfsense)
            _step_start "Deploying to pfSense..."
            freq_ssh_pass "$ip" "$root_pass" "
                pw groupshow ${svc_group} >/dev/null 2>&1 || pw groupadd ${svc_group}
                if ! pw usershow ${svc_name} >/dev/null 2>&1; then
                    pw useradd -n ${svc_name} -m -s /bin/sh -g ${svc_group}
                    echo '${root_pass}' | pw usermod ${svc_name} -h 0
                fi
                mkdir -p /home/${svc_name}/.ssh
                echo '${pubkey}' > /home/${svc_name}/.ssh/authorized_keys
                chmod 700 /home/${svc_name}/.ssh
                chmod 600 /home/${svc_name}/.ssh/authorized_keys
                chown -R ${svc_name}:${svc_group} /home/${svc_name}/.ssh
                mkdir -p /usr/local/etc/sudoers.d
                echo '${svc_name} ALL=(ALL) NOPASSWD: ALL' > /usr/local/etc/sudoers.d/freq-${svc_name}
                chmod 440 /usr/local/etc/sudoers.d/freq-${svc_name}
            " 2>/dev/null
            if [ $? -eq 0 ]; then
                _step_ok "pfSense: account, key, sudoers deployed"
            else
                _step_fail "pfSense bootstrap failed"
                return 1
            fi
            ;;
        truenas)
            _step_start "Deploying to TrueNAS..."
            freq_ssh_pass "$ip" "$root_pass" "
                if ! id ${svc_name} >/dev/null 2>&1; then
                    midclt call user.create '{\"username\": \"${svc_name}\", \"full_name\": \"FREQ Service Account\", \"group_create\": true, \"home\": \"/home/${svc_name}\", \"shell\": \"/usr/bin/bash\", \"password\": \"${root_pass}\", \"sudo_commands_nopasswd\": [\"ALL\"]}' >/dev/null 2>&1
                fi
                _home=\$(getent passwd ${svc_name} | cut -d: -f6)
                mkdir -p \${_home}/.ssh
                echo '${pubkey}' > \${_home}/.ssh/authorized_keys
                chmod 700 \${_home}/.ssh
                chmod 600 \${_home}/.ssh/authorized_keys
                chown -R ${svc_name}:${svc_name} \${_home}/.ssh
            " 2>/dev/null
            if [ $? -eq 0 ]; then
                _step_ok "TrueNAS: account, key deployed"
            else
                _step_fail "TrueNAS bootstrap failed"
                return 1
            fi
            ;;
        linux|*)
            _step_start "Deploying to ${label}..."
            freq_ssh_pass "$ip" "$root_pass" "
                getent group ${svc_group} >/dev/null 2>&1 || groupadd -g ${SVC_GID:-950} ${svc_group}
                if ! id ${svc_name} >/dev/null 2>&1; then
                    useradd -m -s /bin/bash -u ${SVC_UID:-3003} -g ${svc_group} ${svc_name}
                    echo '${svc_name}:${root_pass}' | chpasswd
                fi
                mkdir -p /home/${svc_name}/.ssh
                echo '${pubkey}' > /home/${svc_name}/.ssh/authorized_keys
                chmod 700 /home/${svc_name}/.ssh
                chmod 600 /home/${svc_name}/.ssh/authorized_keys
                chown -R ${svc_name}:${svc_group} /home/${svc_name}/.ssh
                echo '${svc_name} ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/freq-${svc_name}
                chmod 440 /etc/sudoers.d/freq-${svc_name}
            " 2>/dev/null
            if [ $? -eq 0 ]; then
                _step_ok "Linux: account, key, sudoers deployed"
            else
                _step_fail "Linux bootstrap failed"
                return 1
            fi
            ;;
    esac

    # Verify
    _step_start "Verifying SSH key auth..."
    if freq_ssh "$ip" "true" 2>/dev/null; then
        _step_ok "SSH key auth working"
    else
        _step_fail "SSH key auth failed -- check deployment"
        return 1
    fi

    echo ""
    freq_footer
    echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}${label} bootstrapped successfully${RESET}"
    echo ""
    freq_celebrate
    log "bootstrap: ${label} (${ip}) [${htype}] -- complete"
}

# ═══════════════════════════════════════════════════════════════════
# ONBOARD — Register a new host and optionally bootstrap it
# ═══════════════════════════════════════════════════════════════════
cmd_onboard() {
    require_admin || return 1

    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
        echo "Usage: freq onboard <ip> <label> <type> [groups]"
        echo ""
        echo "Register a new host in hosts.conf and optionally bootstrap it."
        echo ""
        echo "Arguments:"
        echo "  ip       IP address of the host"
        echo "  label    Hostname label (e.g., vm200-myvm)"
        echo "  type     Host type: linux, pfsense, truenas, switch, external"
        echo "  groups   Comma-separated groups (e.g., prod,docker)"
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    local ip="${1:-}" label="${2:-}" htype="${3:-}" groups="${4:-}"

    [ -z "$ip" ] || [ -z "$label" ] || [ -z "$htype" ] && \
        die "Usage: freq onboard <ip> <label> <type> [groups]"

    validate_ip "$ip"
    validate_label "$label"

    # Add to hosts.conf
    echo -e "    Adding ${label} to hosts.conf..."
    cmd_hosts add "$ip" "$label" "$htype" "$groups"

    # Offer to bootstrap
    if [ "$htype" != "external" ] && [ "$htype" != "idrac" ]; then
        echo ""
        if ask_rsq "Bootstrap ${label} now? (deploy account + SSH key)"; then
            cmd_bootstrap "$label"
        else
            echo -e "    ${DIM}Skipping bootstrap. Run 'freq bootstrap ${label}' later.${RESET}"
        fi
    fi

    log "onboard: ${label} (${ip}) [${htype}] groups=${groups}"
}

# ═══════════════════════════════════════════════════════════════════
# MIGRATE-IP — Change a fleet host's IP (full safety net)
# ═══════════════════════════════════════════════════════════════════
cmd_migrate_ip() {
    require_admin || return 1
    require_ssh_key
    load_hosts

    if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
        echo "Usage: freq migrate-ip <host> <old-ip> <new-ip>"
        echo ""
        echo "Migrate a fleet host from one IP to another."
        echo "Updates networking config, sshd, hosts.conf, and verifies."
        echo ""
        echo "Options:"
        echo "  -h, --help    Show this help"
        return 0
    fi

    local host="${1:-}" old_ip="${2:-}" new_ip="${3:-}"
    [ -z "$host" ] || [ -z "$old_ip" ] || [ -z "$new_ip" ] && \
        die "Usage: freq migrate-ip <host> <old-ip> <new-ip>"

    validate_ip "$old_ip"
    validate_ip "$new_ip"
    [ "$old_ip" = "$new_ip" ] && die "Old and new IP are the same."

    find_host "$host" || die "Host '${host}' not found in hosts.conf."
    local midx=$FOUND_IDX
    local host_ip="${HOST_IPS[$midx]}" host_label="${HOST_LABELS[$midx]}"

    [ "$host_ip" != "$old_ip" ] && \
        echo -e "    ${YELLOW}${_WARN}${RESET}  hosts.conf IP (${host_ip}) differs from old_ip (${old_ip})"

    echo ""
    freq_header "Migrate IP ${_DASH} ${host_label}"
    echo -e "    ${DIM}${old_ip} -> ${new_ip}${RESET}"
    echo ""

    # Pre-flight: scan for old IP references
    _step_start "Scanning ${host_label} for ${old_ip}..."
    local scan_result
    scan_result=$(freq_ssh "$old_ip" "
        for f in /etc/network/interfaces /etc/hosts /etc/resolv.conf; do
            [ -f \"\$f\" ] && grep -q '${old_ip}' \"\$f\" 2>/dev/null && echo \"\$f\"
        done
        for f in /etc/network/interfaces.d/* /etc/ssh/sshd_config.d/*; do
            [ -f \"\$f\" ] && grep -q '${old_ip}' \"\$f\" 2>/dev/null && echo \"\$f\"
        done
        for f in /etc/netplan/*.yaml /etc/netplan/*.yml; do
            [ -f \"\$f\" ] && grep -q '${old_ip}' \"\$f\" 2>/dev/null && echo \"\$f\"
        done
    " 2>/dev/null)

    if [ -z "$scan_result" ]; then
        _step_fail "No files containing ${old_ip} found"
        die "Nothing to migrate."
    fi
    _step_ok "Files to update:"
    echo "$scan_result" | while IFS= read -r _f; do
        [ -n "$_f" ] && echo -e "      ${DIM}${_f}${RESET}"
    done

    # Validate new IP is free
    _step_start "Checking ${new_ip} is free..."
    if ping -c1 -W2 "$new_ip" &>/dev/null; then
        _step_fail "${new_ip} already responding"
        die "New IP ${new_ip} is already in use."
    fi
    _step_ok "${new_ip} is free"
    echo ""

    # Confirm
    _freq_confirm "Migrate ${host_label}: ${old_ip} -> ${new_ip}? (will restart networking)" || return 1

    # Execute: update files on remote host
    _step_start "Updating files..."
    freq_ssh "$old_ip" "
        for f in /etc/network/interfaces /etc/hosts /etc/resolv.conf; do
            [ -f \"\$f\" ] && grep -q '${old_ip}' \"\$f\" 2>/dev/null && sudo sed -i 's|${old_ip}|${new_ip}|g' \"\$f\"
        done
        for f in /etc/network/interfaces.d/*; do
            [ -f \"\$f\" ] && grep -q '${old_ip}' \"\$f\" 2>/dev/null && sudo sed -i 's|${old_ip}|${new_ip}|g' \"\$f\"
        done
        for f in /etc/netplan/*.yaml /etc/netplan/*.yml; do
            [ -f \"\$f\" ] && grep -q '${old_ip}' \"\$f\" 2>/dev/null && sudo sed -i 's|${old_ip}|${new_ip}|g' \"\$f\"
        done
        for f in /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*; do
            [ -f \"\$f\" ] && grep -q '${old_ip}' \"\$f\" 2>/dev/null && sudo sed -i 's|${old_ip}|${new_ip}|g' \"\$f\"
        done
    " 2>/dev/null
    _step_ok "Files updated"

    # Schedule network restart (SSH will drop)
    _step_start "Scheduling network restart..."
    freq_ssh "$old_ip" "nohup bash -c 'sleep 1; netplan apply 2>/dev/null || systemctl restart networking 2>/dev/null; sleep 2; systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null' &>/dev/null &" 2>/dev/null || true
    _step_ok "Restart queued"

    # Verify on new IP
    local ssh_ok=false attempt
    for attempt in 1 2 3 4 5 6; do
        sleep 5
        _step_start "SSH to ${new_ip} (attempt ${attempt}/6)..."
        if freq_ssh "$new_ip" "hostname" &>/dev/null; then
            _step_ok "SSH working on ${new_ip}"
            ssh_ok=true
            break
        fi
        _step_fail "Not yet..."
    done

    if ! $ssh_ok; then
        die "SSH failed on ${new_ip} after 6 attempts. Manual recovery needed."
    fi

    # Update hosts.conf
    _step_start "Updating hosts.conf..."
    if grep -q "^${old_ip}[[:space:]]" "$HOSTS_FILE" 2>/dev/null; then
        sed -i "s|^${old_ip}[[:space:]]|${new_ip} |" "$HOSTS_FILE"
        _step_ok "hosts.conf updated"
    else
        _step_warn "Could not find ${old_ip} in hosts.conf"
    fi

    echo ""
    freq_footer
    echo -e "    ${GREEN}${_TICK}${RESET}  ${BOLD}Migration complete:${RESET} ${host_label} ${old_ip} -> ${new_ip}"
    echo ""
    log "migrate-ip: ${host_label} ${old_ip} -> ${new_ip}"
}

# ═══════════════════════════════════════════════════════════════════
# OPERATOR — Operator identity management
# ═══════════════════════════════════════════════════════════════════
cmd_operator() {
    local subcmd="${1:-whoami}"; shift 2>/dev/null || true

    case "$subcmd" in
        whoami)
            echo -e "    Operator: ${BOLD}${FREQ_USER:-$(id -un)}${RESET}"
            echo -e "    Role:     ${FREQ_ROLE:-unknown}"
            echo -e "    Host:     $(hostname) ($(hostname -I 2>/dev/null | awk '{print $1}'))"
            ;;
        -h|--help|help)
            echo "Usage: freq operator <subcommand>"
            echo ""
            echo "Subcommands:"
            echo "  whoami     Show current operator identity and role"
            echo "  -h, --help Show this help"
            ;;
        *)
            echo "Unknown subcommand: $subcmd"
            echo "Usage: freq operator {whoami}"
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# FLEET SSH MODE — Toggle password auth fleet-wide
# ═══════════════════════════════════════════════════════════════════
cmd_fleet_ssh_mode() {
    local mode="${1:-status}" dry_run=false
    [ "${2:-}" = "--dry-run" ] && dry_run=true

    case "$mode" in
        status)
            require_ssh_key
            load_hosts
            echo ""
            freq_header "Fleet SSH Mode"
            echo ""
            local i
            for ((i=0; i<HOST_COUNT; i++)); do
                local ip="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
                [ "$htype" != "linux" ] && [ "$htype" != "truenas" ] && continue
                local pass_auth
                pass_auth=$(freq_ssh "$ip" "sudo grep -rh '^PasswordAuthentication' /etc/ssh/sshd_config.d/ /etc/ssh/sshd_config 2>/dev/null | tail -1 | awk '{print \$2}'" 2>/dev/null)
                [ -z "$pass_auth" ] && pass_auth="unknown"
                if [ "$pass_auth" = "yes" ]; then
                    echo -e "    ${label}: ${YELLOW}password-auth ON${RESET}"
                elif [ "$pass_auth" = "no" ]; then
                    echo -e "    ${label}: ${GREEN}key-only${RESET}"
                else
                    echo -e "    ${label}: ${DIM}${pass_auth}${RESET}"
                fi
            done
            echo ""
            freq_footer
            ;;
        key-only|allow-password)
            require_admin || return 1
            require_ssh_key
            load_hosts

            local target_value
            [ "$mode" = "key-only" ] && target_value="no" || target_value="yes"

            echo ""
            freq_header "Fleet SSH Mode: ${mode}"
            echo ""

            if $dry_run; then
                echo -e "    ${YELLOW}DRY RUN${RESET}"
                local i
                for ((i=0; i<HOST_COUNT; i++)); do
                    local htype="${HOST_TYPES[$i]}"
                    [ "$htype" != "linux" ] && [ "$htype" != "truenas" ] && continue
                    echo -e "    ${_ARROW} ${HOST_LABELS[$i]}: would set PasswordAuthentication=${target_value}"
                done
                freq_footer
                return 0
            fi

            local risk
            if [ "$mode" = "key-only" ]; then
                risk="Disabling password auth without verified keys = total lockout"
            else
                risk="Re-enabling password auth weakens fleet security"
            fi
            _freq_confirm "${risk}. Proceed?" || return 1

            local succeeded=0 failed=0 skipped=0 i
            for ((i=0; i<HOST_COUNT; i++)); do
                local ip="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
                [ "$htype" != "linux" ] && [ "$htype" != "truenas" ] && { skipped=$((skipped + 1)); continue; }

                if freq_ssh "$ip" "sudo sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication ${target_value}/' /etc/ssh/sshd_config && sudo systemctl restart sshd 2>/dev/null || sudo systemctl restart ssh 2>/dev/null" 2>/dev/null; then
                    echo -e "    ${GREEN}${_TICK}${RESET}  ${label}: ${mode}"
                    succeeded=$((succeeded + 1))
                else
                    echo -e "    ${RED}${_CROSS}${RESET}  ${label}: FAILED"
                    failed=$((failed + 1))
                fi
            done

            echo ""
            freq_footer
            echo -e "    ${BOLD}Results:${RESET} ${succeeded} succeeded, ${failed} failed, ${skipped} skipped"
            log "ssh-mode: ${mode} -- ${succeeded} OK, ${failed} failed, ${skipped} skipped"
            [ $failed -gt 0 ] && return 2
            ;;
        -h|--help|help)
            echo "Usage: freq ssh-mode {status|key-only|allow-password} [--dry-run]"
            echo ""
            echo "Subcommands:"
            echo "  status           Show current SSH auth mode per host"
            echo "  key-only         Disable password auth fleet-wide"
            echo "  allow-password   Enable password auth fleet-wide"
            echo "  --dry-run        Show what would change"
            ;;
        *)
            echo "Usage: freq ssh-mode {status|key-only|allow-password} [--dry-run]"
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# SUBMENU EXEC — Quick command picker (for interactive menu)
# ═══════════════════════════════════════════════════════════════════
_submenu_exec() {
    echo ""
    echo -e "    ${BOLD}Quick Commands${RESET}"
    echo -e "    1) Run command on all hosts"
    echo -e "    2) Run command on a group"
    echo -e "    3) Back"
    echo ""
    read -t 120 -rp "    > " choice || { echo ""; echo "  Timed out."; return; }
    case "$choice" in
        1)
            read -t 120 -rp "    Command: " cmd || cmd=""
            [ -n "$cmd" ] && cmd_exec -- "$cmd"
            ;;
        2)
            read -t 120 -rp "    Group: " grp || grp=""
            read -t 120 -rp "    Command: " cmd || cmd=""
            [ -n "$grp" ] && [ -n "$cmd" ] && cmd_exec -g "$grp" -- "$cmd"
            ;;
        3|"") return 0 ;;
    esac
}
