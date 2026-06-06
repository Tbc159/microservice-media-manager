from typing import Optional, Protocol


class DuplicateObjectKeyError(Exception):
    """Sollevata da insert() quando l'object_key esiste gia' (vincolo di unicita').

    Astrae il conflitto di persistenza: il controller la traduce in 409 senza
    dipendere dal backend concreto (sqlite3.IntegrityError o check in-memory).
    """


class SourceMediaRepository(Protocol):
    """Astrazione di persistenza dei metadati media.

    Disaccoppia il SourceService dallo storage concreto: Mock (statico, dev/test)
    e Sqlite (coll/prod) sono intercambiabili senza toccare service ne' controller.
    I record restituiti contengono `object_key` (riferimento interno allo storage);
    il service lo traduce in `content_url`/`download_url` prima di esporlo via API.
    """

    def find(
        self,
        media_type: str,
        title: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        """Restituisce (items, total_count) filtrando per media_type ed eventuale title."""
        ...

    def get(self, media_id: int) -> Optional[dict]:
        """Restituisce il record con quell'id, o None se assente."""
        ...

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
        """Inserisce un nuovo record e ne restituisce l'id. Usato da seeding e futuro POST."""
        ...
