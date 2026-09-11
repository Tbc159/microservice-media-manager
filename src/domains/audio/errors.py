"""Errori del dominio audio, diagnosticabili (dicono QUALE riferimento e con QUALE criterio).

Il controller li traduce in `400` con corpo `Error` (`detail`/`field`/`value`/`searched_by`),
come nel dominio content: un `400` generico non lascia distinguere "campo sbagliato" da
"file assente".
"""
from typing import Optional


class RefNotResolved(Exception):
    """Un `MediaRef` non e' stato risolto su source."""

    def __init__(self, value, *, field: str, searched_by: str) -> None:
        self.value = value
        self.field = field
        self.searched_by = searched_by
        super().__init__(self.detail())

    def detail(self) -> str:
        return (
            f"riferimento non risolto per il campo '{self.field}': '{self.value}' "
            f"(ricerca per {self.searched_by})"
        )

    def to_body(self) -> dict:
        return {
            "detail": self.detail(), "field": self.field,
            "value": self.value, "searched_by": self.searched_by,
        }


class FormatNotSupported(Exception):
    """Formato input/output non supportato dall'operazione."""

    def __init__(self, media_type: Optional[str], *, field: str, accepted) -> None:
        self.media_type = media_type or "(sconosciuto)"
        self.field = field
        self.accepted = sorted(accepted)
        super().__init__(self.detail())

    def detail(self) -> str:
        return (
            f"formato non supportato per '{self.field}': '{self.media_type}'. "
            f"Accettati: {', '.join(self.accepted)}"
        )

    def to_body(self) -> dict:
        return {"detail": self.detail(), "field": self.field, "value": self.media_type}
