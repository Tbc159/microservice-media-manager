"""Worker: esegue i job audio rivendicati dallo store.

Scarica gli input da source, esegue ffmpeg, carica gli output come nuovi media (o, per
analyze, salva l'analisi associata al media e la riusa). Aggiorna lo stato del job. Ogni
errore diventa `error` diagnostico sul job (non un crash del worker).

In produzione un thread di background chiama `run_once()` in loop (vedi factory). Nei test si
chiama `run_once()`/`execute()` in modo sincrono.
"""
import logging
import os
import tempfile

from src import signed_url
from src.domains.audio.errors import FormatNotSupported, RefNotResolved
from src.domains.audio.naming import output_filename
from src.domains.audio.processors import ffmpeg_processor as fp

logger = logging.getLogger("audio")


class Worker:
    def __init__(self, gateway, store) -> None:
        self._gw = gateway
        self._store = store

    def run_once(self):
        """Rivendica ed esegue un job; ritorna il job_id eseguito o None se coda vuota."""
        job = self._store.claim_next()
        if job is None:
            return None
        self.execute(job)
        return job["job_id"]

    def execute(self, job: dict) -> None:
        job_id = job["job_id"]
        try:
            result = self._dispatch(job)
            self._store.set_succeeded(job_id, result)
        except (RefNotResolved, FormatNotSupported) as exc:
            self._store.set_failed(job_id, exc.to_body())
        except fp.FfmpegError as exc:
            self._store.set_failed(job_id, {"detail": f"ffmpeg: {exc}"})
        except Exception as exc:  # noqa: BLE001 - qualunque errore diventa stato del job
            logger.exception("job %s fallito", job_id)
            self._store.set_failed(job_id, {"detail": str(exc)})

    # ── esecuzione ──────────────────────────────────────────────────────────────

    def _dispatch(self, job: dict) -> dict:
        params = job["params"]
        op = params["op"]
        inputs = params["inputs"]
        token = job["job_id"].rsplit("-", 1)[-1]

        with tempfile.TemporaryDirectory(prefix="audio-") as work:
            in_paths = []
            for inp in inputs:
                data = self._gw.get_bytes(inp["id"])
                if data is None:
                    raise RefNotResolved(inp["id"], field="source", searched_by="id")
                path = os.path.join(work, f"in-{inp['id']}.{fp.input_ext(inp['media_type'])}")
                with open(path, "wb") as fh:
                    fh.write(data)
                in_paths.append(path)

            if op == "analyze":
                return self._run_analyze(inputs[0], in_paths[0], params)

            fmt = params["format"]
            stem = inputs[0]["filename"]
            title = params.get("title")

            if op in ("normalize", "silence", "convert"):
                out = os.path.join(work, output_filename(stem, op, fp.ext_for(fmt), token))
                self._run_op(op, in_paths[0], out, params)
                return {"media": [self._upload(out, fmt, os.path.basename(out), title, stem, op)]}

            if op == "split":
                parts = fp.run_split(in_paths[0], work, f"{token}-part",
                                     segment_seconds=params["segment_seconds"], out_fmt=fmt)
                media = []
                for i, part in enumerate(parts):
                    fn = output_filename(stem, f"split-{i:03d}", fp.ext_for(fmt), token)
                    media.append(self._upload(part, fmt, fn, title, stem, f"split {i:03d}"))
                return {"media": media}

            if op == "concat":
                out = os.path.join(work, output_filename(stem, op, fp.ext_for(fmt), token))
                fp.run_concat(in_paths, out, out_fmt=fmt, work_dir=work)
                return {"media": [self._upload(out, fmt, os.path.basename(out), title, stem, op)]}

            raise ValueError(f"operazione sconosciuta: {op}")

    def _run_op(self, op, inp, out, params) -> None:
        if op == "normalize":
            fp.run_normalize(
                inp, out, maxgain=params["maxgain"], target_lufs=params["target_lufs"],
                true_peak=params["true_peak_dbtp"], lra=params["loudness_range"],
                two_pass=params["two_pass"], out_fmt=params["format"],
            )
        elif op == "silence":
            fp.run_silence(
                inp, out, threshold_db=params["threshold_db"],
                min_pause_s=params["min_pause_s"], keep_silence_s=params["keep_silence_s"],
                out_fmt=params["format"],
            )
        elif op == "convert":
            fp.run_convert(inp, out, out_fmt=params["format"])

    def _run_analyze(self, inp_meta, path, params) -> dict:
        media_id = inp_meta["id"]
        analysis = self._store.get_analysis(media_id)
        if analysis is None:
            analysis = fp.analyze(path, silence_thresholds=params["silence_thresholds_db"])
            self._store.put_analysis(media_id, analysis)
        return {"analysis": {"media_id": media_id, **analysis}}

    def _upload(self, path, out_fmt, filename, title, source_stem, op) -> dict:
        with open(path, "rb") as fh:
            data = fh.read()
        result = self._gw.upload_media(
            title=title or f"{source_stem} ({op})", media_type=out_fmt,
            filename=filename, data=data,
        )
        if result.status_code != 201:
            raise RuntimeError(
                f"salvataggio media fallito ({result.status_code}): "
                f"{result.payload.get('detail', '')}"
            )
        p = result.payload
        mid = p["id"]
        # Il client riproduce l'output in un <audio src>: senza URL firmato riceverebbe 401.
        return signed_url.decorate({
            "id": mid, "media_type": p.get("media_type", out_fmt),
            "content_url": f"/v0/media/{mid}/content",
            "download_url": f"/v0/media/{mid}/content?download=1",
        }, mid)
