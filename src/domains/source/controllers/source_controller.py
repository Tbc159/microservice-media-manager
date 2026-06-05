"""Controller del dominio source: thin layer.

Il service viene assemblato dal factory (composition root), che sceglie repository e
storage backend in base all'ambiente. Il controller non conosce le implementazioni.
"""
from typing import Optional

from src.domains.source.factory import build_source_service

_service = build_source_service()


def query_source_media(
    type: str,
    title: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[dict, int]:
    return _service.query(media_type=type, title=title, page=page, page_size=page_size), 200
