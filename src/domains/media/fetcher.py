"""Download lato server di un URL esterno, con difese contro SSRF.

Usato dall'endpoint PUBBLICO `POST /v0/media/from-url`: l'URL arriva dall'esterno, quindi il
fetch deve essere blindato prima ancora di delegare a `source` la creazione del media.

Difese:
  - solo schemi http/https;
  - l'host non deve risolvere su indirizzi privati/loopback/link-local/riservati (SSRF verso
    la rete interna o l'endpoint metadata del cloud);
  - limite di dimensione (streaming con abort) e timeout;
  - massimo N redirect, **rivalidando ogni hop** (un 302 verso http://169.254.169.254 non deve
    passare).

La guardia su schema/IP e' condivisa (`src/net_guard.py`): la usa anche `feed`. Qui sopra
resta la parte specifica del download (dimensione, timeout, redirect rivalidati).
"""
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from src.net_guard import HostNotAllowed, assert_public_host, ip_disallowed  # noqa: F401

MAX_BYTES = 200 * 1024 * 1024  # 200 MB
TIMEOUT_S = 30.0
MAX_REDIRECTS = 3
_ALLOWED_SCHEMES = ("http", "https")


class UrlNotAllowed(Exception):
    """URL rifiutato prima/durante il fetch (schema, host, o IP non pubblico) -> 400."""


class ContentTooLarge(Exception):
    """Contenuto oltre il limite di dimensione -> 413."""


class FetchFailed(Exception):
    """Fetch fallito (timeout, errore remoto, troppi redirect) -> 502."""


def assert_public_url(url: str) -> None:
    """Solleva UrlNotAllowed se l'URL non e' http/https o risolve su un indirizzo non pubblico."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UrlNotAllowed(f"schema non consentito: {parsed.scheme or '(vuoto)'} (solo http/https)")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        assert_public_host(parsed.hostname, port)
    except HostNotAllowed as exc:
        raise UrlNotAllowed(str(exc)) from exc


def fetch(
    url: str,
    *,
    max_bytes: int = MAX_BYTES,
    timeout: float = TIMEOUT_S,
    max_redirects: int = MAX_REDIRECTS,
    client: Optional[httpx.Client] = None,
) -> tuple[bytes, str]:
    """Scarica l'URL e restituisce (byte, content_type-normalizzato).

    I redirect sono seguiti a mano (max `max_redirects`) e ogni hop e' rivalidato con
    assert_public_url. `client` iniettabile per i test (httpx.MockTransport).
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=False)
    current = url
    try:
        for _ in range(max_redirects + 1):
            assert_public_url(current)
            with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        raise FetchFailed("redirect senza header Location")
                    current = urljoin(current, location)
                    continue
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ContentTooLarge(f"contenuto oltre il limite di {max_bytes} byte")
                    chunks.append(chunk)
                return b"".join(chunks), content_type
        raise FetchFailed(f"troppi redirect (>{max_redirects})")
    except (UrlNotAllowed, ContentTooLarge):
        raise
    except httpx.HTTPStatusError as exc:
        raise FetchFailed(f"risposta remota {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise FetchFailed(str(exc)) from exc
    finally:
        if owns_client:
            client.close()
