"""CORS per i domini PUBBLICI, gestito nell'app (non in nginx).

Perche' qui e non nel reverse-proxy: la regressione piu' facile da reintrodurre e' un
preflight rotto, e va coperta da un test di contratto che gira contro l'app (pytest
TestClient) — cosa impossibile se il CORS vivesse solo in nginx. Tenendolo qui:
  - il proxy resta CORS-free (nessuna intestazione duplicata, che romperebbe il preflight
    in modo difficile da diagnosticare);
  - il preflight e' testabile senza rete/nginx.

E' un middleware ASGI installato **outermost** (BEFORE_EXCEPTION): intercetta l'OPTIONS
prima che il routing di connexion risponda 405, e aggiunge gli header anche alle risposte
d'errore. Si applica **solo** ai path dei domini pubblici passati in `public_prefixes`,
quindi `source` (interno) non riceve mai CORS.

Config via env:
  CORS_ALLOW_ORIGINS  elenco di origini separate da virgola (es.
                      "https://app.example.com,http://localhost:5173").
                      Assente/vuoto -> CORS disabilitato (nessun header).
  CORS_MAX_AGE        secondi di cache del preflight (default 600).

Le origini vengono **riecheggiate** una a una (mai `*`): con l'auth via header X-API-Key
un wildcard sarebbe inappropriato.
"""
import os
from typing import Iterable

_ALLOW_HEADERS = "content-type, x-api-key"
_ALLOW_METHODS = "GET, POST, OPTIONS"
_DEFAULT_MAX_AGE = "600"


def allowed_origins_from_env() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _origin(scope) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == b"origin":
            return value.decode("latin-1")
    return None


class CorsMiddleware:
    """Middleware ASGI: preflight 204 + header CORS sui soli path pubblici."""

    def __init__(
        self,
        app,
        *,
        allow_origins: Iterable[str],
        public_prefixes: Iterable[str],
        max_age: str = _DEFAULT_MAX_AGE,
    ) -> None:
        self.app = app
        self.allow_origins = set(allow_origins)
        self.public_prefixes = tuple(public_prefixes)
        self.max_age = str(max_age)

    def _is_public(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self.public_prefixes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self._is_public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        origin = _origin(scope)
        allowed = origin is not None and origin in self.allow_origins

        if scope.get("method") == "OPTIONS":
            headers = [
                (b"access-control-allow-methods", _ALLOW_METHODS.encode()),
                (b"access-control-allow-headers", _ALLOW_HEADERS.encode()),
                (b"access-control-max-age", self.max_age.encode()),
                (b"vary", b"Origin"),
            ]
            if allowed:
                headers.insert(0, (b"access-control-allow-origin", origin.encode("latin-1")))
            await send({"type": "http.response.start", "status": 204, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start" and allowed:
                message.setdefault("headers", []).extend(
                    [
                        (b"access-control-allow-origin", origin.encode("latin-1")),
                        (b"vary", b"Origin"),
                    ]
                )
            await send(message)

        await self.app(scope, receive, send_with_cors)


def install_cors(app, public_domains: Iterable[str], allow_origins: Iterable[str]) -> bool:
    """Installa il middleware CORS sull'app connexion per i domini pubblici indicati.

    No-op (ritorna False) se non ci sono origini configurate o nessun dominio pubblico:
    cosi' i container interni (es. source) e gli ambienti senza CORS_ALLOW_ORIGINS non
    espongono alcun header CORS.
    """
    allow_origins = list(allow_origins)
    prefixes = [f"/v0/{d}" for d in public_domains]
    if not allow_origins or not prefixes:
        return False

    from connexion.middleware import MiddlewarePosition

    app.add_middleware(
        CorsMiddleware,
        position=MiddlewarePosition.BEFORE_EXCEPTION,
        allow_origins=allow_origins,
        public_prefixes=prefixes,
        max_age=os.environ.get("CORS_MAX_AGE", _DEFAULT_MAX_AGE),
    )
    return True
