"""Controller del dominio `media` (BFF pubblico su `source`).

Thin layer: delega al MediaService (gateway verso source) e traduce gli esiti in
risposte HTTP. Per i byte: 302 (propagato da source in coll/prod) oppure relay dei
byte (dev).
"""
from typing import Optional

import flask

from src.domains.media.factory import build_media_service

_service = build_media_service()

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value) -> bool:
    return value is not None and str(value).strip().lower() in _TRUTHY


def list_media(
    type: str,
    title: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[dict, int]:
    return _service.list(media_type=type, title=title, page=page, page_size=page_size), 200


def get_media(id: int):
    item = _service.get(id)
    return (item, 200) if item is not None else ("", 404)


def get_media_content(id: int, download: Optional[str] = None):
    req = flask.request
    is_head = req.method == "HEAD"
    result = _service.content(
        id,
        download=_is_truthy(download),
        range_header=req.headers.get("Range"),
        head=is_head,
    )
    if result is None:
        return "", 404
    if result.redirect_url:
        return "", 302, {"Location": result.redirect_url}
    # Accept-Ranges + propagazione del Range: i player (Kodi, browser) possono "seekare"
    # per leggere il moov dei .m4a non-faststart.
    headers = {
        "Content-Type": result.content_type or "application/octet-stream",
        "Accept-Ranges": result.accept_ranges or "bytes",
    }
    if result.content_disposition:
        headers["Content-Disposition"] = result.content_disposition
    if result.content_range:
        headers["Content-Range"] = result.content_range
    if is_head and result.content_length:
        headers["Content-Length"] = result.content_length
    return result.body, result.status_code, headers


def upload_media(body: dict, file):
    filename = (getattr(file, "filename", "") or "").strip()
    if not filename:
        return {"detail": "file mancante o privo di nome"}, 400
    result = _service.upload(
        title=body["title"],
        media_type=body["media_type"],
        filename=filename,
        data=file.read(),
        duration_s=body.get("duration_s"),
    )
    return result.payload, result.status_code
