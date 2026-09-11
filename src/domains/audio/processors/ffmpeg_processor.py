"""Elaborazione audio con ffmpeg: command-builder puri (testabili) + runner.

Scelte DSP misurate (vedi test e2e e doc):
- normalize: `dynaudnorm=f=250:g=11:m=<maxgain>` + `loudnorm` (target EBU R128). `maxgain` alto e'
  cio' che allinea i parlanti (il default 10 di ffmpeg non basta). 1 passata soddisfa i target;
  2 passate (misura+applica, linear) sono piu' precise ma piu' lente.
- silence: `silenceremove` con start_periods (taglia il silenzio INIZIALE lungo, lasciando
  `keep_silence_s`) + stop_periods=-1 (accorcia pause interne e coda). Soglia con unita' `dB`.
- intermedi senza perdita: l'output di default delle operazioni "intermedie" (silence/split) e'
  wav; la compressione avviene solo dove il chiamante sceglie il `format`.

Il binario e' `FFMPEG_BIN` (default "ffmpeg"): nei test punta al binario statico imageio-ffmpeg.
"""
import json
import os
import re
import subprocess
from typing import Optional

def _bin() -> str:
    # Risolto a ogni chiamata: i test possono puntarlo al binario statico imageio-ffmpeg.
    return os.environ.get("FFMPEG_BIN", "ffmpeg")

# media_type -> (estensione, argomenti codec di output)
_FORMATS = {
    "audio/mpeg": ("mp3", ["-c:a", "libmp3lame", "-q:a", "2"]),
    "audio/m4a": ("m4a", ["-c:a", "aac", "-b:a", "192k"]),
    "audio/wav": ("wav", ["-c:a", "pcm_s16le"]),
}

# input accettati dalle operazioni audio (i wav inclusi: nessuna conversione a carico del client)
INPUT_AUDIO_TYPES = frozenset({"audio/m4a", "audio/mpeg", "audio/mp3", "audio/wav"})
# formati di output producibili
OUTPUT_FORMATS = frozenset(_FORMATS)
# media_type input -> estensione del file temporaneo (ffmpeg rileva comunque dal contenuto)
_INPUT_EXT = {"audio/m4a": "m4a", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav"}


def input_ext(media_type: str) -> str:
    return _INPUT_EXT.get(media_type, "bin")


class FfmpegError(Exception):
    """ffmpeg ha restituito un codice != 0 (l'ultima riga di stderr e' nel messaggio)."""


def _num(x) -> str:
    """Numero -> stringa senza `.0` inutile (ffmpeg accetta comunque i float)."""
    f = float(x)
    return str(int(f)) if f == int(f) else str(f)


def ext_for(media_type: str) -> str:
    return _FORMATS[media_type][0]


def output_args(media_type: str) -> list[str]:
    return list(_FORMATS[media_type][1])


def is_supported_output(media_type: str) -> bool:
    return media_type in _FORMATS


# ── Command-builder puri (filtri) ───────────────────────────────────────────────

def normalize_af(maxgain, target_lufs, true_peak, lra, measured: Optional[dict] = None) -> str:
    af = f"dynaudnorm=f=250:g=11:m={_num(maxgain)}"
    ln = f"loudnorm=I={_num(target_lufs)}:TP={_num(true_peak)}:LRA={_num(lra)}"
    if measured is not None:
        ln += (
            f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            ":linear=true"
        )
    return f"{af},{ln}"


def silence_af(threshold_db, min_pause_s, keep_silence_s) -> str:
    thr = f"{_num(threshold_db)}dB"
    keep = _num(keep_silence_s)
    return (
        f"silenceremove=start_periods=1:start_duration=0.1:start_threshold={thr}:start_silence={keep}:"
        f"stop_periods=-1:stop_duration={_num(min_pause_s)}:stop_threshold={thr}:stop_silence={keep}"
    )


# ── Runner ──────────────────────────────────────────────────────────────────────

def _run(args: list[str]) -> str:
    r = subprocess.run(
        [_bin(), "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()
        raise FfmpegError(tail[-1] if tail else f"ffmpeg exit {r.returncode}")
    return r.stderr


def run_normalize(inp, out, *, maxgain, target_lufs, true_peak, lra, two_pass, out_fmt) -> None:
    measured = None
    if two_pass:
        af_measure = normalize_af(maxgain, target_lufs, true_peak, lra) + ":print_format=json"
        stderr = _run(["-i", inp, "-af", af_measure, "-f", "null", "-"])
        measured = json.loads(stderr[stderr.rfind("{"): stderr.rfind("}") + 1])
    af = normalize_af(maxgain, target_lufs, true_peak, lra, measured=measured)
    _run(["-i", inp, "-af", af, "-ar", "44100", *output_args(out_fmt), out])


def run_silence(inp, out, *, threshold_db, min_pause_s, keep_silence_s, out_fmt) -> None:
    _run(["-i", inp, "-af", silence_af(threshold_db, min_pause_s, keep_silence_s),
          *output_args(out_fmt), out])


def run_convert(inp, out, *, out_fmt) -> None:
    _run(["-i", inp, *output_args(out_fmt), out])


def run_split(inp, out_dir, stem, *, segment_seconds, out_fmt) -> list[str]:
    ext = ext_for(out_fmt)
    pattern = os.path.join(out_dir, f"{stem}-%03d.{ext}")
    _run(["-i", inp, "-f", "segment", "-segment_time", str(int(segment_seconds)),
          *output_args(out_fmt), pattern])
    return sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir)
        if f.startswith(f"{stem}-") and f.endswith(f".{ext}")
    )


def run_concat(inputs: list[str], out, *, out_fmt, work_dir) -> None:
    # Concat via demuxer su intermedi wav (senza perdita), poi codifica nel formato scelto.
    wavs = []
    for i, src in enumerate(inputs):
        w = os.path.join(work_dir, f"part-{i:03d}.wav")
        _run(["-i", src, "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", w])
        wavs.append(w)
    listfile = os.path.join(work_dir, "concat.txt")
    with open(listfile, "w") as fh:
        fh.write("".join(f"file '{w}'\n" for w in wavs))
    _run(["-f", "concat", "-safe", "0", "-i", listfile, *output_args(out_fmt), out])


# ── Analisi (misura, non modifica) ──────────────────────────────────────────────

def _search_last(pattern, text, default=None):
    m = re.findall(pattern, text)
    return float(m[-1]) if m else default


def _parse_silences(stderr) -> list[tuple[float, float]]:
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?\d+\.?\d*)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?\d+\.?\d*)", stderr)]
    return list(zip(starts, ends))


# dB "molto basso" per il silenzio digitale puro (astats stampa "-inf"): evita None nel contratto.
_SILENCE_FLOOR_DB = -120.0


def _overall_rms(inp, ss=None, t=None):
    pre = (["-ss", str(ss)] if ss is not None else []) + (["-t", str(t)] if t is not None else [])
    stderr = _run([*pre, "-i", inp, "-af", "astats=metadata=1:reset=0", "-f", "null", "-"])
    m = re.findall(r"RMS level dB:\s*(-?inf|-?\d+\.?\d*)", stderr)
    if not m:
        return None
    val = m[-1]
    return _SILENCE_FLOOR_DB if "inf" in val else float(val)


def analyze(inp, *, silence_thresholds) -> dict:
    """Misura EBU R128 + rumore di fondo + distribuzione dei silenzi. Non modifica nulla."""
    eb = _run(["-i", inp, "-af", "ebur128=peak=true", "-f", "null", "-"])
    integrated = _search_last(r"I:\s*(-?\d+\.?\d*)\s*LUFS", eb)
    lra = _search_last(r"LRA:\s*(-?\d+\.?\d*)\s*LU", eb)
    true_peak = _search_last(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", eb)

    silences = []
    lowest_regions: list[tuple[float, float]] = []
    lowest_thr = min(silence_thresholds) if silence_thresholds else None
    for thr in silence_thresholds:
        ev = _run(["-i", inp, "-af", f"silencedetect=noise={_num(thr)}dB:d=0.3", "-f", "null", "-"])
        regions = _parse_silences(ev)
        durs = [round(e - s, 3) for s, e in regions if e > s]
        silences.append({
            "threshold_db": thr, "count": len(durs),
            "total_s": round(sum(durs), 3), "durations_s": durs,
        })
        if thr == lowest_thr:
            lowest_regions = [(s, e) for s, e in regions if e > s]

    # rumore di fondo: RMS del silenzio piu' lungo (soglia piu' bassa); altrimenti RMS complessivo.
    if lowest_regions:
        s, e = max(lowest_regions, key=lambda r: r[1] - r[0])
        noise_floor = _overall_rms(inp, ss=s, t=max(0.05, e - s))
    else:
        noise_floor = _overall_rms(inp)

    return {
        "integrated_lufs": integrated,
        "true_peak_dbtp": true_peak,
        "loudness_range_lu": lra,
        "noise_floor_lufs": noise_floor,
        "silences": silences,
    }
