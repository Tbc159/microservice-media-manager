"""Rate limit per IP, a finestra fissa e in memoria.

Serve al dominio `feed`, che e' **pubblico e senza autenticazione**: senza un limite, una
singola richiesta ripetuta costringe il servizio ad aprire WebSocket verso i relay.

In memoria e per processo: sufficiente qui, dove ogni dominio gira in un container con un
processo. Non e' un limite distribuito e non pretende di esserlo — se un giorno servisse,
il posto giusto sarebbe il reverse-proxy o uno store condiviso.

L'IP si legge da `X-Real-IP`, che imposta **nginx** (`proxy_set_header X-Real-IP $remote_addr`):
e' il peer visto dal proxy, non un header che il client possa falsificare a piacimento. Senza
proxy davanti si ricade sull'indirizzo della connessione.
"""
import os
import threading
import time
from typing import Dict, Optional, Tuple

_DEFAULT_LIMIT = 60
_DEFAULT_WINDOW_S = 60


def limit() -> int:
    try:
        return max(1, int(os.environ.get("FEED_RATE_LIMIT", _DEFAULT_LIMIT)))
    except ValueError:
        return _DEFAULT_LIMIT


def window_s() -> int:
    try:
        return max(1, int(os.environ.get("FEED_RATE_WINDOW_S", _DEFAULT_WINDOW_S)))
    except ValueError:
        return _DEFAULT_WINDOW_S


class FixedWindowLimiter:
    """`check(key)` -> (consentito, secondi di attesa). Finestra fissa, contatore per chiave."""

    def __init__(self, max_requests: Optional[int] = None, window: Optional[int] = None) -> None:
        self._max = max_requests
        self._window = window
        self._lock = threading.Lock()
        self._counters: Dict[str, Tuple[int, int]] = {}     # key -> (inizio finestra, conteggio)

    def check(self, key: str, *, now: Optional[float] = None) -> Tuple[bool, int]:
        max_requests = self._max if self._max is not None else limit()
        window = self._window if self._window is not None else window_s()
        now = int(now if now is not None else time.time())
        start = now - (now % window)
        with self._lock:
            if len(self._counters) > 10000:                 # igiene: non crescere all'infinito
                self._counters = {k: v for k, v in self._counters.items() if v[0] >= start}
            window_start, count = self._counters.get(key, (start, 0))
            if window_start != start:
                window_start, count = start, 0
            if count >= max_requests:
                return False, max(1, window_start + window - now)
            self._counters[key] = (window_start, count + 1)
        return True, 0


def client_ip(request) -> str:
    """IP del chiamante: X-Real-IP messo da nginx, altrimenti il peer della connessione."""
    return (request.headers.get("X-Real-IP") or request.remote_addr or "sconosciuto").strip()
