"""Contract test del preflight CORS sui domini PUBBLICI.

E' la regressione piu' facile da reintrodurre e la piu' difficile da notare: `curl` non
vede il preflight, e un client browser fallisce in modo opaco. Qui verifichiamo, contro
l'app (senza nginx), che:
  - OPTIONS su un endpoint pubblico -> 204 con le tre intestazioni CORS;
  - l'app risponde con l'origine configurata (riecheggiata, mai `*`);
  - `source` (interno) NON riceve CORS;
  - senza `CORS_ALLOW_ORIGINS` il CORS e' disattivato.

Il CORS e' nell'app (src/cors.py), non in nginx: per questo e' testabile qui.
"""
import warnings

import pytest

warnings.filterwarnings("ignore")

_ORIGIN = "https://app.example.com"
_ENV = "CORS_ALLOW_ORIGINS"


def _client(monkeypatch, domain, origins=_ORIGIN):
    monkeypatch.setenv(_ENV, origins)
    monkeypatch.delenv("API_KEY", raising=False)
    from src.app import create_app

    return create_app(domains=[domain]).test_client()


# path pubblici rappresentativi: health (no auth) e un endpoint "vero" per dominio
@pytest.mark.parametrize("domain,path", [
    ("media", "/v0/media/health"),
    ("media", "/v0/media"),
    ("content", "/v0/content/health"),
    ("content", "/v0/content/image"),
])
def test_preflight_returns_204_with_cors_headers(monkeypatch, domain, path):
    client = _client(monkeypatch, domain)
    r = client.options(
        path,
        headers={"Origin": _ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 204, f"{path}: atteso 204, ottenuto {r.status_code}"
    # 1) Access-Control-Allow-Origin = origine configurata (non '*')
    assert r.headers.get("access-control-allow-origin") == _ORIGIN
    # 2) Access-Control-Allow-Headers include content-type e x-api-key
    allow_headers = (r.headers.get("access-control-allow-headers") or "").lower()
    assert "content-type" in allow_headers
    assert "x-api-key" in allow_headers
    # 3) Access-Control-Allow-Methods include GET, POST, OPTIONS
    allow_methods = (r.headers.get("access-control-allow-methods") or "").upper()
    for m in ("GET", "POST", "OPTIONS"):
        assert m in allow_methods, f"metodo {m} assente in {allow_methods}"
    # Max-Age ragionevole
    assert int(r.headers.get("access-control-max-age", "0")) > 0


def test_actual_response_carries_allow_origin(monkeypatch):
    client = _client(monkeypatch, "media")
    r = client.get("/v0/media/health", headers={"Origin": _ORIGIN})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == _ORIGIN
    assert "origin" in (r.headers.get("vary") or "").lower()


def test_unlisted_origin_gets_no_cors(monkeypatch):
    client = _client(monkeypatch, "content")
    r = client.options("/v0/content/image", headers={"Origin": "https://evil.example.com"})
    assert r.headers.get("access-control-allow-origin") is None


def test_source_is_not_cors_enabled(monkeypatch):
    # dominio interno: nessun header CORS, a prescindere dall'origine
    client = _client(monkeypatch, "source")
    r = client.options("/v0/source/media", headers={"Origin": _ORIGIN})
    assert r.headers.get("access-control-allow-origin") is None
    r = client.get("/v0/source/health", headers={"Origin": _ORIGIN})
    assert r.headers.get("access-control-allow-origin") is None


def test_cors_disabled_without_env(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    from src.app import create_app

    client = create_app(domains=["media"]).test_client()
    r = client.options("/v0/media/health", headers={"Origin": _ORIGIN})
    assert r.headers.get("access-control-allow-origin") is None
