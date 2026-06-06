"""Unit test del dominio media come BFF: delega al gateway (fittizio) e ri-mappa gli URL."""
from src.domains.media.controllers.health_controller import get_health
from src.domains.media.gateway import ContentResult, UploadResult
from src.domains.media.services.media_service import MediaService


def _src_item(i: int, title: str = "P") -> dict:
    # item come lo restituisce source: URL col prefisso interno /v0/source
    return {
        "id": i,
        "title": title,
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

    def get_content(self, media_id, *, download):
        if media_id == 1:  # dev: source relaia i byte
            disp = ("attachment" if download else "inline") + "; filename=p.m4a"
            return ContentResult(
                body=b"BYTES", content_type="application/octet-stream", content_disposition=disp
            )
        if media_id == 2:  # coll/prod: source risponde 302
            return ContentResult(redirect_url="https://storage/presigned")
        return None

    def upload_media(self, **kw):
        return UploadResult(201, _src_item(9, title=kw["title"]))


def _svc() -> MediaService:
    return MediaService(_FakeGateway())


def test_health_returns_ok():
    body, status = get_health()
    assert status == 200 and body["status"] == "ok"


def test_list_remaps_urls_to_media():
    env = _svc().list(media_type="audio/m4a")
    item = env["items"][0]
    assert item["content_url"] == "/v0/media/1/content"            # /v0/source -> /v0/media
    assert item["download_url"] == "/v0/media/1/content?download=1"
    assert env["pagination"]["total"] == 1


def test_get_remaps_and_404():
    assert _svc().get(1)["content_url"] == "/v0/media/1/content"
    assert _svc().get(999) is None


def test_content_relay_dev():
    r = _svc().content(1, download=False)
    assert r.redirect_url is None
    assert r.body == b"BYTES"
    assert "inline" in r.content_disposition


def test_content_redirect_passthrough_prod():
    r = _svc().content(2, download=False)
    assert r.redirect_url == "https://storage/presigned"
    assert r.body is None


def test_content_absent_none():
    assert _svc().content(999, download=False) is None


def test_upload_remaps_url():
    r = _svc().upload(title="N", media_type="audio/m4a", filename="n.m4a", data=b"xy")
    assert r.status_code == 201
    assert r.payload["content_url"] == "/v0/media/9/content"
