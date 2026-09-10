"""Controller del dominio audio.

Le operationId dell'OAS risolvono qui via RelativeResolver("src.domains.audio.controllers").
All'import si avvia (se richiesto da AUDIO_START_WORKER) il worker in background.
"""
from src.domains.audio.factory import maybe_start_background_worker

from .audio_controller import (
    analyze_audio,
    concat_audio,
    convert_audio,
    get_audio_job,
    normalize_audio,
    shorten_silence,
    split_audio,
)
from .health_controller import get_health

maybe_start_background_worker()

__all__ = [
    "get_health",
    "normalize_audio",
    "shorten_silence",
    "convert_audio",
    "analyze_audio",
    "split_audio",
    "concat_audio",
    "get_audio_job",
]
