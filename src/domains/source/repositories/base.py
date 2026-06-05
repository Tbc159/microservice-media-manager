from typing import Optional, Protocol


class SourceMediaRepository(Protocol):
    def find(
        self,
        media_type: str,
        title: Optional[str],
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        """Restituisce (items, total_count)."""
        ...
