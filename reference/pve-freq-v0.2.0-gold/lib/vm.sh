#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/vm.sh
# VM Lifecycle Management
#
# Author:  FREQ Project
#
# -- every great setup started with qm create. this is that moment. --
#
# Commands: cmd_vm (list, create, clone, resize, destroy, snapshot, status,
#                   change-id, nic)
# Dependencies: core.sh, ssh.sh, resolve.sh, fmt.sh, validate.sh
# =============================================================================

# Globals for VM finding (set by _vm_find)
_found_node=""
_found_node_ip=""
_found_vmid=""

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

# Run a command on a PVE node via freq_ssh (adds sudo)
_vm_pve_cmd() {
    local node_ip="$1"; shift
    freq_ssh "$node_ip" "sudo $*"
}

# Find a VM across all PVE nodes by VMID or name
# Sets: _found_node, _found_node_ip, _found_vmid
_vm_find() {
    local id_or_name="$1"
    _found_node=""
    _found_node_ip=""
    _found_vmid=""

    # If not numeric, try to resolve from hosts.conf label (e.g., vm102-arr → 102)
    if [[ ! "$id_or_name" =~ ^[0-9]+$ ]] && [ -f "$HOSTS_FILE" ]; then
        local _label_match
        _label_match=$(awk -v lbl="$id_or_name" '!/^#/ && !/^$/ && $2==lbl {print $2}' "$HOSTS_FILE")
        if [ -n "$_label_match" ]; then
            local _extracted_id
            _extracted_id=$(echo "$_label_match" | sed -n 's/^vm\([0-9]\+\).*/\1/p')
            [ -n "$_extracted_id" ] && id_or_name="$_extracted_id"
        fi
    fi

    local i nip nname
    for ((i=0; i<${#PVE_NODES[@]}; i++)); do
        nip="${PVE_NODES[$i]}"
        nname="${PVE_NODE_NAMES[$i]}"

        if [[ "$id_or_name" =~ ^[0-9]+$ ]]; then
            if _vm_pve_cmd "$nip" "qm status ${id_or_name}" &>/dev/null; then
                _found_node="$nname"
                _found_node_ip="$nip"
                _found_vmid="$id_or_name"
                return 0
            fi
        else
            local vmid_by_name
            vmid_by_name=$(_vm_pve_cmd "$nip" "qm list" 2>/dev/null | awk -v name="$id_or_name" '$2==name {print $1}')
            if [ -n "$vmid_by_name" ]; then
                _found_node="$nname"
                _found_node_ip="$nip"
                _found_vmid="$vmid_by_name"
                return 0
            fi
        fi
    done
    return 1
}

# Get VM config as key: value lines
_vm_config() {
    local node_ip="$1" vmid="$2"
    _vm_pve_cmd "$node_ip" "qm config ${vmid}" 2>/dev/null
}

# Extract a field value from VM config output
_vm_field() {
    local config="$1" field="$2"
    echo "$config" | grep "^${field}:" | sed "s/^${field}: *//"
}

# Get VM IP from cloud-init config, then guest agent, then hosts.conf
_vm_ip() {
    local node_ip="$1" vmid="$2"
    local config
    config=$(_vm_config "$node_ip" "$vmid")

    # Try cloud-init ipconfig0
    local ip
    ip=$(echo "$config" | grep '^ipconfig0' | grep -oP 'ip=\K[0-9.]+')
    [ -n "$ip" ] && { echo "$ip"; return 0; }

    # Try guest agent
    local agent_out
    agent_out=$(_vm_pve_cmd "$node_ip" "qm guest cmd ${vmid} network-get-interfaces" 2>/dev/null)
    if [ -n "$agent_out" ]; then
        ip=$(echo "$agent_out" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for iface in data:
        if iface.get('name') == 'lo': continue
        for addr in iface.get('ip-addresses', []):
            if addr.get('ip-address-type') == 'ipv4':
                a = addr.get('ip-address', '')
                if a and not a.startswith('127.'):
                    print(a); sys.exit(0)
except: pass
" 2>/dev/null)
        [ -n "$ip" ] && { echo "$ip"; return 0; }
    fi

    # Fallback: hosts.conf
    if [ -f "$HOSTS_FILE" ]; then
        ip=$(grep -v '^#' "$HOSTS_FILE" | grep -i "vm${vmid}" | head -1 | awk '{print $1}')
        [ -n "$ip" ] && { echo "$ip"; return 0; }
    fi
    return 1
}

# Get next available VMID from cluster
_vm_next_id() {
    local node_ip="${PVE_NODES[0]}"
    _vm_pve_cmd "$node_ip" "pvesh get /cluster/nextid" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# LIST — Cluster-wide VM inventory
# ═══════════════════════════════════════════════════════════════════

_vm_list() {
    require_ssh_key

    local filter_node="" filter_status=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --node)   filter_node="$2"; shift 2 ;;
            --running) filter_status="running"; shift ;;
            --stopped) filter_status="stopped"; shift ;;
            --help|-h) echo "Usage: freq vm list [--node NAME] [--running|--stopped]"; return 0 ;;
            *) die "Unknown flag: $1. Use --help for usage." ;;
        esac
    done

    local cluster_json="" node_ip
    for node_ip in "${PVE_NODES[@]}"; do
        cluster_json=$(_vm_pve_cmd "$node_ip" "pvesh get /cluster/resources --type vm --output-format json" 2>/dev/null)
        [ -n "$cluster_json" ] && break
    done
    [ -z "$cluster_json" ] && die "Cannot reach any PVE node. Check SSH connectivity to: ${PVE_NODES[*]}"

    freq_header "VM Inventory"

    local table
    table=$(echo "$cluster_json" | python3 -c "
import sys, json
from collections import OrderedDict

data = json.load(sys.stdin)
vms = [v for v in data if v.get('type') in ('qemu', 'lxc')]

node_filter = '${filter_node}'
status_filter = '${filter_status}'

if node_filter:
    vms = [v for v in vms if v.get('node') == node_filter]
if status_filter:
    vms = [v for v in vms if v.get('status') == status_filter]

nodes = OrderedDict()
for vm in sorted(vms, key=lambda v: v.get('vmid', 0)):
    node = vm.get('node', 'unknown')
    nodes.setdefault(node, []).append(vm)

for node in sorted(nodes.keys()):
    node_vms = nodes[node]
    running = sum(1 for v in node_vms if v.get('status') == 'running')
    print(f'__DIV__{node} -- {len(node_vms)} VMs ({running} running)')
    print(f'  {\"VMID\":>5}  {\"Name\":<22}  {\"Status\":<9}  {\"CPU\":>4}  {\"RAM\":>7}  {\"Type\":<4}')
    for vm in node_vms:
        vmid = vm.get('vmid', '?')
        name = vm.get('name', '?')[:22]
        status = vm.get('status', '?')
        maxcpu = vm.get('maxcpu', 0)
        maxmem_gb = vm.get('maxmem', 0) / (1024**3)
        typ = 'CT' if vm.get('type','') == 'lxc' else 'VM'
        is_tmpl = vm.get('template', 0) == 1
        if is_tmpl:
            status = 'template'
        sc = 'OK' if status == 'running' else ('!!' if status == 'stopped' else '--')
        print(f'  {sc:>2} {vmid:>4}  {name:<22}  {status:<9}  {maxcpu:>4}  {maxmem_gb:>5.1f}G  {typ:<4}')

total_running = sum(1 for v in vms if v.get('status') == 'running')
total_stopped = sum(1 for v in vms if v.get('status') == 'stopped' and not v.get('template'))
total_tmpl = sum(1 for v in vms if v.get('template', 0) == 1)
parts = f'{total_running} running, {total_stopped} stopped'
if total_tmpl: parts += f', {total_tmpl} template' + ('s' if total_tmpl > 1 else '')
print(f'__SUMMARY__{len(vms)} VMs/CTs across {len(nodes)} nodes -- {parts}')
" 2>/dev/null)

    if [ -n "$table" ]; then
        while IFS= read -r line; do
            if [[ "$line" == __DIV__* ]]; then
                freq_divider "${BOLD}${WHITE}${line#__DIV__}${RESET}"
            elif [[ "$line" == __SUMMARY__* ]]; then
                freq_blank
                freq_line "  ${DIM}${line#__SUMMARY__}${RESET}"
            else
                freq_line "$line"
            fi
        done <<< "$table"
    else
        freq_blank
        freq_line "  ${DIM}No VMs found or cannot parse cluster data.${RESET}"
    fi

    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# STATUS — Detailed VM health check
# ═══════════════════════════════════════════════════════════════════

_vm_status() {
    require_ssh_key

    local target="${1:-}"
    [ -z "$target" ] && die "Usage: freq vm status <vmid|name>"

    if ! _vm_find "$target"; then
        die "VM '${target}' not found on any PVE node. Check VMID or name."
    fi

    local vmid="$_found_vmid" node="$_found_node" node_ip="$_found_node_ip"
    local vm_config
    vm_config=$(_vm_config "$node_ip" "$vmid")
    [ -z "$vm_config" ] && die "Cannot read config for VM ${vmid} on ${node}."

    local vm_name vm_status vm_ip vm_cores vm_ram
    vm_name=$(_vm_field "$vm_config" "name")
    vm_status=$(_vm_pve_cmd "$node_ip" "qm status ${vmid}" 2>/dev/null | awk '{print $2}')
    vm_ip=$(_vm_ip "$node_ip" "$vmid")
    vm_cores=$(_vm_field "$vm_config" "cores")
    vm_ram=$(_vm_field "$vm_config" "memory")

    freq_header "Status > ${vm_name:-VM ${vmid}}"
    freq_blank
    freq_line "${BOLD}${WHITE}Health Check: VM ${vmid} (${vm_name:-?})${RESET}"
    freq_line "${DIM}Node: ${node}  IP: ${vm_ip:-unknown}${RESET}"
    freq_blank

    local ok=0 warn=0 fail=0

    # 1. VM running?
    if [ "$vm_status" = "running" ]; then
        freq_line "  ${GREEN}${_TICK}${RESET}  VM status: ${GREEN}running${RESET}"
        ok=$((ok + 1))
    elif [ "$vm_status" = "stopped" ]; then
        freq_line "  ${RED}${_CROSS}${RESET}  VM status: ${RED}stopped${RESET}"
        fail=$((fail + 1))
    else
        freq_line "  ${YELLOW}${_WARN}${RESET}  VM status: ${YELLOW}${vm_status:-unknown}${RESET}"
        warn=$((warn + 1))
    fi

    # 2. Guest agent (only if running)
    if [ "$vm_status" = "running" ]; then
        if _vm_pve_cmd "$node_ip" "qm guest cmd ${vmid} ping" &>/dev/null; then
            freq_line "  ${GREEN}${_TICK}${RESET}  Guest agent: responding"
            ok=$((ok + 1))
        else
            freq_line "  ${YELLOW}${_WARN}${RESET}  Guest agent: not responding"
            warn=$((warn + 1))
        fi
    fi

    # 3. Network reachability (only if we have an IP and VM is running)
    if [ "$vm_status" = "running" ] && [ -n "$vm_ip" ]; then
        if ping -c 1 -W 2 "$vm_ip" &>/dev/null; then
            freq_line "  ${GREEN}${_TICK}${RESET}  Network: ${vm_ip} reachable"
            ok=$((ok + 1))
        else
            freq_line "  ${RED}${_CROSS}${RESET}  Network: ${vm_ip} unreachable"
            fail=$((fail + 1))
        fi
    fi

    # 4. SSH (only if running + reachable)
    if [ "$vm_status" = "running" ] && [ -n "$vm_ip" ]; then
        if freq_ssh "$vm_ip" "echo SSH_OK" &>/dev/null; then
            freq_line "  ${GREEN}${_TICK}${RESET}  SSH: connected"
            ok=$((ok + 1))
        else
            freq_line "  ${YELLOW}${_WARN}${RESET}  SSH: cannot connect"
            warn=$((warn + 1))
        fi
    fi

    # 5. Protection status
    if _is_protected_vmid "$vmid"; then
        freq_line "  ${YELLOW}${_WARN}${RESET}  Protection: ${BOLD}${PROTECTED_TYPE}${RESET}"
    else
        freq_line "  ${DIM}      Protection: none${RESET}"
    fi

    # 6. Config summary
    freq_blank
    freq_divider "Configuration"
    freq_line "$(printf "  %-12s %s" "CPU:" "${vm_cores:-?} cores")"
    freq_line "$(printf "  %-12s %s MB" "RAM:" "${vm_ram:-?}")"

    # Disk info from config
    local disk_lines
    disk_lines=$(echo "$vm_config" | grep -E '^(scsi|virtio|ide|sata|efidisk)[0-9]*:' | head -5)
    if [ -n "$disk_lines" ]; then
        while IFS= read -r dline; do
            local dname dsize
            dname=$(echo "$dline" | cut -d: -f1)
            dsize=$(echo "$dline" | grep -oP 'size=\K[^,]+')
            freq_line "$(printf "  %-12s %s" "${dname}:" "${dsize:-?}")"
        done <<< "$disk_lines"
    fi

    # Network config
    local net_lines
    net_lines=$(echo "$vm_config" | grep -E '^net[0-9]+:' | head -5)
    if [ -n "$net_lines" ]; then
        while IFS= read -r nline; do
            local nname nbridge ntag
            nname=$(echo "$nline" | cut -d: -f1)
            nbridge=$(echo "$nline" | grep -oP 'bridge=\K[^,]+')
            ntag=$(echo "$nline" | grep -oP 'tag=\K[0-9]+')
            local ninfo="${nbridge:-?}"
            [ -n "$ntag" ] && ninfo="${ninfo} (VLAN ${ntag})"
            freq_line "$(printf "  %-12s %s" "${nname}:" "${ninfo}")"
        done <<< "$net_lines"
    fi

    freq_blank
    freq_line "  ${DIM}${ok} OK, ${warn} warnings, ${fail} failures${RESET}"
    freq_blank
    freq_footer

    [ "$fail" -gt 0 ] && return 1
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# CREATE — Cloud-init VM creation
# ═══════════════════════════════════════════════════════════════════

_vm_create() {
    require_operator || return 1
    require_ssh_key

    local vmid="" vm_name="" distro="" node="" cores=2 memory=2048 disk="60G"
    local vlan="" ip="" gw="" bridge="vmbr0" storage="local-zfs"
    local dry_run="${DRY_RUN:-false}" auto_yes="${FREQ_YES:-false}" start_after=true

    while [ $# -gt 0 ]; do
        case "$1" in
            --vmid)    vmid="$2"; shift 2 ;;
            --name)    vm_name="$2"; shift 2 ;;
            --distro)  distro="$2"; shift 2 ;;
            --node)    node="$2"; shift 2 ;;
            --cores)   cores="$2"; shift 2 ;;
            --memory)  memory="$2"; shift 2 ;;
            --disk)    disk="$2"; shift 2 ;;
            --vlan)    vlan="$2"; shift 2 ;;
            --ip)      ip="$2"; shift 2 ;;
            --gateway) gw="$2"; shift 2 ;;
            --bridge)  bridge="$2"; shift 2 ;;
            --storage) storage="$2"; shift 2 ;;
            --no-start) start_after=false; shift ;;
            --dry-run) dry_run=true; shift ;;
            --yes|-y)  auto_yes=true; shift ;;
            --help|-h)
                echo "Usage: freq vm create --name NAME --distro DISTRO [options]"
                echo ""
                echo "Required:"
                echo "  --name NAME       VM hostname"
                echo "  --distro DISTRO   Cloud image (e.g., debian-13, ubuntu-2404)"
                echo ""
                echo "Optional:"
                echo "  --vmid N          Specific VMID (default: auto-assign)"
                echo "  --node NAME       PVE node (default: pve01)"
                echo "  --cores N         CPU cores (default: 2)"
                echo "  --memory N        RAM in MB (default: 2048)"
                echo "  --disk SIZE       Root disk (default: 60G)"
                echo "  --vlan TAG        VLAN tag for net0"
                echo "  --ip ADDR/CIDR    Static IP (e.g., 10.25.255.50/24)"
                echo "  --gateway IP      Default gateway"
                echo "  --bridge NAME     Bridge name (default: vmbr0)"
                echo "  --storage NAME    Storage backend (default: local-zfs)"
                echo "  --no-start        Do not start VM after creation"
                echo "  --dry-run         Show what would be done"
                echo "  --yes             Skip confirmation"
                echo ""
                echo "Distros: ${DISTRO_ORDER[*]}"
                return 0 ;;
            *) die "Unknown flag: $1. Use --help for usage." ;;
        esac
    done

    [ -z "$vm_name" ] && die "VM name is required. Usage: freq vm create --name NAME --distro DISTRO"
    [ -z "$distro" ] && die "Distro is required. Usage: freq vm create --name NAME --distro DISTRO"
    [[ "$vm_name" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "Invalid name: lowercase alphanumeric and hyphens only"

    # Resolve distro alias
    if [ -n "${DISTRO_ALIASES[$distro]+x}" ]; then
        distro="${DISTRO_ALIASES[$distro]}"
    fi
    [ -z "${DISTRO_NAMES[$distro]+x}" ] && die "Unknown distro: ${distro}. Available: ${DISTRO_ORDER[*]}"

    # Determine target node
    local target_node_ip=""
    if [ -z "$node" ]; then
        node="${PVE_NODE_NAMES[0]}"
        target_node_ip="${PVE_NODES[0]}"
    else
        local ni
        for ((ni=0; ni<${#PVE_NODE_NAMES[@]}; ni++)); do
            if [ "${PVE_NODE_NAMES[$ni]}" = "$node" ]; then
                target_node_ip="${PVE_NODES[$ni]}"
                break
            fi
        done
        [ -z "$target_node_ip" ] && die "Unknown node: ${node}. Valid: ${PVE_NODE_NAMES[*]}"
    fi

    # Auto-assign VMID if not specified
    if [ -z "$vmid" ]; then
        vmid=$(_vm_next_id)
        [[ "$vmid" =~ ^[0-9]+$ ]] || die "Cannot allocate VMID from cluster. Check PVE connectivity."
    else
        [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: ${vmid}"
        # Check if VMID already in use
        if _vm_find "$vmid" 2>/dev/null; then
            die "VMID ${vmid} already exists on ${_found_node}."
        fi
    fi

    # Protection check on target VMID
    if _is_protected_vmid "$vmid"; then
        echo -e "  ${YELLOW}${_WARN}${RESET}  Target VMID ${vmid} is in protected range (${PROTECTED_TYPE})"
        if ! require_protected "create VM in protected range ${PROTECTED_TYPE} (VMID ${vmid})" "$target_node_ip"; then
            return 1
        fi
    fi

    # Build cloud-init network config
    local net_opts="virtio,bridge=${bridge}"
    [ -n "$vlan" ] && net_opts="${net_opts},tag=${vlan}"

    local ci_ip="dhcp"
    if [ -n "$ip" ]; then
        ci_ip="ip=${ip}"
        [ -n "$gw" ] && ci_ip="${ci_ip},gw=${gw}"
    fi

    local distro_name="${DISTRO_NAMES[$distro]}"
    local distro_url="${DISTRO_URLS[$distro]}"
    local distro_file="${DISTRO_FILES[$distro]}"
    local img_dir="/var/lib/vz/template/iso"

    freq_header "Create VM"
    freq_blank
    freq_line "$(printf "  %-12s %s" "VMID:" "${vmid}")"
    freq_line "$(printf "  %-12s %s" "Name:" "${vm_name}")"
    freq_line "$(printf "  %-12s %s" "Distro:" "${distro_name}")"
    freq_line "$(printf "  %-12s %s" "Node:" "${node}")"
    freq_line "$(printf "  %-12s %s cores, %s MB RAM, %s disk" "Resources:" "${cores}" "${memory}" "${disk}")"
    freq_line "$(printf "  %-12s %s" "Network:" "${net_opts}")"
    freq_line "$(printf "  %-12s %s" "IP:" "${ci_ip}")"
    freq_line "$(printf "  %-12s %s" "Storage:" "${storage}")"
    freq_blank
    freq_footer

    if $dry_run; then
        echo ""
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would create VM ${vmid} (${vm_name}) on ${node}"
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Distro: ${distro_name}"
        echo -e "  ${CYAN}[DRY-RUN]${RESET} No changes made."
        return 0
    fi

    if ! $auto_yes; then
        if ! ask_rsq "Create VM ${vmid} (${vm_name})?"; then
            echo -e "  ${YELLOW}Aborted.${RESET}"
            return 1
        fi
    fi

    # Step 1: Check/download cloud image
    _step_start "Checking cloud image..."
    local img_exists
    img_exists=$(_vm_pve_cmd "$target_node_ip" "test -f ${img_dir}/${distro_file} && echo YES" 2>/dev/null)
    if [ "$img_exists" = "YES" ]; then
        _step_ok "Image cached: ${distro_file}"
    else
        _step_warn "Downloading ${distro_file}..."
        local dl_out
        dl_out=$(_vm_pve_cmd "$target_node_ip" "wget -q -O ${img_dir}/${distro_file} '${distro_url}'" 2>&1)
        if [ $? -ne 0 ]; then
            _step_fail "Download failed: ${dl_out}"
            return 1
        fi
        _step_ok "Downloaded ${distro_file}"
    fi

    # Step 2: Create VM skeleton + import disk + configure (single SSH call)
    _step_start "Creating VM ${vmid}..."
    local ssh_key_pub
    ssh_key_pub=$(cat "${FREQ_SSH_KEY}.pub" 2>/dev/null)
    [ -z "$ssh_key_pub" ] && ssh_key_pub=$(get_ssh_pubkey 2>/dev/null)

    local create_script="
set -e
# Create skeleton
qm create ${vmid} --name ${vm_name} --cores ${cores} --memory ${memory} \
    --net0 ${net_opts} --ostype l26 --scsihw virtio-scsi-single --agent 1

# Import disk
qm importdisk ${vmid} ${img_dir}/${distro_file} ${storage} 2>/dev/null

# Attach disk + configure
qm set ${vmid} --scsi0 ${storage}:vm-${vmid}-disk-0,discard=on,iothread=1,ssd=1
qm set ${vmid} --boot order=scsi0
qm set ${vmid} --serial0 socket --vga serial0

# Resize disk
qm disk resize ${vmid} scsi0 ${disk} 2>/dev/null

# Cloud-init
qm set ${vmid} --ide2 ${storage}:cloudinit
qm set ${vmid} --ciuser ${FREQ_SERVICE_ACCOUNT:-svc-admin}
qm set ${vmid} --ipconfig0 ${ci_ip}
"
    # Add SSH key if available (write to temp file to avoid quoting issues)
    if [ -n "$ssh_key_pub" ]; then
        create_script="${create_script}
echo '${ssh_key_pub}' > /tmp/freq-sshkey-${vmid}.pub
qm set ${vmid} --sshkeys /tmp/freq-sshkey-${vmid}.pub
rm -f /tmp/freq-sshkey-${vmid}.pub
"
    fi

    local create_out
    create_out=$(_vm_pve_cmd "$target_node_ip" "bash -c '${create_script}'" 2>&1)
    if [ $? -ne 0 ]; then
        _step_fail "Creation failed"
        echo -e "    ${DIM}${create_out}${RESET}" | head -5
        log "vm create FAILED: VM ${vmid} (${vm_name}) on ${node}"
        return 1
    fi
    _step_ok "VM ${vmid} created"

    # Step 3: Start VM (unless --no-start)
    if $start_after; then
        _step_start "Starting VM ${vmid}..."
        local start_out
        start_out=$(_vm_pve_cmd "$target_node_ip" "qm start ${vmid}" 2>&1)
        if [ $? -eq 0 ]; then
            _step_ok "VM ${vmid} started"
        else
            _step_warn "Start failed: ${start_out}"
        fi
    fi

    echo ""
    echo -e "  ${GREEN}${_TICK}${RESET}  ${BOLD}VM ${vmid}${RESET} (${vm_name}) created on ${node}"
    [ -n "$ip" ] && echo -e "  ${DIM}IP: ${ip}${RESET}"
    echo ""
    log "vm create: VM ${vmid} (${vm_name}) on ${node} -- ${distro_name}, ${cores}c/${memory}M/${disk}"
    freq_celebrate 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# CLONE — Clone an existing VM
# ═══════════════════════════════════════════════════════════════════

_vm_clone() {
    require_operator || return 1
    require_ssh_key

    local src_vmid="" new_name="" new_vmid="" target_node="" new_ip=""
    local dry_run="${DRY_RUN:-false}" auto_yes="${FREQ_YES:-false}" full_clone=true

    while [ $# -gt 0 ]; do
        case "$1" in
            --vmid)    new_vmid="$2"; shift 2 ;;
            --node)    target_node="$2"; shift 2 ;;
            --ip)      new_ip="$2"; shift 2 ;;
            --linked)  full_clone=false; shift ;;
            --dry-run) dry_run=true; shift ;;
            --yes|-y)  auto_yes=true; shift ;;
            --help|-h)
                echo "Usage: freq vm clone <source-vmid> <new-name> [options]"
                echo ""
                echo "  --vmid N       New VMID (default: auto-assign)"
                echo "  --node NAME    Target PVE node"
                echo "  --ip ADDR/CIDR New IP address"
                echo "  --linked       Linked clone (default: full)"
                echo "  --dry-run      Show what would be done"
                echo "  --yes          Skip confirmation"
                return 0 ;;
            -*)  die "Unknown flag: $1. Use --help for usage." ;;
            *)
                if [ -z "$src_vmid" ]; then src_vmid="$1"
                elif [ -z "$new_name" ]; then new_name="$1"
                else die "Too many arguments. Use --help for usage."
                fi
                shift ;;
        esac
    done

    [ -z "$src_vmid" ] && die "Usage: freq vm clone <source-vmid> <new-name> [--vmid N] [--node NAME]"
    [ -z "$new_name" ] && die "Usage: freq vm clone <source-vmid> <new-name>"
    [[ "$src_vmid" =~ ^[0-9]+$ ]] || die "Invalid source VMID: ${src_vmid}"
    [[ "$new_name" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "Invalid name: lowercase alphanumeric and hyphens only"

    if ! _vm_find "$src_vmid"; then
        die "Source VM ${src_vmid} not found on any PVE node."
    fi
    local src_node="$_found_node" src_node_ip="$_found_node_ip"

    # Resolve target node
    local clone_node_ip="$src_node_ip"
    local clone_node="${target_node:-$src_node}"
    if [ -n "$target_node" ]; then
        local ni
        for ((ni=0; ni<${#PVE_NODE_NAMES[@]}; ni++)); do
            if [ "${PVE_NODE_NAMES[$ni]}" = "$target_node" ]; then
                clone_node_ip="${PVE_NODES[$ni]}"
                break
            fi
        done
        [ "$clone_node_ip" = "$src_node_ip" ] && [ "$target_node" != "$src_node" ] && \
            die "Unknown node: ${target_node}. Valid: ${PVE_NODE_NAMES[*]}"
    fi

    # Auto-assign VMID
    if [ -z "$new_vmid" ]; then
        new_vmid=$(_vm_next_id)
        [[ "$new_vmid" =~ ^[0-9]+$ ]] || die "Cannot allocate VMID."
    fi

    local src_config
    src_config=$(_vm_config "$src_node_ip" "$src_vmid")
    local src_name
    src_name=$(_vm_field "$src_config" "name")

    freq_header "Clone VM"
    freq_blank
    freq_line "$(printf "  %-12s %s (%s) on %s" "Source:" "${src_name:-?}" "${src_vmid}" "${src_node}")"
    freq_line "$(printf "  %-12s %s (%s) on %s" "Target:" "${new_name}" "${new_vmid}" "${clone_node}")"
    freq_line "$(printf "  %-12s %s" "Mode:" "$($full_clone && echo "Full clone" || echo "Linked clone")")"
    [ -n "$new_ip" ] && freq_line "$(printf "  %-12s %s" "New IP:" "${new_ip}")"
    freq_blank
    freq_footer

    if $dry_run; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would clone VM ${src_vmid} → ${new_vmid} (${new_name})"
        return 0
    fi

    if ! $auto_yes; then
        if ! ask_rsq "Clone VM ${src_vmid} → ${new_vmid} (${new_name})?"; then
            echo -e "  ${YELLOW}Aborted.${RESET}"
            return 1
        fi
    fi

    local clone_cmd="qm clone ${src_vmid} ${new_vmid} --name ${new_name}"
    $full_clone && clone_cmd="${clone_cmd} --full"
    [ "$clone_node" != "$src_node" ] && clone_cmd="${clone_cmd} --target ${clone_node}"

    # Use animated spinner for clone (can take 30-60s for full clones)
    if declare -f _spinner_start &>/dev/null && [ -t 1 ]; then
        _spinner_start "Cloning VM ${src_vmid} → ${new_vmid}..."
        local clone_out
        clone_out=$(_vm_pve_cmd "$src_node_ip" "${clone_cmd}" 2>&1)
        local rc=$?
        if [ $rc -ne 0 ]; then
            _spinner_stop fail "Clone failed"
            echo -e "    ${DIM}${clone_out}${RESET}" | head -3
            return 1
        fi
        _spinner_stop ok "Cloned to VM ${new_vmid}"
    else
        _step_start "Cloning VM ${src_vmid} → ${new_vmid}..."
        local clone_out
        clone_out=$(_vm_pve_cmd "$src_node_ip" "${clone_cmd}" 2>&1)
        if [ $? -ne 0 ]; then
            _step_fail "Clone failed"
            echo -e "    ${DIM}${clone_out}${RESET}" | head -3
            return 1
        fi
        _step_ok "Cloned to VM ${new_vmid}"
    fi

    # Set new IP if requested
    if [ -n "$new_ip" ]; then
        _step_start "Setting IP to ${new_ip}..."
        _vm_pve_cmd "$clone_node_ip" "qm set ${new_vmid} --ipconfig0 ip=${new_ip}" 2>&1
        _step_ok "IP configured"
    fi

    echo ""
    echo -e "  ${GREEN}${_TICK}${RESET}  ${BOLD}VM ${new_vmid}${RESET} (${new_name}) cloned from ${src_vmid}"
    echo ""
    log "vm clone: ${src_vmid} (${src_name}) → ${new_vmid} (${new_name}) on ${clone_node}"
    freq_celebrate 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# RESIZE — Resize VM CPU, RAM, or disk
# ═══════════════════════════════════════════════════════════════════

_vm_resize() {
    require_operator || return 1
    require_ssh_key

    local vmid="" flag_cores="" flag_ram="" flag_disk=""
    local dry_run="${DRY_RUN:-false}" auto_yes="${FREQ_YES:-false}" force=false

    while [ $# -gt 0 ]; do
        case "$1" in
            --cores|-c)  flag_cores="$2"; shift 2 ;;
            --memory|-m) flag_ram="$2"; shift 2 ;;
            --disk|-d)   flag_disk="$2"; shift 2 ;;
            --yes|-y)    auto_yes=true; shift ;;
            --force)     force=true; shift ;;
            --dry-run)   dry_run=true; shift ;;
            --help|-h)
                echo "Usage: freq vm resize <vmid> [--cores N] [--memory N] [--disk +NG] [--force] [--dry-run]"
                return 0 ;;
            -*)  die "Unknown flag: $1. Use --help for usage." ;;
            *)
                [ -z "$vmid" ] && { vmid="$1"; shift; continue; }
                die "Too many arguments. Use --help for usage." ;;
        esac
    done

    [ -z "$vmid" ] && die "Usage: freq vm resize <vmid> [--cores N] [--memory N] [--disk +NG]"
    [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: ${vmid}"
    [ -z "$flag_cores" ] && [ -z "$flag_ram" ] && [ -z "$flag_disk" ] && \
        die "Specify at least one: --cores N, --memory N, or --disk +NG"

    # Protected VMID guard
    if _is_protected_vmid "$vmid"; then
        if ! $force; then
            echo -e "  ${RED}${_CROSS}${RESET}  VM ${vmid} is protected (${PROTECTED_TYPE}). Use --force to override."
            return 1
        fi
        echo -e "  ${YELLOW}${_WARN}${RESET}  --force: proceeding with protected VM ${vmid} (${PROTECTED_TYPE})"
    fi

    if ! _vm_find "$vmid"; then
        die "VM ${vmid} not found on any PVE node."
    fi
    local node="$_found_node" node_ip="$_found_node_ip"

    local vm_config
    vm_config=$(_vm_config "$node_ip" "$vmid")
    local vm_name cur_cores cur_ram
    vm_name=$(_vm_field "$vm_config" "name")
    cur_cores=$(_vm_field "$vm_config" "cores")
    cur_ram=$(_vm_field "$vm_config" "memory")

    freq_header "Resize VM > ${vm_name:-VM ${vmid}}"
    freq_blank
    [ -n "$flag_cores" ] && freq_line "$(printf "  CPU:    %s → %s cores" "${cur_cores:-?}" "${flag_cores}")"
    [ -n "$flag_ram" ] && freq_line "$(printf "  RAM:    %s → %s MB" "${cur_ram:-?}" "${flag_ram}")"
    [ -n "$flag_disk" ] && freq_line "$(printf "  Disk:   %s (scsi0)" "${flag_disk}")"
    freq_blank
    freq_footer

    if $dry_run; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would resize VM ${vmid}. No changes made."
        return 0
    fi

    if ! $auto_yes; then
        if ! ask_rsq "Resize VM ${vmid} (${vm_name:-?})?"; then
            echo -e "  ${YELLOW}Aborted.${RESET}"
            return 1
        fi
    fi

    local changes=0

    if [ -n "$flag_cores" ]; then
        _step_start "Setting CPU to ${flag_cores} cores..."
        if _vm_pve_cmd "$node_ip" "qm set ${vmid} --cores ${flag_cores}" &>/dev/null; then
            _step_ok "CPU: ${flag_cores} cores"
            changes=$((changes + 1))
        else
            _step_fail "CPU change failed"
        fi
    fi

    if [ -n "$flag_ram" ]; then
        _step_start "Setting RAM to ${flag_ram} MB..."
        if _vm_pve_cmd "$node_ip" "qm set ${vmid} --memory ${flag_ram}" &>/dev/null; then
            _step_ok "RAM: ${flag_ram} MB"
            changes=$((changes + 1))
        else
            _step_fail "RAM change failed"
        fi
    fi

    if [ -n "$flag_disk" ]; then
        _step_start "Resizing disk scsi0 by ${flag_disk}..."
        local disk_out
        disk_out=$(_vm_pve_cmd "$node_ip" "qm disk resize ${vmid} scsi0 ${flag_disk}" 2>&1)
        if [ $? -eq 0 ]; then
            _step_ok "Disk resized: ${flag_disk}"
            changes=$((changes + 1))
        else
            _step_fail "Disk resize failed: ${disk_out}"
        fi
    fi

    echo ""
    echo -e "  ${GREEN}${_TICK}${RESET}  ${changes} change(s) applied to VM ${vmid}"
    echo ""
    log "vm resize: VM ${vmid} (${vm_name}) -- cores=${flag_cores:-unchanged} ram=${flag_ram:-unchanged} disk=${flag_disk:-unchanged}"
}

# ═══════════════════════════════════════════════════════════════════
# DESTROY — Permanently destroy a VM
# ═══════════════════════════════════════════════════════════════════

_vm_destroy() {
    local vmid="${1:-}"
    local force=false purge=true
    [ "${2:-}" = "--force" ] && force=true
    [ "${2:-}" = "--yes" ] && force=true
    [ "${3:-}" = "--force" ] && force=true

    [ -z "$vmid" ] && die "Usage: freq vm destroy <vmid> [--force]"

    require_elevated "vm destroy" || return 1
    require_ssh_key
    [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: ${vmid}"

    # Protected VMID check
    if _is_protected_vmid "$vmid"; then
        echo -e "  ${YELLOW}${_WARN}${RESET}  VM ${vmid} is protected (${PROTECTED_TYPE})"
        if ! _vm_find "$vmid"; then
            die "VM ${vmid} not found on any PVE node."
        fi
        if ! require_protected "destroy protected VM ${vmid} (${PROTECTED_TYPE})" "$_found_node_ip" \
            "This will permanently delete VM ${vmid} and all its data." \
            "Recovery: restore from vzdump backup only."; then
            return 1
        fi
    fi

    if ! _vm_find "$vmid"; then
        die "VM ${vmid} not found on any PVE node."
    fi
    local node="$_found_node" node_ip="$_found_node_ip"

    local vm_config
    vm_config=$(_vm_config "$node_ip" "$vmid")
    local vm_name vm_status vm_ip
    vm_name=$(_vm_field "$vm_config" "name")
    vm_status=$(_vm_pve_cmd "$node_ip" "qm status ${vmid}" 2>/dev/null | awk '{print $2}')
    vm_ip=$(_vm_ip "$node_ip" "$vmid")

    freq_header "Destroy VM"
    freq_blank
    freq_line "${RED}${BOLD}  WARNING: This will permanently destroy VM ${vmid}${RESET}"
    freq_blank
    freq_line "$(printf "  %-12s %s (%s)" "VM:" "${vm_name:-?}" "${vmid}")"
    freq_line "$(printf "  %-12s %s" "Node:" "${node}")"
    freq_line "$(printf "  %-12s %s" "Status:" "${vm_status:-?}")"
    [ -n "$vm_ip" ] && freq_line "$(printf "  %-12s %s" "IP:" "${vm_ip}")"
    freq_blank
    freq_footer

    # Respect --yes global flag and --force local flag
    if ! $force && [ "${FREQ_YES:-false}" != "true" ]; then
        if [ ! -t 0 ]; then
            echo -e "  ${YELLOW}Aborted.${RESET} (non-interactive — use --yes to confirm)"
            return 1
        fi
        if ! ask_rsq "PERMANENTLY destroy VM ${vmid} (${vm_name:-?})?"; then
            echo -e "  ${YELLOW}Aborted.${RESET}"
            return 1
        fi
    fi

    # Stop VM if running
    if [ "$vm_status" = "running" ]; then
        _step_start "Stopping VM ${vmid}..."
        _vm_pve_cmd "$node_ip" "qm stop ${vmid}" &>/dev/null
        _step_ok "VM stopped"
    fi

    _step_start "Destroying VM ${vmid}..."
    local destroy_cmd="qm destroy ${vmid}"
    $purge && destroy_cmd="${destroy_cmd} --purge"

    local destroy_out
    destroy_out=$(_vm_pve_cmd "$node_ip" "${destroy_cmd}" 2>&1)
    if [ $? -eq 0 ]; then
        _step_ok "VM ${vmid} destroyed"
    else
        _step_fail "Destroy failed"
        echo -e "    ${DIM}${destroy_out}${RESET}" | head -3
        return 1
    fi

    echo ""
    echo -e "  ${RED}${_CROSS}${RESET}  VM ${vmid} (${vm_name:-?}) permanently destroyed on ${node}"
    echo ""
    log "vm destroy: VM ${vmid} (${vm_name}) on ${node}"
}

# ═══════════════════════════════════════════════════════════════════
# SNAPSHOT — Create, list, or delete VM snapshots
# ═══════════════════════════════════════════════════════════════════

_vm_snapshot() {
    require_operator || return 1
    require_ssh_key

    local vmid="" action="create" snap_name="" force=false dry_run="${DRY_RUN:-false}"

    while [ $# -gt 0 ]; do
        case "$1" in
            --list)    action="list"; shift ;;
            --delete)  action="delete"; snap_name="$2"; shift 2 ;;
            --force)   force=true; shift ;;
            --dry-run) dry_run=true; shift ;;
            --help|-h)
                echo "Usage: freq vm snapshot <vmid> [--list] [--delete NAME] [--force] [--dry-run]"
                return 0 ;;
            -*)  die "Unknown flag: $1. Use --help for usage." ;;
            *)   [ -z "$vmid" ] && { vmid="$1"; shift; continue; }
                 die "Too many arguments. Use --help for usage." ;;
        esac
    done

    [ -z "$vmid" ] && die "Usage: freq vm snapshot <vmid>"
    [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: ${vmid}"

    # Protected VMID guard
    if _is_protected_vmid "$vmid" && ! $force; then
        echo -e "  ${RED}${_CROSS}${RESET}  VM ${vmid} is protected (${PROTECTED_TYPE}). Use --force to override."
        return 1
    fi

    if ! _vm_find "$vmid"; then
        die "VM ${vmid} not found on any PVE node."
    fi
    local node="$_found_node" node_ip="$_found_node_ip"
    local vm_name
    vm_name=$(_vm_pve_cmd "$node_ip" "qm config ${vmid}" 2>/dev/null | grep '^name:' | awk '{print $2}')

    case "$action" in
        list)
            freq_header "Snapshots > ${vm_name:-VM ${vmid}}"
            freq_blank
            local snap_out
            snap_out=$(_vm_pve_cmd "$node_ip" "qm listsnapshot ${vmid}" 2>/dev/null)
            if [ -n "$snap_out" ]; then
                while IFS= read -r line; do
                    freq_line "  ${line}"
                done <<< "$snap_out"
            else
                freq_line "  ${DIM}No snapshots.${RESET}"
            fi
            freq_blank
            freq_footer
            ;;

        delete)
            [ -z "$snap_name" ] && die "Snapshot name required: --delete NAME"
            if $dry_run; then
                echo -e "  ${CYAN}[DRY-RUN]${RESET} Would delete snapshot '${snap_name}' from VM ${vmid}"
                return 0
            fi
            _step_start "Deleting snapshot ${snap_name}..."
            if _vm_pve_cmd "$node_ip" "qm delsnapshot ${vmid} ${snap_name}" &>/dev/null; then
                _step_ok "Snapshot deleted"
                log "vm snapshot delete: ${snap_name} on VM ${vmid}"
            else
                _step_fail "Delete failed"
                return 1
            fi
            ;;

        create)
            local new_snap
            new_snap="freq-snap-$(date '+%Y%m%d-%H%M%S')"
            freq_header "Snapshot > ${vm_name:-VM ${vmid}}"
            freq_blank
            freq_line "$(printf "  %-12s %s" "VMID:" "${vmid}")"
            freq_line "$(printf "  %-12s %s" "Name:" "${vm_name:-unknown}")"
            freq_line "$(printf "  %-12s %s" "Snapshot:" "${new_snap}")"
            freq_blank
            freq_line "  ${YELLOW}${_WARN}${RESET}  PVE snapshots disable live migration until removed."
            freq_blank
            freq_footer

            if $dry_run; then
                echo -e "  ${CYAN}[DRY-RUN]${RESET} Would create snapshot: ${new_snap}"
                return 0
            fi

            if ! ask_rsq "Create snapshot?"; then
                echo -e "  ${YELLOW}Aborted.${RESET}"
                return 1
            fi

            _step_start "Creating snapshot ${new_snap}..."
            local desc
            desc="FREQ snapshot $(date '+%Y-%m-%d %H:%M:%S')"
            if _vm_pve_cmd "$node_ip" "qm snapshot ${vmid} ${new_snap} --description '${desc}'" &>/dev/null; then
                _step_ok "Snapshot created"
                echo ""
                echo -e "  ${GREEN}${_TICK}${RESET}  ${BOLD}${new_snap}${RESET} on VM ${vmid} (${vm_name:-?})"
                echo ""
                log "vm snapshot: created ${new_snap} on VM ${vmid} (${vm_name})"
            else
                _step_fail "Snapshot failed"
                return 1
            fi
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# CHANGE-ID — Rename VM ID (MUST SHIP F1)
# Renames VMID, all ZFS volumes, config, firewall, HA references
# ═══════════════════════════════════════════════════════════════════

_vm_change_id() {
    local old_id="" new_id="" dry_run="${DRY_RUN:-false}" auto_yes="${FREQ_YES:-false}"

    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run) dry_run=true; shift ;;
            --yes|-y)  auto_yes=true; shift ;;
            --help|-h)
                echo "Usage: freq vm change-id <old-vmid> <new-vmid> [--dry-run] [--yes]"
                echo ""
                echo "Changes a VM's ID, renaming all associated ZFS volumes,"
                echo "config files, and firewall rules. VM must be stopped."
                echo ""
                echo "Example: freq vm change-id 999 900"
                return 0 ;;
            -*)  die "Unknown flag: $1. Use --help for usage." ;;
            *)
                if [ -z "$old_id" ]; then old_id="$1"
                elif [ -z "$new_id" ]; then new_id="$1"
                else die "Too many arguments. Use --help for usage."
                fi
                shift ;;
        esac
    done

    [ -z "$old_id" ] || [ -z "$new_id" ] && die "Usage: freq vm change-id <old-vmid> <new-vmid>"

    # RBAC + SSH key (skip for dry-run to allow non-interactive planning)
    if ! $dry_run; then
        require_elevated "vm change-id" || return 1
    fi
    require_ssh_key
    [[ "$old_id" =~ ^[0-9]+$ ]] || die "Invalid old VMID: ${old_id}"
    [[ "$new_id" =~ ^[0-9]+$ ]] || die "Invalid new VMID: ${new_id}"
    [ "$old_id" = "$new_id" ] && die "Old and new VMID are the same."

    # Find old VM
    if ! _vm_find "$old_id"; then
        die "VM ${old_id} not found on any PVE node. Check VMID."
    fi
    local node="$_found_node" node_ip="$_found_node_ip"

    # Verify new VMID is not in use
    if _vm_find "$new_id" 2>/dev/null; then
        die "VMID ${new_id} already exists on ${_found_node}. Choose a different target VMID."
    fi

    # Get VM details
    local vm_config
    vm_config=$(_vm_config "$node_ip" "$old_id")
    [ -z "$vm_config" ] && die "Cannot read config for VM ${old_id}."
    local vm_name vm_status
    vm_name=$(_vm_field "$vm_config" "name")
    vm_status=$(_vm_pve_cmd "$node_ip" "qm status ${old_id}" 2>/dev/null | awk '{print $2}')

    # VM must be stopped (unless dry-run — allow planning on running VMs)
    if [ "$vm_status" = "running" ] && ! $dry_run; then
        echo -e "  ${RED}${_CROSS}${RESET}  VM ${old_id} is running. Stop it first: freq vm stop ${old_id}"
        echo -e "  ${DIM}Or stop automatically with: freq vm change-id ${old_id} ${new_id} --yes${RESET}"
        if $auto_yes; then
            _step_start "Stopping VM ${old_id}..."
            _vm_pve_cmd "$node_ip" "qm stop ${old_id}" &>/dev/null
            sleep 3
            _step_ok "VM stopped"
        else
            return 1
        fi
    fi

    # Protection checks on both old and new VMIDs
    local old_protected=false new_protected=false
    local old_prot_type="" new_prot_type=""
    if _is_protected_vmid "$old_id"; then
        old_protected=true
        old_prot_type="$PROTECTED_TYPE"
    fi
    if _is_protected_vmid "$new_id"; then
        new_protected=true
        new_prot_type="$PROTECTED_TYPE"
    fi

    # Show protection warnings (but only enforce auth if not dry-run)
    if $old_protected || $new_protected; then
        echo -e "  ${YELLOW}${_WARN}${RESET}  Protected operation:"
        $old_protected && echo -e "    ${_ARROW} Moving OUT of protected range: ${old_prot_type} (VMID ${old_id})"
        $new_protected && echo -e "    ${_ARROW} Moving INTO protected range: ${new_prot_type} (VMID ${new_id})"

        if ! $dry_run; then
            local prot_desc="change-id: VM ${old_id}"
            [ "$old_protected" = true ] && prot_desc="${prot_desc} (protected: ${old_prot_type})"
            prot_desc="${prot_desc} → ${new_id}"
            [ "$new_protected" = true ] && prot_desc="${prot_desc} (protected: ${new_prot_type})"

            if ! require_protected "$prot_desc" "$node_ip" \
                "This renames all ZFS volumes and PVE config for VM ${old_id}." \
                "Recovery: manual ZFS rename + config restore from /etc/pve backup." \
                "--no-locality"; then
                return 1
            fi
        fi
    fi

    # Identify disks to rename (extract storage:vm-<old>-disk-N from config)
    local disk_lines
    disk_lines=$(echo "$vm_config" | grep -E '^(scsi|virtio|ide|sata|efidisk)[0-9]*:' | \
        grep -oP '[^,\s]+:vm-'"${old_id}"'-disk-[0-9]+' | sort -u)
    # Also check for cloud-init disk
    local ci_disk
    ci_disk=$(echo "$vm_config" | grep -E '^(ide|scsi)[0-9]*:.*cloudinit' | \
        grep -oP '[^,\s]+:vm-'"${old_id}"'-cloudinit' | head -1)

    # Determine storage backend for each disk
    local zfs_renames=() config_seds=()
    if [ -n "$disk_lines" ]; then
        while IFS= read -r disk_ref; do
            local vol_name
            vol_name=$(echo "$disk_ref" | cut -d: -f2)
            local new_vol
            new_vol=$(echo "$vol_name" | sed "s/vm-${old_id}-/vm-${new_id}-/")

            # Get ZFS dataset path
            local zvol_path
            zvol_path=$(_vm_pve_cmd "$node_ip" "pvesm path ${disk_ref}" 2>/dev/null)
            if [[ "$zvol_path" == /dev/zvol/* ]]; then
                # ZFS volume: extract dataset name from /dev/zvol/<pool>/<vol>
                local zfs_dataset="${zvol_path#/dev/zvol/}"
                local zfs_new="${zfs_dataset/vm-${old_id}-/vm-${new_id}-}"
                zfs_renames+=("${zfs_dataset}|${zfs_new}")
                config_seds+=("s|${vol_name}|${new_vol}|g")
                freq_debug "ZFS rename: ${zfs_dataset} → ${zfs_new}"
            else
                # Non-ZFS (directory, LVM, etc.) — use qm move-disk approach
                config_seds+=("s|${vol_name}|${new_vol}|g")
                freq_debug "Non-ZFS disk: ${disk_ref} (manual rename may be needed)"
            fi
        done <<< "$disk_lines"
    fi

    # Cloud-init disk
    if [ -n "$ci_disk" ]; then
        local ci_vol ci_new_vol
        ci_vol=$(echo "$ci_disk" | cut -d: -f2)
        ci_new_vol=$(echo "$ci_vol" | sed "s/vm-${old_id}-/vm-${new_id}-/")
        local ci_zvol
        ci_zvol=$(_vm_pve_cmd "$node_ip" "pvesm path ${ci_disk}" 2>/dev/null)
        if [[ "$ci_zvol" == /dev/zvol/* ]]; then
            local ci_ds="${ci_zvol#/dev/zvol/}"
            local ci_new_ds="${ci_ds/vm-${old_id}-/vm-${new_id}-}"
            zfs_renames+=("${ci_ds}|${ci_new_ds}")
        fi
        config_seds+=("s|${ci_vol}|${ci_new_vol}|g")
    fi

    # Show plan
    freq_header "Change VM ID"
    freq_blank
    freq_line "${BOLD}${WHITE}  VM ${old_id} → ${new_id}${RESET}  (${vm_name:-?}) on ${node}"
    freq_blank

    if [ ${#zfs_renames[@]} -gt 0 ]; then
        freq_divider "ZFS Volume Renames"
        local zr
        for zr in "${zfs_renames[@]}"; do
            local zr_old="${zr%%|*}" zr_new="${zr##*|}"
            freq_line "  ${DIM}${zr_old}${RESET}"
            freq_line "    ${_ARROW} ${zr_new}"
        done
    fi

    freq_divider "Config Changes"
    freq_line "  /etc/pve/qemu-server/${old_id}.conf → ${new_id}.conf"
    freq_line "  ${DIM}+ sed: vm-${old_id}-disk → vm-${new_id}-disk${RESET}"
    local fw_exists
    fw_exists=$(_vm_pve_cmd "$node_ip" "test -f /etc/pve/firewall/${old_id}.fw && echo YES" 2>/dev/null)
    [ "$fw_exists" = "YES" ] && freq_line "  /etc/pve/firewall/${old_id}.fw → ${new_id}.fw"

    freq_blank
    freq_footer

    if $dry_run; then
        echo ""
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would rename VM ${old_id} → ${new_id}"
        echo -e "  ${CYAN}[DRY-RUN]${RESET} ${#zfs_renames[@]} ZFS volume(s) to rename"
        echo -e "  ${CYAN}[DRY-RUN]${RESET} No changes made."
        return 0
    fi

    if ! $auto_yes; then
        echo ""
        echo -e "  ${RED}${BOLD}This operation renames ZFS volumes and PVE config.${RESET}"
        echo -e "  ${DIM}Make sure you have a backup (vzdump) before proceeding.${RESET}"
        if ! ask_rsq "Change VM ID ${old_id} → ${new_id}?"; then
            echo -e "  ${YELLOW}Aborted.${RESET}"
            return 1
        fi
    fi

    # Execute the change-id
    local errors=0

    # Phase 1: Rename ZFS volumes
    if [ ${#zfs_renames[@]} -gt 0 ]; then
        local zr
        for zr in "${zfs_renames[@]}"; do
            local zr_old="${zr%%|*}" zr_new="${zr##*|}"
            _step_start "ZFS rename: $(basename "$zr_old") → $(basename "$zr_new")..."
            local zfs_out
            zfs_out=$(_vm_pve_cmd "$node_ip" "zfs rename ${zr_old} ${zr_new}" 2>&1)
            if [ $? -eq 0 ]; then
                _step_ok "Renamed"
            else
                _step_fail "ZFS rename failed: ${zfs_out}"
                errors=$((errors + 1))
            fi
        done
    fi

    # Bail if ZFS renames failed
    if [ "$errors" -gt 0 ]; then
        echo -e "  ${RED}${_CROSS}${RESET}  ZFS rename failed. Config not modified. Manual cleanup may be needed."
        log "vm change-id FAILED: ${old_id} → ${new_id} -- ZFS rename errors"
        return 1
    fi

    # Phase 2: Update config file (single SSH call)
    _step_start "Updating PVE config..."
    local sed_expr=""
    local s
    for s in "${config_seds[@]}"; do
        sed_expr="${sed_expr} -e '${s}'"
    done

    local config_script="
set -e
# Read old config
cfg=\$(cat /etc/pve/qemu-server/${old_id}.conf)
# Apply disk name substitutions
echo \"\$cfg\" | sed ${sed_expr} > /etc/pve/qemu-server/${new_id}.conf
# Remove old config
rm -f /etc/pve/qemu-server/${old_id}.conf
"
    # Firewall
    if [ "$fw_exists" = "YES" ]; then
        config_script="${config_script}
mv /etc/pve/firewall/${old_id}.fw /etc/pve/firewall/${new_id}.fw
"
    fi

    # HA check
    config_script="${config_script}
if grep -q 'vm:${old_id}' /etc/pve/ha/resources.cfg 2>/dev/null; then
    sed -i 's/vm:${old_id}/vm:${new_id}/g' /etc/pve/ha/resources.cfg
    echo HA_UPDATED
fi
"

    local config_out
    config_out=$(_vm_pve_cmd "$node_ip" "bash -c '${config_script}'" 2>&1)
    if [ $? -eq 0 ]; then
        _step_ok "Config updated"
        [[ "$config_out" == *"HA_UPDATED"* ]] && echo -e "      ${DIM}HA resources.cfg updated${RESET}"
    else
        _step_fail "Config update failed"
        echo -e "    ${DIM}${config_out}${RESET}" | head -3
        log "vm change-id PARTIAL FAIL: ZFS renamed but config failed. VM ${old_id} → ${new_id}"
        echo -e "  ${RED}${_CROSS}${RESET}  ZFS volumes renamed but config update failed."
        echo -e "  ${DIM}Manual fix: update /etc/pve/qemu-server/ config on ${node}${RESET}"
        return 1
    fi

    # Phase 3: Verify
    _step_start "Verifying VM ${new_id}..."
    local verify_out
    verify_out=$(_vm_pve_cmd "$node_ip" "qm status ${new_id}" 2>/dev/null)
    if [ -n "$verify_out" ]; then
        _step_ok "VM ${new_id} exists: $(echo "$verify_out" | awk '{print $2}')"
    else
        _step_warn "Cannot verify VM ${new_id} — check manually"
    fi

    # Phase 4: Update hosts.conf if old VMID was registered
    if [ -f "$HOSTS_FILE" ]; then
        local old_entry
        old_entry=$(grep -v '^#' "$HOSTS_FILE" | grep -i "vm${old_id}" | head -1)
        if [ -n "$old_entry" ]; then
            _step_start "Updating hosts.conf..."
            local old_label new_label
            old_label=$(echo "$old_entry" | awk '{print $2}')
            new_label=$(echo "$old_label" | sed "s/vm${old_id}/vm${new_id}/")
            if [ "$old_label" != "$new_label" ]; then
                sed -i "s/${old_label}/${new_label}/" "$HOSTS_FILE"
                _step_ok "hosts.conf: ${old_label} → ${new_label}"
                log "vm change-id: hosts.conf updated ${old_label} → ${new_label}"
            else
                _step_ok "hosts.conf: no label change needed"
            fi
        fi
    fi

    # Success
    echo ""
    echo -e "  ${GREEN}${_TICK}${RESET}  ${BOLD}VM ${old_id} → ${new_id}${RESET} (${vm_name:-?}) on ${node}"
    echo -e "  ${DIM}${#zfs_renames[@]} ZFS volume(s) renamed. Config migrated.${RESET}"
    [ "$fw_exists" = "YES" ] && echo -e "  ${DIM}Firewall config migrated.${RESET}"
    echo ""
    echo -e "  ${DIM}Next steps:${RESET}"
    echo -e "  ${DIM}  freq vm start ${new_id}       -- start the renamed VM${RESET}"
    echo -e "  ${DIM}  freq vm nic ${new_id} --ip ... -- change IP if needed${RESET}"
    echo ""

    log "vm change-id: VM ${old_id} → ${new_id} (${vm_name}) on ${node} -- ${#zfs_renames[@]} ZFS vols"
    _protected_log "COMPLETED" "${FREQ_USER:-$(id -un)}" "change-id: ${old_id} → ${new_id}" "$node_ip" "success" 2>/dev/null
    freq_celebrate 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# NIC — Reconfigure VM network interface
# ═══════════════════════════════════════════════════════════════════

_vm_nic() {
    require_operator || return 1
    require_ssh_key

    local vmid="" bridge="" vlan="" ip="" gw="" iface="net0"
    local dry_run="${DRY_RUN:-false}"

    while [ $# -gt 0 ]; do
        case "$1" in
            --bridge)  bridge="$2"; shift 2 ;;
            --vlan)    vlan="$2"; shift 2 ;;
            --ip)      ip="$2"; shift 2 ;;
            --gateway) gw="$2"; shift 2 ;;
            --iface)   iface="$2"; shift 2 ;;
            --dry-run) dry_run=true; shift ;;
            --help|-h)
                echo "Usage: freq vm nic <vmid> [--bridge BR] [--vlan TAG] [--ip ADDR/CIDR] [--gateway IP]"
                echo ""
                echo "  --bridge NAME   Set bridge (default: keep current)"
                echo "  --vlan TAG      Set VLAN tag"
                echo "  --ip ADDR/CIDR  Set cloud-init IP (e.g., 10.25.255.50/24)"
                echo "  --gateway IP    Set default gateway"
                echo "  --iface NAME    NIC to modify (default: net0)"
                echo "  --dry-run       Show what would be done"
                return 0 ;;
            -*)  die "Unknown flag: $1. Use --help for usage." ;;
            *)   [ -z "$vmid" ] && { vmid="$1"; shift; continue; }
                 die "Too many arguments. Use --help for usage." ;;
        esac
    done

    [ -z "$vmid" ] && die "Usage: freq vm nic <vmid> [--bridge BR] [--vlan TAG] [--ip ADDR/CIDR]"
    [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: ${vmid}"
    [ -z "$bridge" ] && [ -z "$vlan" ] && [ -z "$ip" ] && \
        die "Specify at least one: --bridge, --vlan, or --ip"

    if ! _vm_find "$vmid"; then
        die "VM ${vmid} not found on any PVE node."
    fi
    local node="$_found_node" node_ip="$_found_node_ip"

    local vm_config
    vm_config=$(_vm_config "$node_ip" "$vmid")
    local vm_name
    vm_name=$(_vm_field "$vm_config" "name")
    local cur_net
    cur_net=$(_vm_field "$vm_config" "$iface")

    freq_header "NIC Reconfig > ${vm_name:-VM ${vmid}}"
    freq_blank
    freq_line "$(printf "  %-12s %s" "Current:" "${cur_net:-none}")"
    [ -n "$bridge" ] && freq_line "$(printf "  %-12s %s" "Bridge:" "${bridge}")"
    [ -n "$vlan" ] && freq_line "$(printf "  %-12s %s" "VLAN:" "${vlan}")"
    [ -n "$ip" ] && freq_line "$(printf "  %-12s %s" "IP:" "${ip}")"
    [ -n "$gw" ] && freq_line "$(printf "  %-12s %s" "Gateway:" "${gw}")"
    freq_blank
    freq_footer

    if $dry_run; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would reconfigure ${iface} on VM ${vmid}. No changes made."
        return 0
    fi

    local changes=0

    # Update NIC hardware config (bridge/vlan)
    if [ -n "$bridge" ] || [ -n "$vlan" ]; then
        _step_start "Updating ${iface}..."
        # Build new net config: keep model (virtio), update bridge/tag
        local model="virtio"
        local mac
        mac=$(echo "$cur_net" | grep -oP '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}')
        local new_net="${model}"
        [ -n "$mac" ] && new_net="${new_net}=${mac}"
        new_net="${new_net},bridge=${bridge:-vmbr0}"
        [ -n "$vlan" ] && new_net="${new_net},tag=${vlan}"

        if _vm_pve_cmd "$node_ip" "qm set ${vmid} --${iface} ${new_net}" &>/dev/null; then
            _step_ok "${iface} updated"
            changes=$((changes + 1))
        else
            _step_fail "${iface} update failed"
        fi
    fi

    # Update cloud-init IP
    if [ -n "$ip" ]; then
        _step_start "Setting IP to ${ip}..."
        local ci_conf="ip=${ip}"
        [ -n "$gw" ] && ci_conf="${ci_conf},gw=${gw}"
        if _vm_pve_cmd "$node_ip" "qm set ${vmid} --ipconfig0 ${ci_conf}" &>/dev/null; then
            _step_ok "IP configured"
            changes=$((changes + 1))
        else
            _step_fail "IP config failed"
        fi
    fi

    # Update hosts.conf IP if changed
    if [ -n "$ip" ] && [ -f "$HOSTS_FILE" ]; then
        local entry
        entry=$(grep -v '^#' "$HOSTS_FILE" | grep -i "vm${vmid}" | head -1)
        if [ -n "$entry" ]; then
            local old_ip new_ip_bare
            old_ip=$(echo "$entry" | awk '{print $1}')
            new_ip_bare="${ip%%/*}"  # Strip CIDR mask
            if [ "$old_ip" != "$new_ip_bare" ]; then
                _step_start "Updating hosts.conf IP..."
                sed -i "s/^${old_ip}/${new_ip_bare}/" "$HOSTS_FILE"
                _step_ok "hosts.conf: ${old_ip} → ${new_ip_bare}"
            fi
        fi
    fi

    echo ""
    echo -e "  ${GREEN}${_TICK}${RESET}  ${changes} NIC change(s) applied to VM ${vmid}"
    echo ""
    log "vm nic: VM ${vmid} (${vm_name}) -- bridge=${bridge:-unchanged} vlan=${vlan:-unchanged} ip=${ip:-unchanged}"
}

# ═══════════════════════════════════════════════════════════════════
# STOP / START — Quick VM power control
# ═══════════════════════════════════════════════════════════════════

_vm_stop() {
    require_operator || return 1
    require_ssh_key
    local vmid="${1:-}"
    [ -z "$vmid" ] && die "Usage: freq vm stop <vmid>"
    [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: ${vmid}"

    if ! _vm_find "$vmid"; then
        die "VM ${vmid} not found on any PVE node."
    fi

    _step_start "Stopping VM ${vmid}..."
    if _vm_pve_cmd "$_found_node_ip" "qm stop ${vmid}" &>/dev/null; then
        _step_ok "VM ${vmid} stopped"
        log "vm stop: VM ${vmid} on ${_found_node}"
    else
        _step_fail "Stop failed"
        return 1
    fi
}

_vm_start() {
    require_operator || return 1
    require_ssh_key
    local vmid="${1:-}"
    [ -z "$vmid" ] && die "Usage: freq vm start <vmid>"
    [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: ${vmid}"

    if ! _vm_find "$vmid"; then
        die "VM ${vmid} not found on any PVE node."
    fi

    _step_start "Starting VM ${vmid}..."
    if _vm_pve_cmd "$_found_node_ip" "qm start ${vmid}" &>/dev/null; then
        _step_ok "VM ${vmid} started"
        log "vm start: VM ${vmid} on ${_found_node}"
    else
        _step_fail "Start failed"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT — freq vm <subcommand>
# ═══════════════════════════════════════════════════════════════════

cmd_vm() {
    local subcmd="${1:-}"
    [ -z "$subcmd" ] && subcmd="--help"
    shift 2>/dev/null || true

    case "$subcmd" in
        list|ls)       _vm_list "$@" ;;
        status)        _vm_status "$@" ;;
        create)        _vm_create "$@" ;;
        clone)         _vm_clone "$@" ;;
        resize)        _vm_resize "$@" ;;
        destroy|rm)    _vm_destroy "$@" ;;
        snapshot|snap) _vm_snapshot "$@" ;;
        change-id)     _vm_change_id "$@" ;;
        nic)           _vm_nic "$@" ;;
        stop)          _vm_stop "$@" ;;
        start)         _vm_start "$@" ;;
        --help|-h|help)
            echo "Usage: freq vm <subcommand> [options]"
            echo ""
            echo "Subcommands:"
            echo "  list            Cluster-wide VM inventory"
            echo "  status <vmid>   Detailed VM health check"
            echo "  create          Create a new VM from cloud image"
            echo "  clone           Clone an existing VM"
            echo "  resize          Resize VM resources (CPU/RAM/disk)"
            echo "  destroy         Permanently destroy a VM"
            echo "  snapshot        Create, list, or delete snapshots"
            echo "  change-id       Change a VM's ID (VMID rename)"
            echo "  nic             Reconfigure VM network interface"
            echo "  stop            Stop a VM"
            echo "  start           Start a VM"
            echo ""
            echo "Examples:"
            echo "  freq vm list"
            echo "  freq vm create --name myvm --distro debian-13"
            echo "  freq vm change-id 999 900"
            echo "  freq vm nic 900 --ip 10.25.255.50/24 --vlan 2550"
            ;;
        *)  die "Unknown subcommand: ${subcmd}. Use 'freq vm --help' for usage." ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY — top-level command aliases
# These support the existing dispatcher routes:
#   create)  cmd_create ...
#   clone)   cmd_clone ...
#   etc.
# ═══════════════════════════════════════════════════════════════════

cmd_create()    { _vm_create "$@"; }
cmd_clone()     { _vm_clone "$@"; }
cmd_resize()    { _vm_resize "$@"; }
cmd_destroy()   { _vm_destroy "$@"; }
cmd_list()      { _vm_list "$@"; }
cmd_snapshot()  { _vm_snapshot "$@"; }
cmd_vm_status() { _vm_status "$@"; }
