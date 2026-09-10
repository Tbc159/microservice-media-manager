"""Integration test di POST /v0/media/from-url (BFF pubblico).

Il gateway verso source e il fetcher HTTP sono sostituiti: si verifica la catena
routing -> security -> controller -> service (SSRF/tipo/dedup) -> mappatura HTTP, senza
rete reale ne' source vero.
"""
import warnings

import pytest

from src.domains.media import fetcher
from src.domains.media.gateway import UploadResult

warnings.filterwarnings("ignore")

_KEY = {"X-API-Key": "test"}


def _src_item(i: int, filename: str, media_type: str) -> dict:
    return {
        "id": i, "title": "T", "filename": filename, "media_type": media_type,
        "size_bytes": 5, "duration_s": None, "created_at_s": 1, "status": "ready",
        "content_url": f"/v0/source/media/{i}/content",
        "download_url": f"/v0/source/media/{i}/content?download=1",
        "metadata": {},
    }


class _FakeGateway:
    def upload_media(self, *, title, media_type, filename, data, duration_s=None):
        if filename == "dup.png":                       # simula object_key duplicato su source
            return UploadResult(409, {"detail": f"media gia' presente: {media_type}/{filename}"})
        return UploadResult(201, _src_item(9, filename, media_type))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    from src.app import create_app
    from src.domains.media.services.media_service import MediaService

    app = create_app(domains=["media"])
    import src.domains.media.controllers.media_controller as mc

    mc._service = MediaService(_FakeGateway())
    return app.test_client()


def _stub_fetch(monkeypatch, *, data=b"BYTES", content_type="image/png"):
    monkeypatch.setattr(fetcher, "assert_public_url", lambda url: None)
    monkeypatch.setattr(fetcher, "fetch", lambda url, **kw: (data, content_type))


def test_requires_api_key(client):
    r = client.post("/v0/media/from-url", json={"url": "https://cdn.example/a.png", "title": "T"})
    assert r.status_code == 401


# 1) URL valido -> 201 con URL ri-mappati su /v0/media
def test_from_url_valid_201(client, monkeypatch):
    _stub_fetch(monkeypatch, content_type="image/png")
    r = client.post(
        "/v0/media/from-url",
        json={"url": "https://cdn.example/pic.png", "title": "Copertina"},
        headers=_KEY,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["media_type"] == "image/png"
    assert body["content_url"] == "/v0/media/9/content"
    assert "/v0/source" not in body["download_url"]


def test_from_url_explicit_media_type_wins(client, monkeypatch):
    # Content-Type generico ma media_type fornito e valido -> usato quello fornito
    _stub_fetch(monkeypatch, content_type="application/octet-stream")
    r = client.post(
        "/v0/media/from-url",
        json={"url": "https://cdn.example/track.m4a", "title": "Ep", "media_type": "audio/m4a"},
        headers=_KEY,
    )
    assert r.status_code == 201
    assert r.json()["media_type"] == "audio/m4a"


# 2) tipo non accettato -> 400 dicendo quale e' stato rilevato (non 500)
def test_from_url_unaccepted_type_400(client, monkeypatch):
    _stub_fetch(monkeypatch, content_type="application/pdf")
    r = client.post(
        "/v0/media/from-url",
        json={"url": "https://cdn.example/doc.pdf", "title": "Doc"},
        headers=_KEY,
    )
    assert r.status_code == 400
    assert "application/pdf" in r.json()["detail"]


# 3) indirizzo su rete privata -> 400 (SSRF), senza toccare la rete
def test_from_url_private_address_400(client):
    r = client.post(
        "/v0/media/from-url",
        json={"url": "http://127.0.0.1/pic.png", "title": "T"},
        headers=_KEY,
    )
    assert r.status_code == 400
    assert "non consentito" in r.json()["detail"].lower()


def test_from_url_link_local_metadata_400(client):
    r = client.post(
        "/v0/media/from-url",
        json={"url": "http://169.254.169.254/latest/meta-data", "title": "T"},
        headers=_KEY,
    )
    assert r.status_code == 400


# 4) file oltre il limite -> 413
def test_from_url_too_large_413(client, monkeypatch):
    monkeypatch.setattr(fetcher, "assert_public_url", lambda url: None)

    def _boom(url, **kw):
        raise fetcher.ContentTooLarge("oltre il limite")

    monkeypatch.setattr(fetcher, "fetch", _boom)
    r = client.post(
        "/v0/media/from-url",
        json={"url": "https://cdn.example/big.mp4", "title": "Big"},
        headers=_KEY,
    )
    assert r.status_code == 413


def test_from_url_fetch_failure_502(client, monkeypatch):
    monkeypatch.setattr(fetcher, "assert_public_url", lambda url: None)

    def _boom(url, **kw):
        raise fetcher.FetchFailed("timeout")

    monkeypatch.setattr(fetcher, "fetch", _boom)
    r = client.post(
        "/v0/media/from-url",
        json={"url": "https://cdn.example/x.png", "title": "X"},
        headers=_KEY,
    )
    assert r.status_code == 502


# 5) duplicato -> 409 (come POST /v0/media)
def test_from_url_duplicate_409(client, monkeypatch):
    _stub_fetch(monkeypatch, content_type="image/png")
    r = client.post(
        "/v0/media/from-url",
        json={"url": "https://cdn.example/dup.png", "title": "Dup"},
        headers=_KEY,
    )
    assert r.status_code == 409
