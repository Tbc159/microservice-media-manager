"""Guardia SSRF condivisa: un host e' raggiungibile solo se risolve su IP pubblici.

Sta qui e non dentro un dominio perche' serve a piu' di uno — `media` la usa per il download
server-side di `POST /v0/media/from-url`, `feed` per i relay WebSocket e per la HEAD sugli
URL degli enclosure. Due copie della stessa logica divergerebbero, e una guardia SSRF che
diverge e' una guardia rotta.

Resta la finestra di DNS-rebinding (TOCTOU) fra il controllo e la connessione: mitigazione
completa = pinning sull'IP validato; qui accettiamo il rischio residuo.
"""
import ipaddress
import socket
from typing import Optional


class HostNotAllowed(ValueError):
    """L'host non risolve, o risolve su un indirizzo non pubblico."""


def ip_disallowed(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    # is_global esclude gia' privati/loopback/link-local/riservati; i controlli espliciti
    # rendono l'intento chiaro e robusto tra versioni di Python.
    return (
        not ip.is_global
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_host(host: Optional[str], port: int) -> None:
    """Solleva HostNotAllowed se l'host manca, non risolve o risolve su un IP non pubblico."""
    if not host:
        raise HostNotAllowed("URL senza host")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise HostNotAllowed(f"host non risolvibile: {host}") from exc
    for info in infos:
        addr = info[4][0]
        if ip_disallowed(addr):
            raise HostNotAllowed(f"host {host} risolve su un indirizzo non pubblico ({addr})")
