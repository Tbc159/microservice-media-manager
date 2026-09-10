"""Business logic del dominio `media` come BFF pubblico.

Orchestra il dominio interno `source` tramite il gateway HTTP e ri-mappa gli URL
delle risorse byte da `/v0/source/...` al path pubblico `/v0/media/...`, cosi' che il
FrontEnd parli solo con `media`.
"""
import os
from typing import Optional
from urllib.parse import unquote, urlparse

from src import signed_url
from src.domains.media import fetcher
from src.domains.media.gateway import ContentResult, SourceGateway, UploadResult

_SOURCE_PREFIX = "/v0/source/media/"
_MEDIA_PREFIX = "/v0/media/"

# Tipi accettati dall'upload pubblico (i font restano solo interni: vedi source).
ACCEPTED_MEDIA_TYPES = frozenset({
    "audio/m4a", "audio/mpeg", "audio/mp3", "audio/wav",
    "video/mp4", "image/png", "image/jpeg", "image/webp",
})


class MediaTypeNotAccepted(Exception):
    """Il media_type (fornito o rilevato dal Content-Type) non e' fra quelli accettati -> 400."""

    def __init__(self, detected: str) -> None:
        self.detected = detected or "(nessuno)"
        super().__init__(self.detected)


def _filename_from_url(url: str) -> str:
    """Nome file dal path dell'URL (per Blossom = l'hash del contenuto -> dedup stabile)."""
    path = urlparse(url).path
    return unquote(path.rsplit("/", 1)[-1]) if path else ""


def _remap(item: dict) -> dict:
    """Riscrive content_url/download_url dal path interno (source) a quello pubblico (media)
    e allega l'URL firmato per i tag del browser (assente se la firma non e' configurata)."""
    out = dict(item)
    for key in ("content_url", "download_url"):
        value = out.get(key)
        if isinstance(value, str):
            out[key] = value.replace(_SOURCE_PREFIX, _MEDIA_PREFIX)
    if "id" in out:
        signed_url.decorate(out, out["id"])
    return out


class MediaService:
    def __init__(self, gateway: SourceGateway) -> None:
        self._gw = gateway

    def list(
        self,
        media_type: Optional[str] = None,
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

    def content(
        self,
        media_id: int,
        *,
        download: bool,
        range_header: Optional[str] = None,
        head: bool = False,
    ) -> Optional[ContentResult]:
        return self._gw.get_content(
            media_id, download=download, range_header=range_header, head=head
        )

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

    def upload_from_url(
        self,
        *,
        url: str,
        title: str,
        media_type: Optional[str] = None,
        duration_s: Optional[int] = None,
    ) -> UploadResult:
        """Scarica `url` (con difese SSRF) e crea il media delegando a source.

        Raises:
            fetcher.UrlNotAllowed: URL non consentito (schema/host non pubblico) -> 400.
            fetcher.ContentTooLarge: contenuto oltre il limite -> 413.
            fetcher.FetchFailed: download fallito -> 502.
            MediaTypeNotAccepted: tipo (fornito o rilevato) non accettato -> 400.
        Il duplicato arriva da source come UploadResult(status_code=409).
        """
        # Difesa SSRF sull'URL iniziale prima di aprire qualsiasi connessione.
        fetcher.assert_public_url(url)

        data, content_type = fetcher.fetch(
            url,
            max_bytes=int(os.environ.get("MEDIA_FETCH_MAX_BYTES", fetcher.MAX_BYTES)),
            timeout=float(os.environ.get("MEDIA_FETCH_TIMEOUT", fetcher.TIMEOUT_S)),
            max_redirects=int(os.environ.get("MEDIA_FETCH_MAX_REDIRECTS", fetcher.MAX_REDIRECTS)),
        )

        resolved_type = media_type or content_type
        if resolved_type not in ACCEPTED_MEDIA_TYPES:
            raise MediaTypeNotAccepted(resolved_type)

        filename = _filename_from_url(url) or "download"
        return self.upload(
            title=title,
            media_type=resolved_type,
            filename=filename,
            data=data,
            duration_s=duration_s,
        )
