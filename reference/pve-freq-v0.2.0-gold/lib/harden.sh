#!/bin/bash
# =============================================================================
# PVE FREQ — lib/harden.sh
# Security Hardening (was stub in v1.0.0, now real)
# Commands: cmd_harden
# Dependencies: core.sh, ssh.sh, resolve.sh, audit.sh
#
# CORRECTED BETA: Full implementation. Bridges to Python engine when available.
# Uses FREQ's single-SSH-multi-section pattern for efficiency.
# =============================================================================
# shellcheck disable=SC2154

cmd_harden() {
    local subcmd="${1:-check}"
    shift 2>/dev/null || true
    case "$subcmd" in
        check)    _harden_check "$@" ;;
        fix)      _harden_fix "$@" ;;
        ssh)      _harden_ssh_detail "$@" ;;
        status)   _harden_status ;;
        help|-h)  _harden_help ;;
        *)        echo -e "  ${RED}Unknown:${RESET} harden $subcmd"; _harden_help ;;
    esac
}

_harden_check() {
    require_operator || return 1
    require_ssh_key
    local target="${1:---all}"
    freq_header "Security Hardening Check"
    local total_findings=0

    load_hosts
    for ((i=0; i<HOST_COUNT; i++)); do
        local ip="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        [[ "$htype" == "switch" || "$htype" == "idrac" ]] && continue
        [[ "$target" != "--all" && "$target" != "$label" ]] && continue

        _step_start "$label ($htype)"

        local data
        data=$(freq_ssh "$label" '
            echo "===SSHD==="
            grep -E "^(PermitRootLogin|PasswordAuthentication|MaxAuthTries|X11Forwarding|AllowTcpForwarding)" /etc/ssh/sshd_config 2>/dev/null || echo "NO_SSHD"
            echo "===RPCBIND==="
            ss -tlnp 2>/dev/null | grep ":111 " || echo "CLEAN"
            echo "===DOCKER==="
            sudo docker ps --format "{{.Image}}" 2>/dev/null | grep -c ":latest" || echo "0"
            echo "===BINDS==="
            sudo docker ps --format "{{.Ports}}" 2>/dev/null | grep -c "0.0.0.0:" || echo "0"
            echo "===END==="
        ' 2>/dev/null)

        local findings=0

        # SSH checks
        local sshd_section
        sshd_section=$(echo "$data" | sed -n '/===SSHD===/,/===RPCBIND===/p' | grep -v "===")
        local permit_root
        permit_root=$(echo "$sshd_section" | grep "^PermitRootLogin" | awk '{print $2}')
        if [[ "$permit_root" == "yes" ]]; then
            echo -e "      ${RED}CRIT${RESET} PermitRootLogin=yes (should be prohibit-password)"
            ((findings++))
        fi
        local max_auth
        max_auth=$(echo "$sshd_section" | grep "^MaxAuthTries" | awk '{print $2}')
        if [[ -z "$max_auth" || "$max_auth" -gt 5 ]]; then
            echo -e "      ${YELLOW}WARN${RESET} MaxAuthTries=${max_auth:-unlimited} (should be 3-5)"
            ((findings++))
        fi
        local x11
        x11=$(echo "$sshd_section" | grep "^X11Forwarding" | awk '{print $2}')
        if [[ "$x11" == "yes" ]]; then
            echo -e "      ${YELLOW}WARN${RESET} X11Forwarding=yes (should be no)"
            ((findings++))
        fi

        # rpcbind
        local rpc_section
        rpc_section=$(echo "$data" | sed -n '/===RPCBIND===/,/===DOCKER===/p' | grep -v "===")
        if [[ "$rpc_section" != "CLEAN" && -n "$rpc_section" ]]; then
            echo -e "      ${YELLOW}WARN${RESET} rpcbind listening on port 111"
            ((findings++))
        fi

        # Docker checks (if applicable)
        if [[ "$htype" == "docker" || "$htype" == "linux" ]]; then
            local latest_count
            latest_count=$(echo "$data" | sed -n '/===DOCKER===/,/===BINDS===/p' | grep -v "===" | head -1)
            if [[ "${latest_count:-0}" -gt 0 ]]; then
                echo -e "      ${YELLOW}WARN${RESET} $latest_count container(s) using :latest tag"
                ((findings++))
            fi
            local bind_count
            bind_count=$(echo "$data" | sed -n '/===BINDS===/,/===END===/p' | grep -v "===" | head -1)
            if [[ "${bind_count:-0}" -gt 0 ]]; then
                echo -e "      ${YELLOW}WARN${RESET} $bind_count container port(s) bound to 0.0.0.0"
                ((findings++))
            fi
        fi

        if [[ $findings -eq 0 ]]; then
            _step_ok "compliant"
        else
            _step_warn "$findings finding(s)"
        fi
        total_findings=$((total_findings + findings))
    done

    freq_divider
    echo -e "  Total findings: $total_findings"
    [[ $total_findings -gt 0 ]] && echo -e "  Run ${BOLD}freq harden fix${RESET} to remediate"
    freq_footer
    log "harden: check complete, $total_findings findings"
}

_harden_fix() {
    require_admin || return 1
    require_ssh_key
    local target="${1:---all}"

    freq_header "Security Hardening — Fix"
    echo -e "  ${YELLOW}This modifies SSH configuration on fleet hosts.${RESET}"
    echo ""

    # Check for Python engine first
    if [ -d "$FREQ_DIR/engine" ] && [ -f "$FREQ_DIR/engine/cli.py" ]; then
        echo "  Using Python remediation engine..."
        python3 -m engine.cli run ssh_hardening 2>&1
        freq_footer
        return
    fi

    # Built-in fix (no engine)
    _freq_confirm "Apply SSH hardening to ${target}?" || return 0

    load_hosts
    local fixed=0 failed=0
    for ((i=0; i<HOST_COUNT; i++)); do
        local ip="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        [[ "$htype" == "switch" || "$htype" == "idrac" ]] && continue
        [[ "$target" != "--all" && "$target" != "$label" ]] && continue

        _step_start "Fixing: $label"

        if [[ "$DRY_RUN" == "true" ]]; then
            echo -e "      ${CYAN}[DRY-RUN]${RESET} Would set PermitRootLogin=prohibit-password, MaxAuthTries=3"
            _step_ok "(dry)"
            continue
        fi

        if [[ "$htype" == "truenas" ]]; then
            freq_ssh "$label" "sudo midclt call ssh.update '{\"rootlogin\": false, \"tcpfwd\": false}'" 2>/dev/null
            freq_ssh "$label" "sudo midclt call service.restart ssh" 2>/dev/null
        else
            freq_ssh "$label" "
                sudo sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
                sudo grep -q '^MaxAuthTries' /etc/ssh/sshd_config && sudo sed -i 's/^MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config || echo 'MaxAuthTries 3' | sudo tee -a /etc/ssh/sshd_config > /dev/null
                sudo sed -i 's/^X11Forwarding.*/X11Forwarding no/' /etc/ssh/sshd_config
                sudo systemctl restart sshd
            " 2>/dev/null
        fi

        # Verify
        local verify
        verify=$(freq_ssh "$label" "grep '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null" 2>/dev/null)
        if echo "$verify" | grep -q "prohibit-password"; then
            _step_ok "verified"
            ((fixed++))
        else
            _step_fail "verify failed"
            ((failed++))
        fi
    done

    freq_divider
    echo "  Fixed: $fixed | Failed: $failed"
    freq_footer
    log "harden: fix complete, $fixed fixed, $failed failed"
}

_harden_ssh_detail() {
    require_operator || return 1
    local target="${1:---all}"
    freq_header "SSH Configuration Detail"
    load_hosts
    for ((i=0; i<HOST_COUNT; i++)); do
        local label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        [[ "$htype" == "switch" || "$htype" == "idrac" ]] && continue
        [[ "$target" != "--all" && "$target" != "$label" ]] && continue
        echo "  $label ($htype):"
        freq_ssh "$label" "grep -E '^(PermitRootLogin|PasswordAuth|MaxAuth|X11|AllowTcp|PubkeyAuth)' /etc/ssh/sshd_config 2>/dev/null" 2>/dev/null | while read -r line; do
            echo "    $line"
        done
        echo ""
    done
    freq_footer
}

_harden_status() {
    freq_header "Hardening Status"
    echo "  Last check: $(stat -c '%Y' "$FREQ_LOG" 2>/dev/null | xargs -I{} date -d @{} 2>/dev/null || echo 'unknown')"
    echo "  Run 'freq harden check' for current findings"
    freq_footer
}

_harden_help() {
    echo "  Usage: freq harden [check|fix|ssh|status]"
    echo ""
    echo "  check     Read-only scan for security findings"
    echo "  fix       Apply SSH hardening (or use Python engine)"
    echo "  ssh       Show detailed SSH config per host"
    echo "  status    Show last check results"
}
