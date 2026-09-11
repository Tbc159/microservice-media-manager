"""Store dei job (e cache analisi) su SQLite — **persistente**, sopravvive al riavvio.

Il vecchio servizio teneva i job in un dizionario in memoria: un riavvio li perdeva e piu' di
un worker non poteva funzionare. Qui lo stato e' su file (WAL, connessione per-chiamata come
`source`). All'avvio i job rimasti `running` (processo morto a meta') tornano `queued`.
`claim_next` rivendica un job in modo atomico (BEGIN IMMEDIATE), cosi' piu' worker non lo
eseguono due volte.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_job (
    job_id       TEXT PRIMARY KEY,
    op           TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued',
    params       TEXT NOT NULL,
    result       TEXT,
    error        TEXT,
    created_at_s INTEGER NOT NULL,
    updated_at_s INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audio_job_status ON audio_job(status, created_at_s);

CREATE TABLE IF NOT EXISTS audio_analysis (
    media_id     INTEGER PRIMARY KEY,
    analysis     TEXT NOT NULL,
    created_at_s INTEGER NOT NULL
);
"""

_COLS = "job_id, op, status, params, result, error, created_at_s, updated_at_s"


class JobStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def _to_job(row: sqlite3.Row) -> dict:
        job = dict(row)
        job["params"] = json.loads(job["params"])
        job["result"] = json.loads(job["result"]) if job["result"] else None
        job["error"] = json.loads(job["error"]) if job["error"] else None
        return job

    def create(self, job_id: str, op: str, params: dict) -> dict:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audio_job (job_id, op, status, params, created_at_s, updated_at_s) "
                "VALUES (?, ?, 'queued', ?, ?, ?)",
                (job_id, op, json.dumps(params), now, now),
            )
            conn.commit()
        return self.get(job_id)

    def get(self, job_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM audio_job WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._to_job(row) if row else None

    def claim_next(self) -> Optional[dict]:
        """Rivendica atomicamente il job `queued` piu' vecchio -> `running`. None se nessuno."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT job_id FROM audio_job WHERE status='queued' "
                "ORDER BY created_at_s, job_id LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            job_id = row["job_id"]
            conn.execute(
                "UPDATE audio_job SET status='running', updated_at_s=? WHERE job_id=?",
                (int(time.time()), job_id),
            )
            conn.commit()
        return self.get(job_id)

    def set_succeeded(self, job_id: str, result: dict) -> None:
        self._finish(job_id, "succeeded", result_json=json.dumps(result))

    def set_failed(self, job_id: str, error: dict) -> None:
        self._finish(job_id, "failed", error_json=json.dumps(error))

    def _finish(self, job_id, status, *, result_json=None, error_json=None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE audio_job SET status=?, result=?, error=?, updated_at_s=? WHERE job_id=?",
                (status, result_json, error_json, int(time.time()), job_id),
            )
            conn.commit()

    def requeue_running(self) -> int:
        """All'avvio: i job rimasti `running` (processo precedente morto) tornano `queued`."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE audio_job SET status='queued', updated_at_s=? WHERE status='running'",
                (int(time.time()),),
            )
            conn.commit()
            return cur.rowcount

    # ── cache analisi (riuso: l'analisi e' associata al media, non ricalcolata) ──

    def get_analysis(self, media_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT analysis FROM audio_analysis WHERE media_id = ?", (media_id,)
            ).fetchone()
        return json.loads(row["analysis"]) if row else None

    def put_analysis(self, media_id: int, analysis: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audio_analysis (media_id, analysis, created_at_s) VALUES (?, ?, ?) "
                "ON CONFLICT(media_id) DO UPDATE SET analysis=excluded.analysis",
                (media_id, json.dumps(analysis), int(time.time())),
            )
            conn.commit()
