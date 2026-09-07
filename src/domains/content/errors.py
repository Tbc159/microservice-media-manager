"""Eccezioni di dominio per `content`.

Disaccoppiano il service dal trasporto HTTP: il controller le traduce in status code
(400 asset mancante, 501 tipo non implementato) senza conoscere i dettagli interni.
"""
from typing import List, Optional


class AssetNotFound(Exception):
    """Un asset referenziato non e' stato risolto su source.

    Porta con se' il contesto necessario a rendere il `400` **diagnosticabile** dal client:
    - `field`: il campo della richiesta (es. `logo_host`, `layers[2].media`);
    - `value`: il valore ricevuto;
    - `searched_by`: come e' stato interpretato (`filename` o `id`);
    - `title_matches`: eventuali media il cui **title** coincide col valore — il tranello
      tipico e' passare il `title` al posto del `filename`; se ne troviamo, lo diciamo e
      suggeriamo il `filename` giusto.

    Perche' NON risolviamo direttamente per title: i title non sono univoci, quindi risolverli
    significherebbe o scegliere in silenzio (il footgun che stiamo togliendo) o rispondere 409
    su ogni ambiguita'. Manteniamo un'unica chiave di riferimento stabile e univoca (`filename`,
    generato dal servizio) e trasformiamo l'errore in un suggerimento puntuale.
    """

    def __init__(
        self,
        value,
        *,
        field: Optional[str] = None,
        searched_by: str = "filename",
        title_matches: Optional[List[dict]] = None,
    ) -> None:
        self.value = value
        self.field = field
        self.searched_by = searched_by
        self.title_matches = title_matches or []
        super().__init__(self.detail())

    def detail(self) -> str:
        loc = f" per il campo '{self.field}'" if self.field else ""
        msg = f"asset non trovato{loc}: '{self.value}' (ricerca per {self.searched_by})"
        if self.searched_by == "filename" and self.title_matches:
            names = ", ".join(
                f"id {m['id']} -> filename '{m['filename']}'" for m in self.title_matches
            )
            msg += (
                f". Esiste pero' un media con quel *title* ({names}): i riferimenti usano il "
                "**filename** (generato dal servizio, leggibile dalla risposta di POST /v0/media), "
                "non il title."
            )
        return msg

    def to_body(self) -> dict:
        body = {"detail": self.detail(), "value": self.value, "searched_by": self.searched_by}
        if self.field is not None:
            body["field"] = self.field
        return body


class TipoNonImplementato(Exception):
    """Il generatore per quel `tipo` non e' ancora implementato (es. social)."""

    def __init__(self, tipo: str) -> None:
        self.tipo = tipo
        super().__init__(f"tipo non ancora implementato: {tipo!r}")
