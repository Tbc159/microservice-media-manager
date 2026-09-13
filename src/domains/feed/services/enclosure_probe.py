"""Dimensione di un enclosure via HEAD, con guardia SSRF e cache.

L'URL viene da un evento Nostr, cioe' dall'esterno: la stessa guardia del download di
`media` (`src/net_guard.py`) impedisce di usare questa HEAD per sondare la rete interna.
Un fallimento non e' un errore del feed: si restituisce None e il chiamante mette `length="0"`
con un commento, perche' un item senza enclosure non e' un episodio per nessun aggregatore.
"""
import logging
import os
from typing import Dict, Iterable, Optional
from urllib.parse import urlparse

import httpx

from src.net_guard import HostNotAllowed, assert_public_host

logger = logging.getLogger("feed")

_TIMEOUT_S = 5.0


def timeout_s() -> float:
    try:
        return float(os.environ.get("FEED_HEAD_TIMEOUT_S", _TIMEOUT_S))
    except ValueError:
        return _TIMEOUT_S


def head_length(url: str, *, client: Optional[httpx.Client] = None) -> Optional[int]:
    """Content-Length dell'URL, o None se non ottenibile (host non pubblico, errore, assente)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    try:
        assert_public_host(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except HostNotAllowed as exc:
        logger.info("enclosure non sondabile %s: %s", url, exc)
        return None
    own = client is None
    client = client or httpx.Client(timeout=timeout_s(), follow_redirects=True)
    try:
        response = client.head(url)
        if response.status_code >= 400:
            return None
        raw = response.headers.get("content-length")
        return int(raw) if raw and raw.isdigit() else None
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("HEAD fallita su %s: %s", url, type(exc).__name__)
        return None
    finally:
        if own:
            client.close()


def lengths_for(urls: Iterable[str], store, *, client=None) -> Dict[str, Optional[int]]:
    """Mappa url -> length, usando la cache persistente e sondando solo cio' che manca."""
    out: Dict[str, Optional[int]] = {}
    for url in dict.fromkeys(urls):
        cached, length = store.get(url)
        if cached:
            out[url] = length
            continue
        length = head_length(url, client=client)
        store.put(url, length)
        out[url] = length
    return out
