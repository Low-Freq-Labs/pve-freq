"""Operational knowledge base for FREQ.

Domain: freq learn <query>

SQLite FTS5 full-text search across lessons learned and platform gotchas.
Knowledge is loaded from TOML files in data/knowledge/ and indexed at runtime.

Replaces: Confluence / wiki knowledge bases ($10+/user/mo enterprise)

Architecture:
    - TOML files are the source of truth; SQLite is the search index
    - FTS5 virtual tables for fast ranked search; LIKE fallback if unavailable
    - Lessons have severity/platform/session; gotchas have trigger/fix pairs

Design decisions:
    - TOML over SQLite as source — human-editable, git-trackable
    - Reseed on count mismatch keeps index fresh without manual rebuilds
"""
import logging
import os
import sqlite3

from freq.core import fmt
from freq.core.config import FreqConfig, load_toml

_logger = logging.getLogger(__name__)


# --- Knowledge Loader ---

def _load_knowledge(cfg: FreqConfig) -> tuple:
    """Load lessons and gotchas from TOML files in data/knowledge/.

    Returns (lessons, gotchas) as lists of tuples matching the DB schema.
    Falls back gracefully if files are missing.
    """
    knowledge_dir = os.path.join(cfg.data_dir, "knowledge")

    lessons = []
    lessons_data = load_toml(os.path.join(knowledge_dir, "lessons.toml"))
    for entry in lessons_data.get("lesson", []):
        lessons.append((
            entry.get("number", 0),
            entry.get("session", ""),
            entry.get("platform", ""),
            entry.get("severity", "info"),
            entry.get("title", ""),
            entry.get("description", ""),
            entry.get("related_commands", ""),
        ))

    gotchas = []
    gotchas_data = load_toml(os.path.join(knowledge_dir, "gotchas.toml"))
    for entry in gotchas_data.get("gotcha", []):
        gotchas.append((
            entry.get("platform", ""),
            entry.get("trigger", ""),
            entry.get("description", ""),
            entry.get("fix", ""),
        ))

    return lessons, gotchas


def _init_db(db_path: str) -> sqlite3.Connection:
    """Initialize or open the knowledge database."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Create tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE NOT NULL,
            session TEXT,
            platform TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            title TEXT NOT NULL,
            description TEXT,
            related_commands TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gotchas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            trigger_pattern TEXT,
            description TEXT NOT NULL,
            fix TEXT
        )
    """)

    # Create FTS5 virtual tables if not exist
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
                title, description, platform, related_commands,
                content='lessons', content_rowid='id'
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS gotchas_fts USING fts5(
                description, fix, platform, trigger_pattern,
                content='gotchas', content_rowid='id'
            )
        """)
    except sqlite3.OperationalError:
        _logger.info("FTS5 not available — falling back to LIKE queries")

    return conn


def _seed_db(conn: sqlite3.Connection, lessons: list, gotchas: list):
    """Seed the database with knowledge from TOML files."""
    # Clear and reseed — knowledge files are the source of truth
    existing = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    if existing > 0:
        # Check if knowledge pack changed (compare counts as simple heuristic)
        existing_gotchas = conn.execute("SELECT COUNT(*) FROM gotchas").fetchone()[0]
        if existing == len(lessons) and existing_gotchas == len(gotchas):
            return  # Same counts — skip reseed

        # Counts differ — reseed
        conn.execute("DELETE FROM lessons")
        conn.execute("DELETE FROM gotchas")

    for entry in lessons:
        conn.execute(
            "INSERT OR IGNORE INTO lessons (number, session, platform, severity, title, description, related_commands) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", entry
        )
    for entry in gotchas:
        conn.execute(
            "INSERT INTO gotchas (platform, trigger_pattern, description, fix) "
            "VALUES (?, ?, ?, ?)", entry
        )

    # Rebuild FTS indexes
    try:
        conn.execute("INSERT INTO lessons_fts(lessons_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO gotchas_fts(gotchas_fts) VALUES('rebuild')")
    except sqlite3.OperationalError:
        pass

    conn.commit()


def _search(conn: sqlite3.Connection, query: str) -> tuple:
    """Search lessons and gotchas. Returns (lessons, gotchas) lists."""
    lessons = []
    gotchas = []

    # Try FTS5 first
    try:
        # Sanitize query for FTS5
        terms = query.replace('"', '').replace("'", '').split()
        fts_query = " ".join(f'"{t}"' for t in terms if t)

        lessons = conn.execute(
            "SELECT l.number, l.session, l.platform, l.severity, l.title, l.description, l.related_commands "
            "FROM lessons_fts f JOIN lessons l ON f.rowid = l.id "
            "WHERE lessons_fts MATCH ? ORDER BY rank LIMIT 15",
            (fts_query,)
        ).fetchall()

        gotchas = conn.execute(
            "SELECT g.platform, g.trigger_pattern, g.description, g.fix "
            "FROM gotchas_fts f JOIN gotchas g ON f.rowid = g.id "
            "WHERE gotchas_fts MATCH ? ORDER BY rank LIMIT 10",
            (fts_query,)
        ).fetchall()
    except sqlite3.OperationalError:
        pass

    # Fallback to LIKE if FTS5 failed or returned nothing
    if not lessons and not gotchas:
        like_pattern = f"%{'%'.join(query.split())}%"
        lessons = conn.execute(
            "SELECT number, session, platform, severity, title, description, related_commands "
            "FROM lessons WHERE title LIKE ? OR description LIKE ? OR platform LIKE ? "
            "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'important' THEN 1 WHEN 'info' THEN 2 ELSE 3 END "
            "LIMIT 15",
            (like_pattern, like_pattern, like_pattern)
        ).fetchall()
        gotchas = conn.execute(
            "SELECT platform, trigger_pattern, description, fix "
            "FROM gotchas WHERE description LIKE ? OR trigger_pattern LIKE ? OR fix LIKE ? "
            "LIMIT 10",
            (like_pattern, like_pattern, like_pattern)
        ).fetchall()

    return lessons, gotchas


# --- Command ---

def cmd_learn(cfg: FreqConfig, pack, args) -> int:
    """Search the FREQ knowledge base."""
    query_parts = getattr(args, "query", [])
    query = " ".join(query_parts) if query_parts else ""

    # Load knowledge from TOML files
    lessons_data, gotchas_data = _load_knowledge(cfg)

    db_path = os.path.join(cfg.data_dir, "jarvis", "knowledge.db")
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = _init_db(db_path)
    except OSError:
        # Fall back to user-local path if data dir is not writable
        fallback = os.path.join(os.path.expanduser("~"), ".freq", "knowledge.db")
        os.makedirs(os.path.dirname(fallback), exist_ok=True)
        conn = _init_db(fallback)
    _seed_db(conn, lessons_data, gotchas_data)

    if not query:
        # Show stats
        fmt.header("Learn — Knowledge Base")
        fmt.blank()
        lesson_count = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        gotcha_count = conn.execute("SELECT COUNT(*) FROM gotchas").fetchone()[0]
        platforms = conn.execute("SELECT DISTINCT platform FROM lessons").fetchall()

        fmt.line(f"{fmt.C.BOLD}{lesson_count} lessons{fmt.C.RESET} + {fmt.C.BOLD}{gotcha_count} gotchas{fmt.C.RESET}")
        fmt.blank()
        if platforms:
            fmt.line(f"{fmt.C.BOLD}Platforms:{fmt.C.RESET} {', '.join(p[0] for p in platforms)}")
            fmt.blank()
        fmt.line(f"{fmt.C.GRAY}Usage: freq learn <query>{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}  freq learn nfs stale{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}  freq learn docker gluetun{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}  freq learn pfsense reboot{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        conn.close()
        return 0

    # Search
    fmt.header(f"Learn: {query}")
    fmt.blank()

    lessons, gotchas = _search(conn, query)

    severity_colors = {
        "critical": fmt.C.RED,
        "important": fmt.C.YELLOW,
        "info": fmt.C.CYAN,
        "tip": fmt.C.GREEN,
    }

    if lessons:
        fmt.line(f"{fmt.C.BOLD}Lessons ({len(lessons)}){fmt.C.RESET}")
        fmt.blank()
        for l in lessons:
            number, session, platform, severity, title, desc, cmds = l
            color = severity_colors.get(severity, fmt.C.GRAY)
            badge = f"{color}[{severity.upper()}]{fmt.C.RESET}"
            plat_badge = f"{fmt.C.CYAN}[{platform}]{fmt.C.RESET}"

            print(f"  {badge} {plat_badge} {fmt.C.BOLD}#{number}{fmt.C.RESET} {title}")
            print(f"    {fmt.C.DIM}{desc}{fmt.C.RESET}")
            if cmds:
                print(f"    {fmt.C.GRAY}Related: {cmds}{fmt.C.RESET}")
            print()

    if gotchas:
        fmt.line(f"{fmt.C.BOLD}Gotchas ({len(gotchas)}){fmt.C.RESET}")
        fmt.blank()
        for g in gotchas:
            platform, trigger, desc, fix = g
            print(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}  {fmt.C.CYAN}[{platform}]{fmt.C.RESET} {desc}")
            if fix:
                print(f"    {fmt.C.GREEN}Fix: {fix}{fmt.C.RESET}")
            print()

    if not lessons and not gotchas:
        fmt.line(f"{fmt.C.YELLOW}No results for '{query}'.{fmt.C.RESET}")
        fmt.blank()

    fmt.footer()
    conn.close()
    return 0
