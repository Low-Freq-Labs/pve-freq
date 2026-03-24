#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/images.sh
# Cloud Image Management — download, verify, manage distro images
#
# -- every VM starts from an image --
# Commands: cmd_images
# Dependencies: core.sh, fmt.sh
# =============================================================================

IMAGES_DIR="${FREQ_DATA_DIR}/images"
DISTROS_FILE="${FREQ_DIR}/conf/distros.conf"

cmd_images() {
    local subcmd="${1:-list}"
    shift 2>/dev/null || true

    case "$subcmd" in
        list)      _images_list ;;
        download)  _images_download "$@" ;;
        delete)    _images_delete "$@" ;;
        verify)    _images_verify "$@" ;;
        distros)   _images_distros ;;
        help|--help|-h) _images_help ;;
        *)
            echo -e "  ${RED}Unknown images command: ${subcmd}${RESET}"
            echo "  Run 'freq images help' for usage."
            return 1
            ;;
    esac
}

_images_help() {
    freq_header "Cloud Image Management"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq images <command>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    list            ${DIM}${_DASH} Show downloaded images${RESET}"
    freq_line "    download <name> ${DIM}${_DASH} Download a cloud image${RESET}"
    freq_line "    delete <file>   ${DIM}${_DASH} Remove a downloaded image${RESET}"
    freq_line "    verify [file]   ${DIM}${_DASH} Verify image checksums${RESET}"
    freq_line "    distros         ${DIM}${_DASH} Show available distro definitions${RESET}"
    freq_blank
    freq_footer
}

_images_list() {
    freq_header "Downloaded Images"
    freq_blank

    mkdir -p "$IMAGES_DIR" 2>/dev/null

    local count=0
    local img
    for img in "${IMAGES_DIR}"/*.{img,qcow2,iso,raw} "${IMAGES_DIR}"/*.{img,qcow2,iso,raw}.gz; do
        [ ! -f "$img" ] && continue
        local name size mtime
        name=$(basename "$img")
        size=$(du -h "$img" 2>/dev/null | awk '{print $1}')
        mtime=$(stat -c '%Y' "$img" 2>/dev/null)
        local age_days=$(( ($(date +%s) - ${mtime:-0}) / 86400 ))
        freq_line "  ${BOLD}${name}${RESET}  ${DIM}${size}  ${age_days}d old${RESET}"
        count=$((count + 1))
    done

    [ "$count" -eq 0 ] && freq_line "  ${DIM}No images found in ${IMAGES_DIR}${RESET}"
    freq_blank
    freq_line "  ${DIM}Total: ${count} images${RESET}"
    freq_footer
}

_images_download() {
    require_operator || return 1
    local name="${1:-}"
    [ -z "$name" ] && { echo -e "  ${RED}Usage: freq images download <distro-name|url>${RESET}"; return 1; }

    mkdir -p "$IMAGES_DIR" 2>/dev/null

    # Check if name is a URL
    local url="" filename=""
    if [[ "$name" == http* ]]; then
        url="$name"
        filename=$(basename "$url")
    elif [ -f "$DISTROS_FILE" ]; then
        # Look up in distros.conf: format "name url checksum"
        local match
        match=$(grep -v '^#' "$DISTROS_FILE" 2>/dev/null | grep -i "^${name} " | head -1)
        if [ -n "$match" ]; then
            url=$(echo "$match" | awk '{print $2}')
            filename=$(basename "$url")
        else
            echo -e "  ${RED}Unknown distro '${name}'. Run 'freq images distros' for available options.${RESET}"
            return 1
        fi
    else
        echo -e "  ${RED}No distros.conf found and '${name}' is not a URL.${RESET}"
        return 1
    fi

    local dest="${IMAGES_DIR}/${filename}"
    if [ -f "$dest" ]; then
        echo -e "  ${YELLOW}${_WARN}${RESET} Image already exists: ${filename}"
        _freq_confirm "Re-download and overwrite?" || return 0
    fi

    freq_header "Download Image"
    freq_blank
    freq_line "  Source: ${DIM}${url}${RESET}"
    freq_line "  Dest:   ${DIM}${dest}${RESET}"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would download ${filename}"
        freq_footer
        return 0
    fi

    _step_start "Downloading ${filename}"
    if curl -fSL --connect-timeout 15 --max-time 600 --progress-bar -o "$dest" "$url" 2>/dev/null; then
        local size
        size=$(du -h "$dest" 2>/dev/null | awk '{print $1}')
        _step_ok "${size}"
    else
        _step_fail "download failed"
        rm -f "$dest" 2>/dev/null
        freq_footer
        return 1
    fi

    freq_blank
    freq_footer
    log "images: downloaded ${filename} from ${url}"
}

_images_delete() {
    require_operator || return 1
    local target="${1:-}"
    [ -z "$target" ] && { echo -e "  ${RED}Usage: freq images delete <filename>${RESET}"; return 1; }

    local filepath="${IMAGES_DIR}/${target}"
    if [ ! -f "$filepath" ]; then
        echo -e "  ${RED}Image not found: ${target}${RESET}"
        return 1
    fi

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would delete: ${target}"
        return 0
    fi

    _freq_confirm "Delete image: ${target}?" || return 0

    rm -f "$filepath"
    echo -e "  ${GREEN}${_TICK}${RESET} Deleted: ${target}"
    log "images: deleted ${target}"
}

_images_verify() {
    local target="${1:-}"

    freq_header "Image Verification"
    freq_blank

    local files=()
    if [ -n "$target" ]; then
        local fp="${IMAGES_DIR}/${target}"
        [ ! -f "$fp" ] && { echo -e "  ${RED}Image not found: ${target}${RESET}"; return 1; }
        files=("$fp")
    else
        for img in "${IMAGES_DIR}"/*.{img,qcow2,iso,raw}; do
            [ -f "$img" ] && files+=("$img")
        done
    fi

    if [ ${#files[@]} -eq 0 ]; then
        freq_line "  ${DIM}No images to verify.${RESET}"
        freq_footer
        return 0
    fi

    local img
    for img in "${files[@]}"; do
        local name sha256
        name=$(basename "$img")
        _step_start "Verify: ${name}"
        sha256=$(sha256sum "$img" 2>/dev/null | awk '{print $1}')
        if [ -n "$sha256" ]; then
            _step_ok "${sha256:0:16}..."
            # Check against distros.conf checksum
            if [ -f "$DISTROS_FILE" ]; then
                local expected
                expected=$(grep -v '^#' "$DISTROS_FILE" 2>/dev/null | grep "$(basename "$img")" | awk '{print $3}')
                if [ -n "$expected" ] && [ "$sha256" != "$expected" ]; then
                    freq_line "    ${RED}${_CROSS} Checksum MISMATCH${RESET}"
                elif [ -n "$expected" ]; then
                    freq_line "    ${GREEN}${_TICK} Checksum verified${RESET}"
                fi
            fi
        else
            _step_fail "hash failed"
        fi
    done

    freq_blank
    freq_footer
}

_images_distros() {
    freq_header "Available Distros"
    freq_blank

    if [ ! -f "$DISTROS_FILE" ]; then
        freq_line "  ${DIM}No distros.conf found at ${DISTROS_FILE}${RESET}"
        freq_line "  ${DIM}Format: <name> <url> [sha256]${RESET}"
        freq_footer
        return 0
    fi

    while IFS= read -r line; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        local name url _
        read -r name url _ <<< "$line"
        freq_line "  ${BOLD}${name}${RESET}  ${DIM}${url}${RESET}"
    done < "$DISTROS_FILE"

    freq_blank
    freq_footer
}
