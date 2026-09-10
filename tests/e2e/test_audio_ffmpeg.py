"""Test e2e del dominio audio con **ffmpeg reale** (binario statico imageio-ffmpeg).

Coprono i punti di "come si verifica" del prompt:
  1. normalize allinea i due parlanti (< 1 LU) e porta il file a -16 LUFS ±0.5;
  2. due `silence` di fila con soglie diverse sulla stessa sorgente, senza ricaricarla
     (l'input non viene distrutto);
  3. `normalize` poi `silence` e `silence` poi `normalize`: entrambi gli ordini completano;
  4. un m4a e un wav attraversano `silence` senza conversioni preliminari a carico del chiamante.
La persistenza al riavvio (5) e' nel test del job store.
"""
import re
import subprocess
import tempfile

import pytest

imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
FF = imageio_ffmpeg.get_ffmpeg_exe()

from src.domains.audio.gateway import UploadResult  # noqa: E402
from src.domains.audio.repositories.job_store import JobStore  # noqa: E402
from src.domains.audio.services.audio_service import AudioService  # noqa: E402
from src.domains.audio.worker import Worker  # noqa: E402


@pytest.fixture(autouse=True)
def _ffmpeg_bin(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN", FF)


def _ff(args):
    r = subprocess.run([FF, "-hide_banner", "-y", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    return r.stderr


def _lufs(path, ss=None, t=None):
    pre = (["-ss", str(ss)] if ss is not None else []) + (["-t", str(t)] if t is not None else [])
    r = subprocess.run([FF, "-hide_banner", *pre, "-i", path, "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"I:\s*(-?\d+\.?\d*)\s*LUFS", r.stderr)
    return float(m[-1]) if m else None


def _two_speaker_wav(d):
    """A a -12 dBFS, B a -30 dBFS, turni 6s, pause 2s (stesso contenuto -> misura solo il livello)."""
    _ff(["-f", "lavfi", "-i", "anoisesrc=color=pink:seed=1:duration=6", "-af", "volume=-12dB",
         "-ar", "44100", "-ac", "1", f"{d}/A.wav"])
    _ff(["-f", "lavfi", "-i", "anoisesrc=color=pink:seed=1:duration=6", "-af", "volume=-30dB",
         "-ar", "44100", "-ac", "1", f"{d}/B.wav"])
    _ff(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "2", "-ar", "44100", "-ac", "1", f"{d}/s.wav"])
    order = []
    for _ in range(4):
        order += [f"{d}/A.wav", f"{d}/s.wav", f"{d}/B.wav", f"{d}/s.wav"]
    with open(f"{d}/list.txt", "w") as fh:
        fh.write("".join(f"file '{p}'\n" for p in order))
    _ff(["-f", "concat", "-safe", "0", "-i", f"{d}/list.txt", "-c", "copy", f"{d}/two.wav"])
    return open(f"{d}/two.wav", "rb").read()


# ── 1) normalize allinea i parlanti e porta a -16 LUFS ──────────────────────────

def test_normalize_aligns_speakers_and_hits_target():
    from src.domains.audio.processors import ffmpeg_processor as fp
    with tempfile.TemporaryDirectory() as d:
        src = f"{d}/two.wav"
        with open(src, "wb") as fh:
            fh.write(_two_speaker_wav(d))
        assert abs(_lufs(src, 0, 6) - _lufs(src, 8, 6)) > 10  # sorgente disallineata (~18 LU)
        out = f"{d}/norm.mp3"
        fp.run_normalize(src, out, maxgain=80, target_lufs=-16, true_peak=-1.5, lra=11,
                         two_pass=False, out_fmt="audio/mpeg")
        spread = abs(_lufs(out, 0, 6) - _lufs(out, 8, 6))
        assert spread < 1.0, f"scarto {spread} LU (atteso <1)"
        assert abs(_lufs(out) - (-16)) <= 0.5, f"file {_lufs(out)} LUFS (atteso -16±0.5)"


# ── worker end-to-end (chaining via gateway in memoria) ─────────────────────────

class _MemGateway:
    def __init__(self):
        self.media = {}
        self._n = 0

    def add(self, filename, media_type, data):
        self._n += 1
        self.media[self._n] = {"id": self._n, "filename": filename, "media_type": media_type, "data": data}
        return self._n

    def get_by_id(self, i):
        m = self.media.get(i)
        return {k: m[k] for k in ("id", "filename", "media_type")} if m else None

    def resolve_filename(self, f):
        for m in self.media.values():
            if m["filename"] == f or m["filename"].rsplit(".", 1)[0] == f:
                return {k: m[k] for k in ("id", "filename", "media_type")}
        return None

    def get_bytes(self, i):
        m = self.media.get(i)
        return m["data"] if m else None

    def upload_media(self, *, title, media_type, filename, data, duration_s=None):
        nid = self.add(filename, media_type, data)
        return UploadResult(201, {"id": nid, "media_type": media_type, "filename": filename, "created_at_s": 1})


def _run(svc, worker, accepted):
    worker.run_once()
    return svc.get_job(accepted["job_id"])


@pytest.fixture()
def stack(tmp_path):
    gw = _MemGateway()
    store = JobStore(str(tmp_path / "audio.db"))
    return gw, AudioService(gw, store), Worker(gw, store)


# ── 2) due silence con soglie diverse, senza ricaricare; input non distrutto ────

def test_two_silences_same_source_without_reload(stack, tmp_path):
    gw, svc, worker = stack
    with tempfile.TemporaryDirectory() as d:
        sid = gw.add("ep.wav", "audio/wav", _two_speaker_wav(d))
    original = gw.media[sid]["data"]
    j1 = _run(svc, worker, svc.silence({"source": sid, "threshold_db": -40}))
    j2 = _run(svc, worker, svc.silence({"source": sid, "threshold_db": -30}))
    assert j1["status"] == "succeeded" and j2["status"] == "succeeded"
    assert gw.media[sid]["data"] == original          # ingresso NON distrutto
    assert j1["result"]["media"][0]["id"] != j2["result"]["media"][0]["id"]  # due output distinti


# ── 3) ordine libero: normalize->silence e silence->normalize completano ────────

def test_order_independence(stack, tmp_path):
    gw, svc, worker = stack
    with tempfile.TemporaryDirectory() as d:
        sid = gw.add("ep.wav", "audio/wav", _two_speaker_wav(d))
    # normalize -> silence
    jn = _run(svc, worker, svc.normalize({"source": sid, "format": "audio/wav"}))
    assert jn["status"] == "succeeded"
    out1 = jn["result"]["media"][0]["id"]
    js = _run(svc, worker, svc.silence({"source": out1}))
    assert js["status"] == "succeeded"
    # silence -> normalize
    js2 = _run(svc, worker, svc.silence({"source": sid}))
    out2 = js2["result"]["media"][0]["id"]
    jn2 = _run(svc, worker, svc.normalize({"source": out2, "format": "audio/mpeg"}))
    assert jn2["status"] == "succeeded"


# ── 4) m4a e wav attraversano silence senza conversioni a carico del client ─────

def test_silence_accepts_m4a_and_wav(stack, tmp_path):
    gw, svc, worker = stack
    with tempfile.TemporaryDirectory() as d:
        wav = _two_speaker_wav(d)
        _ff(["-i", f"{d}/two.wav", "-c:a", "aac", "-b:a", "192k", f"{d}/two.m4a"])
        m4a = open(f"{d}/two.m4a", "rb").read()
    wid = gw.add("ep.wav", "audio/wav", wav)
    mid = gw.add("ep.m4a", "audio/m4a", m4a)
    jw = _run(svc, worker, svc.silence({"source": wid}))
    jm = _run(svc, worker, svc.silence({"source": mid}))
    assert jw["status"] == "succeeded", jw.get("error")
    assert jm["status"] == "succeeded", jm.get("error")


# ── analyze end-to-end + riuso della cache ──────────────────────────────────────

def test_analyze_and_cache_reuse(stack, tmp_path):
    gw, svc, worker = stack
    with tempfile.TemporaryDirectory() as d:
        sid = gw.add("ep.wav", "audio/wav", _two_speaker_wav(d))
    j = _run(svc, worker, svc.analyze({"source": sid, "silence_thresholds_db": [-30, -50]}))
    an = j["result"]["analysis"]
    assert an["media_id"] == sid
    assert an["integrated_lufs"] is not None and an["noise_floor_lufs"] is not None
    assert len(an["silences"]) == 2
