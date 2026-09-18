"""Lettura da relay Nostr via WebSocket.

Interroga piu' relay **in parallelo**, unisce e deduplica gli eventi per id, e riporta quali
relay hanno risposto: un feed vuoto e' quasi sempre un problema di relay, non di dati, e senza
questa informazione non e' diagnosticabile.

Un relay lento o irraggiungibile non deve bloccare la risposta: ogni relay ha il proprio
timeout e i suoi errori vengono assorbiti (il feed si costruisce con quello che e' arrivato).
Ma un relay che va in **timeout** — non uno che rifiuta la connessione — spesso risponde se gli
si da' piu' tempo: un secondo tentativo con timeout doppio costa pochi secondi e evita di
dichiarare "non raggiunto" un relay che tiene gli episodi vecchi. Il chiamante sa comunque
com'e' andata: `reached < queried` significa risultato **parziale**.
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
_RETRY_TIMEOUT_FACTOR = 2


@dataclass
class RelayQueryResult:
    events: List[dict] = field(default_factory=list)
    queried: List[str] = field(default_factory=list)
    reached: List[str] = field(default_factory=list)

    @property
    def unreached(self) -> List[str]:
        """Relay interrogati che non hanno risposto: se non e' vuoto il risultato e' PARZIALE."""
        reached = set(self.reached)
        return [u for u in self.queried if u not in reached]

    @property
    def partial(self) -> bool:
        return bool(self.unreached)


def timeout_s() -> float:
    try:
        return float(os.environ.get("FEED_RELAY_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


def retry_on_timeout() -> bool:
    """Secondo tentativo (timeout doppio) per i relay in timeout. `FEED_RELAY_RETRY=0` lo spegne."""
    return os.environ.get("FEED_RELAY_RETRY", "1").strip() not in ("0", "false", "no")


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


async def _query_all(relays: Sequence[str], filters: Sequence[dict], timeout: float) -> dict:
    """url -> lista eventi, oppure l'eccezione. Tutti in parallelo, nessuno blocca gli altri."""
    outcomes = await asyncio.gather(
        *(asyncio.wait_for(_query_one(url, filters, timeout), timeout + 2) for url in relays),
        return_exceptions=True,
    )
    return dict(zip(relays, outcomes))


async def _gather(relays: Sequence[str], filters: Sequence[dict], timeout: float,
                  retry: bool = None) -> RelayQueryResult:
    result = RelayQueryResult(queried=list(relays))
    outcomes = await _query_all(relays, filters, timeout)

    # Secondo tentativo, solo per chi e' andato in TIMEOUT: un rifiuto di connessione o un
    # errore di protocollo non cambiano dandogli piu' tempo, un relay lento si'.
    retry = retry_on_timeout() if retry is None else retry
    timed_out = [u for u, o in outcomes.items() if isinstance(o, TimeoutError)]
    if retry and timed_out:
        logger.info("relay in timeout, secondo tentativo con timeout x%s: %s",
                    _RETRY_TIMEOUT_FACTOR, timed_out)
        outcomes.update(await _query_all(timed_out, filters, timeout * _RETRY_TIMEOUT_FACTOR))

    seen: Dict[str, dict] = {}
    for url in relays:
        outcome = outcomes[url]
        if isinstance(outcome, BaseException):
            logger.warning("relay non raggiunto %s: %s", url, type(outcome).__name__)
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
