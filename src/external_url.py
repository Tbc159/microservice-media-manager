"""URL **esterno** del servizio: quello con cui il mondo lo raggiunge.

`request.scheme` e `request.host` sono lo schema e l'host con cui la richiesta arriva *a noi*,
cioe' l'ultimo hop. Dietro a un reverse-proxy che termina il TLS sono `http` e un nome interno:
comporre un URL assoluto da li' produce link sbagliati che finiscono fuori dal servizio — un
`<atom:link rel="self">` in http sottomesso a Podcast Index, per dirne una gia' vista.

La fonte giusta sono gli header `X-Forwarded-*`, impostati dal proxy piu' esterno e **propagati**
da quelli intermedi (vedi `deploy/proxy/gen-nginx-conf.sh`: propaga il valore ricevuto e usa
`$scheme` solo se non c'e' nessuno davanti). Con piu' proxy in fila l'header puo' diventare una
lista (`https, http`): vale il **primo** valore, che e' quello dell'hop piu' vicino al client.

Nessuna fiducia mal riposta: questi header sono attendibili solo perche' l'unico ingresso e' il
reverse-proxy. Se un domani i container fossero raggiungibili direttamente, andrebbero filtrati
sull'IP del proxy.
"""
from typing import Optional


def _first(value: Optional[str]) -> Optional[str]:
    """Primo elemento di un header eventualmente a lista, o None se vuoto."""
    if not value:
        return None
    first = value.split(",")[0].strip()
    return first or None


def external_scheme(request) -> str:
    return _first(request.headers.get("X-Forwarded-Proto")) or request.scheme


def external_host(request) -> str:
    return (
        _first(request.headers.get("X-Forwarded-Host"))
        or request.headers.get("Host")
        or request.host
    )


def external_url(request, path: str) -> str:
    """URL assoluto di `path` (che deve iniziare con `/`) come lo vede il client."""
    return f"{external_scheme(request)}://{external_host(request)}{path}"
