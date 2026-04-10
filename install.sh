#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# PVE FREQ Installer
#
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/Low-Freq-Labs/pve-freq/main/install.sh | sudo bash
#
# Manual:
#   sudo bash install.sh --from-local /path/to/source
#
# Uninstall:
#   sudo bash install.sh --uninstall
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Version: read from freq/__init__.py if available, else fallback
_detect_version() {
    local init_py
    for init_py in "./freq/__init__.py" "${FREQ_DIR:-/opt/pve-freq}/freq/__init__.py"; do
        if [[ -f "$init_py" ]]; then
            grep -oP '__version__\s*=\s*"\K[^"]+' "$init_py" 2>/dev/null && return
        fi
    done
    echo "1.0.0"  # fallback — keep in sync with freq/__init__.py
}
FREQ_VERSION="${FREQ_VERSION:-$(_detect_version)}"
INSTALL_DIR="${FREQ_DIR:-/opt/pve-freq}"
REPO_URL="https://github.com/Low-Freq-Labs/pve-freq"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
MIN_DISK_MB=50

# FREQ brand colors
C_PURPLE='\033[38;5;93m'
C_GREEN='\033[38;5;82m'
C_RED='\033[38;5;196m'
C_YELLOW='\033[38;5;220m'
C_CYAN='\033[38;5;87m'
C_GRAY='\033[38;5;245m'
C_BOLD='\033[1m'
C_RESET='\033[0m'

# ── Flags ──────────────────────────────────────────────────────────────────

MODE="install"
SOURCE=""
SKIP_DOCTOR=false
YES=false
WITH_SYSTEMD=false

usage() {
    echo -e "${C_PURPLE}${C_BOLD}PVE FREQ Installer v${FREQ_VERSION}${C_RESET}"
    echo ""
    echo "Usage: install.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --from-local <path>  Install from local source directory"
    echo "  --from-git           Clone from GitHub"
    echo "  --dir <path>         Custom install directory (default: /opt/pve-freq)"
    echo "  --skip-doctor        Skip post-install verification"
    echo "  --with-systemd       Install systemd unit for freq serve"
    echo "  --uninstall          Remove FREQ from this host"
    echo "  --yes, -y            Non-interactive (no confirmations)"
    echo "  --help               Show this help"
    echo "  --version            Show version"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-local)
            MODE="local"
            SOURCE="${2:?'--from-local requires a path'}"
            shift 2
            ;;
        --from-git)
            MODE="git"
            shift
            ;;
        --dir)
            INSTALL_DIR="${2:?'--dir requires a path'}"
            shift 2
            ;;
        --skip-doctor)
            SKIP_DOCTOR=true
            shift
            ;;
        --with-systemd)
            WITH_SYSTEMD=true
            shift
            ;;
        --uninstall)
            MODE="uninstall"
            shift
            ;;
        --yes|-y)
            YES=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        --version)
            echo "PVE FREQ installer v${FREQ_VERSION}"
            exit 0
            ;;
        *)
            echo -e "${C_RED}Unknown option: $1${C_RESET}"
            echo "Run install.sh --help for usage"
            exit 1
            ;;
    esac
done

# ── Output helpers ─────────────────────────────────────────────────────────

ok()   { echo -e "  ${C_GREEN}[OK]${C_RESET}   $1"; }
fail() { echo -e "  ${C_RED}[FAIL]${C_RESET} $1"; }
warn() { echo -e "  ${C_YELLOW}[WARN]${C_RESET} $1"; }
info() { echo -e "  ${C_CYAN}[INFO]${C_RESET} $1"; }
step() { echo -e "  ${C_PURPLE}>>>${C_RESET}   $1"; }

banner() {
    echo ""
    local title="PVE FREQ v${FREQ_VERSION} Installer"
    local width=42
    local pad=$(( (width - ${#title}) / 2 ))
    local lpad=$(printf '%*s' "$pad" '')
    local rpad=$(printf '%*s' "$((width - ${#title} - pad))" '')
    echo -e "${C_PURPLE}${C_BOLD}╔$(printf '═%.0s' $(seq 1 $width))╗${C_RESET}"
    echo -e "${C_PURPLE}${C_BOLD}║${lpad}${title}${rpad}║${C_RESET}"
    echo -e "${C_PURPLE}${C_BOLD}╚$(printf '═%.0s' $(seq 1 $width))╝${C_RESET}"
    echo ""
}

# ── Pre-flight checks ─────────────────────────────────────────────────────

preflight() {
    local errors=0

    echo -e "${C_BOLD}Pre-flight checks${C_RESET}"
    echo ""

    # 1. Root check
    if [[ $EUID -eq 0 ]]; then
        ok "Running as root"
    else
        fail "Must run as root (use sudo)"
        exit 1
    fi

    # 2. OS detection
    local distro="" version="" family="" pretty=""
    if [[ -f /etc/os-release ]]; then
        distro=$(grep '^ID=' /etc/os-release | cut -d= -f2 | tr -d '"')
        version=$(grep '^VERSION_ID=' /etc/os-release | cut -d= -f2 | tr -d '"')
        pretty=$(grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2 | tr -d '"')

        case "$distro" in
            debian|ubuntu)           family="debian" ;;
            rhel|rocky|almalinux|centos|fedora) family="rhel" ;;
            *suse*)                  family="suse" ;;
            *)                       family="unknown" ;;
        esac

        if [[ "$family" == "unknown" ]]; then
            warn "OS: ${pretty:-$distro} (untested — proceeding anyway)"
        else
            ok "OS: ${pretty:-$distro $version}"
        fi
    else
        warn "OS: cannot detect (/etc/os-release missing)"
    fi

    # 3. Python version
    local python_bin=""
    for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python39; do
        if command -v "$candidate" &>/dev/null; then
            python_bin="$candidate"
            break
        fi
    done

    if [[ -z "$python_bin" ]]; then
        fail "Python 3 not found"
        case "$family" in
            debian) echo -e "       ${C_GRAY}Fix: apt install python3${C_RESET}" ;;
            rhel)   echo -e "       ${C_GRAY}Fix: dnf install python39${C_RESET}" ;;
            suse)   echo -e "       ${C_GRAY}Fix: zypper install python39${C_RESET}" ;;
            *)      echo -e "       ${C_GRAY}Fix: install Python 3.11+ for your distro${C_RESET}" ;;
        esac
        errors=$((errors + 1))
    else
        local py_ver
        py_ver=$("$python_bin" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null)
        local py_major py_minor
        py_major=$("$python_bin" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        py_minor=$("$python_bin" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)

        if [[ "$py_major" -ge $MIN_PYTHON_MAJOR ]] && [[ "$py_minor" -ge $MIN_PYTHON_MINOR ]]; then
            ok "Python ${py_ver} (${python_bin})"
        else
            fail "Python ${py_ver} — need >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}"
            case "$family" in
                debian) echo -e "       ${C_GRAY}Fix: apt install python3${C_RESET}" ;;
                rhel)   echo -e "       ${C_GRAY}Fix: dnf install python39${C_RESET}" ;;
                suse)   echo -e "       ${C_GRAY}Fix: zypper install python39${C_RESET}" ;;
            esac
            errors=$((errors + 1))
        fi
    fi

    # 4. Disk space
    local target_parent
    target_parent=$(dirname "$INSTALL_DIR")
    if [[ -d "$target_parent" ]]; then
        local free_mb
        free_mb=$(df -m "$target_parent" | awk 'NR==2 {print $4}')
        if [[ "$free_mb" -ge $MIN_DISK_MB ]]; then
            ok "Disk: ${free_mb}MB free at ${target_parent}"
        else
            fail "Disk: only ${free_mb}MB free at ${target_parent} (need ${MIN_DISK_MB}MB)"
            errors=$((errors + 1))
        fi
    else
        warn "Disk: ${target_parent} does not exist (will create)"
    fi

    # 5. Required binaries
    local missing_req=()
    for bin in ssh ssh-keygen; do
        if ! command -v "$bin" &>/dev/null; then
            missing_req+=("$bin")
        fi
    done

    if [[ ${#missing_req[@]} -gt 0 ]]; then
        fail "Missing required: ${missing_req[*]}"
        echo -e "       ${C_GRAY}Fix: apt install openssh-client${C_RESET}"
        errors=$((errors + 1))
    else
        ok "Required tools: ssh, ssh-keygen"
    fi

    # 6. Optional binaries
    local missing_opt=()
    for bin in sshpass curl jq; do
        if ! command -v "$bin" &>/dev/null; then
            missing_opt+=("$bin")
        fi
    done

    if [[ ${#missing_opt[@]} -gt 0 ]]; then
        warn "Optional tools missing: ${missing_opt[*]}"
        if [[ " ${missing_opt[*]} " == *" sshpass "* ]]; then
            echo -e "       ${C_GRAY}sshpass is needed for 'freq init' (password-based SSH deployment)${C_RESET}"
        fi
    else
        ok "Optional tools: sshpass, curl, jq"
    fi

    # 7. Existing installation
    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ -d "$INSTALL_DIR/.git" ]]; then
            info "Existing install detected (git clone) — will upgrade"
        elif [[ -f "$INSTALL_DIR/.install-method" ]]; then
            local method
            method=$(cat "$INSTALL_DIR/.install-method")
            info "Existing install detected (${method}) — will upgrade"
        else
            info "Existing install detected — will upgrade"
        fi
    fi

    echo ""

    if [[ $errors -gt 0 ]]; then
        echo -e "${C_RED}Pre-flight failed: ${errors} issue(s) must be fixed first.${C_RESET}"
        exit 1
    fi

    ok "Pre-flight passed"
    echo ""
}

# ── Install ────────────────────────────────────────────────────────────────

do_install() {
    echo -e "${C_BOLD}Installing PVE FREQ v${FREQ_VERSION}${C_RESET}"
    echo ""

    # Get files into INSTALL_DIR
    case "$MODE" in
        local)
            step "Copying from ${SOURCE}"
            if [[ ! -f "$SOURCE/freq/__init__.py" ]]; then
                fail "Not a FREQ source directory: ${SOURCE}"
                exit 1
            fi
            mkdir -p "$INSTALL_DIR"
            # Copy source — exclude dev artifacts
            rsync -a --delete \
                --exclude='.git' \
                --exclude='__pycache__' \
                --exclude='*.pyc' \
                --exclude='.pytest_cache' \
                --exclude='*.egg-info' \
                --exclude='data/vault/*' \
                --exclude='data/keys/*' \
                --exclude='memory/' \
                --exclude='resume-state.md' \
                --exclude='CLAUDE.md' \
                --exclude='cold-storage/' \
                --exclude='skills/' \
                --exclude='planning/' \
                --exclude='reference/' \
                --exclude='archive/' \
                "$SOURCE/" "$INSTALL_DIR/"
            echo "local" > "$INSTALL_DIR/.install-method"
            ok "Source copied to ${INSTALL_DIR}"
            ;;
        git)
            step "Cloning from ${REPO_URL}"
            if [[ -d "$INSTALL_DIR/.git" ]]; then
                git -C "$INSTALL_DIR" pull --ff-only
                ok "Updated existing git clone"
            else
                git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
                ok "Cloned to ${INSTALL_DIR}"
            fi
            echo "git-release" > "$INSTALL_DIR/.install-method"
            ;;
        install)
            # Default: download release tarball
            if ! command -v curl &>/dev/null; then
                fail "curl is required for tarball download"
                echo -e "       ${C_GRAY}Fix: apt install curl  OR  use --from-git / --from-local${C_RESET}"
                exit 1
            fi
            local tarball_url="${REPO_URL}/releases/download/v${FREQ_VERSION}/pve-freq-${FREQ_VERSION}.tar.gz"
            local checksum_url="${tarball_url}.sha256"
            local tmpdir
            tmpdir=$(mktemp -d)
            trap "rm -rf '$tmpdir'" EXIT

            step "Downloading PVE FREQ v${FREQ_VERSION}"
            if ! curl -fsSL -o "$tmpdir/pve-freq.tar.gz" "$tarball_url"; then
                fail "Download failed. Check your internet connection."
                echo -e "       ${C_GRAY}URL: ${tarball_url}${C_RESET}"
                echo -e "       ${C_GRAY}Alternative: install.sh --from-git${C_RESET}"
                exit 1
            fi
            ok "Downloaded"

            # Verify checksum if available
            if curl -fsSL -o "$tmpdir/pve-freq.tar.gz.sha256" "$checksum_url" 2>/dev/null; then
                step "Verifying checksum"
                cd "$tmpdir"
                if sha256sum -c pve-freq.tar.gz.sha256 &>/dev/null; then
                    ok "SHA256 verified"
                else
                    fail "Checksum mismatch — download may be corrupted"
                    exit 1
                fi
                cd - >/dev/null
            else
                warn "Checksum file not available — skipping verification"
            fi

            step "Extracting"
            mkdir -p "$INSTALL_DIR"
            tar xzf "$tmpdir/pve-freq.tar.gz" -C "$INSTALL_DIR" --strip-components=1
            echo "tarball" > "$INSTALL_DIR/.install-method"
            ok "Extracted to ${INSTALL_DIR}"
            ;;
    esac

    echo ""

    # Create data directories
    step "Setting up data directories"
    mkdir -p "$INSTALL_DIR/data/log"
    mkdir -p "$INSTALL_DIR/data/vault"
    mkdir -p "$INSTALL_DIR/data/keys"
    mkdir -p "$INSTALL_DIR/data/cache"
    mkdir -p "$INSTALL_DIR/data/knowledge"
    chmod 700 "$INSTALL_DIR/data/vault"
    chmod 700 "$INSTALL_DIR/data/keys"
    # Make data dirs writable by the user who runs freq (not just root)
    local freq_user="${SUDO_USER:-$(whoami)}"
    if [[ -n "$freq_user" && "$freq_user" != "root" ]]; then
        chown -R "$freq_user" "$INSTALL_DIR/data"
    fi
    ok "Data directories created"

    # Seed config files from examples (idempotent — never overwrite existing)
    step "Seeding configuration"
    local seeded=0
    for example in "$INSTALL_DIR"/conf/*.example; do
        [[ -f "$example" ]] || continue
        local active="${example%.example}"
        if [[ ! -f "$active" ]]; then
            cp "$example" "$active"
            seeded=$((seeded + 1))
        fi
    done

    # Seed personality packs from package data
    local pkg_personality="$INSTALL_DIR/freq/data/conf-templates/personality"
    local conf_personality="$INSTALL_DIR/conf/personality"
    if [[ -d "$pkg_personality" && ! -d "$conf_personality" ]]; then
        mkdir -p "$conf_personality"
        cp "$pkg_personality"/*.toml "$conf_personality/" 2>/dev/null
        seeded=$((seeded + 1))
    fi

    if [[ $seeded -gt 0 ]]; then
        ok "Created ${seeded} config file(s) from examples"
    else
        ok "Config files already exist"
    fi

    echo ""

    # Set up entry point
    step "Setting up 'freq' command"
    local freq_ready=false

    # Strategy A: pip install (preferred)
    if command -v pip3 &>/dev/null; then
        if pip3 install --no-deps --root-user-action=ignore -q "$INSTALL_DIR" 2>/dev/null; then
            if command -v freq &>/dev/null; then
                ok "Installed via pip ($(which freq))"
                freq_ready=true
            fi
        fi
    fi

    # Strategy B: python3 -m pip
    if [[ "$freq_ready" == false ]] && command -v python3 &>/dev/null; then
        if python3 -m pip install --no-deps --root-user-action=ignore -q "$INSTALL_DIR" 2>/dev/null; then
            if command -v freq &>/dev/null; then
                ok "Installed via python3 -m pip ($(which freq))"
                freq_ready=true
            fi
        fi
    fi

    # Strategy C: symlink wrapper (no pip)
    if [[ "$freq_ready" == false ]]; then
        cat > /usr/local/bin/freq << WRAPPER
#!/bin/sh
FREQ_DIR="${INSTALL_DIR}" PYTHONPATH="${INSTALL_DIR}" exec python3 -m freq "\$@"
WRAPPER
        chmod 755 /usr/local/bin/freq
        if /usr/local/bin/freq --version &>/dev/null; then
            ok "Installed via wrapper script (/usr/local/bin/freq)"
            freq_ready=true
        else
            fail "Could not set up freq command"
            exit 1
        fi
    fi

    echo ""
}

# ── Post-install ───────────────────────────────────────────────────────────

post_install() {
    # Verify version
    local installed_ver
    installed_ver=$(freq --version 2>/dev/null | head -1 || echo "unknown")
    step "Installed: ${installed_ver}"
    echo ""

    # Run doctor
    if [[ "$SKIP_DOCTOR" == false ]]; then
        echo -e "${C_BOLD}Running diagnostics...${C_RESET}"
        echo ""
        freq doctor 2>/dev/null || true
        echo ""
    fi

    # Install systemd unit if requested
    if [[ "$WITH_SYSTEMD" == true ]]; then
        if [[ -f "$INSTALL_DIR/contrib/freq-serve.service" ]]; then
            step "Installing systemd unit"
            cp "$INSTALL_DIR/contrib/freq-serve.service" /etc/systemd/system/
            systemctl daemon-reload
            systemctl enable freq-serve
            ok "Systemd unit installed (freq-serve.service)"
            info "Start with: systemctl start freq-serve"
        else
            warn "Systemd unit not found at $INSTALL_DIR/contrib/freq-serve.service"
        fi
        echo ""
    fi

    # Next steps
    echo -e "${C_GREEN}${C_BOLD}PVE FREQ v${FREQ_VERSION} installed successfully.${C_RESET}"
    echo ""
    echo -e "  ${C_BOLD}Next steps:${C_RESET}"
    echo -e "    1. Run ${C_CYAN}sudo freq init${C_RESET} — discovers your cluster and deploys fleet access"
    echo -e "    2. Run ${C_CYAN}freq doctor${C_RESET} to verify everything is healthy"
    echo -e "    3. Run ${C_CYAN}freq serve${C_RESET} to start the dashboard"
    echo ""
    echo -e "  ${C_GRAY}Documentation: ${REPO_URL}${C_RESET}"
    echo ""
}

# ── Uninstall ──────────────────────────────────────────────────────────────

do_uninstall() {
    echo -e "${C_BOLD}Uninstalling PVE FREQ${C_RESET}"
    echo ""

    # Must be root
    if [[ $EUID -ne 0 ]]; then
        fail "Must run as root (use sudo)"
        exit 1
    fi

    # Warn about fleet accounts
    if [[ -d "$INSTALL_DIR/data/keys" ]] && ls "$INSTALL_DIR"/data/keys/freq_id_* &>/dev/null 2>&1; then
        echo -e "  ${C_YELLOW}WARNING: FREQ SSH keys still exist in ${INSTALL_DIR}/data/keys/${C_RESET}"
        echo -e "  ${C_YELLOW}Fleet hosts may still have the FREQ service account.${C_RESET}"
        echo -e "  ${C_YELLOW}Run 'sudo freq init --uninstall' first to clean up fleet hosts.${C_RESET}"
        echo ""
        if [[ "$YES" == false ]]; then
            read -rp "  Continue with local uninstall anyway? [y/N]: " confirm
            if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
                echo "  Aborted."
                exit 0
            fi
        fi
    fi

    # Remove pip package
    if command -v pip3 &>/dev/null; then
        step "Removing pip package"
        pip3 uninstall -y pve-freq 2>/dev/null && ok "pip package removed" || true
    fi

    # Remove wrapper script
    if [[ -f /usr/local/bin/freq ]]; then
        rm -f /usr/local/bin/freq
        ok "Removed /usr/local/bin/freq"
    fi

    # Remove install directory
    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ "$YES" == false ]]; then
            echo ""
            echo -e "  ${C_YELLOW}This will remove all FREQ files including config:${C_RESET}"
            echo -e "  ${C_YELLOW}  ${INSTALL_DIR}${C_RESET}"
            read -rp "  Are you sure? [y/N]: " confirm
            if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
                echo "  Aborted. Files remain at ${INSTALL_DIR}"
                exit 0
            fi
        fi
        rm -rf "$INSTALL_DIR"
        ok "Removed ${INSTALL_DIR}"
    else
        info "Install directory not found: ${INSTALL_DIR}"
    fi

    echo ""
    echo -e "${C_GREEN}FREQ removed from this host.${C_RESET}"
    echo -e "${C_GRAY}Fleet hosts were NOT modified. To remove FREQ from fleet hosts,${C_RESET}"
    echo -e "${C_GRAY}run 'sudo freq init --uninstall' before uninstalling.${C_RESET}"
    echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────

main() {
    if [[ "$MODE" == "uninstall" ]]; then
        banner
        do_uninstall
        exit 0
    fi

    banner
    preflight
    do_install
    post_install
}

main
