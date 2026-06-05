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
