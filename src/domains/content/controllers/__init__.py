"""Controller del dominio content.

Le operationId dell'OAS risolvono qui via RelativeResolver("src.domains.content.controllers"):
le funzioni vanno ri-esportate a livello di package perche' siano raggiungibili come
src.domains.content.controllers.<operationId>.
"""
from .content_controller import generate_image, list_fonts
from .health_controller import get_health

__all__ = [
    "get_health",
    "generate_image",
    "list_fonts",
]
