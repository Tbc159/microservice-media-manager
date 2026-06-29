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
from src.domains.content.services import copertina_renderer, layer_compositor
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
    raw, warnings = copertina_renderer.render_copertina(
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
    assert isinstance(warnings, list)


def test_renderer_gradient_background():
    raw, _ = copertina_renderer.render_copertina(
        titolo="X", testo_centrale="Y",
        colore_sfondo="#000000", tipo_sfondo="sfumato-up", colore_sfumato="#ffffff",
        logo_bytes=_LOGO, ospiti_bytes=[], formato="image/png",
    )
    assert Image.open(io.BytesIO(raw)).size == (2560, 1440)


def test_renderer_invalid_custom_font_warns():
    # byte che non sono un font -> fallback + warning per quel ruolo, immagine valida
    raw, warnings = copertina_renderer.render_copertina(
        titolo="X", testo_centrale="Y", colore_sfondo="#000000", tipo_sfondo="unicolor",
        colore_sfumato=None, logo_bytes=_LOGO, ospiti_bytes=[], formato="image/png",
        font_titolo_bytes=b"not-a-font",
    )
    assert Image.open(io.BytesIO(raw)).size == (2560, 1440)
    assert any("titolo" in w for w in warnings)


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
    assert isinstance(item["warnings"], list)


def test_font_not_found_emits_warning_and_201():
    # font richiesto per id inesistente -> warning + immagine comunque salvata (201 soft)
    item = _svc().generate(
        {"tipo": "copertina", "titolo": "B", "testo_centrale": "c",
         "logo_host": 10, "font_titolo": 999}
    )
    assert item["id"] == 99
    assert any("999" in w for w in item["warnings"])


def test_font_by_filename_resolved_but_invalid_bytes_warns_from_renderer():
    # font_titolo='logo.png' risolve (id 50) ma i byte non sono un font -> warning del renderer,
    # non un 'non trovato' del service
    item = _svc().generate(
        {"tipo": "copertina", "titolo": "B", "testo_centrale": "c",
         "logo_host": 10, "font_titolo": "logo.png"}
    )
    assert any("titolo" in w for w in item["warnings"])
    assert not any("non trovato" in w and "logo.png" in w for w in item["warnings"])


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


# ── composita: compositor (Pillow puro) ────────────────────────────────────────

def test_resolve_axis_keyword_percent_pixel():
    ra = layer_compositor._resolve_axis
    X = layer_compositor._X_KEYWORDS
    assert ra("left", 100, 1000, X) == 0
    assert ra("right", 100, 1000, X) == 900
    assert ra("center", 100, 1000, X) == 450
    assert ra("50%", 100, 1000, X) == 450
    assert ra("100px", 100, 1000, X) == 100
    assert ra("250", 100, 1000, X) == 250
    assert ra(None, 100, 1000, X) == 450          # default center


def test_resolve_size_preserves_aspect():
    rs = layer_compositor._resolve_size
    assert rs({"width": "50%"}, (200, 100)) == (960, 480)   # 50% di 1920, h in proporzione
    assert rs({"height": "100%"}, (200, 100)) == (2160, 1080)
    # nessuna dimensione + immagine enorme -> clamp nella canvas, mai upscale
    w, h = rs(None, (4000, 4000))
    assert (w, h) == (1080, 1080)


def test_compositor_color_background_and_text():
    raw, warnings = layer_compositor.render_composita([
        {"type": "background", "fallback_color": "#ff0000", "image_bytes": None},
        {"type": "text", "content": "HELLO", "x": "center", "y": "center",
         "font_size": 90, "color": "#ffffff"},
    ])
    img = Image.open(io.BytesIO(raw))
    assert img.size == (1920, 1080)
    assert isinstance(warnings, list)


def test_compositor_full_stack():
    raw, _ = layer_compositor.render_composita([
        {"type": "background", "image_bytes": _LOGO, "fit": "cover"},
        {"type": "person", "image_bytes": _AVATAR, "x": "right", "y": "bottom",
         "size": {"height": "50%"}},
        {"type": "image", "image_bytes": _LOGO, "x": "10%", "y": "top",
         "size": {"width": "120px"}, "opacity": 0.8},
        {"type": "text", "content": "RASSEGNA\nSTAMPA", "x": "left", "y": "12%",
         "font_size": 130, "color": "#ff751f", "stroke": {"width": 6, "color": "#000000"}},
        {"type": "text", "content": "BOX", "x": "70%", "y": "60%", "font_size": 48,
         "color": "#000000", "box": {"color": "#ffd200", "radius": 18, "padding": 16}},
    ], formato="image/jpeg")
    img = Image.open(io.BytesIO(raw))
    assert img.format == "JPEG"
    assert img.size == (1920, 1080)


# ── composita: service ──────────────────────────────────────────────────────────

def test_composita_service_ok():
    gw = _FakeGateway()
    item = ImageService(gw).generate({
        "tipo": "composita",
        "layers": [
            {"type": "background", "media": 10, "fit": "cover"},
            {"type": "person", "media": 21, "x": "right", "y": "bottom",
             "size": {"height": "80%"}},
            {"type": "text", "content": "TITLE", "x": "left", "y": "top", "font_size": 120},
        ],
    })
    assert item["id"] == 99 and item["tipo"] == "composita"
    assert item["content_url"] == "/v0/media/99/content"
    assert gw.uploaded[0]["media_type"] == "image/png"
    assert gw.uploaded[0]["filename"].startswith("composita-")


def test_composita_missing_person_skipped_with_warning():
    item = _svc().generate({
        "tipo": "composita",
        "layers": [
            {"type": "background", "fallback_color": "#000000"},
            {"type": "person", "media": 404},                 # assente, non required -> skip
        ],
    })
    assert item["id"] == 99
    assert any("404" in w for w in item["warnings"])


def test_composita_missing_required_person_raises():
    with pytest.raises(AssetNotFound):
        _svc().generate({
            "tipo": "composita",
            "layers": [
                {"type": "background", "fallback_color": "#000000"},
                {"type": "person", "media": 404, "required": True},
            ],
        })


def test_composita_missing_background_falls_back_with_warning():
    item = _svc().generate({
        "tipo": "composita",
        "layers": [{"type": "background", "media": 404}],
    })
    assert item["id"] == 99
    assert any("sfondo" in w and "404" in w for w in item["warnings"])
