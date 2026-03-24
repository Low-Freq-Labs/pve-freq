"""Display layer — git-style diffs and formatted output.

Core 07 architecture — the winner for visualization.
Colored unified diffs, fleet result tables, policy listings.
All output is ANSI-aware for terminal rendering.

Visual language matches lib/fmt.sh exactly: same borders, same
colors, same soul. Purple brand palette, rounded corners,
breadcrumb navigation, Unicode status icons.
"""
import difflib
import shutil
from engine.core.types import Host, Phase, FleetResult, Finding

# ─── COLORS — matched to lib/core.sh palette ────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
MAGENTA = "\033[0;35m"
PURPLE = "\033[38;5;93m"
PURPLELIGHT = "\033[38;5;135m"
PURPLEDIM = "\033[38;5;60m"
PURPLEGLOW = "\033[38;5;141m"
WHITE = "\033[1;37m"
BLUE = "\033[38;5;69m"
ORANGE = "\033[38;5;208m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ─── BOX DRAWING — rounded single-line ──────────────────────────
B_H = "\u2500"   # ─
B_V = "\u2502"   # │
B_TL = "\u256d"  # ╭
B_TR = "\u256e"  # ╮
B_BL = "\u2570"  # ╰
B_BR = "\u256f"  # ╯
B_LM = "\u251c"  # ├
B_RM = "\u2524"  # ┤

# ─── SYMBOLS — matched to core.sh unicode set ───────────────────
TICK = "\u2714"      # ✔
CROSS = "\u2718"     # ✘
WARN_SYM = "\u26a0"  # ⚠
DIAMOND = "\u25c6"   # ◆
BULLET = "\u2022"    # •
DASH = "\u2014"      # —
DOT = "\u00b7"       # ·
SPARKLE = "\u2728"   # ✨
RARROW = "\u203a"    # ›
ARROW = "\u2192"     # →

# ─── PHASE ICONS — same status indicators as bash _badge() ──────
PHASE_ICONS = {
    Phase.DONE:      f"{GREEN}{TICK}{RESET}",
    Phase.COMPLIANT: f"{DIM}{DASH}{RESET}",
    Phase.PLANNED:   f"{CYAN}{DIAMOND}{RESET}",
    Phase.DRIFT:     f"{YELLOW}{WARN_SYM}{RESET}",
    Phase.FAILED:    f"{RED}{CROSS}{RESET}",
    Phase.FIXING:    f"{YELLOW}{DIAMOND}{RESET}",
    Phase.VERIFYING: f"{CYAN}{TICK}{RESET}",
}


# ═════════════════════════════════════════════════════════════════
# WIDTH + ANSI HELPERS
# ═════════════════════════════════════════════════════════════════

def _get_width():
    """Terminal width — one call, sane defaults. Mirrors _freq_width()."""
    try:
        w = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        w = 80
    if w < 40 or w > 300:
        w = 80
    return w


def _strip_ansi(text):
    """Strip ANSI escape sequences to get visible length."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)


def _visible_len(text):
    """Return visible character count (excludes ANSI codes)."""
    return len(_strip_ansi(text))


def _repeat(char, count):
    """Repeat a character N times."""
    if count < 1:
        return ""
    return char * count


# ═════════════════════════════════════════════════════════════════
# BORDER SYSTEM — mirrors freq_header / freq_line / freq_footer
# ═════════════════════════════════════════════════════════════════

def _header(title):
    """Top border with breadcrumb: ╭──[ PVE FREQ › title ]───...───╮"""
    w = _get_width()
    inner = f"[ PVE FREQ {RARROW} {title} ]"
    vis_inner = _visible_len(inner)
    fill = w - vis_inner - 4
    if fill < 1:
        fill = 1
    print(f"\n{PURPLE}{B_TL}{B_H}{B_H}{inner}{_repeat(B_H, fill)}{B_TR}{RESET}")


def _footer():
    """Bottom border: ╰────...────╯"""
    w = _get_width()
    fill = w - 2
    if fill < 1:
        fill = 1
    print(f"{PURPLE}{B_BL}{_repeat(B_H, fill)}{B_BR}{RESET}\n")


def _line(content=""):
    """Content line with side borders: │ content            │"""
    w = _get_width()
    vis_len = _visible_len(content)
    pad = w - vis_len - 4
    if pad < 0:
        pad = 0
    print(f"{PURPLE}{B_V}{RESET} {content}{' ' * pad} {PURPLE}{B_V}{RESET}")


def _blank():
    """Empty bordered line."""
    w = _get_width()
    pad = w - 2
    if pad < 0:
        pad = 0
    print(f"{PURPLE}{B_V}{RESET}{' ' * pad}{PURPLE}{B_V}{RESET}")


def _divider(title=""):
    """Mid-section divider: ├──────...──┤ or ├── title ──...──┤"""
    w = _get_width()
    if not title:
        fill = w - 2
        if fill < 1:
            fill = 1
        print(f"{PURPLEDIM}{B_LM}{_repeat(B_H, fill)}{B_RM}{RESET}")
    else:
        vis_len = _visible_len(title)
        left = 2
        right = w - vis_len - left - 6
        if right < 1:
            right = 1
        print(f"{PURPLE}{B_LM}{RESET}{_repeat(B_H, left)} {title} {_repeat(B_H, right)}{PURPLE}{B_RM}{RESET}")


# ═════════════════════════════════════════════════════════════════
# PUBLIC API — same signatures, new visuals
# ═════════════════════════════════════════════════════════════════

def show_diff(host: Host):
    """Show git-style unified diff of current vs desired config.

    Renders a colored unified diff comparing the host's current
    configuration against the desired policy state.
    """
    current_lines = [f"{k} {v}" for k, v in sorted(host.current.items())
                     if not k.startswith("_")]
    desired_lines = [f"{k} {v}" for k, v in sorted(host.desired.items())
                     if not k.startswith("_")]

    diff = difflib.unified_diff(
        current_lines, desired_lines,
        fromfile=f"{host.label} (current)",
        tofile=f"{host.label} (desired)",
        lineterm="",
    )

    lines = list(diff)
    if not lines:
        return

    _header(f"diff {DOT} {host.label}")

    for ln in lines:
        if ln.startswith("---"):
            _line(f"{RED}{ln}{RESET}")
        elif ln.startswith("+++"):
            _line(f"{GREEN}{ln}{RESET}")
        elif ln.startswith("-"):
            _line(f"{RED}{ln}{RESET}")
        elif ln.startswith("+"):
            _line(f"{GREEN}{ln}{RESET}")
        elif ln.startswith("@@"):
            _line(f"{CYAN}{ln}{RESET}")
        else:
            _line(f" {ln}")

    _footer()


def show_results(result: FleetResult):
    """Show fleet remediation results.

    Renders a formatted table with phase icons, host labels,
    status, duration, findings, and changes. Bordered output
    matching freq_header/freq_footer style.
    """
    _header(result.policy)

    # Mode / host count / duration subtitle
    _line(f"{BOLD}Mode:{RESET} {result.mode}  {PURPLEDIM}{DOT}{RESET}  "
          f"{BOLD}{result.total}{RESET} hosts  {PURPLEDIM}{DOT}{RESET}  "
          f"{result.duration:.1f}s")
    _blank()

    # Per-host results
    for host in result.hosts:
        icon = PHASE_ICONS.get(host.phase, f"{DIM}?{RESET}")
        status = host.error if host.error else host.phase.name

        # Color the status text
        if host.phase == Phase.FAILED:
            status_colored = f"{RED}{status}{RESET}"
        elif host.phase == Phase.DONE:
            status_colored = f"{GREEN}{status}{RESET}"
        elif host.phase == Phase.COMPLIANT:
            status_colored = f"{DIM}{status}{RESET}"
        elif host.phase in (Phase.DRIFT, Phase.PLANNED):
            status_colored = f"{YELLOW}{status}{RESET}"
        else:
            status_colored = status

        _line(f" {icon}  {host.label:<18} {status_colored:<30} {DIM}{host.duration:.1f}s{RESET}")

        # Show findings
        for finding in host.findings:
            if result.mode == "check" or host.phase in (Phase.DRIFT, Phase.PLANNED):
                tag = f"{YELLOW}{WARN_SYM} DRIFT{RESET}"
            else:
                tag = f"{GREEN}{TICK} FIXED{RESET}"
            _line(f"      {tag}  {finding.key}: "
                  f"{RED}{finding.current}{RESET} {ARROW} "
                  f"{GREEN}{finding.desired}{RESET}")

        # Show changes
        for change in host.changes:
            _line(f"      {GREEN}{TICK} DONE{RESET}  {change}")

    # Summary
    _divider()
    parts = []
    if result.compliant:
        parts.append(f"{GREEN}{result.compliant} compliant{RESET}")
    if result.drift:
        parts.append(f"{YELLOW}{result.drift} drift{RESET}")
    if result.fixed:
        parts.append(f"{GREEN}{result.fixed} fixed{RESET}")
    if result.failed:
        parts.append(f"{RED}{result.failed} failed{RESET}")

    summary = f" {PURPLEDIM}{DOT}{RESET} ".join(parts) if parts else f"{DIM}no results{RESET}"
    _line(f" {BOLD}Summary:{RESET}  {summary}")

    _footer()


def show_policies(policies):
    """List available policies with their descriptions and scope."""
    _header("Policies")

    if not policies:
        _line(f"{DIM}No policies found.{RESET}")
        _line(f"{DIM}Place policy files in engine/policies/ directory.{RESET}")
        _footer()
        return

    for i, p in enumerate(policies):
        if i > 0:
            _blank()
        scope_str = ", ".join(p.scope)
        _line(f" {PURPLELIGHT}{BOLD}{p.name}{RESET}")
        _line(f"   {p.description}")
        _line(f"   {DIM}Scope: {scope_str}  {DOT}  {len(p.resources)} resources{RESET}")

    _footer()


def show_host_detail(host: Host):
    """Show detailed view of a single host's state."""
    _header(f"host {DOT} {host.label}")

    icon = PHASE_ICONS.get(host.phase, f"{DIM}?{RESET}")
    _line(f" {icon}  {BOLD}{host.label}{RESET}  ({host.ip})  {DIM}{host.htype}{RESET}")
    _line(f"    Phase: {host.phase.name}  {PURPLEDIM}{DOT}{RESET}  Duration: {host.duration:.1f}s")

    if host.error:
        _line(f"    {RED}Error: {host.error}{RESET}")

    if host.current:
        _divider(f"{DIM}Current State ({len(host.current)} keys){RESET}")
        for k, v in sorted(host.current.items()):
            if not k.startswith("_"):
                _line(f"    {k}: {v}")

    if host.desired:
        _divider(f"{DIM}Desired State ({len(host.desired)} keys){RESET}")
        for k, v in sorted(host.desired.items()):
            _line(f"    {k}: {v}")

    if host.findings:
        _divider(f"{YELLOW}Findings ({len(host.findings)}){RESET}")
        for f in host.findings:
            _line(f"    {YELLOW}{f.key}{RESET}: {f.current} {ARROW} {f.desired}")

    if host.changes:
        _divider(f"{GREEN}Changes ({len(host.changes)}){RESET}")
        for c in host.changes:
            _line(f"    {GREEN}{TICK}{RESET} {c}")

    _footer()
