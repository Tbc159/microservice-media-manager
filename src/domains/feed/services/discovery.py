"""Scoperta dei relay da cui leggere gli eventi di una chiave.

Un feed che interroga il relay sbagliato e' **vuoto**: e' il modo piu' probabile in cui questo
dominio fallisce, e fallisce in silenzio. Per questo l'insieme dei relay si costruisce da piu'
fonti e viene riportato nella risposta.

Ordine delle fonti:
  1. **NIP-65** (kind 10002) della chiave, letta dai relay *indicizzatori* (purplepag.es,
     user.kindpag.es), che esistono apposta per servire le liste di relay. Si usano i relay di
     **scrittura** dell'autore: sono quelli dove pubblica, quindi dove stanno i suoi eventi.
  2. **Ripiego fisso**, per le chiavi senza kind 10002.
  3. **`?relays=`** del chiamante, in aggiunta (non in sostituzione).

Gli URL sono normalizzati e ordinati: l'insieme deve essere **deterministico**, altrimenti il
commento XML in testa cambia a ogni richiesta e l'ETag non vale piu' nulla.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import List, Sequence
from urllib.parse import urlparse

from src.domains.feed.nostr import events as ev
from src.domains.feed.nostr import relay_client
from src.net_guard import HostNotAllowed, assert_public_host

logger = logging.getLogger("feed")

DEFAULT_INDEXERS = ("wss://purplepag.es", "wss://user.kindpag.es")
DEFAULT_FALLBACK = ("wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net")

_MAX_EXTRA_RELAYS = 8
_SCHEMES = ("wss", "ws")


@dataclass
class Discovery:
    relays: List[str] = field(default_factory=list)
    from_nip65: List[str] = field(default_factory=list)
    indexers_queried: List[str] = field(default_factory=list)
    indexers_reached: List[str] = field(default_factory=list)


def _from_env(name: str, default: Sequence[str]) -> List[str]:
    raw = os.environ.get(name, "")
    values = [v.strip() for v in raw.split(",") if v.strip()]
    return values or list(default)


def indexer_relays() -> List[str]:
    return _from_env("FEED_INDEXER_RELAYS", DEFAULT_INDEXERS)


def fallback_relays() -> List[str]:
    return _from_env("FEED_FALLBACK_RELAYS", DEFAULT_FALLBACK)


def normalize(url: str) -> str:
    """Forma canonica di un URL di relay, o "" se non utilizzabile.

    Canonica = schema e host minuscoli, senza slash finale: due scritture dello stesso relay
    non devono contare come due relay (cambierebbe il corpo del feed, e quindi l'ETag).
    """
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in _SCHEMES or not parsed.hostname:
        return ""
    netloc = parsed.hostname.lower() + (f":{parsed.port}" if parsed.port else "")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{netloc}{path}"


def is_public(url: str) -> bool:
    """False se il relay punta alla rete interna: `?relays=` arriva dall'esterno (SSRF)."""
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    try:
        assert_public_host(parsed.hostname, port)
    except HostNotAllowed as exc:
        logger.info("relay rifiutato %s: %s", url, exc)
        return False
    return True


def parse_extra(raw: str) -> List[str]:
    """`?relays=wss://a,wss://b` -> lista normalizzata, pubblica, limitata e deduplicata."""
    out: List[str] = []
    for candidate in (raw or "").split(","):
        url = normalize(candidate)
        if url and url not in out and is_public(url):
            out.append(url)
        if len(out) >= _MAX_EXTRA_RELAYS:
            break
    return out


def write_relays(nip65_event: dict) -> List[str]:
    """Relay di **scrittura** da un kind 10002: `["r", url]` oppure `["r", url, "write"]`."""
    out: List[str] = []
    for values in ev.tag_values(nip65_event, "r"):
        if not values:
            continue
        marker = values[1].strip().lower() if len(values) > 1 and values[1] else ""
        if marker == "read":          # solo lettura: l'autore non ci pubblica
            continue
        url = normalize(values[0])
        if url and url not in out:
            out.append(url)
    return out


def discover(pubkey_hex: str, extra: Sequence[str] = (), *, client=relay_client) -> Discovery:
    """Insieme ordinato e deterministico dei relay da interrogare per quella chiave."""
    result = Discovery()
    indexers = [normalize(u) for u in indexer_relays()]
    indexers = [u for u in indexers if u]

    found = client.query(indexers, [{"kinds": [10002], "authors": [pubkey_hex], "limit": 5}])
    result.indexers_queried = list(indexers)
    result.indexers_reached = list(found.reached)
    valid = [e for e in found.events if ev.is_valid(e, pubkey=pubkey_hex) and e["kind"] == 10002]
    if valid:
        newest = max(valid, key=lambda e: e["created_at"])
        result.from_nip65 = write_relays(newest)

    candidates = list(result.from_nip65) + [normalize(u) for u in fallback_relays()] + list(extra)
    seen = {u for u in candidates if u}
    result.relays = sorted(u for u in seen if is_public(u))
    return result
