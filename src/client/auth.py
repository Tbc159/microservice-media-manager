"""Factory unico per i client generati: injection dinamica di api_key/secret.

Multi-dominio: ogni dominio genera il proprio SDK in generated/<dominio>/client
come package `<dominio>_client`. La factory riceve il dominio e importa il
package giusto. Quando arrivera' l'API Gateway, si modifica SOLO questo file.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass


@dataclass
class AuthSettings:
    host: str
    api_key: str | None = None
    api_secret: str | None = None

    @classmethod
    def from_env(cls) -> "AuthSettings":
        return cls(
            host=os.environ["API_HOST"],
            api_key=os.environ.get("API_KEY"),
            api_secret=os.environ.get("API_SECRET"),
        )


def build_api_client(domain: str, settings: "AuthSettings | None" = None):
    """Costruisce l'ApiClient del dominio indicato.

    Richiede che generated/<dominio>/client sia sul PYTHONPATH (lo e' dopo
    `make generate-<dominio>`). Import lazy per non dipendere dal generato
    finche' non serve davvero.
    """
    client_pkg = importlib.import_module(f"{domain}_client")
    Configuration = client_pkg.Configuration
    ApiClient = client_pkg.ApiClient

    settings = settings or AuthSettings.from_env()
    config = Configuration(host=settings.host)
    if settings.api_key:
        config.api_key["ApiKeyAuth"] = settings.api_key
    if settings.api_secret:
        config.api_key["ApiSecretAuth"] = settings.api_secret
    return ApiClient(configuration=config)
