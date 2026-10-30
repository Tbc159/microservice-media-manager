"""Rigenera tests/fixtures/feed_p20_events.json e feed_p20_expected.xml.

Fixture dei tag Podcasting 2.0 / NIP-73: un 10154 con tutti i tag nuovi e due 54. Eseguire da
root del repo: `python3 tests/fixtures/gen_feed_p20.py` — poi RILEGGERE il golden prima di
committarlo: questo script fotografa l'output, non lo verifica.
"""
import json
import sys

sys.path.insert(0, ".")
from src.domains.feed.nostr import nip19  # noqa: E402
from src.domains.feed.services import rss_builder  # noqa: E402
from tests.nostr_fixtures import make_event, pubkey_of  # noqa: E402

SK = "c3" * 32
PK = pubkey_of(SK)
VR = ["value-recipient", "Alice", "node",
      "02d5c1bf8b940dc9cadca86d1b0a3c37fbe39cee4c7e839e33bef9174531d27f52", "90", "", "", ""]
VR_FEE = ["value-recipient", "Host", "node",
          "03ae9f91a0cb8ff43840e3c322c4c61f019d8c1c3cea15a25cfc425ac605e61a4a", "10", "",
          "", "true"]

card = make_event(SK, kind=10154, created_at=1760000000, tags=[
    ["title", "Radio Satoshi"],
    ["description", "Conversazioni su Bitcoin."],
    ["image", "https://cdn.example.org/cover.png"],
    ["i", "podcast:guid:917393e3-1b1e-5cef-ace4-edaa54e1f810"], ["k", "podcast:guid"],
    ["feed", "https://feed.radiosatoshi.example.org/rss.xml"],
    ["author", "Redazione Radio Satoshi"],
    ["email", "owner@radiosatoshi.example.org"],
    ["type", "serial"],
    ["value", "lightning", "keysend", "0.00000005000"],
    VR, VR_FEE,
    ["person", "Alice Rossi", "host", "cast", "https://cdn.example.org/alice.png",
     "https://alice.example.org"],
    ["funding", "https://radiosatoshi.example.org/sostieni", "Sostieni lo show"],
])
# Due episodi con published_at in ordine OPPOSTO al created_at: il feed segue published_at.
ep_a = make_event(SK, kind=54, created_at=1760900000, tags=[  # creato DOPO, pubblicato PRIMA
    ["title", "Ep. 1 — Migrato"],
    ["description", "Episodio importato da un vecchio host."],
    ["audio", "https://blossom.example.org/a.mp3", "audio/mpeg"],
    ["i", "podcast:item:guid:https://oldhost.example.com/ep?id=1&show=rs"],
    ["k", "podcast:item:guid"],
    ["published_at", "1700000000"],
    ["season", "1"], ["episode", "1"], ["episode-type", "full"],
    ["transcript", "https://cdn.example.org/ep1.vtt", "text/vtt"],
    ["transcript", "https://cdn.example.org/ep1.srt", "application/srt"],
    ["chapters", "https://cdn.example.org/ep1.json", "application/json+chapters"],
    ["person", "Bob Verdi", "guest", "", "", ""],
    ["value", "lightning", "keysend", "0.00000005000"], VR,
])
ep_b = make_event(SK, kind=54, created_at=1760800000, tags=[  # creato PRIMA, pubblicato DOPO
    ["title", "Ep. 2 — Trailer"],
    ["description", "Il trailer della stagione 2."],
    ["audio", "https://blossom.example.org/b.mp3", "audio/mpeg"],
    ["published_at", "1760500000"],
    ["season", "2"], ["episode", "2.5"], ["episode-type", "trailer"],
])
events = {"pubkey": PK, "card": card, "ep_a": ep_a, "ep_b": ep_b}
json.dump(events, open("tests/fixtures/feed_p20_events.json", "w"), indent=2, ensure_ascii=False)

RELAYS = ["wss://nos.example"]
body = rss_builder.build_feed(
    card=card, profile=None, episodes=[ep_b, ep_a], pubkey_hex=PK,
    feed_url=f"http://interno:8080/v0/feed/{nip19.hex_to_npub(PK)}.xml",
    lang="it", relays=RELAYS, episode_relay_hints=RELAYS,
    enclosure_lengths={"https://blossom.example.org/a.mp3": 1000,
                       "https://blossom.example.org/b.mp3": 2000})
open("tests/fixtures/feed_p20_expected.xml", "w").write(body)
print(body)
