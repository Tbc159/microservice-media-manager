"""Business logic del dominio `media` come BFF pubblico.

Orchestra il dominio interno `source` tramite il gateway HTTP e ri-mappa gli URL
delle risorse byte da `/v0/source/...` al path pubblico `/v0/media/...`, cosi' che il
FrontEnd parli solo con `media`.
"""
from typing import Optional

from src.domains.media.gateway import ContentResult, SourceGateway, UploadResult

_SOURCE_PREFIX = "/v0/source/media/"
_MEDIA_PREFIX = "/v0/media/"


def _remap(item: dict) -> dict:
    """Riscrive content_url/download_url dal path interno (source) a quello pubblico (media)."""
    out = dict(item)
    for key in ("content_url", "download_url"):
        value = out.get(key)
        if isinstance(value, str):
            out[key] = value.replace(_SOURCE_PREFIX, _MEDIA_PREFIX)
    return out


class MediaService:
    def __init__(self, gateway: SourceGateway) -> None:
        self._gw = gateway

    def list(
        self,
        media_type: str,
        title: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        env = self._gw.list_media(
            media_type=media_type, title=title, page=page, page_size=page_size
        )
        env["items"] = [_remap(i) for i in env.get("items", [])]
        return env

    def get(self, media_id: int) -> Optional[dict]:
        item = self._gw.get_media(media_id)
        return _remap(item) if item is not None else None

    def content(self, media_id: int, *, download: bool) -> Optional[ContentResult]:
        return self._gw.get_content(media_id, download=download)

    def upload(
        self,
        *,
        title: str,
        media_type: str,
        filename: str,
        data: bytes,
        duration_s: Optional[int] = None,
    ) -> UploadResult:
        result = self._gw.upload_media(
            title=title,
            media_type=media_type,
            filename=filename,
            data=data,
            duration_s=duration_s,
        )
        if result.status_code == 201:
            result = UploadResult(status_code=201, payload=_remap(result.payload))
        return result
