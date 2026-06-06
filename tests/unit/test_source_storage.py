"""Test del backend storage locale e del factory (composition root)."""
import importlib

from src.domains.source.repositories.mock_repository import MockSourceMediaRepository
from src.domains.source.repositories.sqlite_repository import SqliteSourceMediaRepository
from src.domains.source.storage.local_backend import LocalStorageBackend


def test_local_put_and_exists(tmp_path):
    backend = LocalStorageBackend(media_dir=str(tmp_path))
    key = "audio/m4a/file.m4a"
    assert backend.object_exists(key) is False
    backend.put_object(key, b"audio-bytes", "audio/m4a")
    assert backend.object_exists(key) is True
    assert (tmp_path / key).read_bytes() == b"audio-bytes"


def test_local_no_presigned_urls(tmp_path):
    backend = LocalStorageBackend(media_dir=str(tmp_path))
    assert backend.get_stream_url("k") is None
    assert backend.get_upload_url("k") is None
    assert backend.get_download_url("k", filename="f.m4a") is None


def test_local_path_existing_and_missing(tmp_path):
    backend = LocalStorageBackend(media_dir=str(tmp_path))
    assert backend.local_path("a/b.m4a") is None          # non esiste
    backend.put_object("a/b.m4a", b"x", "audio/m4a")
    p = backend.local_path("a/b.m4a")
    assert p is not None and p.endswith("a/b.m4a")


def _factory(monkeypatch, **env):
    for k in (
        "SOURCE_DB_PATH",
        "STORAGE_BACKEND",
        "STORAGE_ENDPOINT",
        "STORAGE_ACCESS_KEY",
        "STORAGE_SECRET_KEY",
        "SOURCE_MEDIA_DIR",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    factory = importlib.import_module("src.domains.source.factory")
    return factory


def test_factory_defaults_to_mock_and_local(monkeypatch):
    factory = _factory(monkeypatch)
    svc = factory.build_source_service()
    assert isinstance(svc._repo, MockSourceMediaRepository)
    assert isinstance(svc._storage, LocalStorageBackend)


def test_factory_uses_sqlite_when_db_path_set(monkeypatch, tmp_path):
    factory = _factory(monkeypatch, SOURCE_DB_PATH=str(tmp_path / "s.db"))
    svc = factory.build_source_service()
    assert isinstance(svc._repo, SqliteSourceMediaRepository)


def test_factory_invalid_backend_raises(monkeypatch):
    factory = _factory(monkeypatch, STORAGE_BACKEND="bogus")
    try:
        factory.build_source_service()
        assert False, "atteso ValueError per backend non valido"
    except ValueError:
        pass
