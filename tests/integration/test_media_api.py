"""Integration test del dominio media (BFF) via connexion TestClient.

Il gateway verso source e' sostituito da un fake (niente HTTP reale): si verifica la
catena routing /v0 -> security -> controller -> service -> gateway, incluso il
re-mapping URL, il passthrough del 302 (coll/prod) e il relay dei byte (dev).
"""
import warnings

import pytest

from src.domains.media.gateway import ContentResult, UploadResult

warnings.filterwarnings("ignore")

_KEY = {"X-API-Key": "test"}


def _src_item(i: int) -> dict:
    return {
        "id": i,
        "title": "P",
        "filename": "p.m4a",
        "media_type": "audio/m4a",
        "size_bytes": 5,
        "duration_s": None,
        "created_at_s": 1,
        "status": "ready",
        "content_url": f"/v0/source/media/{i}/content",
        "download_url": f"/v0/source/media/{i}/content?download=1",
        "metadata": {},
    }


class _FakeGateway:
    def list_media(self, *, media_type, title=None, page=1, page_size=20):
        return {
            "items": [_src_item(1)],
            "pagination": {"page": page, "page_size": page_size, "total": 1, "total_pages": 1},
        }

    def get_media(self, media_id):
        return _src_item(media_id) if media_id == 1 else None

    def get_content(self, media_id, *, download, range_header=None, head=False):
        if media_id == 1:
            if range_header:
                return ContentResult(
                    body=b"BY", status_code=206, content_type="application/octet-stream",
                    content_range="bytes 0-1/5", accept_ranges="bytes",
                )
            disp = ("attachment" if download else "inline") + "; filename=p.m4a"
            return ContentResult(
                body=(b"" if head else b"BYTES"), content_type="application/octet-stream",
                content_disposition=disp, accept_ranges="bytes",
            )
        if media_id == 2:
            return ContentResult(redirect_url="https://storage/presigned?sig=x")
        return None

    def upload_media(self, **kw):
        return UploadResult(201, _src_item(9))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    from src.app import create_app
    from src.domains.media.services.media_service import MediaService

    app = create_app(domains=["media"])
    import src.domains.media.controllers.media_controller as mc

    mc._service = MediaService(_FakeGateway())
    return app.test_client()


def test_health(client):
    assert client.get("/v0/media/health").json() == {"status": "ok"}


def test_list_requires_key_and_remaps(client):
    assert client.get("/v0/media?type=audio/m4a").status_code == 401
    item = client.get("/v0/media?type=audio/m4a", headers=_KEY).json()["items"][0]
    assert item["content_url"] == "/v0/media/1/content"
    assert "/v0/source" not in item["download_url"]


def test_get_single_and_404(client):
    assert client.get("/v0/media/1", headers=_KEY).json()["content_url"] == "/v0/media/1/content"
    assert client.get("/v0/media/999", headers=_KEY).status_code == 404


def test_content_relay_dev(client):
    r = client.get("/v0/media/1/content", headers=_KEY)
    assert r.status_code == 200
    assert "inline" in r.headers["content-disposition"]
    assert r.headers["accept-ranges"] == "bytes"      # i player sanno di poter seekare
    assert r.content == b"BYTES"


def test_content_range_relays_206(client):
    # Range propagato a source -> 206 parziale (necessario per i .m4a non-faststart)
    r = client.get("/v0/media/1/content", headers={**_KEY, "Range": "bytes=0-1"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 0-1/5"
    assert r.content == b"BY"


def test_content_download_attachment(client):
    r = client.get("/v0/media/1/content?download=true", headers=_KEY)
    assert "attachment" in r.headers["content-disposition"]


def test_content_redirect_passthrough(client):
    r = client.get("/v0/media/2/content", headers=_KEY, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://storage/presigned?sig=x"


def test_content_absent_404(client):
    assert client.get("/v0/media/999/content", headers=_KEY).status_code == 404


def test_upload_delegated(client):
    r = client.post(
        "/v0/media",
        files={"file": ("n.m4a", b"XY", "audio/m4a")},
        data={"title": "N", "media_type": "audio/m4a"},
        headers=_KEY,
    )
    assert r.status_code == 201
    assert r.json()["content_url"] == "/v0/media/9/content"
