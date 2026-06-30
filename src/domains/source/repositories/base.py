from typing import Optional, Protocol

# Estensioni note rimosse in fase di normalizzazione (per matchare "x.ttf" con "x").
_KNOWN_EXTS = {
    "ttf", "otf", "ttc", "png", "jpg", "jpeg", "webp", "gif", "mp3", "m4a", "mp4", "wav",
}


def normalize_asset_name(name: str) -> str:
    """Forma normalizzata di un nome asset per il match tollerante.

    Minuscole, estensione nota rimossa, separatori (trattino/underscore/spazio) collassati.
    Cosi' `Montserrat-Bold.ttf`, `montserrat-bold` e `montserrat bold` coincidono.
    """
    s = name.strip().lower()
    if "." in s:
        stem, ext = s.rsplit(".", 1)
        if ext in _KNOWN_EXTS:
            s = stem
    for sep in ("-", "_", " "):
        s = s.replace(sep, "")
    return s


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

    def find_by_filename(self, filename: str) -> Optional[dict]:
        """Risolve un media per nome file **esatto**. Il filename non e' univoco (l'unicita'
        e' sull'object_key = media_type/filename): in caso di collisione tra tipi diversi
        restituisce il piu' recente. None se nessun record corrisponde."""
        ...

    def find_by_name(self, name: str) -> Optional[dict]:
        """Risolve un media per nome in modo **tollerante**: prima il match esatto sul
        filename, poi un match normalizzato (vedi normalize_asset_name) che ignora
        maiuscole, estensione e separatori. In caso di piu' candidati, il piu' recente."""
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
