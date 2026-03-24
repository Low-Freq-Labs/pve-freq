#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/pve.sh
# PVE Cluster Management: vm-overview, vmconfig, migrate, rescue
#
# Author:  FREQ Project
# -- cluster commander --
# Commands: cmd_vm_overview, cmd_vmconfig, cmd_migrate, cmd_rescue
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh, vm.sh
# =============================================================================
# shellcheck disable=SC2154
# =============================================================================
# FREQ -- lib/pve.sh
# Proxmox cluster operations: overview, config editor, migration, rescue
#
# Author:  FREQ Project
# -- the whole picture, one cluster at a time --
# Commands: cmd_vm_overview, cmd_vmconfig, cmd_migrate, cmd_rescue
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh, vm.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# HELPERS — PVE node utilities
# ═══════════════════════════════════════════════════════════════════

# Convert PVE node name to IP using freq.conf arrays
_pve_node_name_to_ip() {
    local name="$1" i
    for ((i=0; i<${#PVE_NODE_NAMES[@]}; i++)); do
        if [ "${PVE_NODE_NAMES[$i]}" = "$name" ]; then
            echo "${PVE_NODES[$i]}"
            return 0
        fi
    done
    return 1
}

# Convert PVE node IP to name
_pve_node_ip_to_name() {
    local ip="$1" i
    for ((i=0; i<${#PVE_NODES[@]}; i++)); do
        if [ "${PVE_NODES[$i]}" = "$ip" ]; then
            echo "${PVE_NODE_NAMES[$i]}"
            return 0
        fi
    done
    return 1
}

# Get target storage for a node from NODE_STORAGE map
_pve_target_storage() {
    local node="$1"
    local stor="${NODE_STORAGE[$node]:-}"
    [ -n "$stor" ] && echo "$stor" && return 0
    return 1
}

# Get storage type for a node (HDD/SSD)
_pve_storage_type() {
    local node="$1"
    echo "${NODE_STORAGE_TYPE[$node]:-unknown}"
}

# Detect primary disk interface for a VM
_pve_disk_iface() {
    local node_ip="$1" vmid="$2"
    local iface
    iface=$(_vm_pve_cmd "$node_ip" "qm config $vmid" 2>/dev/null \
        | grep -v "media=cdrom" \
        | grep -oP '^(scsi|virtio|ide|sata)\d+(?=:)' \
        | head -1)
    [ -n "$iface" ] && echo "$iface" || return 1
}

# Get current storage for a VM's primary disk
_pve_current_storage() {
    local node_ip="$1" vmid="$2" iface="$3"
    _vm_pve_cmd "$node_ip" "qm config $vmid" 2>/dev/null \
        | grep "^${iface}:" \
        | grep -oP '^\w+:\s*\K[^:,]+' \
        | head -1
}

# Execute command on a VM via QEMU guest agent (out-of-band, no SSH needed)
_pve_guest_exec() {
    local vmid="$1"; shift
    local cmd="$*"

    # Find which node has this VMID
    _vm_find "$vmid" || { echo "ERROR: VM $vmid not found" >&2; return 1; }
    local node_ip="$_found_node_ip"

    # Execute via guest agent
    local raw
    raw=$(_vm_pve_cmd "$node_ip" "qm guest exec ${vmid} -- /bin/bash -c '${cmd}'" 2>/dev/null)
    local rc=$?

    # qm guest exec returns JSON: {"out-data":"...","err-data":"...","exitcode":N}
    if echo "$raw" | python3 -c "import sys,json; json.load(sys.stdin)" &>/dev/null; then
        local out err exitcode
        out=$(echo "$raw" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('out-data','').rstrip())" 2>/dev/null)
        err=$(echo "$raw" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('err-data','').rstrip())" 2>/dev/null)
        exitcode=$(echo "$raw" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('exitcode',1))" 2>/dev/null)
        [ -n "$out" ] && echo "$out"
        [ -n "$err" ] && echo "$err" >&2
        return "${exitcode:-1}"
    else
        [ -n "$raw" ] && echo "$raw"
        return $rc
    fi
}

# ═══════════════════════════════════════════════════════════════════
# VM OVERVIEW — Cluster-wide VM inventory
# ═══════════════════════════════════════════════════════════════════

cmd_vm_overview() {
    local json_mode="${JSON_OUTPUT:-false}"

    # Parse args
    while [ $# -gt 0 ]; do
        case "$1" in
            --json)  json_mode=true; shift ;;
            --help|-h)
                echo "Usage: freq vm-overview [--json]"
                echo ""
                echo "Show all VMs across all PVE cluster nodes."
                echo ""
                echo "Options:"
                echo "  --json    Output as JSON array"
                echo "  --help    Show this help"
                return 0
                ;;
            *) echo -e "  ${RED}${_CROSS}${RESET} Unknown option: $1"; return 1 ;;
        esac
    done

    require_ssh_key || return 1

    local total_vms=0 running=0 stopped=0
    local -a node_data=()
    local i

    # Collect VM data from all PVE nodes
    for ((i=0; i<${#PVE_NODES[@]}; i++)); do
        local node_name="${PVE_NODE_NAMES[$i]}" node_ip="${PVE_NODES[$i]}"
        local vms
        vms=$(_vm_pve_cmd "$node_ip" "pvesh get /nodes/${node_name}/qemu --output-format json 2>/dev/null" 2>/dev/null)
        node_data+=("$vms")
    done

    # JSON mode: output all VMs as JSON array
    if $json_mode; then
        local all_json="["
        local first=true
        for ((i=0; i<${#PVE_NODES[@]}; i++)); do
            local vms="${node_data[$i]}"
            [ -z "$vms" ] || [ "$vms" = "[]" ] && continue
            local parsed
            parsed=$(echo "$vms" | python3 -c "
import sys, json
try:
    vms = json.loads(sys.stdin.read())
    node = '${PVE_NODE_NAMES[$i]}'
    for vm in sorted(vms, key=lambda v: v.get('vmid', 0)):
        if vm.get('template', 0) == 1:
            continue
        mem_mb = vm.get('maxmem', 0) // 1048576
        print(json.dumps({
            'vmid': vm.get('vmid'),
            'name': vm.get('name', ''),
            'node': node,
            'status': vm.get('status', ''),
            'maxmem_mb': mem_mb,
            'maxcpu': vm.get('cpus', vm.get('maxcpu', 0)),
            'maxdisk_gb': round(vm.get('maxdisk', 0) / 1073741824)
        }))
except:
    pass
" 2>/dev/null)
            while IFS= read -r line; do
                [ -z "$line" ] && continue
                if $first; then first=false; else all_json+=","; fi
                all_json+="$line"
            done <<< "$parsed"
        done
        all_json+="]"
        echo "$all_json" | python3 -m json.tool 2>/dev/null || echo "$all_json"
        return 0
    fi

    # Count totals
    for ((i=0; i<${#PVE_NODES[@]}; i++)); do
        local vms="${node_data[$i]}"
        if [ -n "$vms" ] && [ "$vms" != "[]" ]; then
            local counts
            counts=$(echo "$vms" | python3 -c "
import sys, json
try:
    vms = json.loads(sys.stdin.read())
    r = sum(1 for v in vms if v.get('status')=='running' and not v.get('template',0))
    s = sum(1 for v in vms if v.get('status')!='running' and not v.get('template',0))
    print(f'{r} {s}')
except: print('0 0')
" 2>/dev/null)
            local r_count s_count
            r_count=$(echo "$counts" | awk '{print $1}')
            s_count=$(echo "$counts" | awk '{print $2}')
            running=$((running + r_count))
            stopped=$((stopped + s_count))
            total_vms=$((total_vms + r_count + s_count))
        fi
    done

    freq_header "VM Overview -- ${#PVE_NODES[@]} nodes, ${total_vms} VMs, ${running} running"
    freq_blank

    for ((i=0; i<${#PVE_NODES[@]}; i++)); do
        local node_name="${PVE_NODE_NAMES[$i]}" node_ip="${PVE_NODES[$i]}"

        # Get node memory usage
        local node_mem ram_pct
        node_mem=$(_vm_pve_cmd "$node_ip" "free -g 2>/dev/null | awk '/^Mem:/{printf \"%dG/%dG %d\", \$3, \$2, 100*\$3/\$2}'" 2>/dev/null)
        local mem_str ram_color
        mem_str=$(echo "$node_mem" | awk '{print $1}')
        ram_pct=$(echo "$node_mem" | awk '{print $2}')
        [ -z "$mem_str" ] && mem_str="?"
        ram_color="${DIM}"
        if [ -n "$ram_pct" ] && [ "$ram_pct" -ge 85 ] 2>/dev/null; then
            ram_color="${RED}"
        elif [ -n "$ram_pct" ] && [ "$ram_pct" -ge 70 ] 2>/dev/null; then
            ram_color="${YELLOW}"
        fi

        # Node storage info
        local stor_name stor_type
        stor_name="${NODE_STORAGE[$node_name]:-?}"
        stor_type="${NODE_STORAGE_TYPE[$node_name]:-?}"

        freq_line "  ${BOLD}${WHITE}${node_name}${RESET}  ${DIM}(${node_ip})${RESET}  RAM: ${ram_color}${mem_str}${RESET}  ${DIM}Storage: ${stor_name} (${stor_type})${RESET}"
        freq_line "  ${DIM}$(printf '%-6s %-22s %-6s %-5s %-4s %-6s %-10s' 'ID' 'Name' 'State' 'RAM' 'CPU' 'Disk' 'IP')${RESET}"
        freq_divider ""

        local vms="${node_data[$i]}"
        if [ -z "$vms" ] || [ "$vms" = "[]" ]; then
            freq_line "    ${DIM}No VMs${RESET}"
        else
            local parsed
            parsed=$(echo "$vms" | python3 -c "
import sys, json
try:
    vms = json.loads(sys.stdin.read())
    for vm in sorted(vms, key=lambda v: v.get('vmid', 0)):
        if vm.get('template', 0) == 1:
            continue
        vmid = vm.get('vmid', '?')
        name = vm.get('name', '?')
        status = vm.get('status', '?')
        mem_mb = vm.get('maxmem', 0) // (1024*1024)
        if mem_mb >= 1024:
            mem_str = f'{mem_mb//1024}G'
        else:
            mem_str = f'{mem_mb}M'
        cpus = vm.get('cpus', vm.get('maxcpu', '?'))
        disk_gb = vm.get('maxdisk', 0) / (1024**3)
        print(f'{vmid}|{name}|{status}|{mem_str}|{cpus}|{disk_gb:.0f}G')
except:
    pass
" 2>/dev/null)
            if [ -z "$parsed" ]; then
                freq_line "    ${DIM}No VMs or connection error${RESET}"
            else
                while IFS='|' read -r vmid vmname vmstatus vmem vcpu vdisk; do
                    [ -z "$vmid" ] && continue
                    local state_tag state_color
                    case "$vmstatus" in
                        running) state_tag="RUN"; state_color="${GREEN}" ;;
                        stopped) state_tag="STP"; state_color="${RED}" ;;
                        paused)  state_tag="PAU"; state_color="${YELLOW}" ;;
                        *)       state_tag="???"; state_color="${DIM}" ;;
                    esac

                    # IP from hosts.conf
                    local vm_ip="" short_ip=""
                    if [ -f "$HOSTS_FILE" ]; then
                        vm_ip=$(grep -i "vm${vmid}" "$HOSTS_FILE" 2>/dev/null | head -1 | awk '{print $1}')
                    fi
                    [ -n "$vm_ip" ] && short_ip=".$(echo "$vm_ip" | awk -F. '{print $NF}')"

                    # Protection/special tags
                    local tag2=""
                    if _is_protected_vmid "$vmid"; then
                        case "$PROTECTED_TYPE" in
                            template)   tag2="${DIM}[TPL]${RESET}" ;;
                            production) tag2="${YELLOW}[PROD]${RESET}" ;;
                            explicit)   tag2="${CYAN}[PROT]${RESET}" ;;
                        esac
                    fi

                    freq_line "  $(printf '%-6s %-22s' "$vmid" "${vmname:0:22}")${state_color}[${state_tag}]${RESET}$(printf '  %-5s %-4s %-6s %-10s' "$vmem" "$vcpu" "$vdisk" "$short_ip") ${tag2}"
                done <<< "$parsed"
            fi
        fi
        freq_blank
    done

    freq_divider ""
    freq_line "${DIM}Total: ${total_vms} VMs  |  Running: ${running}  |  Stopped: ${stopped}  |  Source: SSH${RESET}"
    freq_blank
    freq_footer
    log "vm_overview: viewed (${total_vms} VMs across ${#PVE_NODES[@]} nodes)"
}

# ═══════════════════════════════════════════════════════════════════
# VMCONFIG — VM configuration editor (RAM, CPU, CPU type)
# ═══════════════════════════════════════════════════════════════════

cmd_vmconfig() {
    local target_vm="" dry_run="${DRY_RUN:-false}" auto_yes="${FREQ_YES:-false}"

    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run)  dry_run=true; shift ;;
            --yes|-y)   auto_yes=true; shift ;;
            --help|-h)
                echo "Usage: freq vmconfig <vmid> [--dry-run] [--yes]"
                echo ""
                echo "Interactive VM configuration editor for RAM, CPU cores, and CPU type."
                echo "Running VMs will be gracefully shut down, reconfigured, and restarted."
                echo ""
                echo "Options:"
                echo "  --dry-run  Show what would change without applying"
                echo "  --yes      Skip confirmation prompts"
                echo "  --help     Show this help"
                return 0
                ;;
            -*)  echo -e "  ${RED}${_CROSS}${RESET} Unknown option: $1"; return 1 ;;
            *)
                if [ -z "$target_vm" ]; then
                    target_vm="$1"
                else
                    echo -e "  ${RED}${_CROSS}${RESET} Too many arguments"; return 1
                fi
                shift ;;
        esac
    done

    if [ -z "$target_vm" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} Usage: freq vmconfig <vmid>"
        echo -e "  ${DIM}Specify a VM ID to configure.${RESET}"
        return 1
    fi

    if ! $dry_run; then
        require_elevated "vmconfig" || return 1
    fi
    require_ssh_key || return 1

    # Validate and find VM
    [[ "$target_vm" =~ ^[0-9]+$ ]] || { echo -e "  ${RED}${_CROSS}${RESET} Invalid VMID: $target_vm (must be numeric)"; return 1; }
    _vm_find "$target_vm" || { echo -e "  ${RED}${_CROSS}${RESET} VM $target_vm not found in cluster."; return 1; }

    local vmid="$_found_vmid"
    local node_name="$_found_node"
    local node_ip="$_found_node_ip"

    # Get current config
    local cur_config
    cur_config=$(_vm_pve_cmd "$node_ip" "qm config $vmid" 2>/dev/null)
    [ -z "$cur_config" ] && { echo -e "  ${RED}${_CROSS}${RESET} Cannot read config for VM $vmid on $node_name"; return 1; }

    local cur_cores cur_memory cur_cpu cur_status vm_name
    cur_cores=$(echo "$cur_config" | grep '^cores:' | awk '{print $2}')
    cur_memory=$(echo "$cur_config" | grep '^memory:' | awk '{print $2}')
    cur_cpu=$(echo "$cur_config" | grep '^cpu:' | awk '{print $2}')
    vm_name=$(echo "$cur_config" | grep '^name:' | awk '{print $2}')
    cur_status=$(_vm_pve_cmd "$node_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')

    local cur_ram_gb
    cur_ram_gb=$(( cur_memory / 1024 ))

    freq_header "VM Config Editor"
    freq_blank
    freq_line "  ${BOLD}${WHITE}${vm_name:-VM $vmid}${RESET} (VM $vmid) on ${BOLD}$node_name${RESET}"
    freq_line "  ${DIM}Status: ${cur_status}${RESET}"
    freq_blank
    freq_line "  ${BOLD}Current Config${RESET}"
    freq_line "    CPU Cores:  ${BOLD}${cur_cores}${RESET}"
    freq_line "    RAM:        ${BOLD}${cur_ram_gb} GB${RESET} (${cur_memory} MB)"
    freq_line "    CPU Type:   ${BOLD}${cur_cpu}${RESET}"
    freq_blank
    freq_footer

    echo ""
    echo -e "    ${BOLD}Enter changes${RESET} ${DIM}(press Enter to keep current)${RESET}"
    echo ""

    local new_cores="" new_memory="" new_cpu=""
    local changes_made=false

    read -rp "    RAM in GB [$cur_ram_gb]: " ram_input
    if [ -n "$ram_input" ]; then
        if [[ "$ram_input" =~ ^[0-9]+$ ]]; then
            [ "$ram_input" -lt 1 ] && { echo -e "  ${RED}${_CROSS}${RESET} RAM must be at least 1 GB."; return 1; }
            [ "$ram_input" -gt 512 ] && { echo -e "  ${RED}${_CROSS}${RESET} RAM cannot exceed 512 GB."; return 1; }
            new_memory=$(( ram_input * 1024 ))
            changes_made=true
        elif [[ "$ram_input" =~ ^[0-9]+[Mm][Bb]?$ ]]; then
            new_memory=$(echo "$ram_input" | grep -oP '[0-9]+')
            changes_made=true
        else
            echo -e "  ${RED}${_CROSS}${RESET} Invalid RAM value. Use a number in GB (e.g., 4, 8, 16)."
            return 1
        fi
    fi

    read -rp "    CPU Cores [$cur_cores]: " cores_input
    if [ -n "$cores_input" ]; then
        [[ "$cores_input" =~ ^[0-9]+$ ]] || { echo -e "  ${RED}${_CROSS}${RESET} Invalid core count."; return 1; }
        [ "$cores_input" -lt 1 ] && { echo -e "  ${RED}${_CROSS}${RESET} Must have at least 1 core."; return 1; }
        [ "$cores_input" -gt 64 ] && { echo -e "  ${RED}${_CROSS}${RESET} Max 64 cores."; return 1; }
        new_cores="$cores_input"
        changes_made=true
    fi

    echo ""
    echo -e "    ${DIM}CPU type options:${RESET}"
    echo -e "      1  x86-64-v2-AES  ${DIM}(migration-safe, recommended)${RESET}"
    echo -e "      2  host           ${DIM}(max performance, locks to this node)${RESET}"
    echo ""
    read -rp "    CPU Type [$cur_cpu]: " cpu_input
    if [ -n "$cpu_input" ]; then
        case "$cpu_input" in
            1|x86-64-v2-AES|x86*)  new_cpu="x86-64-v2-AES"; changes_made=true ;;
            2|host)                 new_cpu="host"; changes_made=true ;;
            *) echo -e "  ${RED}${_CROSS}${RESET} Invalid CPU type. Use 1 (x86-64-v2-AES) or 2 (host)."; return 1 ;;
        esac
    fi

    if ! $changes_made; then
        echo ""
        echo -e "    ${DIM}No changes entered.${RESET}"
        return 0
    fi

    echo ""
    echo -e "    ${BOLD}Changes to apply:${RESET}"
    if [ -n "$new_memory" ]; then
        local new_ram_gb=$(( new_memory / 1024 ))
        echo -e "      RAM:       ${cur_ram_gb} GB -> ${BOLD}${new_ram_gb} GB${RESET} (${new_memory} MB)"
    fi
    [ -n "$new_cores" ] && echo -e "      CPU Cores: ${cur_cores} -> ${BOLD}${new_cores}${RESET}"
    [ -n "$new_cpu" ] && echo -e "      CPU Type:  ${cur_cpu} -> ${BOLD}${new_cpu}${RESET}"

    local needs_reboot=false
    if [ -n "$new_memory" ] || [ -n "$new_cores" ]; then
        needs_reboot=true
    fi

    if $needs_reboot && [ "$cur_status" = "running" ]; then
        echo ""
        echo -e "    ${YELLOW}${_WARN}${RESET} RAM/CPU changes require a reboot."
        echo -e "    ${DIM}VM will be gracefully shut down, reconfigured, and restarted.${RESET}"
    fi

    if $dry_run; then
        echo ""
        echo -e "    ${DIM}[DRY RUN] Would apply:${RESET}"
        [ -n "$new_memory" ] && echo -e "    ${DIM}  qm set $vmid -memory $new_memory${RESET}"
        [ -n "$new_cores" ] && echo -e "    ${DIM}  qm set $vmid -cores $new_cores${RESET}"
        [ -n "$new_cpu" ] && echo -e "    ${DIM}  qm set $vmid -cpu $new_cpu${RESET}"
        $needs_reboot && [ "$cur_status" = "running" ] && echo -e "    ${DIM}  + shutdown -> start cycle${RESET}"
        echo ""
        echo -e "    ${YELLOW}DRY RUN -- no changes made.${RESET}"
        return 0
    fi

    if ! $auto_yes; then
        echo ""
        read -rp "    Apply changes? [y/N]: " confirm
        [[ "$confirm" =~ ^[Yy] ]] || { echo -e "    ${DIM}Aborted.${RESET}"; return 0; }
    fi

    freq_lock "vmconfig $vmid"

    # Phase 1: Graceful shutdown if needed
    if $needs_reboot && [ "$cur_status" = "running" ]; then
        echo ""
        echo -e "      ${BOLD}Step 1/3:${RESET} Graceful shutdown"

        # Try graceful ACPI shutdown first
        echo -e "      ${DIM}Shutting down VM $vmid...${RESET}"
        _vm_pve_cmd "$node_ip" "qm shutdown $vmid --timeout 60" >/dev/null 2>&1

        echo -e "      ${DIM}Press Ctrl+C to abort waiting...${RESET}"
        local tries=0
        trap 'echo ""; echo -e "      ${YELLOW}Interrupted${RESET}"; break' INT
        while [ $tries -lt 30 ]; do
            local st
            st=$(_vm_pve_cmd "$node_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
            [ "$st" = "stopped" ] && break
            sleep 2
            tries=$((tries + 1))
        done
        trap - INT

        local final_st
        final_st=$(_vm_pve_cmd "$node_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
        if [ "$final_st" != "stopped" ]; then
            echo -e "      ${YELLOW}${_WARN}${RESET} Graceful shutdown timed out, forcing stop..."
            _vm_pve_cmd "$node_ip" "qm stop $vmid" >/dev/null 2>&1
            sleep 3
            final_st=$(_vm_pve_cmd "$node_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
        fi

        if [ "$final_st" != "stopped" ]; then
            echo -e "      ${RED}${_CROSS}${RESET} VM did not stop (status: $final_st). Aborting."
            freq_unlock
            return 1
        fi
        echo -e "      ${GREEN}${_TICK}${RESET} VM stopped"
    fi

    # Phase 2: Apply config changes
    echo ""
    echo -e "      ${BOLD}Step 2/3:${RESET} Applying config changes"
    local apply_ok=true

    if [ -n "$new_memory" ]; then
        if _vm_pve_cmd "$node_ip" "qm set $vmid -memory $new_memory" >/dev/null 2>&1; then
            echo -e "      ${GREEN}${_TICK}${RESET} RAM set to $(( new_memory / 1024 )) GB ($new_memory MB)"
        else
            echo -e "      ${RED}${_CROSS}${RESET} Failed to set RAM"
            apply_ok=false
        fi
    fi

    if [ -n "$new_cores" ]; then
        if _vm_pve_cmd "$node_ip" "qm set $vmid -cores $new_cores" >/dev/null 2>&1; then
            echo -e "      ${GREEN}${_TICK}${RESET} CPU cores set to $new_cores"
        else
            echo -e "      ${RED}${_CROSS}${RESET} Failed to set CPU cores"
            apply_ok=false
        fi
    fi

    if [ -n "$new_cpu" ]; then
        if _vm_pve_cmd "$node_ip" "qm set $vmid -cpu $new_cpu" >/dev/null 2>&1; then
            echo -e "      ${GREEN}${_TICK}${RESET} CPU type set to $new_cpu"
        else
            echo -e "      ${RED}${_CROSS}${RESET} Failed to set CPU type"
            apply_ok=false
        fi
    fi

    if ! $apply_ok; then
        echo -e "      ${YELLOW}${_WARN}${RESET} Some changes failed."
    fi

    # Phase 3: Restart if was running
    if $needs_reboot && [ "$cur_status" = "running" ]; then
        echo ""
        echo -e "      ${BOLD}Step 3/3:${RESET} Starting VM"
        if _vm_pve_cmd "$node_ip" "qm start $vmid" >/dev/null 2>&1; then
            echo -e "      ${GREEN}${_TICK}${RESET} VM $vmid started"

            # Wait for guest agent
            echo -e "      ${DIM}Waiting for guest agent... (Ctrl+C to skip)${RESET}"
            local ga_tries=0 ga_up=false
            trap 'echo ""; echo -e "      ${YELLOW}Interrupted${RESET}"; break' INT
            while [ $ga_tries -lt 15 ]; do
                if _vm_pve_cmd "$node_ip" "qm agent $vmid ping" &>/dev/null; then
                    ga_up=true; break
                fi
                sleep 2
                ga_tries=$((ga_tries + 1))
            done
            trap - INT
            if $ga_up; then
                echo -e "      ${GREEN}${_TICK}${RESET} Guest agent responding"
            else
                echo -e "      ${YELLOW}${_WARN}${RESET} Guest agent not responding (may need a moment)"
            fi
        else
            echo -e "      ${RED}${_CROSS}${RESET} Failed to start VM"
        fi
    elif [ -z "$new_memory" ] && [ -z "$new_cores" ] && [ -n "$new_cpu" ]; then
        echo -e "      ${DIM}CPU type change takes effect on next reboot.${RESET}"
    fi

    freq_unlock

    # Final verification
    echo ""
    echo -e "    ${BOLD}Verification${RESET}"
    local final_config
    final_config=$(_vm_pve_cmd "$node_ip" "qm config $vmid" 2>/dev/null)
    local final_cores final_mem final_cpu final_status
    final_cores=$(echo "$final_config" | grep '^cores:' | awk '{print $2}')
    final_mem=$(echo "$final_config" | grep '^memory:' | awk '{print $2}')
    final_cpu=$(echo "$final_config" | grep '^cpu:' | awk '{print $2}')
    final_status=$(_vm_pve_cmd "$node_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')

    echo -e "      CPU Cores:  ${BOLD}${final_cores}${RESET}"
    echo -e "      RAM:        ${BOLD}$(( final_mem / 1024 )) GB${RESET} ($final_mem MB)"
    echo -e "      CPU Type:   ${BOLD}${final_cpu}${RESET}"
    echo -e "      Status:     ${BOLD}${final_status}${RESET}"

    echo ""
    echo -e "    ${GREEN}${_TICK}${RESET} VM $vmid config updated"
    freq_celebrate
    log "vmconfig: VM $vmid cores=$final_cores mem=${final_mem}MB cpu=$final_cpu on $node_name"
}

# ═══════════════════════════════════════════════════════════════════
# MIGRATION PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════════

_migrate_preflight() {
    local vmid="$1" source_node="$2" target_node="$3" method="$4"
    local issues=0

    local source_ip target_ip
    source_ip=$(_pve_node_name_to_ip "$source_node")
    target_ip=$(_pve_node_name_to_ip "$target_node")

    # 1. Target node reachable
    printf "      %-35s " "Target node reachable"
    if _vm_pve_cmd "$target_ip" "echo OK" 2>/dev/null | grep -q OK; then
        echo -e "${GREEN}${_TICK}${RESET}"
    else
        echo -e "${RED}${_CROSS}${RESET} Cannot reach $target_node ($target_ip)"
        issues=$((issues + 1))
    fi

    # 2. Target storage exists
    local target_storage
    target_storage=$(_pve_target_storage "$target_node")
    printf "      %-35s " "Target storage ($target_storage)"
    if [ -n "$target_storage" ] && _vm_pve_cmd "$target_ip" "pvesm status --storage $target_storage" &>/dev/null; then
        echo -e "${GREEN}${_TICK}${RESET}"
    else
        echo -e "${RED}${_CROSS}${RESET} Storage '$target_storage' not available"
        issues=$((issues + 1))
    fi

    # 3. VM status check
    local vm_status
    vm_status=$(_vm_pve_cmd "$source_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
    printf "      %-35s " "VM status"
    echo -e "${GREEN}${_TICK}${RESET} $vm_status"

    # 4. Disk interface detection
    local disk_iface
    disk_iface=$(_pve_disk_iface "$source_ip" "$vmid")
    printf "      %-35s " "Disk interface"
    if [ -n "$disk_iface" ]; then
        echo -e "${GREEN}${_TICK}${RESET} $disk_iface"
    else
        echo -e "${RED}${_CROSS}${RESET} Cannot detect disk interface"
        issues=$((issues + 1))
    fi

    # 5. Live requires running VM
    if [ "$method" = "live" ] && [ "$vm_status" != "running" ]; then
        echo -e "      ${YELLOW}${_WARN}${RESET} VM is $vm_status -- live migration requires running VM"
        echo -e "        ${DIM}Use --method park for offline migration${RESET}"
        issues=$((issues + 1))
    fi

    # 6. GPU passthrough blocks migration
    if _vm_pve_cmd "$source_ip" "qm config $vmid" 2>/dev/null | grep -qE '^hostpci[0-9]+:'; then
        echo -e "      ${RED}${_CROSS}${RESET} VM has GPU/PCI passthrough -- cannot migrate"
        return 1
    fi

    # 7. efidisk0 check (UEFI VMs + live migration)
    if [ "$method" = "live" ]; then
        local has_efidisk
        has_efidisk=$(_vm_pve_cmd "$source_ip" "qm config $vmid" 2>/dev/null | grep -c "^efidisk0:")
        printf "      %-35s " "UEFI efidisk0 compatibility"
        if [ "$has_efidisk" -gt 0 ]; then
            echo -e "${YELLOW}${_WARN}${RESET} VM has efidisk0 (UEFI) -- live migration may fail"
            echo -e "        ${DIM}Recommendation: Use --method park for cross-storage migration${RESET}"
            issues=$((issues + 1))
        else
            echo -e "${GREEN}${_TICK}${RESET} No efidisk0 -- live migration compatible"
        fi
    fi

    return $issues
}

# ═══════════════════════════════════════════════════════════════════
# MIGRATE — Move a VM to another PVE node (live or park)
# ═══════════════════════════════════════════════════════════════════

cmd_migrate() {
    local target_vm="" target_node="" method=""
    local dry_run="${DRY_RUN:-false}" auto_yes="${FREQ_YES:-false}" unpark=false

    while [ $# -gt 0 ]; do
        case "$1" in
            --method|-m)  method="$2"; shift 2 ;;
            --dry-run)    dry_run=true; shift ;;
            --unpark)     unpark=true; shift ;;
            --yes|-y)     auto_yes=true; shift ;;
            --help|-h)
                echo "Usage: freq migrate <vmid> <target-node> [--method live|park] [--dry-run] [--yes]"
                echo ""
                echo "Migrate a VM to another PVE node."
                echo ""
                echo "Methods:"
                echo "  live   Zero-downtime migration (requires running VM)"
                echo "  park   Shutdown -> move disk to NFS -> migrate config -> start on target"
                echo "         (unpark to local storage later with --unpark)"
                echo ""
                echo "Options:"
                echo "  --method <m>  Migration method: live or park (auto-detected if omitted)"
                echo "  --unpark      Move parked VM disk from NFS to local storage"
                echo "  --dry-run     Show migration plan without executing"
                echo "  --yes         Skip confirmation prompts"
                echo "  --help        Show this help"
                return 0
                ;;
            -*)  echo -e "  ${RED}${_CROSS}${RESET} Unknown option: $1"; return 1 ;;
            *)
                if [ -z "$target_vm" ]; then
                    target_vm="$1"
                elif [ -z "$target_node" ]; then
                    target_node="$1"
                else
                    echo -e "  ${RED}${_CROSS}${RESET} Too many arguments."
                    echo "  Usage: freq migrate <vmid> <target-node> [--method live|park]"
                    return 1
                fi
                shift ;;
        esac
    done

    if [ -z "$target_vm" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} Usage: freq migrate <vmid> <target-node> [--method live|park]"
        return 1
    fi

    if ! $dry_run; then
        require_elevated "migrate" || return 1
    fi
    require_ssh_key || return 1

    # Validate and find VM
    [[ "$target_vm" =~ ^[0-9]+$ ]] || { echo -e "  ${RED}${_CROSS}${RESET} Invalid VMID: $target_vm (must be numeric)"; return 1; }
    _vm_find "$target_vm" || { echo -e "  ${RED}${_CROSS}${RESET} VM $target_vm not found in cluster."; return 1; }

    local vmid="$_found_vmid"
    local source_node="$_found_node"
    local source_ip="$_found_node_ip"

    freq_header "VM Migration"
    freq_blank
    freq_line "  Found VM $vmid on: ${BOLD}$source_node${RESET} ($source_ip)"

    # Resolve target node
    if [ -z "$target_node" ]; then
        echo ""
        echo -e "    ${DIM}Available target nodes:${RESET}"
        local i
        for ((i=0; i<${#PVE_NODE_NAMES[@]}; i++)); do
            local _n="${PVE_NODE_NAMES[$i]}"
            [ "$_n" = "$source_node" ] && continue
            local _stor="${NODE_STORAGE[$_n]:-?}"
            local _type="${NODE_STORAGE_TYPE[$_n]:-?}"
            echo -e "      $((i+1))  ${BOLD}$_n${RESET}  (${PVE_NODES[$i]})  ${DIM}[${_stor} ${_type}]${RESET}"
        done
        echo ""
        read -rp "    Target node: " target_node
        # Accept number or name
        if [[ "$target_node" =~ ^[0-9]+$ ]] && [ "$target_node" -ge 1 ] && [ "$target_node" -le ${#PVE_NODE_NAMES[@]} ]; then
            target_node="${PVE_NODE_NAMES[$((target_node - 1))]}"
        fi
    fi

    local target_ip
    target_ip=$(_pve_node_name_to_ip "$target_node") || {
        echo -e "  ${RED}${_CROSS}${RESET} Unknown node '$target_node'. Valid: ${PVE_NODE_NAMES[*]}"
        return 1
    }

    # Handle --unpark (move disk from NFS to local storage)
    if $unpark; then
        local disk_iface
        disk_iface=$(_pve_disk_iface "$target_ip" "$vmid") || {
            echo -e "  ${RED}${_CROSS}${RESET} Cannot detect disk interface for VM $vmid"
            return 1
        }
        local cur_storage
        cur_storage=$(_pve_current_storage "$target_ip" "$vmid" "$disk_iface")

        if [ "$cur_storage" != "${PARK_STORAGE}" ] && [ "$cur_storage" != "truenas-os-drive" ]; then
            echo -e "  ${RED}${_CROSS}${RESET} VM $vmid disk is on '$cur_storage', not NFS parking. Nothing to unpark."
            return 1
        fi

        local local_storage
        local_storage=$(_pve_target_storage "$target_node") || {
            echo -e "  ${RED}${_CROSS}${RESET} No storage mapping for $target_node"
            return 1
        }

        echo ""
        echo -e "    ${BOLD}UNPARK:${RESET} Moving VM $vmid disk from NFS -> $local_storage ($target_node)"

        if $dry_run; then
            echo -e "    ${DIM}[DRY RUN] Would run: qm move-disk $vmid $disk_iface --storage $local_storage --delete 1${RESET}"
            echo -e "    ${YELLOW}DRY RUN -- no action taken.${RESET}"
            return 0
        fi

        if ! $auto_yes; then
            read -rp "    Proceed? [y/N]: " confirm
            [[ "$confirm" =~ ^[Yy] ]] || { echo -e "    ${DIM}Aborted.${RESET}"; return 0; }
        fi

        echo -e "    ${DIM}Moving disk to local storage (this may take a while)...${RESET}"
        if _vm_pve_cmd "$target_ip" "qm move-disk $vmid $disk_iface --storage $local_storage --delete 1" 2>&1; then
            echo -e "    ${GREEN}${_TICK}${RESET} Disk moved to $local_storage"
            freq_celebrate
        else
            echo -e "    ${RED}${_CROSS}${RESET} Disk move failed"
            return 1
        fi
        log "migrate unpark: VM $vmid disk $disk_iface -> $local_storage on $target_node"
        return 0
    fi

    # Cannot migrate to same node
    [ "$target_node" = "$source_node" ] && {
        echo -e "  ${RED}${_CROSS}${RESET} VM $vmid is already on $source_node."
        return 1
    }

    # Auto-select method based on VM status
    local vm_status
    vm_status=$(_vm_pve_cmd "$source_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
    if [ -z "$method" ]; then
        if [ "$vm_status" = "running" ]; then
            method="live"
        else
            method="park"
        fi
        echo -e "    Auto-selected method: ${BOLD}$method${RESET} (VM is $vm_status)"
    fi

    [ "$method" != "live" ] && [ "$method" != "park" ] && {
        echo -e "  ${RED}${_CROSS}${RESET} Invalid method '$method'. Use 'live' or 'park'."
        return 1
    }

    # Pre-flight checks
    echo ""
    echo -e "    ${BOLD}Pre-flight checks${RESET}"
    local preflight_issues=0
    _migrate_preflight "$vmid" "$source_node" "$target_node" "$method"
    preflight_issues=$?

    if [ $preflight_issues -gt 0 ]; then
        echo ""
        echo -e "    ${YELLOW}${_WARN} $preflight_issues issue(s) found.${RESET}"
        if ! $dry_run && ! $auto_yes; then
            read -rp "    Continue anyway? [y/N]: " cont
            [[ "$cont" =~ ^[Yy] ]] || { echo -e "    ${DIM}Aborted.${RESET}"; return 0; }
        fi
    fi

    local disk_iface
    disk_iface=$(_pve_disk_iface "$source_ip" "$vmid") || {
        echo -e "  ${RED}${_CROSS}${RESET} Cannot detect disk interface"
        return 1
    }
    local target_storage
    target_storage=$(_pve_target_storage "$target_node") || {
        echo -e "  ${RED}${_CROSS}${RESET} No storage mapping for $target_node"
        return 1
    }

    # Show migration plan
    echo ""
    echo -e "    ${BOLD}Migration Plan${RESET}"
    echo -e "      VM:      $vmid"
    echo -e "      From:    $source_node ($source_ip)"
    echo -e "      To:      $target_node ($target_ip)"
    echo -e "      Method:  $method"
    echo -e "      Disk:    $disk_iface"
    if [ "$method" = "live" ]; then
        echo -e "      Storage: -> $target_storage (direct)"
    else
        echo -e "      Storage: -> ${PARK_STORAGE} (NFS) -> $target_storage (unpark later)"
    fi

    if $dry_run; then
        echo ""
        if [ "$method" = "live" ]; then
            echo -e "    ${DIM}[DRY RUN] Would run on $source_node:${RESET}"
            echo -e "    ${DIM}  qm migrate $vmid $target_node --online --with-local-disks --targetstorage $target_storage${RESET}"
        else
            echo -e "    ${DIM}[DRY RUN] Steps:${RESET}"
            echo -e "    ${DIM}  1. qm shutdown $vmid${RESET}"
            echo -e "    ${DIM}  2. qm move-disk $vmid $disk_iface --storage ${PARK_STORAGE} --delete 1${RESET}"
            echo -e "    ${DIM}  3. qm migrate $vmid $target_node${RESET}"
            echo -e "    ${DIM}  4. qm start $vmid${RESET}"
            echo -e "    ${DIM}  5. (Later) freq migrate $vmid $target_node --unpark${RESET}"
        fi
        echo ""
        echo -e "    ${YELLOW}DRY RUN -- no action taken.${RESET}"
        return 0
    fi

    if ! $auto_yes; then
        echo ""
        read -rp "    Proceed with migration? [y/N]: " confirm
        [[ "$confirm" =~ ^[Yy] ]] || { echo -e "    ${DIM}Aborted.${RESET}"; return 0; }
    fi

    freq_lock "migrate VM $vmid $source_node->$target_node ($method)"

    # Protection check
    if _is_protected_vmid "$vmid"; then
        echo -e "    ${YELLOW}${_WARN}${RESET} VM $vmid is protected ($PROTECTED_TYPE)"
        if ! $auto_yes; then
            echo -e "    ${DIM}Protected VM migration requires explicit confirmation.${RESET}"
            read -rp "    Type MIGRATE to confirm: " prot_confirm
            if [ "$prot_confirm" != "MIGRATE" ]; then
                echo -e "    ${DIM}Aborted.${RESET}"
                freq_unlock
                return 0
            fi
        fi
        _protected_log "migrate" "VM $vmid $source_node->$target_node method=$method"
    fi

    # === LIVE MIGRATION ===
    if [ "$method" = "live" ]; then
        echo ""
        echo -e "    Starting live migration (zero downtime)..."
        echo -e "    ${DIM}Copying disk over the network. May take several minutes.${RESET}"

        local migrate_output
        migrate_output=$(_vm_pve_cmd "$source_ip" "qm migrate $vmid $target_node --online --with-local-disks --targetstorage $target_storage" 2>&1)
        local migrate_rc=$?

        if [ $migrate_rc -eq 0 ]; then
            echo -e "    ${GREEN}${_TICK}${RESET} Live migration completed"
        else
            echo -e "    ${RED}${_CROSS}${RESET} Live migration failed (exit code $migrate_rc)"
            echo "$migrate_output" | tail -5 | sed 's/^/      /'
            freq_unlock
            return 1
        fi

    # === PARK MIGRATION ===
    else
        echo ""

        # Step 1: Shutdown VM
        if [ "$vm_status" = "running" ]; then
            echo -e "    Step 1/4: Shutting down VM $vmid..."
            _vm_pve_cmd "$source_ip" "qm shutdown $vmid --timeout 60" >/dev/null 2>&1 || \
                _vm_pve_cmd "$source_ip" "qm stop $vmid" >/dev/null 2>&1

            echo -e "    ${DIM}Press Ctrl+C to abort waiting...${RESET}"
            local tries=0
            trap 'echo ""; echo -e "    ${YELLOW}Interrupted${RESET}"; break' INT
            while [ $tries -lt 30 ]; do
                local st
                st=$(_vm_pve_cmd "$source_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
                [ "$st" = "stopped" ] && break
                sleep 2
                tries=$((tries + 1))
            done
            trap - INT
            local final_st
            final_st=$(_vm_pve_cmd "$source_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
            if [ "$final_st" != "stopped" ]; then
                echo -e "    ${RED}${_CROSS}${RESET} VM did not shut down (status: $final_st)"
                freq_unlock
                return 1
            fi
            echo -e "    ${GREEN}${_TICK}${RESET} VM stopped"
        else
            echo -e "    Step 1/4: VM already stopped"
        fi

        # Step 2: Move disk to NFS
        echo -e "    Step 2/4: Moving disk to NFS parking (${PARK_STORAGE})..."
        local move_output
        move_output=$(_vm_pve_cmd "$source_ip" "qm move-disk $vmid $disk_iface --storage ${PARK_STORAGE} --delete 1" 2>&1)
        if [ $? -ne 0 ]; then
            echo -e "    ${RED}${_CROSS}${RESET} Disk move failed"
            echo "$move_output" | tail -3 | sed 's/^/      /'
            freq_unlock
            return 1
        fi
        echo -e "    ${GREEN}${_TICK}${RESET} Disk parked on NFS"

        # Step 3: Migrate config
        echo -e "    Step 3/4: Migrating VM config to $target_node..."
        local mig_output
        mig_output=$(_vm_pve_cmd "$source_ip" "qm migrate $vmid $target_node" 2>&1)
        if [ $? -ne 0 ]; then
            echo -e "    ${RED}${_CROSS}${RESET} Config migration failed"
            echo "$mig_output" | tail -3 | sed 's/^/      /'
            freq_unlock
            return 1
        fi
        echo -e "    ${GREEN}${_TICK}${RESET} VM config moved to $target_node"

        # Step 4: Start VM on target
        echo -e "    Step 4/4: Starting VM $vmid on $target_node..."
        if _vm_pve_cmd "$target_ip" "qm start $vmid" >/dev/null 2>&1; then
            echo -e "    ${GREEN}${_TICK}${RESET} VM $vmid started on $target_node"
        else
            echo -e "    ${YELLOW}${_WARN}${RESET} Start failed -- may need manual intervention"
        fi

        echo ""
        echo -e "    ${DIM}Note: VM disk is running from NFS (${PARK_STORAGE}).${RESET}"
        echo -e "    ${DIM}For better performance, unpark to local storage:${RESET}"
        echo -e "    ${BOLD}  freq migrate $vmid $target_node --unpark${RESET}"
    fi

    freq_unlock

    # Post-migration verification
    echo ""
    echo -e "    ${BOLD}Post-migration verification${RESET}"
    sleep 3

    _vm_find "$vmid"
    if [ "$_found_node" = "$target_node" ]; then
        echo -e "    ${GREEN}${_TICK}${RESET} VM $vmid is on $target_node"
    else
        echo -e "    ${RED}${_CROSS}${RESET} VM $vmid is on $_found_node (expected $target_node)"
    fi

    local final_status
    final_status=$(_vm_pve_cmd "$target_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
    echo -e "    ${GREEN}${_TICK}${RESET} Status: $final_status"

    if _vm_pve_cmd "$target_ip" "qm agent $vmid ping" &>/dev/null; then
        echo -e "    ${GREEN}${_TICK}${RESET} Guest agent: responding"
    else
        echo -e "    ${YELLOW}${_WARN}${RESET} Guest agent: not responding (may need a moment)"
    fi

    echo ""
    echo -e "    ${GREEN}${_TICK}${RESET} Migration complete: VM $vmid -> $target_node ($method)"
    freq_celebrate
    log "migrate: VM $vmid $source_node->$target_node method=$method"
}

# ═══════════════════════════════════════════════════════════════════
# RESCUE — Boot a VM from rescue ISO
# ═══════════════════════════════════════════════════════════════════

cmd_rescue() {
    local target_vm="" dry_run="${DRY_RUN:-false}" auto_yes="${FREQ_YES:-false}"
    local iso_file=""

    while [ $# -gt 0 ]; do
        case "$1" in
            --iso)      iso_file="$2"; shift 2 ;;
            --dry-run)  dry_run=true; shift ;;
            --yes|-y)   auto_yes=true; shift ;;
            --help|-h)
                echo "Usage: freq rescue <vmid> [--iso <file>] [--dry-run] [--yes]"
                echo ""
                echo "Boot a VM from a rescue ISO for emergency recovery."
                echo "The VM's boot order is temporarily changed to boot from CD-ROM."
                echo ""
                echo "Options:"
                echo "  --iso <file>  ISO filename on ${ISO_STORAGE:-iso-storage} (e.g., systemrescue.iso)"
                echo "  --dry-run     Show what would happen without making changes"
                echo "  --yes         Skip confirmation prompts"
                echo "  --help        Show this help"
                echo ""
                echo "After rescue work is done, run 'freq rescue <vmid> --restore' to reset boot order."
                return 0
                ;;
            --restore)
                # Special mode: restore boot order after rescue
                shift
                target_vm="${1:-}"
                [ -z "$target_vm" ] && { echo -e "  ${RED}${_CROSS}${RESET} Usage: freq rescue --restore <vmid>"; return 1; }
                _rescue_restore "$target_vm"
                return $?
                ;;
            -*)  echo -e "  ${RED}${_CROSS}${RESET} Unknown option: $1"; return 1 ;;
            *)
                if [ -z "$target_vm" ]; then
                    target_vm="$1"
                else
                    echo -e "  ${RED}${_CROSS}${RESET} Too many arguments"; return 1
                fi
                shift ;;
        esac
    done

    if [ -z "$target_vm" ]; then
        echo -e "  ${RED}${_CROSS}${RESET} Usage: freq rescue <vmid> [--iso <file>]"
        return 1
    fi

    if ! $dry_run; then
        require_elevated "rescue" || return 1
    fi
    require_ssh_key || return 1

    # Validate and find VM
    [[ "$target_vm" =~ ^[0-9]+$ ]] || { echo -e "  ${RED}${_CROSS}${RESET} Invalid VMID: $target_vm (must be numeric)"; return 1; }
    _vm_find "$target_vm" || { echo -e "  ${RED}${_CROSS}${RESET} VM $target_vm not found in cluster."; return 1; }

    local vmid="$_found_vmid"
    local node_name="$_found_node"
    local node_ip="$_found_node_ip"

    freq_header "VM Rescue Mode"
    freq_blank

    # Get VM info
    local vm_name vm_status
    vm_name=$(_vm_pve_cmd "$node_ip" "qm config $vmid" 2>/dev/null | grep '^name:' | awk '{print $2}')
    vm_status=$(_vm_pve_cmd "$node_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')

    freq_line "  ${BOLD}${vm_name:-VM $vmid}${RESET} (VM $vmid) on ${BOLD}$node_name${RESET}"
    freq_line "  ${DIM}Status: ${vm_status}${RESET}"
    freq_blank

    # List available ISOs if none specified
    if [ -z "$iso_file" ]; then
        echo -e "    ${DIM}Available rescue ISOs on ${ISO_STORAGE:-iso-storage}:${RESET}"
        local iso_list
        iso_list=$(_vm_pve_cmd "$node_ip" "ls ${ISO_STORAGE_MOUNT:-/mnt/iso-share}/template/iso/*.iso 2>/dev/null | xargs -n1 basename 2>/dev/null" 2>/dev/null)

        if [ -z "$iso_list" ]; then
            echo -e "    ${YELLOW}${_WARN}${RESET} No ISOs found on ${ISO_STORAGE:-iso-storage}"
            echo -e "    ${DIM}Upload a rescue ISO (e.g., SystemRescue, GParted) to the storage first.${RESET}"
            freq_footer
            return 1
        fi

        local iso_count=0
        while IFS= read -r iso; do
            [ -z "$iso" ] && continue
            iso_count=$((iso_count + 1))
            echo -e "      ${BOLD}${iso_count}${RESET}  $iso"
        done <<< "$iso_list"

        echo ""
        read -rp "    Select ISO (number or filename): " iso_choice

        if [[ "$iso_choice" =~ ^[0-9]+$ ]] && [ "$iso_choice" -ge 1 ] && [ "$iso_choice" -le "$iso_count" ]; then
            iso_file=$(echo "$iso_list" | sed -n "${iso_choice}p")
        elif [ -n "$iso_choice" ]; then
            iso_file="$iso_choice"
        else
            echo -e "    ${DIM}Aborted.${RESET}"
            return 0
        fi
    fi

    # Verify ISO exists
    local iso_path="${ISO_STORAGE:-iso-storage}:iso/${iso_file}"
    echo -e "    ISO: ${BOLD}${iso_file}${RESET}"

    # Save current boot config for restore
    local cur_boot cur_ide2
    cur_boot=$(_vm_pve_cmd "$node_ip" "qm config $vmid" 2>/dev/null | grep '^boot:' | sed 's/^boot: *//')
    cur_ide2=$(_vm_pve_cmd "$node_ip" "qm config $vmid" 2>/dev/null | grep '^ide2:' | sed 's/^ide2: *//')

    echo ""
    echo -e "    ${BOLD}Rescue plan:${RESET}"
    echo -e "      1. Attach ISO to ide2 (CD-ROM)"
    echo -e "      2. Set boot order: cd-rom first"
    if [ "$vm_status" = "running" ]; then
        echo -e "      3. Stop VM"
        echo -e "      4. Start VM (boots from rescue ISO)"
    else
        echo -e "      3. Start VM (boots from rescue ISO)"
    fi
    echo -e "      ${DIM}After done: freq rescue --restore $vmid${RESET}"

    if $dry_run; then
        echo ""
        echo -e "    ${DIM}[DRY RUN] Would run:${RESET}"
        echo -e "    ${DIM}  qm set $vmid --ide2 ${iso_path},media=cdrom${RESET}"
        echo -e "    ${DIM}  qm set $vmid --boot order=ide2\\;scsi0${RESET}"
        [ "$vm_status" = "running" ] && echo -e "    ${DIM}  qm stop $vmid && qm start $vmid${RESET}"
        [ "$vm_status" != "running" ] && echo -e "    ${DIM}  qm start $vmid${RESET}"
        echo ""
        echo -e "    ${YELLOW}DRY RUN -- no action taken.${RESET}"
        return 0
    fi

    if ! $auto_yes; then
        echo ""
        read -rp "    Boot VM $vmid into rescue mode? [y/N]: " confirm
        [[ "$confirm" =~ ^[Yy] ]] || { echo -e "    ${DIM}Aborted.${RESET}"; return 0; }
    fi

    freq_lock "rescue $vmid"

    # Save original config for restore
    local rescue_dir="${RESCUE_DIR:-${FREQ_DATA_DIR}/rescue}"
    _vm_pve_cmd "$node_ip" "mkdir -p $rescue_dir" 2>/dev/null
    _vm_pve_cmd "$node_ip" "echo 'boot: ${cur_boot}' > ${rescue_dir}/${vmid}.rescue ; echo 'ide2: ${cur_ide2}' >> ${rescue_dir}/${vmid}.rescue" 2>/dev/null

    # Step 1: Attach ISO
    echo ""
    echo -e "    Attaching rescue ISO..."
    if _vm_pve_cmd "$node_ip" "qm set $vmid --ide2 ${iso_path},media=cdrom" >/dev/null 2>&1; then
        echo -e "    ${GREEN}${_TICK}${RESET} ISO attached to ide2"
    else
        echo -e "    ${RED}${_CROSS}${RESET} Failed to attach ISO"
        freq_unlock
        return 1
    fi

    # Step 2: Set boot order
    if _vm_pve_cmd "$node_ip" "qm set $vmid --boot order=ide2\\;scsi0" >/dev/null 2>&1; then
        echo -e "    ${GREEN}${_TICK}${RESET} Boot order set: ide2 (CD-ROM) first"
    else
        echo -e "    ${RED}${_CROSS}${RESET} Failed to set boot order"
        freq_unlock
        return 1
    fi

    # Step 3: Stop if running, then start
    if [ "$vm_status" = "running" ]; then
        echo -e "    Stopping VM..."
        _vm_pve_cmd "$node_ip" "qm stop $vmid" >/dev/null 2>&1
        sleep 3
    fi

    echo -e "    Starting VM in rescue mode..."
    if _vm_pve_cmd "$node_ip" "qm start $vmid" >/dev/null 2>&1; then
        echo -e "    ${GREEN}${_TICK}${RESET} VM $vmid booting from rescue ISO"
    else
        echo -e "    ${RED}${_CROSS}${RESET} Failed to start VM"
        freq_unlock
        return 1
    fi

    freq_unlock

    echo ""
    echo -e "    ${BOLD}Rescue mode active.${RESET}"
    echo -e "    ${DIM}Connect via VNC/SPICE console in Proxmox WebUI.${RESET}"
    echo -e "    ${DIM}When done, restore normal boot:${RESET}"
    echo -e "      ${BOLD}freq rescue --restore $vmid${RESET}"
    echo ""

    freq_footer
    _protected_log "rescue" "VM $vmid booted from rescue ISO: $iso_file on $node_name"
    log "rescue: VM $vmid booted from $iso_file on $node_name"
}

# Restore VM boot order after rescue
_rescue_restore() {
    local target_vm="$1"
    require_ssh_key || return 1

    [[ "$target_vm" =~ ^[0-9]+$ ]] || { echo -e "  ${RED}${_CROSS}${RESET} Invalid VMID: $target_vm (must be numeric)"; return 1; }
    _vm_find "$target_vm" || { echo -e "  ${RED}${_CROSS}${RESET} VM $target_vm not found."; return 1; }

    local vmid="$_found_vmid"
    local node_ip="$_found_node_ip"
    local node_name="$_found_node"

    local rescue_dir="${RESCUE_DIR:-${FREQ_DATA_DIR}/rescue}"
    local rescue_file="${rescue_dir}/${vmid}.rescue"

    # Check for saved config
    local saved_config
    saved_config=$(_vm_pve_cmd "$node_ip" "cat $rescue_file 2>/dev/null" 2>/dev/null)

    freq_header "Rescue Restore"
    freq_blank

    if [ -z "$saved_config" ]; then
        echo -e "    ${YELLOW}${_WARN}${RESET} No saved rescue config found for VM $vmid"
        echo -e "    ${DIM}Restoring defaults: removing ide2, boot order = scsi0${RESET}"
        echo ""

        # Default restore: remove CD-ROM, set normal boot
        _vm_pve_cmd "$node_ip" "qm set $vmid --delete ide2" >/dev/null 2>&1
        _vm_pve_cmd "$node_ip" "qm set $vmid --boot order=scsi0" >/dev/null 2>&1
    else
        local orig_boot orig_ide2
        orig_boot=$(echo "$saved_config" | grep '^boot:' | sed 's/^boot: *//')
        orig_ide2=$(echo "$saved_config" | grep '^ide2:' | sed 's/^ide2: *//')

        echo -e "    ${DIM}Restoring original config:${RESET}"
        echo -e "      Boot: ${orig_boot:-default}"
        echo -e "      IDE2: ${orig_ide2:-none}"
        echo ""

        # Restore boot order
        if [ -n "$orig_boot" ]; then
            _vm_pve_cmd "$node_ip" "qm set $vmid --boot ${orig_boot}" >/dev/null 2>&1
        else
            _vm_pve_cmd "$node_ip" "qm set $vmid --boot order=scsi0" >/dev/null 2>&1
        fi

        # Restore or remove ide2
        if [ -n "$orig_ide2" ] && [ "$orig_ide2" != "none" ]; then
            _vm_pve_cmd "$node_ip" "qm set $vmid --ide2 ${orig_ide2}" >/dev/null 2>&1
        else
            _vm_pve_cmd "$node_ip" "qm set $vmid --delete ide2" >/dev/null 2>&1
        fi

        # Cleanup rescue file
        _vm_pve_cmd "$node_ip" "rm -f $rescue_file" 2>/dev/null
    fi

    echo -e "    ${GREEN}${_TICK}${RESET} Boot configuration restored for VM $vmid"
    echo ""

    # Ask about reboot
    local vm_status
    vm_status=$(_vm_pve_cmd "$node_ip" "qm status $vmid" 2>/dev/null | awk '{print $2}')
    if [ "$vm_status" = "running" ]; then
        echo -e "    ${DIM}VM is running. Reboot to apply restored boot order.${RESET}"
        read -rp "    Reboot now? [y/N]: " reboot_confirm
        if [[ "$reboot_confirm" =~ ^[Yy] ]]; then
            echo -e "    Rebooting VM $vmid..."
            _vm_pve_cmd "$node_ip" "qm reboot $vmid" >/dev/null 2>&1
            echo -e "    ${GREEN}${_TICK}${RESET} VM $vmid rebooting with normal boot order"
        fi
    fi

    freq_footer
    log "rescue restore: VM $vmid boot config restored on $node_name"
}
