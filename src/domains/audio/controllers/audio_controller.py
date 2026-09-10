"""Controller del dominio `audio`: thin layer.

Ogni POST valida/accoda e risponde **202** con il job; gli errori di riferimento/formato
diventano **400** diagnostici (field/value/searched_by). `GET /audio/job/{id}` -> stato o 404.
Il worker (se attivo) gira in background e viene avviato all'import del package.
"""
from src.domains.audio.errors import FormatNotSupported, RefNotResolved
from src.domains.audio.factory import build_service

_service = build_service()


def _accepted(fn, body):
    try:
        return fn(body), 202
    except (RefNotResolved, FormatNotSupported) as exc:
        return exc.to_body(), 400


def normalize_audio(body: dict):
    return _accepted(_service.normalize, body)


def shorten_silence(body: dict):
    return _accepted(_service.silence, body)


def convert_audio(body: dict):
    return _accepted(_service.convert, body)


def analyze_audio(body: dict):
    return _accepted(_service.analyze, body)


def split_audio(body: dict):
    return _accepted(_service.split, body)


def concat_audio(body: dict):
    return _accepted(_service.concat, body)


def get_audio_job(id: str):
    job = _service.get_job(id)
    return (job, 200) if job is not None else ("", 404)
