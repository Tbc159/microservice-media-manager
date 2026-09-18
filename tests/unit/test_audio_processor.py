"""Unit test dei command-builder ffmpeg (puri, senza eseguire ffmpeg).

Bloccano le regressioni sui parametri misurati: se qualcuno riabbassa `maxgain`, toglie
l'unita' `dB` alla soglia, o toglie il taglio del silenzio iniziale, il test fallisce.
"""
from src.domains.audio.processors import ffmpeg_processor as fp


def test_normalize_af_uses_maxgain_and_loudnorm():
    af = fp.normalize_af(80, -16, -1.5, 11)
    assert "dynaudnorm=f=250:g=11:m=80" in af
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in af
    assert "measured_I" not in af  # 1 passata


def test_normalize_af_two_pass_injects_measured():
    measured = {"input_i": "-20", "input_tp": "-3", "input_lra": "5", "input_thresh": "-30"}
    af = fp.normalize_af(80, -16, -1.5, 11, measured=measured)
    assert "measured_I=-20" in af and "linear=true" in af


def test_silence_af_has_leading_trim_and_db_unit_and_keep():
    af = fp.silence_af(-40, 1.0, 0.3)
    # taglio del silenzio INIZIALE (nuovo requisito) + soglia con unita' dB + pausa lasciata
    assert "start_periods=1" in af and "start_silence=0.3" in af
    assert "stop_periods=-1" in af and "stop_silence=0.3" in af
    assert "threshold=-40dB" in af  # unita' dB, non ampiezza lineare
    assert "stop_duration=1" in af


def test_output_args_and_ext():
    assert fp.ext_for("audio/mpeg") == "mp3"
    assert fp.ext_for("audio/wav") == "wav"
    assert fp.ext_for("audio/m4a") == "m4a"
    assert "libmp3lame" in fp.output_args("audio/mpeg")
    assert "pcm_s16le" in fp.output_args("audio/wav")


def test_supported_sets():
    assert fp.is_supported_output("audio/mpeg")
    assert not fp.is_supported_output("image/png")
    assert "audio/wav" in fp.INPUT_AUDIO_TYPES  # i wav sono input validi
    assert fp.OUTPUT_FORMATS == {"audio/mpeg", "audio/m4a", "audio/wav"}


# ── mp3 pronto per i lettori: CBR + ID3v2.3 ─────────────────────────────────────

def test_mp3_is_cbr_never_vbr():
    """Molti lettori stimano la durata dal bitrate del primo frame: con un VBR la barra di
    avanzamento sbaglia. Quindi `-b:a`, mai `-q:a`."""
    args = fp.output_args("audio/mpeg")
    assert "-q:a" not in args
    assert args[args.index("-b:a") + 1] == "128k"


def test_bitrate_is_a_parameter_clamped_to_64_320():
    assert fp.output_args("audio/mpeg", 192)[-1] == "192k"
    assert fp.output_args("audio/m4a", 96)[-1] == "96k"
    assert fp.clamp_bitrate(None) == 128
    assert fp.clamp_bitrate(32) == 64 and fp.clamp_bitrate(999) == 320
    assert fp.clamp_bitrate("abc") == 128
    assert "-b:a" not in fp.output_args("audio/wav", 128)      # lossless: ignorato


def test_id3_args_write_only_present_fields_as_v23():
    args = fp.id3_args(title="Puntata 42", artist="Radio", album="Radio", duration_ms=3000,
                       with_cover=True)
    assert args[args.index("-id3v2_version") + 1] == "3"      # v2.3, non v2.4
    assert "-metadata" in args and "title=Puntata 42" in args
    assert "artist=Radio" in args and "album=Radio" in args and "TLEN=3000" in args
    assert "attached_pic" in args and "1:v" in args
    assert args[args.index("-c") + 1] == "copy"               # nessuna ricodifica


def test_id3_args_omit_missing_fields_no_unknown():
    args = fp.id3_args(title=None, artist=None, album=None, duration_ms=None, with_cover=False)
    assert not any(a.startswith(("title=", "artist=", "album=", "TLEN=")) for a in args)
    assert "attached_pic" not in args
    assert "Unknown" not in " ".join(args)
