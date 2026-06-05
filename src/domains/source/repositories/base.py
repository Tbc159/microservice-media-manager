from typing import Optional, Protocol


class SourceMediaRepository(Protocol):
    """Astrazione di persistenza dei metadati media.

    Disaccoppia il SourceService dallo storage concreto: Mock (statico, dev/test)
    e Sqlite (coll/prod) sono intercambiabili senza toccare service ne' controller.
    I record restituiti contengono `object_key` (riferimento interno allo storage);
    il service lo traduce in `stream_url` prima di esporlo via API.
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
