"""Controller del dominio `content`: thin layer.

Delega all'ImageService (assemblato dal factory) e traduce gli esiti in HTTP:
- 201 con il DTO GeneratedImage;
- 400 se un asset (logo/ospite) non esiste;
- 501 se il `tipo` richiesto non e' ancora implementato (es. social).
"""
from src.domains.content.errors import AssetNotFound, TipoNonImplementato
from src.domains.content.factory import build_image_service

_service = build_image_service()


def generate_image(body: dict):
    try:
        item = _service.generate(body)
    except TipoNonImplementato as exc:
        return {"detail": f"tipo non ancora implementato: {exc.tipo}"}, 501
    except AssetNotFound as exc:
        return {"detail": f"asset non trovato: {exc.ref}"}, 400
    return item, 201
