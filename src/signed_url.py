"""URL di lettura firmati e a scadenza per i byte di un media.

**Perche' servono.** `GET /v0/media/{id}/content` richiede `X-API-Key` in un header, ma il
browser NON allega header alle richieste di sotto-risorsa: `<img src>`, `<audio src>`,
`<video src>` ricevono `401`. Il front-end e' costretto a scaricare i byte con `fetch` e a
costruirsi un object URL — funziona, ma tiene il file in memoria e rinuncia alla cache HTTP e
allo streaming con `Range` (seek su audio/video lunghi).

**Cos'e' il token.** Un HMAC-SHA256 su `(id del media, scadenza)`, messo in query string. E'
un permesso **ristretto** che chi ha la chiave API puo' emettere:

- **legato a quel media**: l'id entra nella firma, quindi spostare il token su un altro id la
  invalida — non e' un confronto che si puo' dimenticare, e' il calcolo stesso;
- **in sola lettura**: e' accettato solo da `GET /media/{id}/content`, da nessun'altra rotta;
- **a scadenza**: oltre `MEDIA_URL_TTL_S` (default 900 s) non vale piu';
- **non revocabile singolarmente**: e' il prezzo dello stateless. La leva e' la scadenza breve
  (e la rotazione di `MEDIA_URL_SIGNING_KEY`, che invalida tutti i token emessi).

**Fail-closed.** Senza `MEDIA_URL_SIGNING_KEY` non si emette e non si accetta alcun token: i
byte non diventano pubblici per distrazione o per una variabile dimenticata. La chiave API
resta sempre valida e resta l'unico modo per *ottenere* un URL firmato.
"""
import base64
import hashlib
import hmac
import os
import time
from typing import Optional, Tuple

_VERSION = "v1"
_MEDIA_PREFIX = "/v0/media/"
_DEFAULT_TTL_S = 900        # 15 min: copre il rendering di una pagina e una sessione di ascolto
_MIN_TTL_S, _MAX_TTL_S = 30, 86400


def _key() -> str:
    return os.environ.get("MEDIA_URL_SIGNING_KEY", "").strip()


def enabled() -> bool:
    """True se la firma e' configurata. Senza chiave: niente `signed_url`, nessun token accettato."""
    return bool(_key())


def ttl_s() -> int:
    """Durata del token in secondi (`MEDIA_URL_TTL_S`), limitata a [30 s, 24 h]."""
    try:
        value = int(os.environ.get("MEDIA_URL_TTL_S", _DEFAULT_TTL_S))
    except ValueError:
        return _DEFAULT_TTL_S
    return max(_MIN_TTL_S, min(_MAX_TTL_S, value))


def _sign(key: str, media_id: int, exp: int) -> str:
    payload = f"{_VERSION}:{media_id}:{exp}".encode()
    digest = hmac.new(key.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def mint(media_id: int, *, now: Optional[int] = None) -> Optional[Tuple[str, int]]:
    """`(url firmato, scadenza epoch)` per quel media, o None se la firma non e' configurata."""
    key = _key()
    if not key:
        return None
    try:
        media_id = int(media_id)
    except (TypeError, ValueError):
        return None
    exp = int(now if now is not None else time.time()) + ttl_s()
    token = f"{_VERSION}.{exp}.{_sign(key, media_id, exp)}"
    return f"{_MEDIA_PREFIX}{media_id}/content?token={token}", exp


def verify(token: Optional[str], media_id, *, now: Optional[int] = None) -> bool:
    """True se il token e' valido **per quel media** e non e' scaduto."""
    key = _key()
    if not key or not token:
        return False
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _VERSION:
        return False
    try:
        exp, media_id = int(parts[1]), int(media_id)
    except (TypeError, ValueError):
        return False
    if exp < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(parts[2], _sign(key, media_id, exp))


def decorate(item: dict, media_id) -> dict:
    """Aggiunge `signed_url`/`signed_url_expires_at_s` al DTO, se la firma e' configurata.

    No-op quando la firma e' spenta: il contratto dichiara i due campi come opzionali, cosi'
    un ambiente senza chiave resta valido e il client capisce dalla loro assenza che deve
    usare `content_url` con la chiave API.
    """
    minted = mint(media_id)
    if minted is not None:
        item["signed_url"], item["signed_url_expires_at_s"] = minted
    return item
