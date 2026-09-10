"""Gateway HTTP verso il dominio `source` (interno) per il dominio `audio`.

Risolve i `MediaRef` (id o filename), scarica i byte degli input e carica i media prodotti,
sulla rete docker interna (`source:8080`), via HTTP diretto (il runtime non usa `generated/`).
Come per `content`, `get_bytes` segue i redirect per ottenere i byte reali in coll/prod.
"""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import httpx


@dataclass
class UploadResult:
    status_code: int
    payload: dict


class SourceGateway:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 600.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._timeout = timeout

    def get_by_id(self, media_id: int) -> Optional[dict]:
        r = httpx.get(f"{self._base}/media/{media_id}", headers=self._headers, timeout=self._timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def resolve_filename(self, filename: str) -> Optional[dict]:
        r = httpx.get(
            f"{self._base}/media/by-filename/{quote(filename, safe='')}",
            headers=self._headers, timeout=self._timeout,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def get_bytes(self, media_id: int) -> Optional[bytes]:
        r = httpx.get(
            f"{self._base}/media/{media_id}/content",
            headers=self._headers, timeout=self._timeout, follow_redirects=True,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def upload_media(
        self, *, title: str, media_type: str, filename: str, data: bytes,
        duration_s: Optional[int] = None,
    ) -> UploadResult:
        form: dict = {"title": title, "media_type": media_type}
        if duration_s is not None:
            form["duration_s"] = str(duration_s)
        files = {"file": (filename, data, media_type)}
        r = httpx.post(
            f"{self._base}/media", data=form, files=files,
            headers=self._headers, timeout=self._timeout,
        )
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return UploadResult(status_code=r.status_code, payload=payload)
