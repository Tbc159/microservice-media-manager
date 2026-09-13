"""Cache persistente `url -> Content-Length` per gli enclosure.

NIP-F4 non porta la dimensione del file, ma RSS vuole `length` nell'enclosure: l'unico modo di
saperla e' una HEAD sull'URL. Farla a ogni generazione del feed significherebbe una richiesta
per episodio a ogni rigenerazione.

La cache non scade: gli URL Blossom sono **content-addressed** (il nome e' l'hash del
contenuto), quindi a URL uguale corrisponde per costruzione lo stesso byte-stream. Per gli URL
non Blossom vale la stessa assunzione degli aggregatori: un enclosure non cambia sotto lo
stesso indirizzo. Si memorizzano anche i fallimenti (length NULL) per non ritentare a raffica.
"""
import os
import sqlite3
import time
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS enclosure (
    url        TEXT PRIMARY KEY,
    length     INTEGER,
    checked_at INTEGER NOT NULL
);
"""
_RETRY_FAILED_AFTER_S = 3600      # un fallimento non e' definitivo: si ritenta dopo un'ora


def db_path() -> str:
    return os.environ.get("FEED_DB_PATH", "/data/feed.db")


class EnclosureStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or db_path()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, url: str, *, now: Optional[int] = None):
        """`(trovato, length)`. `trovato=False` se assente o se un fallimento e' da ritentare."""
        now = int(now if now is not None else time.time())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT length, checked_at FROM enclosure WHERE url = ?", (url,)
            ).fetchone()
        if row is None:
            return False, None
        length, checked_at = row
        if length is None and now - checked_at > _RETRY_FAILED_AFTER_S:
            return False, None
        return True, length

    def put(self, url: str, length: Optional[int], *, now: Optional[int] = None) -> None:
        now = int(now if now is not None else time.time())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO enclosure (url, length, checked_at) VALUES (?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET length = excluded.length, "
                "checked_at = excluded.checked_at",
                (url, length, now),
            )
