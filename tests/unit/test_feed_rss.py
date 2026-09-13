"""Generatore RSS, scoperta dei relay, cache e rate limit: la logica pura del dominio feed."""
import json
import xml.etree.ElementTree as ET

import pytest

from src.domains.feed.repositories.enclosure_store import EnclosureStore
from src.domains.feed.services import discovery, markdown_html, rss_builder
from src.rate_limit import FixedWindowLimiter
from tests.nostr_fixtures import make_event

SK = "b7" * 32
FIXTURES = json.load(open("tests/fixtures/feed_events.json"))
CARD, PROFILE, EP1 = FIXTURES["card"], FIXTURES["profile"], FIXTURES["ep1"]
PK = FIXTURES["pubkey"]


def _build(**over):
    args = dict(card=CARD, profile=PROFILE, episodes=[EP1], pubkey_hex=PK,
                feed_url="https://media.example.org/v0/feed/npub.xml", lang="it",
                relays=["wss://nos.lol"], enclosure_lengths={}, skipped=0)
    args.update(over)
    return rss_builder.build_feed(**args)


# ── determinismo (senza, l'ETag non serve a nulla) ─────────────────────────────

def test_output_is_byte_identical_across_calls():
    assert _build() == _build()


def test_no_generation_timestamp_leaks_into_the_body():
    """lastBuildDate deriva dall'evento piu' recente, non dall'orologio."""
    body = _build()
    assert f"<lastBuildDate>{rss_builder.rfc822(EP1['created_at'])}</lastBuildDate>" in body
    assert _build(episodes=[]).count("lastBuildDate") == 0


def test_rfc822_is_locale_independent():
    """Con LANG=it_IT, strftime darebbe 'Ven, 05 Set': i validatori lo rifiutano."""
    assert rss_builder.rfc822(1757100000) == "Fri, 05 Sep 2025 19:20:00 +0000"
    assert rss_builder.rfc822(0) == "Thu, 01 Jan 1970 00:00:00 +0000"


def test_podcast_guid_is_uuid5_of_the_url_without_scheme_and_stable():
    import uuid

    expected = str(uuid.uuid5(uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6"),
                              "media.example.org/v0/feed/x.xml"))
    assert rss_builder.podcast_guid("https://media.example.org/v0/feed/x.xml") == expected
    # lo schema non conta: http e https devono dare lo stesso guid
    assert (rss_builder.podcast_guid("http://media.example.org/v0/feed/x.xml")
            == rss_builder.podcast_guid("https://media.example.org/v0/feed/x.xml"))


# ── contenuto del feed ─────────────────────────────────────────────────────────

def test_feed_is_well_formed_and_has_the_tags_apple_requires():
    root = ET.fromstring(_build(enclosure_lengths={EP1["tags"][3][1]: 10}))
    channel = root.find("channel")
    itunes = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    for tag in ("title", "description", "language"):
        assert channel.findtext(tag), tag
    assert channel.find(f"{itunes}image") is not None
    assert channel.findtext(f"{itunes}explicit") == "false"
    assert channel.find("item/enclosure") is not None


def test_category_and_duration_are_not_invented():
    body = _build()
    assert "itunes:category" not in body
    assert "itunes:duration" not in body


def test_link_falls_back_to_njump_when_the_card_has_no_website():
    card = make_event(SK, kind=10154, created_at=1, tags=[["title", "T"]])
    body = _build(card=card)
    assert "<link>https://njump.me/npub1" in body


def test_author_falls_back_to_npub_without_profile():
    body = _build(profile=None)
    assert "<itunes:author>npub1" in body


def test_first_audio_tag_becomes_the_enclosure_others_are_alternates():
    body = _build(enclosure_lengths={"https://blossom.example.org/aaaa.mp3": 51200})
    assert '<enclosure url="https://blossom.example.org/aaaa.mp3" type="audio/mpeg" length="51200"/>' in body
    assert "podcast:alternateEnclosure" in body
    assert body.count("<enclosure ") == 1


def test_non_audio_mime_tags_are_ignored():
    event = make_event(SK, kind=54, created_at=1, tags=[
        ["title", "T"], ["audio", "https://x/v.mp4", "video/mp4"],
        ["audio", "https://x/a.mp3", "audio/mpeg"]])
    assert rss_builder.audio_tags(event) == [("https://x/a.mp3", "audio/mpeg")]


def test_unknown_length_keeps_the_enclosure_and_says_why():
    body = _build(enclosure_lengths={})
    assert 'length="0"' in body
    assert "length sconosciuto" in body
    assert body.count("<enclosure ") == 1      # non si omette: senza, non e' un episodio


def test_skipped_episodes_are_counted_inside_the_channel():
    body = _build(skipped=3)
    assert "<!-- saltati: 3 senza audio -->" in body
    assert body.index("<!-- saltati") < body.index("</channel>")
    ET.fromstring(body)


def test_queried_relays_are_declared_in_the_head():
    body = _build(relays=["wss://a.example", "wss://b.example"])
    assert "<!-- relays: wss://a.example, wss://b.example -->" in body


def test_cdata_survives_a_closing_sequence_in_the_content():
    event = make_event(SK, kind=54, created_at=1, tags=[
        ["title", "T"], ["audio", "https://x/a.mp3", "audio/mpeg"]], content="prima ]]> dopo")
    ET.fromstring(_build(episodes=[event]))      # se il CDATA non fosse spezzato, non parserebbe


def test_special_characters_are_escaped():
    card = make_event(SK, kind=10154, created_at=1, tags=[["title", "A & B <c> \"d\""]])
    body = _build(card=card)
    assert "<title>A &amp; B &lt;c&gt; \"d\"</title>" in body
    ET.fromstring(body)


# ── sanificazione del Markdown ─────────────────────────────────────────────────

@pytest.mark.parametrize("source,forbidden", [
    ("<script>alert(1)</script>", "<script"),
    ("<img src=x onerror=alert(1)>", "<img"),
    ("<iframe src='//evil'></iframe>", "<iframe"),
    ("[x](javascript:alert(1))", 'href="javascript:'),
    ("[x](data:text/html;base64,PHNjcmlwdD4=)", 'href="data:'),
])
def test_markdown_never_emits_raw_html_or_dangerous_links(source, forbidden):
    """Si controlla il markup **vivo**: l'HTML escapato (`&lt;img ...`) e' testo inerte, ed e'
    proprio il risultato voluto — `html=False` escapa invece di passare."""
    html = markdown_html.to_html(source)
    assert forbidden not in html
    if source.startswith("<"):
        assert "&lt;" in html          # e' stato escapato, non semplicemente rimosso


def test_commonmark_preset_alone_would_reintroduce_xss():
    """Il preset "commonmark" abilita `html`: la sicurezza sta nell'override, non nel preset.
    Se un domani qualcuno togliesse `html: False`, questo test lo direbbe subito."""
    from markdown_it import MarkdownIt

    assert "<script>" in MarkdownIt("commonmark").render("<script>alert(1)</script>")
    assert "<script>" not in markdown_html.to_html("<script>alert(1)</script>")


def test_markdown_still_renders_the_usual_constructs():
    html = markdown_html.to_html("# T\n\n**forte** e [ok](https://e.org)\n\n- a\n- b")
    assert "<h1>T</h1>" in html and "<strong>forte</strong>" in html
    assert '<a href="https://e.org">ok</a>' in html and "<li>a</li>" in html


# ── scoperta dei relay ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("wss://Relay.Example.ORG/", "wss://relay.example.org"),
    ("wss://relay.example.org/path/", "wss://relay.example.org/path"),
    ("wss://relay.example.org:7777", "wss://relay.example.org:7777"),
    ("https://relay.example.org", ""),          # non e' un relay
    ("relay.example.org", ""),
    ("", ""),
])
def test_relay_normalization_is_canonical(raw, expected):
    assert discovery.normalize(raw) == expected


def test_nip65_uses_write_relays_only():
    """`read` = dove l'autore legge, non dove pubblica: leggerci i suoi eventi e' inutile."""
    event = make_event(SK, kind=10002, created_at=1, tags=[
        ["r", "wss://scrive.example"],                     # senza marker = lettura e scrittura
        ["r", "wss://scrive2.example", "write"],
        ["r", "wss://solo-lettura.example", "read"],
    ])
    assert discovery.write_relays(event) == ["wss://scrive.example", "wss://scrive2.example"]


def test_extra_relays_reject_internal_hosts():
    """`?relays=` arriva dall'esterno: non deve poter puntare alla rete interna (SSRF)."""
    parsed = discovery.parse_extra(
        "wss://127.0.0.1,ws://localhost:8080,wss://10.0.0.5,http://example.org")
    assert parsed == []


def test_extra_relays_are_capped_and_deduplicated(monkeypatch):
    monkeypatch.setattr(discovery, "is_public", lambda url: True)
    raw = ",".join(f"wss://r{i}.example" for i in range(20)) + ",wss://r0.example/"
    parsed = discovery.parse_extra(raw)
    assert len(parsed) == 8 and len(set(parsed)) == 8


def test_discovery_prefers_nip65_and_always_keeps_the_fallbacks(monkeypatch):
    monkeypatch.setattr(discovery, "is_public", lambda url: True)
    monkeypatch.setenv("FEED_FALLBACK_RELAYS", "wss://ripiego.example")
    monkeypatch.setenv("FEED_INDEXER_RELAYS", "wss://indice.example")
    from tests.nostr_fixtures import FakeRelays

    nip65 = make_event(SK, kind=10002, created_at=5, tags=[["r", "wss://suo.example"]])
    found = discovery.discover(nip65["pubkey"], ["wss://extra.example"],
                               client=FakeRelays([nip65]))
    assert found.from_nip65 == ["wss://suo.example"]
    # ordinato = deterministico: il commento in testa al feed non deve ballare
    assert found.relays == ["wss://extra.example", "wss://ripiego.example", "wss://suo.example"]


def test_discovery_without_nip65_uses_only_fallbacks(monkeypatch):
    monkeypatch.setattr(discovery, "is_public", lambda url: True)
    monkeypatch.setenv("FEED_FALLBACK_RELAYS", "wss://a.example,wss://b.example")
    from tests.nostr_fixtures import FakeRelays

    found = discovery.discover("ab" * 32, client=FakeRelays([]))
    assert found.from_nip65 == []
    assert found.relays == ["wss://a.example", "wss://b.example"]


# ── cache delle dimensioni e rate limit ────────────────────────────────────────

def test_enclosure_store_caches_values_and_retries_failures(tmp_path):
    store = EnclosureStore(str(tmp_path / "feed.db"))
    assert store.get("https://x/a.mp3") == (False, None)
    store.put("https://x/a.mp3", 1234, now=1000)
    assert store.get("https://x/a.mp3", now=1000) == (True, 1234)
    # un fallimento e' memorizzato (niente raffica di HEAD) ma non per sempre
    store.put("https://x/b.mp3", None, now=1000)
    assert store.get("https://x/b.mp3", now=1000) == (True, None)
    assert store.get("https://x/b.mp3", now=1000 + 3601) == (False, None)


def test_enclosure_store_survives_a_restart(tmp_path):
    EnclosureStore(str(tmp_path / "feed.db")).put("https://x/a.mp3", 7)
    assert EnclosureStore(str(tmp_path / "feed.db")).get("https://x/a.mp3") == (True, 7)


def test_rate_limiter_counts_per_key_and_resets_next_window():
    limiter = FixedWindowLimiter(max_requests=2, window=60)
    assert limiter.check("1.2.3.4", now=0) == (True, 0)
    assert limiter.check("1.2.3.4", now=1) == (True, 0)
    allowed, retry = limiter.check("1.2.3.4", now=2)
    assert allowed is False and 0 < retry <= 60
    assert limiter.check("5.6.7.8", now=2)[0] is True      # altro IP, contatore proprio
    assert limiter.check("1.2.3.4", now=60)[0] is True     # finestra nuova


# ── fixture di riferimento ─────────────────────────────────────────────────────

def test_matches_the_expected_feed_ignoring_whitespace():
    """Golden file: tre eventi (10154, 0, due 54 di cui uno senza audio) -> feed atteso.

    Confronto a spazi normalizzati, cosi' una riformattazione non fa fallire il test mentre
    ogni differenza di contenuto — un tag in meno, un attributo cambiato — lo fa.
    """
    from src.domains.feed.nostr import nip19

    relays = ["wss://damus.example", "wss://nos.example"]
    body = rss_builder.build_feed(
        card=CARD, profile=PROFILE, episodes=[EP1], pubkey_hex=PK,
        feed_url=f"https://media.example.org/v0/feed/{nip19.hex_to_npub(PK)}.xml",
        lang="it", relays=relays,
        enclosure_lengths={"https://blossom.example.org/aaaa.mp3": 51200},
        skipped=1, episode_relay_hints=relays)
    expected = open("tests/fixtures/feed_expected.xml").read()
    import re

    squash = lambda s: re.sub(r"\s+", " ", s).strip()        # noqa: E731
    assert squash(body) == squash(expected)


def test_missing_image_is_declared_not_invented():
    """Caso reale: esistono kind 10154 senza `image`. Apple pretende `itunes:image`, ma
    l'avatar del kind 0 e' l'autore, non la copertina: si segnala invece di inventare."""
    card = make_event(SK, kind=10154, created_at=1, tags=[["title", "Senza copertina"]])
    body = _build(card=card)
    itunes = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
    channel = ET.fromstring(body).find("channel")
    assert channel.find(f"{itunes}image") is None       # il canale non ne ha
    assert channel.find(f"item/{itunes}image") is not None   # l'episodio si': e' un altro campo
    assert "image assente nel kind 10154" in body


def test_enclosure_store_degrades_to_memory_when_the_volume_is_missing(caplog):
    """Il service si costruisce all'import: un volume non montato deve degradare, non impedire
    l'avvio. La cache e' un'ottimizzazione — senza, si rifanno le HEAD."""
    store = EnclosureStore("/proc/non-scrivibile/feed.db")
    assert "cache enclosure non disponibile" in caplog.text
    store.put("https://x/a.mp3", 42)
    assert store.get("https://x/a.mp3") == (True, 42)      # funziona comunque, in memoria
