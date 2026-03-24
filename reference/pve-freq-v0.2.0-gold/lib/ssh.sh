#!/bin/bash
# shellcheck disable=SC2034
# =============================================================================
# PVE FREQ v1.0.0 -- lib/ssh.sh
# ONE unified SSH transport — replaces 7 per-module wrappers
#
# -- the keys to the kingdom. literally. --
#
# freq_ssh <host_or_ip> <command>     Key-based SSH (all host types)
# freq_ssh_pass <host_or_ip> <cmd>    Password-based SSH (bootstrap)
# freq_ssh_bg <ip> <cmd> <outfile>    Background SSH (fire-and-forget)
#
# Host type detection is automatic via resolve.sh + hosts.conf:
#   linux   → svc-admin@host via FREQ key
#   truenas → svc-admin@host via FREQ key
#   pfsense → root@host via FREQ key (FreeBSD)
#   switch  → svc-admin@host via FREQ key + legacy crypto
#   idrac   → svc-admin@host via FREQ key + restricted ciphers
#
# Dependencies: core.sh (SSH_OPTS, FREQ_KEY_PATH), resolve.sh (freq_resolve)
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# freq_ssh — Unified key-based SSH transport
# Usage: freq_ssh <host_or_ip> <command> [args...]
# ═══════════════════════════════════════════════════════════════════
freq_ssh() {
    local target="$1"; shift
    local cmd="$*"

    # Resolve target to IP + type
    local resolved ip host_type label
    resolved=$(freq_resolve "$target" 2>/dev/null)
    if [ -n "$resolved" ]; then
        ip=$(echo "$resolved" | awk '{print $1}')
        host_type=$(echo "$resolved" | awk '{print $2}')
        label=$(echo "$resolved" | awk '{print $3}')
    else
        # Fallback: treat as raw IP, assume linux
        ip="$target"
        host_type="linux"
        label="$target"
    fi

    # Protected operation override — use root SSH with live password
    if [ -n "${PROTECTED_ROOT_PASS:-}" ]; then
        SSHPASS="$PROTECTED_ROOT_PASS" sshpass -e ssh -n \
            -o StrictHostKeyChecking=no -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-5}" \
            root@"$ip" "$cmd"
        return $?
    fi

    case "$host_type" in
        pfsense)
            # pfSense: SSH as root via FREQ key
            ssh -n $SSH_OPTS root@"$ip" "$cmd"
            ;;
        switch)
            # Cisco switch: legacy crypto required
            ssh -n \
                -o KexAlgorithms=+diffie-hellman-group14-sha1 \
                -o HostKeyAlgorithms=+ssh-rsa \
                -o PubkeyAcceptedKeyTypes=+ssh-rsa \
                -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
                -o StrictHostKeyChecking=no \
                -o BatchMode=yes \
                -o ConnectTimeout=10 \
                ${FREQ_KEY_PATH:+-i "$FREQ_KEY_PATH"} \
                "${REMOTE_USER}@${ip}" "$cmd"
            ;;
        idrac)
            # iDRAC: racadm-restricted SSH
            ssh -n \
                -o KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group1-sha1 \
                -o HostKeyAlgorithms=+ssh-rsa \
                -o PubkeyAcceptedKeyTypes=+ssh-rsa \
                -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
                -o StrictHostKeyChecking=no \
                -o BatchMode=yes \
                -o ConnectTimeout=10 \
                ${FREQ_KEY_PATH:+-i "$FREQ_KEY_PATH"} \
                "${REMOTE_USER}@${ip}" "$cmd"
            ;;
        linux|truenas|*)
            # Standard SSH via FREQ key
            ssh -n $SSH_OPTS "${REMOTE_USER}@${ip}" "$cmd"
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# freq_ssh_pass — Password-based SSH (for bootstrap before keys)
# Uses export SSHPASS pattern — NEVER eval injection
# Usage: freq_ssh_pass <ip> <password> <command>
# ═══════════════════════════════════════════════════════════════════
freq_ssh_pass() {
    local ip="$1" pass="$2"; shift 2
    local cmd="$*"

    local resolved host_type
    resolved=$(freq_resolve "$ip" 2>/dev/null)
    if [ -n "$resolved" ]; then
        host_type=$(echo "$resolved" | awk '{print $2}')
    else
        host_type="linux"
    fi

    local ssh_user="$REMOTE_USER"
    [ "$host_type" = "pfsense" ] && ssh_user="root"

    export SSHPASS="$pass"
    case "$host_type" in
        switch)
            sshpass -e ssh -n \
                -o KexAlgorithms=+diffie-hellman-group14-sha1 \
                -o HostKeyAlgorithms=+ssh-rsa \
                -o PubkeyAcceptedKeyTypes=+ssh-rsa \
                -o Ciphers=+aes128-cbc,aes256-cbc,3des-cbc \
                -o StrictHostKeyChecking=no \
                -o ConnectTimeout=10 \
                "${ssh_user}@${ip}" "$cmd"
            ;;
        *)
            sshpass -e ssh -n \
                -o StrictHostKeyChecking=accept-new \
                -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-5}" \
                "${ssh_user}@${ip}" "$cmd"
            ;;
    esac
    local rc=$?
    unset SSHPASS
    return $rc
}

# ═══════════════════════════════════════════════════════════════════
# freq_ssh_bg — Background SSH (fire-and-forget, collect via file)
# Usage: freq_ssh_bg <ip> <cmd> <outfile>
# Returns: PID of background process
# ═══════════════════════════════════════════════════════════════════
freq_ssh_bg() {
    local ip="$1" cmd="$2" outfile="$3"
    freq_ssh "$ip" "$cmd" > "$outfile" 2>/dev/null &
    echo $!
}

# ═══════════════════════════════════════════════════════════════════
# PARALLEL FLEET EXECUTION
# Usage: _freq_parallel <remote_cmd> <callback_fn> <ip1> <label1> ...
# ═══════════════════════════════════════════════════════════════════
_parallel_ssh() {
    local exec_cmd="$1"
    shift
    local -a target_ips=("$@")
    local total=${#target_ips[@]}

    PARALLEL_DIR=$(mktemp -d /tmp/freq-pssh.XXXXXX)
    local running=0

    for ((i=0; i<total; i++)); do
        (
            local rc=0
            freq_ssh "${target_ips[$i]}" "$exec_cmd" > "$PARALLEL_DIR/$i.out" 2>&1 || rc=$?
            echo "$rc" > "$PARALLEL_DIR/$i.rc"
        ) &

        running=$((running+1))
        if [ $running -ge "${MAX_PARALLEL:-5}" ]; then
            wait -n 2>/dev/null || true
            running=$((running-1))
        fi
    done
    wait
}

_parallel_show() {
    local tmp_dir="$1"
    shift
    local -a names=("$@")
    local ok=0 fail=0

    for ((i=0; i<${#names[@]}; i++)); do
        local rc
        rc=$(cat "$tmp_dir/$i.rc" 2>/dev/null || echo 255)
        local output
        output=$(cat "$tmp_dir/$i.out" 2>/dev/null)

        echo -e "    ${BOLD}--- ${names[$i]} ---${RESET}"
        [ -n "$output" ] && echo "$output"
        if [ "$rc" != "0" ]; then
            echo -e "  ${RED}(exit code: $rc)${RESET}"
            fail=$((fail+1))
        else
            ok=$((ok+1))
        fi
        echo ""
    done

    rm -rf "$tmp_dir"
    PARALLEL_OK=$ok
    PARALLEL_FAIL=$fail
}

# ═══════════════════════════════════════════════════════════════════
# SSH COMMAND SANITIZER — Block dangerous patterns
# ═══════════════════════════════════════════════════════════════════
sanitize_ssh_cmd() {
    local cmd="$1"
    # Block command injection patterns
    if [[ "$cmd" == *'$('* ]] || [[ "$cmd" == *'`'* ]] || [[ "$cmd" == *'|'*'rm '* ]]; then
        die "Command contains potentially dangerous patterns. Review and try again."
    fi
}
