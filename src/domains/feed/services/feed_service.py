"""Orchestrazione del dominio `feed`: dagli eventi Nostr al documento RSS.

Il flusso: normalizza la chiave -> scopre i relay -> legge gli eventi -> valida id e firma ->
sceglie la scheda (10154), il profilo (0) e gli episodi (54) -> risolve le dimensioni degli
enclosure -> costruisce l'XML -> ne calcola l'ETag.

**La cache sta qui, non solo negli header.** `Cache-Control` ed `ETag` risparmiano banda ai
client, ma non risparmiano *un solo* accesso ai relay: per rispondere `304` bisogna comunque
conoscere l'ETag corrente, cioe' avere il corpo. Senza una cache lato server ogni `If-None-Match`
aprirebbe una manciata di WebSocket. Per questo il corpo generato resta in memoria per
`FEED_CACHE_TTL_S` e il `304` si risponde da li'.
"""
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from src.domains.feed.errors import InvalidKey, NoPodcastCard
from src.domains.feed.nostr import events as ev
from src.domains.feed.nostr import nip19
from src.domains.feed.nostr import relay_client as default_relay_client
from src.domains.feed.services import discovery, enclosure_probe, rss_builder

logger = logging.getLogger("feed")

KIND_CARD, KIND_PROFILE, KIND_EPISODE = 10154, 0, 54

_DEFAULT_TTL_S = 300
_DEFAULT_MAX_EPISODES = 200
_RELAY_HINTS_IN_NEVENT = 2


def cache_ttl_s() -> int:
    try:
        return max(0, int(os.environ.get("FEED_CACHE_TTL_S", _DEFAULT_TTL_S)))
    except ValueError:
        return _DEFAULT_TTL_S


def max_episodes() -> int:
    try:
        return max(1, int(os.environ.get("FEED_MAX_EPISODES", _DEFAULT_MAX_EPISODES)))
    except ValueError:
        return _DEFAULT_MAX_EPISODES


@dataclass
class FeedResult:
    body: str
    etag: str
    relays: List[str]
    cached: bool = False


def _etag(body: str) -> str:
    return '"' + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32] + '"'


class FeedService:
    def __init__(self, store, *, relays=default_relay_client, http_client=None) -> None:
        self._store = store
        self._relays = relays
        self._http = http_client
        self._cache: Dict[tuple, Tuple[float, FeedResult]] = {}

    # ── cache ──────────────────────────────────────────────────────────────────
    def _cached(self, key: tuple, now: float) -> Optional[FeedResult]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, result = entry
        if expires_at <= now:
            self._cache.pop(key, None)
            return None
        return FeedResult(result.body, result.etag, result.relays, cached=True)

    # ── generazione ────────────────────────────────────────────────────────────
    def build(self, key: str, *, lang: str, extra_relays: Sequence[str], feed_url: str,
              now: Optional[float] = None) -> FeedResult:
        """Documento RSS per quella chiave. Solleva InvalidKey (400) o NoPodcastCard (404)."""
        try:
            pubkey = nip19.normalize_pubkey(key)
        except nip19.Nip19Error as exc:
            raise InvalidKey(str(exc)) from exc

        now = time.time() if now is None else now
        cache_key = (pubkey, lang, tuple(extra_relays), feed_url)
        hit = self._cached(cache_key, now)
        if hit is not None:
            return hit

        found = discovery.discover(pubkey, extra_relays, client=self._relays)
        result = self._generate(pubkey, found, lang=lang, feed_url=feed_url)

        ttl = cache_ttl_s()
        if ttl:
            self._cache[cache_key] = (now + ttl, result)
        return result

    def _generate(self, pubkey: str, found: discovery.Discovery, *, lang: str,
                  feed_url: str) -> FeedResult:
        fetched = self._relays.query(found.relays, [
            {"kinds": [KIND_CARD, KIND_PROFILE], "authors": [pubkey], "limit": 10},
            {"kinds": [KIND_EPISODE], "authors": [pubkey], "limit": max_episodes()},
        ])
        valid = [e for e in fetched.events if ev.is_valid(e, pubkey=pubkey)]
        discarded = len(fetched.events) - len(valid)
        if discarded:
            logger.warning("scartati %s eventi non validi per %s", discarded, pubkey[:12])

        card = _newest(valid, KIND_CARD)
        if card is None:
            raise NoPodcastCard(found.relays)
        profile = _newest(valid, KIND_PROFILE)

        # created_at decrescente; a parita' di secondo l'id decide, per un ordine stabile.
        episodes = sorted(
            (e for e in valid if e["kind"] == KIND_EPISODE),
            key=lambda e: (e["created_at"], e["id"]),
            reverse=True,
        )[: max_episodes()]
        playable = [e for e in episodes if rss_builder.audio_tags(e)]
        skipped = len(episodes) - len(playable)

        # Tutti gli URL audio, non solo il primo: anche gli alternateEnclosure portano length.
        lengths = enclosure_probe.lengths_for(
            (url for e in playable for url, _ in rss_builder.audio_tags(e)),
            self._store, client=self._http,
        )
        body = rss_builder.build_feed(
            card=card,
            profile=profile,
            episodes=playable,
            pubkey_hex=pubkey,
            feed_url=feed_url,
            lang=lang,
            relays=found.relays,
            enclosure_lengths=lengths,
            skipped=skipped,
            episode_relay_hints=found.relays[:_RELAY_HINTS_IN_NEVENT],
        )
        return FeedResult(body=body, etag=_etag(body), relays=found.relays)


def _newest(events: Sequence[dict], kind: int) -> Optional[dict]:
    """L'evento piu' recente di quel kind: 10154 e 0 sono rimpiazzabili, vale l'ultima versione."""
    candidates = [e for e in events if e["kind"] == kind]
    return max(candidates, key=lambda e: e["created_at"]) if candidates else None
