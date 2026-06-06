"""Controller del dominio media.

Le operationId dell'OAS risolvono qui via RelativeResolver("src.domains.media.controllers"):
le funzioni vanno ri-esportate a livello di package perche' siano raggiungibili come
src.domains.media.controllers.<operationId>.
"""
from .health_controller import get_health
from .media_controller import (
    get_media,
    get_media_content,
    list_media,
    upload_media,
)

__all__ = [
    "get_health",
    "list_media",
    "get_media",
    "get_media_content",
    "upload_media",
]
