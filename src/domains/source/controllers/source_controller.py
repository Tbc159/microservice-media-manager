"""Controller del dominio source: thin layer.

Il service viene assemblato dal factory (composition root), che sceglie repository e
storage backend in base all'ambiente. Il controller non conosce le implementazioni.
"""
from typing import Optional

from src.domains.source.factory import build_source_service
from src.domains.source.repositories.base import DuplicateObjectKeyError

_service = build_source_service()


def query_source_media(
    type: str,
    title: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[dict, int]:
    return _service.query(media_type=type, title=title, page=page, page_size=page_size), 200


def upload_source_media(body: dict, file) -> tuple[dict, int]:
    """Upload server-side multipart: byte -> storage, metadati -> DB.

    connexion passa i campi non-file in `body` (dict) e il file come FileStorage
    (`.filename`, `.read()`).
    """
    filename = (getattr(file, "filename", "") or "").strip()
    if not filename:
        return {"detail": "file mancante o privo di nome"}, 400
    try:
        item = _service.create(
            title=body["title"],
            media_type=body["media_type"],
            filename=filename,
            data=file.read(),
            duration_s=body.get("duration_s"),
        )
    except DuplicateObjectKeyError:
        return {"detail": f"media gia' presente: {body['media_type']}/{filename}"}, 409
    return item, 201
