"""Verifica delle firme Schnorr BIP-340 degli eventi Nostr (secp256k1, Python puro).

**Perche' c'e'.** Il feed e' pubblico e il chiamante puo' aggiungere relay con `?relays=`:
senza verifica, chiunque puo' far servire al nostro dominio contenuti arbitrari attribuiti a
un `npub` altrui, e quell'URL finisce su Podcast Index. Controllare solo l'`id` non basta —
l'id e' un hash del contenuto, un falsificatore lo ricalcola. Serve la firma.

Python puro perche' non c'e' una libreria secp256k1 fra le dipendenze e aggiungerne una
(binaria, da compilare) per ~60 righe di aritmetica modulare non si giustifica. Il costo e'
qualche millisecondo per evento, assorbito dalla cache del feed; `FEED_VERIFY_SIGNATURES=0`
lo disattiva se un giorno il volume lo rendesse un problema.
"""
import hashlib
from typing import Optional, Tuple

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

Point = Optional[Tuple[int, int]]


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    digest = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(digest + digest + msg).digest()


def _add(p1: Point, p2: Point) -> Point:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    if p1[0] == p2[0] and p1[1] != p2[1]:
        return None
    if p1 == p2:
        lam = 3 * p1[0] * p1[0] * pow(2 * p1[1], _P - 2, _P) % _P
    else:
        lam = (p2[1] - p1[1]) * pow(p2[0] - p1[0], _P - 2, _P) % _P
    x = (lam * lam - p1[0] - p2[0]) % _P
    return (x, (lam * (p1[0] - x) - p1[1]) % _P)


def _mul(point: Point, scalar: int) -> Point:
    result: Point = None
    for i in range(256):
        if (scalar >> i) & 1:
            result = _add(result, point)
        point = _add(point, point)
    return result


def _lift_x(x: int) -> Point:
    """Punto con coordinata x e y pari (chiave pubblica x-only di BIP-340)."""
    if x >= _P:
        return None
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_sq:
        return None
    return (x, y if y % 2 == 0 else _P - y)


def verify(msg32: bytes, pubkey32: bytes, sig64: bytes) -> bool:
    """True se `sig64` e' una firma BIP-340 valida di `msg32` per la chiave x-only `pubkey32`."""
    if len(msg32) != 32 or len(pubkey32) != 32 or len(sig64) != 64:
        return False
    point = _lift_x(int.from_bytes(pubkey32, "big"))
    if point is None:
        return False
    r = int.from_bytes(sig64[:32], "big")
    s = int.from_bytes(sig64[32:], "big")
    if r >= _P or s >= _N:
        return False
    e = int.from_bytes(_tagged_hash("BIP0340/challenge", sig64[:32] + pubkey32 + msg32), "big") % _N
    candidate = _add(_mul(_G, s), _mul(point, _N - e))
    if candidate is None or candidate[1] % 2 != 0 or candidate[0] != r:
        return False
    return True
