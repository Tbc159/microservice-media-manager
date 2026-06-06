"""Composition root del dominio `media` (BFF).

Costruisce il MediaService col gateway verso `source`. L'URL interno e la API key
arrivano dall'ambiente:
  SOURCE_INTERNAL_URL  base del dominio source sulla rete interna
                       (default http://source:8080/v0/source)
  API_KEY              chiave usata per autenticarsi verso source
"""
import os

from .gateway import SourceGateway
from .services.media_service import MediaService


def build_media_service() -> MediaService:
    base_url = os.environ.get("SOURCE_INTERNAL_URL", "http://source:8080/v0/source")
    api_key = os.environ.get("API_KEY", "")
    return MediaService(SourceGateway(base_url=base_url, api_key=api_key))
