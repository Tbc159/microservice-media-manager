"""Business logic del dominio source.

Orchestrazione: legge i record dal repository (storage-agnostico) e li traduce nel
DTO dell'API arricchendoli con lo stream_url pre-firmato preso dallo StorageBackend.
Il campo interno `object_key` non viene mai esposto.
"""
import math
from typing import Optional

from src.domains.source.repositories.base import SourceMediaRepository
from src.domains.source.storage.base import StorageBackend

# URL pre-firmati validi 1h: abbastanza per avviare e fare seek del playback,
# abbastanza corti da non diventare link permanenti condivisibili.
_STREAM_URL_TTL_S = 3600


class SourceService:
    def __init__(self, repo: SourceMediaRepository, storage: StorageBackend) -> None:
        self._repo = repo
        self._storage = storage

    def _to_dto(self, record: dict) -> dict:
        dto = {k: v for k, v in record.items() if k != "object_key"}
        dto["stream_url"] = self._storage.get_stream_url(
            record["object_key"], ttl_seconds=_STREAM_URL_TTL_S
        )
        return dto

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
