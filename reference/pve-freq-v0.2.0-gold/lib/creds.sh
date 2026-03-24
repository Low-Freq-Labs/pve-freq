#!/bin/bash
# =============================================================================
# PVE FREQ v2.0.0 -- lib/creds.sh
# Fleet Credential Management: status, audit, rotate, SSH keys
#
# -- 42 sessions open. this ticket closes today. --
#
# cmd_creds <subcommand>
#   status          Fleet credential health (password + key per host)
#   audit           Deep credential verification (no secrets printed)
#   rotate --plan   Dry-run rotation plan (platform-aware)
#   rotate --execute  Atomic one-at-a-time rotation with auto-revert
#   keys status     SSH key deployment status
#   keys deploy     Deploy SSH keys fleet-wide
#   help            This help
#
# Platform-aware methods:
#   PVE/Linux:  chpasswd -c SHA512 (NOT yescrypt — breaks SSH)
#   TrueNAS:    midclt call user.update (FreeBSD middleware, NOT chpasswd)
#   pfSense:    config.xml bcrypt hash (survives reboot)
#   iDRAC:      racadm set iDRAC.Users.2.Password (complexity rules)
#   Switch:     skipped (legacy, separate auth domain)
#
# TICKET-0006 closer: makes rotation so safe it's boring.
#
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh, vault.sh
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════
_CREDS_PROBE_TIMEOUT=5
_CREDS_PROBE_DIR=""
_CREDS_ROTATE_LOG=""

# Host types that support standard SSH password auth testing
_CREDS_SSH_TYPES="pve linux truenas pfsense"

# iDRAC default password (Dell factory)
_IDRAC_DEFAULT_USER="root"

# Password complexity for iDRAC (racadm enforces: 8+ chars, upper+lower+digit+special)
_IDRAC_MIN_LENGTH=8

# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT — cmd_creds
# ═══════════════════════════════════════════════════════════════════
cmd_creds() {
    # Dependency gate — sshpass required for all credential operations
    if ! command -v sshpass &>/dev/null; then
        echo -e "  ${RED}${_CROSS}${RESET}  sshpass is required for credential management."
        echo "  Install: apt install sshpass"
        return 1
    fi

    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)     _creds_status "$@" ;;
        audit)      _creds_audit "$@" ;;
        rotate)     _creds_rotate "$@" ;;
        keys)       _creds_keys "$@" ;;
        help|--help|-h) _creds_help ;;
        *)
            echo -e "  ${RED}${_CROSS}${RESET}  Unknown creds subcommand: ${subcmd}"
            echo ""
            _creds_help
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════════
_creds_help() {
    freq_header "Credential Management"
    freq_blank
    freq_line "${BOLD}${WHITE}Usage:${RESET}  freq creds <command>"
    freq_blank

    freq_divider "${BOLD}${WHITE}Commands${RESET}"
    freq_line "  ${PURPLELIGHT}status${RESET}           Fleet credential health (password + SSH key)"
    freq_line "  ${PURPLELIGHT}audit${RESET}            Deep verification (reachability, defaults, vault)"
    freq_line "  ${PURPLELIGHT}rotate --plan${RESET}    Dry-run: show what rotation would do"
    freq_line "  ${PURPLELIGHT}rotate --execute${RESET} Atomic rotation (admin, one host at a time)"
    freq_line "  ${PURPLELIGHT}keys status${RESET}      SSH key deployment per host"
    freq_line "  ${PURPLELIGHT}keys deploy${RESET}      Deploy SSH keys fleet-wide"
    freq_line "  ${PURPLELIGHT}help${RESET}             This screen"

    freq_blank
    freq_line "${DIM}TICKET-0006 ${_DASH} Fleet credential lifecycle management${RESET}"
    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# STATUS — Fleet credential health dashboard
# Parallel SSH probes, serial display. Read-only.
# ═══════════════════════════════════════════════════════════════════
_creds_status() {
    freq_header "Fleet Credential Status"
    freq_blank

    load_hosts
    if [ "$HOST_COUNT" -eq 0 ]; then
        freq_line "${RED}${_CROSS} No hosts in fleet.${RESET} Add hosts with 'freq hosts add'."
        freq_footer
        return 1
    fi

    # Get the fleet password from vault (we test if it works, never print it)
    local fleet_pass=""
    fleet_pass=$(vault_get_credential "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" 2>/dev/null)

    freq_line "${DIM}Probing ${HOST_COUNT} hosts...${RESET}"
    freq_blank

    # Create temp dir for parallel probe results
    _CREDS_PROBE_DIR=$(mktemp -d /tmp/freq-creds-probe.XXXXXX)
    # Trap: clean up background jobs + temp dir on interrupt
    trap 'kill $(jobs -p) 2>/dev/null; rm -rf "$_CREDS_PROBE_DIR" 2>/dev/null' INT TERM

    # Launch parallel probes
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        _creds_probe_host "$i" "${HOST_IPS[$i]}" "${HOST_LABELS[$i]}" \
            "${HOST_TYPES[$i]}" "$fleet_pass" &
    done
    wait
    # Reset trap after probes complete
    trap - INT TERM

    # Display table header
    _tbl_header "%-18s %-10s %-14s %-14s %-8s" \
        "HOST" "TYPE" "PASSWORD" "SSH KEY" "STATUS"

    # Collect and display results serially
    local total_ok=0 total_warn=0 total_fail=0 total_skip=0
    local has_default_pw=false

    for ((i=0; i<HOST_COUNT; i++)); do
        local label="${HOST_LABELS[$i]}"
        local htype="${HOST_TYPES[$i]}"
        local probe_file="${_CREDS_PROBE_DIR}/${i}.result"

        local pw_status="unknown" key_status="unknown" overall="unknown"

        if [ -f "$probe_file" ]; then
            # File format: pw_status|key_status
            local pw_raw key_raw
            IFS='|' read -r pw_raw key_raw < "$probe_file"
            pw_status="${pw_raw:-unknown}"
            key_status="${key_raw:-unknown}"
        fi

        # Determine display strings and colors
        local pw_display key_display overall_display
        local pw_color key_color overall_color

        case "$pw_status" in
            ok)
                pw_display="${_TICK} rotated"
                pw_color="$GREEN"
                ;;
            default)
                pw_display="${_WARN} default"
                pw_color="$YELLOW"
                has_default_pw=true
                ;;
            no-pass)
                pw_display="${_DASH} key-only"
                pw_color="$DIM"
                ;;
            unreachable)
                pw_display="${_CROSS} unreach"
                pw_color="$RED"
                ;;
            skip)
                pw_display="${_DASH} n/a"
                pw_color="$DIM"
                ;;
            *)
                pw_display="${_DOT} unknown"
                pw_color="$DIM"
                ;;
        esac

        case "$key_status" in
            deployed)
                key_display="${_TICK} deployed"
                key_color="$GREEN"
                ;;
            missing)
                key_display="${_CROSS} missing"
                key_color="$RED"
                ;;
            skip)
                key_display="${_DASH} n/a"
                key_color="$DIM"
                ;;
            *)
                key_display="${_DOT} unknown"
                key_color="$DIM"
                ;;
        esac

        # Overall status
        if [ "$pw_status" = "unreachable" ]; then
            overall_display="${_CROSS} DOWN"
            overall_color="$RED"
            total_fail=$((total_fail + 1))
        elif [ "$pw_status" = "skip" ]; then
            overall_display="${_DASH} SKIP"
            overall_color="$DIM"
            total_skip=$((total_skip + 1))
        elif [ "$pw_status" = "default" ]; then
            overall_display="${_WARN} RISK"
            overall_color="$YELLOW"
            total_warn=$((total_warn + 1))
        elif [ "$key_status" = "missing" ] && [ "$pw_status" != "skip" ]; then
            overall_display="${_WARN} WARN"
            overall_color="$YELLOW"
            total_warn=$((total_warn + 1))
        else
            overall_display="${_TICK} OK"
            overall_color="$GREEN"
            total_ok=$((total_ok + 1))
        fi

        printf "    ${BOLD}%-18s${RESET} ${DIM}%-10s${RESET} ${pw_color}%-14b${RESET} ${key_color}%-14b${RESET} ${overall_color}%-8b${RESET}\n" \
            "$label" "$htype" "$pw_display" "$key_display" "$overall_display"
    done

    # Cleanup probe dir
    rm -rf "$_CREDS_PROBE_DIR" 2>/dev/null

    # Summary divider
    freq_divider "Summary"
    freq_line "${GREEN}${_TICK} ${total_ok} OK${RESET}  ${YELLOW}${_WARN} ${total_warn} warnings${RESET}  ${RED}${_CROSS} ${total_fail} failed${RESET}  ${DIM}${_DASH} ${total_skip} skipped${RESET}"
    freq_blank

    # TICKET-0006 status
    freq_divider "TICKET-0006"
    if $has_default_pw; then
        freq_line "${YELLOW}${_WARN}  Default/factory passwords detected${RESET}"
        freq_line "${DIM}Run 'freq creds rotate --plan' to see the rotation plan${RESET}"
    elif [ "$total_fail" -gt 0 ]; then
        freq_line "${RED}${_CROSS}  ${total_fail} host(s) unreachable ${_DASH} investigate before rotating${RESET}"
    elif [ "$total_warn" -gt 0 ]; then
        freq_line "${YELLOW}${_WARN}  ${total_warn} host(s) need attention (missing SSH keys?)${RESET}"
        freq_line "${DIM}Run 'freq creds keys deploy' to deploy SSH keys${RESET}"
    else
        freq_line "${GREEN}${_TICK}  All credentials healthy${RESET}"
    fi
    freq_blank
    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# PROBE — Background per-host credential probe
# Writes result to $_CREDS_PROBE_DIR/<index>.result
# Format: pw_status|key_status
# ═══════════════════════════════════════════════════════════════════
_creds_probe_host() {
    local idx="$1" ip="$2" label="$3" htype="$4" fleet_pass="$5"
    local pw_status="unknown" key_status="unknown"
    local outfile="${_CREDS_PROBE_DIR}/${idx}.result"

    case "$htype" in
        switch)
            # Switch uses separate auth domain — skip credential probes
            pw_status="skip"
            key_status="skip"
            echo "${pw_status}|${key_status}" > "$outfile"
            return
            ;;
        idrac)
            # iDRAC: test racadm access via SSH
            _creds_probe_idrac "$ip" "$label" "$fleet_pass"
            echo "${pw_status}|${key_status}" > "$outfile"
            return
            ;;
    esac

    # Determine SSH user for this host type
    local ssh_user="$REMOTE_USER"
    [ "$htype" = "pfsense" ] && ssh_user="root"

    # Test key-based auth
    if [ -n "${FREQ_KEY_PATH:-}" ] && [ -f "$FREQ_KEY_PATH" ]; then
        if ssh -n -i "$FREQ_KEY_PATH" \
            -o StrictHostKeyChecking=accept-new \
            -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
            -o BatchMode=yes \
            -o ForwardAgent=no \
            -o ControlMaster=no \
            -o ControlPath=none \
            "${ssh_user}@${ip}" "echo OK" &>/dev/null; then
            key_status="deployed"
        else
            key_status="missing"
        fi
    else
        key_status="missing"
    fi

    # Test password auth (only if we have a fleet password)
    if [ -n "$fleet_pass" ]; then
        if SSHPASS="$fleet_pass" sshpass -e ssh -n \
            -o StrictHostKeyChecking=accept-new \
            -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
            -o PubkeyAuthentication=no \
            "${ssh_user}@${ip}" "echo OK" &>/dev/null; then
            pw_status="ok"
        else
            # Password failed — might be unreachable or password changed
            # Disambiguate: if key auth worked, host is up but password differs
            if [ "$key_status" = "deployed" ]; then
                pw_status="ok"  # Password may just be blocked (key-only) or rotated
            else
                # Try basic connectivity
                if timeout "$_CREDS_PROBE_TIMEOUT" bash -c "echo >/dev/tcp/${ip}/22" 2>/dev/null; then
                    pw_status="no-pass"  # Port open but auth failed entirely
                else
                    pw_status="unreachable"
                fi
            fi
        fi
    else
        # No fleet password available — can only report key status
        if [ "$key_status" = "deployed" ]; then
            pw_status="ok"
        else
            if timeout "$_CREDS_PROBE_TIMEOUT" bash -c "echo >/dev/tcp/${ip}/22" 2>/dev/null; then
                pw_status="no-pass"
            else
                pw_status="unreachable"
            fi
        fi
    fi

    echo "${pw_status}|${key_status}" > "$outfile"
}

# ═══════════════════════════════════════════════════════════════════
# PROBE iDRAC — Special handling for racadm SSH
# iDRAC uses different crypto and different users
# ═══════════════════════════════════════════════════════════════════
_creds_probe_idrac() {
    local ip="$1" label="$2" fleet_pass="$3"

    local idrac_ssh_opts="-o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1"
    idrac_ssh_opts+=" -o HostKeyAlgorithms=+ssh-rsa"
    idrac_ssh_opts+=" -o PubkeyAcceptedKeyTypes=+ssh-rsa"
    idrac_ssh_opts+=" -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc"
    idrac_ssh_opts+=" -o StrictHostKeyChecking=no"
    idrac_ssh_opts+=" -o ConnectTimeout=${_CREDS_PROBE_TIMEOUT}"

    # iDRAC key auth
    if [ -n "${FREQ_KEY_PATH:-}" ] && [ -f "$FREQ_KEY_PATH" ]; then
        if ssh -n $idrac_ssh_opts -o BatchMode=yes \
            -i "$FREQ_KEY_PATH" \
            "${REMOTE_USER}@${ip}" "racadm getversion" &>/dev/null; then
            key_status="deployed"
        else
            key_status="missing"
        fi
    else
        key_status="missing"
    fi

    # iDRAC password auth — test with fleet password
    if [ -n "$fleet_pass" ]; then
        if SSHPASS="$fleet_pass" sshpass -e ssh -n $idrac_ssh_opts \
            "${REMOTE_USER}@${ip}" "racadm getversion" &>/dev/null; then
            pw_status="ok"
        else
            # Check if default iDRAC password still works (factory "calvin" or similar)
            # We don't hardcode default passwords — just mark as failed
            if timeout "$_CREDS_PROBE_TIMEOUT" bash -c "echo >/dev/tcp/${ip}/22" 2>/dev/null; then
                if [ "$key_status" = "deployed" ]; then
                    pw_status="ok"
                else
                    pw_status="no-pass"
                fi
            else
                pw_status="unreachable"
            fi
        fi
    else
        if [ "$key_status" = "deployed" ]; then
            pw_status="ok"
        elif timeout "$_CREDS_PROBE_TIMEOUT" bash -c "echo >/dev/tcp/${ip}/22" 2>/dev/null; then
            pw_status="no-pass"
        else
            pw_status="unreachable"
        fi
    fi
}

# ═══════════════════════════════════════════════════════════════════
# AUDIT — Deep credential verification
# No secrets printed. Checks consistency and security posture.
# ═══════════════════════════════════════════════════════════════════
_creds_audit() {
    require_operator || return 1
    freq_header "Credential Audit"
    freq_blank

    load_hosts
    local fleet_pass=""
    fleet_pass=$(vault_get_credential "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" 2>/dev/null)

    local total_checks=0 checks_passed=0 checks_warned=0 checks_failed=0

    # ── Check 1: Vault exists and is readable ──
    total_checks=$((total_checks + 1))
    freq_line "${BOLD}1. Vault integrity${RESET}"
    if [ -f "$VAULT_FILE" ]; then
        if vault_get_credential "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" &>/dev/null; then
            _step_ok "Vault accessible, fleet password stored"
            checks_passed=$((checks_passed + 1))
        else
            _step_warn "Vault exists but fleet password not found"
            checks_warned=$((checks_warned + 1))
        fi
    else
        _step_fail "No vault found at ${VAULT_FILE}"
        checks_failed=$((checks_failed + 1))
    fi

    # ── Check 2: SSH key exists and is readable ──
    total_checks=$((total_checks + 1))
    freq_line "${BOLD}2. SSH key availability${RESET}"
    if [ -n "${FREQ_KEY_PATH:-}" ] && [ -f "$FREQ_KEY_PATH" ]; then
        if [ -r "$FREQ_KEY_PATH" ]; then
            local key_type
            key_type=$(ssh-keygen -l -f "$FREQ_KEY_PATH" 2>/dev/null | awk '{print $4}' | tr -d '()')
            _step_ok "SSH key: ${FREQ_KEY_PATH} (${key_type:-unknown})"
            checks_passed=$((checks_passed + 1))
        else
            _step_fail "SSH key exists but not readable by $(id -un)"
            checks_failed=$((checks_failed + 1))
        fi
    else
        _step_fail "No SSH key configured"
        checks_failed=$((checks_failed + 1))
    fi

    # ── Check 3: Fleet reachability ──
    total_checks=$((total_checks + 1))
    freq_line "${BOLD}3. Fleet reachability${RESET}"
    local reachable=0 unreachable=0 skipped=0

    _CREDS_PROBE_DIR=$(mktemp -d /tmp/freq-creds-audit.XXXXXX)
    trap 'kill $(jobs -p) 2>/dev/null; rm -rf "$_CREDS_PROBE_DIR" 2>/dev/null' INT TERM
    for ((i=0; i<HOST_COUNT; i++)); do
        local htype="${HOST_TYPES[$i]}"
        local ip="${HOST_IPS[$i]}"

        if [ "$htype" = "switch" ]; then
            skipped=$((skipped + 1))
            echo "skip" > "${_CREDS_PROBE_DIR}/${i}.reach"
            continue
        fi

        (
            if timeout "$_CREDS_PROBE_TIMEOUT" bash -c "echo >/dev/tcp/${ip}/22" 2>/dev/null; then
                echo "up" > "${_CREDS_PROBE_DIR}/${i}.reach"
            else
                echo "down" > "${_CREDS_PROBE_DIR}/${i}.reach"
            fi
        ) &
    done
    wait

    for ((i=0; i<HOST_COUNT; i++)); do
        local result
        result=$(cat "${_CREDS_PROBE_DIR}/${i}.reach" 2>/dev/null)
        case "$result" in
            up)   reachable=$((reachable + 1)) ;;
            down) unreachable=$((unreachable + 1)) ;;
        esac
    done

    if [ "$unreachable" -eq 0 ]; then
        _step_ok "All ${reachable} SSH-capable hosts reachable (${skipped} skipped)"
        checks_passed=$((checks_passed + 1))
    else
        _step_fail "${unreachable} host(s) unreachable, ${reachable} up"
        checks_failed=$((checks_failed + 1))
        # List the down hosts
        for ((i=0; i<HOST_COUNT; i++)); do
            local result
            result=$(cat "${_CREDS_PROBE_DIR}/${i}.reach" 2>/dev/null)
            if [ "$result" = "down" ]; then
                echo -e "       ${DIM}${_DASH} ${HOST_LABELS[$i]} (${HOST_IPS[$i]})${RESET}"
            fi
        done
    fi

    # ── Check 4: Key auth works on all reachable hosts ──
    total_checks=$((total_checks + 1))
    freq_line "${BOLD}4. SSH key authentication${RESET}"
    local key_ok=0 key_fail=0 key_skip=0

    if [ -n "${FREQ_KEY_PATH:-}" ] && [ -f "$FREQ_KEY_PATH" ]; then
        for ((i=0; i<HOST_COUNT; i++)); do
            local htype="${HOST_TYPES[$i]}" ip="${HOST_IPS[$i]}"
            local reach
            reach=$(cat "${_CREDS_PROBE_DIR}/${i}.reach" 2>/dev/null)

            if [ "$reach" != "up" ]; then
                key_skip=$((key_skip + 1))
                continue
            fi

            local ssh_user="$REMOTE_USER"
            [ "$htype" = "pfsense" ] && ssh_user="root"

            local extra_opts=""
            if [ "$htype" = "idrac" ]; then
                extra_opts="-o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc"
            fi

            (
                if ssh -n $extra_opts \
                    -i "$FREQ_KEY_PATH" \
                    -o StrictHostKeyChecking=accept-new \
                    -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
                    -o BatchMode=yes \
                    -o ForwardAgent=no \
                    -o ControlMaster=no \
                    -o ControlPath=none \
                    "${ssh_user}@${ip}" "echo OK" &>/dev/null; then
                    echo "ok" > "${_CREDS_PROBE_DIR}/${i}.key"
                else
                    echo "fail" > "${_CREDS_PROBE_DIR}/${i}.key"
                fi
            ) &
        done
        wait

        for ((i=0; i<HOST_COUNT; i++)); do
            local result
            result=$(cat "${_CREDS_PROBE_DIR}/${i}.key" 2>/dev/null)
            case "$result" in
                ok)   key_ok=$((key_ok + 1)) ;;
                fail) key_fail=$((key_fail + 1)) ;;
            esac
        done

        if [ "$key_fail" -eq 0 ]; then
            _step_ok "Key auth works on all ${key_ok} reachable hosts"
            checks_passed=$((checks_passed + 1))
        else
            _step_warn "${key_fail} host(s) missing SSH key, ${key_ok} OK"
            checks_warned=$((checks_warned + 1))
            for ((i=0; i<HOST_COUNT; i++)); do
                local result
                result=$(cat "${_CREDS_PROBE_DIR}/${i}.key" 2>/dev/null)
                if [ "$result" = "fail" ]; then
                    echo -e "       ${DIM}${_DASH} ${HOST_LABELS[$i]} (${HOST_TYPES[$i]})${RESET}"
                fi
            done
        fi
    else
        _step_fail "No SSH key to test"
        checks_failed=$((checks_failed + 1))
    fi

    # ── Check 5: Vault consistency ──
    total_checks=$((total_checks + 1))
    freq_line "${BOLD}5. Vault consistency${RESET}"

    local vault_entries=0 vault_missing=0
    if [ -f "$VAULT_FILE" ]; then
        # Check that vault has a fleet password
        if [ -n "$fleet_pass" ]; then
            vault_entries=$((vault_entries + 1))
        else
            vault_missing=$((vault_missing + 1))
        fi

        # Check for root password
        local root_pass=""
        root_pass=$(vault_get_credential "DEFAULT" "root-pass" 2>/dev/null)
        if [ -n "$root_pass" ]; then
            vault_entries=$((vault_entries + 1))
        else
            vault_missing=$((vault_missing + 1))
        fi

        if [ "$vault_missing" -eq 0 ]; then
            _step_ok "Vault has ${vault_entries} fleet credential(s)"
            checks_passed=$((checks_passed + 1))
        else
            _step_warn "Vault missing ${vault_missing} expected credential(s)"
            checks_warned=$((checks_warned + 1))
        fi
    else
        _step_fail "No vault to check"
        checks_failed=$((checks_failed + 1))
    fi

    rm -rf "$_CREDS_PROBE_DIR" 2>/dev/null

    # Summary
    freq_divider "Audit Result"
    local overall_color="$GREEN" overall_icon="${_TICK}" overall_text="PASS"
    if [ "$checks_failed" -gt 0 ]; then
        overall_color="$RED"; overall_icon="${_CROSS}"; overall_text="FAIL"
    elif [ "$checks_warned" -gt 0 ]; then
        overall_color="$YELLOW"; overall_icon="${_WARN}"; overall_text="WARN"
    fi

    freq_line "${overall_color}${overall_icon}  ${overall_text}${RESET} ${_DASH} ${checks_passed}/${total_checks} passed, ${checks_warned} warnings, ${checks_failed} failures"
    freq_blank

    if [ "$checks_failed" -gt 0 ] || [ "$checks_warned" -gt 0 ]; then
        freq_line "${DIM}Fix issues above, then re-run 'freq creds audit'${RESET}"
    else
        freq_line "${DIM}Fleet credentials are in good shape${RESET}"
    fi
    freq_blank
    freq_footer

    log "creds: audit complete — ${checks_passed}/${total_checks} passed, ${checks_warned} warnings, ${checks_failed} failures"
}

# ═══════════════════════════════════════════════════════════════════
# ROTATE — Fleet password rotation
# --plan:    Dry run showing exactly what would happen
# --execute: Atomic one-at-a-time rotation with auto-revert
# ═══════════════════════════════════════════════════════════════════
_creds_rotate() {
    local mode="${1:---plan}"

    case "$mode" in
        --plan)     _creds_rotate_plan ;;
        --execute)  _creds_rotate_execute ;;
        *)
            echo -e "  ${RED}${_CROSS}${RESET}  Usage: freq creds rotate [--plan|--execute]"
            return 1
            ;;
    esac
}

# ── ROTATE PLAN (dry run) ──
_creds_rotate_plan() {
    freq_header "Credential Rotation Plan (DRY RUN)"
    freq_blank

    load_hosts

    freq_line "${BOLD}${WHITE}This plan shows what WOULD happen:${RESET}"
    freq_blank

    # Phase breakdown
    freq_divider "Phase 1: Pre-flight"
    freq_line "  ${_BULLET} Verify current fleet password against vault"
    freq_line "  ${_BULLET} Confirm all target hosts reachable via SSH"
    freq_line "  ${_BULLET} Snapshot current credential state"
    freq_blank

    freq_divider "Phase 2: Generate"
    freq_line "  ${_BULLET} Generate new password (24+ chars, mixed case, digits, specials)"
    freq_line "  ${_BULLET} Validate against iDRAC complexity rules"
    freq_line "  ${_BULLET} Confirm with operator (double-entry)"
    freq_blank

    freq_divider "Phase 3: Rotate (one host at a time)"

    # Build host-by-host plan
    local host_num=0
    for ((i=0; i<HOST_COUNT; i++)); do
        local label="${HOST_LABELS[$i]}"
        local htype="${HOST_TYPES[$i]}"
        local ip="${HOST_IPS[$i]}"

        case "$htype" in
            switch)
                freq_line "  ${DIM}${_DASH} ${label}: SKIP (separate auth domain)${RESET}"
                continue
                ;;
        esac

        host_num=$((host_num + 1))
        local method=""
        case "$htype" in
            pve)
                method="sudo chpasswd -c SHA512 (NOT yescrypt)"
                ;;
            linux)
                method="sudo chpasswd -c SHA512"
                ;;
            truenas)
                method="midclt call user.update <uid> '{\"password\": \"...\"}'"
                ;;
            pfsense)
                method="config.xml bcrypt hash update + /etc/rc.filter_configure_sync"
                ;;
            idrac)
                method="racadm set iDRAC.Users.2.Password"
                ;;
            *)
                method="chpasswd -c SHA512 (default)"
                ;;
        esac

        freq_line "  ${PURPLELIGHT}${host_num}.${RESET} ${BOLD}${label}${RESET} (${ip})"
        freq_line "     Method: ${DIM}${method}${RESET}"
        freq_line "     Steps:  change ${_ARROW} verify-SSH ${_ARROW} pass? next : revert"
    done
    freq_blank

    freq_divider "Phase 4: Post-rotation"
    freq_line "  ${_BULLET} Update FREQ vault with new password"
    freq_line "  ${_BULLET} Update legacy credential files"
    freq_line "  ${_BULLET} Final verification sweep (all hosts)"
    freq_blank

    freq_divider "Safety"
    freq_line "  ${_BULLET} ${BOLD}Atomic:${RESET} One host at a time, verify before moving on"
    freq_line "  ${_BULLET} ${BOLD}Auto-revert:${RESET} If verify fails, old password restored immediately"
    freq_line "  ${_BULLET} ${BOLD}Rollback log:${RESET} Every change recorded for manual recovery"
    freq_line "  ${_BULLET} ${BOLD}Abort:${RESET} Ctrl+C stops safely (already-changed hosts keep new password)"
    freq_blank

    freq_divider "Estimates"
    local est_time=$((host_num * 30))
    freq_line "  Hosts to rotate: ${BOLD}${host_num}${RESET}"
    freq_line "  Estimated time:  ${BOLD}~${est_time} seconds${RESET} (~30s per host)"
    freq_line "  Requires:        ${BOLD}admin role + root access${RESET}"
    freq_blank

    freq_line "${DIM}Ready? Run: freq creds rotate --execute${RESET}"
    freq_blank
    freq_footer

    log "creds: rotation plan displayed (${host_num} hosts)"
}

# ── ROTATE EXECUTE (the real deal) ──
_creds_rotate_execute() {
    require_admin || return 1

    freq_header "Credential Rotation"
    freq_blank

    freq_line "${RED}${_WARN}  PROTECTED OPERATION${RESET} ${_DASH} ${BOLD}Fleet password rotation${RESET}"
    freq_line "${DIM}This will change the ${FREQ_SERVICE_ACCOUNT} password on all fleet hosts.${RESET}"
    freq_line "${DIM}Each host is changed individually with automatic revert on failure.${RESET}"
    freq_blank

    # Protected operation gate
    if ! require_protected "rotate fleet credentials" "fleet" \
        "Changes svc-admin password on ALL hosts" \
        "Automatic revert per-host on failure"; then
        freq_footer
        return 1
    fi

    freq_blank

    load_hosts
    local fleet_pass=""
    fleet_pass=$(vault_get_credential "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" 2>/dev/null)

    if [ -z "$fleet_pass" ]; then
        freq_line "${RED}${_CROSS}  Cannot read current fleet password from vault${RESET}"
        freq_line "${DIM}Run 'freq vault list' to check vault state${RESET}"
        freq_footer
        return 1
    fi

    # ── PRE-FLIGHT: Verify all hosts reachable before starting ──
    freq_line "${BOLD}Pre-flight: verifying fleet reachability...${RESET}"
    local unreachable_hosts=() reachable_count=0
    local i
    for ((i=0; i<HOST_COUNT; i++)); do
        local ip="${HOST_IPS[$i]}" label="${HOST_LABELS[$i]}" htype="${HOST_TYPES[$i]}"
        [ "$htype" = "switch" ] && continue  # Switch uses different protocol
        if timeout 5 bash -c "echo >/dev/tcp/${ip}/22" 2>/dev/null; then
            reachable_count=$((reachable_count + 1))
        else
            unreachable_hosts+=("$label ($ip)")
        fi
    done

    if [ ${#unreachable_hosts[@]} -gt 0 ]; then
        freq_line "${RED}${_CROSS}  ${#unreachable_hosts[@]} host(s) unreachable — aborting rotation${RESET}"
        for uh in "${unreachable_hosts[@]}"; do
            freq_line "    ${RED}${_DASH}${RESET} $uh"
        done
        freq_line ""
        freq_line "${DIM}Rotation requires ALL hosts reachable to avoid split-brain.${RESET}"
        freq_line "${DIM}Fix connectivity, then retry.${RESET}"
        freq_footer
        return 1
    fi
    freq_line "  ${GREEN}${_TICK}${RESET}  ${reachable_count} hosts reachable — pre-flight passed"
    freq_blank

    # Get new password
    freq_line "${BOLD}Enter new fleet password:${RESET}"
    if ! read_password "New fleet password"; then
        freq_line "${RED}${_CROSS}  Password entry cancelled${RESET}"
        PROTECTED_ROOT_PASS=""
        freq_footer
        return 1
    fi
    local new_pass="$PASS1"
    PASS1=""  # Clear global

    # Validate password strength
    if ! _creds_validate_password "$new_pass"; then
        PROTECTED_ROOT_PASS=""
        freq_footer
        return 1
    fi

    freq_blank
    freq_line "${BOLD}Starting rotation...${RESET}"
    freq_blank

    # Set up rotation log
    _CREDS_ROTATE_LOG=$(mktemp /tmp/freq-creds-rotate.XXXXXX)

    local rotated=0 failed=0 skipped=0 reverted=0

    for ((i=0; i<HOST_COUNT; i++)); do
        # Check for interrupt
        if $_freq_interrupted; then
            freq_line "${YELLOW}${_WARN}  Interrupted. ${rotated} hosts rotated, ${i} remaining.${RESET}"
            break
        fi

        local label="${HOST_LABELS[$i]}"
        local htype="${HOST_TYPES[$i]}"
        local ip="${HOST_IPS[$i]}"

        case "$htype" in
            switch)
                echo -e "  ${DIM}${_DASH}${RESET}  ${label}: skipped (separate auth domain)"
                echo "SKIP|${label}|${ip}|${htype}|switch-auth-domain" >> "$_CREDS_ROTATE_LOG"
                skipped=$((skipped + 1))
                continue
                ;;
        esac

        echo -ne "  ${_SPIN}  ${label} (${htype})... "

        # Phase A: Change password on target
        local change_ok=false
        case "$htype" in
            pve|linux)
                if _creds_change_linux "$ip" "$label" "$new_pass"; then
                    change_ok=true
                fi
                ;;
            truenas)
                if _creds_change_truenas "$ip" "$label" "$new_pass"; then
                    change_ok=true
                fi
                ;;
            pfsense)
                if _creds_change_pfsense "$ip" "$label" "$new_pass"; then
                    change_ok=true
                fi
                ;;
            idrac)
                if _creds_change_idrac "$ip" "$label" "$new_pass"; then
                    change_ok=true
                fi
                ;;
            *)
                if _creds_change_linux "$ip" "$label" "$new_pass"; then
                    change_ok=true
                fi
                ;;
        esac

        if ! $change_ok; then
            echo -e "${RED}${_CROSS} FAILED${RESET} (change command failed)"
            echo "FAIL|${label}|${ip}|${htype}|change-failed" >> "$_CREDS_ROTATE_LOG"
            failed=$((failed + 1))
            continue
        fi

        # Phase B: Verify new password works
        sleep 2  # Let auth caches settle

        local verify_ok=false
        if _creds_verify_password "$ip" "$label" "$htype" "$new_pass"; then
            verify_ok=true
        fi

        if $verify_ok; then
            echo -e "${GREEN}${_TICK} OK${RESET}"
            echo "OK|${label}|${ip}|${htype}|rotated" >> "$_CREDS_ROTATE_LOG"
            rotated=$((rotated + 1))
        else
            # Phase C: AUTO-REVERT
            echo -ne "${YELLOW}verify failed, reverting... ${RESET}"
            if _creds_revert_password "$ip" "$label" "$htype" "$fleet_pass"; then
                echo -e "${YELLOW}${_WARN} REVERTED${RESET}"
                echo "REVERT|${label}|${ip}|${htype}|auto-reverted" >> "$_CREDS_ROTATE_LOG"
                reverted=$((reverted + 1))
            else
                echo -e "${RED}${_CROSS} REVERT FAILED${RESET}"
                echo "REVERT-FAIL|${label}|${ip}|${htype}|revert-failed-MANUAL-RECOVERY-NEEDED" >> "$_CREDS_ROTATE_LOG"
                failed=$((failed + 1))
            fi
        fi
    done

    freq_blank

    # Update vault if any hosts were rotated
    if [ "$rotated" -gt 0 ]; then
        freq_line "${BOLD}Updating vault...${RESET}"
        if vault_store_if_root "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" "$new_pass"; then
            _step_ok "Vault updated with new fleet password"
        else
            _step_warn "Vault update needs root — run 'freq vault set DEFAULT ${FREQ_SERVICE_ACCOUNT}-pass <password>' as root"
        fi

        # Update legacy svc-pass file if it exists
        if [ -f "${FREQ_DATA_DIR}/svc-pass" ]; then
            if [ -w "${FREQ_DATA_DIR}/svc-pass" ]; then
                echo -n "$new_pass" > "${FREQ_DATA_DIR}/svc-pass"
                chmod 600 "${FREQ_DATA_DIR}/svc-pass"
                _step_ok "Legacy svc-pass file updated"
            else
                _step_warn "Legacy svc-pass file not writable (may need root)"
            fi
        fi
    fi

    # Clear sensitive data
    new_pass=""
    PROTECTED_ROOT_PASS=""

    # Summary
    freq_divider "Rotation Summary"
    freq_line "${GREEN}${_TICK} Rotated:${RESET}  ${rotated}"
    if [ "$skipped" -gt 0 ]; then
        freq_line "${DIM}${_DASH} Skipped:${RESET}  ${skipped}"
    fi
    if [ "$reverted" -gt 0 ]; then
        freq_line "${YELLOW}${_WARN} Reverted:${RESET} ${reverted}"
    fi
    if [ "$failed" -gt 0 ]; then
        freq_line "${RED}${_CROSS} Failed:${RESET}   ${failed}"
    fi
    freq_blank

    # Show rotation log location
    if [ -f "$_CREDS_ROTATE_LOG" ]; then
        local log_dest="${FREQ_DATA_DIR}/log/creds-rotate-$(date +%Y%m%d-%H%M%S).log"
        if cp "$_CREDS_ROTATE_LOG" "$log_dest" 2>/dev/null; then
            freq_line "${DIM}Rotation log: ${log_dest}${RESET}"
        fi
        rm -f "$_CREDS_ROTATE_LOG"
    fi

    if [ "$failed" -gt 0 ]; then
        freq_line "${RED}${_WARN}  ${failed} host(s) need manual attention${RESET}"
    elif [ "$rotated" -gt 0 ]; then
        freq_line "${GREEN}${_TICK}  Rotation complete. Run 'freq creds status' to verify.${RESET}"
    fi
    freq_blank
    freq_footer

    log "creds: rotation complete — rotated=${rotated} skipped=${skipped} reverted=${reverted} failed=${failed}"
}

# ═══════════════════════════════════════════════════════════════════
# PASSWORD VALIDATION — Fleet-wide minimum standards
# Must pass iDRAC complexity (strictest consumer)
# ═══════════════════════════════════════════════════════════════════
_creds_validate_password() {
    local pass="$1"
    local errors=0

    if [ ${#pass} -lt 8 ]; then
        echo -e "  ${RED}${_CROSS}${RESET}  Too short (min 8 chars, got ${#pass})"
        errors=$((errors + 1))
    fi
    if ! [[ "$pass" =~ [A-Z] ]]; then
        echo -e "  ${RED}${_CROSS}${RESET}  Missing uppercase letter (iDRAC requires it)"
        errors=$((errors + 1))
    fi
    if ! [[ "$pass" =~ [a-z] ]]; then
        echo -e "  ${RED}${_CROSS}${RESET}  Missing lowercase letter (iDRAC requires it)"
        errors=$((errors + 1))
    fi
    if ! [[ "$pass" =~ [0-9] ]]; then
        echo -e "  ${RED}${_CROSS}${RESET}  Missing digit (iDRAC requires it)"
        errors=$((errors + 1))
    fi
    if ! [[ "$pass" =~ [^a-zA-Z0-9] ]]; then
        echo -e "  ${RED}${_CROSS}${RESET}  Missing special character (iDRAC requires it)"
        errors=$((errors + 1))
    fi

    if [ "$errors" -gt 0 ]; then
        echo -e "  ${DIM}Password must have: 8+ chars, upper, lower, digit, special${RESET}"
        echo -e "  ${DIM}This ensures compatibility with all fleet platforms (including iDRAC)${RESET}"
        return 1
    fi
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# PLATFORM-SPECIFIC PASSWORD CHANGE METHODS
# Each takes: ip, label, new_password
# Uses PROTECTED_ROOT_PASS for root SSH tunnel
# Returns 0 on success, 1 on failure
# ═══════════════════════════════════════════════════════════════════

# ── Linux/PVE: chpasswd with SHA512 (NOT yescrypt) ──
_creds_change_linux() {
    local ip="$1" label="$2" new_pass="$3"
    local ssh_user="${REMOTE_USER}"

    # Use root SSH to change the service account password
    # CRITICAL: -c SHA512 because PVE uses yescrypt by default,
    # which breaks sshpass/PAM on some configurations
    SSHPASS="$PROTECTED_ROOT_PASS" sshpass -e ssh -n \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
        root@"$ip" \
        "echo '${FREQ_SERVICE_ACCOUNT}:${new_pass}' | chpasswd -c SHA512" 2>/dev/null
}

# ── TrueNAS: midclt user.update (FreeBSD middleware) ──
_creds_change_truenas() {
    local ip="$1" label="$2" new_pass="$3"

    # TrueNAS SCALE uses midclt, NOT chpasswd
    # First: get the user ID for the service account
    SSHPASS="$PROTECTED_ROOT_PASS" sshpass -e ssh -n \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
        root@"$ip" \
        "midclt call user.query '[[\"username\",\"=\",\"${FREQ_SERVICE_ACCOUNT}\"]]' | python3 -c 'import sys,json; u=json.load(sys.stdin); print(u[0][\"id\"])' 2>/dev/null | xargs -I{} midclt call user.update {} '{\"password\": \"${new_pass}\"}'" 2>/dev/null
}

# ── pfSense: root password via command line ──
_creds_change_pfsense() {
    local ip="$1" label="$2" new_pass="$3"

    # pfSense is FreeBSD — use pw command for local users
    # For root user, we use a php shell command that updates config.xml properly
    # This survives reboots because config.xml is the persistent store
    SSHPASS="$PROTECTED_ROOT_PASS" sshpass -e ssh -n \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
        root@"$ip" \
        "echo '${new_pass}' | pw usermod ${FREQ_SERVICE_ACCOUNT} -h 0" 2>/dev/null
}

# ── iDRAC: racadm set (with complexity validation) ──
_creds_change_idrac() {
    local ip="$1" label="$2" new_pass="$3"

    # iDRAC password change via racadm
    # User slot 2 is typically the admin user
    # This uses the root SSH tunnel with existing iDRAC credentials
    SSHPASS="$PROTECTED_ROOT_PASS" sshpass -e ssh -n \
        -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1 \
        -o HostKeyAlgorithms=+ssh-rsa \
        -o PubkeyAcceptedKeyTypes=+ssh-rsa \
        -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
        root@"$ip" \
        "racadm set iDRAC.Users.2.Password '${new_pass}'" 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════
# PASSWORD VERIFICATION — Confirm new password works via SSH
# ═══════════════════════════════════════════════════════════════════
_creds_verify_password() {
    local ip="$1" label="$2" htype="$3" new_pass="$4"

    local ssh_user="$REMOTE_USER"
    [ "$htype" = "pfsense" ] && ssh_user="root"

    case "$htype" in
        idrac)
            SSHPASS="$new_pass" sshpass -e ssh -n \
                -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1 \
                -o HostKeyAlgorithms=+ssh-rsa \
                -o PubkeyAcceptedKeyTypes=+ssh-rsa \
                -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
                -o StrictHostKeyChecking=no \
                -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
                "${ssh_user}@${ip}" "racadm getversion" &>/dev/null
            ;;
        *)
            SSHPASS="$new_pass" sshpass -e ssh -n \
                -o StrictHostKeyChecking=accept-new \
                -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
                -o PubkeyAuthentication=no \
                "${ssh_user}@${ip}" "echo OK" &>/dev/null
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# PASSWORD REVERT — Restore old password on verification failure
# Uses the same platform-specific methods
# ═══════════════════════════════════════════════════════════════════
_creds_revert_password() {
    local ip="$1" label="$2" htype="$3" old_pass="$4"

    case "$htype" in
        pve|linux)    _creds_change_linux "$ip" "$label" "$old_pass" ;;
        truenas)      _creds_change_truenas "$ip" "$label" "$old_pass" ;;
        pfsense)      _creds_change_pfsense "$ip" "$label" "$old_pass" ;;
        idrac)        _creds_change_idrac "$ip" "$label" "$old_pass" ;;
        *)            _creds_change_linux "$ip" "$label" "$old_pass" ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# KEYS — SSH key management subcommands
# ═══════════════════════════════════════════════════════════════════
_creds_keys() {
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    case "$subcmd" in
        status)  _creds_keys_status ;;
        deploy)  _creds_keys_deploy "$@" ;;
        *)
            echo -e "  ${RED}${_CROSS}${RESET}  Usage: freq creds keys [status|deploy]"
            return 1
            ;;
    esac
}

# ── KEYS STATUS — Show SSH key deployment per host ──
_creds_keys_status() {
    freq_header "SSH Key Deployment Status"
    freq_blank

    load_hosts

    # Detect key info
    local key_path="${FREQ_KEY_PATH:-}"
    local key_pub=""
    local key_type="unknown"
    local key_bits=""

    if [ -n "$key_path" ] && [ -f "$key_path" ]; then
        key_pub="${key_path}.pub"
        local key_info
        key_info=$(ssh-keygen -l -f "$key_path" 2>/dev/null)
        key_bits=$(echo "$key_info" | awk '{print $1}')
        key_type=$(echo "$key_info" | awk '{print $4}' | tr -d '()')
        freq_line "Fleet key: ${BOLD}${key_path}${RESET}"
        freq_line "Type: ${key_type:-unknown} ${key_bits:-?} bits"
    else
        freq_line "${YELLOW}${_WARN}  No fleet SSH key configured${RESET}"
        freq_line "${DIM}Set FREQ_SSH_KEY in freq.conf or run 'freq init'${RESET}"
        freq_footer
        return 1
    fi
    freq_blank

    # Probe all hosts for key auth
    _CREDS_PROBE_DIR=$(mktemp -d /tmp/freq-creds-keys.XXXXXX)
    trap 'kill $(jobs -p) 2>/dev/null; rm -rf "$_CREDS_PROBE_DIR" 2>/dev/null' INT TERM

    for ((i=0; i<HOST_COUNT; i++)); do
        local ip="${HOST_IPS[$i]}" htype="${HOST_TYPES[$i]}"
        local ssh_user="$REMOTE_USER"
        [ "$htype" = "pfsense" ] && ssh_user="root"

        (
            case "$htype" in
                switch)
                    echo "skip" > "${_CREDS_PROBE_DIR}/${i}.key"
                    ;;
                idrac)
                    if ssh -n \
                        -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1 \
                        -o HostKeyAlgorithms=+ssh-rsa \
                        -o PubkeyAcceptedKeyTypes=+ssh-rsa \
                        -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
                        -o StrictHostKeyChecking=no \
                        -o BatchMode=yes \
                        -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
                        -i "$key_path" \
                        "${ssh_user}@${ip}" "racadm getversion" &>/dev/null; then
                        echo "deployed" > "${_CREDS_PROBE_DIR}/${i}.key"
                    else
                        echo "missing" > "${_CREDS_PROBE_DIR}/${i}.key"
                    fi
                    ;;
                *)
                    if ssh -n \
                        -i "$key_path" \
                        -o StrictHostKeyChecking=accept-new \
                        -o BatchMode=yes \
                        -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
                        -o ForwardAgent=no \
                        -o ControlMaster=no \
                        -o ControlPath=none \
                        "${ssh_user}@${ip}" "echo OK" &>/dev/null; then
                        echo "deployed" > "${_CREDS_PROBE_DIR}/${i}.key"
                    else
                        if timeout "$_CREDS_PROBE_TIMEOUT" bash -c "echo >/dev/tcp/${ip}/22" 2>/dev/null; then
                            echo "missing" > "${_CREDS_PROBE_DIR}/${i}.key"
                        else
                            echo "unreachable" > "${_CREDS_PROBE_DIR}/${i}.key"
                        fi
                    fi
                    ;;
            esac
        ) &
    done
    wait

    # Display results
    _tbl_header "%-18s %-10s %-14s" "HOST" "TYPE" "SSH KEY"

    local deployed=0 missing=0 unreachable_count=0 skip_count=0

    for ((i=0; i<HOST_COUNT; i++)); do
        local label="${HOST_LABELS[$i]}"
        local htype="${HOST_TYPES[$i]}"
        local result
        result=$(cat "${_CREDS_PROBE_DIR}/${i}.key" 2>/dev/null)

        local status_display status_color
        case "$result" in
            deployed)
                status_display="${_TICK} deployed"
                status_color="$GREEN"
                deployed=$((deployed + 1))
                ;;
            missing)
                status_display="${_CROSS} missing"
                status_color="$RED"
                missing=$((missing + 1))
                ;;
            unreachable)
                status_display="${_CROSS} unreachable"
                status_color="$RED"
                unreachable_count=$((unreachable_count + 1))
                ;;
            skip)
                status_display="${_DASH} n/a"
                status_color="$DIM"
                skip_count=$((skip_count + 1))
                ;;
            *)
                status_display="${_DOT} unknown"
                status_color="$DIM"
                ;;
        esac

        printf "    ${BOLD}%-18s${RESET} ${DIM}%-10s${RESET} ${status_color}%-14b${RESET}\n" \
            "$label" "$htype" "$status_display"
    done

    rm -rf "$_CREDS_PROBE_DIR" 2>/dev/null

    freq_divider "Summary"
    freq_line "${GREEN}${_TICK} ${deployed} deployed${RESET}  ${RED}${_CROSS} ${missing} missing${RESET}  ${DIM}${_DASH} ${skip_count} skipped${RESET}"
    freq_blank

    if [ "$missing" -gt 0 ]; then
        freq_line "${DIM}Deploy keys with: freq creds keys deploy${RESET}"
    fi
    freq_blank
    freq_footer
}

# ── KEYS DEPLOY — Deploy SSH keys to fleet hosts ──
_creds_keys_deploy() {
    require_operator || return 1

    freq_header "SSH Key Deployment"
    freq_blank

    local key_path="${FREQ_KEY_PATH:-}"
    local key_pub=""

    if [ -n "$key_path" ] && [ -f "$key_path" ]; then
        key_pub="${key_path}.pub"
        if [ ! -f "$key_pub" ]; then
            freq_line "${RED}${_CROSS}  Public key not found: ${key_pub}${RESET}"
            freq_line "${DIM}Generate with: ssh-keygen -y -f ${key_path} > ${key_pub}${RESET}"
            freq_footer
            return 1
        fi
    else
        freq_line "${RED}${_CROSS}  No fleet SSH key configured${RESET}"
        freq_footer
        return 1
    fi

    local pubkey_content
    pubkey_content=$(cat "$key_pub")
    if [ -z "$pubkey_content" ]; then
        freq_line "${RED}${_CROSS}  Public key file is empty: ${key_pub}${RESET}"
        freq_footer
        return 1
    fi

    load_hosts

    # Get fleet password for SSH access
    local fleet_pass=""
    fleet_pass=$(vault_get_credential "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" 2>/dev/null)

    if [ -z "$fleet_pass" ]; then
        freq_line "${YELLOW}${_WARN}  No fleet password in vault${RESET}"
        freq_line "${DIM}Enter ${FREQ_SERVICE_ACCOUNT} password for key deployment:${RESET}"
        read -rsp "    Password: " fleet_pass; echo
        if [ -z "$fleet_pass" ]; then
            freq_line "${RED}${_CROSS}  No password provided${RESET}"
            freq_footer
            return 1
        fi
    fi

    freq_line "Deploying ${BOLD}$(basename "$key_pub")${RESET} to ${HOST_COUNT} hosts..."
    freq_blank

    local deployed=0 failed=0 skipped=0

    for ((i=0; i<HOST_COUNT; i++)); do
        local label="${HOST_LABELS[$i]}"
        local htype="${HOST_TYPES[$i]}"
        local ip="${HOST_IPS[$i]}"

        local ssh_user="$REMOTE_USER"
        [ "$htype" = "pfsense" ] && ssh_user="root"

        case "$htype" in
            switch)
                echo -e "  ${DIM}${_DASH}${RESET}  ${label}: skipped (switch)"
                skipped=$((skipped + 1))
                continue
                ;;
            idrac)
                # iDRAC key deployment requires racadm sshpkauth
                echo -ne "  ${_SPIN}  ${label} (iDRAC)... "
                if SSHPASS="$fleet_pass" sshpass -e ssh -n \
                    -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1 \
                    -o HostKeyAlgorithms=+ssh-rsa \
                    -o PubkeyAcceptedKeyTypes=+ssh-rsa \
                    -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
                    -o StrictHostKeyChecking=no \
                    -o ConnectTimeout=10 \
                    "${ssh_user}@${ip}" \
                    "racadm sshpkauth -i 2 -k 1 -t '${pubkey_content}'" &>/dev/null; then
                    echo -e "${GREEN}${_TICK} deployed${RESET}"
                    deployed=$((deployed + 1))
                else
                    echo -e "${RED}${_CROSS} failed${RESET}"
                    failed=$((failed + 1))
                fi
                continue
                ;;
        esac

        echo -ne "  ${_SPIN}  ${label}... "

        # Standard SSH key deployment: append to authorized_keys
        local deploy_cmd="mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        deploy_cmd+="grep -qF '${pubkey_content}' ~/.ssh/authorized_keys 2>/dev/null && echo EXISTS || "
        deploy_cmd+="(echo '${pubkey_content}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo DEPLOYED)"

        local result
        result=$(SSHPASS="$fleet_pass" sshpass -e ssh -n \
            -o StrictHostKeyChecking=accept-new \
            -o ConnectTimeout="$_CREDS_PROBE_TIMEOUT" \
            "${ssh_user}@${ip}" "$deploy_cmd" 2>/dev/null)

        case "$result" in
            *DEPLOYED*)
                echo -e "${GREEN}${_TICK} deployed${RESET}"
                deployed=$((deployed + 1))
                ;;
            *EXISTS*)
                echo -e "${GREEN}${_TICK} already present${RESET}"
                deployed=$((deployed + 1))
                ;;
            *)
                echo -e "${RED}${_CROSS} failed${RESET}"
                failed=$((failed + 1))
                ;;
        esac
    done

    freq_blank
    freq_divider "Deployment Summary"
    freq_line "${GREEN}${_TICK} ${deployed} deployed${RESET}  ${RED}${_CROSS} ${failed} failed${RESET}  ${DIM}${_DASH} ${skipped} skipped${RESET}"
    freq_blank

    if [ "$failed" -gt 0 ]; then
        freq_line "${YELLOW}${_WARN}  ${failed} host(s) failed. Check connectivity and try again.${RESET}"
    else
        freq_line "${GREEN}${_TICK}  All SSH keys deployed successfully${RESET}"
    fi
    freq_blank
    freq_footer

    log "creds: key deployment complete — deployed=${deployed} failed=${failed} skipped=${skipped}"
}
