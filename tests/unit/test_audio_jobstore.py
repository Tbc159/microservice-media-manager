"""Job store persistente: creazione, claim atomico, recovery al riavvio, cache analisi.

Copre il vincolo #5 del modello: i job sopravvivono al riavvio (stato su file, non in memoria).
"""
from src.domains.audio.repositories.job_store import JobStore


def _store(tmp_path):
    return JobStore(str(tmp_path / "audio.db"))


def test_create_and_get(tmp_path):
    s = _store(tmp_path)
    s.create("normalize-1", "normalize", {"op": "normalize", "inputs": [{"id": 7}]})
    job = s.get("normalize-1")
    assert job["status"] == "queued" and job["op"] == "normalize"
    assert job["params"]["inputs"][0]["id"] == 7
    assert s.get("inesistente") is None


def test_claim_next_is_fifo_and_sets_running(tmp_path):
    s = _store(tmp_path)
    s.create("a-1", "convert", {"op": "convert"})
    s.create("a-2", "convert", {"op": "convert"})
    first = s.claim_next()
    assert first["job_id"] == "a-1" and first["status"] == "running"
    second = s.claim_next()
    assert second["job_id"] == "a-2"
    assert s.claim_next() is None  # coda vuota


def test_survives_restart(tmp_path):
    # "riavvio" = nuova istanza sullo stesso file DB
    s1 = _store(tmp_path)
    s1.create("job-x", "normalize", {"op": "normalize"})
    s1.claim_next()  # -> running
    s2 = JobStore(str(tmp_path / "audio.db"))
    assert s2.get("job-x")["status"] == "running"       # ancora interrogabile
    assert s2.requeue_running() == 1                    # recovery: running -> queued
    assert s2.get("job-x")["status"] == "queued"


def test_result_and_failure(tmp_path):
    s = _store(tmp_path)
    s.create("j", "analyze", {"op": "analyze"})
    s.set_succeeded("j", {"analysis": {"media_id": 5}})
    assert s.get("j")["status"] == "succeeded"
    assert s.get("j")["result"]["analysis"]["media_id"] == 5
    s.create("k", "normalize", {"op": "normalize"})
    s.set_failed("k", {"detail": "boom", "field": "source"})
    assert s.get("k")["status"] == "failed" and s.get("k")["error"]["field"] == "source"


def test_analysis_cache(tmp_path):
    s = _store(tmp_path)
    assert s.get_analysis(42) is None
    s.put_analysis(42, {"integrated_lufs": -21.0})
    assert s.get_analysis(42)["integrated_lufs"] == -21.0
    s.put_analysis(42, {"integrated_lufs": -20.0})   # upsert
    assert s.get_analysis(42)["integrated_lufs"] == -20.0
