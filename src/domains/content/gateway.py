"""Gateway HTTP verso il dominio `source` (interno) per il dominio `content`.

`content` e' un BFF pubblico di *generazione immagini*: legge gli asset (logo, avatar)
da source e vi salva l'immagine prodotta, sulla rete docker interna (`source:8080`),
NON tramite SDK generato (il runtime non usa `generated/`).

Differenza rispetto al gateway di `media`: qui servono i **byte veri** degli asset per
darli in pasto a Pillow, quindi `get_bytes` **segue i redirect** (il 302 verso lo storage
in coll/prod) invece di propagarli.
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
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 300.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._timeout = timeout

    def resolve_filename(self, filename: str) -> Optional[dict]:
        """Risolve un asset per nome file -> record (o None se assente)."""
        r = httpx.get(
            f"{self._base}/media/by-filename/{quote(filename, safe='')}",
            headers=self._headers,
            timeout=self._timeout,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def list_by_type(self, media_type: str, page_size: int = 100) -> list[dict]:
        """Elenco (non paginato) dei media di un tipo. Usato per il catalogo font."""
        r = httpx.get(
            f"{self._base}/media",
            params={"type": media_type, "page": 1, "page_size": page_size},
            headers=self._headers,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json().get("items", [])

    def get_bytes(self, media_id: int) -> Optional[bytes]:
        """Byte di un media per id. Segue il 302 (coll/prod) per ottenere i byte reali.
        None se l'id non esiste o i byte mancano (404)."""
        r = httpx.get(
            f"{self._base}/media/{media_id}/content",
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=True,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def upload_image(
        self, *, title: str, media_type: str, filename: str, data: bytes
    ) -> UploadResult:
        """Salva l'immagine generata come media su source (multipart server-side)."""
        files = {"file": (filename, data, media_type)}
        r = httpx.post(
            f"{self._base}/media",
            data={"title": title, "media_type": media_type},
            files=files,
            headers=self._headers,
            timeout=self._timeout,
        )
        payload = (
            r.json()
            if r.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return UploadResult(status_code=r.status_code, payload=payload)
