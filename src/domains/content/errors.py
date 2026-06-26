"""Eccezioni di dominio per `content`.

Disaccoppiano il service dal trasporto HTTP: il controller le traduce in status code
(400 asset mancante, 501 tipo non implementato) senza conoscere i dettagli interni.
"""


class AssetNotFound(Exception):
    """Un asset referenziato (logo/ospite, per id o nome file) non esiste su source."""

    def __init__(self, ref) -> None:
        self.ref = ref
        super().__init__(f"asset non trovato: {ref!r}")


class TipoNonImplementato(Exception):
    """Il generatore per quel `tipo` non e' ancora implementato (es. social)."""

    def __init__(self, tipo: str) -> None:
        self.tipo = tipo
        super().__init__(f"tipo non ancora implementato: {tipo!r}")
