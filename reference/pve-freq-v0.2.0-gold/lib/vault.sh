#!/bin/bash
# =============================================================================
# PVE FREQ v1.0.0 -- lib/vault.sh
# Encrypted Credential Vault (AES-256-CBC)
#
# -- the lockbox. credentials in, credentials out, nothing in between. --
#
# Key derived from /etc/machine-id (unique per host, stable across reboots)
# Dependencies: core.sh, fmt.sh, openssl
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# _vault_key — Derive encryption key from machine-id
# ═══════════════════════════════════════════════════════════════════
_vault_key() {
    local machine_id=""
    if [ -f /etc/machine-id ]; then
        machine_id=$(cat /etc/machine-id)
    elif [ -f /var/lib/dbus/machine-id ]; then
        machine_id=$(cat /var/lib/dbus/machine-id)
    else
        die "No machine-id found — cannot derive vault key"
    fi
    echo -n "$machine_id" | openssl dgst -sha256 -r | cut -d' ' -f1
}

vault_init() {
    [ "$(id -u)" -ne 0 ] && die "vault_init requires root"
    command -v openssl >/dev/null 2>&1 || die "openssl not found — required for vault"

    [ -d "$VAULT_DIR" ] || mkdir -p "$VAULT_DIR"
    chmod 700 "$VAULT_DIR"
    chown root:root "$VAULT_DIR"

    if [ -f "$VAULT_FILE" ]; then
        log "vault: already exists at $VAULT_FILE"
        return 0
    fi

    echo "# FREQ Vault -- created $(date -u +%Y-%m-%dT%H:%M:%SZ)" | \
        openssl enc -aes-256-cbc -salt -pbkdf2 -pass "pass:$(_vault_key)" -out "$VAULT_FILE" 2>/dev/null
    chmod 600 "$VAULT_FILE"
    log "vault: initialized at $VAULT_FILE (AES-256-CBC)"
}

# ═══════════════════════════════════════════════════════════════════
# _vault_decrypt / _vault_encrypt — Internal helpers
# ═══════════════════════════════════════════════════════════════════
_vault_decrypt() {
    [ ! -f "$VAULT_FILE" ] && return 0
    openssl enc -aes-256-cbc -d -salt -pbkdf2 -pass "pass:$(_vault_key)" -in "$VAULT_FILE" 2>/dev/null
}

_vault_encrypt() {
    local tmpfile
    tmpfile=$(mktemp "${VAULT_DIR}/.vault-tmp.XXXXXX")
    chmod 600 "$tmpfile"
    cat > "$tmpfile"
    openssl enc -aes-256-cbc -salt -pbkdf2 -pass "pass:$(_vault_key)" -in "$tmpfile" -out "${VAULT_FILE}.new" 2>/dev/null
    rm -f "$tmpfile"
    mv -f "${VAULT_FILE}.new" "$VAULT_FILE"
    chmod 600 "$VAULT_FILE"
}

# ═══════════════════════════════════════════════════════════════════
# vault_set <host> <key> <value> — Store encrypted credential
# ═══════════════════════════════════════════════════════════════════
vault_set() {
    if [ $# -lt 3 ]; then
        echo "Usage: freq vault set <host> <key> <value>"
        return 1
    fi
    local host="$1" key="$2" value="$3"
    [ "$(id -u)" -ne 0 ] && die "vault_set requires root"

    [ ! -f "$VAULT_FILE" ] && vault_init

    {
        _vault_decrypt | grep -v "^${host}|${key}|"
        echo "${host}|${key}|${value}"
    } | sort | _vault_encrypt

    log "vault: set ${key} for ${host}"
}

# ═══════════════════════════════════════════════════════════════════
# vault_get <host> <key> — Retrieve credential (stdout)
# Falls back to DEFAULT if host-specific entry not found
# ═══════════════════════════════════════════════════════════════════
vault_get() {
    if [ $# -lt 2 ]; then
        echo "Usage: freq vault get <host> <key>"
        return 1
    fi
    local host="$1" key="$2"
    [ "$(id -u)" -ne 0 ] && die "vault_get requires root"

    local result
    result=$(_vault_decrypt | grep "^${host}|${key}|" | head -1 | cut -d'|' -f3-)
    if [ -z "$result" ]; then
        result=$(_vault_decrypt | grep "^DEFAULT|${key}|" | head -1 | cut -d'|' -f3-)
    fi
    [ -n "$result" ] && echo "$result"
}

# ═══════════════════════════════════════════════════════════════════
# vault_delete <host> <key> — Remove a credential entry
# ═══════════════════════════════════════════════════════════════════
vault_delete() {
    if [ $# -lt 2 ]; then
        echo "Usage: freq vault delete <host> <key>"
        return 1
    fi
    local host="$1" key="$2"
    [ "$(id -u)" -ne 0 ] && die "vault_delete requires root"

    _vault_decrypt | grep -v "^${host}|${key}|" | _vault_encrypt
    log "vault: deleted ${key} for ${host}"
}

# ═══════════════════════════════════════════════════════════════════
# vault_list — Show all hosts with stored creds (values masked)
# ═══════════════════════════════════════════════════════════════════
vault_list() {
    [ "$(id -u)" -ne 0 ] && die "vault_list requires root"

    if [ ! -f "$VAULT_FILE" ]; then
        echo "No vault found. Run: freq vault init"
        return 1
    fi

    local entries
    entries=$(_vault_decrypt | grep -v "^#" | grep -v "^$")
    if [ -z "$entries" ]; then
        echo "Vault is empty."
        return 0
    fi

    printf "%-20s %-20s %s\n" "HOST" "KEY" "VALUE"
    printf "%-20s %-20s %s\n" "----" "---" "-----"
    echo "$entries" | while IFS='|' read -r host key value; do
        case "$key" in
            *pass*) masked="********" ;;
            ssh-key) masked="$value" ;;
            *)       masked="[set]" ;;
        esac
        printf "%-20s %-20s %s\n" "$host" "$key" "$masked"
    done
}

# ═══════════════════════════════════════════════════════════════════
# vault_import_legacy — Import from legacy data files
# ═══════════════════════════════════════════════════════════════════
vault_import_legacy() {
    [ "$(id -u)" -ne 0 ] && die "vault_import_legacy requires root"

    local imported=0

    if [ -f "${FREQ_DATA_DIR}/svc-pass" ]; then
        local pass
        pass=$(cat "${FREQ_DATA_DIR}/svc-pass" 2>/dev/null)
        if [ -n "$pass" ]; then
            vault_set "DEFAULT" "${FREQ_SERVICE_ACCOUNT}-pass" "$pass"
            echo "${_TICK} Imported $FREQ_SERVICE_ACCOUNT password as DEFAULT"
            imported=$((imported + 1))
        fi
    fi

    if [ -f "${FREQ_DATA_DIR}/root-pass" ]; then
        local rpass
        rpass=$(cat "${FREQ_DATA_DIR}/root-pass" 2>/dev/null)
        if [ -n "$rpass" ]; then
            vault_set "DEFAULT" "root-pass" "$rpass"
            echo "${_TICK} Imported root password as DEFAULT"
            imported=$((imported + 1))
        fi
    fi

    if [ -n "${FREQ_SSH_KEY:-}" ] && [ -f "$FREQ_SSH_KEY" ]; then
        vault_set "DEFAULT" "ssh-key" "$FREQ_SSH_KEY"
        echo "${_TICK} Set FREQ SSH key as DEFAULT"
        imported=$((imported + 1))
    fi

    echo ""
    echo "Imported $imported entries. Run 'freq vault list' to verify."
}

# ═══════════════════════════════════════════════════════════════════
# vault_get_credential — Operator-safe credential lookup
# Tries: vault (via sudo) -> file fallback -> returns empty
# This is the ONLY function other libs should call for credentials.
# ═══════════════════════════════════════════════════════════════════
vault_get_credential() {
    local host="${1:-DEFAULT}" key="${2:?Usage: vault_get_credential <host> <key>}"
    local result=""

    if [ "$(id -u)" -eq 0 ]; then
        result=$(vault_get "$host" "$key" 2>/dev/null)
    elif [ -f "$VAULT_FILE" ]; then
        result=$(sudo -n openssl enc -aes-256-cbc -d -salt -pbkdf2 \
            -pass "pass:$(sudo -n cat /etc/machine-id | openssl dgst -sha256 -r | cut -d' ' -f1)" \
            -in "$VAULT_FILE" 2>/dev/null | grep "^${host}|${key}|" | head -1 | cut -d'|' -f3-)
        if [ -z "$result" ]; then
            result=$(sudo -n openssl enc -aes-256-cbc -d -salt -pbkdf2 \
                -pass "pass:$(sudo -n cat /etc/machine-id | openssl dgst -sha256 -r | cut -d' ' -f1)" \
                -in "$VAULT_FILE" 2>/dev/null | grep "^DEFAULT|${key}|" | head -1 | cut -d'|' -f3-)
        fi
    fi

    # Fall back to legacy file paths
    if [ -z "$result" ]; then
        case "$key" in
            "${FREQ_SERVICE_ACCOUNT}-pass") [ -f "${FREQ_DATA_DIR}/svc-pass" ] && result=$(cat "${FREQ_DATA_DIR}/svc-pass" 2>/dev/null) ;;
            root-pass) [ -f "${FREQ_DATA_DIR}/root-pass" ] && result=$(cat "${FREQ_DATA_DIR}/root-pass" 2>/dev/null) ;;
            ssh-key)   [ -n "${FREQ_KEY_PATH:-}" ] && [ -f "$FREQ_KEY_PATH" ] && result="$FREQ_KEY_PATH" ;;
        esac
    fi

    [ -n "$result" ] && echo "$result"
}

# ═══════════════════════════════════════════════════════════════════
# vault_get_or_prompt — Get from vault or ask user interactively
# ═══════════════════════════════════════════════════════════════════
VAULT_CREDENTIAL=""
vault_get_or_prompt() {
    local host="${1:-DEFAULT}" key="${2:?}" prompt_text="${3:-Password}"
    VAULT_CREDENTIAL=""

    VAULT_CREDENTIAL=$(vault_get_credential "$host" "$key")
    if [ -n "$VAULT_CREDENTIAL" ]; then
        echo -e "    ${DIM}${_DOT} Credential loaded from vault ($key for $host)${RESET}"
        return 0
    fi

    read -rsp "    $prompt_text: " VAULT_CREDENTIAL; echo
    [ -z "$VAULT_CREDENTIAL" ] && return 1

    if [ "$(id -u)" -eq 0 ] && [ -f "$VAULT_FILE" ]; then
        read -rp "    Save to vault for future use? [Y/n]: " _save
        if [[ ! "$_save" =~ ^[nN] ]]; then
            vault_set "$host" "$key" "$VAULT_CREDENTIAL"
            echo -e "    ${GREEN}${_TICK}${RESET} Saved to vault"
        fi
    fi
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# vault_store_if_root — Silent store if running as root
# ═══════════════════════════════════════════════════════════════════
vault_store_if_root() {
    local host="$1" key="$2" value="$3"
    if [ "$(id -u)" -eq 0 ] && [ -f "$VAULT_FILE" ]; then
        vault_set "$host" "$key" "$value" 2>/dev/null
    fi
}

# ═══════════════════════════════════════════════════════════════════
# vault_migrate_gpg — One-time migration from GPG vault
# ═══════════════════════════════════════════════════════════════════
vault_migrate_gpg() {
    [ "$(id -u)" -ne 0 ] && die "vault_migrate_gpg requires root"
    local gpg_file="${VAULT_DIR}/freq-vault.gpg"

    if [ ! -f "$gpg_file" ]; then
        echo "No GPG vault found at $gpg_file — nothing to migrate."
        return 0
    fi
    if [ -f "$VAULT_FILE" ]; then
        echo "AES vault already exists. Skipping migration."
        return 0
    fi

    echo "Migrating GPG vault to AES-256-CBC..."
    local plaintext
    plaintext=$(gpg --batch --yes --quiet -d "$gpg_file" 2>/dev/null)
    if [ -z "$plaintext" ]; then
        echo "WARNING: Could not decrypt GPG vault (missing key?). Migration skipped."
        return 1
    fi

    echo "$plaintext" | openssl enc -aes-256-cbc -salt -pbkdf2 \
        -pass "pass:$(_vault_key)" -out "$VAULT_FILE" 2>/dev/null
    chmod 600 "$VAULT_FILE"

    mv "$gpg_file" "${gpg_file}.migrated-$(date +%Y%m%d)"
    echo "${_TICK} Migrated to AES-256-CBC vault. Old GPG vault backed up."
    log "vault: migrated from GPG to AES-256-CBC"
}

# ═══════════════════════════════════════════════════════════════════
# cmd_vault — Vault CLI dispatcher
# ═══════════════════════════════════════════════════════════════════
cmd_vault() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        init)           vault_init ;;
        set)            require_admin || return 1; vault_set "$@" ;;
        get)
            local result
            result=$(vault_get "$@")
            [ -n "$result" ] && echo "$result" || { echo "Not found."; return 1; }
            ;;
        delete)         vault_delete "$@" ;;
        list)           vault_list ;;
        import-legacy)  vault_import_legacy ;;
        migrate-gpg)    vault_migrate_gpg ;;
        *)
            echo "Usage: freq vault {init|set|get|delete|list|import-legacy|migrate-gpg}"
            echo ""
            echo "  init                         Create empty vault (AES-256-CBC)"
            echo "  set <host> <key> <value>     Store credential"
            echo "  get <host> <key>             Retrieve credential"
            echo "  delete <host> <key>          Remove credential"
            echo "  list                         Show stored creds (masked)"
            echo "  import-legacy                Import from ${FREQ_DATA_DIR}/*"
            echo "  migrate-gpg                  Migrate old GPG vault to AES-256-CBC"
            ;;
    esac
}
