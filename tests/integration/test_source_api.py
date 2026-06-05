"""Integration test del dominio source via connexion TestClient.

Esercita l'intera catena: routing /v0, security ApiKey, controller -> service ->
repo(mock) -> storage(local), e soprattutto validate_responses=True (il payload
deve conformare allo schema OAS). Repo mock + storage local: nessun DB ne' MinIO.
"""
import warnings

import pytest

warnings.filterwarnings("ignore")


@pytest.fixture()
def client(monkeypatch):
    # Determinismo: nessuna API_KEY attesa -> qualunque chiave non vuota e' accettata;
    # backend mock+local (niente DB/MinIO) a prescindere dall'ambiente del runner.
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("SOURCE_DB_PATH", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    from src.app import create_app

    return create_app(domains=["source"]).test_client()


_KEY = {"X-API-Key": "test"}


def test_health(client):
    r = client.get("/v0/source/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_listing_requires_api_key(client):
    r = client.get("/v0/source/media?type=audio/m4a")
    assert r.status_code == 401


def test_listing_returns_valid_envelope(client):
    r = client.get("/v0/source/media?type=audio/m4a", headers=_KEY)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "pagination"}
    assert body["pagination"]["total"] == 2
    assert body["items"]


def test_item_contract(client):
    r = client.get("/v0/source/media?type=audio/m4a", headers=_KEY)
    item = r.json()["items"][0]
    assert {"id", "title", "filename", "media_type", "created_at_s", "status"} <= item.keys()
    assert "stream_url" in item and item["stream_url"] is None  # local backend
    assert "object_key" not in item  # dettaglio interno mai esposto


def test_filter_by_title(client):
    r = client.get(
        "/v0/source/media?type=audio/m4a&title=Puntata%20pilota", headers=_KEY
    )
    assert r.json()["pagination"]["total"] == 1


def test_pagination(client):
    r = client.get("/v0/source/media?type=audio/m4a&page=1&page_size=1", headers=_KEY)
    p = r.json()["pagination"]
    assert p["page_size"] == 1
    assert p["total"] == 2
    assert p["total_pages"] == 2


def test_invalid_type_rejected(client):
    # type fuori enum -> 400 da strict_validation
    r = client.get("/v0/source/media?type=application/pdf", headers=_KEY)
    assert r.status_code == 400
