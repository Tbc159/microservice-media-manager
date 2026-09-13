"""Controller del dominio `feed`: thin layer.

Tre cose che non fanno gli altri domini e che vivono qui:
  - **nessuna autenticazione** (lo scarica un'app di podcast, che non conosce X-API-Key);
  - **rate limit per IP**, perche' l'endpoint e' pubblico;
  - **ETag e 304**, con `Cache-Control` allineato al TTL della cache del service.

Le risposte sono costruite come `flask.Response` esplicite: l'operazione dichiara due content
type (RSS per il 200, JSON per gli errori) e connexion non puo' indovinare quale usare da un
dict.
"""
import json

import flask

from src.domains.feed.errors import InvalidKey, NoPodcastCard
from src.domains.feed.factory import build_feed_service
from src.domains.feed.nostr import nip19
from src.domains.feed.services import discovery, feed_service
from src.rate_limit import FixedWindowLimiter, client_ip

_service = build_feed_service()
_limiter = FixedWindowLimiter()

_RSS_TYPE = "application/rss+xml; charset=utf-8"


def _json(payload: dict, status: int) -> flask.Response:
    return flask.Response(json.dumps(payload), status, {"Content-Type": "application/json"})


def _cache_headers(etag: str) -> dict:
    return {"Cache-Control": f"public, max-age={feed_service.cache_ttl_s()}", "ETag": etag}


def _matches(header: str, etag: str) -> bool:
    """True se l'If-None-Match del client copre il nostro ETag (anche in forma debole o `*`)."""
    if not header:
        return False
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate == "*" or candidate.removeprefix("W/") == etag:
            return True
    return False


def _feed_url(npub: str) -> str:
    """URL canonico del feed: **sempre** in forma npub, anche se e' stato chiesto in esadecimale.

    Cosi' `podcast:guid` e `atom:link rel=self` non dipendono da come il chiamante ha scritto la
    chiave: lo stesso podcast resta lo stesso feed per Podcast Index.
    """
    request = flask.request
    scheme = request.headers.get("X-Forwarded-Proto") or request.scheme
    host = request.headers.get("Host") or request.host
    return f"{scheme}://{host}/v0/feed/{npub}.xml"


def get_feed(npub: str, lang: str = "it", relays: str = None):
    allowed, retry_after = _limiter.check(client_ip(flask.request))
    if not allowed:
        return _json({"detail": "troppe richieste da questo indirizzo"}, 429)

    try:
        canonical = nip19.hex_to_npub(nip19.normalize_pubkey(npub))
    except nip19.Nip19Error as exc:
        return _json({"detail": f"chiave non valida: {exc}"}, 400)

    try:
        result = _service.build(
            npub,
            lang=lang,
            extra_relays=discovery.parse_extra(relays or ""),
            feed_url=_feed_url(canonical),
        )
    except InvalidKey as exc:
        return _json({"detail": f"chiave non valida: {exc}"}, 400)
    except NoPodcastCard as exc:
        return _json(exc.to_body(), 404)

    headers = _cache_headers(result.etag)
    if _matches(flask.request.headers.get("If-None-Match", ""), result.etag):
        return flask.Response(status=304, headers=headers)
    return flask.Response(result.body, 200, {**headers, "Content-Type": _RSS_TYPE})
