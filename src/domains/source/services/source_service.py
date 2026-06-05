import math
from typing import Optional

from src.domains.source.repositories.base import SourceMediaRepository


class SourceService:
    def __init__(self, repo: SourceMediaRepository) -> None:
        self._repo = repo

    def query(
        self,
        media_type: str,
        title: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        items, total = self._repo.find(media_type, title, page, page_size)
        total_pages = math.ceil(total / page_size) if total > 0 else 0
        return {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }
