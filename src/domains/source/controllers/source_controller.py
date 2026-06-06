"""Controller del dominio source: thin layer.

Il service viene assemblato dal factory (composition root), che sceglie repository e
storage backend in base all'ambiente. Il controller non conosce le implementazioni.
"""
from typing import Optional

import flask

from src.domains.source.factory import build_source_service
from src.domains.source.repositories.base import DuplicateObjectKeyError

_service = build_source_service()

# connexion coerce i boolean SOLO da "true"/"false"; per accettare anche "1" trattiamo
# il parametro come stringa e valutiamo noi i valori veri.
_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value) -> bool:
    return value is not None and str(value).strip().lower() in _TRUTHY


def query_source_media(
    type: str,
    title: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[dict, int]:
    return _service.query(media_type=type, title=title, page=page, page_size=page_size), 200


def get_source_media(id: int):
    """Metadati del singolo media (i byte sono su /content)."""
    item = _service.get_item(id)
    return (item, 200) if item is not None else ("", 404)


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


def get_source_media_content(id: int, download: Optional[str] = None):
    """Byte del media. `?download=1|true|yes|on` -> allegato, altrimenti inline.
    coll/prod -> 302 verso URL pre-firmato; dev -> streaming dal FS (con Range).
    404 se l'id non esiste o i byte mancano."""
    as_attachment = _is_truthy(download)
    target = _service.content(id, download=as_attachment)
    if target is None:
        return "", 404
    if target.redirect_url:
        return "", 302, {"Location": target.redirect_url}
    return flask.send_file(
        target.local_path,
        mimetype="application/octet-stream",
        as_attachment=as_attachment,
        download_name=target.filename,
        conditional=True,
    )
