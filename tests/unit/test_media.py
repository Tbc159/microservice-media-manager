from src.domains.media.controllers.health_controller import get_health
from src.domains.media.services.media_service import MediaService


def test_health_returns_ok():
    body, status = get_health()
    assert status == 200
    assert body["status"] == "ok"


def test_list_all_conforms_to_schema():
    items = MediaService().list_all()
    assert isinstance(items, list) and items
    item = items[0]
    assert isinstance(item["id"], int)
    assert isinstance(item["name"], str)
    assert item["status"] in {"draft", "processing", "published"}
