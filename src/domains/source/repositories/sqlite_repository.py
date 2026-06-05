"""Repository SQLite del dominio source.

Read-heavy / write-rare: WAL mode permette N lettori concorrenti + 1 scrittore.
connexion 3.x esegue le view sync in un threadpool: SQLite non condivide connessioni
tra thread, quindi qui si apre una connessione per chiamata (open su file gia' esistente
e' nell'ordine dei microsecondi). Lo schema e' creato all'avvio in modo idempotente.
"""
import json
import sqlite3
from pathlib import Path
from typing import Optional

from .schema import SCHEMA_SQL

_SELECT_COLS = (
    "id, title, filename, media_type, object_key, "
    "size_bytes, duration_s, created_at_s, status, metadata"
)


class SqliteSourceMediaRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-65536")  # 64 MB
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict:
        rec = dict(row)
        raw = rec.get("metadata")
        rec["metadata"] = json.loads(raw) if raw else {}
        return rec

    def find(
        self,
        media_type: str,
        title: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        where = "WHERE media_type = ?"
        params: list = [media_type]
        if title is not None:
            where += " AND title = ?"
            params.append(title)

        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM source_media {where}", params
            ).fetchone()[0]

            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT {_SELECT_COLS} FROM source_media {where} "
                "ORDER BY created_at_s DESC, id DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()

        return [self._row_to_record(r) for r in rows], total

    def insert(
        self,
        *,
        title: str,
        filename: str,
        media_type: str,
        object_key: str,
        size_bytes: Optional[int] = None,
        duration_s: Optional[int] = None,
        status: str = "ready",
        metadata: Optional[dict] = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO source_media "
                "(title, filename, media_type, object_key, size_bytes, "
                " duration_s, status, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    filename,
                    media_type,
                    object_key,
                    size_bytes,
                    duration_s,
                    status,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
