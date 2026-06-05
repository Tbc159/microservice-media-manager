from src.domains.source.controllers.health_controller import get_health
from src.domains.source.repositories.mock_repository import MockSourceMediaRepository
from src.domains.source.services.source_service import SourceService


def _svc() -> SourceService:
    return SourceService(repo=MockSourceMediaRepository())


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
    required = {"id", "title", "filename", "media_type", "file_path", "created_at_s"}
    for item in result["items"]:
        assert required.issubset(item.keys()), f"Campi mancanti in {item}"
        assert isinstance(item["id"], int)
        assert isinstance(item["title"], str)
        assert isinstance(item["created_at_s"], int)
