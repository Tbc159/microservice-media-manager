import pytest

from src.domains.source.controllers.health_controller import get_health
from src.domains.source.repositories.base import DuplicateObjectKeyError
from src.domains.source.repositories.mock_repository import MockSourceMediaRepository
from src.domains.source.services.source_service import SourceService
from src.domains.source.storage.local_backend import LocalStorageBackend


def _svc() -> SourceService:
    return SourceService(repo=MockSourceMediaRepository(), storage=LocalStorageBackend())


def _svc_fs(tmp_path) -> SourceService:
    # storage locale su dir temporanea: create() scrive davvero i byte
    return SourceService(
        repo=MockSourceMediaRepository(), storage=LocalStorageBackend(media_dir=str(tmp_path))
    )


def test_health_returns_ok():
    body, status = get_health()
    assert status == 200
    assert body["status"] == "ok"


def test_query_all_by_type_returns_matching():
    result = _svc().query(media_type="audio/m4a")
    assert result["items"]
    assert all(i["media_type"] == "audio/m4a" for i in result["items"])


def test_query_mp3_returns_only_mp3():
    result = _svc().query(media_type="audio/mp3")
    assert result["items"]
    assert all(i["media_type"] == "audio/mp3" for i in result["items"])


def test_query_by_exact_title():
    result = _svc().query(media_type="audio/m4a", title="Puntata pilota")
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == "Puntata pilota"


def test_query_title_no_match_returns_empty():
    result = _svc().query(media_type="audio/m4a", title="Titolo inesistente")
    assert result["items"] == []
    assert result["pagination"]["total"] == 0
    assert result["pagination"]["total_pages"] == 0


def test_pagination_page_size_1():
    result = _svc().query(media_type="audio/m4a", page=1, page_size=1)
    assert len(result["items"]) == 1
    p = result["pagination"]
    assert p["page"] == 1
    assert p["page_size"] == 1
    assert p["total"] >= 2
    assert p["total_pages"] >= 2


def test_pagination_page_2():
    first = _svc().query(media_type="audio/m4a", page=1, page_size=1)
    second = _svc().query(media_type="audio/m4a", page=2, page_size=1)
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_pagination_fields_present():
    result = _svc().query(media_type="audio/m4a")
    p = result["pagination"]
    assert all(k in p for k in ("page", "page_size", "total", "total_pages"))


def test_item_schema_required_fields():
    result = _svc().query(media_type="audio/m4a")
    required = {"id", "title", "filename", "media_type", "created_at_s", "status"}
    for item in result["items"]:
        assert required.issubset(item.keys()), f"Campi mancanti in {item}"
        assert isinstance(item["id"], int)
        assert isinstance(item["title"], str)
        assert isinstance(item["created_at_s"], int)
        assert item["status"] in {"ready", "processing", "error"}


def test_object_key_never_exposed():
    # object_key e' un dettaglio interno allo storage: non deve uscire dall'API.
    result = _svc().query(media_type="audio/m4a")
    for item in result["items"]:
        assert "object_key" not in item
        assert "file_path" not in item


def test_content_urls_exposed_not_object_key():
    # Ogni item espone i link content_url/download_url (verso /content), mai object_key.
    result = _svc().query(media_type="audio/m4a")
    for item in result["items"]:
        assert item["content_url"] == f"/v0/source/media/{item['id']}/content"
        assert item["download_url"] == f"/v0/source/media/{item['id']}/content?download=1"
        assert "stream_url" not in item
        assert "object_key" not in item


def test_create_inserts_metadata_and_writes_bytes(tmp_path):
    svc = _svc_fs(tmp_path)
    item = svc.create(
        title="Nuova", media_type="audio/m4a", filename="x.m4a", data=b"abc", duration_s=10
    )
    assert item["title"] == "Nuova"
    assert item["filename"] == "x.m4a"
    assert item["size_bytes"] == 3
    assert item["duration_s"] == 10
    assert item["status"] == "ready"
    assert item["content_url"] == f"/v0/source/media/{item['id']}/content"
    assert "object_key" not in item          # interno, mai esposto
    assert (tmp_path / "audio/m4a/x.m4a").read_bytes() == b"abc"


def test_create_then_listed(tmp_path):
    svc = _svc_fs(tmp_path)
    svc.create(title="N", media_type="audio/m4a", filename="nuovo.m4a", data=b"z")
    result = svc.query(media_type="audio/m4a")
    titles = [i["title"] for i in result["items"]]
    assert "N" in titles


def test_create_duplicate_raises(tmp_path):
    svc = _svc_fs(tmp_path)
    svc.create(title="A", media_type="audio/m4a", filename="dup.m4a", data=b"1")
    with pytest.raises(DuplicateObjectKeyError):
        svc.create(title="B", media_type="audio/m4a", filename="dup.m4a", data=b"2")


def test_presigned_upload_url_none_on_local(tmp_path):
    # Predisposizione pre-signed: con storage locale (dev) non c'e' URL firmato.
    svc = _svc_fs(tmp_path)
    assert svc.presigned_upload_url(media_type="audio/m4a", filename="x.m4a") is None


def test_get_item_returns_metadata_or_none(tmp_path):
    svc = _svc_fs(tmp_path)
    svc.create(title="G", media_type="audio/m4a", filename="g.m4a", data=b"x")
    rid = next(i["id"] for i in svc.query(media_type="audio/m4a")["items"] if i["title"] == "G")
    item = svc.get_item(rid)
    assert item is not None and item["title"] == "G"
    assert item["content_url"] == f"/v0/source/media/{rid}/content"
    assert svc.get_item(99999) is None


def test_content_local_returns_target_inline_and_attachment(tmp_path):
    svc = _svc_fs(tmp_path)
    svc.create(title="D", media_type="audio/m4a", filename="d.m4a", data=b"hello")
    rid = next(i["id"] for i in svc.query(media_type="audio/m4a")["items"] if i["title"] == "D")
    for download in (False, True):  # in locale entrambi -> local_path (la disposition e' nel controller)
        target = svc.content(rid, download=download)
        assert target is not None
        assert target.redirect_url is None          # storage locale: nessun redirect
        assert target.local_path is not None
        assert target.filename == "d.m4a"
        with open(target.local_path, "rb") as fh:
            assert fh.read() == b"hello"


def test_content_absent_id_returns_none(tmp_path):
    assert _svc_fs(tmp_path).content(99999, download=False) is None


def test_content_record_without_bytes_returns_none(tmp_path):
    # I record seed del mock non hanno file su storage -> content None (404 a valle).
    assert _svc_fs(tmp_path).content(1, download=False) is None
