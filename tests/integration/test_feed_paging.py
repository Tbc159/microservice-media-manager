"""Paging dei kind 54, doppioni per GUID e taglio per data di pubblicazione (delta su K).

I relay applicano `limit` per created_at; in un catalogo importato i created_at sono i giorni
dell'import, nell'ordine dell'import. Qui i 250 episodi hanno created_at in ordine OPPOSTO al
published_at: chi tagliasse per created_at terrebbe proprio gli episodi piu' vecchi.
"""
import json
import re
import warnings

import pytest

from src.domains.feed.nostr import nip19
from src.domains.feed.services import discovery
from src.domains.feed.services.feed_service import FeedService
from src.rate_limit import FixedWindowLimiter
from tests.nostr_fixtures import FakeRelays, MemoryStore, make_event

warnings.filterwarnings("ignore")

SK = "d4" * 32
FEED_URL = "https://media.example.org/v0/feed/x.xml"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "is_public", lambda url: True)
    monkeypatch.setenv("FEED_DB_PATH", str(tmp_path / "feed.db"))
    monkeypatch.setenv("FEED_FALLBACK_RELAYS", "wss://unico.example")
    monkeypatch.setenv("FEED_INDEXER_RELAYS", "wss://indice.example")
    monkeypatch.delenv("FEED_MAX_EPISODES", raising=False)
    monkeypatch.delenv("FEED_CACHE_TTL_S", raising=False)


@pytest.fixture(scope="module")
def catalogue():
    card = make_event(SK, kind=10154, created_at=1750000000, tags=[["title", "Catalogo"]])
    episodes = [
        make_event(SK, kind=54, created_at=1760000000 - i, tags=[   # creati in ordine inverso
            ["title", f"Ep {i:03d}"],
            ["audio", f"https://blossom.example.org/{i:03d}.mp3", "audio/mpeg"],
            ["published_at", str(1600000000 + i * 86400)],           # i alto = piu' recente
        ])
        for i in range(250)
    ]
    return card, episodes


def _lengths(episodes):
    return {f"https://blossom.example.org/{i:03d}.mp3": 1000 for i in range(len(episodes))}


def _build(events, *, cap=None, store=None):
    relays = FakeRelays(events, cap=cap)
    svc = FeedService(store or MemoryStore(_lengths(events)), relays=relays)
    return svc.build(nip19.hex_to_npub(events[0]["pubkey"]), lang="it", extra_relays=[],
                     feed_url=FEED_URL), relays


def _titles(body):
    return re.findall(r"<title>(Ep \d+)</title>", body)


def test_cut_keeps_the_newest_by_published_at_even_when_the_relay_caps_at_100(
        monkeypatch, catalogue):
    monkeypatch.setenv("FEED_MAX_EPISODES", "200")
    card, episodes = catalogue
    result, relays = _build([card] + episodes, cap=100)
    titles = _titles(result.body)
    assert titles == [f"Ep {i:03d}" for i in range(249, 49, -1)]        # i 200 piu' recenti
    assert "<!-- troncati: 50 episodi più vecchi oltre FEED_MAX_EPISODES -->" in result.body
    pages = [c for c in relays.calls if c[0] == "each"]
    assert len(pages) >= 3                                              # 250 / tetto 100


def test_with_the_default_limit_every_episode_comes_out_and_no_comment(catalogue):
    card, episodes = catalogue
    result, _ = _build([card] + episodes, cap=100)                     # default ora 1000
    assert len(_titles(result.body)) == 250
    assert "troncati" not in result.body


def test_same_second_pages_do_not_stop_the_scan():
    """Un relay che restituisce 10 eventi alla volta e 30 episodi nello STESSO secondo: con
    `until` inclusivo la pagina successiva riporterebbe solo eventi gia' visti. Si riprova una
    volta con until-1 invece di fermarsi."""
    card = make_event(SK, kind=10154, created_at=1, tags=[["title", "Stesso secondo"]])
    same = [make_event(SK, kind=54, created_at=1700000000, tags=[
        ["title", f"Ep {i:03d}"], ["audio", f"https://blossom.example.org/{i:03d}.mp3", "audio/mpeg"]])
        for i in range(30)]
    older = [make_event(SK, kind=54, created_at=1600000000 + i, tags=[
        ["title", f"Ep {100 + i:03d}"],
        ["audio", f"https://blossom.example.org/{100 + i:03d}.mp3", "audio/mpeg"]]) for i in range(5)]
    lengths = {f"https://blossom.example.org/{i:03d}.mp3": 1 for i in list(range(30)) + list(range(100, 105))}
    result, _ = _build([card] + same + older, cap=10, store=MemoryStore(lengths))
    titles = set(_titles(result.body))
    # dello stesso secondo il relay finto ne restituisce al piu' 10 (stessa logica di un relay
    # vero): quelli oltre sono irraggiungibili per qualunque client. Ma i 5 piu' vecchi devono
    # arrivare: lo scorrimento non si e' fermato.
    assert {f"Ep {100 + i:03d}" for i in range(5)} <= titles


def test_duplicate_guid_keeps_the_newer_event_whole():
    card = make_event(SK, kind=10154, created_at=1, tags=[["title", "Doppioni"]])
    old = make_event(SK, kind=54, created_at=1700000000, tags=[
        ["title", "Versione vecchia"], ["description", "solo nella vecchia"],
        ["audio", "https://blossom.example.org/000.mp3", "audio/mpeg"],
        ["i", "podcast:item:guid:ep-1"], ["k", "podcast:item:guid"]])
    new = make_event(SK, kind=54, created_at=1700000500, tags=[
        ["title", "Versione corretta"],
        ["audio", "https://blossom.example.org/001.mp3", "audio/mpeg"],
        ["i", "podcast:item:guid:ep-1"], ["k", "podcast:item:guid"]])
    result, _ = _build([card, old, new], store=MemoryStore(_lengths([0, 1])))
    assert result.body.count("<item>") == 1
    assert "Versione corretta" in result.body and "Versione vecchia" not in result.body
    assert "solo nella vecchia" not in result.body          # rimpiazzato INTERO, non fuso
    assert "<!-- doppioni scartati: 1 -->" in result.body


def test_comments_are_deterministic_and_etag_is_stable(monkeypatch, catalogue):
    monkeypatch.setenv("FEED_MAX_EPISODES", "200")
    monkeypatch.setenv("FEED_CACHE_TTL_S", "0")
    card, episodes = catalogue
    a, _ = _build([card] + episodes, cap=100)
    b, _ = _build([card] + list(reversed(episodes)), cap=37)           # altro ordine, altro tetto
    assert a.body == b.body and a.etag == b.etag


def test_a_relay_failing_mid_scan_leaves_the_feed_partial(catalogue):
    """Il paging non cambia la regola di J: un relay che non risponde a una pagina rende il
    feed parziale (cache breve), e il feed esce con quello che c'e'."""
    card, episodes = catalogue

    class FailsOnSecondPage(FakeRelays):
        def query_each(self, requests, *, timeout=None):
            out = super().query_each(requests, timeout=timeout)
            if len([c for c in self.calls if c[0] == "each"]) >= 2:
                out = {u: TimeoutError("caduto") for u in out}
            return out

    relays = FailsOnSecondPage([card] + episodes, cap=100)
    svc = FeedService(MemoryStore(_lengths(episodes)), relays=relays)
    result = svc.build(nip19.hex_to_npub(card["pubkey"]), lang="it", extra_relays=[],
                       feed_url=FEED_URL)
    assert result.partial and result.cache_control == "public, max-age=30"
    assert "wss://unico.example (nessuna risposta)" in result.body
    assert len(_titles(result.body)) == 100                              # la prima pagina


def test_prompt_k_fixture_through_the_api_is_todays_feed_byte_for_byte(monkeypatch):
    """La fixture del Prompt K, passata dal servizio vero (paging incluso), da' esattamente il
    golden generato prima di questo delta: stesso corpo, stesso ETag."""
    from src.app import create_app
    import src.domains.feed.controllers.feed_controller as fc
    from src.domains.feed.services.feed_service import _etag

    monkeypatch.setenv("FEED_FALLBACK_RELAYS", "wss://nos.example")
    p20 = json.load(open("tests/fixtures/feed_p20_events.json"))
    app = create_app(domains=["feed"])
    fc._service = FeedService(MemoryStore({"https://blossom.example.org/a.mp3": 1000,
                                           "https://blossom.example.org/b.mp3": 2000}),
                              relays=FakeRelays([p20["card"], p20["ep_a"], p20["ep_b"]]))
    fc._limiter = FixedWindowLimiter(max_requests=1000, window=60)
    r = app.test_client().get(f"/v0/feed/{nip19.hex_to_npub(p20['pubkey'])}.xml",
                              headers={"Host": "interno:8080"})
    expected = open("tests/fixtures/feed_p20_expected.xml").read()
    assert r.text == expected
    assert r.headers["etag"] == _etag(expected)
