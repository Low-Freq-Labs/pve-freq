"""Display formatting for FREQ.

Every pixel on screen goes through here. Purple branding, Unicode borders,
step indicators, tables, badges. The visual identity of the tool.

Adapted from fmt.sh (315 lines) — reimagined in Python with full Unicode support.
"""
import re
import shutil


# --- Colors (ANSI escape sequences) ---

class C:
    """Color constants. The FREQ palette."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Brand
    PURPLE = "\033[38;5;93m"
    PURPLE_BOLD = "\033[1;38;5;93m"

    # Semantic
    RED = "\033[38;5;196m"
    GREEN = "\033[38;5;82m"
    YELLOW = "\033[38;5;220m"
    CYAN = "\033[38;5;87m"
    BLUE = "\033[38;5;69m"
    ORANGE = "\033[38;5;208m"
    MAGENTA = "\033[38;5;201m"
    WHITE = "\033[38;5;255m"
    GRAY = "\033[38;5;245m"
    DARK_GRAY = "\033[38;5;240m"


# --- Symbols (Unicode with ASCII fallback) ---

class _Symbols:
    """Symbols. Unicode by default, ASCII if terminal can't handle it."""

    def __init__(self):
        self._ascii = False

    def set_ascii(self, ascii_mode: bool) -> None:
        self._ascii = ascii_mode

    @property
    def TICK(self) -> str:
        return "[OK]" if self._ascii else "\u2714"

    @property
    def CROSS(self) -> str:
        return "[X]" if self._ascii else "\u2718"

    @property
    def WARN(self) -> str:
        return "[!]" if self._ascii else "\u26a0"

    @property
    def INFO(self) -> str:
        return "[i]" if self._ascii else "\u2139"

    @property
    def ARROW(self) -> str:
        return "->" if self._ascii else "\u2192"

    @property
    def STAR(self) -> str:
        return "*" if self._ascii else "\u2605"

    @property
    def DIAMOND(self) -> str:
        return "<>" if self._ascii else "\u25c6"

    @property
    def SPARKLE(self) -> str:
        return "~" if self._ascii else "\u2728"

    @property
    def DOT(self) -> str:
        return "." if self._ascii else "\u2022"


# Module-level singleton
S = _Symbols()


# --- Border Characters ---

def _use_ascii() -> bool:
    return S._ascii


def _b(unicode_char: str, ascii_char: str) -> str:
    return ascii_char if _use_ascii() else unicode_char


# Box drawing
def B_TL() -> str: return _b("\u256d", "+")
def B_TR() -> str: return _b("\u256e", "+")
def B_BL() -> str: return _b("\u2570", "+")
def B_BR() -> str: return _b("\u256f", "+")
def B_H() -> str: return _b("\u2500", "-")
def B_V() -> str: return _b("\u2502", "|")
def B_LM() -> str: return _b("\u251c", "+")
def B_RM() -> str: return _b("\u2524", "+")


# --- Terminal Width ---

_cached_width: int = 0


def term_width() -> int:
    """Get terminal width, cached for performance."""
    global _cached_width
    if _cached_width == 0:
        _cached_width = shutil.get_terminal_size((80, 24)).columns
    return _cached_width


# --- ANSI Utilities ---

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def visible_len(text: str) -> int:
    """Length of text as it appears on screen (ignoring ANSI codes)."""
    return len(strip_ansi(text))


def truncate(text: str, max_width: int) -> str:
    """Truncate text to max_width visible characters, preserving ANSI codes."""
    if visible_len(text) <= max_width:
        return text

    result = []
    visible = 0
    i = 0
    while i < len(text) and visible < max_width:
        if text[i] == "\033":
            # Consume entire ANSI sequence
            j = i + 1
            while j < len(text) and text[j] != "m":
                j += 1
            result.append(text[i:j + 1])
            i = j + 1
        else:
            result.append(text[i])
            visible += 1
            i += 1

    return "".join(result) + C.RESET


# --- Display Functions ---

def header(title: str, breadcrumb: str = "PVE FREQ") -> None:
    """Print a bordered header line: [ PVE FREQ > Title ]"""
    w = term_width()
    label = f" {breadcrumb} {S.ARROW} {title} " if breadcrumb else f" {title} "
    label_vis = visible_len(label)
    # Inner width = w - 2 (left border + right border)
    inner = w - 2
    if label_vis > inner:
        label = truncate(label, inner)
        label_vis = inner
    padding = inner - label_vis

    top = f"{C.PURPLE}{B_TL()}{B_H() * inner}{B_TR()}{C.RESET}"
    mid = f"{C.PURPLE}{B_V()}{C.RESET}{C.PURPLE_BOLD}{label}{C.RESET}{' ' * padding}{C.PURPLE}{B_V()}{C.RESET}"

    print(top)
    print(mid)
    print(f"{C.PURPLE}{B_LM()}{B_H() * inner}{B_RM()}{C.RESET}")


def footer() -> None:
    """Print a bordered footer line."""
    w = term_width()
    print(f"{C.PURPLE}{B_BL()}{B_H() * (w - 2)}{B_BR()}{C.RESET}")


def line(text: str = "", indent: int = 2) -> None:
    """Print a bordered content line."""
    w = term_width()
    inner = w - 2  # space between left and right border
    prefix = " " * indent
    content = f"{prefix}{text}"
    content_vis = visible_len(content)
    if content_vis > inner:
        content = truncate(content, inner)
        content_vis = inner
    padding = inner - content_vis
    print(f"{C.PURPLE}{B_V()}{C.RESET}{content}{' ' * padding}{C.PURPLE}{B_V()}{C.RESET}")


def blank() -> None:
    """Print an empty bordered line."""
    line("")


def divider(title: str = "") -> None:
    """Print a mid-section divider, optionally with a centered title."""
    w = term_width()
    inner = w - 2  # space between connectors
    if title:
        label = f" {title} "
        label_vis = visible_len(label)
        if label_vis > inner:
            label = truncate(label, inner)
            label_vis = inner
        left = (inner - label_vis) // 2
        right = inner - label_vis - left
        print(f"{C.PURPLE}{B_LM()}{B_H() * left}{C.RESET}{C.GRAY}{label}{C.PURPLE}{B_H() * right}{B_RM()}{C.RESET}")
    else:
        print(f"{C.PURPLE}{B_LM()}{B_H() * inner}{B_RM()}{C.RESET}")


# --- Step Indicators ---
# All step functions render inside the bordered box.

def _bordered_line(content: str, end: str = "\n") -> None:
    """Print content wrapped in box borders with correct padding."""
    w = term_width()
    inner = w - 2
    content_vis = visible_len(content)
    if content_vis > inner:
        content = truncate(content, inner)
        content_vis = inner
    pad = max(0, inner - content_vis)
    print(f"{C.PURPLE}{B_V()}{C.RESET}{content}{' ' * pad}{C.PURPLE}{B_V()}{C.RESET}", end=end, flush=(end != "\n"))


def step_start(msg: str) -> None:
    """Print a step-in-progress indicator (bordered)."""
    _bordered_line(f"  {C.CYAN}{S.ARROW}{C.RESET} {msg}...", end="")


def step_ok(msg: str = "done") -> None:
    """Complete a step with success (bordered)."""
    w = term_width()
    inner = w - 2
    content = f"  {C.GREEN}{S.TICK}{C.RESET} {msg}"
    content_vis = visible_len(content)
    if content_vis > inner:
        content = truncate(content, inner)
        content_vis = inner
    pad = max(0, inner - content_vis)
    print(f"\r{C.PURPLE}{B_V()}{C.RESET}{content}{' ' * pad}{C.PURPLE}{B_V()}{C.RESET}")


def step_fail(msg: str = "failed") -> None:
    """Complete a step with failure (bordered)."""
    w = term_width()
    inner = w - 2
    content = f"  {C.RED}{S.CROSS}{C.RESET} {msg}"
    content_vis = visible_len(content)
    if content_vis > inner:
        content = truncate(content, inner)
        content_vis = inner
    pad = max(0, inner - content_vis)
    print(f"\r{C.PURPLE}{B_V()}{C.RESET}{content}{' ' * pad}{C.PURPLE}{B_V()}{C.RESET}")


def step_warn(msg: str) -> None:
    """Print a warning step (bordered)."""
    _bordered_line(f"  {C.YELLOW}{S.WARN}{C.RESET}  {msg}")


def step_info(msg: str) -> None:
    """Print an info step (bordered)."""
    _bordered_line(f"  {C.CYAN}{S.INFO}{C.RESET}  {msg}")


# --- Badges ---

_BADGE_COLORS = {
    "ok": C.GREEN, "up": C.GREEN, "running": C.GREEN, "pass": C.GREEN,
    "compliant": C.GREEN, "online": C.GREEN, "healthy": C.GREEN,
    "warn": C.YELLOW, "drift": C.YELLOW, "degraded": C.YELLOW,
    "fail": C.RED, "down": C.RED, "error": C.RED, "critical": C.RED,
    "offline": C.RED, "failed": C.RED,
    "skip": C.GRAY, "unknown": C.GRAY, "pending": C.GRAY,
}


def badge(status: str) -> str:
    """Return a colored status badge: [STATUS]"""
    color = _BADGE_COLORS.get(status.lower(), C.GRAY)
    return f"{color}[{status.upper()}]{C.RESET}"


# --- Table Helpers ---

def table_header(*columns: tuple) -> None:
    """Print a bordered table header row. Each column is (label, width)."""
    parts = []
    for label, width in columns:
        parts.append(f"{C.BOLD}{label:<{width}}{C.RESET}")
    _bordered_line(f"  {'  '.join(parts)}")
    total = sum(w for _, w in columns) + 2 * (len(columns) - 1) + 2
    _bordered_line(f"  {C.DARK_GRAY}{B_H() * total}{C.RESET}")


def table_row(*cells: tuple) -> None:
    """Print a bordered table data row. Each cell is (value, width)."""
    parts = []
    for value, width in cells:
        vis = visible_len(str(value))
        padding = max(0, width - vis)
        parts.append(f"{value}{' ' * padding}")
    _bordered_line(f"  {'  '.join(parts)}")


# --- Direct Output ---

def error(msg: str) -> None:
    """Print an error message."""
    print(f"{C.RED}{S.CROSS}{C.RESET} {msg}")


def success(msg: str) -> None:
    """Print a success message."""
    print(f"{C.GREEN}{S.TICK}{C.RESET} {msg}")


def warn(msg: str) -> None:
    """Print a warning message."""
    print(f"{C.YELLOW}{S.WARN}{C.RESET}  {msg}")


def info(msg: str) -> None:
    """Print an info message."""
    print(f"{C.CYAN}{S.INFO}{C.RESET}  {msg}")


def dim(msg: str) -> None:
    """Print dimmed text."""
    print(f"{C.DIM}{msg}{C.RESET}")
