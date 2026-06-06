"""Controller del dominio source.

Le operationId dell'OAS risolvono qui via RelativeResolver("src.domains.source.controllers"):
le funzioni vanno ri-esportate a livello di package perche' siano raggiungibili come
src.domains.source.controllers.<operationId>.
"""
from .health_controller import get_health
from .source_controller import (
    get_source_media,
    get_source_media_content,
    query_source_media,
    upload_source_media,
)

__all__ = [
    "get_health",
    "query_source_media",
    "get_source_media",
    "upload_source_media",
    "get_source_media_content",
]
