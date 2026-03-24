#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# PVE FREQ v1.0.0 -- lib/validate.sh
# Input validators: username, IP, label, SSH pubkey, VMID, hostname
#
# Author:  FREQ Project
# -- trust but verify --
# Dependencies: core.sh (die)
# ═══════════════════════════════════════════════════════════════════

validate_username() {
    local u="$1"
    [ -z "$u" ] && die "Username cannot be empty."
    [[ "$u" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "Invalid username: '$u'. Use lowercase, numbers, hyphens, underscores."
    [ "${#u}" -gt 32 ] && die "Username too long (max 32 chars)."
    return 0
}

validate_ip() {
    local ip="$1"
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Invalid IP address: '$ip'"
    local IFS='.'; read -ra octets <<< "$ip"
    local o; for o in "${octets[@]}"; do
        [ "$o" -gt 255 ] 2>/dev/null && die "Invalid IP address: '$ip' (octet $o > 255)"
    done
    return 0
}

validate_label() {
    local l="$1"
    [ -z "$l" ] && die "Label cannot be empty."
    [[ "$l" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || die "Invalid label: '$l'"
    return 0
}

validate_ssh_pubkey() {
    local key="$1"
    [ -z "$key" ] && die "SSH public key cannot be empty."
    local _valid_prefix="^(ssh-(rsa|ed25519)|ecdsa-sha2-nistp[0-9]+) "
    if [[ ! "$key" =~ $_valid_prefix ]]; then
        die "Invalid SSH public key format. Must start with ssh-rsa, ssh-ed25519, or ecdsa-sha2-nistp*"
    fi
    return 0
}

validate_vmid() {
    local vmid="$1"
    [[ "$vmid" =~ ^[0-9]+$ ]] || die "Invalid VMID: '$vmid'. Must be numeric."
    [ "$vmid" -lt 100 ] && die "VMID $vmid is below minimum (100)."
    [ "$vmid" -gt 999999 ] && die "VMID $vmid is above maximum (999999)."
    return 0
}

validate_hostname() {
    local h="$1"
    [ -z "$h" ] && die "Hostname cannot be empty."
    [[ "$h" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || die "Invalid hostname: '$h'"
    [ "${#h}" -gt 63 ] && die "Hostname too long (max 63 chars)."
    return 0
}
