"""Composition root del dominio `audio`.

Service e worker condividono lo **stesso** job store (stesso file SQLite): il service crea i
job, il worker li rivendica. Il worker gira in un thread di background nel container (attivato
da `AUDIO_START_WORKER=1`); nei test resta spento e i job si eseguono in modo sincrono.

Env:
  AUDIO_DB_PATH        file SQLite dei job (default /data/audio.db)
  SOURCE_INTERNAL_URL  base di source (default http://source:8080/v0/source)
  API_KEY              chiave verso source
  FFMPEG_BIN           binario ffmpeg (default 'ffmpeg')
  AUDIO_START_WORKER   '1' -> avvia il worker in background (container)
"""
import logging
import os
import threading
import time

from src.domains.audio.gateway import SourceGateway
from src.domains.audio.repositories.job_store import JobStore
from src.domains.audio.services.audio_service import AudioService
from src.domains.audio.worker import Worker

logger = logging.getLogger("audio")


def _db_path() -> str:
    return os.environ.get("AUDIO_DB_PATH", "/data/audio.db")


def _gateway() -> SourceGateway:
    return SourceGateway(
        base_url=os.environ.get("SOURCE_INTERNAL_URL", "http://source:8080/v0/source"),
        api_key=os.environ.get("API_KEY", ""),
    )


def build_service() -> AudioService:
    return AudioService(_gateway(), JobStore(_db_path()))


def build_worker() -> Worker:
    return Worker(_gateway(), JobStore(_db_path()))


def maybe_start_background_worker() -> None:
    """Avvia il worker in background se richiesto (container). Idempotente per processo."""
    if os.environ.get("AUDIO_START_WORKER") != "1":
        return
    store = JobStore(_db_path())
    requeued = store.requeue_running()  # recupero dei job del processo precedente
    if requeued:
        logger.info("audio: ri-accodati %d job 'running' dopo il riavvio", requeued)
    worker = Worker(_gateway(), store)

    def _loop() -> None:
        while True:
            try:
                if worker.run_once() is None:
                    time.sleep(1.0)
            except Exception:  # noqa: BLE001
                logger.exception("audio worker: errore nel loop")
                time.sleep(2.0)

    threading.Thread(target=_loop, name="audio-worker", daemon=True).start()
    logger.info("audio worker avviato")
