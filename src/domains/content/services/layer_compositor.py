"""Layer-based image compositor shared by every layered generator (`composita`, presets).

Pure Pillow, framework- and network-agnostic: it receives layers whose asset references have
already been resolved to bytes by the caller (the service), and composes them onto a canvas
whose size is a parameter (default 1920x1080, HD 16:9). Position and size accept keyword /
percentage (free-space) / pixel forms. Returns ``(image_bytes, warnings)``.

Layer dicts (as produced by ImageService or by a preset):
  background: {type, image_bytes|None, fit, fallback_color, overlay}
  person/image: {type, image_bytes, x, y, size, opacity, mask}
  text: {type, content, font_bytes|None, font_size, color, align, x, y, max_width, stroke, box}
"""
import io
import logging
import os
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.domains.content.services.copertina_renderer import FONT_EXTRABOLD, FONTS_DIR

logger = logging.getLogger("content")

# Canvas HD standard YouTube: default, non piu' un vincolo (i preset ne usano altri).
DEFAULT_CANVAS: Tuple[int, int] = (1920, 1080)

_OUTPUT = {
    "image/png": ("PNG", {}),
    "image/jpeg": ("JPEG", {"quality": 90}),
    "image/webp": ("WEBP", {"quality": 90}),
}

_X_KEYWORDS = {"left": 0.0, "center": 0.5, "right": 1.0}
_Y_KEYWORDS = {"top": 0.0, "center": 0.5, "bottom": 1.0}

# Sovracampionamento della maschera circolare: bordo antialiasato senza filtri.
_MASK_SS = 4


def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _resolve_axis(spec: Optional[str], layer_size: int, canvas_size: int, keywords: dict) -> int:
    """Top-left coordinate (px) of the layer along one axis.

    keyword/percent map the layer within the *free space* (canvas - layer): 0%/start = flush,
    100%/end = flush opposite, 50%/center = centered. Pixel = absolute top-left.
    """
    spec = (spec or "center").strip().lower()
    free = canvas_size - layer_size
    if spec in keywords:
        return round(free * keywords[spec])
    if spec.endswith("%"):
        pct = max(0.0, min(100.0, float(spec[:-1]))) / 100.0
        return round(free * pct)
    return int(spec[:-2] if spec.endswith("px") else spec)


def _dim(spec: Optional[str], canvas_dim: int) -> Optional[int]:
    if not spec:
        return None
    spec = spec.strip().lower()
    if spec.endswith("%"):
        return round(canvas_dim * float(spec[:-1]) / 100.0)
    return int(spec[:-2] if spec.endswith("px") else spec)


def _resolve_size(
    size_spec: Optional[dict], natural: Tuple[int, int], canvas: Tuple[int, int] = DEFAULT_CANVAS
) -> Tuple[int, int]:
    """Target (width, height) in px. One dimension → aspect preserved; none → natural, clamped."""
    nat_w, nat_h = natural
    cw, ch = canvas
    spec = size_spec or {}
    w = _dim(spec.get("width"), cw)
    h = _dim(spec.get("height"), ch)
    if w and not h:
        h = round(nat_h * (w / nat_w))
    elif h and not w:
        w = round(nat_w * (h / nat_h))
    elif not w and not h:
        scale = min(1.0, cw / nat_w, ch / nat_h)  # clamp into canvas, never upscale
        w, h = round(nat_w * scale), round(nat_h * scale)
    return max(1, w), max(1, h)


def _circle_side(size_spec: Optional[dict], natural: Tuple[int, int],
                 canvas: Tuple[int, int]) -> int:
    """Diametro del cerchio: la dimensione richiesta (se date entrambe, la minore)."""
    spec = size_spec or {}
    dims = [d for d in (_dim(spec.get("width"), canvas[0]), _dim(spec.get("height"), canvas[1])) if d]
    return max(1, min(dims) if dims else min(*natural, *canvas))


def _fit(img: Image.Image, mode: str, canvas: Tuple[int, int]) -> Image.Image:
    cw, ch = canvas
    iw, ih = img.size
    if mode == "stretch":
        return img.resize((cw, ch), Image.LANCZOS)
    scale = max(cw / iw, ch / ih) if mode == "cover" else min(cw / iw, ch / ih)
    img = img.resize((round(iw * scale), round(ih * scale)), Image.LANCZOS)
    if mode == "cover":
        left, top = (img.width - cw) // 2, (img.height - ch) // 2
        img = img.crop((left, top, left + cw, top + ch))
    return img


def _apply_opacity(img: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 1:
        return img
    alpha = img.getchannel("A").point(lambda a: int(a * opacity))
    img.putalpha(alpha)
    return img


def _circle(img: Image.Image, side: int) -> Image.Image:
    """Ritaglio circolare di diametro `side`: cover-fit nel quadrato + alfa a ellisse.

    Il diametro e' quello **richiesto**, non quello che risulta dalle proporzioni della
    sorgente: un logo largo e uno quadrato producono lo stesso cerchio, senza deformarli
    (l'immagine viene riempita a `cover` e ritagliata al centro). Bordo antialiasato via
    sovracampionamento.
    """
    img = _fit(img, "cover", (side, side))
    mask = Image.new("L", (side * _MASK_SS, side * _MASK_SS), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, side * _MASK_SS - 1, side * _MASK_SS - 1], fill=255)
    mask = mask.resize((side, side), Image.LANCZOS)
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (side, side), 0), mask))
    return img


def _composite_over(canvas: Image.Image, element: Image.Image, pos: Tuple[int, int]) -> Image.Image:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(element, pos, element)
    return Image.alpha_composite(canvas, layer)


def _load_font(font_bytes: Optional[bytes], size: int, warnings: List[str]):
    """Custom font (bytes) → bundled Montserrat → Pillow default. Each fallback warns."""
    if font_bytes is not None:
        try:
            return ImageFont.truetype(io.BytesIO(font_bytes), size)
        except OSError:
            warnings.append("font del layer testo non valido: usato il font predefinito")
    try:
        return ImageFont.truetype(os.path.join(FONTS_DIR, FONT_EXTRABOLD), size)
    except OSError:
        warnings.append(f"font '{FONT_EXTRABOLD}' non trovato: usato il default Pillow")
        return ImageFont.load_default(size)


def _render_background(canvas: Image.Image, layer: dict) -> Image.Image:
    cw, ch = canvas.size
    canvas.paste(_hex_to_rgb(layer.get("fallback_color", "#111111")) + (255,), [0, 0, cw, ch])
    data = layer.get("image_bytes")
    if data is not None:
        bg = _fit(Image.open(io.BytesIO(data)).convert("RGBA"), layer.get("fit", "cover"),
                  canvas.size)
        canvas = _composite_over(canvas, bg, ((cw - bg.width) // 2, (ch - bg.height) // 2))
    return _apply_overlay(canvas, layer.get("overlay"))


def _apply_overlay(canvas: Image.Image, overlay: Optional[dict]) -> Image.Image:
    """Velo a tinta unita sopra lo sfondo: rende leggibile il testo su foto complesse."""
    if not overlay:
        return canvas
    alpha = int(255 * overlay.get("opacity", 0.45))
    veil = Image.new("RGBA", canvas.size, _hex_to_rgb(overlay.get("color", "#000000")) + (alpha,))
    return Image.alpha_composite(canvas, veil)


def _render_image(canvas: Image.Image, layer: dict) -> Image.Image:
    cw, ch = canvas.size
    img = Image.open(io.BytesIO(layer["image_bytes"])).convert("RGBA")
    if layer.get("mask") == "circle":
        w = h = _circle_side(layer.get("size"), img.size, canvas.size)
        img = _circle(img, w)
    else:
        w, h = _resolve_size(layer.get("size"), img.size, canvas.size)
        img = img.resize((w, h), Image.LANCZOS)
    img = _apply_opacity(img, layer.get("opacity", 1))
    x = _resolve_axis(layer.get("x"), w, cw, _X_KEYWORDS)
    y = _resolve_axis(layer.get("y"), h, ch, _Y_KEYWORDS)
    return _composite_over(canvas, img, (x, y))


def _draw_lines(draw, lines, widths, block_w, bx, by, line_h, align, font, fill, stroke_w, stroke_fill):
    for i, line in enumerate(lines):
        offset = {"center": (block_w - widths[i]) // 2, "right": block_w - widths[i]}.get(align, 0)
        draw.text(
            (bx + offset, by + i * line_h),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_w,
            stroke_fill=stroke_fill,
        )


def _build_shadow(shadow, lines, widths, block_w, bx, by, line_h, align, font, stroke_w,
                  canvas_size) -> Image.Image:
    """Ombra/glow del testo: silhouette piena nel colore ombra, sfocata e con opacita'."""
    color = _hex_to_rgb(shadow.get("color", "#000000"))
    off = shadow.get("offset") or {}
    img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    _draw_lines(
        ImageDraw.Draw(img), lines, widths, block_w,
        bx + off.get("x", 4), by + off.get("y", 4), line_h, align, font, color, stroke_w, color,
    )
    blur = shadow.get("blur", 0)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return _apply_opacity(img, shadow.get("opacity", 1))


def _render_text(canvas: Image.Image, layer: dict, warnings: List[str]) -> Image.Image:
    cw, ch = canvas.size
    font = _load_font(layer.get("font_bytes"), layer.get("font_size", 72), warnings)
    color = _hex_to_rgb(layer.get("color", "#ffffff"))
    align = layer.get("align", "left")
    stroke = layer.get("stroke") or {}
    stroke_w = stroke.get("width", 0) or 0
    stroke_fill = _hex_to_rgb(stroke.get("color", "#000000")) if stroke_w else None

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    lines = _wrap(layer["content"], font, layer.get("max_width"), odraw, stroke_w)
    widths = [_line_width(odraw, ln, font, stroke_w) for ln in lines]
    block_w = max(widths) if widths else 0
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + stroke_w * 2
    block_h = line_h * len(lines)

    bx = _resolve_axis(layer.get("x"), block_w, cw, _X_KEYWORDS)
    by = _resolve_axis(layer.get("y"), block_h, ch, _Y_KEYWORDS)

    box = layer.get("box")
    if box:
        pad = box.get("padding", 16)
        r, g, b = _hex_to_rgb(box["color"])
        alpha = int(255 * box.get("opacity", 1))
        odraw.rounded_rectangle(
            [bx - pad, by - pad, bx + block_w + pad, by + block_h + pad],
            radius=box.get("radius", 0),
            fill=(r, g, b, alpha),
        )

    # Ombra/glow: sotto al testo, sopra l'eventuale box.
    shadow = layer.get("shadow")
    if shadow:
        overlay = Image.alpha_composite(
            overlay,
            _build_shadow(shadow, lines, widths, block_w, bx, by, line_h, align, font, stroke_w,
                          canvas.size),
        )
        odraw = ImageDraw.Draw(overlay)

    _draw_lines(odraw, lines, widths, block_w, bx, by, line_h, align, font, color, stroke_w, stroke_fill)
    return Image.alpha_composite(canvas, overlay)


def _line_width(draw: ImageDraw.ImageDraw, text: str, font, stroke_w: int) -> int:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    return bbox[2] - bbox[0]


def _wrap(content: str, font, max_width: Optional[int], draw: ImageDraw.ImageDraw, stroke_w: int) -> List[str]:
    """Split on explicit \\n; if max_width is set, wrap each paragraph on word boundaries."""
    paragraphs = content.split("\n")
    if not max_width:
        return paragraphs
    out: List[str] = []
    for para in paragraphs:
        words = para.split(" ")
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if line and _line_width(draw, candidate, font, stroke_w) > max_width:
                out.append(line)
                line = word
            else:
                line = candidate
        out.append(line)
    return out


_RENDERERS = {
    "background": lambda c, layer, w: _render_background(c, layer),
    "person": lambda c, layer, w: _render_image(c, layer),
    "image": lambda c, layer, w: _render_image(c, layer),
    "text": _render_text,
}


def render_composita(
    layers: List[dict], *, formato: str = "image/png", canvas: Tuple[int, int] = DEFAULT_CANVAS
) -> "Tuple[bytes, List[str]]":
    """Compose the resolved layers onto a `canvas`-sized image; returns (bytes, warnings)."""
    warnings: List[str] = []
    image = Image.new("RGBA", canvas, (0, 0, 0, 0))
    for layer in layers:
        renderer = _RENDERERS[layer["type"]]
        image = renderer(image, layer, warnings)

    pil_format, kwargs = _OUTPUT[formato]
    out = image.convert("RGB") if pil_format == "JPEG" else image
    buf = io.BytesIO()
    out.save(buf, pil_format, **kwargs)
    logger.info("Immagine composta: %sx%s, layer=%s, formato=%s, warnings=%s",
                canvas[0], canvas[1], len(layers), formato, len(warnings))
    return buf.getvalue(), warnings
