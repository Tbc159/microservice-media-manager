"""Composition root del dominio `content` (BFF di generazione immagini).

Costruisce l'ImageService col gateway verso `source`. URL interno e API key dall'ambiente:
  SOURCE_INTERNAL_URL  base del dominio source sulla rete interna
                       (default http://source:8080/v0/source)
  API_KEY              chiave usata per autenticarsi verso source
"""
import os

from .gateway import SourceGateway
from .services.image_service import ImageService


def build_image_service() -> ImageService:
    base_url = os.environ.get("SOURCE_INTERNAL_URL", "http://source:8080/v0/source")
    api_key = os.environ.get("API_KEY", "")
    return ImageService(SourceGateway(base_url=base_url, api_key=api_key))
