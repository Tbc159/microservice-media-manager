"""Integration test del dominio content via connexion TestClient.

Verifica la catena routing /v0 -> security -> validazione body (discriminatore `tipo`)
-> controller -> service -> gateway (fake), inclusa la validazione della risposta
(validate_responses=True): GeneratedImage per il 201, Error per 400/501.
"""
import io
import warnings

import pytest
from PIL import Image

from src.domains.content.gateway import UploadResult

warnings.filterwarnings("ignore")

_KEY = {"X-API-Key": "test"}


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (48, 48), (200, 120, 30, 255)).save(buf, "PNG")
    return buf.getvalue()


_LOGO = _png_bytes()


class _FakeGateway:
    def resolve_filename(self, filename):
        return {"id": 50, "filename": filename, "media_type": "image/png"} if filename == "logo.png" else None

    def get_bytes(self, media_id):
        return _LOGO if media_id in (10, 50) else None

    def list_by_type(self, media_type, page_size=100):
        if media_type == "font/ttf":
            return [{"id": 70, "title": "Montserrat Black", "filename": "montserrat-black.ttf",
                     "media_type": "font/ttf", "size_bytes": 100, "created_at_s": 1700000000}]
        return []

    def upload_image(self, *, title, media_type, filename, data):
        return UploadResult(
            201,
            {
                "id": 99, "title": title, "filename": filename, "media_type": media_type,
                "size_bytes": len(data), "created_at_s": 1700000000, "status": "ready",
                "content_url": "/v0/source/media/99/content",
                "download_url": "/v0/source/media/99/content?download=1",
            },
        )


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    from src.app import create_app
    from src.domains.content.services.image_service import ImageService

    app = create_app(domains=["content"])
    import src.domains.content.controllers.content_controller as cc

    cc._service = ImageService(_FakeGateway())
    return app.test_client()


def test_health(client):
    assert client.get("/v0/content/health").json() == {"status": "ok"}


def test_list_fonts(client):
    r = client.get("/v0/content/fonts", headers=_KEY)
    assert r.status_code == 200
    fonts = r.json()
    assert any(f["name"] == "Montserrat Black" and f["media_type"] == "font/ttf" for f in fonts)


def test_list_fonts_requires_key(client):
    assert client.get("/v0/content/fonts").status_code == 401


def test_requires_api_key(client):
    r = client.post("/v0/content/image", json={"tipo": "copertina", "titolo": "B",
                                               "testo_centrale": "c", "logo_host": 10})
    assert r.status_code == 401


def test_generate_copertina_201_and_remap(client):
    r = client.post(
        "/v0/content/image",
        json={"tipo": "copertina", "titolo": "Bitcoin Radio",
              "testo_centrale": "è lieto di ospitare", "logo_host": 10},
        headers=_KEY,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 99 and body["tipo"] == "copertina"
    assert body["media_type"] == "image/png"
    assert body["content_url"] == "/v0/media/99/content"
    assert "/v0/source" not in body["download_url"]


def test_logo_by_filename(client):
    r = client.post(
        "/v0/content/image",
        json={"tipo": "copertina", "titolo": "B", "testo_centrale": "c", "logo_host": "logo.png"},
        headers=_KEY,
    )
    assert r.status_code == 201


def test_missing_logo_is_400(client):
    r = client.post(
        "/v0/content/image",
        json={"tipo": "copertina", "titolo": "B", "testo_centrale": "c", "logo_host": 404},
        headers=_KEY,
    )
    assert r.status_code == 400


def test_generate_composita_201(client):
    # solo colore + testo: nessun asset da risolvere -> robusto e deterministico
    r = client.post(
        "/v0/content/image",
        json={
            "tipo": "composita",
            "layers": [
                {"type": "background", "fallback_color": "#222222"},
                {"type": "text", "content": "CIAO", "x": "center", "y": "center", "font_size": 100},
            ],
        },
        headers=_KEY,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["tipo"] == "composita"
    assert body["content_url"] == "/v0/media/99/content"
    assert isinstance(body["warnings"], list)


def test_composita_invalid_layer_type_400(client):
    r = client.post(
        "/v0/content/image",
        json={"tipo": "composita", "layers": [{"type": "banana"}]},
        headers=_KEY,
    )
    assert r.status_code == 400


def test_social_is_501(client):
    r = client.post(
        "/v0/content/image",
        json={"tipo": "social", "logo_top": 10, "logo_bottom": 10},
        headers=_KEY,
    )
    assert r.status_code == 501


def test_missing_required_field_is_422_or_400(client):
    # manca testo_centrale (required nello schema copertina) -> validazione body fallisce
    r = client.post(
        "/v0/content/image",
        json={"tipo": "copertina", "titolo": "B", "logo_host": 10},
        headers=_KEY,
    )
    assert r.status_code in (400, 422)
