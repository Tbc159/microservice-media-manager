"""Orchestrazione del dominio `feed`: dagli eventi Nostr al documento RSS.

Il flusso: normalizza la chiave -> scopre i relay -> legge gli eventi -> valida id e firma ->
sceglie la scheda (10154), il profilo (0) e gli episodi (54) -> risolve le dimensioni degli
enclosure -> costruisce l'XML -> ne calcola l'ETag.

**La cache sta qui, non solo negli header.** `Cache-Control` ed `ETag` risparmiano banda ai
client, ma non risparmiano *un solo* accesso ai relay: per rispondere `304` bisogna comunque
conoscere l'ETag corrente, cioe' avere il corpo. Senza una cache lato server ogni `If-None-Match`
aprirebbe una manciata di WebSocket. Per questo il corpo generato resta in memoria per
`FEED_CACHE_TTL_S` e il `304` si risponde da li'.

**Un feed parziale non resta in cache per il TTL pieno.** Se un relay non risponde entro il
timeout, il feed esce comunque con quello che e' arrivato — meglio pochi episodi che un 503 —
ma tenerlo in cache cinque minuti significa che chi lo verifica in quel momento vede sparire
gli episodi che stanno solo sul relay lento (osservato: 1 episodio su 5). Quindi: un risultato
con `reached < queried` si tiene al massimo `FEED_PARTIAL_CACHE_TTL_S` (default 30 s; 0 = mai),
il `Cache-Control` lo dice, e il commento in testa segna chi non ha risposto.

**L'ETag e' del contenuto, non del documento.** Il commento `<!-- relays: ... -->` cambia fra
parziale e completo, ma a parita' di eventi l'ETag deve restare lo stesso: un client con la
copia completa che chiede `If-None-Match` mentre noi abbiamo un parziale con gli stessi eventi
deve ricevere `304` e tenersi la sua. Per questo l'hash si calcola sul corpo *senza* quel
commento.
"""
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from src.domains.feed.errors import InvalidKey, NoPodcastCard
from src.domains.feed.nostr import events as ev
from src.domains.feed.nostr import nip19
from src.domains.feed.nostr import relay_client as default_relay_client
from src.domains.feed.services import discovery, enclosure_probe, rss_builder

logger = logging.getLogger("feed")

KIND_CARD, KIND_PROFILE, KIND_EPISODE = 10154, 0, 54

_DEFAULT_TTL_S = 300
_DEFAULT_PARTIAL_TTL_S = 30
_DEFAULT_MAX_EPISODES = 1000
_DEFAULT_MAX_EVENTS_SCAN = 5000
_PAGE_LIMIT = 500           # quanto si chiede per pagina; i relay possono tagliare di meno
_RELAY_HINTS_IN_NEVENT = 2


def cache_ttl_s() -> int:
    try:
        return max(0, int(os.environ.get("FEED_CACHE_TTL_S", _DEFAULT_TTL_S)))
    except ValueError:
        return _DEFAULT_TTL_S


def partial_cache_ttl_s() -> int:
    """Per quanto tenere un feed costruito senza tutti i relay (0 = non metterlo in cache)."""
    try:
        return max(0, int(os.environ.get("FEED_PARTIAL_CACHE_TTL_S", _DEFAULT_PARTIAL_TTL_S)))
    except ValueError:
        return _DEFAULT_PARTIAL_TTL_S


def max_events_scan() -> int:
    """Tetto agli eventi kind 54 letti in tutto (tutte le pagine, tutti i relay)."""
    try:
        return max(1, int(os.environ.get("FEED_MAX_EVENTS_SCAN", _DEFAULT_MAX_EVENTS_SCAN)))
    except ValueError:
        return _DEFAULT_MAX_EVENTS_SCAN


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
    unreached: List[str] = field(default_factory=list)
    cached: bool = False

    @property
    def partial(self) -> bool:
        """Costruito senza la risposta di tutti i relay: vale poco, e va tenuto poco."""
        return bool(self.unreached)

    @property
    def cache_ttl(self) -> int:
        return partial_cache_ttl_s() if self.partial else cache_ttl_s()

    @property
    def cache_control(self) -> str:
        """`max-age` coerente con quanto lo teniamo noi; `no-cache` se un parziale non si tiene."""
        ttl = self.cache_ttl
        return f"public, max-age={ttl}" if ttl else "no-cache"


def _etag(body: str) -> str:
    """Hash del CONTENUTO: il commento diagnostico sui relay non entra, cosi' parziale e
    completo con gli stessi eventi hanno lo stesso ETag."""
    content = rss_builder.strip_relays_comment(body)
    return '"' + hashlib.sha256(content.encode("utf-8")).hexdigest()[:32] + '"'


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
        return FeedResult(result.body, result.etag, result.relays, list(result.unreached), cached=True)

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

        ttl = result.cache_ttl            # parziale -> TTL breve (o niente cache)
        if ttl:
            self._cache[cache_key] = (now + ttl, result)
        return result

    def _scan(self, relays: Sequence[str], pubkey: str):
        """Tutti gli eventi utili della chiave: scheda, profilo e OGNI kind 54, con paging.

        I relay applicano `limit` per created_at, non per published_at: chiedere 200 episodi e
        ordinare poi per data di pubblicazione darebbe 200 episodi qualsiasi di un catalogo
        importato (dove i created_at sono i giorni dell'import, nell'ordine dell'import). Quindi
        si leggono tutti, pagina per pagina all'indietro, e il taglio si fa dopo.

        Paging **per relay**: ognuno ha il proprio tetto al `limit` e quindi il proprio `until`
        (inclusivo: nello stesso secondo possono stare piu' eventi; si deduplica per id). Un
        relay e' esaurito quando una pagina non porta nulla di nuovo; prima di arrendersi si
        riprova una volta con `until - 1`, perche' una pagina tutta nello stesso secondo — piu'
        eventi di quanti il relay ne restituisce — altrimenti bloccherebbe lo scorrimento.
        Si ferma comunque a FEED_MAX_EVENTS_SCAN eventi letti.

        Restituisce `(eventi deduplicati per id, relay che non hanno risposto)`: un relay che
        cade a meta' paging rende il risultato parziale come uno che non risponde affatto.
        """
        head = [{"kinds": [KIND_CARD, KIND_PROFILE], "authors": [pubkey], "limit": 10}]

        def page(until=None):
            f = {"kinds": [KIND_EPISODE], "authors": [pubkey], "limit": _PAGE_LIMIT}
            if until is not None:
                f["until"] = until
            return f

        seen: Dict[str, dict] = {}
        per_relay: Dict[str, set] = {u: set() for u in relays}
        unreached: List[str] = []
        state: Dict[str, Tuple[Optional[int], bool]] = {}   # url -> (until, gia' provato -1)
        requests = {u: head + [page()] for u in relays}
        scanned = 0
        while requests and scanned < max_events_scan():
            outcomes = self._relays.query_each(requests)
            next_requests = {}
            for url in requests:
                outcome = outcomes.get(url)
                if isinstance(outcome, BaseException) or outcome is None:
                    if url not in unreached:
                        unreached.append(url)
                    continue
                new_ids = 0
                oldest = None
                for event in outcome:
                    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
                        continue
                    scanned += 1
                    seen.setdefault(event["id"], event)
                    if event.get("kind") != KIND_EPISODE:
                        continue
                    if event["id"] not in per_relay[url]:
                        per_relay[url].add(event["id"])
                        new_ids += 1
                    ts = event.get("created_at")
                    if isinstance(ts, int):
                        oldest = ts if oldest is None else min(oldest, ts)
                until, tried_minus_one = state.get(url, (None, False))
                if new_ids and oldest is not None:
                    state[url] = (oldest, False)
                    next_requests[url] = [page(oldest)]
                elif until is not None and not tried_minus_one and until > 0:
                    state[url] = (until - 1, True)
                    next_requests[url] = [page(until - 1)]
            requests = next_requests
        if scanned >= max_events_scan():
            logger.warning("scansione interrotta a %s eventi per %s (FEED_MAX_EVENTS_SCAN)",
                           scanned, pubkey[:12])
        return list(seen.values()), [u for u in relays if u in unreached]

    def _generate(self, pubkey: str, found: discovery.Discovery, *, lang: str,
                  feed_url: str) -> FeedResult:
        events, unreached_relays = self._scan(found.relays, pubkey)
        valid = [e for e in events if ev.is_valid(e, pubkey=pubkey)]
        discarded = len(events) - len(valid)
        if discarded:
            logger.warning("scartati %s eventi non validi per %s", discarded, pubkey[:12])

        card = _newest(valid, KIND_CARD)
        if card is None:
            raise NoPodcastCard(found.relays, unreached=list(unreached_relays))
        profile = _newest(valid, KIND_PROFILE)

        # 1) Un episodio per GUID: fra gli eventi con lo stesso podcast:item:guid vince il
        #    created_at piu' recente (l'ultima versione), INTERO — mai fusi campo per campo.
        episodes, duplicates = _latest_per_guid(e for e in valid if e["kind"] == KIND_EPISODE)
        playable = [e for e in episodes if rss_builder.audio_tags(e)]
        skipped = len(episodes) - len(playable)
        # 2) Ordine per data di pubblicazione (published_at, altrimenti created_at), piu' recente
        #    prima; a parita' di secondo l'id decide, per un ordine stabile.
        playable.sort(key=lambda e: (rss_builder.pub_timestamp(e), e["id"]), reverse=True)
        # 3) SOLO ORA il taglio: resta fuori sempre il piu' vecchio per data di pubblicazione.
        #    Mai per created_at: in un catalogo importato e' il giorno dell'import.
        truncated = max(0, len(playable) - max_episodes())
        playable = playable[: max_episodes()]

        # Tutti gli URL audio, non solo il primo: anche gli alternateEnclosure portano length.
        lengths = enclosure_probe.lengths_for(
            (url for e in playable for url, _ in rss_builder.audio_tags(e)),
            self._store, client=self._http,
        )
        unreached = list(unreached_relays)
        if found.indexers_queried and not found.indexers_reached:
            # Senza indicizzatori non sappiamo quali siano i relay dell'autore: abbiamo letto
            # solo i ripieghi, e i suoi episodi potrebbero stare altrove. E' parziale anche questo.
            unreached.append("indicizzatori NIP-65")
        if unreached:
            logger.warning("feed parziale per %s: senza risposta %s", pubkey[:12], unreached)
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
            duplicates=duplicates,
            truncated=truncated,
            # NON `fetched.reached`: gli hint entrano nel corpo e quindi nell'ETag, e devono
            # dipendere solo dagli eventi, non da quale relay ha risposto stavolta.
            episode_relay_hints=found.relays[:_RELAY_HINTS_IN_NEVENT],
            unreached=unreached,
        )
        return FeedResult(body=body, etag=_etag(body), relays=found.relays, unreached=unreached)


def _latest_per_guid(episodes):
    """`(episodi, doppioni scartati)`: un evento per GUID di episodio, il created_at piu' recente.

    Due 54 con lo stesso `["i", "podcast:item:guid:<g>"]` sono lo stesso episodio (un import
    ripreso dopo che un relay aveva perso la prima copia, o una correzione): il piu' recente
    rimpiazza l'altro per intero. Senza tag `i` il GUID e' l'id dell'evento, gia' unico.
    """
    best: dict = {}
    count = 0
    for event in episodes:
        count += 1
        key = rss_builder.nip73_value(event, "podcast:item:guid:") or ("id", event["id"])
        current = best.get(key)
        if current is None or (event["created_at"], event["id"]) > (current["created_at"], current["id"]):
            best[key] = event
    return list(best.values()), count - len(best)


def _newest(events: Sequence[dict], kind: int) -> Optional[dict]:
    """L'evento piu' recente di quel kind: 10154 e 0 sono rimpiazzabili, vale l'ultima versione."""
    candidates = [e for e in events if e["kind"] == kind]
    return max(candidates, key=lambda e: e["created_at"]) if candidates else None
