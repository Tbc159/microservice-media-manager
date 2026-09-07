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
from src.domains.content.services import copertina_renderer, layer_compositor

_SOURCE_PREFIX = "/v0/source/media/"
_MEDIA_PREFIX = "/v0/media/"


def _is_int_ref(ref) -> bool:
    """True se il MediaRef e' un id intero (bool escluso: e' sottoclasse di int)."""
    return isinstance(ref, int) and not isinstance(ref, bool)


class ImageService:
    def __init__(self, gateway: SourceGateway) -> None:
        self._gw = gateway

    _FONT_TYPES = ("font/ttf", "font/otf")

    def list_fonts(self) -> list[dict]:
        """Catalogo dei font disponibili (da source), ordinati per nome."""
        items: list[dict] = []
        for media_type in self._FONT_TYPES:
            items.extend(self._gw.list_by_type(media_type))
        fonts = [
            {
                "id": it["id"],
                "name": it.get("title"),
                "filename": it["filename"],
                "media_type": it["media_type"],
                "size_bytes": it.get("size_bytes"),
                "created_at_s": it["created_at_s"],
            }
            for it in items
        ]
        return sorted(fonts, key=lambda f: (f["name"] or f["filename"]).lower())

    def generate(self, body: dict) -> dict:
        """Genera l'immagine richiesta dal `tipo` e restituisce il DTO GeneratedImage.

        Raises:
            AssetNotFound: un asset referenziato non esiste su source (-> 400).
            TipoNonImplementato: generatore non ancora portato, es. social (-> 501).
        """
        tipo = body["tipo"]
        if tipo == "copertina":
            return self._generate_copertina(body)
        if tipo == "composita":
            return self._generate_composita(body)
        raise TipoNonImplementato(tipo)

    def _generate_copertina(self, body: dict) -> dict:
        formato = body.get("formato", "image/png")
        warnings: List[str] = []

        logo_bytes = self._fetch_ref(body["logo_host"])
        if logo_bytes is None:
            raise self._asset_not_found(body["logo_host"], field="logo_host")

        ospiti_bytes: List[Optional[bytes]] = [self._fetch_ref(o) for o in body.get("ospiti", [])]
        font_titolo = self._fetch_font(body.get("font_titolo"), "titolo", "font_titolo", warnings)
        font_testo = self._fetch_font(body.get("font_testo"), "testo", "font_testo", warnings)

        image, render_warnings = copertina_renderer.render_copertina(
            titolo=body["titolo"],
            testo_centrale=body["testo_centrale"],
            colore_sfondo=body.get("colore_sfondo", "#ff751f"),
            tipo_sfondo=body.get("tipo_sfondo", "unicolor"),
            colore_sfumato=body.get("colore_sfumato"),
            logo_bytes=logo_bytes,
            ospiti_bytes=ospiti_bytes,
            formato=formato,
            font_titolo_bytes=font_titolo,
            font_testo_bytes=font_testo,
        )
        warnings.extend(render_warnings)

        filename = f"copertina-{uuid.uuid4().hex[:8]}.{copertina_renderer.ext_for(formato)}"
        title = " ".join(body["titolo"].split()) or "copertina"
        result = self._gw.upload_image(
            title=title, media_type=formato, filename=filename, data=image
        )
        if result.status_code != 201:
            # Improbabile (filename con uuid): propaga l'errore di source come 400.
            detail = result.payload.get("detail", "salvataggio immagine fallito")
            raise AssetNotFound(detail)
        dto = self._to_generated(result.payload, tipo="copertina", formato=formato)
        dto["warnings"] = warnings
        return dto

    def _generate_composita(self, body: dict) -> dict:
        """Layer engine: resolve each layer's assets to bytes, compose, save, return DTO.

        Missing asset on a person/image layer → skipped with warning, unless `required: true`
        (→ AssetNotFound/400). A missing background image falls back to its color.
        """
        formato = body.get("formato", "image/png")
        warnings: List[str] = []
        resolved: List[dict] = []

        for i, layer in enumerate(body["layers"]):
            ltype = layer["type"]
            field = f"layers[{i}].media"
            if ltype == "background":
                item = dict(layer)
                ref = layer.get("media")
                item["image_bytes"] = self._fetch_ref(ref) if ref is not None else None
                if ref is not None and item["image_bytes"] is None:
                    warnings.append(
                        f"sfondo ({field}) '{ref}' non trovato per filename: usato il colore di fallback"
                    )
                resolved.append(item)
            elif ltype in ("person", "image"):
                ref = layer["media"]
                data = self._fetch_ref(ref)
                if data is None:
                    if layer.get("required"):
                        raise self._asset_not_found(ref, field=field)
                    warnings.append(
                        f"layer {ltype} ({field}) '{ref}' non trovato per filename: layer saltato"
                    )
                    continue
                item = dict(layer)
                item["image_bytes"] = data
                resolved.append(item)
            elif ltype == "text":
                item = dict(layer)
                font_ref = layer.get("font")
                item["font_bytes"] = (
                    self._fetch_font(font_ref, "testo", f"layers[{i}].font", warnings)
                    if font_ref is not None
                    else None
                )
                resolved.append(item)

        image, render_warnings = layer_compositor.render_composita(resolved, formato=formato)
        warnings.extend(render_warnings)

        filename = f"composita-{uuid.uuid4().hex[:8]}.{copertina_renderer.ext_for(formato)}"
        result = self._gw.upload_image(
            title="composizione", media_type=formato, filename=filename, data=image
        )
        if result.status_code != 201:
            raise AssetNotFound(result.payload.get("detail", "salvataggio immagine fallito"))
        dto = self._to_generated(result.payload, tipo="composita", formato=formato)
        dto["warnings"] = warnings
        return dto

    def _fetch_font(self, ref, role: str, field: str, warnings: List[str]) -> Optional[bytes]:
        """Risolve un font referenziato (id o nome file) nei byte. Ref assente -> None
        (il renderer usa il Montserrat bundle). Ref presente ma non trovato -> warning + None
        (degradazione soft: il font richiesto non esiste, si userà il predefinito)."""
        if ref is None:
            return None
        data = self._fetch_ref(ref)
        if data is None:
            by = "id" if _is_int_ref(ref) else "filename"
            warnings.append(
                f"font {role} ({field}) '{ref}' non trovato (ricerca per {by}): "
                "usato il font predefinito"
            )
        return data

    def _fetch_ref(self, ref) -> Optional[bytes]:
        """Risolve un MediaRef (id intero o nome file) nei byte dell'asset, o None."""
        if _is_int_ref(ref):
            return self._gw.get_bytes(ref)
        record = self._gw.resolve_filename(str(ref))
        if record is None:
            return None
        return self._gw.get_bytes(record["id"])

    def _asset_not_found(self, value, *, field: str) -> AssetNotFound:
        """Costruisce un AssetNotFound diagnosticabile. Per un riferimento-stringa (ricerca
        per filename) cerca un match per **title** e lo allega come suggerimento: e' il
        tranello tipico (title al posto di filename)."""
        if _is_int_ref(value):
            return AssetNotFound(value, field=field, searched_by="id")
        matches = self._gw.find_by_title(str(value))
        return AssetNotFound(
            value,
            field=field,
            searched_by="filename",
            title_matches=[{"id": m["id"], "filename": m["filename"]} for m in matches],
        )

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
