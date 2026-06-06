"""Business logic del dominio source.

Orchestrazione: legge i record dal repository (storage-agnostico) e li traduce nel
DTO dell'API, esponendo i link `content_url`/`download_url` verso la sotto-risorsa /content.
Il campo interno `object_key` non viene mai esposto.
"""
import math
from dataclasses import dataclass
from typing import Optional

from src.domains.source.repositories.base import SourceMediaRepository
from src.domains.source.storage.base import StorageBackend


@dataclass
class DownloadTarget:
    """Esito di una richiesta di download, discriminato per backend.

    - redirect_url valorizzato -> coll/prod: il controller risponde 302 verso lo storage.
    - local_path valorizzato   -> dev: il controller streamma il file dal FS.
    """

    filename: str
    redirect_url: Optional[str] = None
    local_path: Optional[str] = None

# URL pre-firmati validi 1h: abbastanza per avviare e fare seek del playback,
# abbastanza corti da non diventare link permanenti condivisibili.
_STREAM_URL_TTL_S = 3600


class SourceService:
    def __init__(self, repo: SourceMediaRepository, storage: StorageBackend) -> None:
        self._repo = repo
        self._storage = storage

    def _to_dto(self, record: dict) -> dict:
        # object_key (interno) non viene mai esposto; al suo posto i link all'endpoint /content.
        dto = {k: v for k, v in record.items() if k != "object_key"}
        content_url = f"/v0/source/media/{record['id']}/content"
        dto["content_url"] = content_url
        dto["download_url"] = f"{content_url}?download=1"
        return dto

    def get_item(self, media_id: int) -> Optional[dict]:
        """Metadati del singolo media, o None se l'id non esiste."""
        record = self._repo.get(media_id)
        return self._to_dto(record) if record is not None else None

    def query(
        self,
        media_type: str,
        title: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        records, total = self._repo.find(media_type, title, page, page_size)
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return {
            "items": [self._to_dto(r) for r in records],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }

    @staticmethod
    def _object_key(media_type: str, filename: str) -> str:
        # es. audio/m4a/<filename> — namespacing per MIME type
        return f"{media_type}/{filename}"

    def create(
        self,
        *,
        title: str,
        media_type: str,
        filename: str,
        data: bytes,
        duration_s: Optional[int] = None,
    ) -> dict:
        """Upload server-side: prima il metadato (rileva i duplicati senza scrivere
        byte orfani), poi i byte nello storage. Restituisce il record creato."""
        object_key = self._object_key(media_type, filename)
        new_id = self._repo.insert(
            title=title,
            filename=filename,
            media_type=media_type,
            object_key=object_key,
            size_bytes=len(data),
            duration_s=duration_s,
        )
        self._storage.put_object(object_key, data, media_type)
        return self._to_dto(self._repo.get(new_id))

    def presigned_upload_url(
        self,
        *,
        media_type: str,
        filename: str,
        ttl_seconds: int = _STREAM_URL_TTL_S,
    ) -> Optional[str]:
        """Predisposizione del flusso pre-signed (coll/prod): URL PUT per upload
        diretto browser -> storage. None con storage locale (dev): in quel caso si
        usa l'upload server-side (create)."""
        object_key = self._object_key(media_type, filename)
        return self._storage.get_upload_url(object_key, ttl_seconds=ttl_seconds)

    def content(self, media_id: int, *, download: bool) -> Optional[DownloadTarget]:
        """Prepara i byte del media. None se l'id non esiste o i byte mancano.
        download=True -> allegato (save); False -> inline (play). coll/prod -> redirect_url
        (URL pre-firmato con la disposition giusta); dev -> local_path (file su FS)."""
        record = self._repo.get(media_id)
        if record is None:
            return None
        object_key = record["object_key"]
        filename = record["filename"]
        if download:
            url = self._storage.get_download_url(
                object_key, filename=filename, ttl_seconds=_STREAM_URL_TTL_S
            )
        else:
            url = self._storage.get_stream_url(object_key, ttl_seconds=_STREAM_URL_TTL_S)
        if url:
            return DownloadTarget(filename=filename, redirect_url=url)
        path = self._storage.local_path(object_key)
        if path:
            return DownloadTarget(filename=filename, local_path=path)
        return None  # record presente ma byte assenti
