"""Helper per i test del dominio `feed`: eventi Nostr **realmente firmati**.

La firma BIP-340 sta qui e non in `src/` di proposito: il dominio feed e' in sola lettura
(nessuna scrittura su Nostr e' nel perimetro), ma le fixture devono passare la verifica vera,
altrimenti i test girerebbero con la verifica spenta e non proverebbero nulla.

`sign` e' l'inverso di `src.domains.feed.nostr.schnorr.verify`: che i due si accordino, e che
`verify` accetti gli eventi veri della rete (verificato in sviluppo), e' la garanzia che
l'implementazione sia corretta in entrambe le direzioni.
"""
import hashlib

from src.domains.feed.nostr import schnorr
from src.domains.feed.nostr.events import compute_id

_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


def _tagged(tag: str, msg: bytes) -> bytes:
    digest = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(digest + digest + msg).digest()


def pubkey_of(seckey_hex: str) -> str:
    d0 = int(seckey_hex, 16)
    point = schnorr._mul(schnorr._G, d0)
    return f"{point[0]:064x}"


def sign(msg32: bytes, seckey_hex: str, aux: bytes = b"\x00" * 32) -> str:
    d0 = int(seckey_hex, 16)
    point = schnorr._mul(schnorr._G, d0)
    d = d0 if point[1] % 2 == 0 else _N - d0
    px = point[0].to_bytes(32, "big")
    t = (d ^ int.from_bytes(_tagged("BIP0340/aux", aux), "big")).to_bytes(32, "big")
    k0 = int.from_bytes(_tagged("BIP0340/nonce", t + px + msg32), "big") % _N
    r_point = schnorr._mul(schnorr._G, k0)
    k = k0 if r_point[1] % 2 == 0 else _N - k0
    rx = r_point[0].to_bytes(32, "big")
    e = int.from_bytes(_tagged("BIP0340/challenge", rx + px + msg32), "big") % _N
    return (rx + ((k + e * d) % _N).to_bytes(32, "big")).hex()


def make_event(seckey_hex: str, *, kind: int, created_at: int, tags=(), content: str = "") -> dict:
    """Evento Nostr completo di `id` e `sig` validi."""
    event = {
        "pubkey": pubkey_of(seckey_hex),
        "created_at": created_at,
        "kind": kind,
        "tags": [list(t) for t in tags],
        "content": content,
    }
    event["id"] = compute_id(event)
    event["sig"] = sign(bytes.fromhex(event["id"]), seckey_hex)
    return event


class FakeRelays:
    """Sostituto di `relay_client`: serve eventi da una lista, senza rete.

    Risponde ai filtri come farebbe un relay (kinds/authors/limit), cosi' il service esercita
    davvero la selezione per kind e l'ordinamento, non una lista gia' pronta.
    """

    def __init__(self, events, *, reached=None, fail=()):
        self.events = list(events)
        self._reached = reached
        self.fail = set(fail)
        self.calls = []

    def query(self, relays, filters, *, timeout=None):
        from src.domains.feed.nostr.relay_client import RelayQueryResult

        self.calls.append((list(relays), list(filters)))
        reached = [r for r in relays if r not in self.fail]
        if self._reached is not None:
            reached = [r for r in reached if r in self._reached]
        out = []
        if reached:
            for f in filters:
                kinds, authors = f.get("kinds"), f.get("authors")
                picked = [
                    e for e in self.events
                    if (kinds is None or e["kind"] in kinds)
                    and (authors is None or e["pubkey"] in authors)
                ]
                picked.sort(key=lambda e: e["created_at"], reverse=True)
                out.extend(picked[: f.get("limit", 500)])
        return RelayQueryResult(events=out, queried=list(relays), reached=reached)


class MemoryStore:
    """EnclosureStore in memoria: `lengths` preimpostate, il resto risulta assente."""

    def __init__(self, lengths=None):
        self.lengths = dict(lengths or {})
        self.written = {}

    def get(self, url, *, now=None):
        return (url in self.lengths, self.lengths.get(url))

    def put(self, url, length, *, now=None):
        self.written[url] = length
        self.lengths[url] = length
