"""Contract test: i campi obbligatori di MediaItem/SourceMediaItem esistono nel contratto
E vengono davvero restituiti dal servizio.

Motivo: `filename` e `status` sono esattamente il genere di campo che sparisce in una
rifattorizzazione (del DTO o della spec) senza che nessuno se ne accorga finche' un client
non si rompe. Qui verifichiamo le DUE facce insieme:
  1) la spec OAS li dichiara `required`;
  2) la risposta reale del servizio li contiene (non nulli).
Se una delle due regredisce, questo test fallisce.
"""
import warnings
from pathlib import Path

import pytest
import yaml

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
_MUST_INCLUDE = {"id", "title", "filename", "media_type", "created_at_s", "status",
                 "content_url", "download_url"}


def _required(spec_path: str, schema: str) -> set:
    spec = yaml.safe_load((ROOT / spec_path).read_text())
    return set(spec["components"]["schemas"][schema]["required"])


# ── 1) lato contratto: la spec dichiara i campi obbligatori ─────────────────────

def test_media_item_declares_filename_and_status_required():
    req = _required("openapi/media/api.yaml", "MediaItem")
    assert {"filename", "status"} <= req
    assert _MUST_INCLUDE <= req


def test_source_media_item_declares_filename_and_status_required():
    req = _required("openapi/source/api.yaml", "SourceMediaItem")
    assert {"filename", "status"} <= req
    assert _MUST_INCLUDE <= req


# ── 2) lato realta': il servizio restituisce quei campi ─────────────────────────

@pytest.fixture()
def source_client(monkeypatch, tmp_path):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("SOURCE_DB_PATH", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("SOURCE_MEDIA_DIR", str(tmp_path))
    from src.app import create_app

    app = create_app(domains=["source"])
    import src.domains.source.controllers.source_controller as sc
    from src.domains.source.factory import build_source_service

    sc._service = build_source_service()
    return app.test_client()


def test_uploaded_media_response_includes_required_fields(source_client):
    r = source_client.post(
        "/v0/source/media",
        files={"file": ("puntata.m4a", b"AUDIO", "audio/m4a")},
        data={"title": "Puntata contratto", "media_type": "audio/m4a"},
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 201
    body = r.json()
    missing = _MUST_INCLUDE - body.keys()
    assert not missing, f"campi obbligatori assenti nella risposta: {missing}"
    assert body["filename"] == "puntata.m4a"      # generato/registrato dal servizio
    assert body["status"] in {"ready", "processing", "error"}


def test_media_remap_preserves_filename_and_status():
    # il BFF media ri-mappa gli URL ma NON deve perdere filename/status nel passaggio.
    from src.domains.media.services.media_service import _remap

    src_item = {
        "id": 1, "title": "T", "filename": "t.m4a", "media_type": "audio/m4a",
        "created_at_s": 1, "status": "ready",
        "content_url": "/v0/source/media/1/content",
        "download_url": "/v0/source/media/1/content?download=1",
    }
    out = _remap(src_item)
    assert out["filename"] == "t.m4a"
    assert out["status"] == "ready"
    assert out["content_url"] == "/v0/media/1/content"
