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
    """Somma in coordinate affini (riferimento leggibile; il percorso caldo e' jacobiano)."""
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


# ── Coordinate jacobiane: (X, Y, Z) rappresenta (X/Z^2, Y/Z^3) ──────────────────
#
# In affine ogni somma costa un'inversione modulare (un `pow` a 256 bit): ~85 ms a verifica.
# In jacobiane le inversioni spariscono dal ciclo e ne resta una sola alla fine. Insieme al
# trucco di Shamir (s*G + k*P in un'unica passata di raddoppi) la verifica diventa abbastanza
# veloce da reggere la scansione dell'intero catalogo di un podcast.

_J_INF = (1, 1, 0)


def _j_double(pt):
    x, y, z = pt
    if z == 0 or y == 0:
        return _J_INF
    yy = y * y % _P
    s = 4 * x * yy % _P
    m = 3 * x * x % _P                       # a = 0 per secp256k1
    x3 = (m * m - 2 * s) % _P
    y3 = (m * (s - x3) - 8 * yy * yy) % _P
    return (x3, y3, 2 * y * z % _P)


def _j_add(p1, p2):
    if p1[2] == 0:
        return p2
    if p2[2] == 0:
        return p1
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    z1z1, z2z2 = z1 * z1 % _P, z2 * z2 % _P
    u1, u2 = x1 * z2z2 % _P, x2 * z1z1 % _P
    s1, s2 = y1 * z2 * z2z2 % _P, y2 * z1 * z1z1 % _P
    if u1 == u2:
        return _j_double(p1) if s1 == s2 else _J_INF
    h, r = (u2 - u1) % _P, (s2 - s1) % _P
    hh = h * h % _P
    hhh = h * hh % _P
    v = u1 * hh % _P
    x3 = (r * r - hhh - 2 * v) % _P
    y3 = (r * (v - x3) - s1 * hhh) % _P
    return (x3, y3, h * z1 * z2 % _P)


def _to_affine(pt) -> Point:
    x, y, z = pt
    if z == 0:
        return None
    zi = pow(z, -1, _P)
    zi2 = zi * zi % _P
    return (x * zi2 % _P, y * zi2 * zi % _P)


def _jac(point: Point):
    return _J_INF if point is None else (point[0], point[1], 1)


def _mul(point: Point, scalar: int) -> Point:
    """scalar * point (affine in ingresso e in uscita)."""
    result, addend = _J_INF, _jac(point)
    for i in range(scalar.bit_length()):
        if (scalar >> i) & 1:
            result = _j_add(result, addend)
        addend = _j_double(addend)
    return _to_affine(result)


def _mul_add(a: int, pa: Point, b: int, pb: Point) -> Point:
    """a*PA + b*PB in un'unica passata (Shamir): un raddoppio per bit invece di due."""
    ja, jb = _jac(pa), _jac(pb)
    jab = _j_add(ja, jb)
    result = _J_INF
    for i in range(max(a.bit_length(), b.bit_length()) - 1, -1, -1):
        result = _j_double(result)
        bit_a, bit_b = (a >> i) & 1, (b >> i) & 1
        if bit_a and bit_b:
            result = _j_add(result, jab)
        elif bit_a:
            result = _j_add(result, ja)
        elif bit_b:
            result = _j_add(result, jb)
    return _to_affine(result)


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
    candidate = _mul_add(s, _G, _N - e, point)
    if candidate is None or candidate[1] % 2 != 0 or candidate[0] != r:
        return False
    return True
