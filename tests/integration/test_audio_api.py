"""Integration test del dominio audio (livello API, senza ffmpeg).

Verifica il contratto: POST -> 202 + job_id (queued), GET job/{id} -> stato, errori
diagnostici (field/searched_by) su riferimento/formato, 404/401. L'esecuzione (worker+ffmpeg)
e' coperta dai test e2e.
"""
import warnings

import pytest

warnings.filterwarnings("ignore")

_KEY = {"X-API-Key": "test"}

_AUDIO = {"id": 7, "filename": "puntata-pilota.wav", "media_type": "audio/wav"}
_IMAGE = {"id": 8, "filename": "logo.png", "media_type": "image/png"}


class _FakeGateway:
    def get_by_id(self, media_id):
        return {7: _AUDIO, 8: _IMAGE}.get(media_id)

    def resolve_filename(self, filename):
        if "puntata" in filename:
            return _AUDIO
        if filename == "logo.png":
            return _IMAGE
        return None


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("AUDIO_DB_PATH", str(tmp_path / "audio.db"))
    monkeypatch.delenv("AUDIO_START_WORKER", raising=False)  # niente worker nei test API
    from src.app import create_app
    from src.domains.audio.repositories.job_store import JobStore
    from src.domains.audio.services.audio_service import AudioService

    app = create_app(domains=["audio"])
    import src.domains.audio.controllers.audio_controller as ac

    ac._service = AudioService(_FakeGateway(), JobStore(str(tmp_path / "audio.db")))
    return app.test_client()


def test_health(client):
    assert client.get("/v0/audio/health").json() == {"status": "ok"}


def test_requires_api_key(client):
    assert client.post("/v0/audio/normalize", json={"source": 7}).status_code == 401


def test_normalize_returns_202_job_and_pollable(client):
    r = client.post("/v0/audio/normalize", json={"source": 7, "maxgain": 80}, headers=_KEY)
    assert r.status_code == 202
    body = r.json()
    assert body["op"] == "normalize" and body["status"] == "queued"
    assert body["poll_url"] == f"/v0/audio/job/{body['job_id']}"
    # human-readable job id
    assert body["job_id"].startswith("normalize-")
    # subito interrogabile
    j = client.get(f"/v0/audio/job/{body['job_id']}", headers=_KEY)
    assert j.status_code == 200 and j.json()["status"] == "queued"


@pytest.mark.parametrize("op,extra", [
    ("normalize", {}),
    ("silence", {}),
    ("convert", {"format": "audio/mpeg"}),
    ("analyze", {}),
    ("split", {"segment_seconds": 30}),
])
def test_each_op_accepts_by_filename(client, op, extra):
    r = client.post(f"/v0/audio/{op}", json={"source": "puntata-pilota", **extra}, headers=_KEY)
    assert r.status_code == 202, r.json()
    assert r.json()["op"] == op


def test_concat_needs_two_and_accepts(client):
    r = client.post("/v0/audio/concat",
                    json={"sources": [7, "puntata-pilota"], "format": "audio/mpeg"}, headers=_KEY)
    assert r.status_code == 202 and r.json()["op"] == "concat"


def test_bad_ref_is_400_diagnostic_by_id(client):
    r = client.post("/v0/audio/normalize", json={"source": 999}, headers=_KEY)
    assert r.status_code == 400
    b = r.json()
    assert b["field"] == "source" and b["value"] == 999 and b["searched_by"] == "id"


def test_bad_ref_by_filename_says_searched_by_filename(client):
    r = client.post("/v0/audio/normalize", json={"source": "non-esiste"}, headers=_KEY)
    assert r.status_code == 400 and r.json()["searched_by"] == "filename"


def test_non_audio_input_is_400_format(client):
    # un'immagine non e' input valido: l'errore lo dice (non un 500), col campo
    r = client.post("/v0/audio/silence", json={"source": 8}, headers=_KEY)
    assert r.status_code == 400
    b = r.json()
    assert b["field"] == "source" and "image/png" in b["detail"]


def test_unknown_job_404(client):
    assert client.get("/v0/audio/job/nope-123", headers=_KEY).status_code == 404
