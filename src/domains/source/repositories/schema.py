"""Schema canonico del DB SQLite del dominio source.

Unica fonte di verita' a runtime: SqliteSourceMediaRepository esegue questo DDL
all'avvio (idempotente, IF NOT EXISTS). object_key e' il riferimento interno allo
storage (FS locale in dev, oggetto MinIO/S3 in coll/prod); NON viene esposto
dall'API, che restituisce invece i link content_url/download_url verso /content.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_media (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    filename     TEXT    NOT NULL,
    media_type   TEXT    NOT NULL,
    object_key   TEXT    NOT NULL UNIQUE,
    size_bytes   INTEGER,
    duration_s   INTEGER,
    created_at_s INTEGER NOT NULL DEFAULT (unixepoch()),
    status       TEXT    NOT NULL DEFAULT 'ready',
    metadata     TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_media_type   ON source_media(media_type);
CREATE INDEX IF NOT EXISTS idx_source_media_title  ON source_media(title);
CREATE INDEX IF NOT EXISTS idx_source_media_status ON source_media(status);
"""
