"""Test del repository SQLite su un DB temporaneo (file reale, WAL)."""
from src.domains.source.repositories.sqlite_repository import SqliteSourceMediaRepository


def _repo(tmp_path) -> SqliteSourceMediaRepository:
    return SqliteSourceMediaRepository(str(tmp_path / "source.db"))


def test_schema_created_and_empty(tmp_path):
    repo = _repo(tmp_path)
    items, total = repo.find("audio/m4a", None, 1, 20)
    assert items == []
    assert total == 0


def test_insert_then_find(tmp_path):
    repo = _repo(tmp_path)
    new_id = repo.insert(
        title="Test puntata",
        filename="test.m4a",
        media_type="audio/m4a",
        object_key="audio/m4a/test.m4a",
        size_bytes=123,
        duration_s=60,
        metadata={"k": "v"},
    )
    assert new_id >= 1
    items, total = repo.find("audio/m4a", None, 1, 20)
    assert total == 1
    rec = items[0]
    assert rec["title"] == "Test puntata"
    assert rec["object_key"] == "audio/m4a/test.m4a"
    assert rec["status"] == "ready"
    assert rec["metadata"] == {"k": "v"}


def test_find_filters_by_type(tmp_path):
    repo = _repo(tmp_path)
    repo.insert(title="A", filename="a.m4a", media_type="audio/m4a", object_key="k/a")
    repo.insert(title="B", filename="b.mp3", media_type="audio/mp3", object_key="k/b")
    m4a, total_m4a = repo.find("audio/m4a", None, 1, 20)
    assert total_m4a == 1 and m4a[0]["media_type"] == "audio/m4a"


def test_find_filters_by_title(tmp_path):
    repo = _repo(tmp_path)
    repo.insert(title="Uno", filename="1.m4a", media_type="audio/m4a", object_key="k/1")
    repo.insert(title="Due", filename="2.m4a", media_type="audio/m4a", object_key="k/2")
    items, total = repo.find("audio/m4a", "Due", 1, 20)
    assert total == 1 and items[0]["title"] == "Due"


def test_pagination_offset(tmp_path):
    repo = _repo(tmp_path)
    for n in range(5):
        repo.insert(
            title=f"T{n}", filename=f"{n}.m4a", media_type="audio/m4a", object_key=f"k/{n}"
        )
    page1, total = repo.find("audio/m4a", None, 1, 2)
    page2, _ = repo.find("audio/m4a", None, 2, 2)
    assert total == 5
    assert len(page1) == 2 and len(page2) == 2
    assert {i["id"] for i in page1}.isdisjoint({i["id"] for i in page2})


def test_unique_object_key_constraint(tmp_path):
    import sqlite3

    repo = _repo(tmp_path)
    repo.insert(title="A", filename="a.m4a", media_type="audio/m4a", object_key="dup")
    try:
        repo.insert(title="B", filename="b.m4a", media_type="audio/m4a", object_key="dup")
        assert False, "atteso IntegrityError su object_key duplicato"
    except sqlite3.IntegrityError:
        pass
