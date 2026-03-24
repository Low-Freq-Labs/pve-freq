"""Result storage — SQLite backend for persistent history.

Stores every engine run with per-host detail. Enables:
- "freq engine status" — show last run
- Historical trend analysis
- Audit trail for compliance
"""
import sqlite3
import json
import time
import os
from engine.core.types import FleetResult, Host, Phase


class ResultStore:
    """Stores remediation results in SQLite.

    Schema:
    - runs: one row per engine invocation
    - host_results: one row per host per run
    """

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT (datetime('now')),
                policy TEXT NOT NULL,
                mode TEXT NOT NULL,
                duration REAL,
                total INTEGER,
                compliant INTEGER,
                drift INTEGER,
                fixed INTEGER,
                failed INTEGER
            );
            CREATE TABLE IF NOT EXISTS host_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES runs(id),
                host TEXT NOT NULL,
                ip TEXT,
                htype TEXT,
                phase TEXT NOT NULL,
                error TEXT,
                findings TEXT,
                changes TEXT,
                duration REAL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_policy ON runs(policy);
            CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_host_results_run ON host_results(run_id);
        """)

    def save(self, result: FleetResult):
        """Save a fleet result to the database."""
        cur = self.db.execute(
            "INSERT INTO runs(policy,mode,duration,total,compliant,drift,fixed,failed) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (result.policy, result.mode, result.duration, result.total,
             result.compliant, result.drift, result.fixed, result.failed)
        )
        run_id = cur.lastrowid
        for h in result.hosts:
            findings_json = json.dumps(
                [{"key": f.key, "current": str(f.current),
                  "desired": str(f.desired), "severity": f.severity.value}
                 for f in h.findings],
                default=str
            )
            self.db.execute(
                "INSERT INTO host_results"
                "(run_id,host,ip,htype,phase,error,findings,changes,duration) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, h.label, h.ip, h.htype, h.phase.name, h.error,
                 findings_json, json.dumps(h.changes), h.duration)
            )
        self.db.commit()
        return run_id

    def last_run(self, policy: str = "") -> dict | None:
        """Get the most recent run, optionally filtered by policy."""
        if policy:
            row = self.db.execute(
                "SELECT * FROM runs WHERE policy=? ORDER BY timestamp DESC LIMIT 1",
                (policy,)
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()

        if row:
            return {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "policy": row["policy"],
                "mode": row["mode"],
                "duration": row["duration"],
                "total": row["total"],
                "compliant": row["compliant"],
                "drift": row["drift"],
                "fixed": row["fixed"],
                "failed": row["failed"],
            }
        return None

    def run_history(self, policy: str = "", limit: int = 10) -> list[dict]:
        """Get recent run history."""
        if policy:
            rows = self.db.execute(
                "SELECT * FROM runs WHERE policy=? ORDER BY timestamp DESC LIMIT ?",
                (policy, limit)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()

        return [dict(r) for r in rows]

    def host_detail(self, run_id: int) -> list[dict]:
        """Get per-host results for a specific run."""
        rows = self.db.execute(
            "SELECT * FROM host_results WHERE run_id=? ORDER BY host",
            (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        """Close the database connection."""
        self.db.close()
