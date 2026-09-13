"""Validazione di un evento Nostr: struttura, id e firma.

Un feed pubblico che accetta relay dal chiamante (`?relays=`) non puo' fidarsi di cio' che
un relay restituisce. Tre controlli, in ordine di costo:

1. **forma** — campi presenti e del tipo giusto;
2. **id** — sha256 della serializzazione NIP-01: scopre un relay che altera il contenuto;
3. **firma** — BIP-340: e' l'unico che scopre un evento *fabbricato* (chi altera il contenuto
   ricalcola anche l'id, ma non sa rifirmare).

Gli eventi che non passano vengono scartati e contati: un feed con contenuti altrui sarebbe
peggio di un feed vuoto.
"""
import hashlib
import json
import logging
import os
from typing import Optional

from src.domains.feed.nostr import schnorr

logger = logging.getLogger("feed")

_REQUIRED = ("id", "pubkey", "created_at", "kind", "tags", "content", "sig")


def compute_id(event: dict) -> str:
    """sha256 della serializzazione canonica NIP-01 `[0, pubkey, created_at, kind, tags, content]`."""
    serialized = json.dumps(
        [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_signatures_enabled() -> bool:
    return os.environ.get("FEED_VERIFY_SIGNATURES", "1").strip() not in ("0", "false", "no")


def is_valid(event, *, pubkey: Optional[str] = None, verify_signature: Optional[bool] = None) -> bool:
    """True se l'evento e' ben formato, coerente col proprio id e firmato dal suo autore."""
    if not isinstance(event, dict) or any(k not in event for k in _REQUIRED):
        return False
    if not isinstance(event["tags"], list) or not isinstance(event["content"], str):
        return False
    if not isinstance(event["created_at"], int) or not isinstance(event["kind"], int):
        return False
    if pubkey is not None and event["pubkey"] != pubkey:
        return False
    try:
        if compute_id(event) != event["id"]:
            logger.warning("evento con id incoerente scartato: %s", event["id"][:12])
            return False
        if verify_signature is None:
            verify_signature = verify_signatures_enabled()
        if verify_signature and not schnorr.verify(
            bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]), bytes.fromhex(event["sig"])
        ):
            logger.warning("evento con firma non valida scartato: %s", event["id"][:12])
            return False
    except (ValueError, TypeError, KeyError):
        return False
    return True


def tag_values(event: dict, name: str) -> list:
    """Valori (tag[1:]) di tutti i tag con quel nome, nell'ordine dell'evento."""
    return [t[1:] for t in event.get("tags", []) if isinstance(t, list) and t and t[0] == name]


def first_tag_value(event: dict, name: str) -> Optional[str]:
    values = tag_values(event, name)
    return values[0][0] if values and values[0] else None
