"""Wiring multi-dominio.

Ogni dominio = una spec OAS in openapi/<dominio>/api.yaml, montata sotto
base_path=/<dominio>. Le operationId risolvono verso i controller custom in
src/domains/<dominio>/controllers, NON verso gli stub generati.

Due modalita':
  - locale (sviluppo veloce): nessuna env var -> monta TUTTI i domini in un
    unico processo (`python -m src.app`), utile per mock e test rapidi.
  - container (dev/coll/prod): DOMAIN=<dominio> -> monta SOLO quel dominio,
    cosi' ogni container serve un solo microservizio. Il reverse-proxy instrada
    host/v0/<dominio>/* -> container (base_path /v0).

Variabili d'ambiente:
  DOMAIN  un solo dominio da montare (default: tutti quelli scoperti)
  MOCK=1  risposte dagli examples dell'OAS (MockResolver, niente controller)
  PORT    porta di ascolto (default 8080)
"""
import os
from pathlib import Path

import connexion

OPENAPI_DIR = Path(__file__).resolve().parent.parent / "openapi"


def discover_domains():
    """Un dominio per ogni openapi/<dominio>/api.yaml. Zero hardcoding:
    aggiungere openapi/social/api.yaml basta a creare il dominio 'social'."""
    return sorted(p.parent.name for p in OPENAPI_DIR.glob("*/api.yaml"))


def create_app(domains=None, mock=False):
    domains = domains if domains is not None else discover_domains()
    app = connexion.FlaskApp(__name__, specification_dir=str(OPENAPI_DIR))
    app.app.url_map.strict_slashes = False
    for domain in domains:
        resolver = (
            connexion.resolver.MockResolver(mock_all=True)
            if mock
            else connexion.resolver.RelativeResolver(f"src.domains.{domain}.controllers")
        )
        app.add_api(
            f"{domain}/api.yaml",
            base_path="/v0",
            resolver=resolver,
            strict_validation=True,
            validate_responses=True,
        )
    return app


def _selected_domains():
    """DOMAIN=media -> [media] (un solo microservizio nel container).
    Assente -> None -> tutti i domini (sviluppo locale)."""
    only = os.environ.get("DOMAIN")
    return [only] if only else None


app = create_app(domains=_selected_domains(), mock=os.environ.get("MOCK") == "1")

if __name__ == "__main__":
    # Dev server. In produzione usare un ASGI server (es. uvicorn/gunicorn).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
