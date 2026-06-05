from typing import Optional

_MOCK_DATA: list[dict] = [
    {
        "id": 1,
        "title": "Puntata pilota",
        "filename": "2024-01-puntata-pilota.m4a",
        "media_type": "audio/m4a",
        "file_path": "/data/media/2024-01-puntata-pilota.m4a",
        "size_bytes": 48_234_567,
        "created_at_s": 1700000000,
        "metadata": {},
    },
    {
        "id": 2,
        "title": "Intervista Mario",
        "filename": "2024-02-intervista-mario.m4a",
        "media_type": "audio/m4a",
        "file_path": "/data/media/2024-02-intervista-mario.m4a",
        "size_bytes": 31_100_000,
        "created_at_s": 1700086400,
        "metadata": {},
    },
    {
        "id": 3,
        "title": "Sigla intro",
        "filename": "2024-03-sigla-intro.mp3",
        "media_type": "audio/mp3",
        "file_path": "/data/media/2024-03-sigla-intro.mp3",
        "size_bytes": 3_200_000,
        "created_at_s": 1700172800,
        "metadata": {"author": "Studio"},
    },
]


class MockSourceMediaRepository:
    def find(
        self,
        media_type: str,
        title: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        results = [r for r in _MOCK_DATA if r["media_type"] == media_type]
        if title is not None:
            results = [r for r in results if r["title"] == title]
        total = len(results)
        start = (page - 1) * page_size
        return results[start : start + page_size], total
