"""Unit test del dominio `content`: renderer Pillow + orchestrazione su gateway fittizio.

Il renderer gira col fallback font (i Montserrat non sono versionati): verifichiamo che
produca immagini valide nei formati supportati. Il service risolve i MediaRef (id o nome
file), gestisce asset mancanti e dispatcha sul `tipo`.
"""
import io

import pytest
from PIL import Image

from src.domains.content.errors import AssetNotFound, TipoNonImplementato
from src.domains.content.gateway import UploadResult
from src.domains.content.services import copertina_renderer
from src.domains.content.services.image_service import ImageService


def _png_bytes(color=(10, 20, 30, 255), size=(48, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


_LOGO = _png_bytes((200, 120, 30, 255))
_AVATAR = _png_bytes((30, 120, 200, 255))


class _FakeGateway:
    """Mappa: id 10 = logo, id 21 = ospite presente, id 22 = ospite assente (None).
    Nome file 'logo.png' -> record id 50; upload -> id 99."""

    def __init__(self):
        self.uploaded = []

    def resolve_filename(self, filename):
        if filename == "logo.png":
            return {"id": 50, "filename": "logo.png", "media_type": "image/png"}
        return None

    def get_bytes(self, media_id):
        return {10: _LOGO, 50: _LOGO, 21: _AVATAR}.get(media_id)  # 22 -> None

    def upload_image(self, *, title, media_type, filename, data):
        self.uploaded.append(
            {"title": title, "media_type": media_type, "filename": filename, "size": len(data)}
        )
        return UploadResult(
            201,
            {
                "id": 99,
                "title": title,
                "filename": filename,
                "media_type": media_type,
                "size_bytes": len(data),
                "created_at_s": 1700000000,
                "status": "ready",
                "content_url": "/v0/source/media/99/content",
                "download_url": "/v0/source/media/99/content?download=1",
            },
        )


def _svc():
    return ImageService(_FakeGateway())


# ── Renderer (Pillow puro, fallback font) ──────────────────────────────────────

@pytest.mark.parametrize("formato,expected", [
    ("image/png", "PNG"),
    ("image/jpeg", "JPEG"),
    ("image/webp", "WEBP"),
])
def test_renderer_produces_valid_image(formato, expected):
    raw = copertina_renderer.render_copertina(
        titolo="Bitcoin Radio",
        testo_centrale="è lieto di ospitare",
        colore_sfondo="#ff751f",
        tipo_sfondo="unicolor",
        colore_sfumato=None,
        logo_bytes=_LOGO,
        ospiti_bytes=[_AVATAR, None],  # uno presente, uno placeholder
        formato=formato,
    )
    img = Image.open(io.BytesIO(raw))
    assert img.format == expected
    assert img.size == (2560, 1440)


def test_renderer_gradient_background():
    raw = copertina_renderer.render_copertina(
        titolo="X", testo_centrale="Y",
        colore_sfondo="#000000", tipo_sfondo="sfumato-up", colore_sfumato="#ffffff",
        logo_bytes=_LOGO, ospiti_bytes=[], formato="image/png",
    )
    assert Image.open(io.BytesIO(raw)).size == (2560, 1440)


def test_ext_for():
    assert copertina_renderer.ext_for("image/png") == "png"
    assert copertina_renderer.ext_for("image/jpeg") == "jpg"
    assert copertina_renderer.ext_for("image/webp") == "webp"


# ── Service (orchestrazione) ───────────────────────────────────────────────────

def test_copertina_by_id_ok_and_remaps_url():
    gw = _FakeGateway()
    item = ImageService(gw).generate(
        {"tipo": "copertina", "titolo": "Brand", "testo_centrale": "ciao", "logo_host": 10}
    )
    assert item["id"] == 99 and item["tipo"] == "copertina"
    assert item["media_type"] == "image/png"
    assert item["content_url"] == "/v0/media/99/content"           # /v0/source -> /v0/media
    assert item["download_url"] == "/v0/media/99/content?download=1"
    assert gw.uploaded[0]["media_type"] == "image/png"
    assert gw.uploaded[0]["filename"].startswith("copertina-")


def test_copertina_format_webp_propagated():
    gw = _FakeGateway()
    item = ImageService(gw).generate(
        {"tipo": "copertina", "titolo": "B", "testo_centrale": "c",
         "logo_host": 10, "formato": "image/webp"}
    )
    assert item["media_type"] == "image/webp"
    assert gw.uploaded[0]["filename"].endswith(".webp")


def test_logo_by_filename_is_resolved():
    item = _svc().generate(
        {"tipo": "copertina", "titolo": "B", "testo_centrale": "c", "logo_host": "logo.png"}
    )
    assert item["id"] == 99


def test_missing_logo_raises_assetnotfound():
    with pytest.raises(AssetNotFound):
        _svc().generate(
            {"tipo": "copertina", "titolo": "B", "testo_centrale": "c", "logo_host": 404}
        )


def test_missing_ospite_uses_placeholder_and_succeeds():
    # ospite id 22 -> get_bytes None -> placeholder, NON un errore
    item = _svc().generate(
        {"tipo": "copertina", "titolo": "B", "testo_centrale": "c",
         "logo_host": 10, "ospiti": [21, 22]}
    )
    assert item["id"] == 99


def test_social_not_implemented():
    with pytest.raises(TipoNonImplementato):
        _svc().generate({"tipo": "social", "logo_top": 10, "logo_bottom": 21})


# ── Controller (mappatura HTTP) ────────────────────────────────────────────────

def test_controller_maps_status_codes(monkeypatch):
    from src.domains.content.controllers import content_controller

    monkeypatch.setattr(content_controller, "_service", _svc())

    ok, status = content_controller.generate_image(
        {"tipo": "copertina", "titolo": "B", "testo_centrale": "c", "logo_host": 10}
    )
    assert status == 201 and ok["content_url"] == "/v0/media/99/content"

    _, status = content_controller.generate_image(
        {"tipo": "copertina", "titolo": "B", "testo_centrale": "c", "logo_host": 404}
    )
    assert status == 400

    _, status = content_controller.generate_image(
        {"tipo": "social", "logo_top": 10, "logo_bottom": 21}
    )
    assert status == 501


def test_health():
    from src.domains.content.controllers.health_controller import get_health

    body, status = get_health()
    assert status == 200 and body["status"] == "ok"
