"""Business logic del dominio `audio`: valida i riferimenti/formati e mette in coda i job.

Le operazioni sono lunghe: il service NON elabora, crea un job `queued` (persistente) e
restituisce 202 + job_id. L'esecuzione e' del worker. `get_job` mappa lo stato per il polling.
"""
from typing import Optional

from src.domains.audio.errors import FormatNotSupported, RefNotResolved
from src.domains.audio.naming import new_job_id
from src.domains.audio.processors import ffmpeg_processor as fp


def _is_int_ref(ref) -> bool:
    return isinstance(ref, int) and not isinstance(ref, bool)


class AudioService:
    def __init__(self, gateway, store) -> None:
        self._gw = gateway
        self._store = store

    # ── risoluzione/validazione riferimenti ────────────────────────────────────

    def _resolve(self, ref, field: str) -> dict:
        if _is_int_ref(ref):
            rec = self._gw.get_by_id(ref)
            searched = "id"
        else:
            rec = self._gw.resolve_filename(str(ref))
            searched = "filename"
        if rec is None:
            raise RefNotResolved(ref, field=field, searched_by=searched)
        return rec

    def _resolve_audio(self, ref, field: str) -> dict:
        rec = self._resolve(ref, field)
        if rec.get("media_type") not in fp.INPUT_AUDIO_TYPES:
            raise FormatNotSupported(rec.get("media_type"), field=field, accepted=fp.INPUT_AUDIO_TYPES)
        return {"id": rec["id"], "filename": rec["filename"], "media_type": rec["media_type"]}

    @staticmethod
    def _require_output(fmt: str, field: str = "format") -> str:
        if not fp.is_supported_output(fmt):
            raise FormatNotSupported(fmt, field=field, accepted=fp.OUTPUT_FORMATS)
        return fmt

    # ── submit delle operazioni ────────────────────────────────────────────────

    def _submit(self, op: str, inputs: list[dict], params: dict) -> dict:
        job_id = new_job_id(op)
        payload = {"op": op, "inputs": inputs, **params}
        self._store.create(job_id, op, payload)
        return {
            "job_id": job_id, "status": "queued", "op": op,
            "poll_url": f"/v0/audio/job/{job_id}",
        }

    def normalize(self, body: dict) -> dict:
        src = self._resolve_audio(body["source"], "source")
        fmt = self._require_output(body.get("format", "audio/mpeg"))
        return self._submit("normalize", [src], {
            "format": fmt,
            "maxgain": body.get("maxgain", 80),
            "target_lufs": body.get("target_lufs", -16),
            "true_peak_dbtp": body.get("true_peak_dbtp", -1.5),
            "loudness_range": body.get("loudness_range", 11),
            "two_pass": bool(body.get("two_pass", False)),
            "title": body.get("title"),
        })

    def silence(self, body: dict) -> dict:
        src = self._resolve_audio(body["source"], "source")
        fmt = self._require_output(body.get("format", "audio/wav"))
        return self._submit("silence", [src], {
            "format": fmt,
            "threshold_db": body.get("threshold_db", -40),
            "min_pause_s": body.get("min_pause_s", 1.0),
            "keep_silence_s": body.get("keep_silence_s", 0.3),
            "title": body.get("title"),
        })

    def convert(self, body: dict) -> dict:
        src = self._resolve_audio(body["source"], "source")
        fmt = self._require_output(body["format"])
        return self._submit("convert", [src], {"format": fmt, "title": body.get("title")})

    def analyze(self, body: dict) -> dict:
        src = self._resolve_audio(body["source"], "source")
        return self._submit("analyze", [src], {
            "silence_thresholds_db": body.get("silence_thresholds_db", [-30, -40, -50]),
        })

    def split(self, body: dict) -> dict:
        src = self._resolve_audio(body["source"], "source")
        fmt = self._require_output(body.get("format", "audio/wav"))
        return self._submit("split", [src], {
            "format": fmt,
            "segment_seconds": int(body["segment_seconds"]),
            "title": body.get("title"),
        })

    def concat(self, body: dict) -> dict:
        inputs = [
            self._resolve_audio(ref, f"sources[{i}]")
            for i, ref in enumerate(body["sources"])
        ]
        fmt = self._require_output(body.get("format", "audio/mpeg"))
        return self._submit("concat", inputs, {"format": fmt, "title": body.get("title")})

    # ── polling ─────────────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[dict]:
        job = self._store.get(job_id)
        if job is None:
            return None
        return {
            "job_id": job["job_id"], "op": job["op"], "status": job["status"],
            "created_at_s": job["created_at_s"], "updated_at_s": job["updated_at_s"],
            "result": job["result"], "error": job["error"],
        }
