"""Integration test del dominio source via connexion TestClient.

Esercita l'intera catena: routing /v0, security ApiKey, controller -> service ->
repo(mock) -> storage(local), e soprattutto validate_responses=True (il payload
deve conformare allo schema OAS). Repo mock + storage local: nessun DB ne' MinIO.
"""
import warnings

import pytest

warnings.filterwarnings("ignore")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # Determinismo: nessuna API_KEY attesa -> qualunque chiave non vuota e' accettata;
    # backend mock+local (niente DB/MinIO) a prescindere dall'ambiente del runner.
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("SOURCE_DB_PATH", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("SOURCE_MEDIA_DIR", str(tmp_path))  # upload locale su dir temporanea
    from src.app import create_app

    app = create_app(domains=["source"])
    # Stato isolato per test: repository mock fresco (il controller usa un singleton di modulo).
    import src.domains.source.controllers.source_controller as sc
    from src.domains.source.factory import build_source_service

    sc._service = build_source_service()
    return app.test_client()


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
    assert item["content_url"] == f"/v0/source/media/{item['id']}/content"
    assert item["download_url"] == f"/v0/source/media/{item['id']}/content?download=1"
    assert "stream_url" not in item
    assert "object_key" not in item  # dettaglio interno mai esposto


def test_get_single_item(client):
    r = client.get("/v0/source/media/1", headers=_KEY)
    assert r.status_code == 200
    assert r.json()["id"] == 1
    assert client.get("/v0/source/media/99999", headers=_KEY).status_code == 404
    assert client.get("/v0/source/media/1").status_code == 401  # senza chiave


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


def test_list_all_without_type(client):
    # type omesso -> tutto l'archivio (non piu' 400 "type mancante")
    r = client.get("/v0/source/media", headers=_KEY)
    assert r.status_code == 200
    body = r.json()
    assert body["pagination"]["total"] == 3          # 2 m4a + 1 mpeg (seed)
    assert {"audio/m4a", "audio/mpeg"} <= {i["media_type"] for i in body["items"]}


def test_mp3_alias_query_normalized(client):
    # filtrare per l'alias legacy audio/mp3 restituisce i record audio/mpeg
    r = client.get("/v0/source/media?type=audio/mp3", headers=_KEY)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and all(i["media_type"] == "audio/mpeg" for i in items)


# --- POST /v0/source/media (upload server-side multipart) ---


def _upload(client, *, filename="nuova.m4a", content=b"AUDIO", title="Nuova",
            media_type="audio/m4a", extra=None, headers=_KEY):
    data = {"title": title, "media_type": media_type}
    if extra:
        data.update(extra)
    return client.post(
        "/v0/source/media",
        files={"file": (filename, content, media_type)},
        data=data,
        headers=headers or {},
    )


def test_upload_returns_201_with_record(client):
    r = _upload(client, content=b"AUDIO", title="Nuova", extra={"duration_s": "55"})
    assert r.status_code == 201
    b = r.json()
    assert b["title"] == "Nuova"
    assert b["filename"] == "nuova.m4a"
    assert b["size_bytes"] == 5
    assert b["duration_s"] == 55
    assert b["status"] == "ready"
    assert b["content_url"] == f"/v0/source/media/{b['id']}/content"
    assert "object_key" not in b


def test_upload_then_appears_in_listing(client):
    _upload(client, filename="extra.m4a", title="Extra")
    r = client.get("/v0/source/media?type=audio/m4a", headers=_KEY)
    assert r.json()["pagination"]["total"] == 3  # 2 seed + 1 caricato


def test_upload_duplicate_returns_409(client):
    assert _upload(client, filename="dup.m4a").status_code == 201
    assert _upload(client, filename="dup.m4a", title="Altro").status_code == 409


def test_upload_missing_title_rejected(client):
    r = client.post(
        "/v0/source/media",
        files={"file": ("x.m4a", b"x", "audio/m4a")},
        data={"media_type": "audio/m4a"},
        headers=_KEY,
    )
    assert r.status_code == 400


def test_upload_requires_api_key(client):
    r = _upload(client, headers=None)
    assert r.status_code == 401


# --- POST /v0/source/media/from-url (upload interno via URL) ---


def test_upload_from_url_201(client, monkeypatch):
    import src.domains.source.controllers.source_controller as sc

    monkeypatch.setattr(sc, "download_asset", lambda url, **kw: b"FONTBYTES")
    r = client.post(
        "/v0/source/media/from-url",
        json={"url": "https://x/MioFont.ttf", "title": "Mio Font", "media_type": "font/ttf"},
        headers=_KEY,
    )
    assert r.status_code == 201
    b = r.json()
    assert b["filename"] == "MioFont.ttf"          # dedotto dall'URL
    assert b["media_type"] == "font/ttf"
    assert "object_key" not in b


def test_upload_from_url_requires_api_key(client):
    r = client.post(
        "/v0/source/media/from-url",
        json={"url": "https://x/f.ttf", "title": "T", "media_type": "font/ttf"},
    )
    assert r.status_code == 401


def test_upload_from_url_invalid_media_type_400(client, monkeypatch):
    import src.domains.source.controllers.source_controller as sc

    monkeypatch.setattr(sc, "download_asset", lambda url, **kw: b"x")
    r = client.post(
        "/v0/source/media/from-url",
        json={"url": "https://x/f.bin", "title": "T", "media_type": "application/pdf"},
        headers=_KEY,
    )
    assert r.status_code == 400


# --- GET /v0/source/media/by-filename/{name} (risoluzione tollerante) ---


def test_resolve_by_name_tolerant(client):
    _upload(client, filename="Montserrat-Bold.ttf", title="Mont",
            media_type="font/ttf", content=b"FONT")
    # normalizzato: senza estensione + case-insensitive
    r = client.get("/v0/source/media/by-filename/montserrat-bold", headers=_KEY)
    assert r.status_code == 200 and r.json()["filename"] == "Montserrat-Bold.ttf"
    # match esatto continua a funzionare
    assert client.get(
        "/v0/source/media/by-filename/Montserrat-Bold.ttf", headers=_KEY
    ).status_code == 200
    # inesistente -> 404
    assert client.get("/v0/source/media/by-filename/arial", headers=_KEY).status_code == 404


# --- GET /v0/source/media/{id}/content (play inline / download) ---


def test_content_inline_by_default(client):
    mid = _upload(client, filename="play.m4a", content=b"PLAY-ME-123").json()["id"]
    r = client.get(f"/v0/source/media/{mid}/content", headers=_KEY)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert "inline" in r.headers["content-disposition"]
    assert r.content == b"PLAY-ME-123"           # integrita' byte


def test_content_download_attachment(client):
    mid = _upload(client, filename="save.m4a", content=b"SAVE-ME").json()["id"]
    for value in ("1", "true", "yes"):           # il param accetta piu' valori veri
        r = client.get(f"/v0/source/media/{mid}/content?download={value}", headers=_KEY)
        assert r.status_code == 200
        assert "attachment" in r.headers["content-disposition"]
        assert "save.m4a" in r.headers["content-disposition"]


def test_content_supports_range(client):
    mid = _upload(client, filename="range.m4a", content=b"0123456789").json()["id"]
    r = client.get(f"/v0/source/media/{mid}/content", headers={**_KEY, "Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.content == b"0123"


def test_content_absent_id_returns_404(client):
    assert client.get("/v0/source/media/99999/content", headers=_KEY).status_code == 404


def test_content_record_without_bytes_returns_404(client):
    # I record seed (es. id=1) non hanno file su storage -> 404
    assert client.get("/v0/source/media/1/content", headers=_KEY).status_code == 404


def test_content_requires_api_key(client):
    assert client.get("/v0/source/media/1/content").status_code == 401
