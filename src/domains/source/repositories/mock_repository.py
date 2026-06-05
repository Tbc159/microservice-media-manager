"""Repository in-memory: dev veloce (`python -m src.app`) e unit test, senza DB.

Stessa interfaccia di SqliteSourceMediaRepository (object_key incluso): il service
non distingue i due. I dati sono per-istanza, cosi' insert() non sporca altri test.
"""
import copy
from typing import Optional

_SEED: list[dict] = [
    {
        "id": 1,
        "title": "Puntata pilota",
        "filename": "2024-01-puntata-pilota.m4a",
        "media_type": "audio/m4a",
        "object_key": "audio/m4a/2024-01-puntata-pilota.m4a",
        "size_bytes": 48_234_567,
        "duration_s": 3012,
        "created_at_s": 1700000000,
        "status": "ready",
        "metadata": {},
    },
    {
        "id": 2,
        "title": "Intervista Mario",
        "filename": "2024-02-intervista-mario.m4a",
        "media_type": "audio/m4a",
        "object_key": "audio/m4a/2024-02-intervista-mario.m4a",
        "size_bytes": 31_100_000,
        "duration_s": 1980,
        "created_at_s": 1700086400,
        "status": "ready",
        "metadata": {},
    },
    {
        "id": 3,
        "title": "Sigla intro",
        "filename": "2024-03-sigla-intro.mp3",
        "media_type": "audio/mp3",
        "object_key": "audio/mp3/2024-03-sigla-intro.mp3",
        "size_bytes": 3_200_000,
        "duration_s": 42,
        "created_at_s": 1700172800,
        "status": "ready",
        "metadata": {"author": "Studio"},
    },
]


class MockSourceMediaRepository:
    def __init__(self) -> None:
        self._data: list[dict] = copy.deepcopy(_SEED)

    def find(
        self,
        media_type: str,
        title: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        results = [r for r in self._data if r["media_type"] == media_type]
        if title is not None:
            results = [r for r in results if r["title"] == title]
        total = len(results)
        start = (page - 1) * page_size
        return copy.deepcopy(results[start : start + page_size]), total

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
        new_id = max((r["id"] for r in self._data), default=0) + 1
        self._data.append(
            {
                "id": new_id,
                "title": title,
                "filename": filename,
                "media_type": media_type,
                "object_key": object_key,
                "size_bytes": size_bytes,
                "duration_s": duration_s,
                "created_at_s": 1700000000 + new_id,
                "status": status,
                "metadata": metadata or {},
            }
        )
        return new_id
