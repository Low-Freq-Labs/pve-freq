#!/bin/bash
# shellcheck disable=SC2154
# =============================================================================
# PVE FREQ v1.0.0 -- lib/configure.sh
# Post-Install Host Configuration — SSH, hostname, timezone, packages
#
# -- making a house a home --
# Commands: cmd_configure, cmd_packages
# Dependencies: core.sh, fmt.sh, ssh.sh, resolve.sh
# =============================================================================

cmd_configure() {
    local subcmd="${1:-help}"
    shift 2>/dev/null || true

    case "$subcmd" in
        ssh)       _configure_ssh "$@" ;;
        hostname)  _configure_hostname "$@" ;;
        timezone)  _configure_timezone "$@" ;;
        network)   _configure_network_detect "$@" ;;
        all)       _configure_all "$@" ;;
        help|--help|-h) _configure_help ;;
        *)
            echo -e "  ${RED}Unknown configure command: ${subcmd}${RESET}"
            echo "  Run 'freq configure help' for usage."
            return 1
            ;;
    esac
}

cmd_packages() {
    local subcmd="${1:-list}"
    shift 2>/dev/null || true

    case "$subcmd" in
        install)  _packages_install "$@" ;;
        list)     _packages_list "$@" ;;
        update)   _packages_update "$@" ;;
        help|--help|-h) _packages_help ;;
        *)
            echo -e "  ${RED}Unknown packages command: ${subcmd}${RESET}"
            return 1
            ;;
    esac
}

_configure_help() {
    freq_header "Host Configuration"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq configure <command> <host>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    ssh <host>       ${DIM}${_DASH} Harden SSH config${RESET}"
    freq_line "    hostname <host> <name> ${DIM}${_DASH} Set hostname${RESET}"
    freq_line "    timezone <host> [tz]   ${DIM}${_DASH} Set timezone (default: UTC)${RESET}"
    freq_line "    network <host>   ${DIM}${_DASH} Detect network config style${RESET}"
    freq_line "    all <host>       ${DIM}${_DASH} Run all post-install config${RESET}"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Related:${RESET} freq packages <install|list|update> <host>"
    freq_blank
    freq_footer
}

_packages_help() {
    freq_header "Package Management"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Usage:${RESET} freq packages <command> <host>"
    freq_blank
    freq_line "  ${BOLD}${WHITE}Commands:${RESET}"
    freq_line "    install <host> <pkg...> ${DIM}${_DASH} Install packages on host${RESET}"
    freq_line "    list <host>             ${DIM}${_DASH} List installed packages${RESET}"
    freq_line "    update <host>           ${DIM}${_DASH} Update all packages${RESET}"
    freq_blank
    freq_footer
}

_detect_pkg_manager() {
    local host="$1"
    local pm
    pm=$(freq_ssh "$host" '
        if command -v apt-get &>/dev/null; then echo "apt"
        elif command -v dnf &>/dev/null; then echo "dnf"
        elif command -v yum &>/dev/null; then echo "yum"
        elif command -v apk &>/dev/null; then echo "apk"
        elif command -v pkg &>/dev/null; then echo "pkg"
        else echo "unknown"; fi
    ' 2>/dev/null)
    echo "${pm:-unknown}"
}

_detect_network_style() {
    local host="$1"
    local style
    style=$(freq_ssh "$host" '
        if [ -d /etc/netplan ] && ls /etc/netplan/*.yaml &>/dev/null; then echo "netplan"
        elif command -v nmcli &>/dev/null && systemctl is-active NetworkManager &>/dev/null; then echo "networkmanager"
        elif [ -f /etc/network/interfaces ]; then echo "eni"
        elif [ -d /etc/sysconfig/network-scripts ]; then echo "sysconfig"
        elif [ -d /etc/systemd/network ] && ls /etc/systemd/network/*.network &>/dev/null; then echo "systemd-networkd"
        else echo "unknown"; fi
    ' 2>/dev/null)
    echo "${style:-unknown}"
}

_configure_ssh() {
    require_admin || return 1
    require_ssh_key

    local host="${1:-}"
    [ -z "$host" ] && { echo -e "  ${RED}Usage: freq configure ssh <host>${RESET}"; return 1; }

    freq_header "SSH Hardening ${_DASH} ${host}"
    freq_blank

    if [ "$DRY_RUN" = "true" ]; then
        freq_line "  ${CYAN}[DRY-RUN]${RESET} Would harden SSH on ${host}"
        freq_footer
        return 0
    fi

    _step_start "Disable root password login"
    if freq_ssh "$host" "sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config" 2>/dev/null; then
        _step_ok
    else
        _step_fail
    fi

    _step_start "Disable password auth"
    if freq_ssh "$host" "sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config" 2>/dev/null; then
        _step_ok
    else
        _step_fail
    fi

    _step_start "Set SSH idle timeout (15min)"
    freq_ssh "$host" "sudo bash -c 'grep -q ClientAliveInterval /etc/ssh/sshd_config && sudo sed -i \"s/^#*ClientAliveInterval.*/ClientAliveInterval 900/\" /etc/ssh/sshd_config || echo \"ClientAliveInterval 900\" | sudo tee -a /etc/ssh/sshd_config >/dev/null'" 2>/dev/null
    _step_ok

    _step_start "Restart sshd"
    if freq_ssh "$host" "sudo systemctl restart sshd 2>/dev/null || sudo systemctl restart ssh 2>/dev/null" 2>/dev/null; then
        _step_ok
    else
        _step_warn "restart may have failed"
    fi

    freq_blank
    freq_footer
    log "configure: ssh hardened on ${host}"
}

_configure_hostname() {
    require_admin || return 1
    require_ssh_key

    local host="${1:-}" newname="${2:-}"
    [ -z "$host" ] || [ -z "$newname" ] && { echo -e "  ${RED}Usage: freq configure hostname <host> <new-name>${RESET}"; return 1; }

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would set hostname to '${newname}' on ${host}"
        return 0
    fi

    _step_start "Set hostname to ${newname}"
    if freq_ssh "$host" "sudo hostnamectl set-hostname '${newname}'" 2>/dev/null; then
        _step_ok
    else
        _step_fail
    fi
    log "configure: hostname set to ${newname} on ${host}"
}

_configure_timezone() {
    require_admin || return 1
    require_ssh_key

    local host="${1:-}" tz="${2:-UTC}"
    [ -z "$host" ] && { echo -e "  ${RED}Usage: freq configure timezone <host> [timezone]${RESET}"; return 1; }

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would set timezone to '${tz}' on ${host}"
        return 0
    fi

    _step_start "Set timezone to ${tz}"
    if freq_ssh "$host" "sudo timedatectl set-timezone '${tz}'" 2>/dev/null; then
        _step_ok
    else
        _step_fail
    fi
    log "configure: timezone set to ${tz} on ${host}"
}

_configure_network_detect() {
    require_operator || return 1
    require_ssh_key

    local host="${1:-}"
    [ -z "$host" ] && { echo -e "  ${RED}Usage: freq configure network <host>${RESET}"; return 1; }

    freq_header "Network Config ${_DASH} ${host}"
    freq_blank

    local style
    style=$(_detect_network_style "$host")
    freq_line "  Network management: ${BOLD}${style}${RESET}"

    case "$style" in
        netplan)
            freq_line "  ${DIM}Config: /etc/netplan/*.yaml${RESET}"
            local configs
            configs=$(freq_ssh "$host" "ls /etc/netplan/*.yaml 2>/dev/null" 2>/dev/null)
            [ -n "$configs" ] && freq_line "  Files: ${DIM}${configs}${RESET}"
            ;;
        networkmanager)
            freq_line "  ${DIM}Config: nmcli / NetworkManager${RESET}"
            ;;
        eni)
            freq_line "  ${DIM}Config: /etc/network/interfaces${RESET}"
            ;;
        sysconfig)
            freq_line "  ${DIM}Config: /etc/sysconfig/network-scripts/${RESET}"
            ;;
        *)
            freq_line "  ${YELLOW}${_WARN}${RESET} Unknown network style"
            ;;
    esac

    freq_blank
    freq_footer
}

_configure_all() {
    require_admin || return 1
    require_ssh_key

    local host="${1:-}"
    [ -z "$host" ] && { echo -e "  ${RED}Usage: freq configure all <host>${RESET}"; return 1; }

    freq_header "Full Post-Install Config ${_DASH} ${host}"
    freq_blank

    _configure_ssh "$host"
    _configure_timezone "$host" "America/New_York"

    # Install baseline packages
    local pm
    pm=$(_detect_pkg_manager "$host")
    if [ "$pm" = "apt" ]; then
        _step_start "Install baseline packages"
        if [ "$DRY_RUN" = "true" ]; then
            _step_ok "dry-run"
        else
            freq_ssh "$host" "sudo apt-get update -qq && sudo apt-get install -y -qq qemu-guest-agent curl wget htop vim sudo" 2>/dev/null
            _step_ok
        fi
    fi

    freq_blank
    freq_footer
    log "configure: full post-install on ${host}"
}

_packages_install() {
    require_admin || return 1
    require_ssh_key

    local host="${1:-}"; shift 2>/dev/null || true
    local pkgs="$*"
    [ -z "$host" ] || [ -z "$pkgs" ] && { echo -e "  ${RED}Usage: freq packages install <host> <pkg1> [pkg2...]${RESET}"; return 1; }

    local pm
    pm=$(_detect_pkg_manager "$host")

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would install on ${host} (${pm}): ${pkgs}"
        return 0
    fi

    _step_start "Install: ${pkgs} (${pm})"
    local install_cmd
    case "$pm" in
        apt)  install_cmd="sudo apt-get install -y -qq ${pkgs}" ;;
        dnf)  install_cmd="sudo dnf install -y ${pkgs}" ;;
        yum)  install_cmd="sudo yum install -y ${pkgs}" ;;
        apk)  install_cmd="sudo apk add ${pkgs}" ;;
        pkg)  install_cmd="sudo pkg install -y ${pkgs}" ;;
        *)    _step_fail "unknown package manager: ${pm}"; return 1 ;;
    esac
    if freq_ssh "$host" "$install_cmd" 2>/dev/null; then
        _step_ok
    else
        _step_fail
    fi
    log "configure: installed '${pkgs}' on ${host} via ${pm}"
}

_packages_list() {
    require_operator || return 1
    require_ssh_key

    local host="${1:-}"
    [ -z "$host" ] && { echo -e "  ${RED}Usage: freq packages list <host>${RESET}"; return 1; }

    local pm
    pm=$(_detect_pkg_manager "$host")

    local list_cmd
    case "$pm" in
        apt)  list_cmd="dpkg -l | tail -n+6 | wc -l" ;;
        dnf|yum) list_cmd="rpm -qa | wc -l" ;;
        apk)  list_cmd="apk list --installed 2>/dev/null | wc -l" ;;
        *)    list_cmd="echo unknown" ;;
    esac

    local count
    count=$(freq_ssh "$host" "$list_cmd" 2>/dev/null)
    echo -e "  ${host} (${pm}): ${BOLD}${count:-?}${RESET} packages installed"
}

_packages_update() {
    require_admin || return 1
    require_ssh_key

    local host="${1:-}"
    [ -z "$host" ] && { echo -e "  ${RED}Usage: freq packages update <host>${RESET}"; return 1; }

    local pm
    pm=$(_detect_pkg_manager "$host")

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "  ${CYAN}[DRY-RUN]${RESET} Would update all packages on ${host} (${pm})"
        return 0
    fi

    _step_start "Update packages on ${host} (${pm})"
    local update_cmd
    case "$pm" in
        apt)  update_cmd="sudo apt-get update -qq && sudo apt-get upgrade -y -qq" ;;
        dnf)  update_cmd="sudo dnf upgrade -y" ;;
        yum)  update_cmd="sudo yum update -y" ;;
        apk)  update_cmd="sudo apk upgrade" ;;
        *)    _step_fail "unknown pm: ${pm}"; return 1 ;;
    esac
    if freq_ssh "$host" "$update_cmd" 2>/dev/null; then
        _step_ok
    else
        _step_fail
    fi
    log "configure: packages updated on ${host} via ${pm}"
}
