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

**Eccezione: i domini "aperti"** (marker `openapi/<dom>/.open`, oggi `feed`). Sono senza
autenticazione e servono contenuto pubblico, quindi rispondono `Access-Control-Allow-Origin: *`
a chiunque, anche quando `CORS_ALLOW_ORIGINS` e' vuoto. Un wildcard e' appropriato solo dove
non c'e' nulla da proteggere e nessuna credenziale in gioco: non estenderlo agli altri domini.
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
        open_prefixes: Iterable[str] = (),
        max_age: str = _DEFAULT_MAX_AGE,
    ) -> None:
        self.app = app
        self.allow_origins = set(allow_origins)
        self.public_prefixes = tuple(public_prefixes)
        self.open_prefixes = tuple(open_prefixes)
        self.max_age = str(max_age)

    @staticmethod
    def _under(path: str, prefixes) -> bool:
        return any(path == p or path.startswith(p + "/") for p in prefixes)

    def _is_public(self, path: str) -> bool:
        return self._under(path, self.public_prefixes) or self._under(path, self.open_prefixes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self._is_public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        origin = _origin(scope)
        # Dominio aperto: wildcard sempre, anche senza Origin e senza allowlist configurata.
        wildcard = self._under(path, self.open_prefixes)
        allowed = wildcard or (origin is not None and origin in self.allow_origins)
        value = b"*" if wildcard else (origin or "").encode("latin-1")

        if scope.get("method") == "OPTIONS":
            headers = [
                (b"access-control-allow-methods", _ALLOW_METHODS.encode()),
                (b"access-control-allow-headers", _ALLOW_HEADERS.encode()),
                (b"access-control-max-age", self.max_age.encode()),
                (b"vary", b"Origin"),
            ]
            if allowed:
                headers.insert(0, (b"access-control-allow-origin", value))
            await send({"type": "http.response.start", "status": 204, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start" and allowed:
                extra = [(b"access-control-allow-origin", value)]
                if not wildcard:
                    # Vary: Origin serve solo quando la risposta dipende dall'origine.
                    extra.append((b"vary", b"Origin"))
                message.setdefault("headers", []).extend(extra)
            await send(message)

        await self.app(scope, receive, send_with_cors)


def install_cors(app, public_domains: Iterable[str], allow_origins: Iterable[str],
                 open_domains: Iterable[str] = ()) -> bool:
    """Installa il middleware CORS sull'app connexion per i domini pubblici indicati.

    No-op (ritorna False) se non c'e' nulla da servire: nessun dominio aperto **e** (nessuna
    origine configurata o nessun dominio pubblico). Cosi' i container interni (es. source) e
    gli ambienti senza CORS_ALLOW_ORIGINS non espongono alcun header CORS, mentre un dominio
    aperto (feed) funziona anche senza configurazione.
    """
    allow_origins = list(allow_origins)
    open_prefixes = [f"/v0/{d}" for d in open_domains]
    prefixes = [f"/v0/{d}" for d in public_domains if f"/v0/{d}" not in open_prefixes]
    if not open_prefixes and (not allow_origins or not prefixes):
        return False

    from connexion.middleware import MiddlewarePosition

    app.add_middleware(
        CorsMiddleware,
        position=MiddlewarePosition.BEFORE_EXCEPTION,
        allow_origins=allow_origins,
        public_prefixes=prefixes,
        open_prefixes=open_prefixes,
        max_age=os.environ.get("CORS_MAX_AGE", _DEFAULT_MAX_AGE),
    )
    return True
