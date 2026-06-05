"""SQLite repository — placeholder per integrazione futura.

Attivare quando SOURCE_DB_PATH e' disponibile nel container e il volume e' montato.
Schema atteso (DDL in deploy/source/schema.sql, da creare):

    CREATE TABLE source_media (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        title        TEXT    NOT NULL,
        filename     TEXT    NOT NULL,
        media_type   TEXT    NOT NULL,
        file_path    TEXT    NOT NULL,
        size_bytes   INTEGER,
        created_at_s INTEGER NOT NULL,
        metadata     TEXT            -- JSON serializzato
    );
    CREATE INDEX idx_source_media_type ON source_media(media_type);
    CREATE INDEX idx_source_media_title ON source_media(title);
"""
from typing import Optional


class SqliteSourceMediaRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def find(
        self,
        media_type: str,
        title: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        raise NotImplementedError(
            "SqliteSourceMediaRepository non e' ancora implementato. "
            "Usare MockSourceMediaRepository finche' SOURCE_DB_PATH non e' attivo."
        )
