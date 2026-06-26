"""Business logic del dominio `content`.

Orchestra la generazione: risolve gli asset (`MediaRef` = id intero o nome file) in byte
via il gateway verso `source`, invoca il renderer Pillow, salva l'immagine prodotta come
media su `source` e restituisce un DTO con gli URL pubblici (ri-mappati su /v0/media).
Il dispatch sul campo `tipo` lascia spazio a generatori futuri (social, ...).
"""
import uuid
from typing import List, Optional

from src.domains.content.errors import AssetNotFound, TipoNonImplementato
from src.domains.content.gateway import SourceGateway
from src.domains.content.services import copertina_renderer

_SOURCE_PREFIX = "/v0/source/media/"
_MEDIA_PREFIX = "/v0/media/"


class ImageService:
    def __init__(self, gateway: SourceGateway) -> None:
        self._gw = gateway

    def generate(self, body: dict) -> dict:
        """Genera l'immagine richiesta dal `tipo` e restituisce il DTO GeneratedImage.

        Raises:
            AssetNotFound: un asset referenziato non esiste su source (-> 400).
            TipoNonImplementato: generatore non ancora portato, es. social (-> 501).
        """
        tipo = body["tipo"]
        if tipo == "copertina":
            return self._generate_copertina(body)
        raise TipoNonImplementato(tipo)

    def _generate_copertina(self, body: dict) -> dict:
        formato = body.get("formato", "image/png")

        logo_bytes = self._fetch_ref(body["logo_host"])
        if logo_bytes is None:
            raise AssetNotFound(body["logo_host"])

        ospiti_bytes: List[Optional[bytes]] = [self._fetch_ref(o) for o in body.get("ospiti", [])]

        image = copertina_renderer.render_copertina(
            titolo=body["titolo"],
            testo_centrale=body["testo_centrale"],
            colore_sfondo=body.get("colore_sfondo", "#ff751f"),
            tipo_sfondo=body.get("tipo_sfondo", "unicolor"),
            colore_sfumato=body.get("colore_sfumato"),
            logo_bytes=logo_bytes,
            ospiti_bytes=ospiti_bytes,
            formato=formato,
        )

        filename = f"copertina-{uuid.uuid4().hex[:8]}.{copertina_renderer.ext_for(formato)}"
        title = " ".join(body["titolo"].split()) or "copertina"
        result = self._gw.upload_image(
            title=title, media_type=formato, filename=filename, data=image
        )
        if result.status_code != 201:
            # Improbabile (filename con uuid): propaga l'errore di source come 400.
            detail = result.payload.get("detail", "salvataggio immagine fallito")
            raise AssetNotFound(detail)
        return self._to_generated(result.payload, tipo="copertina", formato=formato)

    def _fetch_ref(self, ref) -> Optional[bytes]:
        """Risolve un MediaRef (id intero o nome file) nei byte dell'asset, o None."""
        # bool e' sottoclasse di int: lo schema usa interi, ma per sicurezza lo escludiamo.
        if isinstance(ref, bool):
            return None
        if isinstance(ref, int):
            return self._gw.get_bytes(ref)
        record = self._gw.resolve_filename(str(ref))
        if record is None:
            return None
        return self._gw.get_bytes(record["id"])

    @staticmethod
    def _to_generated(source_payload: dict, *, tipo: str, formato: str) -> dict:
        media_id = source_payload["id"]
        content_url = f"{_MEDIA_PREFIX}{media_id}/content"
        return {
            "id": media_id,
            "tipo": tipo,
            "media_type": source_payload.get("media_type", formato),
            "size_bytes": source_payload.get("size_bytes"),
            "created_at_s": source_payload["created_at_s"],
            "content_url": content_url,
            "download_url": f"{content_url}?download=1",
        }
