from typing import Optional

from src.domains.source.repositories.mock_repository import MockSourceMediaRepository
from src.domains.source.services.source_service import SourceService

_service = SourceService(repo=MockSourceMediaRepository())


def query_source_media(
    type: str,
    title: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[dict, int]:
    return _service.query(media_type=type, title=title, page=page, page_size=page_size), 200
