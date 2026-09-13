"""Controller del dominio feed.

Le operationId dell'OAS risolvono qui via RelativeResolver("src.domains.feed.controllers"):
le funzioni vanno ri-esportate a livello di package perche' siano raggiungibili come
src.domains.feed.controllers.<operationId>.
"""
from .feed_controller import get_feed
from .health_controller import get_health

__all__ = [
    "get_health",
    "get_feed",
]
