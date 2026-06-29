"""Renderer della copertina (immagine 2560x1440) — Pillow puro, niente framework ne' rete.

Portato da microservices-media (ytmedia/processors/slide_processor.py) e adattato al
modello contract-first: invece di risolvere gli asset da un registro su FS, riceve i
**byte** gia' recuperati (logo host e avatar ospiti). Gli avatar mancanti arrivano come
None e vengono resi con un placeholder. L'output e' nel formato richiesto (png/jpeg/webp).
"""
import io
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("content")

# Canvas 2K (scala 4/3 rispetto all'originale 1920x1080)
W, H = 2560, 1440
SCALE = W / 1920  # 1.3333…

MARGIN = round(70 * SCALE)
LOGO_TOP_SIZE = round(200 * SCALE)
AVATAR_SIZE = round(220 * SCALE)
LOGO_TOP_Y = round(50 * SCALE)

FONT_BRAND_SIZE = round(90 * SCALE)
FONT_TESTO_SIZE = round(90 * SCALE)
FONT_EXTRABOLD = "Montserrat-ExtraBold.ttf"
FONT_LIGHT = "Montserrat-Light.ttf"

# I font Montserrat NON sono versionati: vanno messi in FONTS_DIR (vedi fonts/README.md).
# Se mancano, si degrada al font di default di Pillow (output funzionante, meno curato).
FONTS_DIR = os.getenv("FONTS_DIR", str(Path(__file__).resolve().parent.parent / "fonts"))

# formato MIME -> (formato Pillow, estensione, kwargs di save)
_OUTPUT = {
    "image/png": ("PNG", "png", {"dpi": (150, 150)}),
    "image/jpeg": ("JPEG", "jpg", {"quality": 90}),
    "image/webp": ("WEBP", "webp", {"quality": 90}),
}


def ext_for(formato: str) -> str:
    """Estensione file per il MIME type di output."""
    return _OUTPUT[formato][1]


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _make_background(tipo: str, colore_sfondo: str, colore_sfumato: Optional[str]) -> Image.Image:
    img = Image.new("RGB", (W, H))
    if tipo == "unicolor":
        img.paste(_hex_to_rgb(colore_sfondo), [0, 0, W, H])
        return img
    c_top = _hex_to_rgb(colore_sfumato if tipo == "sfumato-up" else colore_sfondo)
    c_bot = _hex_to_rgb(colore_sfondo if tipo == "sfumato-up" else colore_sfumato)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        r = int(c_top[0] + (c_bot[0] - c_top[0]) * t)
        g = int(c_top[1] + (c_bot[1] - c_top[1]) * t)
        b = int(c_top[2] + (c_bot[2] - c_top[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img


def _resolve_font(
    custom_bytes: Optional[bytes],
    default_name: str,
    size: int,
    role: str,
    warnings: List[str],
):
    """Risolve il font per un ruolo. Priorità: font personalizzato (byte) → Montserrat bundle
    → default Pillow. Ogni fallback aggiunge un warning non bloccante (e logga)."""
    if custom_bytes is not None:
        try:
            return ImageFont.truetype(io.BytesIO(custom_bytes), size)
        except OSError:
            warnings.append(f"font per il {role} non valido: usato il font predefinito")
            logger.warning("Font personalizzato per %s non valido: fallback", role)
    try:
        return ImageFont.truetype(os.path.join(FONTS_DIR, default_name), size)
    except OSError:
        warnings.append(f"font '{default_name}' ({role}) non trovato: usato il default Pillow")
        logger.warning("Font %s non trovato in %s: default Pillow", default_name, FONTS_DIR)
        return ImageFont.load_default(size)


def _resize_to_max(img: Image.Image, max_px: int) -> Image.Image:
    """Ridimensiona proporzionalmente se la dimensione dominante supera max_px.
    Foto verticali (h > w): usa l'altezza; orizzontali/quadrate: la larghezza."""
    w, h = img.size
    dominant = h if h > w else w
    if dominant <= max_px:
        return img
    scale = max_px / dominant
    return img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)


def _placeholder_avatar() -> Image.Image:
    av = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(av)
    d.ellipse(
        [0, 0, AVATAR_SIZE - 1, AVATAR_SIZE - 1],
        outline=(255, 255, 255, 200),
        width=round(4 * SCALE),
    )
    mid, q = AVATAR_SIZE // 2, AVATAR_SIZE // 4
    d.line([(q, mid), (3 * q, mid)], fill=(255, 255, 255, 200), width=round(3 * SCALE))
    d.line([(mid, q), (mid, 3 * q)], fill=(255, 255, 255, 200), width=round(3 * SCALE))
    return av


def render_copertina(
    *,
    titolo: str,
    testo_centrale: str,
    colore_sfondo: str,
    tipo_sfondo: str,
    colore_sfumato: Optional[str],
    logo_bytes: bytes,
    ospiti_bytes: List[Optional[bytes]],
    formato: str = "image/png",
    font_titolo_bytes: Optional[bytes] = None,
    font_testo_bytes: Optional[bytes] = None,
) -> "tuple[bytes, List[str]]":
    """Genera la copertina; restituisce (byte_immagine, warnings).

    `logo_bytes` e' obbligatorio (gia' recuperato dal chiamante). Ogni elemento di
    `ospiti_bytes` puo' essere None -> avatar placeholder. `font_titolo_bytes`/`font_testo_bytes`
    sono i font personalizzati (byte) o None -> Montserrat bundle. I fallback finiscono in
    `warnings` (la generazione non fallisce mai per un font).
    """
    warnings: List[str] = []
    img = _make_background(tipo_sfondo, colore_sfondo, colore_sfumato)
    draw = ImageDraw.Draw(img)

    # Header: logo + titolo (in alto a sinistra)
    logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
    logo.thumbnail((LOGO_TOP_SIZE, LOGO_TOP_SIZE), Image.LANCZOS)
    img.paste(logo, (MARGIN, LOGO_TOP_Y), logo)
    max_guest_px = round(logo.width * 1.05)

    font_brand = _resolve_font(font_titolo_bytes, FONT_EXTRABOLD, FONT_BRAND_SIZE, "titolo", warnings)
    brand_lines = [ln.strip() for ln in titolo.split("\n")]
    line_h = draw.textbbox((0, 0), "A", font=font_brand)[3] + round(8 * SCALE)
    brand_h = len(brand_lines) * line_h
    brand_y = LOGO_TOP_Y + (logo.height - brand_h) // 2
    text_x = MARGIN + logo.width + round(40 * SCALE)
    for i, line in enumerate(brand_lines):
        draw.text((text_x, brand_y + i * line_h), line, fill=(255, 255, 255), font=font_brand)

    # Testo centrale
    header_bottom = LOGO_TOP_Y + max(logo.height, brand_h) + round(60 * SCALE)
    font_testo = _resolve_font(font_testo_bytes, FONT_LIGHT, FONT_TESTO_SIZE, "testo", warnings)
    testo_lines = [ln.strip() for ln in testo_centrale.split("\n")]
    tline_h = draw.textbbox((0, 0), "A", font=font_testo)[3] + round(16 * SCALE)

    has_avatars = bool(ospiti_bytes)
    footer_h = AVATAR_SIZE + round(80 * SCALE) if has_avatars else 0
    avail_bot = H - footer_h - round(40 * SCALE)
    total_testo = len(testo_lines) * tline_h
    testo_y = header_bottom + (avail_bot - header_bottom - total_testo) // 2
    for i, line in enumerate(testo_lines):
        bbox = draw.textbbox((0, 0), line, font=font_testo)
        lw = bbox[2] - bbox[0]
        draw.text(((W - lw) // 2, testo_y + i * tline_h), line, fill=(255, 255, 255), font=font_testo)

    # Footer: avatar ospiti (1–5, spaziatura dinamica)
    if ospiti_bytes:
        avatars = []
        for raw in ospiti_bytes:
            if raw is None:
                avatars.append(_placeholder_avatar())
                continue
            av = Image.open(io.BytesIO(raw)).convert("RGBA")
            avatars.append(_resize_to_max(av, min(AVATAR_SIZE, max_guest_px)))

        total_av_w = sum(av.width for av in avatars)
        usable_w = W - 2 * MARGIN
        gap = (usable_w - total_av_w) // (len(avatars) + 1)
        bot_y = H - AVATAR_SIZE - round(60 * SCALE)
        x = MARGIN + gap
        for av in avatars:
            img.paste(av, (x, bot_y), av)
            x += av.width + gap

    # Output nel formato richiesto
    pil_format, _ext, save_kwargs = _OUTPUT[formato]
    out = img if pil_format != "JPEG" else img.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, pil_format, **save_kwargs)
    logger.info("Copertina generata: %sx%s, sfondo=%s, ospiti=%s, formato=%s, warnings=%s",
                W, H, tipo_sfondo, len(ospiti_bytes), formato, len(warnings))
    return buf.getvalue(), warnings
