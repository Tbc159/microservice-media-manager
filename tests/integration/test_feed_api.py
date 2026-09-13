"""Contratto HTTP del dominio `feed`, via connexion TestClient (niente rete, niente relay veri).

Copre cio' che rende questo dominio diverso dagli altri: nessuna autenticazione, cache con
ETag/304, rate limit per IP, CORS `*` — piu' la validita' del documento prodotto.
"""
import json
import re
import warnings
import xml.etree.ElementTree as ET

import pytest

from src.domains.feed.services import discovery
from src.domains.feed.services.feed_service import FeedService
from src.rate_limit import FixedWindowLimiter
from tests.nostr_fixtures import FakeRelays, MemoryStore, make_event

warnings.filterwarnings("ignore")

FIXTURES = json.load(open("tests/fixtures/feed_events.json"))
PK = FIXTURES["pubkey"]
ALL_EVENTS = [FIXTURES["card"], FIXTURES["profile"], FIXTURES["ep1"], FIXTURES["ep_no_audio"]]
AUDIO_URL = "https://blossom.example.org/aaaa.mp3"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch, tmp_path):
    # I relay di ripiego sono nomi finti: senza questo, discovery farebbe una risoluzione DNS
    # reale. La guardia SSRF vera e' provata in tests/unit/test_feed_rss.py.
    monkeypatch.setattr(discovery, "is_public", lambda url: True)
    # Il controller costruisce il service all'import: senza questo userebbe /data/feed.db,
    # che sul runner di CI non esiste.
    monkeypatch.setenv("FEED_DB_PATH", str(tmp_path / "feed.db"))
    monkeypatch.setenv("FEED_FALLBACK_RELAYS", "wss://nos.example,wss://damus.example")
    monkeypatch.setenv("FEED_INDEXER_RELAYS", "wss://indice.example")
    monkeypatch.delenv("FEED_CACHE_TTL_S", raising=False)


def _client(events=None, lengths=None):
    from src.app import create_app
    import src.domains.feed.controllers.feed_controller as fc

    app = create_app(domains=["feed"])
    fc._service = FeedService(MemoryStore(lengths if lengths is not None else {AUDIO_URL: 51200}),
                              relays=FakeRelays(ALL_EVENTS if events is None else events))
    fc._limiter = FixedWindowLimiter(max_requests=1000, window=60)
    return app.test_client()


@pytest.fixture()
def client():
    return _client()


def _npub():
    from src.domains.feed.nostr import nip19
    return nip19.hex_to_npub(PK)


# ── il feed ────────────────────────────────────────────────────────────────────

def test_health(client):
    assert client.get("/v0/feed/health").json() == {"status": "ok"}


def test_feed_needs_no_api_key_and_is_rss(client):
    """Lo scarica un'app di podcast: non conosce X-API-Key. Negli altri domini sarebbe 401."""
    r = client.get(f"/v0/feed/{_npub()}.xml")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/rss+xml; charset=utf-8"
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.headers["etag"].startswith('"')
    ET.fromstring(r.text)


def test_feed_has_the_tags_apple_requires(client):
    channel = ET.fromstring(client.get(f"/v0/feed/{_npub()}.xml").text).find("channel")
    assert channel.findtext("title") == "Radio Satoshi"
    assert channel.findtext("description")
    assert channel.findtext("language") == "it"
    assert channel.find(f"{ITUNES}image").get("href")
    assert channel.findtext(f"{ITUNES}explicit") == "false"
    enclosure = channel.find("item/enclosure")
    assert enclosure.get("url") == AUDIO_URL and enclosure.get("length") == "51200"


def test_episode_without_audio_is_skipped_and_counted(client):
    body = client.get(f"/v0/feed/{_npub()}.xml").text
    assert body.count("<item>") == 1
    assert "<!-- saltati: 1 senza audio -->" in body


def test_queried_relays_are_declared_for_diagnosis(client):
    body = client.get(f"/v0/feed/{_npub()}.xml").text
    assert "<!-- relays: wss://damus.example, wss://nos.example -->" in body


def test_extra_relays_are_added_to_the_discovered_ones(client):
    body = client.get(f"/v0/feed/{_npub()}.xml?relays=wss://extra.example").text
    assert "wss://extra.example" in body.split("\n")[1]


def test_lang_changes_only_the_declared_language(client):
    assert "<language>en</language>" in client.get(f"/v0/feed/{_npub()}.xml?lang=en").text
    assert "<language>it</language>" in client.get(f"/v0/feed/{_npub()}.xml").text


def test_hex_and_npub_yield_the_same_canonical_feed(client):
    from_npub = client.get(f"/v0/feed/{_npub()}.xml").text
    from_hex = client.get(f"/v0/feed/{PK}.xml").text
    guid = lambda s: re.search(r"<podcast:guid>([^<]+)", s).group(1)      # noqa: E731
    assert guid(from_npub) == guid(from_hex)
    assert "rel=\"self\"" in from_hex and f"/v0/feed/{_npub()}.xml" in from_hex


# ── cache ──────────────────────────────────────────────────────────────────────

def test_etag_is_stable_when_nothing_changes(monkeypatch):
    """Con TTL 0 il corpo si rigenera davvero: se contenesse un timestamp, l'ETag ballerebbe."""
    monkeypatch.setenv("FEED_CACHE_TTL_S", "0")
    client = _client()
    first = client.get(f"/v0/feed/{_npub()}.xml")
    second = client.get(f"/v0/feed/{_npub()}.xml")
    assert first.text == second.text
    assert first.headers["etag"] == second.headers["etag"]


def test_if_none_match_gets_304_without_body(client):
    etag = client.get(f"/v0/feed/{_npub()}.xml").headers["etag"]
    r = client.get(f"/v0/feed/{_npub()}.xml", headers={"If-None-Match": etag})
    assert r.status_code == 304 and r.content == b""
    assert r.headers["etag"] == etag and r.headers["cache-control"] == "public, max-age=300"


def test_weak_and_wildcard_if_none_match_are_honoured(client):
    etag = client.get(f"/v0/feed/{_npub()}.xml").headers["etag"]
    assert client.get(f"/v0/feed/{_npub()}.xml",
                      headers={"If-None-Match": f"W/{etag}"}).status_code == 304
    assert client.get(f"/v0/feed/{_npub()}.xml",
                      headers={"If-None-Match": "*"}).status_code == 304
    assert client.get(f"/v0/feed/{_npub()}.xml",
                      headers={"If-None-Match": '"altro"'}).status_code == 200


def test_etag_changes_when_an_episode_appears():
    before = _client().get(f"/v0/feed/{_npub()}.xml").headers["etag"]
    extra = make_event("b7" * 32, kind=54, created_at=1757200000, tags=[
        ["title", "Episodio 3"], ["audio", "https://blossom.example.org/ccc.mp3", "audio/mpeg"]])
    after = _client(ALL_EVENTS + [extra]).get(f"/v0/feed/{_npub()}.xml").headers["etag"]
    assert before != after


def test_cached_response_does_not_touch_the_relays():
    """Il 304 richiede comunque di conoscere l'ETag: senza cache lato server, ogni
    If-None-Match riaprirebbe i WebSocket verso i relay."""
    from src.app import create_app
    import src.domains.feed.controllers.feed_controller as fc

    relays = FakeRelays(ALL_EVENTS)
    app = create_app(domains=["feed"])
    fc._service = FeedService(MemoryStore({AUDIO_URL: 1}), relays=relays)
    fc._limiter = FixedWindowLimiter(max_requests=1000, window=60)
    client = app.test_client()
    client.get(f"/v0/feed/{_npub()}.xml")
    calls = len(relays.calls)
    client.get(f"/v0/feed/{_npub()}.xml")
    client.get(f"/v0/feed/{_npub()}.xml", headers={"If-None-Match": "*"})
    assert len(relays.calls) == calls


# ── errori ─────────────────────────────────────────────────────────────────────

def test_missing_card_is_404_listing_the_relays():
    client = _client([FIXTURES["profile"], FIXTURES["ep1"]])      # nessun kind 10154
    r = client.get(f"/v0/feed/{_npub()}.xml")
    assert r.status_code == 404
    body = r.json()
    assert "kind 10154" in body["detail"]
    assert body["relays"] == ["wss://damus.example", "wss://nos.example"]


def test_a_channel_is_not_invented_from_the_profile():
    """Il kind 0 non basta: senza scheda podcast e' 404, non un feed inventato."""
    assert _client([FIXTURES["profile"]]).get(f"/v0/feed/{_npub()}.xml").status_code == 404


def test_no_episodes_is_a_valid_empty_feed():
    client = _client([FIXTURES["card"], FIXTURES["profile"]])
    r = client.get(f"/v0/feed/{_npub()}.xml")
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    assert root.find("channel/item") is None
    assert root.findtext("channel/title") == "Radio Satoshi"


@pytest.mark.parametrize("key", ["npub1nonvalido", "zz" * 32, "abc"])
def test_invalid_key_is_rejected(client, key):
    assert client.get(f"/v0/feed/{key}.xml").status_code in (400, 404)


def test_forged_events_are_discarded(client):
    """Un relay ostile (anche uno passato in ?relays=) non puo' iniettare episodi."""
    from src.domains.feed.nostr.events import compute_id

    forged = dict(FIXTURES["ep1"])
    forged["content"] = "episodio fabbricato"
    forged["id"] = compute_id(forged)                 # id ricalcolato, firma no
    c = _client([FIXTURES["card"], forged])
    body = c.get(f"/v0/feed/{_npub()}.xml").text
    assert "fabbricato" not in body
    assert body.count("<item>") == 0


def test_rate_limit_returns_429():
    from src.app import create_app
    import src.domains.feed.controllers.feed_controller as fc

    app = create_app(domains=["feed"])
    fc._service = FeedService(MemoryStore({AUDIO_URL: 1}), relays=FakeRelays(ALL_EVENTS))
    fc._limiter = FixedWindowLimiter(max_requests=2, window=60)
    client = app.test_client()
    url = f"/v0/feed/{_npub()}.xml"
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    r = client.get(url)
    assert r.status_code == 429 and "troppe richieste" in r.json()["detail"]


# ── CORS ───────────────────────────────────────────────────────────────────────

def test_cors_is_wildcard_even_without_configured_origins(client):
    r = client.get(f"/v0/feed/{_npub()}.xml", headers={"Origin": "https://qualsiasi.example"})
    assert r.headers["access-control-allow-origin"] == "*"
    assert "vary" not in {k.lower() for k in r.headers}


def test_cors_preflight_is_open(client):
    r = client.options(f"/v0/feed/{_npub()}.xml", headers={
        "Origin": "https://qualsiasi.example", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "*"
