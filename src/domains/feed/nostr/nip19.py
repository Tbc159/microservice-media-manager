"""NIP-19: identificatori bech32 di Nostr (`npub`, `nevent`).

Implementato qui invece di aggiungere una dipendenza: il codec bech32 e' BIP-173, ~40 righe
e verificabile sui vettori ufficiali, mentre la parte TLV di `nevent` e' specifica di Nostr e
nessuna libreria bech32 generica la fornisce. Il tutto e' puro: niente rete, niente stato.

Attenzione a un punto: BIP-173 limita le stringhe a 90 caratteri, **NIP-19 rimuove il limite**
(un `nevent` con piu' relay hint lo supera facilmente). Qui infatti non lo applichiamo.
"""
from typing import List, Optional, Tuple

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GENERATOR = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)

# Tipi TLV di NIP-19.
_TLV_SPECIAL, _TLV_RELAY, _TLV_AUTHOR, _TLV_KIND = 0, 1, 2, 3


class Nip19Error(ValueError):
    """Identificatore non valido (charset, checksum, hrp o payload)."""


def _polymod(values: List[int]) -> int:
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= _GENERATOR[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> List[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _checksum(hrp: str, data: List[int]) -> List[int]:
    polymod = _polymod(_hrp_expand(hrp) + data + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def bech32_encode(hrp: str, data: List[int]) -> str:
    return hrp + "1" + "".join(_CHARSET[d] for d in data + _checksum(hrp, data))


def bech32_decode(value: str) -> Tuple[str, List[int]]:
    """`(hrp, data a 5 bit)`. Solleva Nip19Error su charset/checksum/formato non validi."""
    if any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise Nip19Error("caratteri fuori range")
    if value.lower() != value and value.upper() != value:
        raise Nip19Error("maiuscole e minuscole mescolate")
    value = value.lower()
    pos = value.rfind("1")
    if pos < 1 or pos + 7 > len(value):
        raise Nip19Error("separatore assente o posizione non valida")
    hrp, payload = value[:pos], value[pos + 1 :]
    try:
        data = [_CHARSET.index(c) for c in payload]
    except ValueError as exc:
        raise Nip19Error("carattere non nel charset bech32") from exc
    if _polymod(_hrp_expand(hrp) + data) != 1:
        raise Nip19Error("checksum non valido")
    return hrp, data[:-6]


def convertbits(data, frombits: int, tobits: int, pad: bool = True) -> Optional[List[int]]:
    """Ricompattamento di bit (BIP-173). None se il padding residuo non e' valido."""
    acc, bits, out = 0, 0, []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return out


# ── npub ────────────────────────────────────────────────────────────────────────

def npub_to_hex(npub: str) -> str:
    """`npub1...` -> pubkey esadecimale (64 caratteri)."""
    hrp, data = bech32_decode(npub)
    if hrp != "npub":
        raise Nip19Error(f"atteso un npub, ricevuto '{hrp}'")
    raw = convertbits(data, 5, 8, False)
    if raw is None or len(raw) != 32:
        raise Nip19Error("payload npub non di 32 byte")
    return bytes(raw).hex()


def hex_to_npub(pubkey_hex: str) -> str:
    raw = bytes.fromhex(pubkey_hex)
    if len(raw) != 32:
        raise Nip19Error("pubkey non di 32 byte")
    return bech32_encode("npub", convertbits(list(raw), 8, 5))


def normalize_pubkey(value: str) -> str:
    """Accetta `npub1...` **oppure** 64 esadecimali e restituisce sempre l'esadecimale."""
    value = (value or "").strip()
    if len(value) == 64:
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise Nip19Error("chiave esadecimale non valida") from exc
        return value.lower()
    return npub_to_hex(value)


# ── nevent (TLV) ────────────────────────────────────────────────────────────────

def _tlv(kind: int, payload: bytes) -> bytes:
    if len(payload) > 255:
        payload = payload[:255]
    return bytes([kind, len(payload)]) + payload


def encode_nevent(event_id_hex: str, *, relays=(), author_hex: Optional[str] = None,
                  kind: Optional[int] = None) -> str:
    """`nevent1...` con gli hint di relay: senza, un client non sa dove ripescare l'evento."""
    raw = _tlv(_TLV_SPECIAL, bytes.fromhex(event_id_hex))
    for relay in relays:
        raw += _tlv(_TLV_RELAY, relay.encode("ascii", "ignore"))
    if author_hex:
        raw += _tlv(_TLV_AUTHOR, bytes.fromhex(author_hex))
    if kind is not None:
        raw += _tlv(_TLV_KIND, kind.to_bytes(4, "big"))
    return bech32_encode("nevent", convertbits(list(raw), 8, 5))


def decode_nevent(nevent: str) -> dict:
    """Inverso di `encode_nevent` (serve ai test: verifica il TLV, non solo il round-trip)."""
    hrp, data = bech32_decode(nevent)
    if hrp != "nevent":
        raise Nip19Error(f"atteso un nevent, ricevuto '{hrp}'")
    raw = convertbits(data, 5, 8, False)
    if raw is None:
        raise Nip19Error("payload nevent non valido")
    raw = bytes(raw)
    out: dict = {"relays": []}
    i = 0
    while i + 2 <= len(raw):
        tag, length = raw[i], raw[i + 1]
        chunk, i = raw[i + 2 : i + 2 + length], i + 2 + length
        if tag == _TLV_SPECIAL:
            out["id"] = chunk.hex()
        elif tag == _TLV_RELAY:
            out["relays"].append(chunk.decode("ascii", "ignore"))
        elif tag == _TLV_AUTHOR:
            out["author"] = chunk.hex()
        elif tag == _TLV_KIND:
            out["kind"] = int.from_bytes(chunk, "big")
    return out
