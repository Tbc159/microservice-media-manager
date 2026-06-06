"""Gateway HTTP verso il dominio `source` (interno).

`media` e' il BFF pubblico: orchestra `source` sulla rete docker interna
(`source:8080`), NON tramite SDK generato (il runtime non usa `generated/`). I metodi
rispecchiano gli endpoint di source; il re-mapping degli URL (`/v0/source` -> `/v0/media`)
e' compito del service, non del gateway.

Per il download: `get_content` NON segue i redirect, cosi' il service puo' decidere:
- source risponde 302 (coll/prod) -> media propaga il 302 (resta fuori dai byte);
- source risponde 200 (dev locale) -> media relaia i byte.
"""
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class ContentResult:
    redirect_url: Optional[str] = None       # coll/prod: 302 verso lo storage
    body: Optional[bytes] = None             # dev: byte relayati da source
    content_type: Optional[str] = None
    content_disposition: Optional[str] = None


@dataclass
class UploadResult:
    status_code: int
    payload: dict


class SourceGateway:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 300.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._timeout = timeout

    def list_media(
        self,
        *,
        media_type: str,
        title: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        params: dict = {"type": media_type, "page": page, "page_size": page_size}
        if title is not None:
            params["title"] = title
        r = httpx.get(
            f"{self._base}/media", params=params, headers=self._headers, timeout=self._timeout
        )
        r.raise_for_status()
        return r.json()

    def get_media(self, media_id: int) -> Optional[dict]:
        r = httpx.get(
            f"{self._base}/media/{media_id}", headers=self._headers, timeout=self._timeout
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def get_content(self, media_id: int, *, download: bool) -> Optional[ContentResult]:
        params = {"download": "1"} if download else {}
        r = httpx.get(
            f"{self._base}/media/{media_id}/content",
            params=params,
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=False,
        )
        if r.status_code == 404:
            return None
        if r.status_code in (301, 302, 303, 307, 308):
            return ContentResult(redirect_url=r.headers.get("location"))
        r.raise_for_status()
        return ContentResult(
            body=r.content,
            content_type=r.headers.get("content-type"),
            content_disposition=r.headers.get("content-disposition"),
        )

    def upload_media(
        self,
        *,
        title: str,
        media_type: str,
        filename: str,
        data: bytes,
        duration_s: Optional[int] = None,
    ) -> UploadResult:
        form: dict = {"title": title, "media_type": media_type}
        if duration_s is not None:
            form["duration_s"] = str(duration_s)
        files = {"file": (filename, data, media_type)}
        r = httpx.post(
            f"{self._base}/media",
            data=form,
            files=files,
            headers=self._headers,
            timeout=self._timeout,
        )
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return UploadResult(status_code=r.status_code, payload=payload)
