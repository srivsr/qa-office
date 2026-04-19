"""
Memory DB — SQLite schema and CRUD for A9 Memory Keeper.
Four tables: run_history, selector_stability, human_decisions, reflection_insights.
WRITE ACCESS: Only A9 Memory Keeper may call write functions here.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_DB_PATH = Path(__file__).parent / "qa_memory.db"
_lock = threading.Lock()

# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    test_case_id    TEXT NOT NULL,
    module          TEXT NOT NULL DEFAULT 'General',
    status          TEXT NOT NULL,
    root_cause      TEXT,
    confidence      REAL,
    retry_count     INTEGER DEFAULT 0,
    duration_ms     INTEGER DEFAULT 0,
    timestamp       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS selector_stability (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    selector_value  TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    test_case_id    TEXT NOT NULL,
    pass_count      INTEGER DEFAULT 0,
    fail_count      INTEGER DEFAULT 0,
    stability_score REAL DEFAULT 1.0,
    last_used       TEXT,
    last_updated    TEXT NOT NULL,
    UNIQUE(selector_value, test_case_id)
);

CREATE TABLE IF NOT EXISTS human_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    test_case_id    TEXT NOT NULL,
    decision        TEXT NOT NULL,
    reason          TEXT,
    decided_by      TEXT NOT NULL DEFAULT 'human',
    timestamp       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reflection_insights (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    insight_text    TEXT NOT NULL,
    run_count       INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    expires_at      TEXT
);

CREATE TABLE IF NOT EXISTS pom_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url    TEXT NOT NULL UNIQUE,
    page_name   TEXT NOT NULL,
    class_name  TEXT NOT NULL,
    elements_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_history_run_id     ON run_history(run_id);
CREATE INDEX IF NOT EXISTS idx_run_history_tc_id      ON run_history(test_case_id);
CREATE INDEX IF NOT EXISTS idx_selector_stability_sel ON selector_stability(selector_value);
CREATE INDEX IF NOT EXISTS idx_human_decisions_run_id ON human_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_insights_agent_id      ON reflection_insights(agent_id);
CREATE INDEX IF NOT EXISTS idx_pom_cache_url          ON pom_cache(page_url);
"""


def _resolve(db_path: Optional[Path]) -> Path:
    return db_path if db_path is not None else _DB_PATH


@contextmanager
def _conn(db_path: Optional[Path] = None):
    with _lock:
        con = sqlite3.connect(str(_resolve(db_path)))
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Create all tables. Safe to call multiple times (idempotent)."""
    with _conn(db_path) as con:
        con.executescript(_SCHEMA)


# ── run_history ────────────────────────────────────────────────────────────────


def insert_run(
    run_id: str,
    test_case_id: str,
    module: str,
    status: str,
    root_cause: Optional[str] = None,
    confidence: Optional[float] = None,
    retry_count: int = 0,
    duration_ms: int = 0,
    db_path: Optional[Path] = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO run_history
               (run_id, test_case_id, module, status, root_cause,
                confidence, retry_count, duration_ms, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                test_case_id,
                module,
                status,
                root_cause,
                confidence,
                retry_count,
                duration_ms,
                ts,
            ),
        )


def get_run_history(
    test_case_id: str,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> List[Dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM run_history WHERE test_case_id=? ORDER BY id DESC LIMIT ?",
            (test_case_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── selector_stability ─────────────────────────────────────────────────────────


def upsert_selector(
    selector_value: str,
    strategy: str,
    test_case_id: str,
    passed: bool,
    db_path: Optional[Path] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO selector_stability
               (selector_value, strategy, test_case_id, pass_count, fail_count,
                stability_score, last_used, last_updated)
               VALUES (?,?,?,?,?,1.0,?,?)
               ON CONFLICT(selector_value, test_case_id) DO UPDATE SET
                 pass_count    = pass_count + ?,
                 fail_count    = fail_count + ?,
                 stability_score = CAST(pass_count + ? AS REAL) /
                                   (pass_count + fail_count + 1),
                 last_used     = ?,
                 last_updated  = ?""",
            (
                selector_value,
                strategy,
                test_case_id,
                1 if passed else 0,
                0 if passed else 1,
                now,
                now,
                1 if passed else 0,
                0 if passed else 1,
                1 if passed else 0,
                now,
                now,
            ),
        )


def get_selector_stability(
    selector_value: str,
    db_path: Optional[Path] = None,
) -> Optional[Dict]:
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM selector_stability WHERE selector_value=? ORDER BY last_updated DESC LIMIT 1",
            (selector_value,),
        ).fetchone()
    return dict(row) if row else None


# ── human_decisions ────────────────────────────────────────────────────────────


def insert_human_decision(
    run_id: str,
    test_case_id: str,
    decision: str,
    reason: Optional[str] = None,
    decided_by: str = "human",
    db_path: Optional[Path] = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO human_decisions
               (run_id, test_case_id, decision, reason, decided_by, timestamp)
               VALUES (?,?,?,?,?,?)""",
            (run_id, test_case_id, decision, reason, decided_by, ts),
        )


def get_human_decisions(
    test_case_id: str,
    db_path: Optional[Path] = None,
) -> List[Dict]:
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM human_decisions WHERE test_case_id=? ORDER BY id DESC",
            (test_case_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── reflection_insights ────────────────────────────────────────────────────────


def insert_insight(
    agent_id: str,
    insight_text: str,
    run_count: int = 1,
    expires_at: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO reflection_insights
               (agent_id, insight_text, run_count, created_at, expires_at)
               VALUES (?,?,?,?,?)""",
            (agent_id, insight_text, run_count, now, expires_at),
        )


def get_insights(
    agent_id: str,
    db_path: Optional[Path] = None,
) -> List[Dict]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as con:
        rows = con.execute(
            """SELECT * FROM reflection_insights
               WHERE agent_id=?
                 AND (expires_at IS NULL OR expires_at > ?)
               ORDER BY id DESC""",
            (agent_id, now),
        ).fetchall()
    return [dict(r) for r in rows]


# ── pom_cache ──────────────────────────────────────────────────────────────────


import json as _json


def upsert_pom_cache(
    page_url: str,
    page_name: str,
    class_name: str,
    elements_json: str,
    ttl_days: int = 7,
    db_path: Optional[Path] = None,
) -> None:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=ttl_days)).isoformat()
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO pom_cache (page_url, page_name, class_name, elements_json, created_at, expires_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(page_url) DO UPDATE SET
                 page_name=excluded.page_name,
                 class_name=excluded.class_name,
                 elements_json=excluded.elements_json,
                 created_at=excluded.created_at,
                 expires_at=excluded.expires_at""",
            (page_url, page_name, class_name, elements_json, now.isoformat(), expires),
        )


def get_pom_cache(
    page_url: str,
    db_path: Optional[Path] = None,
) -> Optional[Dict]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM pom_cache WHERE page_url=? AND expires_at > ?",
            (page_url, now),
        ).fetchone()
    return dict(row) if row else None


def get_all_pom_cache(
    db_path: Optional[Path] = None,
) -> List[Dict]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as con:
        rows = con.execute(
            "SELECT * FROM pom_cache WHERE expires_at > ? ORDER BY page_name",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]
