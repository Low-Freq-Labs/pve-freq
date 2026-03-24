#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/provision.sh
# VM Provisioning Pipeline — clone, configure, deploy
#
# -- from zero to production in one command --
# Commands: cmd_provision
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

PROVISION_LOG="${FREQ_DATA_DIR}/log/provision.log"

cmd_provision() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        auto)      _provision_auto "$@" ;;
        plan)      _provision_plan "$@" ;;
        rollback)  _provision_rollback "$@" ;;
        help|--help|-h) _provision_help ;;
        *)
            echo -e "  ${RED}Unknown provision command: ${subcmd}${RESET}"
            echo "  Run 'freq provision help' for usage."
            return 1
            ;;
    esac
}

_provision_help() {
    freq_header "VM Provisioning"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq provision <command> [options]"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    auto <vmid> <template> <node> ${DIM}${_DASH} Full auto-provision pipeline${RESET}"
    freq_line "    plan <vmid> <template> <node> ${DIM}${_DASH} Show what auto would do${RESET}"
    freq_line "    rollback <vmid> <node>        ${DIM}${_DASH} Destroy a failed provision${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Options:${RESET}"
    freq_line "    --name <name>     ${DIM}${_DASH} VM hostname${RESET}"
    freq_line "    --cores <n>       ${DIM}${_DASH} CPU cores (default: 2)${RESET}"
    freq_line "    --memory <mb>     ${DIM}${_DASH} RAM in MB (default: 2048)${RESET}"
    freq_line "    --disk <gb>       ${DIM}${_DASH} Disk size in GB (default: 32)${RESET}"
    freq_line "    --ip <ip/cidr>    ${DIM}${_DASH} Static IP (default: DHCP)${RESET}"
    freq_line "    --gateway <gw>    ${DIM}${_DASH} Gateway IP${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Pipeline:${RESET} clone ${_ARROW} cloud-init ${_ARROW} start ${_ARROW} wait SSH"
    freq_line "              ${_ARROW} bootstrap ${_ARROW} register ${_ARROW} harden ${_ARROW} verify"
    freq_blank
    freq_footer
}

_provision_parse_opts() {
    PROV_NAME=""; PROV_CORES=2; PROV_MEMORY=2048; PROV_DISK=32
    PROV_IP="dhcp"; PROV_GATEWAY=""
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --name)    PROV_NAME="$2"; shift 2 ;;
            --cores)   PROV_CORES="$2"; shift 2 ;;
            --memory)  PROV_MEMORY="$2"; shift 2 ;;
            --disk)    PROV_DISK="$2"; shift 2 ;;
            --ip)      PROV_IP="$2"; shift 2 ;;
            --gateway) PROV_GATEWAY="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
}

_provision_auto() {
    require_admin || return 1
    require_ssh_key

    local vmid="${1:-}" template="${2:-}" node="${3:-}"
    shift 3 2>/dev/null || true
    _provision_parse_opts "$@"

    [ -z "$vmid" ] || [ -z "$template" ] || [ -z "$node" ] && {
        echo -e "  ${RED}Usage: freq provision auto <vmid> <template> <node> [options]${RESET}"
        return 1
    }

    # Protect reserved ranges
    if [[ "$vmid" =~ ^[89][0-9]{2}$ ]]; then
        die "VMID ${vmid} is in a protected range (800-999). Choose a different ID."
    fi

    [ -z "$PROV_NAME" ] && PROV_NAME="vm${vmid}"
    local node_ip
    node_ip=$(freq_resolve_ip "$node") || die "Cannot resolve PVE node: ${node}"

    freq_header "Provisioning ${_DASH} VM ${vmid} on ${node}"
    freq_blank
    freq_line "  Template: ${template}  Node: ${node}  Name: ${PROV_NAME}"
    freq_line "  Specs: ${PROV_CORES}c / ${PROV_MEMORY}MB / ${PROV_DISK}GB  IP: ${PROV_IP}"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_divider "Pipeline (dry-run)"
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would execute 8-step provision pipeline"
        freq_footer
        return 0
    fi

    _freq_confirm "Provision VM ${vmid} (${PROV_NAME}) on ${node}?" || { echo "  Cancelled."; return 1; }

    freq_divider "Pipeline"

    # Step 1: Clone template
    _step_start "Clone template ${template} -> ${vmid}"
    if freq_ssh "$node" "sudo qm clone ${template} ${vmid} --name ${PROV_NAME} --full 1" 2>/dev/null; then
        _step_ok "cloned"
    else
        _step_fail "clone failed"; log "provision: clone failed vmid=${vmid}"; return 1
    fi

    # Step 2: Cloud-init configuration
    _step_start "Configure cloud-init"
    local ci_cmd="sudo qm set ${vmid} --cores ${PROV_CORES} --memory ${PROV_MEMORY}"
    if [ "$PROV_IP" != "dhcp" ]; then
        ci_cmd+=" --ipconfig0 ip=${PROV_IP},gw=${PROV_GATEWAY}"
    fi
    local pubkey
    pubkey=$(get_ssh_pubkey 2>/dev/null)
    if [ -n "$pubkey" ]; then
        ci_cmd+=" --sshkeys /tmp/freq-pubkey-${vmid}.pub"
        freq_ssh "$node" "echo '${pubkey}' | sudo tee /tmp/freq-pubkey-${vmid}.pub >/dev/null" 2>/dev/null
    fi
    if freq_ssh "$node" "$ci_cmd" 2>/dev/null; then
        _step_ok "configured"
    else
        _step_warn "partial config"
    fi

    # Step 3: Resize disk
    _step_start "Resize disk to ${PROV_DISK}GB"
    if freq_ssh "$node" "sudo qm resize ${vmid} scsi0 ${PROV_DISK}G" 2>/dev/null; then
        _step_ok "resized"
    else
        _step_warn "resize skipped"
    fi

    # Step 4: Start VM
    _step_start "Start VM ${vmid}"
    if freq_ssh "$node" "sudo qm start ${vmid}" 2>/dev/null; then
        _step_ok "started"
    else
        _step_fail "start failed"; return 1
    fi

    # Step 5: Wait for SSH
    _step_start "Waiting for SSH (up to 120s)"
    local vm_ip="${PROV_IP%%/*}"
    [ "$vm_ip" = "dhcp" ] && { _step_warn "DHCP — manual SSH check needed"; vm_ip=""; }
    if [ -n "$vm_ip" ]; then
        local waited=0
        while [ $waited -lt 120 ]; do
            if freq_ssh "$vm_ip" "echo ready" &>/dev/null; then
                _step_ok "SSH up after ${waited}s"
                break
            fi
            sleep 5
            waited=$((waited + 5))
        done
        [ $waited -ge 120 ] && _step_warn "SSH timeout — may still be booting"
    fi

    # Step 6: Bootstrap (FREQ service account)
    if [ -n "$vm_ip" ]; then
        _step_start "Bootstrap service account"
        if freq_ssh "$vm_ip" "id ${FREQ_SERVICE_ACCOUNT}" &>/dev/null; then
            _step_ok "account exists"
        else
            _step_warn "manual bootstrap needed"
        fi
    fi

    # Step 7: Register in hosts.conf
    _step_start "Register in hosts.conf"
    if [ -n "$vm_ip" ] && [ -f "$HOSTS_FILE" ]; then
        if ! grep -q "$vm_ip" "$HOSTS_FILE" 2>/dev/null; then
            echo "${vm_ip}  ${PROV_NAME}  linux  provision" >> "$HOSTS_FILE"
            _step_ok "registered"
        else
            _step_ok "already registered"
        fi
    else
        _step_warn "skipped — no IP or hosts.conf"
    fi

    # Step 8: Verify
    _step_start "Verify VM status"
    local vm_status
    vm_status=$(freq_ssh "$node" "sudo qm status ${vmid}" 2>/dev/null)
    if echo "$vm_status" | grep -q "running"; then
        _step_ok "running"
    else
        _step_warn "${vm_status:-unknown}"
    fi

    freq_blank
    freq_line "  ${GREEN}${_TICK}${RESET} VM ${vmid} (${PROV_NAME}) provisioned on ${node}"
    freq_footer
    log "provision: auto completed vmid=${vmid} node=${node} name=${PROV_NAME}"
}

_provision_plan() {
    local vmid="${1:-}" template="${2:-}" node="${3:-}"
    shift 3 2>/dev/null || true
    _provision_parse_opts "$@"

    [ -z "$vmid" ] || [ -z "$template" ] || [ -z "$node" ] && {
        echo -e "  ${RED}Usage: freq provision plan <vmid> <template> <node> [options]${RESET}"
        return 1
    }

    [ -z "$PROV_NAME" ] && PROV_NAME="vm${vmid}"

    freq_header "Provision Plan ${_DASH} VM ${vmid}"
    freq_blank
    freq_line "  ${BOLD}Step 1:${RESET} qm clone ${template} ${vmid} --name ${PROV_NAME} --full 1"
    freq_line "  ${BOLD}Step 2:${RESET} qm set ${vmid} --cores ${PROV_CORES} --memory ${PROV_MEMORY}"
    freq_line "  ${BOLD}Step 3:${RESET} qm resize ${vmid} scsi0 ${PROV_DISK}G"
    freq_line "  ${BOLD}Step 4:${RESET} qm start ${vmid}"
    freq_line "  ${BOLD}Step 5:${RESET} Wait for SSH on ${PROV_IP}"
    freq_line "  ${BOLD}Step 6:${RESET} Bootstrap ${FREQ_SERVICE_ACCOUNT} account"
    freq_line "  ${BOLD}Step 7:${RESET} Register in hosts.conf"
    freq_line "  ${BOLD}Step 8:${RESET} Verify VM running"
    freq_blank
    freq_footer
}

_provision_rollback() {
    require_admin || return 1
    require_ssh_key

    local vmid="${1:-}" node="${2:-}"
    [ -z "$vmid" ] || [ -z "$node" ] && {
        echo -e "  ${RED}Usage: freq provision rollback <vmid> <node>${RESET}"
        return 1
    }

    freq_header "Provision Rollback ${_DASH} VM ${vmid}"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would stop and destroy VM ${vmid} on ${node}"
        freq_footer
        return 0
    fi

    _freq_confirm "DESTROY VM ${vmid} on ${node}? This is irreversible." --danger || return 1

    _step_start "Stop VM ${vmid}"
    freq_ssh "$node" "sudo qm stop ${vmid} --skiplock 1" 2>/dev/null
    _step_ok "stopped (or already stopped)"

    _step_start "Destroy VM ${vmid}"
    if freq_ssh "$node" "sudo qm destroy ${vmid} --purge 1 --skiplock 1" 2>/dev/null; then
        _step_ok "destroyed"
    else
        _step_fail "destroy failed"
    fi

    # Remove from hosts.conf if present
    if [ -f "$HOSTS_FILE" ] && grep -q "vm${vmid}" "$HOSTS_FILE" 2>/dev/null; then
        sed -i "/vm${vmid}/d" "$HOSTS_FILE"
        _step_ok "removed from hosts.conf"
    fi

    freq_blank
    freq_footer
    log "provision: rollback vmid=${vmid} node=${node}"
}
