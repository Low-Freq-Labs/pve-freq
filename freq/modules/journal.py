"""Operation journal for FREQ.

Maintains a log of all significant operations — creates, destroys,
config changes, audit results, policy fixes. Queryable history.

Usage:
  freq journal              # show recent operations
  freq journal --lines 50   # show last 50 entries
  freq journal --search vm  # search for VM operations
"""
import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig


def _journal_path(cfg: FreqConfig) -> str:
    """Path to the journal file."""
    return os.path.join(cfg.data_dir, "log", "journal.jsonl")


def cmd_journal(cfg: FreqConfig, pack, args) -> int:
    """Show operation history."""
    lines = getattr(args, "lines", None) or 20
    search = getattr(args, "search", None)

    fmt.header("Journal")
    fmt.blank()

    path = _journal_path(cfg)
    if not os.path.exists(path):
        fmt.line(f"{fmt.C.YELLOW}No journal entries yet.{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Operations will be logged as you use FREQ.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Read entries
    entries = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        fmt.error("Cannot read journal.")
        return 1

    # Filter
    if search:
        search_lower = search.lower()
        entries = [e for e in entries if
                   search_lower in e.get("action", "").lower() or
                   search_lower in e.get("target", "").lower() or
                   search_lower in e.get("detail", "").lower()]

    # Show last N
    entries = entries[-lines:]

    if not entries:
        fmt.line(f"{fmt.C.YELLOW}No matching entries.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("TIME", 20),
        ("ACTION", 16),
        ("TARGET", 16),
        ("STATUS", 8),
    )

    status_colors = {"ok": fmt.C.GREEN, "fail": fmt.C.RED, "warn": fmt.C.YELLOW}

    for e in entries:
        ts = e.get("timestamp", "?")
        action = e.get("action", "?")[:16]
        target = e.get("target", "")[:16]
        status = e.get("status", "?")
        color = status_colors.get(status, fmt.C.GRAY)

        fmt.table_row(
            (f"{fmt.C.DIM}{ts}{fmt.C.RESET}", 20),
            (f"{fmt.C.BOLD}{action}{fmt.C.RESET}", 16),
            (target, 16),
            (f"{color}{status}{fmt.C.RESET}", 8),
        )

        detail = e.get("detail", "")
        if detail:
            print(f"    {fmt.C.DIM}{detail[:60]}{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}{len(entries)} entries shown{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
