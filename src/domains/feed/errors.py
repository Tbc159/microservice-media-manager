"""Eccezioni di dominio per `feed`: il controller le traduce in HTTP."""
from typing import List


class InvalidKey(ValueError):
    """`{npub}` non e' ne' bech32 valido ne' 64 esadecimali -> 400."""


class NoPodcastCard(Exception):
    """Nessun kind 10154 per quella chiave sui relay interrogati -> 404.

    Porta con se' i relay: senza, un feed assente e' indistinguibile da un feed cercato nel
    posto sbagliato, che e' il caso di gran lunga piu' frequente.
    """

    def __init__(self, relays: List[str], unreached: List[str] = ()) -> None:
        self.relays = list(relays)
        self.unreached = list(unreached)
        super().__init__("nessuna scheda podcast (kind 10154)")

    def to_body(self) -> dict:
        body = {
            "detail": "nessuna scheda podcast (kind 10154) per questa chiave sui relay interrogati",
            "relays": self.relays,
        }
        if self.unreached:
            # Un 404 con relay senza risposta e' il caso peggiore: la scheda potrebbe esserci.
            body["detail"] += " (alcuni non hanno risposto: potrebbe essere un problema di relay)"
            body["unreached"] = self.unreached
        return body


class RateLimited(Exception):
    """Troppe richieste da questo IP -> 429."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("troppe richieste")
