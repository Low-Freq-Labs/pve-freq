#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/serial.sh
# Serial Console & Rescue Boot — attach to VM consoles, ISO rescue
#
# -- when all else fails, get a console --
# Commands: cmd_serial, cmd_rescue
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

cmd_serial() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        attach)   _serial_attach "$@" ;;
        devices)  _serial_devices "$@" ;;
        help|--help|-h) _serial_help ;;
        *)
            echo -e "  ${RED}Unknown serial command: ${subcmd}${RESET}"
            echo "  Run 'freq serial help' for usage."
            return 1
            ;;
    esac
}

cmd_rescue() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        boot)   _rescue_boot "$@" ;;
        detach) _rescue_detach "$@" ;;
        help|--help|-h) _rescue_help ;;
        *)
            echo -e "  ${RED}Unknown rescue command: ${subcmd}${RESET}"
            echo "  Run 'freq rescue help' for usage."
            return 1
            ;;
    esac
}

_serial_help() {
    freq_header "Serial Console"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq serial <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    attach <vmid> <node>  ${DIM}${_DASH} Open serial console to VM${RESET}"
    freq_line "    devices <node>        ${DIM}${_DASH} List serial devices on node${RESET}"
    freq_blank
    freq_footer
}

_rescue_help() {
    freq_header "Rescue Boot"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq rescue <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    boot <vmid> <node> <iso>  ${DIM}${_DASH} Attach ISO and reboot into rescue${RESET}"
    freq_line "    detach <vmid> <node>      ${DIM}${_DASH} Remove rescue ISO and reboot${RESET}"
    freq_blank
    freq_footer
}

_serial_attach() {
    require_operator || return 1
    require_ssh_key

    local vmid="${1:-}" node="${2:-}"
    [ -z "$vmid" ] || [ -z "$node" ] && {
        echo -e "  ${RED}Usage: freq serial attach <vmid> <node>${RESET}"
        return 1
    }

    freq_header "Serial Console ${_DASH} VM ${vmid} on ${node}"
    freq_blank

    # Verify VM exists and has serial configured
    local has_serial
    has_serial=$(freq_ssh "$node" "grep -c 'serial0' /etc/pve/qemu-server/${vmid}.conf 2>/dev/null" 2>/dev/null)

    if [ "${has_serial:-0}" = "0" ]; then
        freq_line "  ${YELLOW}${_WARN}${RESET} VM ${vmid} has no serial device configured."
        freq_line "  ${DIM}Add with: qm set ${vmid} --serial0 socket${RESET}"
        freq_footer
        return 1
    fi

    freq_line "  Connecting to serial console on VM ${vmid}..."
    freq_line "  ${DIM}Press Ctrl+O to detach from the console.${RESET}"
    freq_blank
    freq_footer

    # Open the serial terminal via SSH
    local node_ip
    node_ip=$(freq_resolve_ip "$node") || die "Cannot resolve: ${node}"
    ssh -t $SSH_OPTS "${REMOTE_USER}@${node_ip}" "sudo qm terminal ${vmid} -iface serial0"
    log "serial: attached to vmid=${vmid} on ${node}"
}

_serial_devices() {
    require_operator || return 1
    require_ssh_key

    local node="${1:-}"
    [ -z "$node" ] && {
        echo -e "  ${RED}Usage: freq serial devices <node>${RESET}"
        return 1
    }

    freq_header "Serial Devices ${_DASH} ${node}"
    freq_blank

    # List hardware serial devices
    _step_start "Hardware serial ports"
    local hw_serial
    hw_serial=$(freq_ssh "$node" "ls -la /dev/ttyS* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null" 2>/dev/null)
    if [ -n "$hw_serial" ]; then
        _step_ok
        while IFS= read -r line; do
            freq_line "    ${DIM}${line}${RESET}"
        done <<< "$hw_serial"
    else
        _step_warn "none found"
    fi

    # List VMs with serial devices
    _step_start "VMs with serial console"
    local vm_serial
    vm_serial=$(freq_ssh "$node" '
        for conf in /etc/pve/qemu-server/*.conf; do
            [ -f "$conf" ] || continue
            if grep -q "serial0" "$conf" 2>/dev/null; then
                vmid=$(basename "$conf" .conf)
                name=$(grep "^name:" "$conf" | awk "{print \$2}")
                serial_type=$(grep "^serial0:" "$conf" | awk "{print \$2}")
                echo "${vmid}|${name:-unnamed}|${serial_type}"
            fi
        done
    ' 2>/dev/null)

    if [ -n "$vm_serial" ]; then
        _step_ok
        while IFS='|' read -r vmid name stype; do
            [ -z "$vmid" ] && continue
            freq_line "    VM ${vmid} (${name}): ${DIM}${stype}${RESET}"
        done <<< "$vm_serial"
    else
        _step_warn "no VMs with serial"
    fi

    freq_blank
    freq_footer
}

_rescue_boot() {
    require_admin || return 1
    require_ssh_key

    local vmid="${1:-}" node="${2:-}" iso="${3:-}"
    [ -z "$vmid" ] || [ -z "$node" ] || [ -z "$iso" ] && {
        echo -e "  ${RED}Usage: freq rescue boot <vmid> <node> <iso-file>${RESET}"
        echo -e "  ${DIM}ISO should be available in PVE storage (e.g., local:iso/rescue.iso)${RESET}"
        return 1
    }

    freq_header "Rescue Boot ${_DASH} VM ${vmid}"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would attach ${iso} and reboot VM ${vmid}"
        freq_footer
        return 0
    fi

    _freq_confirm "Reboot VM ${vmid} into rescue ISO?" || return 1

    # Attach ISO to CD-ROM drive
    _step_start "Attach ISO: ${iso}"
    if freq_ssh "$node" "sudo qm set ${vmid} --cdrom ${iso}" 2>/dev/null; then
        _step_ok
    else
        _step_fail "failed to attach ISO"
        freq_footer
        return 1
    fi

    # Set boot order to CD first
    _step_start "Set boot order (CD first)"
    freq_ssh "$node" "sudo qm set ${vmid} --boot order='ide2;scsi0'" 2>/dev/null
    _step_ok

    # Reboot VM
    _step_start "Reboot VM ${vmid}"
    if freq_ssh "$node" "sudo qm reboot ${vmid}" 2>/dev/null; then
        _step_ok
    else
        # Try stop+start if reboot doesn't work
        freq_ssh "$node" "sudo qm stop ${vmid}" 2>/dev/null
        sleep 3
        freq_ssh "$node" "sudo qm start ${vmid}" 2>/dev/null
        _step_ok "stop+start"
    fi

    freq_blank
    freq_line "  ${GREEN}${_TICK}${RESET} VM ${vmid} booting from rescue ISO"
    freq_line "  ${DIM}Use 'freq serial attach ${vmid} ${node}' for console access${RESET}"
    freq_footer
    log "serial: rescue boot vmid=${vmid} iso=${iso}"
}

_rescue_detach() {
    require_admin || return 1
    require_ssh_key

    local vmid="${1:-}" node="${2:-}"
    [ -z "$vmid" ] || [ -z "$node" ] && {
        echo -e "  ${RED}Usage: freq rescue detach <vmid> <node>${RESET}"
        return 1
    }

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would remove rescue ISO from VM ${vmid}"
        return 0
    fi

    _step_start "Remove CD-ROM"
    freq_ssh "$node" "sudo qm set ${vmid} --delete cdrom" 2>/dev/null
    _step_ok

    _step_start "Restore boot order"
    freq_ssh "$node" "sudo qm set ${vmid} --boot order=scsi0" 2>/dev/null
    _step_ok

    _step_start "Reboot VM"
    freq_ssh "$node" "sudo qm reboot ${vmid}" 2>/dev/null
    _step_ok

    echo -e "  ${GREEN}${_TICK}${RESET} Rescue ISO detached. VM ${vmid} rebooting normally."
    log "serial: rescue detach vmid=${vmid}"
}
