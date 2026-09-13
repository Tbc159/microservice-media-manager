"""Assemblaggio del dominio `feed` (composition root).

Variabili d'ambiente:
  FEED_DB_PATH             cache persistente delle dimensioni enclosure (default /data/feed.db)
  FEED_CACHE_TTL_S         durata della cache del feed generato (default 300, = max-age)
  FEED_MAX_EPISODES        tetto agli episodi letti dai relay (default 200)
  FEED_RELAY_TIMEOUT_S     timeout per relay (default 6)
  FEED_HEAD_TIMEOUT_S      timeout della HEAD sugli enclosure (default 5)
  FEED_INDEXER_RELAYS      relay indicizzatori per la NIP-65 (default purplepag.es, user.kindpag.es)
  FEED_FALLBACK_RELAYS     relay di ripiego (default damus, nos.lol, primal)
  FEED_VERIFY_SIGNATURES   0 per saltare la verifica BIP-340 (default 1: verificare)
  FEED_RATE_LIMIT          richieste per finestra e per IP (default 60)
  FEED_RATE_WINDOW_S       ampiezza della finestra in secondi (default 60)
"""
from src.domains.feed.repositories.enclosure_store import EnclosureStore
from src.domains.feed.services.feed_service import FeedService


def build_feed_service() -> FeedService:
    return FeedService(EnclosureStore())
