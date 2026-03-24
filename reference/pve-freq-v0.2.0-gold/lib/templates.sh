#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/templates.sh
# PVE Template Management — scan, create, configure VM templates
#
# -- the blueprint factory --
# Commands: cmd_templates
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

cmd_templates() {
    local subcmd="${1:-list}"
    shift 2>/dev/null || true

    case "$subcmd" in
        list)    _templates_list "$@" ;;
        create)  _templates_create "$@" ;;
        setup)   _templates_setup "$@" ;;
        help|--help|-h) _templates_help ;;
        *)
            echo -e "  ${RED}Unknown templates command: ${subcmd}${RESET}"
            echo "  Run 'freq templates help' for usage."
            return 1
            ;;
    esac
}

_templates_help() {
    freq_header "Template Management"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq templates <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    list [node]              ${DIM}${_DASH} List templates across PVE nodes${RESET}"
    freq_line "    create <vmid> <node>     ${DIM}${_DASH} Convert VM to template${RESET}"
    freq_line "    setup <vmid> <node> <image> ${DIM}${_DASH} Create template from cloud image${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Template Naming:${RESET}"
    freq_line "    VMIDs 9000-9999 are reserved for templates by convention."
    freq_blank
    freq_footer
}

_templates_list() {
    require_operator || return 1
    require_ssh_key

    local target_node="${1:-}"

    freq_header "VM Templates"
    freq_blank

    local total=0
    local n
    for ((n=0; n<${#PVE_NODES[@]}; n++)); do
        local nname="${PVE_NODE_NAMES[$n]}"
        [ -n "$target_node" ] && [ "$target_node" != "$nname" ] && continue

        freq_line "  ${BOLD}${WHITE}${nname}${RESET}"

        local tmpl_data
        tmpl_data=$(freq_ssh "$nname" '
            for conf in /etc/pve/qemu-server/*.conf; do
                [ -f "$conf" ] || continue
                if grep -q "^template: 1" "$conf" 2>/dev/null; then
                    vmid=$(basename "$conf" .conf)
                    name=$(grep "^name:" "$conf" | awk "{print \$2}")
                    mem=$(grep "^memory:" "$conf" | awk "{print \$2}")
                    cores=$(grep "^cores:" "$conf" | awk "{print \$2}")
                    echo "${vmid}|${name:-unnamed}|${cores:-?}c|${mem:-?}MB"
                fi
            done
        ' 2>/dev/null)

        if [ -z "$tmpl_data" ]; then
            freq_line "    ${DIM}No templates found (or node unreachable)${RESET}"
        else
            while IFS='|' read -r vmid name cores mem; do
                [ -z "$vmid" ] && continue
                freq_line "    ${PURPLELIGHT}${vmid}${RESET}  ${BOLD}${name}${RESET}  ${DIM}${cores} / ${mem}${RESET}"
                total=$((total + 1))
            done <<< "$tmpl_data"
        fi
        freq_blank
    done

    freq_line "  ${DIM}Total templates: ${total}${RESET}"
    freq_footer
    log "templates: list viewed (${total} templates)"
}

_templates_create() {
    require_admin || return 1
    require_ssh_key

    local vmid="${1:-}" node="${2:-}"
    [ -z "$vmid" ] || [ -z "$node" ] && {
        echo -e "  ${RED}Usage: freq templates create <vmid> <node>${RESET}"
        return 1
    }

    freq_header "Convert to Template ${_DASH} VM ${vmid}"
    freq_blank

    # Verify VM exists and is stopped
    local vm_status
    vm_status=$(freq_ssh "$node" "sudo qm status ${vmid}" 2>/dev/null)
    if [ -z "$vm_status" ]; then
        freq_line "  ${RED}${_CROSS}${RESET} VM ${vmid} not found on ${node}"
        freq_footer
        return 1
    fi

    if echo "$vm_status" | grep -q "running"; then
        freq_line "  ${RED}${_CROSS}${RESET} VM ${vmid} is running. Stop it first."
        freq_footer
        return 1
    fi

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would convert VM ${vmid} to template on ${node}"
        freq_footer
        return 0
    fi

    _freq_confirm "Convert VM ${vmid} to template? This is irreversible." --danger || return 1

    _step_start "Converting VM ${vmid} to template"
    if freq_ssh "$node" "sudo qm template ${vmid}" 2>/dev/null; then
        _step_ok "converted"
    else
        _step_fail "conversion failed"
        freq_footer
        return 1
    fi

    freq_blank
    freq_line "  ${GREEN}${_TICK}${RESET} VM ${vmid} is now a template on ${node}"
    freq_footer
    log "templates: created template from vmid=${vmid} on ${node}"
}

_templates_setup() {
    require_admin || return 1
    require_ssh_key

    local vmid="${1:-}" node="${2:-}" image="${3:-}"
    [ -z "$vmid" ] || [ -z "$node" ] || [ -z "$image" ] && {
        echo -e "  ${RED}Usage: freq templates setup <vmid> <node> <image-file>${RESET}"
        return 1
    }

    local image_path="${FREQ_DATA_DIR}/images/${image}"
    [ ! -f "$image_path" ] && {
        echo -e "  ${RED}Image not found: ${image_path}${RESET}"
        echo -e "  ${DIM}Download an image first with 'freq images download <distro>'.${RESET}"
        return 1
    }

    local name="tmpl-${vmid}"

    freq_header "Template Setup ${_DASH} ${vmid}"
    freq_blank
    freq_line "  Image: ${image}  Node: ${node}  VMID: ${vmid}"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would create template ${vmid} from ${image} on ${node}"
        freq_footer
        return 0
    fi

    _freq_confirm "Create template ${vmid} from ${image} on ${node}?" || return 1

    local node_ip
    node_ip=$(freq_resolve_ip "$node") || die "Cannot resolve: ${node}"

    # Step 1: Create empty VM
    _step_start "Create VM shell"
    if freq_ssh "$node" "sudo qm create ${vmid} --name ${name} --memory 2048 --cores 2 --net0 virtio,bridge=vmbr0 --ostype l26" 2>/dev/null; then
        _step_ok
    else
        _step_fail "create failed"; return 1
    fi

    # Step 2: Copy image to node
    _step_start "Copy image to node"
    if scp -i "${FREQ_KEY_PATH}" "$image_path" "${REMOTE_USER}@${node_ip}:/tmp/${image}" 2>/dev/null; then
        _step_ok
    else
        _step_fail "scp failed"; return 1
    fi

    # Step 3: Import disk
    _step_start "Import disk from image"
    local storage="${PVE_STORAGE:-local-lvm}"
    if freq_ssh "$node" "sudo qm importdisk ${vmid} /tmp/${image} ${storage}" 2>/dev/null; then
        _step_ok
    else
        _step_fail "import failed"; return 1
    fi

    # Step 4: Configure VM
    _step_start "Configure VM hardware"
    freq_ssh "$node" "sudo qm set ${vmid} --scsihw virtio-scsi-single --scsi0 ${storage}:vm-${vmid}-disk-0 --boot order=scsi0 --ide2 ${storage}:cloudinit --serial0 socket --vga serial0 --agent enabled=1" 2>/dev/null
    _step_ok

    # Step 5: Convert to template
    _step_start "Convert to template"
    if freq_ssh "$node" "sudo qm template ${vmid}" 2>/dev/null; then
        _step_ok
    else
        _step_fail "template conversion failed"
    fi

    # Cleanup
    freq_ssh "$node" "sudo rm -f /tmp/${image}" 2>/dev/null

    freq_blank
    freq_line "  ${GREEN}${_TICK}${RESET} Template ${vmid} (${name}) created on ${node}"
    freq_footer
    log "templates: setup vmid=${vmid} node=${node} image=${image}"
}
