"""Lettura da relay Nostr via WebSocket.

Interroga piu' relay **in parallelo**, unisce e deduplica gli eventi per id, e riporta quali
relay hanno risposto: un feed vuoto e' quasi sempre un problema di relay, non di dati, e senza
questa informazione non e' diagnosticabile.

Un relay lento o irraggiungibile non deve bloccare la risposta: ogni relay ha il proprio
timeout e i suoi errori vengono assorbiti (il feed si costruisce con quello che e' arrivato).
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

try:
    import websockets
except ImportError:  # pragma: no cover - dipendenza dichiarata in requirements.txt
    websockets = None

logger = logging.getLogger("feed")

_DEFAULT_TIMEOUT_S = 6.0
_MAX_EVENTS_PER_RELAY = 500


@dataclass
class RelayQueryResult:
    events: List[dict] = field(default_factory=list)
    queried: List[str] = field(default_factory=list)
    reached: List[str] = field(default_factory=list)


def timeout_s() -> float:
    try:
        return float(os.environ.get("FEED_RELAY_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


async def _query_one(url: str, filters: Sequence[dict], timeout: float) -> List[dict]:
    events: List[dict] = []
    async with websockets.connect(url, open_timeout=timeout, close_timeout=1) as ws:
        await ws.send(json.dumps(["REQ", "feed", *filters]))
        deadline = asyncio.get_event_loop().time() + timeout
        while len(events) < _MAX_EVENTS_PER_RELAY:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            raw = await asyncio.wait_for(ws.recv(), remaining)
            message = json.loads(raw)
            if not isinstance(message, list) or not message:
                continue
            if message[0] == "EVENT" and len(message) >= 3:
                events.append(message[2])
            elif message[0] in ("EOSE", "CLOSED"):
                break
    return events


async def _gather(relays: Sequence[str], filters: Sequence[dict], timeout: float) -> RelayQueryResult:
    result = RelayQueryResult(queried=list(relays))
    outcomes = await asyncio.gather(
        *(asyncio.wait_for(_query_one(url, filters, timeout), timeout + 2) for url in relays),
        return_exceptions=True,
    )
    seen: Dict[str, dict] = {}
    for url, outcome in zip(relays, outcomes):
        if isinstance(outcome, BaseException):
            logger.info("relay non utilizzabile %s: %s", url, type(outcome).__name__)
            continue
        result.reached.append(url)
        for event in outcome:
            if isinstance(event, dict) and isinstance(event.get("id"), str):
                seen.setdefault(event["id"], event)
    result.events = list(seen.values())
    return result


def query(relays: Sequence[str], filters: Sequence[dict], *, timeout: float = None) -> RelayQueryResult:
    """Interroga i relay e restituisce gli eventi deduplicati. Sincrona: la usa il controller."""
    relays = list(dict.fromkeys(relays))          # dedup mantenendo l'ordine
    if not relays or websockets is None:
        return RelayQueryResult(queried=relays)
    timeout = timeout_s() if timeout is None else timeout
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_gather(relays, filters, timeout))
    # Gia' dentro un event loop (caso raro): un loop dedicato in un thread separato.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _gather(relays, filters, timeout)).result()
