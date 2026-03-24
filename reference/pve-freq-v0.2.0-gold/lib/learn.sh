#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v2.0.0 -- lib/learn.sh
# Institutional Knowledge Base — searchable lessons from 154+ sessions
#
# -- the memory. every scar is a lesson. every lesson is searchable. --
# Two knowledge types: Lessons (numbered, from sessions) and Gotchas
# (platform-specific traps). SQLite with FTS5 full-text search.
# Commands: cmd_learn
# Dependencies: core.sh, fmt.sh, sqlite3
# =============================================================================

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION — Database paths
# ═══════════════════════════════════════════════════════════════════
LEARN_DIR="${FREQ_DATA_DIR}/learn"
LEARN_DB="${LEARN_DIR}/knowledge.db"

# ═══════════════════════════════════════════════════════════════════
# cmd_learn — Main entry point: freq learn [subcommand] [args...]
#
# Subcommands:
#   <query>           Search all knowledge (default)
#   search <query>    Explicit search
#   import            Load seed data into the database
#   list              Show all lessons sorted by number
#   gotchas [plat]    Show gotchas, optionally filtered by platform
#   help              Show usage
# ═══════════════════════════════════════════════════════════════════
cmd_learn() {
    # Gate: sqlite3 must be available
    if ! command -v sqlite3 &>/dev/null; then
        echo -e "  ${RED}${_CROSS} sqlite3 not found.${RESET} Install: apt install sqlite3"
        return 1
    fi

    local subcmd="${1:-}"

    # No args = help
    if [[ -z "$subcmd" ]]; then
        _learn_help
        return 0
    fi

    # Route subcommand or treat as search query
    case "$subcmd" in
        search)
            shift
            if [[ -z "$*" ]]; then
                echo -e "  ${RED}Usage: freq learn search <query>${RESET}"
                return 1
            fi
            _learn_search "$@"
            ;;
        import)
            shift
            _learn_import "$@"
            ;;
        list)
            shift
            _learn_list "$@"
            ;;
        gotchas)
            shift
            _learn_gotchas "$@"
            ;;
        help|--help|-h)
            _learn_help
            ;;
        *)
            # Everything else is a search query
            _learn_search "$@"
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# _learn_ensure_db — Create database and tables if they don't exist
#
# Creates the learn directory, the SQLite database, and both
# data tables plus their FTS5 virtual tables. Safe to call
# multiple times (all CREATE statements use IF NOT EXISTS).
# ═══════════════════════════════════════════════════════════════════
_learn_ensure_db() {
    if [[ ! -d "$LEARN_DIR" ]]; then
        mkdir -p "$LEARN_DIR" 2>/dev/null
        chmod 775 "$LEARN_DIR" 2>/dev/null
    fi

    # If database exists and has tables, skip init
    if [[ -f "$LEARN_DB" ]]; then
        local tbl_count
        tbl_count=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='lessons';" 2>/dev/null)
        [[ "$tbl_count" == "1" ]] && return 0
    fi

    sqlite3 "$LEARN_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER UNIQUE NOT NULL,
    session TEXT,
    platform TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    description TEXT,
    related_commands TEXT
);

CREATE TABLE IF NOT EXISTS gotchas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    trigger_pattern TEXT,
    description TEXT NOT NULL,
    fix TEXT,
    sessions TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
    title, description, platform, related_commands,
    content='lessons', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS gotchas_fts USING fts5(
    description, fix, platform, trigger_pattern,
    content='gotchas', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS lessons_ai AFTER INSERT ON lessons BEGIN
    INSERT INTO lessons_fts(rowid, title, description, platform, related_commands)
    VALUES (new.id, new.title, new.description, new.platform, new.related_commands);
END;

CREATE TRIGGER IF NOT EXISTS lessons_ad AFTER DELETE ON lessons BEGIN
    INSERT INTO lessons_fts(lessons_fts, rowid, title, description, platform, related_commands)
    VALUES ('delete', old.id, old.title, old.description, old.platform, old.related_commands);
END;

CREATE TRIGGER IF NOT EXISTS gotchas_ai AFTER INSERT ON gotchas BEGIN
    INSERT INTO gotchas_fts(rowid, description, fix, platform, trigger_pattern)
    VALUES (new.id, new.description, new.fix, new.platform, new.trigger_pattern);
END;

CREATE TRIGGER IF NOT EXISTS gotchas_ad AFTER DELETE ON gotchas BEGIN
    INSERT INTO gotchas_fts(gotchas_fts, rowid, description, fix, platform, trigger_pattern)
    VALUES ('delete', old.id, old.description, old.fix, old.platform, old.trigger_pattern);
END;
SQL

    if [[ $? -ne 0 ]]; then
        echo -e "  ${RED}${_CROSS} Failed to initialize knowledge database${RESET}"
        return 1
    fi

    log "learn: database initialized at $LEARN_DB"
    return 0
}

# ═══════════════════════════════════════════════════════════════════
# _learn_db_has_data — Check if database has any lesson rows
# Returns: 0 if data exists, 1 if empty
# ═══════════════════════════════════════════════════════════════════
_learn_db_has_data() {
    [[ ! -f "$LEARN_DB" ]] && return 1
    local count
    count=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM lessons;" 2>/dev/null)
    [[ "${count:-0}" -gt 0 ]] && return 0
    return 1
}

# ═══════════════════════════════════════════════════════════════════
# _learn_severity_badge — Return color-coded severity badge
#
# Args: severity (critical|important|info|tip)
# Output: ANSI-colored badge string
# ═══════════════════════════════════════════════════════════════════
_learn_severity_badge() {
    local sev="${1:-info}"
    case "$sev" in
        critical)  printf "${RED}${_CROSS} CRIT${RESET}" ;;
        important) printf "${YELLOW}${_WARN} IMPT${RESET}" ;;
        info)      printf "${CYAN}${_ICO_INFO} INFO${RESET}" ;;
        tip)       printf "${GREEN}${_TICK} TIP${RESET}" ;;
        *)         printf "${DIM}${_DOT} ${sev}${RESET}" ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# _learn_platform_badge — Return color-coded platform label
#
# Args: platform name
# Output: ANSI-colored platform string
# ═══════════════════════════════════════════════════════════════════
_learn_platform_badge() {
    local plat="${1:-}"
    case "$plat" in
        pve)       printf "${PURPLE}pve${RESET}" ;;
        linux)     printf "${GREEN}linux${RESET}" ;;
        docker)    printf "${CYAN}docker${RESET}" ;;
        pfsense)   printf "${RED}pfsense${RESET}" ;;
        truenas)   printf "${BLUE}truenas${RESET}" ;;
        idrac)     printf "${ORANGE}idrac${RESET}" ;;
        network)   printf "${YELLOW}network${RESET}" ;;
        nfs)       printf "${MAGENTA}nfs${RESET}" ;;
        ssh)       printf "${PURPLELIGHT}ssh${RESET}" ;;
        *)         printf "${DIM}${plat}${RESET}" ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════
# _learn_sanitize_query — Escape query for FTS5 safety
#
# Wraps each word in double quotes for FTS5 phrase matching.
# Prevents SQL injection and FTS5 syntax errors from special chars.
# ═══════════════════════════════════════════════════════════════════
_learn_sanitize_query() {
    local raw="$*"
    # Strip characters that break FTS5: quotes, semicolons, parens
    raw="${raw//\"/}"
    raw="${raw//\'/}"
    raw="${raw//;/}"
    raw="${raw//(/}"
    raw="${raw//)/}"
    # Wrap each word in double quotes for exact token matching
    local sanitized=""
    local word
    for word in $raw; do
        [[ -z "$word" ]] && continue
        [[ -n "$sanitized" ]] && sanitized+=" "
        sanitized+="\"${word}\""
    done
    echo "$sanitized"
}

# ═══════════════════════════════════════════════════════════════════
# _learn_search — Full-text search across lessons and gotchas
#
# Searches both tables using FTS5, falling back to LIKE queries
# if FTS returns nothing. Displays results in bordered output
# with severity badges, platform labels, and descriptions.
#
# Args: query terms (all positional args joined)
# ═══════════════════════════════════════════════════════════════════
_learn_search() {
    local raw_query="$*"
    _learn_ensure_db || return 1

    if ! _learn_db_has_data; then
        freq_header "Knowledge Search"
        freq_blank
        freq_line "  ${DIM}No knowledge loaded yet.${RESET}"
        freq_line "  Run ${BOLD}freq learn import${RESET} to load the seed database."
        freq_blank
        freq_footer
        return 0
    fi

    local fts_query
    fts_query=$(_learn_sanitize_query "$raw_query")

    freq_header "Knowledge Search: ${raw_query}"
    freq_blank

    # --- Search lessons via FTS5 ---
    local lesson_results
    lesson_results=$(sqlite3 -separator '|' "$LEARN_DB" \
        "SELECT l.number, l.session, l.platform, l.severity, l.title, l.description
         FROM lessons l
         JOIN lessons_fts f ON l.id = f.rowid
         WHERE lessons_fts MATCH '${fts_query}'
         ORDER BY rank
         LIMIT 15;" 2>/dev/null)

    # Fallback to LIKE if FTS5 returned nothing
    if [[ -z "$lesson_results" ]]; then
        local like_pat="%${raw_query// /%}%"
        lesson_results=$(sqlite3 -separator '|' "$LEARN_DB" \
            "SELECT number, session, platform, severity, title, description
             FROM lessons
             WHERE title LIKE '${like_pat}' OR description LIKE '${like_pat}'
                OR platform LIKE '${like_pat}'
             ORDER BY number
             LIMIT 15;" 2>/dev/null)
    fi

    # Display lesson results
    local lesson_count=0
    if [[ -n "$lesson_results" ]]; then
        freq_divider "${BOLD}${WHITE}Lessons${RESET}"
        freq_blank

        while IFS='|' read -r l_num l_session l_platform l_severity l_title l_desc; do
            [[ -z "$l_num" ]] && continue
            lesson_count=$((lesson_count + 1))

            local sev_badge plat_badge
            sev_badge=$(_learn_severity_badge "$l_severity")
            plat_badge=$(_learn_platform_badge "$l_platform")

            freq_line "  ${BOLD}${WHITE}#${l_num}${RESET}  ${DIM}[${l_session}]${RESET}  ${plat_badge}  ${sev_badge}"
            freq_line "    ${BOLD}${l_title}${RESET}"

            # Show description truncated to fit bordered output
            if [[ -n "$l_desc" ]]; then
                freq_line "    ${DIM}${l_desc}${RESET}"
            fi
            freq_blank
        done <<< "$lesson_results"
    fi

    # --- Search gotchas via FTS5 ---
    local gotcha_results
    gotcha_results=$(sqlite3 -separator '|' "$LEARN_DB" \
        "SELECT g.platform, g.trigger_pattern, g.description, g.fix, g.sessions
         FROM gotchas g
         JOIN gotchas_fts f ON g.id = f.rowid
         WHERE gotchas_fts MATCH '${fts_query}'
         ORDER BY rank
         LIMIT 10;" 2>/dev/null)

    # Fallback to LIKE for gotchas
    if [[ -z "$gotcha_results" ]]; then
        local like_pat="%${raw_query// /%}%"
        gotcha_results=$(sqlite3 -separator '|' "$LEARN_DB" \
            "SELECT platform, trigger_pattern, description, fix, sessions
             FROM gotchas
             WHERE description LIKE '${like_pat}' OR fix LIKE '${like_pat}'
                OR platform LIKE '${like_pat}' OR trigger_pattern LIKE '${like_pat}'
             LIMIT 10;" 2>/dev/null)
    fi

    # Display gotcha results
    local gotcha_count=0
    if [[ -n "$gotcha_results" ]]; then
        freq_divider "${BOLD}${WHITE}Known Gotchas${RESET}"
        freq_blank

        while IFS='|' read -r g_plat g_trigger g_desc g_fix g_sessions; do
            [[ -z "$g_plat" ]] && continue
            gotcha_count=$((gotcha_count + 1))

            local plat_badge
            plat_badge=$(_learn_platform_badge "$g_plat")

            freq_line "  ${RED}${_WARN}${RESET} ${plat_badge}  ${DIM}trigger: ${g_trigger}${RESET}"
            freq_line "    ${g_desc}"
            if [[ -n "$g_fix" ]]; then
                freq_line "    ${GREEN}Fix:${RESET} ${g_fix}"
            fi
            if [[ -n "$g_sessions" ]]; then
                freq_line "    ${DIM}Sessions: ${g_sessions}${RESET}"
            fi
            freq_blank
        done <<< "$gotcha_results"
    fi

    # --- Related commands ---
    local related
    related=$(sqlite3 "$LEARN_DB" \
        "SELECT DISTINCT related_commands FROM lessons
         WHERE related_commands IS NOT NULL
           AND (title LIKE '%${raw_query// /%}%' OR description LIKE '%${raw_query// /%}%')
         LIMIT 5;" 2>/dev/null)

    if [[ -n "$related" ]]; then
        freq_divider "${BOLD}${WHITE}Related Commands${RESET}"
        freq_blank
        while IFS= read -r cmd_line; do
            [[ -z "$cmd_line" ]] && continue
            # Split comma-separated commands
            local IFS=','
            for rcmd in $cmd_line; do
                rcmd="${rcmd## }"
                rcmd="${rcmd%% }"
                [[ -n "$rcmd" ]] && freq_line "    ${PURPLELIGHT}${_ARROW}${RESET} ${rcmd}"
            done
        done <<< "$related"
        freq_blank
    fi

    # --- Summary ---
    local total=$((lesson_count + gotcha_count))
    if [[ $total -eq 0 ]]; then
        freq_line "  ${DIM}No results for '${raw_query}'.${RESET}"
        freq_blank
        freq_line "  ${DIM}Try broader terms or check: freq learn list${RESET}"
        freq_blank
    else
        freq_divider
        freq_line "  ${DIM}Found: ${lesson_count} lesson(s), ${gotcha_count} gotcha(s)${RESET}"
    fi

    freq_footer
    log "learn: search '${raw_query}' returned ${total} result(s)"
}

# ═══════════════════════════════════════════════════════════════════
# _learn_list — Display all lessons sorted by number
#
# Shows every lesson in the database in a compact table format
# with lesson number, session, platform badge, severity badge,
# and title.
# ═══════════════════════════════════════════════════════════════════
_learn_list() {
    _learn_ensure_db || return 1

    if ! _learn_db_has_data; then
        freq_header "Knowledge Base"
        freq_blank
        freq_line "  ${DIM}No knowledge loaded yet.${RESET}"
        freq_line "  Run ${BOLD}freq learn import${RESET} to load the seed database."
        freq_blank
        freq_footer
        return 0
    fi

    local total
    total=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM lessons;" 2>/dev/null)

    freq_header "All Lessons (${total})"
    freq_blank
    freq_line "  ${DIM}NUM   SESSION  PLATFORM   SEVERITY   TITLE${RESET}"
    freq_divider
    freq_blank

    local results
    results=$(sqlite3 -separator '|' "$LEARN_DB" \
        "SELECT number, session, platform, severity, title
         FROM lessons ORDER BY number;" 2>/dev/null)

    while IFS='|' read -r l_num l_session l_platform l_severity l_title; do
        [[ -z "$l_num" ]] && continue
        local sev_badge plat_badge

        sev_badge=$(_learn_severity_badge "$l_severity")
        plat_badge=$(_learn_platform_badge "$l_platform")

        # Right-pad the number for alignment
        local num_pad
        printf -v num_pad '%-5s' "#${l_num}"

        freq_line "  ${BOLD}${WHITE}${num_pad}${RESET} ${DIM}${l_session}${RESET}  ${plat_badge}  ${sev_badge}  ${l_title}"
    done <<< "$results"

    freq_blank
    freq_divider
    freq_line "  ${DIM}${total} lessons from DC01 operational history${RESET}"
    freq_footer
    log "learn: listed ${total} lessons"
}

# ═══════════════════════════════════════════════════════════════════
# _learn_gotchas — Show known platform gotchas
#
# Displays all gotchas or filters by platform name. Each gotcha
# shows its trigger pattern, description, fix procedure, and
# related sessions.
#
# Args: [platform] — optional filter (pfsense, truenas, docker, etc.)
# ═══════════════════════════════════════════════════════════════════
_learn_gotchas() {
    local platform="${1:-}"
    _learn_ensure_db || return 1

    local total
    total=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM gotchas;" 2>/dev/null)

    if [[ "${total:-0}" -eq 0 ]]; then
        freq_header "Known Gotchas"
        freq_blank
        freq_line "  ${DIM}No gotchas loaded yet.${RESET}"
        freq_line "  Run ${BOLD}freq learn import${RESET} to load the seed database."
        freq_blank
        freq_footer
        return 0
    fi

    local query results header_title

    if [[ -n "$platform" ]]; then
        # Sanitize platform input
        platform="${platform//\'/}"
        platform="${platform//;/}"
        query="SELECT platform, trigger_pattern, description, fix, sessions FROM gotchas WHERE platform = '${platform}' ORDER BY id;"
        header_title="Gotchas: ${platform}"
        total=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM gotchas WHERE platform = '${platform}';" 2>/dev/null)
    else
        query="SELECT platform, trigger_pattern, description, fix, sessions FROM gotchas ORDER BY platform, id;"
        header_title="All Known Gotchas"
    fi

    freq_header "${header_title}"
    freq_blank

    results=$(sqlite3 -separator '|' "$LEARN_DB" "$query" 2>/dev/null)

    if [[ -z "$results" ]]; then
        freq_line "  ${DIM}No gotchas for platform '${platform}'.${RESET}"
        freq_blank

        # Show available platforms
        local platforms
        platforms=$(sqlite3 "$LEARN_DB" "SELECT DISTINCT platform FROM gotchas ORDER BY platform;" 2>/dev/null)
        if [[ -n "$platforms" ]]; then
            freq_line "  ${DIM}Available platforms:${RESET}"
            while IFS= read -r p; do
                [[ -n "$p" ]] && freq_line "    ${_BULLET} ${p}"
            done <<< "$platforms"
            freq_blank
        fi
    else
        local current_plat=""
        while IFS='|' read -r g_plat g_trigger g_desc g_fix g_sessions; do
            [[ -z "$g_plat" ]] && continue

            # Platform section header (when showing all)
            if [[ -z "$platform" && "$g_plat" != "$current_plat" ]]; then
                [[ -n "$current_plat" ]] && freq_blank
                local plat_badge
                plat_badge=$(_learn_platform_badge "$g_plat")
                freq_divider "${plat_badge}"
                freq_blank
                current_plat="$g_plat"
            fi

            freq_line "  ${RED}${_WARN}${RESET} ${BOLD}${g_desc}${RESET}"
            [[ -n "$g_trigger" ]] && freq_line "    ${DIM}Trigger: ${g_trigger}${RESET}"
            [[ -n "$g_fix" ]]     && freq_line "    ${GREEN}Fix:${RESET} ${g_fix}"
            [[ -n "$g_sessions" ]] && freq_line "    ${DIM}Sessions: ${g_sessions}${RESET}"
            freq_blank
        done <<< "$results"

        freq_divider
        freq_line "  ${DIM}${total} gotcha(s) shown${RESET}"
    fi

    freq_footer
    log "learn: listed gotchas${platform:+ for ${platform}}"
}

# ═══════════════════════════════════════════════════════════════════
# _learn_help — Show usage and examples
# ═══════════════════════════════════════════════════════════════════
_learn_help() {
    freq_header "Learn ${_DASH} Searchable Knowledge Base"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq learn <command|query>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    <query>               ${DIM}${_DASH} Search all knowledge (default)${RESET}"
    freq_line "    search <query>        ${DIM}${_DASH} Explicit full-text search${RESET}"
    freq_line "    import                ${DIM}${_DASH} Load seed data into database${RESET}"
    freq_line "    list                  ${DIM}${_DASH} Show all lessons by number${RESET}"
    freq_line "    gotchas [platform]    ${DIM}${_DASH} Show platform gotchas${RESET}"
    freq_line "    help                  ${DIM}${_DASH} This help${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Examples:${RESET}"
    freq_line "    freq learn NFS stale         ${DIM}${_DASH} Find NFS lessons${RESET}"
    freq_line "    freq learn iDRAC password     ${DIM}${_DASH} iDRAC credential gotchas${RESET}"
    freq_line "    freq learn LACP               ${DIM}${_DASH} Network bonding traps${RESET}"
    freq_line "    freq learn Docker SQLite       ${DIM}${_DASH} Container storage lessons${RESET}"
    freq_line "    freq learn gotchas pfsense     ${DIM}${_DASH} pfSense-specific traps${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Platforms:${RESET} pve, linux, docker, pfsense, truenas, idrac, network, nfs, ssh"
    freq_blank

    if _learn_db_has_data 2>/dev/null; then
        local lcount gcount
        lcount=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM lessons;" 2>/dev/null)
        gcount=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM gotchas;" 2>/dev/null)
        freq_line "  ${DIM}Database: ${lcount} lessons, ${gcount} gotchas loaded${RESET}"
    else
        freq_line "  ${DIM}Database: not initialized. Run 'freq learn import' first.${RESET}"
    fi

    freq_footer
}

# ═══════════════════════════════════════════════════════════════════
# _learn_import — Load all seed knowledge into the database
#
# Imports lessons from DC01 operational history (154+ sessions)
# and known platform gotchas. Safe to re-run — uses INSERT OR
# IGNORE to skip duplicates on the UNIQUE number constraint.
# ═══════════════════════════════════════════════════════════════════
_learn_import() {
    _learn_ensure_db || return 1

    freq_header "Knowledge Import"
    freq_blank

    # Count before
    local before_lessons before_gotchas
    before_lessons=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM lessons;" 2>/dev/null || echo 0)
    before_gotchas=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM gotchas;" 2>/dev/null || echo 0)

    freq_line "  ${DIM}Loading lessons from DC01 operational history...${RESET}"
    freq_blank

    # ---------------------------------------------------------------
    # LESSONS — Numbered knowledge from 154+ sessions
    # Each row: (number, session, platform, severity, title, description, related_commands)
    # ---------------------------------------------------------------
    sqlite3 "$LEARN_DB" <<'SQL'
INSERT OR IGNORE INTO lessons (number, session, platform, severity, title, description, related_commands) VALUES
-- Original 7 from prototype
(3, 'S012', 'nfs', 'critical', 'NFS fstab must have _netdev,nofail', 'Without _netdev, mount tries before network is up. Without nofail, mount failure blocks boot entirely. Add soft,timeo=150,retrans=3,bg for resilience.', 'freq mount'),
(6, 'S031', 'docker', 'critical', 'SQLite cannot run on NFS', 'Bazarr/Plex SQLite DBs enter D-state on NFS during network glitches. All service configs MUST be on local disk. NFS only for media.', 'freq mount,freq docker'),
(13, 'S017', 'pve', 'critical', 'Use vmbr0vXXXX not vmbr0.XXXX on Proxmox', 'Dot notation creates kernel sub-interface that conflicts with bridge. VLAN bridge notation works at bridge level above physical NIC.', 'freq configure'),
(95, 'S066', 'idrac', 'important', 'iDRAC 7 vs 8 different SSH ciphers', 'iDRAC 7 requires deprecated ciphers (diffie-hellman-group14-sha1, ssh-rsa). iDRAC 8 uses standard SSH. Both accept same racadm syntax.', 'freq idrac'),
(124, 'S073', 'truenas', 'critical', 'TrueNAS sudoers: middleware DB only', 'sudoers.d files get wiped on firmware update. Use midclt call user.update to set sudo commands permanently in middleware DB.', 'freq truenas'),
(127, 'S075', 'idrac', 'important', 'iDRAC rejects Ed25519 SSH keys', 'Only RSA keys accepted. Deploy via racadm sshpkauth. Use RSA-4096 for iDRAC, Ed25519 everywhere else.', 'freq idrac,freq keys'),
(128, 'S076', 'idrac', 'important', 'iDRAC password complexity requires special chars', 'racadm set Password rejects alphanumeric-only (RAC947). Must include uppercase+lowercase+digit+special char.', 'freq idrac,freq vault'),

-- NFS knowledge
(1, 'S005', 'nfs', 'critical', 'NFS stale handles require remount', 'Stale NFS handles (ESTALE errno 116) survive indefinitely. Only fix is lazy umount then remount. Processes with open FDs must be killed first.', 'freq mount'),
(4, 'S014', 'nfs', 'important', 'NFS v4.1 with multipath for HA', 'NFSv4.1 supports session trunking. Use multiple paths via /etc/nfs.conf clientaddr settings. Failover is automatic if configured.', 'freq mount,freq truenas'),
(5, 'S020', 'nfs', 'critical', 'NFS mount ordering vs systemd dependencies', 'systemd auto-generates mount units from fstab. Docker containers starting before NFS is ready get empty bind mounts. Use RequiresMountsFor in service unit.', 'freq mount,freq docker'),

-- Docker knowledge
(7, 'S033', 'docker', 'critical', 'Docker bridge network IP exhaustion', 'Default docker0 bridge uses 172.17.0.0/16. With many containers, subnet exhaustion causes no-IP failures. Define custom bridge networks with smaller subnets.', 'freq docker'),
(8, 'S035', 'docker', 'important', 'Docker compose down removes named volumes if --volumes used', 'docker compose down --volumes destroys named volumes with all data. Never use --volumes in production. Use docker compose down (no flags) then prune selectively.', 'freq docker'),
(9, 'S041', 'docker', 'critical', 'Gluetun VPN container must own all ports', 'qBit/FlareSolverr ports go on Gluetun container, NOT on the service containers. network_mode: service:gluetun on qBit. All ports on gluetun service definition.', 'freq docker'),
(10, 'S044', 'docker', 'important', 'Docker DNS resolution fails with custom networks', 'Containers on custom bridge networks need explicit DNS (dns: 10.25.25.1 in compose). Default Docker DNS only resolves container names, not LAN hostnames.', 'freq docker'),

-- PVE / Proxmox knowledge
(14, 'S018', 'pve', 'critical', 'PVE cluster quorum requires 3 nodes minimum', 'Two-node PVE cluster loses quorum when one node fails. Always deploy 3+ nodes or configure expected_votes=1 for two-node operation with fencing.', 'freq status'),
(15, 'S019', 'pve', 'important', 'PVE VM config lives in /etc/pve which is FUSE', '/etc/pve is a pmxcfs FUSE mount backed by SQLite in corosync. Direct edits risky. Always use qm set or pvesh to modify VM configs safely.', 'freq vmconfig'),
(16, 'S022', 'pve', 'important', 'PVE backup vzdump must target non-NFS for SQLite VMs', 'vzdump streaming to NFS causes SQLite lock contention in the backup snapshot. Use local storage for vzdump tmp, then move to NFS after completion.', 'freq backup'),
(17, 'S024', 'pve', 'critical', 'PVE yescrypt hashes break SSH authentication', 'PVE uses yescrypt ($y$) by default which breaks SSH key-based auth fallback. Use chpasswd -c SHA512 for $6$ hashes on all provisioned VMs.', 'freq provision,freq users'),
(18, 'S082', 'pve', 'important', 'PVE VM IDs must not overlap across clusters', 'When migrating VMs between clusters, ID collisions cause silent failures. Reserve ID ranges per cluster: 100-399 prod, 400-699 lab, 800-899 vault.', 'freq create,freq clone'),

-- pfSense knowledge
(20, 'S032', 'pfsense', 'critical', 'pfSense reboot wipes SSH config and sudoers', 'pfSense firmware updates wipe /etc/sshd and sudoers. Backup sshd_config and verify SSH access after every update. Sudoers must be re-applied.', 'freq pfsense'),
(21, 'S045', 'pfsense', 'important', 'pfSense VLAN rules must be on VLAN interface not parent', 'Firewall rules on the parent interface do not apply to VLAN-tagged traffic. Rules must be created on each VLAN interface individually.', 'freq pfsense'),
(22, 'S047', 'pfsense', 'important', 'pfSense NAT outbound needs manual mode for VPN split', 'Automatic outbound NAT sends all traffic out WAN. For split-tunnel VPN, switch to Manual Outbound NAT and create explicit rules per subnet.', 'freq pfsense,freq vpn'),
(23, 'S053', 'pfsense', 'tip', 'pfSense tcsh shell breaks stderr redirection in SSH', '2>/dev/null inside SSH command strings breaks tcsh parsing. Redirect stderr OUTSIDE the SSH string: ssh fw "command" 2>/dev/null.', 'freq pfsense'),

-- Networking knowledge
(30, 'S032', 'network', 'critical', 'LACP transition errdisables switch ports', 'LACP bond reconfiguration during reboot can errdisable switch ports. Pre-configure switch channel-group before host. Set errdisable recovery interval 30.', 'freq switch'),
(31, 'S036', 'network', 'important', 'MTU mismatch causes silent packet drops', 'Jumbo frames (9000) on storage VLAN but 1500 on switch causes fragmentation and drops. MTU must match end-to-end: NIC, switch port, VLAN, NFS server.', 'freq switch,freq mount'),
(32, 'S038', 'network', 'important', 'VLAN trunk pruning must allow all needed VLANs', 'Switch trunk ports default to allow all VLANs. Manual pruning that forgets a VLAN silently drops that traffic. Always verify: show int trunk.', 'freq switch'),
(33, 'S050', 'network', 'tip', 'ARP table timeout mismatch causes intermittent drops', 'Linux ARP timeout (30s default) vs switch (14400s) vs firewall (7200s) causes reachability gaps. Standardize ARP timers across all layers.', 'freq health'),

-- SSH knowledge
(40, 'S055', 'ssh', 'critical', 'SSH host key verification fails after VM rebuild', 'Rebuilding a VM keeps the same IP but generates new host keys. Old key in known_hosts causes MITM warning. Use ssh-keygen -R to remove stale entry.', 'freq ssh,freq provision'),
(41, 'S058', 'ssh', 'important', 'SSH agent forwarding leaks credentials', 'ForwardAgent yes exposes the SSH agent socket on the remote host. Any root user on that host can use your keys. Never enable on untrusted hosts.', 'freq ssh'),
(42, 'S060', 'ssh', 'important', 'SSH connection multiplexing saves 10x on fleet ops', 'ControlMaster auto with ControlPath and ControlPersist 600 reuses SSH connections. Fleet-wide exec goes from 30s to 3s for 10-host operations.', 'freq ssh,freq exec'),

-- TrueNAS knowledge
(50, 'S070', 'truenas', 'critical', 'TrueNAS REST API deprecated in 25.10', 'REST API deprecated in TrueNAS 25.10, removed in 26.04. Use midclt call via SSH for all automation. websocket API is the only supported path.', 'freq truenas'),
(51, 'S072', 'truenas', 'important', 'TrueNAS ZFS scrub should run monthly not weekly', 'Weekly scrubs on large pools cause excessive I/O that impacts NFS serving. Monthly scrubs with email alerts are sufficient for home/lab use.', 'freq truenas,freq zfs'),
(52, 'S074', 'truenas', 'important', 'TrueNAS dataset permissions recursive changes are slow', 'Recursive chmod/chown on datasets with millions of files can take hours and locks SMB/NFS. Set permissions at dataset creation. Use ACL inheritance.', 'freq truenas'),

-- Linux general
(60, 'S025', 'linux', 'important', 'systemd service restart limits prevent boot loops', 'StartLimitIntervalSec and StartLimitBurst in systemd prevent a crashing service from consuming resources. Set sane limits on all custom units.', 'freq provision'),
(61, 'S028', 'linux', 'critical', 'apt unattended-upgrades can reboot without warning', 'Default unattended-upgrades config may auto-reboot. Set Unattended-Upgrade::Automatic-Reboot to false in /etc/apt/apt.conf.d/50unattended-upgrades.', 'freq harden'),
(62, 'S029', 'linux', 'important', 'journald logs consume disk until configured', 'Without SystemMaxUse in /etc/systemd/journald.conf, journal grows unbounded. Set SystemMaxUse=500M and SystemMaxFiles=5 on all VMs.', 'freq harden,freq provision');
SQL

    local lesson_rc=$?

    # ---------------------------------------------------------------
    # GOTCHAS — Platform-specific traps and their fixes
    # ---------------------------------------------------------------
    sqlite3 "$LEARN_DB" <<'SQL'
INSERT OR IGNORE INTO gotchas (platform, trigger_pattern, description, fix, sessions) VALUES
-- Original 5 from prototype
('pfsense', 'reboot', 'pfSense firmware updates wipe /etc/sshd and sudoers. Verify SSH config after any update.', 'Re-apply sshd_config from backup. Verify sudo works.', 'S054,S062'),
('pfsense', 'LACP', 'LACP transition during reboot can errdisable switch ports. Must pre-configure switch before host.', 'Switch: errdisable recovery 30. Pre-enable channel-group.', 'S032,S035'),
('truenas', 'REST API', 'REST API deprecated in TrueNAS 25.10, removed in 26.04. Use midclt via SSH instead.', 'Replace _tn_api() with _tn_midclt() in truenas.sh', 'S078'),
('docker', 'gluetun', 'qBit/FlareSolverr ports go on Gluetun container, NOT on the service containers.', 'network_mode: service:gluetun on qBit. All ports on gluetun service.', 'S057'),
('pve', 'yescrypt', 'PVE uses yescrypt ($y$) by default which breaks SSH. Use chpasswd -c SHA512 for $6$ hashes.', 'chpasswd -c SHA512 <<< "user:password"', 'S077'),

-- Additional gotchas from operational history
('nfs', 'stale handle', 'NFS stale file handle (errno 116) blocks all I/O on that mount. Processes hang in D-state uninterruptible sleep.', 'Kill processes with open FDs: fuser -km /mount. Lazy umount: umount -l. Remount fresh.', 'S005,S014'),
('nfs', 'fstab boot', 'Missing _netdev in fstab causes NFS mount attempt before network is up. Boot hangs for 90s on each mount.', 'Add _netdev,nofail,soft,timeo=150,retrans=3,bg to all NFS fstab entries.', 'S012'),
('docker', 'bind mount empty', 'Docker bind mount to NFS path shows empty if NFS not mounted yet. Container starts with empty config directory.', 'Use RequiresMountsFor=/mnt/nfs in docker service unit. Or healthcheck that verifies mount.', 'S020,S031'),
('docker', 'compose restart', 'docker compose restart does not pick up env file changes. Must use down+up to reload environment variables.', 'docker compose down && docker compose up -d. Never use restart for config changes.', 'S041'),
('pve', 'pmxcfs lock', '/etc/pve FUSE mount locks during cluster partition. VMs cannot be modified until quorum restored.', 'Fix quorum first: pvecm expected 1 (dangerous). Better: maintain 3-node cluster.', 'S019'),
('pve', 'VM template', 'Cannot modify a VM template directly. Must clone first, modify clone, then convert back to template.', 'qm clone VMID NEWID --full. Modify NEWID. qm template NEWID. Remove old template.', 'S022,S024'),
('ssh', 'host key changed', 'VM rebuild with same IP triggers MITM warning. SSH refuses connection until old host key removed.', 'ssh-keygen -R <ip>. Or use StrictHostKeyChecking=accept-new for fleet automation.', 'S055'),
('network', 'MTU path', 'Jumbo frames (MTU 9000) on only part of the path causes silent drops. TCP MSS clamping masks the issue for small packets.', 'Verify MTU end-to-end: ip link show on every hop. Match MTU on NIC, switch port, VLAN, and NFS server.', 'S036'),
('linux', 'unattended reboot', 'apt unattended-upgrades defaults to Automatic-Reboot "true" on some distros. Server reboots unexpectedly after security update.', 'Set Unattended-Upgrade::Automatic-Reboot "false" in 50unattended-upgrades.', 'S028'),
('truenas', 'sudoers wipe', 'TrueNAS firmware updates wipe /usr/local/etc/sudoers.d/. Custom sudo rules disappear after update.', 'Use midclt call user.update to set sudo in middleware DB. Permanent across updates.', 'S073'),
('pfsense', '2>/dev/null', 'tcsh (pfSense default shell) cannot parse bash-style 2>/dev/null inside SSH strings. Command fails silently.', 'Redirect stderr OUTSIDE the SSH command: ssh fw "cmd" 2>/dev/null — not inside quotes.', 'S053'),
('idrac', 'Ed25519 key', 'iDRAC firmware (all versions) rejects Ed25519 SSH keys. Only RSA keys work for racadm SSH access.', 'Generate RSA-4096 key specifically for iDRAC. Deploy via racadm sshpkauth.', 'S075,S076');
SQL

    local gotcha_rc=$?

    # Count after
    local after_lessons after_gotchas
    after_lessons=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM lessons;" 2>/dev/null || echo 0)
    after_gotchas=$(sqlite3 "$LEARN_DB" "SELECT count(*) FROM gotchas;" 2>/dev/null || echo 0)

    local new_lessons=$((after_lessons - before_lessons))
    local new_gotchas=$((after_gotchas - before_gotchas))

    # Report results
    if [[ $lesson_rc -eq 0 && $gotcha_rc -eq 0 ]]; then
        freq_line "  ${GREEN}${_TICK}${RESET}  Lessons:  ${new_lessons} new, ${after_lessons} total"
        freq_line "  ${GREEN}${_TICK}${RESET}  Gotchas:  ${new_gotchas} new, ${after_gotchas} total"
    else
        freq_line "  ${YELLOW}${_WARN}${RESET}  Import completed with warnings"
        freq_line "       ${DIM}Lessons: ${after_lessons}, Gotchas: ${after_gotchas}${RESET}"
    fi

    freq_blank

    # Show platform breakdown
    freq_divider "${BOLD}${WHITE}Coverage by Platform${RESET}"
    freq_blank

    local plat_stats
    plat_stats=$(sqlite3 -separator '|' "$LEARN_DB" \
        "SELECT platform, count(*) FROM lessons GROUP BY platform ORDER BY count(*) DESC;" 2>/dev/null)

    while IFS='|' read -r p_name p_count; do
        [[ -z "$p_name" ]] && continue
        local plat_badge
        plat_badge=$(_learn_platform_badge "$p_name")
        freq_line "    ${plat_badge}  ${p_count} lessons"
    done <<< "$plat_stats"

    freq_blank
    freq_footer

    log "learn: imported ${new_lessons} lessons, ${new_gotchas} gotchas (total: ${after_lessons}L/${after_gotchas}G)"
}

# ═══════════════════════════════════════════════════════════════════
# _learn_auto_surface — Hook for other commands to show related tips
#
# Called by other FREQ commands (freq mount, freq docker, etc.)
# to automatically surface relevant lessons when a related
# command is executed. Shows up to 3 tips in dimmed text.
#
# Args: command — the freq command being run (e.g., "freq mount")
# Returns: nothing (display only, never fails)
# ═══════════════════════════════════════════════════════════════════
_learn_auto_surface() {
    local command="${1:-}"
    [[ -z "$command" ]] && return
    [[ ! -f "$LEARN_DB" ]] && return

    # Sanitize command for SQL
    command="${command//\'/}"
    command="${command//;/}"

    local tips
    tips=$(sqlite3 -separator '|' "$LEARN_DB" \
        "SELECT number, severity, title FROM lessons
         WHERE related_commands LIKE '%${command}%'
         ORDER BY
           CASE severity
             WHEN 'critical' THEN 1
             WHEN 'important' THEN 2
             WHEN 'info' THEN 3
             WHEN 'tip' THEN 4
             ELSE 5
           END
         LIMIT 3;" 2>/dev/null)

    [[ -z "$tips" ]] && return

    echo ""
    echo -e "  ${DIM}${_ICO_INFO} Related knowledge:${RESET}"
    while IFS='|' read -r t_num t_sev t_title; do
        [[ -z "$t_num" ]] && continue
        local sev_indicator
        case "$t_sev" in
            critical)  sev_indicator="${RED}${_BULLET}${RESET}" ;;
            important) sev_indicator="${YELLOW}${_BULLET}${RESET}" ;;
            *)         sev_indicator="${DIM}${_BULLET}${RESET}" ;;
        esac
        echo -e "  ${DIM}  ${sev_indicator} #${t_num}: ${t_title}${RESET}"
    done <<< "$tips"
}
